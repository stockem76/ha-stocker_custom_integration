"""Audit a Frigate face library and propose images to remove. Never deletes anything.

For every image under each face name (the "train" folder is skipped) it:
  * backs the file up to OUT/library-backup/<name>/<file>
  * measures size, sharpness and brightness
  * asks Frigate's own recogniser who it is (the crop is padded, because Frigate's
    detector cannot find a face in a tight crop)
  * finds near-duplicates within the same name (difference hash)

Proposed removals (OUT/audit/report.json, OUT/audit/sheet_<n>.jpg):
  tiny       shorter side < --min-side px
  blurry     Laplacian variance < --min-sharp
  confused   Frigate recognises it as a different name with score >= --confused-score
  duplicate  near-identical to a better image of the same name
Flagged for review only: unreadable (no face found) or recognised as unknown.

Usage: python audit_face_library.py --frigate http://HOST:5000 OUT
Apply removals later with: POST /api/faces/<name>/delete {"ids": [...]}
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import cv2
import numpy as np

PADS = (1.0, 0.75, 1.5)


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


def recognize(base: str, jpeg: bytes) -> dict:
    boundary = uuid.uuid4().hex
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="f.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        + jpeg
        + f"\r\n--{boundary}--\r\n".encode()
    )
    req = urllib.request.Request(
        f"{base}/api/faces/recognize",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def padded(img: np.ndarray, pad: float) -> bytes:
    p = int(max(img.shape[:2]) * pad)
    out = cv2.copyMakeBorder(img, p, p, p, p, cv2.BORDER_CONSTANT, value=(90, 90, 90))
    scale = max(1.0, 480 / out.shape[1])
    out = cv2.resize(out, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()


def frigate_opinion(base: str, img: np.ndarray, pause: float) -> tuple[str | None, float]:
    for pad in PADS:
        try:
            r = recognize(base, padded(img, pad))
        except OSError:
            r = {}
        time.sleep(pause)
        if r.get("success"):
            return r.get("face_name"), float(r.get("score") or 0)
    return None, 0.0


def dhash(img: np.ndarray) -> int:
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (9, 8), interpolation=cv2.INTER_AREA)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--frigate", required=True)
    ap.add_argument("--min-side", type=int, default=40)
    ap.add_argument("--min-sharp", type=float, default=25.0)
    ap.add_argument("--confused-score", type=float, default=0.75)
    ap.add_argument("--dup-bits", type=int, default=3)
    ap.add_argument("--pause", type=float, default=0.3)
    args = ap.parse_args()

    base = args.frigate.rstrip("/")
    faces = {k: v for k, v in get_json(f"{base}/api/faces").items() if k != "train"}
    backup = args.out / "library-backup"
    audit = args.out / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    results: dict[str, list[dict]] = {}

    for name, files in sorted(faces.items()):
        rows = []
        for fn in files:
            dest = backup / name / fn
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                q = f"{urllib.parse.quote(name)}/{urllib.parse.quote(fn)}"
                with urllib.request.urlopen(f"{base}/clips/faces/{q}", timeout=30) as resp:
                    dest.write_bytes(resp.read())
            img = cv2.imread(str(dest))
            if img is None:
                rows.append({"file": fn, "reasons": ["unreadable-file"]})
                continue
            h, w = img.shape[:2]
            gray = cv2.cvtColor(cv2.resize(img, (112, 112)), cv2.COLOR_BGR2GRAY)
            sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            seen_as, score = frigate_opinion(base, img, args.pause)
            reasons = []
            if min(h, w) < args.min_side:
                reasons.append("tiny")
            if sharp < args.min_sharp:
                reasons.append("blurry")
            if seen_as and seen_as not in (name, "unknown") and score >= args.confused_score:
                reasons.append(f"confused:{seen_as}")
            review = []
            if seen_as is None:
                review.append("no-face-found")
            elif seen_as == "unknown":
                review.append("unknown")
            rows.append(
                {
                    "file": fn,
                    "w": w,
                    "h": h,
                    "sharp": round(sharp),
                    "seen_as": seen_as,
                    "score": round(score, 2),
                    "hash": dhash(img),
                    "reasons": reasons,
                    "review": review,
                }
            )
        # Near-duplicates: keep the larger, sharper one.
        rows_ok = [r for r in rows if "hash" in r]
        rows_ok.sort(key=lambda r: (r["w"] * r["h"], r["sharp"]), reverse=True)
        kept: list[dict] = []
        for r in rows_ok:
            if any(bin(r["hash"] ^ k["hash"]).count("1") <= args.dup_bits for k in kept):
                r["reasons"].append("duplicate")
            elif not r["reasons"]:
                kept.append(r)
        results[name] = rows
        remove = sum(1 for r in rows if r["reasons"])
        print(f"{name:14} images={len(rows):3} remove={remove:3} keep={len(rows) - remove:3}")

    for rows in results.values():
        for r in rows:
            r.pop("hash", None)
    (audit / "report.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    make_sheets(backup, audit, results)


def make_sheets(backup: Path, audit: Path, results: dict[str, list[dict]]) -> None:
    tile, label_w, cols = 96, 200, 14
    rows = []
    for name, items in sorted(results.items()):
        flagged = [r for r in items if r["reasons"]]
        for i in range(0, len(flagged), cols):
            rows.append((name if i == 0 else "", flagged[i : i + cols], name))
    for old in audit.glob("sheet_*.jpg"):
        old.unlink()
    per_sheet = 10
    for s in range(0, len(rows), per_sheet):
        chunk = rows[s : s + per_sheet]
        sheet = np.full((len(chunk) * (tile + 22), label_w + cols * tile, 3), 30, np.uint8)
        for r, (label, items, name) in enumerate(chunk):
            y = r * (tile + 22)
            cv2.putText(
                sheet, label, (8, y + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2
            )
            for c, item in enumerate(items):
                im = cv2.imread(str(backup / name / item["file"]))
                if im is None:
                    continue
                x = label_w + c * tile
                sheet[y : y + tile, x : x + tile] = cv2.resize(im, (tile, tile))
                why = item["reasons"][0].replace("confused:", "=")[:13]
                cv2.putText(
                    sheet,
                    why,
                    (x + 2, y + tile + 15),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    (120, 200, 255),
                    1,
                )
        cv2.imwrite(
            str(audit / f"sheet_{s // per_sheet + 1}.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85]
        )


if __name__ == "__main__":
    main()

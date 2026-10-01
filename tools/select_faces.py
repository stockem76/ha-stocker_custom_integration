"""Pick good, varied face crops per person for Frigate's Face Library.

Input:  ROOT/raw/<person>/*.jpg (+ optional index.json mapping file -> "… – 22 Sept 2026, 08:14:05")
Output: ROOT/selected/<person>/*.jpg, ROOT/sheets/sheet_<n>.jpg, ROOT/report.json

Each folder is assumed to be mostly one person (e.g. a Google Photos face group)
but photos may contain other people. The person is found as the face identity
that recurs across the most photos (OpenCV YuNet detection + SFace embeddings).
Quality gates loosely follow ISO/IEC 29794-5 ideas: size, sharpness, pose,
illumination.

Usage: python select_faces.py ROOT --models DIR [--tiles DIR] [--merge T=a,b] [--exclude g]
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

SAME_PERSON = 0.40  # SFace cosine; OpenCV's published threshold is 0.363
MEMBER = 0.45
NEAR_DUPLICATE = 0.93
PER_DAY = 3


@dataclass
class Face:
    photo: str
    box: np.ndarray  # x, y, w, h
    raw: np.ndarray  # YuNet row (box, 5 landmarks, score)
    feat: np.ndarray
    quality: float
    metrics: dict = field(default_factory=dict)
    day: str = ""
    rank: int = 0  # photo order, 0 = newest


def load_models(models: Path):
    det = cv2.FaceDetectorYN.create(
        str(models / "face_detection_yunet_2023mar.onnx"), "", (320, 320), 0.8, 0.3, 50
    )
    rec = cv2.FaceRecognizerSF.create(str(models / "face_recognition_sface_2021dec.onnx"), "")
    return det, rec


def quality(img: np.ndarray, row: np.ndarray, aligned: np.ndarray) -> tuple[float, dict] | None:
    w = row[2]
    re_, le, nose = row[4:6], row[6:8], row[8:10]
    eye_dist = float(np.linalg.norm(le - re_))
    if w < 80 or eye_dist < 30:
        return None
    mid = (re_ + le) / 2
    yaw = abs(float(nose[0] - mid[0])) / eye_dist
    roll = abs(math.degrees(math.atan2(le[1] - re_[1], le[0] - re_[0])))
    roll = min(roll, 180 - roll)
    gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    bright = float(gray.mean())
    if yaw > 0.45 or roll > 30 or sharp < 40 or not 40 < bright < 220:
        return None
    score = (
        0.25 * min(1.0, w / 220)
        + 0.30 * min(1.0, sharp / 300)
        + 0.25 * max(0.0, 1 - yaw / 0.45)
        + 0.10 * (1 - abs(bright - 128) / 128)
        + 0.10 * float(row[14])
    )
    metrics = {
        "w": int(w),
        "yaw": round(float(yaw), 2),
        "roll": round(float(roll), 1),
        "sharp": int(sharp),
    }
    return float(score), metrics


def faces_in(path: Path, det, rec, label: str, rank: int) -> list[Face]:
    img = cv2.imread(str(path))
    if img is None:
        return []
    h, w = img.shape[:2]
    det.setInputSize((w, h))
    _, rows = det.detect(img)
    out = []
    day = ""
    if m := re.search(r"(\d{1,2} \w+ \d{4})", label):
        day = m.group(1)
    for row in rows if rows is not None else []:
        aligned = rec.alignCrop(img, row)
        feat = rec.feature(aligned).flatten()
        feat = feat / np.linalg.norm(feat)
        q = quality(img, row, aligned)
        out.append(
            Face(
                str(path),
                row[:4].astype(int),
                row,
                feat,
                q[0] if q else -1.0,
                q[1] if q else {},
                day,
                rank,
            )
        )
    return out


def dominant_identity(faces: list[Face]) -> np.ndarray | None:
    if not faces:
        return None
    feats = np.stack([f.feat for f in faces])
    sims = feats @ feats.T
    photos = np.array([f.photo for f in faces])
    support = [
        len(set(photos[(sims[i] > SAME_PERSON) & (photos != photos[i])])) for i in range(len(faces))
    ]
    medoid = int(np.argmax(support))
    members = feats[sims[medoid] > SAME_PERSON]
    ref = members.mean(axis=0)
    return ref / np.linalg.norm(ref)


def anchor_identity(tile: Path, faces: list[Face], det, rec) -> np.ndarray | None:
    """Reference embedding from the group's cover face (e.g. a Google Photos People tile)."""
    tile_faces = faces_in(tile, det, rec, "", 0)
    if not tile_faces:
        return None
    anchor = max(tile_faces, key=lambda f: f.box[2] * f.box[3]).feat
    close = [f.feat for f in faces if float(f.feat @ anchor) > SAME_PERSON]
    ref = np.mean([anchor, *close], axis=0)
    return ref / np.linalg.norm(ref)


def members_of(faces: list[Face], ref: np.ndarray) -> list[Face]:
    """Best-matching face per photo, if it is close enough to the reference."""
    best_per_photo: dict[str, Face] = {}
    for f in faces:
        s = float(f.feat @ ref)
        if s < MEMBER:
            continue
        cur = best_per_photo.get(f.photo)
        if cur is None or s > float(cur.feat @ ref):
            best_per_photo[f.photo] = f
    return list(best_per_photo.values())


def pick(members: list[Face], limit: int) -> list[Face]:
    """Highest-quality, recent-leaning, varied subset."""
    usable = [f for f in members if f.quality > 0]
    usable.sort(key=lambda f: f.quality + 0.1 * (1 - f.rank / 40), reverse=True)
    chosen: list[Face] = []
    per_day: dict[str, int] = {}
    for f in usable:
        if any(float(f.feat @ c.feat) > NEAR_DUPLICATE for c in chosen):
            continue
        if f.day and per_day.get(f.day, 0) >= PER_DAY:
            continue
        chosen.append(f)
        per_day[f.day] = per_day.get(f.day, 0) + 1
        if len(chosen) >= limit:
            break
    return chosen


def crop(img: np.ndarray, box: np.ndarray, margin: float = 0.35, size: int = 320) -> np.ndarray:
    x, y, w, h = box
    side = int(max(w, h) * (1 + 2 * margin))
    cx, cy = x + w // 2, y + h // 2
    x0, y0 = max(0, cx - side // 2), max(0, cy - side // 2)
    x1, y1 = min(img.shape[1], x0 + side), min(img.shape[0], y0 + side)
    c = img[y0:y1, x0:x1]
    scale = size / max(c.shape[:2])
    return cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else c


def contact_sheets(
    root: Path, rows: list[tuple[str, list[Path], str]], per_sheet: int = 11
) -> None:
    tile, label_w, cols = 96, 230, 15
    out_dir = root / "sheets"
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink()
    for s in range(0, len(rows), per_sheet):
        chunk = rows[s : s + per_sheet]
        sheet = np.full((len(chunk) * (tile + 6), label_w + cols * tile, 3), 30, np.uint8)
        for r, (name, files, note) in enumerate(chunk):
            y = r * (tile + 6)
            cv2.putText(sheet, name, (8, y + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(
                sheet, note, (8, y + 70), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1
            )
            for c, f in enumerate(files[:cols]):
                im = cv2.resize(cv2.imread(str(f)), (tile, tile))
                sheet[y : y + tile, label_w + c * tile : label_w + (c + 1) * tile] = im
        cv2.imwrite(
            str(out_dir / f"sheet_{s // per_sheet + 1}.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85]
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--per-person", type=int, default=15)
    ap.add_argument("--tiles", type=Path, help="folder of <group>.jpg cover faces used as anchors")
    ap.add_argument(
        "--merge", action="append", default=[], help="TARGET=group1,group2 (repeatable)"
    )
    ap.add_argument("--exclude", action="append", default=[], help="group to skip (repeatable)")
    args = ap.parse_args()

    det, rec = load_models(args.models)
    raw = args.root / "raw"
    groups = sorted(p.name for p in raw.iterdir() if p.is_dir() and p.name not in args.exclude)
    targets: dict[str, list[str]] = {g: [g] for g in groups}
    for spec in args.merge:
        target, sources = spec.split("=", 1)
        sources = [x.strip() for x in sources.split(",")]
        for src in sources:
            targets.pop(src, None)
        targets[target.strip()] = [x for x in sources if x in groups]

    report, sheet_rows, refs = {}, [], {}
    for target in sorted(targets):
        pooled: list[Face] = []
        n_photos, how = 0, []
        for group in targets[target]:
            group_dir = raw / group
            index_file = group_dir / "index.json"
            index = (
                json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else {}
            )
            photos = sorted(group_dir.glob("*.jpg"))
            n_photos += len(photos)
            faces: list[Face] = []
            for rank, p in enumerate(photos):
                faces += faces_in(p, det, rec, index.get(p.name, ""), rank)
            tile = args.tiles / f"{group}.jpg" if args.tiles else None
            ref = anchor_identity(tile, faces, det, rec) if tile and tile.exists() else None
            how.append("tile" if ref is not None else "dominant")
            if ref is None:
                ref = dominant_identity(faces)
            if ref is not None:
                refs[group] = ref
                pooled += members_of(faces, ref)

        out = args.root / "selected" / target
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("*.jpg"):
            old.unlink()
        chosen = pick(pooled, args.per_person)
        files = []
        for i, f in enumerate(chosen):
            img = cv2.imread(f.photo)
            dest = out / f"{target.replace(' ', '_')}_{i:02d}.jpg"
            cv2.imwrite(str(dest), crop(img, f.box), [cv2.IMWRITE_JPEG_QUALITY, 92])
            files.append(dest)
        report[target] = {
            "groups": targets[target],
            "anchor": how,
            "photos": n_photos,
            "photos_with_person": len(pooled),
            "selected": len(chosen),
            "details": [
                {
                    "photo": str(Path(f.photo).relative_to(raw)),
                    "q": round(f.quality, 2),
                    **f.metrics,
                }
                for f in chosen
            ],
        }
        sheet_rows.append(
            (target, files, f"{len(chosen)} of {len(pooled)}/{n_photos} {'+'.join(how)}")
        )
        print(
            f"{target:16} photos={n_photos:3} matched={len(pooled):3} "
            f"selected={len(chosen):2} anchor={'+'.join(how)}"
        )

    names = list(refs)
    similar = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            s = float(refs[a] @ refs[b])
            if s > SAME_PERSON:
                similar.append({"a": a, "b": b, "similarity": round(s, 2)})
    report["_possibly_same_person"] = similar
    (args.root / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    contact_sheets(args.root, sheet_rows)
    print("possibly same person:", similar)


if __name__ == "__main__":
    main()

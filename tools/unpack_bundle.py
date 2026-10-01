"""Unpack a photo bundle exported from the browser.

Bundle layout: <image bytes...><index JSON><16-digit index length>
Index entries: {"folder", "name", "label", "offset", "len"}

Usage: python unpack_bundle.py BUNDLE OUT_DIR   -> OUT_DIR/raw/<folder>/<name> + index.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()

    data = args.bundle.read_bytes()
    idx_len = int(data[-16:])
    index = json.loads(data[-16 - idx_len : -16])
    labels: dict[str, dict[str, str]] = defaultdict(dict)
    for e in index:
        dest = args.out / "raw" / e["folder"] / e["name"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data[e["offset"] : e["offset"] + e["len"]])
        labels[e["folder"]][e["name"]] = e.get("label", "")
    for folder, mapping in labels.items():
        path = args.out / "raw" / folder / "index.json"
        path.write_text(json.dumps(mapping, indent=1), encoding="utf-8")
    print(f"{len(index)} files into {len(labels)} folders")


if __name__ == "__main__":
    main()

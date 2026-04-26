#!/usr/bin/env python3
"""
Merge `originals_videos.json` (from drive_originals_videos.gs) into
`assets/data/drive_photos.json` by adding an `originalId` field to each
video entry. Match key: (event_side, filename).

Usage:
    python3 scripts/merge_original_ids.py originals_videos.json
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRIVE_PHOTOS = REPO / "assets" / "data" / "drive_photos.json"


def main():
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <originals_videos.json>")
        sys.exit(2)
    originals_path = Path(sys.argv[1])

    photos = json.loads(DRIVE_PHOTOS.read_text())
    originals = json.loads(originals_path.read_text())

    matched = 0
    unmatched = []
    duplicate_names = []

    # Case-insensitive filename match: 1080p transcodes use .mp4, originals .MP4
    for event_side, vids in photos.get("videos", {}).items():
        orig_list = originals.get("videos", {}).get(event_side, [])
        name_to_id = {}
        for v in orig_list:
            key = v["name"].lower()
            if key in name_to_id:
                duplicate_names.append(f"{event_side}/{v['name']}")
            else:
                name_to_id[key] = v["id"]
        for v in vids:
            oid = name_to_id.get(v["name"].lower())
            if oid:
                v["originalId"] = oid
                matched += 1
            else:
                unmatched.append(f"{event_side}/{v['name']}")

    print(f"Matched:    {matched}")
    print(f"Unmatched:  {len(unmatched)}")
    print(f"Duplicate filenames in originals: {len(duplicate_names)}")
    for u in unmatched[:20]:
        print(f"  unmatched: {u}")
    if len(unmatched) > 20:
        print(f"  ... and {len(unmatched) - 20} more")
    for d in duplicate_names[:10]:
        print(f"  dup: {d}")

    DRIVE_PHOTOS.write_text(json.dumps(photos))
    print(f"Wrote {DRIVE_PHOTOS}")


if __name__ == "__main__":
    main()

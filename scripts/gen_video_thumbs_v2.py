"""
Generate video thumbnails v2 — generates for ALL local videos,
then matches to Drive IDs by event+folder position and filename patterns.
Falls back to generating thumbnails named by local filename.
Updates drive_photos.json with thumbnail paths.
"""

import os
import sys
import json
import subprocess
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# ============================================================
# CONFIG
# ============================================================
GIRL_SIDE_DIR = r"C:\Users\jessica\wedding data\Girl Side"
BOY_SIDE_DIR = r"C:\Wedding\Wedding\Boy Side"
OUTPUT_DIR = r"C:\Users\jessica\wedding data\sharan-avleen-wedding\assets\video_thumbs"
DRIVE_JSON = r"C:\Users\jessica\wedding data\sharan-avleen-wedding\assets\data\drive_photos.json"

THUMB_WIDTH = 400
SEEK_TIME = "00:00:02"
MAX_WORKERS = 12  # Spread across 2 GPUs
NUM_GPUS = 2

GIRL_FOLDERS = {
    "Mehdi 21": "mehdi",
    "21 jan shagan ok": "shagan",
    "22 Sangeet ok": "sangeet",
    "23 date Vatna": "vatna",
    "24 Jan Wedding": "wedding",
}

BOY_FOLDERS = {
    "19 jan path ok 25 gb": "path",
    "22 jan shagan ok 138 gb": "shagan",
    "22 Jan Sangeet": "sangeet",
    "23 Jan Vatna 56 gb ok": "vatna",
    "24 jan Wedding 428GB": "wedding",
    "24 Reception 374 gb ok": "reception",
}


def find_all_local_videos(base_dir, folder_map, side):
    """Find all video files grouped by event."""
    event_videos = {}
    for folder_name, event_id in folder_map.items():
        folder_path = os.path.join(base_dir, folder_name)
        if not os.path.exists(folder_path):
            continue

        key = f"{event_id}_{side}"
        event_videos[key] = []

        for root, dirs, files in os.walk(folder_path):
            parts = Path(root).parts
            in_video_dir = any(p.upper() in ("VIDEO", "VIDEOS") for p in parts)
            if in_video_dir:
                for f in sorted(files):
                    if f.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')):
                        event_videos[key].append({
                            "path": os.path.join(root, f),
                            "filename": f,
                        })

    return event_videos


def generate_thumbnail(video_path, output_path, gpu_id=0):
    """Extract a frame from video using ffmpeg with CUDA on specified GPU."""
    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        return True
    try:
        cmd = [
            "ffmpeg", "-y",
            "-hwaccel", "cuda",
            "-hwaccel_device", str(gpu_id),
            "-ss", SEEK_TIME,
            "-i", video_path,
            "-vframes", "1",
            "-vf", f"scale={THUMB_WIDTH}:-1",
            "-q:v", "80",
            output_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        return result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except:
        if os.path.exists(output_path):
            os.remove(output_path)
        return False


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load drive_photos.json
    print("Loading drive_photos.json...")
    with open(DRIVE_JSON, 'r') as f:
        drive_data = json.load(f)

    # Find all local videos grouped by event
    print("Scanning local videos...")
    local_videos = {}
    local_videos.update(find_all_local_videos(GIRL_SIDE_DIR, GIRL_FOLDERS, "girl"))
    local_videos.update(find_all_local_videos(BOY_SIDE_DIR, BOY_FOLDERS, "boy"))

    for key, vids in local_videos.items():
        print(f"  {key}: {len(vids)} local videos")

    # Strategy: match local videos to Drive videos by sorted order within each event
    # Both local and Drive are sorted by filename, so position-based matching works
    # when file counts match. When they don't, we use the local filename as thumb name.

    all_tasks = []  # (video_path, thumb_filename)
    drive_thumb_map = {}  # drive_id → thumb_filename

    for event_key in drive_data.get("videos", {}):
        drive_vids = drive_data["videos"][event_key]
        local_vids = local_videos.get(event_key, [])

        # Sort both by filename for consistent ordering
        drive_sorted = sorted(drive_vids, key=lambda x: x["name"].lower())
        local_sorted = sorted(local_vids, key=lambda x: x["filename"].lower())

        print(f"\n{event_key}: {len(drive_sorted)} drive, {len(local_sorted)} local")

        if len(drive_sorted) == len(local_sorted):
            # Perfect count match — pair by position
            print(f"  Count matches! Pairing by position.")
            for drive_vid, local_vid in zip(drive_sorted, local_sorted):
                thumb_name = f"{drive_vid['id']}.webp"
                thumb_path = os.path.join(OUTPUT_DIR, thumb_name)
                all_tasks.append((local_vid["path"], thumb_path))
                drive_thumb_map[drive_vid["id"]] = thumb_name
        else:
            # Count mismatch — try filename matching first, then positional for remainder
            print(f"  Count mismatch. Trying filename match...")
            local_by_name = {v["filename"].lower(): v for v in local_sorted}
            matched = 0
            unmatched_drive = []

            for dv in drive_sorted:
                if dv["name"].lower() in local_by_name:
                    lv = local_by_name[dv["name"].lower()]
                    thumb_name = f"{dv['id']}.webp"
                    thumb_path = os.path.join(OUTPUT_DIR, thumb_name)
                    all_tasks.append((lv["path"], thumb_path))
                    drive_thumb_map[dv["id"]] = thumb_name
                    matched += 1
                else:
                    unmatched_drive.append(dv)

            print(f"  Matched by name: {matched}, Unmatched: {len(unmatched_drive)}")

            # For unmatched, try to pair remaining local files by position
            matched_local_paths = set(t[0] for t in all_tasks)
            remaining_local = [v for v in local_sorted if v["path"] not in matched_local_paths]

            for i, dv in enumerate(unmatched_drive):
                if i < len(remaining_local):
                    lv = remaining_local[i]
                    thumb_name = f"{dv['id']}.webp"
                    thumb_path = os.path.join(OUTPUT_DIR, thumb_name)
                    all_tasks.append((lv["path"], thumb_path))
                    drive_thumb_map[dv["id"]] = thumb_name

    print(f"\nTotal thumbnails to generate: {len(all_tasks)}")

    # Filter out already existing
    tasks_needed = [(src, dst) for src, dst in all_tasks
                    if not (os.path.exists(dst) and os.path.getsize(dst) > 0)]
    tasks_existing = len(all_tasks) - len(tasks_needed)
    print(f"Already exist: {tasks_existing}, Need to generate: {len(tasks_needed)}")

    # Generate thumbnails
    if tasks_needed:
        success = 0
        failed = 0
        task_counter = [0]  # mutable counter for round-robin GPU assignment

        def do_thumb(task):
            src, dst = task
            gpu_id = task_counter[0] % NUM_GPUS
            task_counter[0] += 1
            ok = generate_thumbnail(src, dst, gpu_id=gpu_id)
            return ok

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(do_thumb, t): t for t in tasks_needed}
            for future in tqdm(as_completed(futures), total=len(tasks_needed), desc="Thumbnails (2 GPUs)"):
                if future.result():
                    success += 1
                else:
                    failed += 1

        print(f"\nGenerated: {success}, Failed: {failed}")

    # Update drive_photos.json with thumb paths
    updated = 0
    for event_key in drive_data.get("videos", {}):
        for vid in drive_data["videos"][event_key]:
            if vid["id"] in drive_thumb_map:
                vid["thumb"] = f"assets/video_thumbs/{drive_thumb_map[vid['id']]}"
                updated += 1

    with open(DRIVE_JSON, 'w') as f:
        json.dump(drive_data, f)

    print(f"\nUpdated {updated} video entries with thumbnail paths in drive_photos.json")

    # Final count
    total_thumbs = len([f for f in os.listdir(OUTPUT_DIR) if f.endswith('.webp')])
    print(f"Total thumbnail files: {total_thumbs}")


if __name__ == "__main__":
    main()

"""
Generate video thumbnails from local video files.
Extracts a frame at 2 seconds into each video and saves as a WebP thumbnail.
Maps filenames to Drive file IDs from drive_photos.json.
"""

import os
import sys
import json
import subprocess
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
SEEK_TIME = "00:00:02"  # Extract frame at 2 seconds
MAX_WORKERS = 8  # Parallel ffmpeg processes (GPU accelerated)

# Folder name → event ID mapping
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


def find_video_folders(base_dir, folder_map, side):
    """Find all Video/Videos subfolders and map to event IDs."""
    videos = []
    for folder_name, event_id in folder_map.items():
        folder_path = os.path.join(base_dir, folder_name)
        if not os.path.exists(folder_path):
            print(f"  WARNING: Folder not found: {folder_path}")
            continue

        # Walk to find Video/Videos subfolders
        for root, dirs, files in os.walk(folder_path):
            # Check if we're inside a Video/Videos folder
            parts = Path(root).parts
            in_video_dir = any(p.upper() in ("VIDEO", "VIDEOS") for p in parts)

            if in_video_dir:
                for f in files:
                    if f.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')):
                        videos.append({
                            "path": os.path.join(root, f),
                            "filename": f,
                            "event": event_id,
                            "side": side,
                        })
            else:
                # Check if any subdirectory is Video/Videos
                for d in dirs:
                    if d.upper() in ("VIDEO", "VIDEOS"):
                        pass  # os.walk will enter it
    return videos


def generate_thumbnail(video_path, output_path):
    """Extract a frame from video using ffmpeg with CUDA GPU acceleration."""
    try:
        cmd = [
            "ffmpeg", "-y",
            "-hwaccel", "cuda",
            "-ss", SEEK_TIME,
            "-i", video_path,
            "-vframes", "1",
            "-vf", f"scale={THUMB_WIDTH}:-1",
            "-q:v", "80",
            output_path
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception as e:
        return False


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load drive_photos.json to get file IDs
    print("Loading drive_photos.json...")
    with open(DRIVE_JSON, 'r') as f:
        drive_data = json.load(f)

    # Build filename → drive_id mapping for videos
    name_to_id = {}
    for event_key, video_list in drive_data.get("videos", {}).items():
        for v in video_list:
            name_to_id[v["name"].lower()] = v["id"]

    print(f"Drive video mapping: {len(name_to_id)} files")

    # Find all local video files
    print("\nScanning local video files...")
    all_videos = []
    all_videos += find_video_folders(GIRL_SIDE_DIR, GIRL_FOLDERS, "girl")
    all_videos += find_video_folders(BOY_SIDE_DIR, BOY_FOLDERS, "boy")
    print(f"Found {len(all_videos)} local video files")

    # Generate thumbnails
    print(f"\nGenerating thumbnails ({MAX_WORKERS} workers)...")
    success = 0
    failed = 0
    skipped = 0
    thumb_map = {}  # drive_id → thumb filename

    def process_video(video):
        fname = video["filename"]
        drive_id = name_to_id.get(fname.lower())
        if not drive_id:
            return ("no_id", fname, None)

        thumb_filename = f"{drive_id}.webp"
        thumb_path = os.path.join(OUTPUT_DIR, thumb_filename)

        # Skip if already exists
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return ("skipped", fname, drive_id)

        ok = generate_thumbnail(video["path"], thumb_path)
        if ok and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return ("ok", fname, drive_id)
        else:
            # Clean up failed file
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
            return ("fail", fname, drive_id)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_video, v): v for v in all_videos}

        for future in tqdm(as_completed(futures), total=len(all_videos), desc="Thumbnails"):
            status, fname, drive_id = future.result()
            if status == "ok":
                success += 1
                thumb_map[drive_id] = f"{drive_id}.webp"
            elif status == "skipped":
                skipped += 1
                thumb_map[drive_id] = f"{drive_id}.webp"
            elif status == "fail":
                failed += 1
            # no_id means no drive mapping found

    print(f"\nDone! Success: {success}, Skipped (existing): {skipped}, Failed: {failed}")
    print(f"Thumbnails in: {OUTPUT_DIR}")

    # Count total thumbnails
    thumb_count = len([f for f in os.listdir(OUTPUT_DIR) if f.endswith('.webp')])
    print(f"Total thumbnail files: {thumb_count}")


if __name__ == "__main__":
    main()

"""
Face Recognition Pipeline for Wedding Photos
=============================================
Scans all wedding photos, detects faces, clusters by person,
and generates data for the "Find My Photos" web feature.

Usage:
  python face_pipeline.py                    # Full run
  python face_pipeline.py --test 50          # Test on 50 photos
  python face_pipeline.py --resume           # Resume from checkpoint
  python face_pipeline.py --cluster-only     # Re-cluster from saved embeddings
"""

import os
import sys
import json
import time
import glob
import argparse
import pickle
from pathlib import Path
from collections import defaultdict

# Add CUDA DLL paths BEFORE importing onnxruntime/insightface
try:
    import site
    sp_base = os.path.dirname(site.getusersitepackages()) if hasattr(site, 'getusersitepackages') else ''
    sp = site.getusersitepackages() if hasattr(site, 'getusersitepackages') else site.getsitepackages()[0]
    cuda_dll_dirs = [
        os.path.join(sp, 'nvidia', 'cublas', 'bin'),
        os.path.join(sp, 'nvidia', 'cuda_runtime', 'bin'),
        os.path.join(sp, 'nvidia', 'cudnn', 'bin'),
        os.path.join(sp, 'nvidia', 'cuda_nvrtc', 'bin'),
    ]
    # Also add CUDA Toolkit system install paths
    for cuda_ver_dir in glob.glob(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v*"):
        for sub in ['bin', os.path.join('bin', 'x64'), 'lib', os.path.join('lib', 'x64')]:
            candidate = os.path.join(cuda_ver_dir, sub)
            if os.path.isdir(candidate):
                cuda_dll_dirs.append(candidate)
    for d in cuda_dll_dirs:
        if os.path.isdir(d):
            os.add_dll_directory(d)
            os.environ['PATH'] = d + os.pathsep + os.environ.get('PATH', '')
            print(f"  Added CUDA DLL path: {d}")
except Exception as e:
    print(f"  Note: Could not add CUDA DLL paths: {e}")

import numpy as np
from PIL import Image, ImageOps
from tqdm import tqdm

# ============================================================
# CONFIGURATION
# ============================================================
GIRL_SIDE_DIR = r"C:\Users\jessica\wedding data\Girl Side"
BOY_SIDE_DIR = r"C:\Wedding\Wedding\Boy Side"
OUTPUT_DIR = r"C:\Users\jessica\wedding data\sharan-avleen-wedding\assets"
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Folder name -> event ID mapping
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

DRIVE_LINKS = {
    "girl": "https://drive.google.com/drive/folders/1V76_3Uo-KY8wKj0vLJ6iQmsyyL71WXML",
    "boy": "https://drive.google.com/drive/folders/144sBhp9suoPpJZ8LnqplNq59el2ZnEOo",
}

# Processing params
MAX_IMAGE_EDGE = 1280       # Resize long edge for face detection
MIN_FACE_SIZE = 40          # Skip faces smaller than this (px)
CHECKPOINT_INTERVAL = 100   # Save progress every N photos

# Clustering params
DBSCAN_EPS = 0.32           # Cosine distance threshold (tighter = fewer false matches)
DBSCAN_MIN_SAMPLES = 3      # Min photos per cluster
MERGE_THRESHOLD = 0.90      # Cosine similarity to merge clusters (higher = fewer merges)
MAX_CENTROID_DIST = 0.35    # Remove faces too far from cluster centroid

# Thumbnail params
FACE_THUMB_SIZE = 150       # Face thumbnail px
PHOTO_THUMB_WIDTH = 400     # Photo thumbnail width px
MAX_PHOTO_THUMBS = None     # Generate thumbnails for ALL photos per cluster

CHECKPOINT_FILE = os.path.join(SCRIPTS_DIR, "checkpoint.pkl")
EMBEDDINGS_FILE = os.path.join(SCRIPTS_DIR, "embeddings.pkl")


# ============================================================
# STEP 1: SCAN PHOTOS
# ============================================================
def scan_photos(limit=None):
    """Walk both directories and collect photo paths with metadata."""
    photos = []

    for base_dir, folder_map, side in [
        (GIRL_SIDE_DIR, GIRL_FOLDERS, "girl"),
        (BOY_SIDE_DIR, BOY_FOLDERS, "boy"),
    ]:
        for folder_name, event_id in folder_map.items():
            folder_path = os.path.join(base_dir, folder_name)
            if not os.path.exists(folder_path):
                print(f"  WARNING: Folder not found: {folder_path}")
                continue

            # Recursively find JPG files, skip VIDEO dirs
            for root, dirs, files in os.walk(folder_path):
                # Skip video directories
                dirs[:] = [d for d in dirs if d.upper() not in ("VIDEO", "VIDEOS")]

                for f in files:
                    if f.lower().endswith(('.jpg', '.jpeg')):
                        filepath = os.path.join(root, f)
                        photo_id = f"{side}_{event_id}_{Path(f).stem}"
                        photos.append({
                            "path": filepath,
                            "id": photo_id,
                            "filename": f,
                            "event": event_id,
                            "side": side,
                            "drive_link": DRIVE_LINKS[side],
                        })

    photos.sort(key=lambda x: x["path"])

    if limit:
        photos = photos[:limit]

    print(f"Found {len(photos)} photos to process")
    return photos


# ============================================================
# STEP 2: DETECT FACES & EXTRACT EMBEDDINGS
# ============================================================
def init_face_model(gpu_id=0):
    """Initialize InsightFace with GPU."""
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(
        name='buffalo_l',
        providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
    )
    app.prepare(ctx_id=gpu_id, det_size=(640, 640))
    print(f"InsightFace initialized on GPU {gpu_id}")
    return app


def load_and_resize(path, max_edge=MAX_IMAGE_EDGE):
    """Load image, apply EXIF rotation, resize for processing."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img = img.convert('RGB')

    w, h = img.size
    if max(w, h) > max_edge:
        scale = max_edge / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    return np.array(img), img.size


def extract_faces(app, photos, resume_from=0):
    """Detect faces and extract embeddings for all photos."""
    all_faces = []

    # Load checkpoint if resuming
    if resume_from > 0 and os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, 'rb') as f:
            all_faces = pickle.load(f)
        print(f"Resumed from checkpoint: {len(all_faces)} faces from {resume_from} photos")

    for i, photo in enumerate(tqdm(photos[resume_from:], initial=resume_from, total=len(photos), desc="Detecting faces")):
        idx = i + resume_from
        try:
            img_array, (w, h) = load_and_resize(photo["path"])
            faces = app.get(img_array)

            for face in faces:
                bbox = face.bbox.astype(int)
                face_w = bbox[2] - bbox[0]
                face_h = bbox[3] - bbox[1]

                # Skip tiny faces
                if face_w < MIN_FACE_SIZE or face_h < MIN_FACE_SIZE:
                    continue

                all_faces.append({
                    "photo_idx": idx,
                    "photo_id": photo["id"],
                    "photo_path": photo["path"],
                    "event": photo["event"],
                    "side": photo["side"],
                    "filename": photo["filename"],
                    "drive_link": photo["drive_link"],
                    "bbox": bbox.tolist(),
                    "det_score": float(face.det_score),
                    "embedding": face.normed_embedding,
                    "face_area": face_w * face_h,
                    "img_size": (w, h),
                })

        except Exception as e:
            print(f"\n  Error processing {photo['path']}: {e}")
            continue

        # Checkpoint
        if (idx + 1) % CHECKPOINT_INTERVAL == 0:
            with open(CHECKPOINT_FILE, 'wb') as f:
                pickle.dump(all_faces, f)

    # Save final embeddings
    with open(EMBEDDINGS_FILE, 'wb') as f:
        pickle.dump(all_faces, f)
    print(f"Extracted {len(all_faces)} faces from {len(photos)} photos")

    return all_faces


# ============================================================
# STEP 3: CLUSTER FACES
# ============================================================
def cluster_faces(all_faces, eps=DBSCAN_EPS):
    """Cluster face embeddings using DBSCAN."""
    from sklearn.cluster import DBSCAN
    from sklearn.preprocessing import normalize

    print(f"Clustering {len(all_faces)} faces (eps={eps})...")

    embeddings = np.array([f["embedding"] for f in all_faces])
    embeddings_norm = normalize(embeddings)

    clustering = DBSCAN(
        eps=eps,
        min_samples=DBSCAN_MIN_SAMPLES,
        metric='cosine',
        n_jobs=-1
    )
    labels = clustering.fit_predict(embeddings_norm)

    # Build clusters
    clusters = defaultdict(list)
    noise_count = 0
    for i, label in enumerate(labels):
        if label == -1:
            noise_count += 1
            continue
        clusters[label].append(i)

    print(f"Found {len(clusters)} clusters, {noise_count} noise faces discarded")

    # Post-processing: merge similar clusters
    cluster_ids = list(clusters.keys())
    centroids = {}
    for cid in cluster_ids:
        indices = clusters[cid]
        centroid = np.mean(embeddings_norm[indices], axis=0)
        centroid = centroid / np.linalg.norm(centroid)
        centroids[cid] = centroid

    merged = set()
    merge_map = {}
    for i, cid1 in enumerate(cluster_ids):
        if cid1 in merged:
            continue
        for cid2 in cluster_ids[i + 1:]:
            if cid2 in merged:
                continue
            sim = np.dot(centroids[cid1], centroids[cid2])
            if sim > MERGE_THRESHOLD:
                clusters[cid1].extend(clusters[cid2])
                merged.add(cid2)
                merge_map[cid2] = cid1

    for cid in merged:
        del clusters[cid]

    print(f"After merging: {len(clusters)} clusters")

    # Post-processing: remove faces too far from centroid (breaks chaining artifacts)
    # Recompute centroids after merge
    cleaned_count = 0
    for cid in list(clusters.keys()):
        indices = clusters[cid]
        embs = embeddings_norm[indices]
        centroid = np.mean(embs, axis=0)
        centroid = centroid / np.linalg.norm(centroid)
        dists = 1 - np.dot(embs, centroid)

        # Keep only faces within MAX_CENTROID_DIST
        keep = [idx for idx, d in zip(indices, dists) if d <= MAX_CENTROID_DIST]
        removed = len(indices) - len(keep)
        cleaned_count += removed

        if len(keep) >= DBSCAN_MIN_SAMPLES:
            clusters[cid] = keep
        else:
            del clusters[cid]

    print(f"After centroid cleanup (max_dist={MAX_CENTROID_DIST}): {len(clusters)} clusters, {cleaned_count} faces removed")

    # Sort by photo count (unique photos) descending
    sorted_clusters = sorted(
        clusters.items(),
        key=lambda x: len(set(all_faces[i]["photo_id"] for i in x[1])),
        reverse=True
    )

    return sorted_clusters


# ============================================================
# STEP 4: GENERATE THUMBNAILS
# ============================================================
def generate_thumbnails(all_faces, sorted_clusters):
    """Generate face thumbnails and photo thumbnails."""
    faces_dir = os.path.join(OUTPUT_DIR, "faces")
    photos_dir = os.path.join(OUTPUT_DIR, "face_photos")
    os.makedirs(faces_dir, exist_ok=True)
    os.makedirs(photos_dir, exist_ok=True)

    cluster_data = []

    for cluster_num, (cid, face_indices) in enumerate(tqdm(sorted_clusters, desc="Generating thumbnails")):
        cluster_id = f"c{cluster_num + 1:03d}"

        # Collect unique photos for this cluster
        photo_map = {}
        for fi in face_indices:
            face = all_faces[fi]
            pid = face["photo_id"]
            if pid not in photo_map or face["det_score"] > photo_map[pid]["det_score"]:
                photo_map[pid] = face

        photos_list = sorted(photo_map.values(), key=lambda x: -x["face_area"])

        # Pick best face for cluster thumbnail
        # Score prioritizes: high confidence, large face, square aspect (frontal), prominent in frame
        def face_thumb_score(x):
            bbox = x["bbox"]
            fw, fh = bbox[2] - bbox[0], bbox[3] - bbox[1]
            aspect = min(fw, fh) / max(fw, fh) if max(fw, fh) > 0 else 0  # 1.0 = square/frontal
            img_area = x["img_size"][0] * x["img_size"][1] if x["img_size"][0] > 0 else 1
            prominence = x["face_area"] / img_area  # How much of the frame the face fills
            return x["det_score"] * (x["face_area"] ** 0.5) * (aspect ** 2) * (1 + prominence * 10)

        best_face = max((all_faces[fi] for fi in face_indices), key=face_thumb_score)

        # Generate face thumbnail (cropped face)
        try:
            img = Image.open(best_face["photo_path"])
            img = ImageOps.exif_transpose(img)
            img = img.convert('RGB')

            # Scale bbox to original image size
            orig_w, orig_h = img.size
            proc_w, proc_h = best_face["img_size"]
            scale_x = orig_w / proc_w
            scale_y = orig_h / proc_h

            bbox = best_face["bbox"]
            x1 = int(bbox[0] * scale_x)
            y1 = int(bbox[1] * scale_y)
            x2 = int(bbox[2] * scale_x)
            y2 = int(bbox[3] * scale_y)

            # Add padding (30%)
            fw, fh = x2 - x1, y2 - y1
            pad = int(max(fw, fh) * 0.3)
            x1 = max(0, x1 - pad)
            y1 = max(0, y1 - pad)
            x2 = min(orig_w, x2 + pad)
            y2 = min(orig_h, y2 + pad)

            face_crop = img.crop((x1, y1, x2, y2))
            face_crop = face_crop.resize((FACE_THUMB_SIZE, FACE_THUMB_SIZE), Image.LANCZOS)
            face_thumb_path = os.path.join(faces_dir, f"{cluster_id}.webp")
            face_crop.save(face_thumb_path, "WEBP", quality=85)
            img.close()
        except Exception as e:
            print(f"\n  Error generating face thumb for {cluster_id}: {e}")
            continue

        # Generate photo thumbnails (top N)
        photo_entries = []
        for pi, photo_face in enumerate(photos_list):
            thumb_path = None
            if MAX_PHOTO_THUMBS is None or pi < MAX_PHOTO_THUMBS:
                try:
                    pimg = Image.open(photo_face["photo_path"])
                    pimg = ImageOps.exif_transpose(pimg)
                    pimg = pimg.convert('RGB')
                    pw, ph = pimg.size
                    new_w = PHOTO_THUMB_WIDTH
                    new_h = int(ph * new_w / pw)
                    pimg = pimg.resize((new_w, new_h), Image.LANCZOS)
                    thumb_filename = f"{photo_face['photo_id']}.webp"
                    thumb_full_path = os.path.join(photos_dir, thumb_filename)
                    pimg.save(thumb_full_path, "WEBP", quality=80)
                    pimg.close()
                    thumb_path = f"assets/face_photos/{thumb_filename}"
                except Exception as e:
                    pass

            photo_entries.append({
                "id": photo_face["photo_id"],
                "filename": photo_face["filename"],
                "event": photo_face["event"],
                "side": photo_face["side"],
                "thumb": thumb_path,
                "drive_link": photo_face["drive_link"],
            })

        events = sorted(set(p["event"] for p in photo_entries))

        cluster_data.append({
            "id": cluster_id,
            "thumbnail": f"assets/faces/{cluster_id}.webp",
            "photo_count": len(photo_entries),
            "events": events,
            "photos": photo_entries,
        })

    return cluster_data


# ============================================================
# STEP 5: EXPORT JSON & REVIEW HTML
# ============================================================
def export_json(cluster_data, total_photos):
    """Export faces_data.json."""
    data_dir = os.path.join(OUTPUT_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)

    output = {
        "version": 1,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stats": {
            "photos_scanned": total_photos,
            "faces_detected": sum(c["photo_count"] for c in cluster_data),
            "clusters": len(cluster_data),
        },
        "clusters": cluster_data,
    }

    json_path = os.path.join(data_dir, "faces_data.json")
    with open(json_path, 'w') as f:
        json.dump(output, f, indent=None, separators=(',', ':'))

    size_mb = os.path.getsize(json_path) / (1024 * 1024)
    print(f"Exported {json_path} ({size_mb:.1f} MB)")
    return json_path


def generate_review_html(cluster_data, all_faces, sorted_clusters):
    """Generate a review HTML to visually verify clusters."""
    html_path = os.path.join(SCRIPTS_DIR, "clusters_review.html")

    html = ['<html><head><style>',
            'body{font-family:sans-serif;background:#111;color:#eee;padding:20px}',
            '.cluster{margin:20px 0;padding:15px;border:1px solid #333;border-radius:8px}',
            '.cluster h3{margin:0 0 10px}',
            '.faces{display:flex;gap:8px;flex-wrap:wrap}',
            '.faces img{width:100px;height:100px;object-fit:cover;border-radius:8px}',
            '</style></head><body>',
            f'<h1>Face Clusters Review ({len(cluster_data)} clusters)</h1>']

    for ci, cd in enumerate(cluster_data[:100]):  # Show top 100
        html.append(f'<div class="cluster">')
        html.append(f'<h3>Cluster {cd["id"]} — {cd["photo_count"]} photos — Events: {", ".join(cd["events"])}</h3>')
        html.append(f'<div class="faces">')

        # Show face thumbnail
        face_path = os.path.join(OUTPUT_DIR, cd["thumbnail"].replace("/", os.sep))
        if os.path.exists(face_path):
            html.append(f'<img src="file:///{face_path}" style="border:2px solid gold">')

        # Show top 5 photo thumbnails
        for p in cd["photos"][:5]:
            if p["thumb"]:
                thumb_path = os.path.join(os.path.dirname(OUTPUT_DIR), p["thumb"].replace("/", os.sep))
                if os.path.exists(thumb_path):
                    html.append(f'<img src="file:///{thumb_path}">')

        html.append('</div></div>')

    html.append('</body></html>')

    with open(html_path, 'w') as f:
        f.write('\n'.join(html))
    print(f"Review HTML: {html_path}")


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Face Recognition Pipeline")
    parser.add_argument("--test", type=int, default=None, help="Test with N photos only")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--cluster-only", action="store_true", help="Re-cluster from saved embeddings")
    parser.add_argument("--gpu", type=int, default=0, help="GPU device ID")
    parser.add_argument("--eps", type=float, default=DBSCAN_EPS, help="DBSCAN eps parameter")
    args = parser.parse_args()

    cluster_eps = args.eps

    start_time = time.time()

    if args.cluster_only:
        # Just re-cluster from saved embeddings
        print("Loading saved embeddings...")
        with open(EMBEDDINGS_FILE, 'rb') as f:
            all_faces = pickle.load(f)
        photos = scan_photos(limit=args.test)
    else:
        # Step 1: Scan
        print("=" * 60)
        print("STEP 1: Scanning photos...")
        print("=" * 60)
        photos = scan_photos(limit=args.test)

        # Step 2: Detect faces
        print("\n" + "=" * 60)
        print("STEP 2: Detecting faces & extracting embeddings...")
        print("=" * 60)
        app = init_face_model(gpu_id=args.gpu)

        resume_from = 0
        if args.resume and os.path.exists(CHECKPOINT_FILE):
            with open(CHECKPOINT_FILE, 'rb') as f:
                existing = pickle.load(f)
            resume_from = max(f["photo_idx"] for f in existing) + 1 if existing else 0
            print(f"Resuming from photo {resume_from}")

        all_faces = extract_faces(app, photos, resume_from=resume_from)

    # Step 3: Cluster
    print("\n" + "=" * 60)
    print("STEP 3: Clustering faces...")
    print("=" * 60)
    sorted_clusters = cluster_faces(all_faces, eps=cluster_eps)

    # Step 4: Thumbnails
    print("\n" + "=" * 60)
    print("STEP 4: Generating thumbnails...")
    print("=" * 60)
    cluster_data = generate_thumbnails(all_faces, sorted_clusters)

    # Step 5: Export
    print("\n" + "=" * 60)
    print("STEP 5: Exporting data...")
    print("=" * 60)
    export_json(cluster_data, len(photos))
    generate_review_html(cluster_data, all_faces, sorted_clusters)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"DONE! Total time: {elapsed / 60:.1f} minutes")
    print(f"Clusters: {len(cluster_data)}")
    print(f"Total photos with faces: {sum(c['photo_count'] for c in cluster_data)}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

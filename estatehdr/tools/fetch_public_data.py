"""Download public, permissively licensed HDR test data and build test series.

Sources (see LICENSES.md / DECISIONS.md D-17):
  * OpenCV extra test data (Debevec 'Memorial Church' 16 exposures; St. Louis Arch 4 exposures,
    Wikimedia CC-BY-SA) - real multi-exposure captures, no EXIF in the PNGs;
  * Google HDR+ burst dataset (CC-BY-SA 4.0) - real RAW DNGs (Nexus 6).  From the HDR+ 'merged.dng'
    (high-SNR linear radiance of real interiors with windows) semi-synthetic bracket series are
    rendered with known exposures, noise, camera curve, handheld shake and EXIF.
  * The user's own portfolio photos from the surrounding website repository (single, finished
    images) - used only locally for the single-image 'do no harm' check.

Usage: python tools/fetch_public_data.py [--out data/public] [--skip-hdrplus]
"""
import argparse
import glob
import json
import os
import shutil
import sys
import urllib.request

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from estatehdr.synthetic import SeriesSpec, write_series  # noqa: E402

OPENCV_RAW = "https://raw.githubusercontent.com/opencv/opencv_extra/4.x/testdata/cv/hdr/exposures/"
HDRPLUS = "https://storage.googleapis.com/hdrplusdata/20171106_subset/"
# interiors with windows / mixed light picked from the HDR+ gallery
HDRPLUS_BURSTS = {
    "bar_windows": "6G7M_20150404_121844_208",
    "stair_window": "6G7M_20150404_132319_709",
    "modern_interior": "6G7M_20150415_185322_439",
    "piano_room": "9bf4_20150824_210544_967",
    "library": "4KK2_20150823_152106_985",
    "church": "0127_20161018_111029_303",
}


def fetch(url: str, path: str):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as fh:
        shutil.copyfileobj(r, fh, length=1 << 20)
    os.replace(tmp, path)
    return path


def opencv_sets(out: str):
    d = os.path.join(out, "opencv_raw")
    times = {}
    txt = fetch(OPENCV_RAW + "list.txt", os.path.join(d, "list.txt"))
    for line in open(txt):
        p = line.split()
        if len(p) == 2:
            times[p[0]] = float(p[1])
    for name in times:
        fetch(OPENCV_RAW + name, os.path.join(d, name))
    for i in range(1, 5):
        fetch(OPENCV_RAW + f"bug_18180/{i}.jpg", os.path.join(d, "stlouis", f"{i}.jpg"))
    # memorial: 3 frames 2 EV apart (no EXIF -> exposures must be estimated from pixels)
    inp = os.path.join(out, "opencv", "input")
    os.makedirs(inp, exist_ok=True)
    for k, name in enumerate(["memorial05.png", "memorial07.png", "memorial09.png"]):
        shutil.copy(os.path.join(d, name), os.path.join(inp, f"memorial_{k}.png"))
    for i in range(1, 5):
        shutil.copy(os.path.join(d, "stlouis", f"{i}.jpg"), os.path.join(inp, f"stlouis_{i}.jpg"))
    print("opencv sets ->", inp)


def hdrplus_sets(out: str, width: int):
    import rawpy
    import tifffile
    raw_dir = os.path.join(out, "hdrplus_raw")
    inp = os.path.join(out, "hdrplus_semi", "input")
    gt = os.path.join(out, "hdrplus_semi", "gt")
    single = os.path.join(out, "hdrplus_single", "input")
    os.makedirs(inp, exist_ok=True)
    os.makedirs(single, exist_ok=True)
    rng = np.random.default_rng(2024)
    idx = 0
    t0 = 10
    manifest = []
    for name, burst in HDRPLUS_BURSTS.items():
        merged = fetch(HDRPLUS + f"results_20171023/{burst}/merged.dng", os.path.join(raw_dir, burst, "merged.dng"))
        frame = fetch(HDRPLUS + f"bursts/{burst}/payload_N000.dng", os.path.join(raw_dir, burst, "payload_N000.dng"))
        # a real single RAW frame for the RAW / single-image path
        shutil.copy(frame, os.path.join(single, f"{name}.dng"))
        with rawpy.imread(merged) as r:
            lin = r.postprocess(gamma=(1, 1), no_auto_bright=True, output_bps=16, use_camera_wb=True,
                                output_color=rawpy.ColorSpace.sRGB).astype(np.float32) / 65535.0
        if width and lin.shape[1] > width:
            s = width / lin.shape[1]
            lin = cv2.resize(lin, (width, round(lin.shape[0] * s)), interpolation=cv2.INTER_AREA)
        y = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        # meter like a camera: put the median at ~10% (interiors), so windows clip in the 0 EV frame
        mid = 0.10 / max(float(np.median(y)), 1e-5)
        ser = SeriesSpec(evs=(-2, 0, 2), handheld=bool(idx % 2), start=f"2026-05-13T10:{t0:02d}:00",
                         mid_exposure=mid, base_shutter=1 / 60, focal_mm=4.67, iso=200)
        frames = write_series(lin, inp, "HDRP", ser, rng, start_index=idx)
        os.makedirs(os.path.join(gt, name), exist_ok=True)
        tifffile.imwrite(os.path.join(gt, name, "radiance_capture.tif"), lin, compression="zlib")
        with open(os.path.join(gt, name, "params.json"), "w") as fh:
            json.dump({"burst": burst, "frames": frames, "mid_exposure": mid}, fh, indent=1)
        manifest.append({"name": name, "files": [f["file"] for f in frames]})
        idx += 3
        t0 += 3
        print("hdrplus", name, lin.shape)
    with open(os.path.join(out, "hdrplus_semi", "manifest.json"), "w") as fh:
        json.dump({"series": manifest}, fh, indent=1)


def portfolio(out: str, site_root: str):
    """Largest JPEG/WebP variant of each portfolio photo of the surrounding site."""
    src = os.path.join(site_root, "_astro")
    if not os.path.isdir(src):
        return
    best = {}
    for f in glob.glob(os.path.join(src, "*")):
        if not f.lower().endswith((".jpg", ".webp")):
            continue
        key = os.path.basename(f).split("_")[0]
        im = cv2.imread(f)
        if im is None:
            continue
        if key not in best or im.shape[0] * im.shape[1] > best[key][1]:
            best[key] = (f, im.shape[0] * im.shape[1], im)
    d = os.path.join(out, "portfolio", "input")
    os.makedirs(d, exist_ok=True)
    for k, (f, _, im) in sorted(best.items()):
        cv2.imwrite(os.path.join(d, f"{k}.jpg"), im, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print("portfolio:", len(best), "images ->", d)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/public")
    ap.add_argument("--width", type=int, default=4208, help="downscale HDR+ radiance to this width (0 = native)")
    ap.add_argument("--skip-hdrplus", action="store_true")
    ap.add_argument("--site-root", default=os.path.join(os.path.dirname(__file__), "..", ".."))
    a = ap.parse_args()
    opencv_sets(a.out)
    if not a.skip_hdrplus:
        hdrplus_sets(a.out, a.width)
    portfolio(a.out, a.site_root)


if __name__ == "__main__":
    main()

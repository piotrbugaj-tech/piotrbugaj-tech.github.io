"""Performance and memory on large series (README section 6.6).

Three frames of the synthetic living room (EV -2, 0, +2) are upscaled to 24 Mpx (6000x4000 JPEG)
and 60 Mpx (9504x6336 JPEG and 16-bit TIFF, the TIFFs without EXIF) into data/perf24,
data/perf60 and data/perf60tiff (made once), and each series is processed alone with one worker.
Time, peak memory and stage timings come from report.json.  Writes reports/perf.json.

Usage (from the project root, after ``python tools/make_synthetic.py``):
  python tools/measure_perf.py [--only 24,60,60tiff]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

import cv2
import numpy as np
import tifffile
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = [os.path.join(ROOT, "data", "synthetic", "input", f"IMG_000{i}.jpg") for i in (1, 2, 3)]
SETS = {"24": ("3x24Mpx JPEG", (6000, 4000), "jpg"), "60": ("3x60Mpx JPEG", (9504, 6336), "jpg"),
        "60tiff": ("3x60Mpx TIFF 16-bit", (9504, 6336), "tif")}


def make_inputs(key: str) -> str:
    _, (w, h), fmt = SETS[key]
    d = os.path.join(ROOT, "data", f"perf{key}")
    if os.path.isdir(d) and len(os.listdir(d)) == len(SRC):
        return d
    os.makedirs(d, exist_ok=True)
    for i, src in enumerate(SRC, 1):
        im = cv2.resize(cv2.imread(src), (w, h), interpolation=cv2.INTER_CUBIC)
        dst = os.path.join(d, f"BIG_{i}.{fmt}")
        if fmt == "jpg":
            exif = Image.open(src).info.get("exif", b"")
            Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)).save(dst, quality=92, exif=exif)
        else:
            rgb16 = (cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.uint16) * 257)
            tifffile.imwrite(dst, rgb16, compression="zlib", photometric="rgb")
    return d


def machine() -> str:
    try:
        ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
    except (ValueError, OSError):
        ram = float("nan")
    gpu = "OpenCL dostępny" if cv2.ocl.haveOpenCL() else "bez GPU (OpenCL niedostępny)"
    return f"{os.cpu_count()} rdzenie CPU, {gpu}, {ram:.0f} GB RAM"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default=",".join(SETS))
    a = ap.parse_args(argv)
    path = os.path.join(ROOT, "reports", "perf.json")
    res = {"machine": machine(), "series": {}}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            res["series"] = json.load(fh).get("series", {})
    for key in [k.strip() for k in a.only.split(",") if k.strip()]:
        name, (w, h), _ = SETS[key]
        src = make_inputs(key)
        out = os.path.join(ROOT, "output", f"perf{key}")
        shutil.rmtree(out, ignore_errors=True)
        subprocess.run([sys.executable, "-m", "estatehdr", "process", src, "-o", out, "--workers", "1"],
                       cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(os.path.join(out, "report.json"), encoding="utf-8") as fh:
            rep = json.load(fh)
        s = rep["series"][0]
        res["series"][name] = {"frames": len(s.get("files", [])) or len(SRC), "width": w, "height": h,
                               "seconds": round(float(rep["seconds"]), 1),
                               "peak_rss_gb": round(float(rep.get("peak_rss_gb", 0.0)), 2),
                               "timings": {k: round(float(v), 1) for k, v in s.get("timings", {}).items()},
                               "device": s.get("device", "cpu")}
        print(name, json.dumps(res["series"][name]), flush=True)
        with open(path, "w", encoding="utf-8") as fh:  # after every series: a later failure keeps it
            json.dump(res, fh, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()

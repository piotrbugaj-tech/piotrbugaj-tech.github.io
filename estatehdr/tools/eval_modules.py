"""Reproducible measurements of the optional modules and of the lens CA estimate (README §6).

  removal  26 deterministic crops of the portfolio photos (or synthetic frames when the portfolio
           is missing); a hole is cut once in a homogeneous area and once at a random place and
           filled with the exemplar method and with Telea; CIEDE2000 inside the hole vs the original
  sky      sky detection on the 14 HDR+ exteriors (data/public/exteriors) and false detections on
           the 104 portfolio interiors
  ca       lateral CA estimate of the same linear scene saved as JPEG 4:4:4 and 4:2:0
Writes reports/modules_eval.json.

Usage (from the project root): python tools/eval_modules.py [--only removal,sky,ca]
"""
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from estatehdr.imgutil import linear_to_srgb, resize_max, rgb_to_lab, srgb_to_linear  # noqa: E402
from estatehdr.quality.metrics import delta_e2000  # noqa: E402

PORTFOLIO = os.path.join(ROOT, "data", "public", "portfolio", "input")
EXTERIORS = os.path.join(ROOT, "data", "public", "exteriors", "input")
SYN = os.path.join(ROOT, "data", "synthetic")


def _read(path, side=None):
    im = cv2.imread(path, cv2.IMREAD_COLOR)
    if im is None:
        return None
    im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return resize_max(im, side)[0] if side else im


def _sources(n=26):
    files = sorted(glob.glob(os.path.join(PORTFOLIO, "*")))
    if not files:
        files = sorted(glob.glob(os.path.join(SYN, "input", "IMG_00*.jpg")))
    step = max(1, len(files) // n)
    return files[::step][:n]


def _de(a, b, m):
    return float(delta_e2000(rgb_to_lab(srgb_to_linear(a[m])), rgb_to_lab(srgb_to_linear(b[m]))).mean())


def eval_removal():
    from estatehdr.modules.remove import remove_objects
    rng = np.random.default_rng(2024)
    rows = []
    for path in _sources():
        img = _read(path, 640)
        if img is None:
            continue
        h, w = img.shape[:2]
        y = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        grad = cv2.GaussianBlur(np.abs(cv2.Laplacian(y, cv2.CV_32F)), (0, 0), 9)
        rh, rw = int(0.16 * h), int(0.16 * w)
        inner = grad[rh // 2 + 8:h - rh // 2 - 8, rw // 2 + 8:w - rw // 2 - 8]
        cy, cx = np.unravel_index(int(np.argmin(inner)), inner.shape)  # most homogeneous place
        places = {"homogeneous": (cy + 8, cx + 8),
                  "random": (int(rng.integers(8, h - rh - 8)), int(rng.integers(8, w - rw - 8)))}
        for kind, (y0, x0) in places.items():
            mask = np.zeros((h, w), np.uint8)
            cv2.ellipse(mask, (x0 + rw // 2, y0 + rh // 2), (rw // 2, rh // 2), 0, 0, 360, 255, -1)
            m = mask > 0
            res = {}
            for method in ("patch", "telea"):
                out, _ = remove_objects(img.copy(), mask, {"modules": {"remove": {"method": method}}}, seed=1)
                res[method] = _de(out, img, m)
            rows.append({"file": os.path.basename(path), "place": kind, **res})
    agg = {}
    for kind in ("homogeneous", "random"):
        sel = [r for r in rows if r["place"] == kind]
        if sel:
            agg[kind] = {m: round(float(np.mean([r[m] for r in sel])), 3) for m in ("patch", "telea")}
            agg[kind]["patch_better"] = int(sum(r["patch"] < r["telea"] for r in sel))
            agg[kind]["n"] = len(sel)
    return {"images": len({r["file"] for r in rows}), "mean_de2000_in_hole": agg, "rows": rows}


def eval_sky():
    from estatehdr.modules.sky import detect_sky
    out = {}
    for name, folder in (("exteriors", EXTERIORS), ("portfolio_interiors", PORTFOLIO)):
        files = sorted(glob.glob(os.path.join(folder, "*")))
        det = []
        for f in files:
            im = _read(f, 1000)
            if im is None:
                continue
            m, info = detect_sky(im)
            det.append({"file": os.path.basename(f), "sky": m is not None,
                        "frac": None if m is None else round(float((m > 0.5).mean()), 3),
                        "reason": info.get("reason")})
        out[name] = {"images": len(det), "with_sky": int(sum(d["sky"] for d in det)), "rows": det}
    return out


def eval_ca():
    import tifffile
    from estatehdr.lens import estimate_ca
    res = {}
    for scene in ("living_room", "bedroom", "kitchen"):
        p = os.path.join(SYN, "gt", scene, "radiance_capture.tif")
        if not os.path.exists(p):
            continue
        rad = tifffile.imread(p).astype(np.float32)
        x = np.clip(rad * (0.18 / float(np.median(rad.mean(-1)))), 0, 1)
        bgr = cv2.cvtColor((linear_to_srgb(x) * 255 + 0.5).astype(np.uint8), cv2.COLOR_RGB2BGR)
        r = {"linear": [round(float(v), 5) for v in estimate_ca(x)[:2]]}
        for nm, flag in (("jpeg_444", cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444),
                         ("jpeg_420", cv2.IMWRITE_JPEG_SAMPLING_FACTOR_420)):
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 95, cv2.IMWRITE_JPEG_SAMPLING_FACTOR, flag])
            d = cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            r[nm] = [round(float(v), 5) for v in estimate_ca(srgb_to_linear(d))[:2]]
        res[scene] = r
    return {"truth": [1.0012, 0.9988], "scenes": res}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="removal,sky,ca")
    a = ap.parse_args(argv)
    path = os.path.join(ROOT, "reports", "modules_eval.json")
    res = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            res = json.load(fh)
    for part in [p.strip() for p in a.only.split(",") if p.strip()]:
        res[part] = {"removal": eval_removal, "sky": eval_sky, "ca": eval_ca}[part]()
        print(part, json.dumps({k: v for k, v in res[part].items() if k != "rows"}, default=str)[:1500], flush=True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=float)


if __name__ == "__main__":
    main()

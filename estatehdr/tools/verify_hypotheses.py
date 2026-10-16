"""Black-box verification experiments for REVERSE.md section 7 (measured on our data).

  A grouping with EXIF vs the same frames without EXIF (visual only)
  B merging 3 frames vs all frames (radiance error and shadow noise vs ground truth)
  C alignment error vs ground-truth homographies (handheld series, full resolution)
  D window view when the darkest frame is clipped (unrecoverable vs output clipping)
  E geometry: estimated k1 / pitch / roll vs ground truth, crop
  F lens: chromatic aberration estimate vs ground truth
  G sky mask IoU vs ground-truth labels
  H noise before / after on single noisy RAW frames (HDR+)

Usage (from the project root, after ``python tools/make_synthetic.py``):
  python tools/verify_hypotheses.py [OUTPUT_DIR]
OUTPUT_DIR is a processed synthetic batch (report.json + quality.json) used by D, E and F; when it
is not given (default output/verify_synthetic) or holds no report.json, the synthetic batch is run
into it (preset neutral) and evaluated against the synthetic ground truth (quality.json, as
tools/evaluate.py does).  Writes reports/verification.json.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

import cv2
import numpy as np
import tifffile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from estatehdr import align, merge  # noqa: E402
from estatehdr.config import load_config  # noqa: E402
from estatehdr.denoise import estimate_sigma  # noqa: E402
from estatehdr.grouping import scan_folder  # noqa: E402
from estatehdr.imgutil import LUMA, linear_to_srgb, luminance, resize_max  # noqa: E402
from estatehdr.io.metadata import read_metadata  # noqa: E402
from estatehdr.series import load_series  # noqa: E402

SYN = os.path.join(ROOT, "data", "synthetic")
OUT = os.path.join(ROOT, "reports")
DEFAULT_BATCH = os.path.join(ROOT, "output", "verify_synthetic")


def gt_params(scene):
    with open(os.path.join(SYN, "gt", scene, "params.json")) as fh:
        return json.load(fh)


def exp_grouping(cfg):
    with open(os.path.join(SYN, "manifest.json")) as fh:
        man = json.load(fh)
    want = [s["files"] for s in man["series"]] + [man["extras"]["noexif_incomplete"]]

    def score(folder, rename=lambda f: f):
        groups, _ = scan_folder(folder, cfg["grouping"])
        got = [[os.path.basename(f.path) for f in g.frames] for g in groups]
        ok = sum(1 for w in want if [rename(f) for f in w] in got)
        return ok, len(want), len(groups)
    with_exif = score(os.path.join(SYN, "input"))
    tmp = tempfile.mkdtemp()
    try:
        for f in sorted(os.listdir(os.path.join(SYN, "input"))):
            src = os.path.join(SYN, "input", f)
            dst = os.path.join(tmp, os.path.splitext(f)[0] + ".png")  # PNG: pixels only, no EXIF
            if f.endswith(".tif"):
                im = tifffile.imread(src)
                cv2.imwrite(dst, cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
            else:
                im = cv2.imread(src)
                if im is not None:
                    cv2.imwrite(dst, im)
        no_exif = score(tmp, lambda f: os.path.splitext(f)[0] + ".png")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"with_exif": {"series_exact": with_exif[0], "of": with_exif[1], "groups": with_exif[2]},
            "without_exif": {"series_exact": no_exif[0], "of": no_exif[1], "groups": no_exif[2]}}


def _merge_error(cfg, scene, files):
    s = load_series(scene, [read_metadata(os.path.join(SYN, "input", f)) for f in files], cfg)
    if len(s.frames) > 1:
        align.align_series(s, cfg["align"])
    m = merge.merge_series(s, cfg)
    gt = tifffile.imread(os.path.join(SYN, "gt", scene, "radiance_capture.tif")).astype(np.float32)
    lab = cv2.imread(os.path.join(SYN, "gt", scene, "labels_capture.png"), cv2.IMREAD_GRAYSCALE)
    yg, ym = luminance(gt), luminance(m.radiance)
    ok = (m.clipped < 0.01) & (lab != 4) & (yg > 1e-6)
    ok = cv2.erode(ok.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    r = np.log2(np.maximum(ym, 1e-7)) - np.log2(np.maximum(yg, 1e-7))
    r -= np.median(r[ok])
    dark = ok & (yg < np.percentile(yg[ok], 15))
    hp = r - cv2.GaussianBlur(r, (0, 0), 2.0)
    return {"frames": len(files), "median_abs_log2_err": float(np.median(np.abs(r[ok]))),
            "shadow_noise_log2": float(np.std(hp[dark])), "dynamic_range_ev": m.stats.get("dynamic_range_ev")}


def exp_three_of_n(cfg):
    out = {}
    for scene in ("kitchen", "living_room"):
        p = gt_params(scene)
        frames = sorted(p["frames"], key=lambda f: f["ev"])
        allf = [f["file"] for f in frames]
        mid = len(frames) // 2
        sub3 = [frames[0]["file"], frames[mid]["file"], frames[-1]["file"]]
        near3 = [frames[mid - 1]["file"], frames[mid]["file"], frames[mid + 1]["file"]]
        out[scene] = {"all": _merge_error(cfg, scene, allf), "3_extremes": _merge_error(cfg, scene, sub3),
                      "3_central": _merge_error(cfg, scene, near3)}
    return out


def exp_alignment(cfg):
    out = {}
    for scene in ("bedroom", "living_room"):
        p = gt_params(scene)
        s = load_series(scene, [read_metadata(os.path.join(SYN, "input", f["file"])) for f in p["frames"]], cfg)
        align.align_series(s, cfg["align"])
        H = [np.array(f["homography"]) for f in p["frames"]]
        w, h = p["camera"]["width"], p["camera"]["height"]
        pts = np.array([[x, y, 1.0] for x in np.linspace(50, w - 50, 9) for y in np.linspace(50, h - 50, 7)]).T
        errs = []
        for i, f in enumerate(s.frames):
            if i == s.ref:
                continue
            E = H[i] @ np.linalg.inv(H[s.ref])
            a, b = f.homography @ pts, E @ pts
            e = np.hypot(*(a[:2] / a[2] - b[:2] / b[2]))
            shift = np.hypot(*(b[:2] / b[2] - pts[:2]))
            errs.append({"frame": f.meta.name, "true_shift_px": float(shift.mean()), "mean_err_px": float(e.mean()),
                         "max_err_px": float(e.max())})
        out[scene] = errs
    return out


def exp_from_outputs(out_dir):
    """D, E, F from a processed synthetic batch (report.json + quality.json)."""
    with open(os.path.join(out_dir, "report.json")) as fh:
        rep = json.load(fh)
    q = {}
    if os.path.exists(os.path.join(out_dir, "quality.json")):
        with open(os.path.join(out_dir, "quality.json")) as fh:
            q = json.load(fh)
    with open(os.path.join(SYN, "manifest.json")) as fh:
        man = json.load(fh)
    scene_of = {s["files"][0]: s["name"] for s in man["series"]}
    win, geo, ca = {}, {}, {}
    for s in rep["series"]:
        if s["status"] != "ok":
            continue
        scene = scene_of.get(os.path.basename(s["files"][0]))
        if scene not in ("living_room", "bedroom", "kitchen"):
            continue
        cam = gt_params(scene)["camera"]
        g = s.get("geometry", {})
        v = g.get("verticals", {})
        geo[scene] = {"k1_true": cam["k1"], "k1_est": g.get("distortion", {}).get("k1"),
                      "pitch_true": cam["pitch_deg"], "pitch_correction": v.get("pitch_deg"),
                      "roll_true": cam["roll_deg"], "roll_correction": v.get("roll_deg"),
                      "crop_fraction": g.get("crop_fraction"),
                      "vert_med_deg_after": q.get(s["name"], {}).get("summary", {}).get("vert_med_deg")}
        ca[scene] = {"ca_true": cam["ca"], "scales_est": s.get("lens", {}).get("ca_scales")}
        w = q.get(s["name"], {}).get("windows_gt", {})
        win[scene] = {"unrecoverable_pct": w.get("unrecoverable_pct"), "output_clipped_pct": w.get("clipped_pct"),
                      "recoverable_clipped_pct": w.get("clipped_recoverable_pct"),
                      "view_L": w.get("L_mean_unclipped"), "detail_ratio": w.get("detail_ratio_vs_ref"),
                      "halo_dL": q.get(s["name"], {}).get("halo_windows", {}).get("halo_dL")}
    return win, geo, ca


def exp_sky(cfg):
    from estatehdr.modules.sky import detect_sky
    from estatehdr.synthetic import render_exterior
    from estatehdr.tonemap import tone_map
    rad, lab = render_exterior(1200, 800, supersample=1)
    img = tone_map(rad, dict(cfg["tonemap"]), analysis_side=1200)
    m, info = detect_sky(resize_max(img, 1000)[0])
    gt = cv2.resize(lab, (m.shape[1], m.shape[0]), interpolation=cv2.INTER_NEAREST) == 9
    pred = m > 0.5
    return {"synthetic_iou": float((gt & pred).sum() / max((gt | pred).sum(), 1))}


def exp_noise(cfg):
    from estatehdr.batch import run_batch
    src = os.path.join(ROOT, "data", "public", "hdrplus_single", "input")
    if not os.path.isdir(src):
        return None
    out = tempfile.mkdtemp()
    try:
        rep = run_batch(src, out, load_config(None, None, ["grouping.mode=single"]))
        res = []
        for s in rep["series"]:
            if s["status"] != "ok":
                continue
            from estatehdr.io.reader import decode
            meta = read_metadata(s["files"][0])
            d = decode(meta.path, meta.orientation, half=True)
            lin = d.as_float()
            k = 0.18 / max(float(np.median(lin @ LUMA)), 1e-4)
            naive = linear_to_srgb(np.clip(lin * k, 0, 1))  # camera-like straight render
            after = cv2.cvtColor(cv2.imread(s["outputs"]["full"]["path"]), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
            a = resize_max(naive, 1600)[0]
            b = resize_max(after, 1600)[0]
            res.append({"name": s["name"], "sigma_before": estimate_sigma(a @ LUMA), "sigma_after": estimate_sigma(b @ LUMA)})
        return res
    finally:
        shutil.rmtree(out, ignore_errors=True)


def ensure_synthetic_batch(out_dir: str) -> str:
    """Processed synthetic batch with quality.json in ``out_dir`` (run + evaluated when missing)."""
    if not os.path.isdir(os.path.join(SYN, "input")):
        sys.exit(f"no synthetic dataset in {SYN} - run: python tools/make_synthetic.py")
    rp = os.path.join(out_dir, "report.json")
    complete = False
    if os.path.exists(rp):
        with open(rp, encoding="utf-8") as fh:
            rep = json.load(fh)
        complete = rep.get("complete", True) and not rep.get("pending")
    if not complete:  # missing or interrupted batch (report.json is written after every series)
        if os.path.exists(os.path.join(out_dir, "quality.json")):
            os.remove(os.path.join(out_dir, "quality.json"))
        from estatehdr.batch import run_batch
        print(f"running the synthetic batch into {out_dir} ...")
        run_batch(os.path.join(SYN, "input"), out_dir, load_config(None, "neutral"))
    if not os.path.exists(os.path.join(out_dir, "quality.json")):
        from estatehdr.quality.evaluate import evaluate_output_dir
        from tools.evaluate import synthetic_gt_map
        res = evaluate_output_dir(out_dir, synthetic_gt_map(SYN, out_dir))
        with open(os.path.join(out_dir, "quality.json"), "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1, default=float)
    return out_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("output_dir", nargs="?", default=DEFAULT_BATCH,
                    help="processed synthetic batch (created when it has no report.json)")
    a = ap.parse_args(argv)
    out_dir = ensure_synthetic_batch(os.path.abspath(a.output_dir))
    cfg = load_config(None, "neutral")
    R = {"grouping": exp_grouping(cfg)}
    print("A done", R["grouping"])
    R["three_of_n"] = exp_three_of_n(cfg)
    print("B done")
    R["alignment"] = exp_alignment(cfg)
    print("C done")
    R["windows"], R["geometry"], R["lens_ca"] = exp_from_outputs(out_dir)
    R["sky"] = exp_sky(cfg)
    R["noise_single_raw"] = exp_noise(cfg)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "verification.json"), "w", encoding="utf-8") as fh:
        json.dump(R, fh, indent=1, default=float)
    print(json.dumps(R, indent=1, default=float)[:6000])


if __name__ == "__main__":
    main()

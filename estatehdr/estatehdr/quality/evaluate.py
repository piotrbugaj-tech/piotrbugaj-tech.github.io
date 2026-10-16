"""Evaluation of processed images (used by tools/evaluate.py, tools/calibrate.py and tests).

For every output image:
  histogram + clipping/crushing, verticality, white-wall neutrality, window brightness/detail,
  halo index, noise, sharpness;
and when a reference is available (synthetic ground truth or an AutoHDR result of the same
series): SSIM, CIEDE2000 and LPIPS after geometric registration (outputs may be cropped or
straightened differently).
"""
from __future__ import annotations

import json
import os

import cv2
import numpy as np

from . import metrics as M
from ..imgutil import resize_max

# synthetic GT labels (see estatehdr/synthetic.py LABELS)
WALL_LABELS = (1, 2)
WINDOW_LABEL = 4
LAMP_LABEL = 7


def load_rgb(path: str, max_side: int | None = None) -> np.ndarray:
    im = cv2.imread(path, cv2.IMREAD_COLOR)
    if im is None:
        raise FileNotFoundError(path)
    im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    if max_side:
        im, _ = resize_max(im, max_side)
    return im


def evaluate_image(img: np.ndarray, reference: np.ndarray | None = None, labels: np.ndarray | None = None,
                   unrecoverable_frac: float = 0.0, window_unrecoverable_pct: float | None = None) -> dict:
    """img/reference: sRGB float [0,1]; labels (synthetic GT) in reference geometry.
    window_unrecoverable_pct: % of the window view clipped even in the darkest frame (GT)."""
    out = {"histogram": M.histogram_stats(img), "verticality": M.verticality(img),
           "noise_sigma": M.noise_sigma(img), "sharpness": M.sharpness(img)}
    h = out["histogram"]
    out["histogram"]["clipped_excl_unrecoverable_pct"] = max(0.0, h["clipped_pct"] - 100 * unrecoverable_frac)
    out["neutrality_auto"] = M.neutrality(img)
    if reference is not None:
        warped, valid = M.register(img, reference)
        out["vs_reference"] = {"ssim": M.ssim(warped, reference, valid), "ms_ssim": M.ms_ssim(warped, reference, valid),
                               "grad_ssim": M.gradient_ssim(warped, reference, valid),
                               **{f"de_{k}": v for k, v in
                                                                            M.delta_e_images(warped, reference, valid).items()},
                               "lpips": M.lpips_distance(np.where(valid[..., None], warped, reference), reference),
                               "registered_frac": float(valid.mean())}
        if labels is not None:
            lab = cv2.resize(labels, (reference.shape[1], reference.shape[0]), interpolation=cv2.INTER_NEAREST)
            walls = np.isin(lab, WALL_LABELS) & valid
            walls = cv2.erode(walls.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
            out["neutrality_walls_gt"] = M.neutrality(warped, walls)
            win = (lab == WINDOW_LABEL) & valid
            out["windows_gt"] = M.window_metrics(warped, win, reference)
            if window_unrecoverable_pct is not None and out["windows_gt"].get("clipped_pct") is not None:
                out["windows_gt"]["unrecoverable_pct"] = window_unrecoverable_pct
                out["windows_gt"]["clipped_recoverable_pct"] = max(
                    0.0, out["windows_gt"]["clipped_pct"] - window_unrecoverable_pct)
            out["halo_windows"] = M.halo_index(warped, (lab == WINDOW_LABEL))
            lamps = (lab == LAMP_LABEL)
            lamps = cv2.dilate(lamps.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
            any8 = np.round(warped * 255).max(-1) >= 254
            nonlight = valid & ~lamps & ~win
            out["histogram"]["clipped_nonlight_gt_pct"] = float(100 * any8[nonlight].mean()) if nonlight.any() else None
    return out


def summarize(res: dict) -> dict:
    """Flat dict of headline numbers (for tables)."""
    h = res["histogram"]
    v = res["verticality"]
    s = {"clipped_%": h["clipped_pct"], "clipped_excl_%": h["clipped_excl_unrecoverable_pct"],
         "crushed_%": h["crushed_pct"], "median_luma": h["p50"],
         "vert_med_deg": v.get("median_abs_deg"), "vert_p90_deg": v.get("p90_abs_deg"),
         "wall_dE_auto": res["neutrality_auto"].get("delta_e_mean"), "noise": res["noise_sigma"],
         "sharpness": res["sharpness"]}
    if "neutrality_walls_gt" in res:
        s["wall_dE_gt"] = res["neutrality_walls_gt"].get("delta_e_mean")
        s["wall_L_gt"] = res["neutrality_walls_gt"].get("L_median")
    if "windows_gt" in res:
        w = res["windows_gt"]
        s["win_L"] = w.get("L_mean_unclipped", w.get("L_mean"))
        s["win_clip_%"] = w.get("clipped_pct")
        if "clipped_recoverable_pct" in w:
            s["win_clip_recov_%"] = w["clipped_recoverable_pct"]
        s["win_detail_ratio"] = w.get("detail_ratio_vs_ref")
    if "halo_windows" in res:
        s["halo_dL"] = res["halo_windows"].get("halo_dL")
    if "histogram" in res and res["histogram"].get("clipped_nonlight_gt_pct") is not None:
        s["clipped_nonlight_%"] = res["histogram"]["clipped_nonlight_gt_pct"]
    if "vs_reference" in res:
        r = res["vs_reference"]
        s["ssim"] = r["ssim"]
        s["ms_ssim"] = r.get("ms_ssim")
        s["grad_ssim"] = r.get("grad_ssim")
        s["dE_ref"] = r["de_mean"]
        s["lpips"] = r["lpips"]
    return s


def window_unrecoverable(gt_dir: str, frame_paths: list[str]) -> float | None:
    """% of the GT window area clipped in the darkest frame of the series (capture geometry)."""
    lp = os.path.join(gt_dir, "labels_capture.png")
    if not os.path.exists(lp) or not frame_paths:
        return None
    lab = cv2.imread(lp, cv2.IMREAD_GRAYSCALE)
    win = lab == WINDOW_LABEL
    if win.sum() < 50:
        return None
    from ..io.metadata import read_metadata
    from ..io.reader import decode
    metas = [read_metadata(p) for p in frame_paths]
    evs = [m.exposure_value for m in metas]
    if any(e is None for e in evs):
        return None
    m = metas[int(np.argmin(evs))]
    d = decode(m.path, m.orientation)
    im = cv2.resize(d.as_float(), (lab.shape[1], lab.shape[0]), interpolation=cv2.INTER_AREA)
    return float(100 * (im.max(-1)[win] >= 0.98).mean())


def evaluate_output_dir(out_dir: str, gt_map: dict | None = None, pairs_dir: str | None = None,
                        size: str = "full", max_side: int = 2048) -> dict:
    """Evaluate all series of a batch output directory.

    gt_map: series name -> GT scene directory (synthetic: reference_ideal.png, labels_ideal.png)
    pairs_dir: folder with reference results named like the series (e.g. AutoHDR exports)."""
    with open(os.path.join(out_dir, "report.json"), encoding="utf-8") as fh:
        report = json.load(fh)
    results = {}
    for s in report["series"]:
        if s.get("status") != "ok" or size not in s.get("outputs", {}):
            continue
        img = load_rgb(s["outputs"][size]["path"], max_side)
        ref = labels = None
        win_unrec = None
        if gt_map and s["name"] in gt_map:
            try:
                win_unrec = window_unrecoverable(gt_map[s["name"]], s.get("files", []))
            except Exception:
                win_unrec = None
            gdir = gt_map[s["name"]]
            rp = os.path.join(gdir, "reference_ideal.png")
            if os.path.exists(rp):
                ref = load_rgb(rp, max_side)
                lp = os.path.join(gdir, "labels_ideal.png")
                labels = cv2.imread(lp, cv2.IMREAD_GRAYSCALE) if os.path.exists(lp) else None
        if pairs_dir:
            cand = [f for f in os.listdir(pairs_dir) if os.path.splitext(f)[0].startswith(s["name"])]
            if cand:
                ref = load_rgb(os.path.join(pairs_dir, sorted(cand)[0]), max_side)
        unrec = float(s.get("merge", {}).get("darkest_clipped_frac", 0.0) or 0.0)
        res = evaluate_image(img, ref, labels, unrec, win_unrec)
        res["summary"] = summarize(res)
        results[s["name"]] = res
    return results


def markdown_table(results: dict, columns: list[str] | None = None) -> str:
    if not results:
        return "(brak wyników)\n"
    cols = columns or list(next(iter(results.values()))["summary"].keys())
    lines = ["| seria | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for name, r in results.items():
        vals = []
        for c in cols:
            v = r["summary"].get(c)
            vals.append("—" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v)))
        lines.append(f"| {name} | " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"

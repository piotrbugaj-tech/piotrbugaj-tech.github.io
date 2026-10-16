"""Black-box verification experiments for REVERSE.md section 7 (measured on our data).

  A grouping with EXIF vs the same frames without EXIF (visual only)
  B merging 3 frames vs all frames (radiance error and shadow noise vs ground truth)
  C alignment error vs ground-truth homographies (handheld series, full resolution)
  D window view when the darkest frame is clipped (unrecoverable vs output clipping)
  E geometry: estimated k1 / pitch / roll vs ground truth, crop
  F lens: chromatic aberration estimate vs ground truth
  G sky mask IoU vs ground-truth labels
  H noise before / after on single noisy RAW frames (HDR+)
  I SPEC.md acceptance criteria without a number elsewhere ("spec_extras"): relative exposures
    with / without EXIF (SPEC 3), ghost residue of a moving object (4), alignment with 15-20 px
    hand-held shifts (4), window mask IoU (6), wall neutrality in the tungsten zone and accent
    hue (7), contrast-invariant edge sharpness output / input (9), clipped / crushed pixels in
    single-frame mode (10)

Usage (from the project root, after ``python tools/make_synthetic.py``):
  python tools/verify_hypotheses.py [OUTPUT_DIR] [--only LETTERS [--parts PART,...]]
OUTPUT_DIR is a processed synthetic batch (report.json + quality.json) used by D, E, F and I; when it
is not given (default output/verify_synthetic) or holds no report.json, the synthetic batch is run
into it (preset neutral) and evaluated against the synthetic ground truth (quality.json, as
tools/evaluate.py does).  Writes reports/verification.json.  ``--only I`` (or e.g. ``--only A,C``)
runs just those experiments and merges their keys into the existing reports/verification.json;
``--only I --parts single_frame`` recomputes only that part of "spec_extras".
"""
import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import time

import cv2
import numpy as np
import tifffile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from estatehdr import align, merge  # noqa: E402
from estatehdr.config import load_config  # noqa: E402
from estatehdr.denoise import estimate_sigma  # noqa: E402
from estatehdr.grouping import scan_folder  # noqa: E402
from estatehdr.imgutil import LUMA, chmax, linear_to_srgb, luminance, resize_max, rgb_to_lab, srgb_to_linear  # noqa: E402
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


def _model_info(info):
    """Motion model the alignment used for a frame (align.model auto: the per-frame choice) + evidence."""
    sel = info.get("model_select") or {}
    return {"model": info.get("model"), **({"model_llr": sel.get("llr"), "model_corner_diff_px": sel.get("corner_diff_px")}
                                           if sel else {})}


def exp_alignment(cfg, models=()):
    """Per frame grid error vs GT with the configured align.model; ``models``: the same series also
    aligned with these explicit models (summary per model under the key "models")."""
    out, cmp_ = {}, {}
    for scene in ("bedroom", "living_room"):
        p = gt_params(scene)
        s = load_series(scene, [read_metadata(os.path.join(SYN, "input", f["file"])) for f in p["frames"]], cfg)
        H = [np.array(f["homography"]) for f in p["frames"]]
        w, h = p["camera"]["width"], p["camera"]["height"]
        pts = np.array([[x, y, 1.0] for x in np.linspace(50, w - 50, 9) for y in np.linspace(50, h - 50, 7)]).T
        for model in (None, *models):
            acfg = dict(cfg["align"], **({"model": model} if model else {}))
            infos = align.align_series(s, acfg)
            errs = []
            for i, f in enumerate(s.frames):
                if i == s.ref:
                    continue
                E = H[i] @ np.linalg.inv(H[s.ref])
                a, b = f.homography @ pts, E @ pts
                e = np.hypot(*(a[:2] / a[2] - b[:2] / b[2]))
                shift = np.hypot(*(b[:2] / b[2] - pts[:2]))
                errs.append({"frame": f.meta.name, "true_shift_px": float(shift.mean()), "mean_err_px": float(e.mean()),
                             "max_err_px": float(e.max()), **_model_info(infos[i])})
            if model is None:
                out[scene] = errs
            else:
                cmp_.setdefault(model, {})[scene] = [{k: e[k] for k in ("frame", "mean_err_px", "max_err_px")} for e in errs]
    return out, cmp_


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


# ---------------------------------------------------------------------------
# I: SPEC acceptance criteria that have no number elsewhere (key "spec_extras")
# ---------------------------------------------------------------------------
GT_SCENES = ("living_room", "bedroom", "kitchen")
SPEC_PARTS = ("exposures", "ghost", "window_iou", "alignment_20px", "white_balance", "sharpness", "single_frame")
# moving object of the bedroom series, as synthetic.generate_dataset draws it (frame i -> centre_xs[i])
GHOST = dict(center_xs=[0.30, 0.38, 0.46, 0.54, 0.62], cy=0.62, rx=0.035, ry=0.10, color=(0.05, 0.07, 0.12))
K9 = np.ones((9, 9), np.uint8)
# GT motion of the non-reference frames in the 20 px alignment test (about the image centre):
# tx, ty [px], rotation [deg], perspective h31, h32 [1/px]
ALIGN20_MOVES = [(17, -8, 0.30, 2e-6, -1.5e-6), (-12, 14, -0.30, -2e-6, 1e-6), (15, 11, 0.25, 1.5e-6, 2e-6),
                 (-16, -10, -0.35, -1e-6, -2e-6)]


def _iou(a, b):
    return float((a & b).sum() / max((a | b).sum(), 1))


def _ref_index(s, p):
    """Index (in params.json frames) of the frame the pipeline chose as reference."""
    return [f["file"] for f in p["frames"]].index(s.frames[s.ref].meta.name)


def _to_ref(img, H, interp=cv2.INTER_NEAREST):
    """Capture-geometry (GT radiance) image -> geometry of the frame with GT homography H."""
    if np.allclose(H, np.eye(3)):
        return img
    return cv2.warpPerspective(img, H, (img.shape[1], img.shape[0]), flags=interp, borderMode=cv2.BORDER_REFLECT)


def _window_gt(lab):
    """GT glass (label 4) and glass + its frame: components of labels 4|5 that contain glass
    (the door is also labelled 5 and is left out)."""
    glass = lab == 4
    _, cc = cv2.connectedComponents(np.isin(lab, (4, 5)).astype(np.uint8))
    return glass, np.isin(cc, np.unique(cc[glass])) & (cc > 0)


def _display_frame(path, crf_model=None):
    """Frame as shot, display-referred float RGB at full resolution (the pipeline's before preview:
    a linear frame is scaled to a 0.18 median and sRGB-encoded)."""
    from estatehdr.io.reader import decode
    m = read_metadata(path)
    d = decode(m.path, m.orientation)
    img = d.as_float()
    if d.encoding == "linear" or crf_model == "linear":
        k = 0.18 / max(float(np.median(img @ LUMA)), 1e-4)
        img = linear_to_srgb(np.clip(img * k, 0, 1))
    return img


def _exposure_errors(s, p):
    ev = {f["file"]: f["ev"] for f in p["frames"]}
    ref_ev = ev[s.frames[s.ref].meta.name]
    rows = []
    for f in s.frames:
        gt, est = ev[f.meta.name] - ref_ev, float(np.log2(f.exposure))
        rows.append({"frame": f.meta.name, "gt_ev": gt, "est_ev": round(est, 4), "err_ev": round(est - gt, 4)})
    return {"reference": s.frames[s.ref].meta.name, "max_abs_err_ev": max(abs(r["err_ev"]) for r in rows), "frames": rows}


def _spec_exposures_noexif(cfg):
    """Same frames with the EXIF removed (JPEG: EXIF segment stripped, bitstream unchanged; TIFF:
    rewritten without tags), so exposures must come from the pixels."""
    import piexif
    out = {}
    tmp = tempfile.mkdtemp()
    try:
        for scene in GT_SCENES:
            p = gt_params(scene)
            metas = []
            for f in p["frames"]:
                src, dst = os.path.join(SYN, "input", f["file"]), os.path.join(tmp, f["file"])
                if f["file"].endswith(".tif"):
                    tifffile.imwrite(dst, tifffile.imread(src), photometric="rgb")
                else:
                    shutil.copyfile(src, dst)
                    piexif.remove(dst)
                metas.append(read_metadata(dst))
            assert all(m.exposure_value is None for m in metas)
            s = load_series(scene, metas, cfg)
            out[scene] = {**_exposure_errors(s, p), "crf": s.crf}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _ghost_residue(cfg, s, p, m, iref, lab):
    """Merged radiance vs GT radiance with the object at the reference frame's position (bedroom)."""
    from estatehdr.synthetic import moving_object
    gt = tifffile.imread(os.path.join(SYN, "gt", "bedroom", "radiance_capture.tif")).astype(np.float32)
    h, w = gt.shape[:2]
    fn = moving_object(GHOST["center_xs"], GHOST["cy"], GHOST["rx"], GHOST["ry"], GHOST["color"])
    Href = np.array(p["frames"][iref]["homography"])
    gt_ref = _to_ref(fn(gt, iref), Href, cv2.INTER_LINEAR)
    del gt
    zero = np.zeros((h, w, 3), np.float32)
    foot = [_to_ref(fn(zero, i)[..., 2] / GHOST["color"][2], Href, cv2.INTER_LINEAR) > 0.5 for i in range(len(p["frames"]))]
    mask = np.logical_or.reduce(foot)
    e_min = p["series"]["mid_exposure"] * 2.0 ** min(f["ev"] for f in p["frames"])
    gt_clip = chmax(gt_ref) * e_min >= 0.95  # saturated even in the darkest frame
    yg = luminance(gt_ref)
    near = cv2.dilate(mask.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)

    def residue(mm):
        valid = (mm.clipped < 0.01) & ~gt_clip & (yg > 1e-6)
        ok = valid & ~near & (lab != 4)
        ry = np.log2(np.maximum(luminance(mm.radiance), 1e-7)) - np.log2(np.maximum(yg, 1e-7))
        k = np.median(ry[ok])
        ry = np.abs(ry - k)
        rc = np.abs(np.log2(np.maximum(mm.radiance, 1e-7)) - np.log2(np.maximum(gt_ref, 1e-7)) - k).max(-1)
        sel = mask & valid
        own, other = sel & foot[iref], sel & ~foot[iref]
        frac = lambda r, m: float((r[m] > 0.5).mean()) if m.any() else None  # noqa: E731
        return {"ghost_mask_px": int(mask.sum()), "excluded_clipped_px": int((mask & ~valid).sum()),
                "frac_dev_gt_0.5ev": frac(rc, sel), "frac_dev_gt_0.5ev_at_ref_position": frac(rc, own),
                "frac_dev_gt_0.5ev_at_other_positions": frac(rc, other),
                "frac_dev_gt_0.5ev_outside_ghost": frac(rc, ok), "frac_dev_gt_0.5ev_luminance": frac(ry, sel),
                "median_dev_ev": float(np.median(rc[sel])), "p95_dev_ev": float(np.percentile(rc[sel], 95)),
                "pipeline_ghost_fraction": mm.stats.get("ghost_fraction")}
    res = {"reference": s.frames[s.ref].meta.name, "deghost_on": residue(m)}
    m_off = merge.merge_series(s, {**cfg, "deghost": {**cfg.get("deghost", {}), "enabled": False}})
    res["deghost_off"] = residue(m_off)
    return res


def _spec_pipeline(cfg):
    """Exposures (EXIF), window mask IoU and ghost residue, from the pipeline's own load / align /
    merge / lens / window detection (capture = reference-frame geometry, full resolution)."""
    from estatehdr import lens, windows
    side = int(cfg["runtime"].get("analysis_max_side", 1600))
    expo, wiou, ghost = {}, {}, None
    for scene in GT_SCENES:
        p = gt_params(scene)
        s = load_series(scene, [read_metadata(os.path.join(SYN, "input", f["file"])) for f in p["frames"]], cfg)
        expo[scene] = {**_exposure_errors(s, p), "crf": s.crf}
        align.align_series(s, cfg["align"])
        m = merge.merge_series(s, cfg)
        iref = _ref_index(s, p)
        lab = _to_ref(cv2.imread(os.path.join(SYN, "gt", scene, "labels_capture.png"), cv2.IMREAD_GRAYSCALE),
                      np.array(p["frames"][iref]["homography"]))
        rad, _ = lens.correct(m.radiance.copy(), cfg)
        win = windows.detect(resize_max(rad, side)[0], resize_max(m.clipped, side)[0], cfg)
        del rad
        glass, glass_frame = _window_gt(lab)
        pred = (cv2.resize(win.mask, (lab.shape[1], lab.shape[0])) > 0.5) if win is not None else np.zeros_like(glass)
        wiou[scene] = {"iou_glass": _iou(pred, glass), "iou_glass_frame": _iou(pred, glass_frame),
                       "pred_frac": float(pred.mean()), "gt_glass_frac": float(glass.mean()),
                       "gt_glass_frame_frac": float(glass_frame.mean()),
                       "windows_detected": win.stats.get("windows") if win is not None else 0}
        if scene == "bedroom":
            ghost = _ghost_residue(cfg, s, p, m, iref, lab)
        del s, m
    return expo, wiou, ghost


def _spec_align20(cfg, moves=ALIGN20_MOVES):
    """GT frames re-warped so every non-reference frame moves 15-20 px (+ rotation, perspective)."""
    import piexif
    from estatehdr.synthetic import write_tiff16
    out = {}
    tmp = tempfile.mkdtemp()
    try:
        for scene in ("bedroom", "living_room"):
            p = gt_params(scene)
            w, h = p["camera"]["width"], p["camera"]["height"]
            ser = p["series"]
            mid = len(p["frames"]) // 2  # the generator's untouched frame stays as it is
            Hmid = np.array(p["frames"][mid]["homography"])
            T = lambda x, y: np.array([[1, 0, x], [0, 1, y], [0, 0, 1]], np.float64)  # noqa: E731
            G, k = [], 0
            for i, f in enumerate(p["frames"]):
                src, dst = os.path.join(SYN, "input", f["file"]), os.path.join(tmp, f["file"])
                if i == mid:
                    G.append(np.eye(3))
                    shutil.copyfile(src, dst)
                    continue
                tx, ty, ang, px, py = moves[k % len(moves)]
                k += 1
                R = np.vstack([cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0), [0, 0, 1]])
                P = T(w / 2, h / 2) @ np.array([[1, 0, 0], [0, 1, 0], [px, py, 1]]) @ T(-w / 2, -h / 2)
                G.append(T(tx, ty) @ P @ R)  # GT: reference coords -> this frame's coords
                A = G[i] @ Hmid @ np.linalg.inv(np.array(f["homography"]))  # replaces the generator's shake
                if f["file"].endswith(".tif"):
                    im = cv2.warpPerspective(tifffile.imread(src), A, (w, h), flags=cv2.INTER_LANCZOS4,
                                             borderMode=cv2.BORDER_REFLECT)
                    write_tiff16(dst, im, {"exposure_time": f["exposure_time"], "fnumber": ser["fnumber"],
                                           "iso": ser["iso"], "focal": ser["focal_mm"], "datetime": f["datetime"]})
                else:
                    im = cv2.warpPerspective(cv2.imread(src), A, (w, h), flags=cv2.INTER_LANCZOS4,
                                             borderMode=cv2.BORDER_REFLECT)
                    cv2.imwrite(dst, im, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    piexif.transplant(src, dst)
            s = load_series(scene, [read_metadata(os.path.join(tmp, f["file"])) for f in p["frames"]], cfg)
            infos = align.align_series(s, cfg["align"])
            pts = np.array([[x, y, 1.0] for x in np.linspace(50, w - 50, 9) for y in np.linspace(50, h - 50, 7)]).T
            iref, errs = _ref_index(s, p), []
            for i, f in enumerate(s.frames):
                if i == s.ref:
                    continue
                E = G[i] @ np.linalg.inv(G[iref])
                a, b = f.homography @ pts, E @ pts
                e = np.hypot(*(a[:2] / a[2] - b[:2] / b[2]))
                shift = np.hypot(*(b[:2] / b[2] - pts[:2]))
                errs.append({"frame": f.meta.name, "true_shift_px": float(shift.mean()), "true_shift_max_px": float(shift.max()),
                             "mean_err_px": float(e.mean()), "max_err_px": float(e.max()), **_model_info(infos[i])})
            out[scene] = errs
            for f in p["frames"]:
                os.remove(os.path.join(tmp, f["file"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _tungsten_share(scene, size):
    """Share of the tungsten point lights in the light reflected by each pixel, rendered in the
    ideal (reference_ideal) camera at 600x400 and upsampled to ``size`` (w, h).  The renderer's
    irradiance is a sum, so lights-only + everything-but-lights == full render (checked: 1e-6)."""
    import dataclasses
    from estatehdr.synthetic import SCENES, CameraSpec, Renderer
    p = gt_params(scene)
    spec = SCENES[scene]["scene"]()
    cam = CameraSpec(**{**p["camera"], "width": 600, "height": 400, "supersample": 1, "pitch_deg": 0.0,
                        "roll_deg": 0.0, "k1": 0.0, "ca": 0.0, "vignetting": 0.0})
    tung, lab = Renderer(dataclasses.replace(spec, sky_lum=0.0, ground_lum=0.0, sun_strength=0.0, ambient=0.0)).render(cam, distort=False)
    day, _ = Renderer(dataclasses.replace(spec, lights=[])).render(cam, distort=False)
    yt, yd = luminance(tung), luminance(day)
    share = yt / np.maximum(yt + yd, 1e-9)
    ideal = cv2.resize(cv2.imread(os.path.join(SYN, "gt", scene, "labels_ideal.png"), cv2.IMREAD_GRAYSCALE),
                       (600, 400), interpolation=cv2.INTER_NEAREST)
    return cv2.resize(share, size, interpolation=cv2.INTER_LINEAR), float((lab == ideal).mean())


def _spec_white_balance(series_of):
    """Output registered to reference_ideal.png exactly as quality/evaluate.py does (2048 px)."""
    from estatehdr.imgutil import delta_e2000
    from estatehdr.quality import metrics as M
    from estatehdr.quality.evaluate import load_rgb
    res = {}
    for scene in GT_SCENES:
        s = series_of.get(scene)
        if s is None:
            continue
        gdir = os.path.join(SYN, "gt", scene)
        ref = load_rgb(os.path.join(gdir, "reference_ideal.png"), 2048)
        warped, valid = M.register(load_rgb(s["outputs"]["full"]["path"], 2048), ref)
        lab = cv2.resize(cv2.imread(os.path.join(gdir, "labels_ideal.png"), cv2.IMREAD_GRAYSCALE),
                         (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_NEAREST)
        share, agree = _tungsten_share(scene, (ref.shape[1], ref.shape[0]))
        walls = cv2.erode((np.isin(lab, (1, 2)) & valid).astype(np.uint8), K9).astype(bool)
        zone = walls & (share > 0.5)
        g, z = M.neutrality(warped, walls), M.neutrality(warped, zone)
        r = {"series": s["name"], "render_label_agreement": agree, "walls_dE": g.get("delta_e_mean"),
             "zone_frac_of_walls": float(zone.sum() / max(walls.sum(), 1)), "zone_px": int(zone.sum()),
             "zone_dE": z.get("delta_e_mean"), "zone_dE_p90": z.get("delta_e_p90"),
             "zone_a_mean": z.get("a_mean"), "zone_b_mean": z.get("b_mean"),
             "zone_dE_in_reference": M.neutrality(ref, zone).get("delta_e_mean"),
             "daylight_walls_dE": M.neutrality(warped, walls & (share <= 0.5)).get("delta_e_mean")}
        acc = cv2.erode(((lab == 8) & valid).astype(np.uint8), K9).astype(bool)
        if acc.sum() >= 100:
            lo, lr = rgb_to_lab(srgb_to_linear(warped))[acc], rgb_to_lab(srgb_to_linear(ref))[acc]
            ho = math.degrees(math.atan2(lo[:, 2].mean(), lo[:, 1].mean()))
            hr = math.degrees(math.atan2(lr[:, 2].mean(), lr[:, 1].mean()))
            r["accent"] = {"px": int(acc.sum()), "hue_out_deg": ho, "hue_ref_deg": hr,
                           "dH_deg": float((ho - hr + 180) % 360 - 180),
                           "chroma_out": float(np.hypot(lo[:, 1].mean(), lo[:, 2].mean())),
                           "chroma_ref": float(np.hypot(lr[:, 1].mean(), lr[:, 2].mean())),
                           "dE2000_mean": float(delta_e2000(lo, lr).mean())}
        res[scene] = r
    return res


def _geometry_plan(s, shape, cfg):
    """The geometry.apply plan the pipeline used, rebuilt from report.json (k1, vertical angles and
    strength, focal); checked through the crop fraction it reproduces."""
    from estatehdr import geometry
    g = s.get("geometry", {})
    dist, v = g.get("distortion", {}), g.get("verticals", {})
    k1 = float(dist.get("k1", 0.0)) if dist.get("accepted", True) else 0.0
    f = float(g.get("focal", {}).get("px_small", 1.0))
    Rm = np.eye(3)
    if "applied_strength" in v:
        Rm, _, _ = geometry.rotation_from_vp(np.array([math.tan(math.radians(v["roll_deg"])), 1.0,
                                                       math.tan(math.radians(v["pitch_deg"])) / f]), f, v["applied_strength"])
    H, W = shape[:2]
    sc = min(1.0, int(cfg["runtime"].get("analysis_max_side", 1600)) / max(H, W))
    return {"enabled": bool(g), "k1": k1, "Rm": Rm, "f_small": f, "s": sc, "size": (W, H), "info": {}}


def _acutance(img):
    """Per-pixel slope g (luma / px), its 3x3 max G and the 9x9 local step height C (max - min)."""
    y = (img @ LUMA).astype(np.float32)
    g = np.hypot(cv2.Sobel(y, cv2.CV_32F, 1, 0), cv2.Sobel(y, cv2.CV_32F, 0, 1)) / 8.0
    return g, cv2.dilate(g, np.ones((3, 3), np.uint8)), cv2.dilate(y, K9) - cv2.erode(y, K9)


def _spec_sharpness(cfg, rep, scene_of):
    from estatehdr import geometry
    from estatehdr.quality import metrics as M
    from estatehdr.quality.evaluate import load_rgb
    res = {}
    for s in rep["series"]:
        if s.get("status") != "ok" or "full" not in s.get("outputs", {}):
            continue
        ref_path = next((f for f in s["files"] if os.path.basename(f) == s.get("reference")), s["files"][0])
        inp = _display_frame(ref_path, (s.get("crf") or {}).get("model"))
        out = load_rgb(s["outputs"]["full"]["path"])
        if out.shape != inp.shape:
            continue
        plan = _geometry_plan(s, inp.shape, cfg)
        inp_w, info = geometry.apply(inp, plan, cfg)
        excl = cv2.dilate((chmax(inp) >= 0.98).astype(np.uint8), K9).astype(bool)
        scene = scene_of.get(os.path.basename(s["files"][0]))
        if scene in GT_SCENES:  # GT window glass + frame (the window pull re-renders the view)
            p = gt_params(scene)
            lab = cv2.imread(os.path.join(SYN, "gt", scene, "labels_capture.png"), cv2.IMREAD_GRAYSCALE)
            iref = [f["file"] for f in p["frames"]].index(os.path.basename(ref_path))
            win = _window_gt(_to_ref(lab, np.array(p["frames"][iref]["homography"])))[1]
            excl |= cv2.dilate(win.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
        excl = geometry.apply(np.repeat(excl[..., None], 3, -1).astype(np.float32), plan, cfg)[0][..., 0] > 0.01
        excl |= cv2.dilate((chmax(out) >= 254 / 255).astype(np.uint8), K9).astype(bool)
        valid = ~excl
        valid[:8], valid[-8:], valid[:, :8], valid[:, -8:] = False, False, False, False
        gi, Gi, Ci = _acutance(inp_w)
        go, Go, Co = _acutance(out)
        cand = valid & (gi >= Gi) & (Ci >= 0.1)  # edge centre lines with a real step
        E = cand & (gi >= np.percentile(gi[valid], 95))
        keep = E & (Co >= 0.03)
        ai, ao = Gi[keep] / Ci[keep], Go[keep] / Co[keep]
        _, Gb, Cb = _acutance(cv2.GaussianBlur(out, (0, 0), 1.0))  # control: a visibly softer output
        res[scene or s["name"]] = {
            "series": s["name"], "reference_frame": os.path.basename(ref_path), "edge_px": int(E.sum()),
            "edge_px_flattened_in_output": int((E & ~keep).sum()),
            "acutance_in_median": float(np.median(ai)), "acutance_out_median": float(np.median(ao)),
            "approx_rise_10_90_px_in": float(1.02 / np.median(ai)), "approx_rise_10_90_px_out": float(1.02 / np.median(ao)),
            "acutance_ratio": float(np.median(ao / ai)),
            "acutance_ratio_output_blurred_sigma1": float(np.median(Gb[keep] / np.maximum(Cb[keep], 1e-6) / ai)),
            "gradient_ratio_same_edges": float(np.median(Go[keep] / np.maximum(Gi[keep], 1e-6))),
            "quality_sharpness_ratio": float(M.sharpness(out) / max(M.sharpness(inp), 1e-9)),
            "geometry_crop_check": [s.get("geometry", {}).get("crop_fraction"), info.get("crop_fraction")]}
    return res


def _spec_single_frame(cfg):
    """Reference frame of every synthetic and HDR+ series processed alone (--single, neutral)."""
    from estatehdr.batch import run_batch
    from estatehdr.quality import metrics as M
    from estatehdr.quality.evaluate import load_rgb
    sets = [("synthetic", os.path.join(SYN, "input"), os.path.join(SYN, "manifest.json")),
            ("hdrplus", os.path.join(ROOT, "data", "public", "hdrplus_semi", "input"),
             os.path.join(ROOT, "data", "public", "hdrplus_semi", "manifest.json"))]
    picks = []
    for set_name, folder, man_path in sets:
        if not os.path.exists(man_path):
            continue
        with open(man_path) as fh:
            man = json.load(fh)
        for ser in man["series"]:
            paths = [os.path.join(folder, f) for f in ser["files"]]
            if len(paths) > 1:  # the pipeline's reference frame (as the before preview uses it)
                s = load_series(ser["name"], [read_metadata(q) for q in paths], cfg)
                paths = [s.frames[s.ref].meta.path]
                del s
            picks.append((f"{set_name}/{ser['name']}", paths[0]))
    tmp = tempfile.mkdtemp()
    rows = {}
    try:
        rep = run_batch(None, tmp, load_config(None, "neutral", ["grouping.mode=single", "runtime.workers=2"]),
                        files=[q for _, q in picks])
        by_file = {os.path.basename(s["files"][0]): s for s in rep["series"]}
        for name, path in picks:
            s = by_file.get(os.path.basename(path))
            if s is None or s.get("status") != "ok":
                rows[name] = {"frame": os.path.basename(path), "error": (s or {}).get("error", "not processed")}
                continue
            hb = M.histogram_stats(_display_frame(path, (s.get("crf") or {}).get("model")))
            ha = M.histogram_stats(load_rgb(s["outputs"]["full"]["path"]))
            rows[name] = {"frame": os.path.basename(path), "clipped_pct_before": hb["clipped_pct"],
                          "clipped_pct_after": ha["clipped_pct"], "crushed_pct_before": hb["crushed_pct"],
                          "crushed_pct_after": ha["crushed_pct"]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rows


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return float(np.mean(vals)) if vals else None


def exp_spec_extras(cfg, out_dir, parts=None, prev=None):
    """parts: subset of SPEC_PARTS to compute (None = all); the other parts are kept from ``prev``."""
    t0 = time.time()
    with open(os.path.join(out_dir, "report.json"), encoding="utf-8") as fh:
        rep = json.load(fh)
    with open(os.path.join(SYN, "manifest.json")) as fh:
        man = json.load(fh)
    scene_of = {s["files"][0]: s["name"] for s in man["series"]}
    series_of = {scene_of.get(os.path.basename(s["files"][0])): s for s in rep["series"] if s.get("status") == "ok"}
    want = lambda *k: parts is None or any(x in parts for x in k)  # noqa: E731
    R = dict(prev or {}) if parts else {}
    R.update({"batch_dir": os.path.relpath(out_dir, ROOT),
              "batch_report_time": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(os.path.join(out_dir, "report.json"))))})

    if want("exposures", "ghost", "window_iou"):  # one shared load / align / merge per scene
        expo, wiou, ghost = _spec_pipeline(cfg)
        noexif = _spec_exposures_noexif(cfg)
        mx = max(v["max_abs_err_ev"] for v in expo.values())
        mn = max(v["max_abs_err_ev"] for v in noexif.values())
        R["exposures"] = {
            "spec": "SPEC 3: relative exposures within +-0.1 EV of GT",
            "definition": "Pipeline (series.load_series) relative exposure of each frame vs the pipeline's reference frame, "
                          "log2(frame.exposure), minus the GT difference ev_frame - ev_ref (params.json); err_ev per frame, "
                          "max |err| per series.  with_exif: original files (EXIF ratios are used; pixels only veto > 0.4 EV "
                          "disagreements).  without_exif: same pixels, EXIF removed (JPEG: EXIF segment stripped, TIFF: "
                          "rewritten without tags), so exposures come from pixel ratios only.  crf = fitted response "
                          "(SPEC 3 second criterion: fit_score < srgb_score means the recovered curve is more consistent).",
            "with_exif": expo, "without_exif": noexif,
            "summary": {"with_exif_max_abs_err_ev": mx, "without_exif_max_abs_err_ev": mn,
                        "pass_with_exif": mx <= 0.1, "pass_without_exif": mn <= 0.1}}
        print("I exposures", R["exposures"]["summary"])

        on, off = ghost["deghost_on"], ghost["deghost_off"]
        R["ghost"] = {
            "spec": "SPEC 4: < 2% of ghost-mask pixels deviate by > 0.5 EV from the reference",
            "definition": "Bedroom (3 hand-held TIFF frames, moving object). GT = radiance_capture.tif with the object drawn "
                          "at the reference frame's position (synthetic.moving_object, as generated), in reference-frame "
                          "geometry. Ghost mask = union of the object's footprints (blurred mask > 0.5) of all frames. The "
                          "series is loaded, aligned and merged by the pipeline at full resolution (2400x1600); the radiance "
                          "scale is normalised by the median log2 luminance ratio merged/GT over unclipped pixels outside the "
                          "ghost mask (dilated 15 px) and outside windows. Deviation = max over R,G,B of "
                          "|log2(merged_c / GT_c)| after that scale: the object (navy) is about as bright as what it "
                          "covers, so a transparent trace is mainly a colour shift (frac_dev_gt_0.5ev_luminance = the same "
                          "with luminance only, much less sensitive). Reported: fraction of ghost-mask pixels deviating "
                          "> 0.5 EV (also split by the object's reference position / the other frames' positions, and the "
                          "rate on non-ghost pixels = noise floor of the metric); pixels saturated in GT even in the darkest "
                          "frame or with the merge's clipped map >= 0.01 are excluded (excluded_clipped_px). deghost_off = "
                          "the same merge with deghost.enabled=false (shows that the metric detects ghosts).",
            **ghost, "summary": {"frac_dev_gt_0.5ev": on["frac_dev_gt_0.5ev"],
                                 "frac_dev_gt_0.5ev_deghost_off": off["frac_dev_gt_0.5ev"],
                                 "pass": on["frac_dev_gt_0.5ev"] < 0.02}}
        print("I ghost", R["ghost"]["summary"])

        R["window_iou"] = {
            "spec": "SPEC 6: IoU of the window mask with GT >= 0.8",
            "definition": "Pipeline window mask (windows.detect on the merged, lens-corrected radiance at analysis "
                          "resolution, as pipeline.finish does), upsampled to 2400x1600 and thresholded at 0.5, vs GT labels "
                          "in capture (= reference frame) geometry: iou_glass vs glass (label 4); iou_glass_frame vs glass "
                          "plus its frame/mullions (components of labels 4|5 containing glass; the door is excluded).",
            **wiou, "summary": {"min_iou_glass": min(v["iou_glass"] for v in wiou.values()),
                                "min_iou_glass_frame": min(v["iou_glass_frame"] for v in wiou.values()),
                                "pass_glass": min(v["iou_glass"] for v in wiou.values()) >= 0.8}}
        print("I window_iou", R["window_iou"]["summary"])

    if want("alignment_20px"):
        def a20_summary(res):
            allf = [e for v in res.values() for e in v]
            return {"mean_err_px": _mean([e["mean_err_px"] for e in allf]),
                    "worst_frame_mean_err_px": max(e["mean_err_px"] for e in allf),
                    "max_err_px": max(e["max_err_px"] for e in allf),
                    "true_shift_px_range": [min(e["true_shift_px"] for e in allf), max(e["true_shift_px"] for e in allf)],
                    "pass": max(e["mean_err_px"] for e in allf) <= 0.8,
                    "models": {m: sum(e.get("model") == m for e in allf) for m in sorted({e.get("model") for e in allf} - {None})}}
        a20 = _spec_align20(cfg)
        sim = _spec_align20(cfg, [(tx, ty, ang, 0.0, 0.0) for tx, ty, ang, _, _ in ALIGN20_MOVES])
        aff = _spec_align20(load_config(None, "neutral", ["align.model=affine"]))
        hom = _spec_align20(load_config(None, "neutral", ["align.model=homography"]))
        R["alignment_20px"] = {
            "spec": "SPEC 4: mean grid error <= 0.8 px hand-held (shifts up to 20 px), 2400x1600",
            "definition": "GT bedroom (3 TIFF16, -2/0/+2 EV) and living room (5 JPEG, -4..+4 EV) frames; each non-reference "
                          "frame is re-warped (Lanczos, written back with its EXIF; JPEG q95) so that its total GT motion "
                          "relative to the untouched middle frame is a known homography (ALIGN20_MOVES): translation 15-20 "
                          "px, rotation 0.25-0.35 deg, perspective h31/h32 1-2e-6 /px about the centre (a real hand-held "
                          "rotation giving 17 px with this 84 deg lens has ~1e-5 /px). align.align_series at full resolution "
                          "with the configured model (align.model); error = distance between estimated and GT mapping of a "
                          "9x7 grid (50 px margin), as in experiment C; per frame the model used (align.model auto: "
                          "the per-frame choice, with its log-likelihood ratio). Diagnostics: similarity_only = the same "
                          "motion without the perspective term (configured model); affine_model / homography_model = the "
                          "full motion with align.model=affine / homography.",
            "align_model": cfg.get("align", {}).get("model"),
            "per_scene": a20, "summary": a20_summary(a20),
            "similarity_only": {"per_scene": sim, "summary": a20_summary(sim)},
            "affine_model": {"per_scene": aff, "summary": a20_summary(aff)},
            "homography_model": {"per_scene": hom, "summary": a20_summary(hom)}}
        print("I alignment_20px", R["alignment_20px"]["summary"], "similarity only", a20_summary(sim),
              "affine model", a20_summary(aff), "homography model", a20_summary(hom))

    if want("white_balance"):
        wb = _spec_white_balance(series_of)
        zones = [v["zone_dE"] for v in wb.values() if v.get("zone_dE") is not None]
        acc = [v["accent"]["dH_deg"] for v in wb.values() if "accent" in v]
        R["white_balance"] = {
            "spec": "SPEC 7: wall dE2000 from neutral <= 3.0 globally and <= 5.0 in the tungsten zone; accent wall dH < 10 deg",
            "definition": "Batch output (full JPEG, 2048 px) registered to reference_ideal.png with quality.metrics.register "
                          "(as quality/evaluate.py). Walls = labels_ideal wall|ceiling (1|2), registered-valid, eroded 9x9. "
                          "Tungsten zone = wall pixels where the scene's tungsten point lights give > 50% of the reflected "
                          "light: the scene is re-rendered in the ideal camera at 600x400 with lights only and with "
                          "everything but the lights (window sky/ground light, sun, ambient inter-reflection term - its colour "
                          "is dominated by the sky term, so it counts as daylight), share = Y_lights / (Y_lights + Y_rest), "
                          "upsampled bilinearly. dE = mean CIEDE2000 of those output pixels from a neutral grey of the same "
                          "L* (quality.metrics.neutrality). zone_dE_in_reference = the same on reference_ideal (sanity, ~0). "
                          "Accent = bedroom accent wall (label 8, eroded 9x9): dH = hue angle of the mean a*,b* (CIELAB) of "
                          "the output minus that of reference_ideal, degrees.",
            **wb, "summary": {"walls_dE_max": max(v["walls_dE"] for v in wb.values()) if wb else None,
                              "zone_dE_max": max(zones) if zones else None, "accent_dH_deg": acc[0] if acc else None,
                              "pass_walls_3": bool(wb) and max(v["walls_dE"] for v in wb.values()) <= 3.0,
                              "pass_zone_5": bool(zones) and max(zones) <= 5.0,
                              "pass_accent_10": bool(acc) and abs(acc[0]) < 10}}
        print("I white_balance", R["white_balance"]["summary"])

    if want("sharpness"):
        sh = _spec_sharpness(cfg, rep, scene_of)
        R["sharpness"] = {
            "spec": "SPEC 9: edge sharpness >= 0.9x input",
            "definition": "Contrast-invariant acutance A = G / C on display luma (sRGB, Rec.709 weights): G = largest slope "
                          "(Sobel/8, luma per px) within 3x3, C = local step height (max - min) within 9x9; for a blurred "
                          "step A ~ 1.02 / (10-90% rise width) (approx_rise_10_90_px; approximate, the 9x9 window truncates "
                          "wide edges), independent of the step's contrast, so local tone mapping and "
                          "the window pull (which change edge contrast, not edge width) do not count as sharpening or "
                          "blurring. The pipeline's reference frame as shot (linear TIFF: before-preview rendering) is "
                          "passed through the exact geometry.apply plan of the output (rebuilt from report.json; the crop "
                          "fraction it reproduces is in geometry_crop_check), so both images share geometry and resampling. "
                          "Edges = input pixels on edge centre lines (3x3 slope maximum) with slope >= 95th percentile and "
                          "C >= 0.1, excluding pixels within 4 px of clipped input/output pixels, GT window glass+frame "
                          "(dilated 7 px; GT scenes only) and an 8 px border; acutance_ratio = median over edges of "
                          "A_out / A_in (edges with C_out < 0.03, i.e. flattened, counted separately); "
                          "acutance_ratio_output_blurred_sigma1 = the same for the output blurred with a 1 px Gaussian "
                          "(control: the measure does respond to blur). "
                          "gradient_ratio_same_edges = median G_out / G_in on the same edges (contrast-dependent, the "
                          "literal 'gradient energy'); quality_sharpness_ratio = quality.metrics.sharpness (mean slope of "
                          "the 5% strongest gradients of the whole image) output / input: it rises and falls with tonal "
                          "contrast (shadow lifting, window pull), which is why the acutance ratio is the criterion.",
            **sh, "summary": {"min_acutance_ratio": min(v["acutance_ratio"] for v in sh.values()) if sh else None,
                              "pass": bool(sh) and min(v["acutance_ratio"] for v in sh.values()) >= 0.9}}
        print("I sharpness", R["sharpness"]["summary"])

    if want("single_frame"):
        sf = _spec_single_frame(cfg)
        ok = [v for v in sf.values() if "clipped_pct_before" in v]
        summ = {k: _mean([v[k] for v in ok]) for k in ("clipped_pct_before", "clipped_pct_after", "crushed_pct_before", "crushed_pct_after")}
        summ.update({"images": len(ok), "failed": len(sf) - len(ok),
                     "clipped_down": sum(v["clipped_pct_after"] < v["clipped_pct_before"] for v in ok),
                     "crushed_down": sum(v["crushed_pct_after"] < v["crushed_pct_before"] for v in ok),
                     "crushed_up": [k for k, v in sf.items() if "clipped_pct_before" in v and v["crushed_pct_after"] > v["crushed_pct_before"]]})
        summ["pass_mean"] = bool(ok) and summ["clipped_pct_after"] < summ["clipped_pct_before"] and summ["crushed_pct_after"] <= summ["crushed_pct_before"]
        summ["pass_every_image"] = bool(ok) and summ["clipped_down"] == len(ok) and not summ["crushed_up"]
        R["single_frame"] = {
            "spec": "SPEC 10: single-frame pseudo-HDR reduces clipped and crushed pixels",
            "definition": "Reference frame (the pipeline's choice, as the before preview) of every synthetic series and every "
                          "HDR+ series (data/public/hdrplus_semi) processed alone (grouping.mode=single, preset neutral, 2 "
                          "workers). Full-size input as shot (linear TIFF: before-preview rendering) vs full-size output "
                          "JPEG: clipped_pct = % pixels with any channel >= 254/255, crushed_pct = % pixels with Rec.709 luma "
                          "<= 1/255 (quality.metrics.histogram_stats). Means over images.",
            "images": sf, "summary": summ}
        print("I single_frame", summ)
    R["seconds"] = round(time.time() - t0, 1)
    R["last_run_parts"] = sorted(parts) if parts else "all"
    return R


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
    ap.add_argument("--only", default="", help="experiment letters to run (e.g. I or A,C); their results are merged "
                                                "into the existing reports/verification.json")
    ap.add_argument("--parts", default="", help="with I: only these parts of spec_extras (comma list of "
                                                 + ", ".join(SPEC_PARTS) + "); the other parts are kept")
    a = ap.parse_args(argv)
    sel = set(a.only.upper().replace(",", "").replace(" ", "")) or set("ABCDEFGHI")
    if sel - set("ABCDEFGHI"):
        ap.error(f"unknown experiment(s): {', '.join(sorted(sel - set('ABCDEFGHI')))}")
    parts = {x.strip() for x in a.parts.split(",") if x.strip()} or None
    if parts and (parts - set(SPEC_PARTS) or not a.only):
        ap.error(f"--parts needs --only and takes: {', '.join(SPEC_PARTS)}")
    path = os.path.join(OUT, "verification.json")
    R = {}
    if a.only and os.path.exists(path):  # keep the other experiments' results
        with open(path, encoding="utf-8") as fh:
            R = json.load(fh)
    out_dir = ensure_synthetic_batch(os.path.abspath(a.output_dir)) if sel & set("DEFI") else None
    cfg = load_config(None, "neutral")
    done = []
    if "A" in sel:
        R["grouping"] = exp_grouping(cfg)
        print("A done", R["grouping"])
        done.append("grouping")
    if "B" in sel:
        R["three_of_n"] = exp_three_of_n(cfg)
        print("B done")
        done.append("three_of_n")
    if "C" in sel:
        R["alignment"], other = exp_alignment(cfg, ("affine", "homography"))
        R["alignment_models"] = {
            "definition": "Experiment C (key 'alignment': configured align.model, per frame the model it used) "
                          "repeated with explicit align.model values on the same loaded series: per scene / frame "
                          "mean and max grid error [px] vs GT.",
            "configured": cfg["align"].get("model"), **other}
        print("C done", {m: [round(e["mean_err_px"], 3) for v in r.values() for e in v]
                         for m, r in [("configured", R["alignment"]), *other.items()]})
        done += ["alignment", "alignment_models"]
    if sel & set("DEF"):
        R["windows"], R["geometry"], R["lens_ca"] = exp_from_outputs(out_dir)
        done += ["windows", "geometry", "lens_ca"]
    if "G" in sel:
        R["sky"] = exp_sky(cfg)
        done.append("sky")
    if "H" in sel:
        R["noise_single_raw"] = exp_noise(cfg)
        done.append("noise_single_raw")
    if "I" in sel:
        R["spec_extras"] = exp_spec_extras(cfg, out_dir, parts, R.get("spec_extras"))
        done.append("spec_extras")
    os.makedirs(OUT, exist_ok=True)
    if a.only and os.path.exists(path):  # re-read: keep what other runs wrote meanwhile, replace only ours
        with open(path, encoding="utf-8") as fh:
            cur = json.load(fh)
        for k in done:
            if k == "spec_extras" and parts:
                cur[k] = {**cur.get(k, {}), **{p: v for p, v in R[k].items() if p in parts or p.startswith("batch_")}}
            else:
                cur[k] = R[k]
        R = cur
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(R, fh, indent=1, default=float)
    print(json.dumps({k: R[k] for k in done}, indent=1, default=float)[:6000])


if __name__ == "__main__":
    main()

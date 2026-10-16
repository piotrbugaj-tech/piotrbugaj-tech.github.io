"""Per-series processing pipeline.

Order of stages (each one can be switched off in config.yaml):
  load -> align -> merge (radiance)            [series.py, align.py, merge.py]
  lens: chromatic aberration, vignetting       [lens.py]       (on radiance)
  white balance: global + mixed light          [color.py]      (on radiance)
  window detection -> exposure offset map      [windows.py]
  tone mapping -> display sRGB                 [tonemap.py]
  denoise + optional modules (sky, twilight,
  grass, object removal)                       [denoise.py, modules/*]
  geometry: distortion + verticals + crop      [geometry.py]
  export: sizes, sharpening, ICC, EXIF         [export.py]
"""
from __future__ import annotations

import gc
import json
import logging
import os
import time
import traceback

import cv2
import numpy as np

from .config import Config
from .grouping import Group
from .imgutil import linear_to_srgb, luminance, resize_max, srgb_to_linear

log = logging.getLogger(__name__)


class StageTimer:
    def __init__(self):
        self.times = {}
        self.rss = {}
        self._t = time.time()

    def mark(self, name: str):
        now = time.time()
        self.times[name] = round(now - self._t, 3)
        self._t = now
        try:
            import resource
            self.rss[name] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20), 2)
        except Exception:
            pass


def process_group(group: Group, cfg: Config, out_dir: str, progress=None, extra_masks: dict | None = None) -> dict:
    """Process one bracket series. Never raises: errors are returned in the result dict."""
    t0 = time.time()
    result = {"name": group.name, "files": [f.path for f in group.frames], "status": "ok",
              "warnings": list(group.warnings), "outputs": {}}
    try:
        _process(group, cfg, out_dir, result, progress, extra_masks or {})
    except MemoryError:
        result["status"] = "error"
        result["error"] = "out of memory (try fewer workers: --workers 1)"
        log.error("[%s] out of memory", group.name)
    except Exception as exc:  # one bad series must not stop the batch
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc(limit=6)
        log.error("[%s] failed: %s", group.name, exc)
        log.debug(result["traceback"])
    result["seconds"] = round(time.time() - t0, 2)
    gc.collect()
    return result


def _p(progress, frac, msg):
    if progress:
        try:
            progress(frac, msg)
        except Exception:
            pass


def _process(group: Group, cfg: Config, out_dir: str, result: dict, progress, extra_masks: dict):
    from . import align, merge, series as series_mod, tonemap
    from . import export
    timer = StageTimer()
    side = int(cfg["runtime"].get("analysis_max_side", 1600))
    _p(progress, 0.02, "wczytywanie")
    s = series_mod.load_series(group.name, group.frames, cfg)
    result["warnings"] += s.warnings
    result["crf"] = s.crf
    result["reference"] = s.frames[s.ref].meta.name
    result["exposures_ev"] = [round(float(np.log2(f.exposure)), 2) for f in s.frames]
    single = len(s.frames) == 1
    scfg = cfg.get("single_image", {})
    own_key = None
    developed = single and s.frames[0].decoded.encoding == "srgb"
    if developed and scfg.get("key_from_input", True):
        # display key of the photographer's own rendering (median display luminance)
        im, _ = resize_max(s.frames[0].decoded.as_float(), 800)
        own_key = float(linear_to_srgb(np.float32(np.median(luminance(srgb_to_linear(im))))))
        result["input_key"] = round(own_key, 3)
    timer.mark("load")
    _p(progress, 0.15, "wyrównanie")
    if len(s.frames) > 1:
        result["align"] = align.align_series(s, cfg.get("align", {}))
    timer.mark("align")
    _p(progress, 0.3, "scalanie HDR")
    m = merge.merge_series(s, cfg)
    result["merge"] = m.stats
    rad = m.radiance
    clipped_full = m.clipped
    m.radiance = None  # later stages work in place: do not keep the original buffer alive
    ref_meta = s.frames[s.ref].meta
    # free the decoded frames early (they are the largest objects)
    for f in s.frames:
        f.decoded.image = None
    timer.mark("merge")

    # --- lens corrections on radiance -------------------------------------------
    _p(progress, 0.4, "korekcja obiektywu")
    try:
        from . import lens
        rad, result["lens"] = lens.correct(rad, cfg)
    except ImportError:
        pass
    timer.mark("lens")

    # --- analysis-resolution helpers -------------------------------------------
    rad_small, _ = resize_max(rad, side)
    clipped_small, _ = resize_max(m.clipped, side)

    # --- window detection (before WB so the exterior is excluded from interior statistics)
    _p(progress, 0.5, "okna")
    win = None
    try:
        from . import windows
        win = windows.detect(rad_small, clipped_small, cfg)
        result["windows"] = win.stats if win is not None else None
    except ImportError:
        pass
    timer.mark("windows")
    if cfg.get("runtime", {}).get("debug"):
        _save_debug(out_dir, group.name, rad_small, win)

    # --- white balance -----------------------------------------------------------
    _p(progress, 0.55, "balans bieli")
    try:
        from . import color
        wb_cfg = cfg
        if developed:
            f = float(scfg.get("wb_strength", 0.5))
            w = dict(cfg.get("white_balance", {}))
            w["global_strength"] = float(w.get("global_strength", 0.9)) * f
            w["mixed_light_strength"] = float(w.get("mixed_light_strength", 0.6)) * f
            wb_cfg = {**cfg, "white_balance": w}
        rad, result["white_balance"] = color.white_balance(rad, rad_small, win, wb_cfg)
        rad_small, _ = resize_max(rad, side)
    except ImportError:
        pass
    timer.mark("white_balance")

    # --- tone mapping -------------------------------------------------------------
    _p(progress, 0.62, "tone mapping")
    tcfg = dict(cfg.get("tonemap", {}))
    if single:
        # one exposure: lifting deep shadows mostly amplifies noise -> lift less when it is noisy
        from .denoise import estimate_sigma
        lin_small = np.clip(rad_small / max(float(np.percentile(luminance(rad_small), 99)), 1e-6), 0, 1)
        sig_lin = estimate_sigma(np.sqrt(luminance(lin_small)))
        result["single_noise"] = round(float(sig_lin), 4)
        if sig_lin > 0.01:
            tcfg["compress_shadows"] = max(float(tcfg.get("compress_shadows", 0.7)),
                                           float(np.clip(0.7 + 8 * (sig_lin - 0.01), 0.7, 0.9)))
    if own_key is not None:
        tk = float(tcfg.get("target_key", 0.56))
        lo, hi = scfg.get("key_range", [-0.08, 0.2])
        tcfg["target_key"] = float(np.clip(own_key, tk + float(lo), tk + float(hi)))
        tcfg["compress_shadows"] = max(float(tcfg.get("compress_shadows", 0.7)),
                                       float(scfg.get("compress_shadows_min", 0.75)))
        result["single_key_target"] = round(tcfg["target_key"], 3)
    wmask = wweight = exclude = None
    if win is not None:
        wmask, wweight, exclude = win.mask, windows.pull_weights(win), windows.exclusion(win)
        exclude = np.clip(exclude + win.patch_mask, 0, 1)  # sun patches do not define 'white'

    dbg = {}
    extra = []
    if win is not None and win.patch_mask.max() > 0.5:
        pw = cv2.GaussianBlur(win.patch_mask.astype(np.float32), (0, 0), 3.0)
        extra.append((pw, float(cfg.get("windows", {}).get("sun_patch_target", 0.88)), 1.0, "sun_patch"))
    img = tonemap.tone_map(rad, tcfg, window_mask=wmask, window_weight=wweight, exclude_small=exclude,
                           window_cfg=cfg.get("windows", {}), analysis_side=side, debug=dbg, extra_pulls=extra,
                           clipped=clipped_full, inplace=True)
    result["tonemap"] = {k: round(float(v), 4) for k, v in dbg.items()}
    del rad, clipped_full, m
    gc.collect()
    timer.mark("tonemap")

    # --- denoise --------------------------------------------------------------------
    _p(progress, 0.7, "odszumianie")
    try:
        from . import denoise
        img = denoise.denoise(img, cfg, single=single)
    except ImportError:
        pass
    timer.mark("denoise")

    # --- optional modules -----------------------------------------------------------
    _p(progress, 0.76, "moduły")
    try:
        from .modules import run_modules
        img, result["modules"] = run_modules(img, cfg, group, win, extra_masks)
    except ImportError:
        pass
    timer.mark("modules")

    # --- geometry ---------------------------------------------------------------------
    _p(progress, 0.84, "geometria")
    try:
        from . import geometry
        img, result["geometry"] = geometry.correct(img, cfg, ref_meta)
    except ImportError:
        pass
    timer.mark("geometry")

    # --- export -------------------------------------------------------------------------
    _p(progress, 0.92, "eksport")
    result["outputs"] = export.export_all(img, group, ref_meta, cfg, out_dir, result)
    timer.mark("export")
    result["timings"] = timer.times
    result["peak_rss_gb_after_stage"] = timer.rss
    _p(progress, 1.0, "gotowe")


def _save_debug(out_dir, name, rad_small, win):
    import cv2
    d = os.path.join(out_dir, ".debug")
    os.makedirs(d, exist_ok=True)
    from .imgutil import linear_to_srgb
    y = luminance(rad_small)
    k = 0.18 / max(float(np.median(y)), 1e-6)
    base = (linear_to_srgb(np.clip(rad_small * k, 0, 1)) * 255).astype(np.uint8)
    if win is not None:
        ov = base.copy().astype(np.float32)
        for m, col in ((win.mask, (255, 40, 40)), (win.lamp_mask, (255, 220, 0)), (win.patch_mask, (0, 160, 255))):
            a = (np.clip(m, 0, 1) * 0.65)[..., None]
            ov = ov * (1 - a) + np.array(col, np.float32)[None, None] * a
        ov = np.clip(ov, 0, 255).astype(np.uint8)
        for r in win.regions:
            if r["area_frac"] < 0.0005:
                continue
            x0, y0, x1, y1 = r["bbox"]
            cv2.rectangle(ov, (x0, y0), (x1, y1), (255, 255, 255), 1)
            cv2.putText(ov, r["kind"][:5], (x0, max(12, y0 - 2)), 0, 0.45, (255, 255, 255), 1)
        cv2.imwrite(os.path.join(d, f"{name}_windows.jpg"), cv2.cvtColor(ov, cv2.COLOR_RGB2BGR))
        cv2.imwrite(os.path.join(d, f"{name}_winmask.png"), (np.clip(win.mask, 0, 1) * 255).astype(np.uint8))

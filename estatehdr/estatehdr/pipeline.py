"""Per-series processing pipeline.

Order of stages (most can be switched off in config.yaml):
  prepare: load -> align -> merge (radiance)   [series.py, align.py, merge.py]
           lens: chromatic aberration, vignetting [lens.py]    (on radiance)
  finish:  window detection                    [windows.py]    (before WB: views excluded)
           white balance: global + mixed light [color.py]      (on radiance)
           tone mapping + window pull -> sRGB  [tonemap.py]
  denoise + optional modules (sky, twilight,
  grass, object removal)                       [denoise.py, modules/*]
  geometry: distortion + verticals + crop      [geometry.py]
  export: sizes, sharpening, ICC, EXIF         [export.py]
"""
from __future__ import annotations

import gc
import logging
import os
import time
import traceback
from dataclasses import dataclass

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
        from . import accel
        result["device"] = accel.setup(cfg.get("runtime", {}).get("device", "auto"))
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


@dataclass
class Prepared:
    """State after the expensive, look-independent stages (load, align, merge, lens).
    ``tools/calibrate.py`` caches it and re-runs only ``finish`` with different parameters."""
    rad: np.ndarray            # linear radiance (reference frame geometry)
    clipped: np.ndarray        # saturated even in the darkest frame (0..1)
    ref_meta: object
    single: bool
    developed: bool            # single, already rendered file (JPEG)
    own_key: float | None      # display key of that rendering
    timer: StageTimer
    night: bool = False        # night / late-dusk exterior (dark, smooth sky band at the top)

    def copy(self) -> "Prepared":
        return Prepared(self.rad.copy(), self.clipped.copy(), self.ref_meta, self.single, self.developed,
                        self.own_key, StageTimer(), self.night)


def detect_night(rad: np.ndarray, cfg: dict) -> tuple[bool, dict]:
    """Night exterior, from the merged radiance (independent of the chosen exposure): normalised so
    the light sources (p99.5) are white, the top band is very dark, darker than the rest and
    smooth (a sky, not a dark ceiling with detail).  Measured: night 0.002 / 0.38 / 0.04; dim
    church interior 0.027 / 0.76 / 0.29; every other interior and day exterior >= 0.13."""
    ncfg = cfg.get("night", {})
    if not ncfg.get("enabled", True):
        return False, {}
    small, _ = resize_max(rad, 600)
    y = luminance(small)
    d = linear_to_srgb(np.clip(y / max(float(np.percentile(y, 99.5)), 1e-12), 0, 1))
    h = y.shape[0]
    k = max(2, int(0.25 * h))
    t = float(np.median(d[:k]))
    ratio = t / max(float(np.median(d)), 1e-4)
    ly = np.log2(y[:k] + 1e-9).astype(np.float32)
    tex = float(np.abs(ly - cv2.GaussianBlur(ly, (0, 0), 3)).mean())
    info = {"top_luma": round(t, 4), "top_ratio": round(ratio, 3), "top_log_texture": round(tex, 3)}
    night = (t < float(ncfg.get("max_top_luma", 0.05)) and ratio < float(ncfg.get("max_top_ratio", 0.6))
             and tex < float(ncfg.get("max_top_texture", 0.15)))
    return night, info


def _process(group: Group, cfg: Config, out_dir: str, result: dict, progress, extra_masks: dict):
    prep = prepare(group, cfg, result, progress)
    finish(prep, group, cfg, result, out_dir, progress, extra_masks)


def prepare(group: Group, cfg: Config, result: dict, progress=None) -> Prepared:
    from . import align, lens, merge, series as series_mod
    timer = StageTimer()
    _p(progress, 0.02, "wczytywanie")
    s = series_mod.load_series(group.name, group.frames, cfg)
    result["warnings"] += s.warnings
    result["crf"] = s.crf
    result["reference"] = s.frames[s.ref].meta.name
    result["exposures_ev"] = [round(float(np.log2(f.exposure)), 2) for f in s.frames]
    single = len(s.frames) == 1
    own_key = None
    developed = single and s.frames[0].decoded.encoding == "srgb"
    if developed and cfg.get("single_image", {}).get("key_from_input", True):
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
    rad, clipped = m.radiance, m.clipped
    m.radiance = None  # later stages work in place: do not keep the original buffer alive
    ref_meta = s.frames[s.ref].meta
    for f in s.frames:  # free the decoded frames early (they are the largest objects)
        f.decoded.image = None
    timer.mark("merge")
    _p(progress, 0.4, "korekcja obiektywu")
    rad, result["lens"] = lens.correct(rad, cfg)
    night, ninfo = detect_night(rad, cfg)
    result["scene"] = {"night": night, **ninfo}
    timer.mark("lens")
    return Prepared(rad, clipped, ref_meta, single, developed, own_key, timer, night)


def finish(prep: Prepared, group: Group, cfg: Config, result: dict, out_dir: str | None = None, progress=None,
           extra_masks: dict | None = None, export: bool = True) -> np.ndarray:
    """Windows, white balance, tone mapping, denoise, modules, geometry and (optionally) export.
    Works in place on ``prep.rad``; returns the final display-referred image."""
    from . import color, denoise, geometry, tonemap, windows
    from . import export as export_mod
    from .modules import run_modules
    timer = prep.timer
    side = int(cfg["runtime"].get("analysis_max_side", 1600))
    scfg = cfg.get("single_image", {})
    rad = prep.rad
    rad_small, _ = resize_max(rad, side)
    clipped_small, _ = resize_max(prep.clipped, side)

    # --- window detection (before WB so the exterior is excluded from interior statistics)
    _p(progress, 0.5, "okna")
    ncfg = cfg.get("night", {})
    # at night bright structures are light sources, not windows to pull down
    win = None if prep.night else windows.detect(rad_small, clipped_small, cfg)
    result["windows"] = win.stats if win is not None else None
    timer.mark("windows")
    if out_dir and cfg.get("runtime", {}).get("debug"):
        _save_debug(out_dir, group.name, rad_small, win)

    # --- white balance -----------------------------------------------------------
    _p(progress, 0.55, "balans bieli")
    wb_cfg = cfg
    if prep.developed or prep.night:
        f = float(scfg.get("wb_strength", 0.5)) if prep.developed else 1.0
        f *= float(ncfg.get("wb_strength", 0.5)) if prep.night else 1.0
        w = dict(cfg.get("white_balance", {}))
        w["global_strength"] = float(w.get("global_strength", 0.9)) * f
        w["mixed_light_strength"] = float(w.get("mixed_light_strength", 0.6)) * f
        wb_cfg = {**cfg, "white_balance": w}
    rad, result["white_balance"] = color.white_balance(rad, rad_small, win, wb_cfg)
    rad_small, _ = resize_max(rad, side)
    timer.mark("white_balance")

    # --- tone mapping -------------------------------------------------------------
    _p(progress, 0.62, "tone mapping")
    tcfg = dict(cfg.get("tonemap", {}))
    if prep.single:
        # one exposure: lifting deep shadows mostly amplifies noise -> lift less when it is noisy
        lin_small = np.clip(rad_small / max(float(np.percentile(luminance(rad_small), 99)), 1e-6), 0, 1)
        sig_lin = denoise.estimate_sigma(np.sqrt(luminance(lin_small)))
        result["single_noise"] = round(float(sig_lin), 4)
        if sig_lin > 0.01:
            tcfg["compress_shadows"] = max(float(tcfg.get("compress_shadows", 0.7)),
                                           float(np.clip(0.7 + 8 * (sig_lin - 0.01), 0.7, 0.9)))
    if prep.night:
        # keep the night dark: low key, little shadow lifting
        tcfg["target_key"] = float(ncfg.get("target_key", 0.32))
        tcfg["compress_shadows"] = max(float(tcfg.get("compress_shadows", 0.7)),
                                       float(ncfg.get("compress_shadows", 0.9)))
    if prep.own_key is not None:
        tk = float(tcfg.get("target_key", 0.56))
        lo, hi = scfg.get("key_range", [-0.08, 0.2])
        tcfg["target_key"] = float(np.clip(prep.own_key, tk + float(lo), tk + float(hi)))
        tcfg["compress_shadows"] = max(float(tcfg.get("compress_shadows", 0.7)),
                                       float(scfg.get("compress_shadows_min", 0.75)))
        result["single_key_target"] = round(tcfg["target_key"], 3)
    wmask = wweight = exclude = None
    extra = []
    if win is not None:
        wmask, wweight, exclude = win.mask, windows.pull_weights(win), windows.exclusion(win)
        exclude = np.clip(exclude + win.patch_mask, 0, 1)  # sun patches do not define 'white'
        if win.patch_mask.max() > 0.5:
            pw = cv2.GaussianBlur(win.patch_mask.astype(np.float32), (0, 0), 3.0)
            extra.append((pw, float(cfg.get("windows", {}).get("sun_patch_target", 0.88)), 1.0, "sun_patch"))
    dbg = {}
    img = tonemap.tone_map(rad, tcfg, window_mask=wmask, window_weight=wweight, exclude_small=exclude,
                           window_cfg=cfg.get("windows", {}), analysis_side=side, debug=dbg, extra_pulls=extra,
                           clipped=prep.clipped, inplace=True)
    result["tonemap"] = {k: round(float(v), 4) for k, v in dbg.items()}
    prep.rad = prep.clipped = None
    del rad
    gc.collect()
    timer.mark("tonemap")

    _p(progress, 0.7, "odszumianie")
    img = denoise.denoise(img, cfg, single=prep.single)
    timer.mark("denoise")
    _p(progress, 0.76, "moduły")
    img, result["modules"] = run_modules(img, cfg, group, win, extra_masks or {})
    timer.mark("modules")
    _p(progress, 0.84, "geometria")
    img, result["geometry"] = geometry.correct(img, cfg, prep.ref_meta)
    timer.mark("geometry")
    if export:
        _p(progress, 0.92, "eksport")
        result["outputs"] = export_mod.export_all(img, group, prep.ref_meta, cfg, out_dir, result)
        timer.mark("export")
    result["timings"] = timer.times
    result["peak_rss_gb_after_stage"] = timer.rss
    _p(progress, 1.0, "gotowe")
    return img


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

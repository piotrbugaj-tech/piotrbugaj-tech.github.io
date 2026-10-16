"""Optional modules (off by default, enabled per flag/preset):
object removal, lawn greening, sky replacement, virtual twilight.

``run_modules`` works on the display-referred sRGB float image before the geometry stage and
never raises: a failing module is skipped and reported in the series result.
"""
from __future__ import annotations

import logging
import traceback

import numpy as np

log = logging.getLogger(__name__)


def run_modules(img: np.ndarray, cfg: dict, group, win=None, extra_masks=None) -> tuple[np.ndarray, dict]:
    mcfg = cfg.get("modules", {})
    on = {k: bool(mcfg.get(k, {}).get("enabled", False)) for k in ("remove", "grass", "sky", "twilight")}
    info: dict = {}
    if not any(on.values()):
        return img, info
    name = group.name
    sky_mask = None
    sky_done = False

    def need_sky():
        nonlocal sky_mask, sky_done
        if not sky_done:
            from .sky import detect_sky
            from ..imgutil import resize_max
            sky_mask, sinfo = detect_sky(resize_max(img, 1000)[0])
            info["sky_detection"] = sinfo
            sky_done = True
        return sky_mask

    def guarded(key, fn):
        nonlocal img
        try:
            img, res = fn()
            info[key] = {k: v for k, v in res.items() if not isinstance(v, np.ndarray)}
        except Exception as exc:  # optional module: report and continue
            log.error("[%s] module %s failed: %s", name, key, exc)
            info[key] = {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(limit=4)}

    if on["remove"]:
        from .remove import find_mask, remove_objects
        mask = find_mask(group, extra_masks)
        if mask is None:
            info["remove"] = {"applied": False, "reason": "no mask (<name>.mask.png or UI brush)"}
        else:
            from .sky import seed_of
            guarded("remove", lambda: remove_objects(img, mask, cfg, seed=seed_of(name)))
    if on["grass"]:
        from .grass import green_grass
        guarded("grass", lambda: green_grass(img, cfg, need_sky()))
    if on["twilight"]:
        from .twilight import twilight
        guarded("twilight", lambda: twilight(img, cfg, name, win, need_sky()))
    elif on["sky"]:
        from .sky import replace_sky
        m = need_sky()
        if m is None and not mcfg.get("sky", {}).get("interior_windows", False):
            info["sky"] = {"applied": False, "reason": info.get("sky_detection", {}).get("reason", "no sky")}
        else:
            guarded("sky", lambda: replace_sky(img, cfg, name, win, mask_small=m))
    return img, info

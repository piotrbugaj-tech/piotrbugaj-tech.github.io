"""Virtual twilight: deterministic dusk relight of a daytime photo.

Exterior (sky found):
  * sky -> twilight gradient (blue / pink / golden) with sky.py compositing,
  * foreground darkened (~1.6 EV), cooled and slightly desaturated (ambient dusk light),
  * facade windows (dark, smooth, rectangular regions under the sky line) lit with a warm glow
    that keeps frames/mullions, plus a soft light spill on the surrounding facade/ground.
Interior (no sky): window views are turned into dusk (darker, bluer), the room keeps its lamps
and gets slightly warmer and darker, like an evening interior.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from ..imgutil import LUMA, linear_to_srgb, resize_max, resize_rows, row_strips, srgb_to_linear
from . import sky as skymod

log = logging.getLogger(__name__)

WARM = np.array([1.0, 0.56, 0.20], np.float32)  # window glow (linear, ~2800 K lamp light)


def find_facade_windows(img_small: np.ndarray, sky_mask: np.ndarray | None) -> tuple[np.ndarray, list]:
    """Glass panes of a daytime facade: regions darker than their surroundings, smooth, roughly
    rectangular, below the sky line and above the ground.  Returns (glass weight 0..1, boxes)."""
    h, w = img_small.shape[:2]
    y = img_small @ LUMA
    local = cv2.GaussianBlur(y, (0, 0), max(4.0, 0.02 * max(h, w)))
    dark = (local - y) > np.maximum(0.06, 0.25 * local)
    if sky_mask is not None:
        dark &= sky_mask < 0.5
    rows = np.arange(h)[:, None]
    dark &= rows < 0.85 * h
    k = max(1, int(0.003 * max(h, w)))
    dark = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((2 * k + 1, 2 * k + 1), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    glass = np.zeros((h, w), np.float32)
    boxes = []
    green = (img_small[..., 1] > img_small[..., 0] * 1.08) & (img_small[..., 1] > img_small[..., 2] * 1.05)
    for i in range(1, n):
        x0, y0, ww, hh, area = stats[i]
        if area < 0.0002 * h * w or area > 0.03 * h * w:
            continue
        aspect = ww / max(hh, 1)
        fill = area / max(ww * hh, 1)
        if not (0.25 <= aspect <= 4.0) or fill < 0.6:
            continue
        comp = lab[y0:y0 + hh, x0:x0 + ww] == i
        if green[y0:y0 + hh, x0:x0 + ww][comp].mean() > 0.3:  # dark foliage
            continue
        glass[y0:y0 + hh, x0:x0 + ww][comp] = 1.0
        boxes.append((int(x0), int(y0), int(ww), int(hh)))
    return glass, boxes


def twilight(img: np.ndarray, cfg: dict, name: str, win=None, sky_mask_small: np.ndarray | None = None
             ) -> tuple[np.ndarray, dict]:
    tcfg = cfg.get("modules", {}).get("twilight", {})
    style = str(tcfg.get("style", "pink"))
    ev = float(tcfg.get("darken_ev", 2.0))
    glow = float(tcfg.get("window_glow", 1.0))
    H, W = img.shape[:2]
    small, _ = resize_max(img, 1000)
    hs, ws = small.shape[:2]
    if sky_mask_small is None:
        sky_mask_small, sinfo = skymod.detect_sky(small)
    else:
        sinfo = {}
    info = {"style": style, "exterior": sky_mask_small is not None}
    rng = np.random.default_rng(skymod.seed_of(name))
    if sky_mask_small is not None:
        # ---- exterior ------------------------------------------------------------------------
        glass, boxes = find_facade_windows(small, sky_mask_small)
        info["windows_lit"] = len(boxes)
        # per-window brightness variation + top-to-bottom falloff inside each pane
        gmap = np.zeros((hs, ws), np.float32)
        for (x0, y0, ww, hh) in boxes:
            v = float(rng.uniform(0.75, 1.15))
            ramp = np.linspace(1.0, 0.7, hh, dtype=np.float32)[:, None]
            gmap[y0:y0 + hh, x0:x0 + ww] = np.maximum(gmap[y0:y0 + hh, x0:x0 + ww], v * ramp)
        gmap *= glass
        # keep frames and mullions: only the darkest pixels inside a pane are glass
        ys = small @ LUMA
        loc = cv2.blur(ys, (5, 5))
        pane = np.clip((loc - ys + 0.05) / 0.1, 0, 1) * (glass > 0)
        gmap *= np.clip(0.35 + pane, 0, 1)
        spill = cv2.GaussianBlur(gmap, (0, 0), max(3.0, 0.012 * ws)) * 0.9 + \
            cv2.GaussianBlur(gmap, (0, 0), max(1.0, 0.003 * ws)) * 0.4
        sky_soft = cv2.GaussianBlur(sky_mask_small.astype(np.float32), (0, 0), 1.0)
        k = 2.0 ** -ev
        cool = np.array([0.74, 0.90, 1.30], np.float32)
        cool /= float(cool @ LUMA)
        g_int = 0.95 * glow
        for r0, r1 in row_strips(H, W):
            lin = srgb_to_linear(img[r0:r1])
            yv = (lin @ LUMA)[..., None]
            fg = (yv + (lin - yv) * 0.7) * k * cool          # darker, cooler, less saturated
            gm = resize_rows(gmap, W, H, r0, r1)[..., None]
            sp = resize_rows(spill, W, H, r0, r1)[..., None]
            # lit panes: warm, brighter in the middle of the pane, a hint of the original detail
            fg = fg * (1 - gm) + WARM * g_int * gm * (0.8 + 0.4 * np.clip(yv * 4, 0, 1))
            fg = fg + WARM * sp * 0.18 * glow + fg * sp * 0.6 * WARM  # light spill on the facade
            s = resize_rows(sky_soft, W, H, r0, r1)[..., None]
            # sky pixels are replaced afterwards; keep them unchanged here to preserve the matte
            img[r0:r1] = linear_to_srgb(np.clip(lin * s + fg * (1 - s), 0, 1))
        img, cinfo = skymod.replace_sky(img, cfg, name, style=style, twilight=True, mask_small=sky_mask_small)
        info["sky"] = {k2: v for k2, v in cinfo.items() if k2 != "mask_small"}
    else:
        # ---- interior: dusk through the windows ---------------------------------------------
        info["reason"] = sinfo.get("reason")
        wm = None
        if win is not None and win.mask.max() > 0.5:
            wm = cv2.resize(np.clip(win.mask, 0, 1).astype(np.float32), (ws, hs))
            wm = cv2.GaussianBlur(wm, (0, 0), 1.0)
        stops = skymod.TWILIGHT_STYLES.get(style, skymod.TWILIGHT_STYLES["pink"])
        dusk = srgb_to_linear(np.array(stops[1], np.float32))
        dusk = dusk / max(float(dusk @ LUMA), 1e-4)
        for r0, r1 in row_strips(H, W):
            lin = srgb_to_linear(img[r0:r1])
            yv = (lin @ LUMA)[..., None]
            room = lin * 2.0 ** -0.35 * np.array([1.04, 1.0, 0.94], np.float32)  # evening, warmer
            if wm is not None:
                m = resize_rows(wm, W, H, r0, r1)[..., None]
                f = 2.0 ** -1.8
                view = yv * f * dusk + (lin - yv) * 0.15 * f  # dark, dusk-tinted view keeping shapes
                room = room * (1 - m) + view * m
            img[r0:r1] = linear_to_srgb(np.clip(room, 0, 1))
        info["window_views"] = wm is not None
    return img, info

"""Lawn greening: dull / yellowish grass -> healthy green, only on the ground plane.

Grass = textured, moderately saturated yellow-green pixels in the lower part of the frame
(below the sky line and the upper third); dry patches enclosed by lawn are included.  The hue
is pulled towards ``target_hue`` and saturation raised slightly; luminance is kept.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..imgutil import resize_max, resize_rows, row_strips


def grass_mask(small: np.ndarray, sky_mask: np.ndarray | None = None) -> np.ndarray:
    h, w = small.shape[:2]
    hsv = cv2.cvtColor(small.astype(np.float32), cv2.COLOR_RGB2HSV)  # H in degrees
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = (H >= 45) & (H <= 150) & (S >= 0.15) & (V >= 0.1) & (V <= 0.92)
    dry = (H >= 25) & (H < 45) & (S >= 0.2) & (V >= 0.15) & (V <= 0.9)
    rows = np.arange(h)[:, None]
    ground = rows > 0.35 * h
    if sky_mask is not None and sky_mask.max() > 0.5:
        r_sky = np.nonzero(sky_mask.max(1) > 0.5)[0]
        ground &= rows > (r_sky.max() if len(r_sky) else 0)
    g = (green & ground).astype(np.uint8)
    k = max(3, int(0.01 * max(h, w)) | 1)
    lawn = cv2.morphologyEx(g, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    m = ((g > 0) | ((lawn > 0) & dry & ground)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= 0.004 * h * w  # lawns are large areas
    return cv2.GaussianBlur(keep[lab].astype(np.float32), (0, 0), 1.5)


def green_grass(img: np.ndarray, cfg: dict, sky_mask_small: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    gcfg = cfg.get("modules", {}).get("grass", {})
    target = float(gcfg.get("target_hue", 95.0))
    pull = float(gcfg.get("hue_pull", 0.6))
    sat = float(gcfg.get("saturation_boost", 0.25))
    small, _ = resize_max(img, 1000)
    hs, ws = small.shape[:2]
    if sky_mask_small is not None and sky_mask_small.shape != (hs, ws):
        sky_mask_small = cv2.resize(sky_mask_small, (ws, hs))
    m = grass_mask(small, sky_mask_small)
    frac = float((m > 0.5).mean())
    if frac < 0.005:
        return img, {"applied": False, "grass_frac": round(frac, 4)}
    Himg, Wimg = img.shape[:2]
    for r0, r1 in row_strips(Himg, Wimg):
        a = resize_rows(m, Wimg, Himg, r0, r1)
        if a.max() < 0.01:
            continue
        hsv = cv2.cvtColor(np.ascontiguousarray(img[r0:r1]), cv2.COLOR_RGB2HSV)
        hh = hsv[..., 0]
        hsv[..., 0] = hh + (target - hh) * pull * a
        hsv[..., 1] = np.clip(hsv[..., 1] * (1 + sat * a), 0, 0.85)
        img[r0:r1] = np.clip(cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB), 0, 1)
    return img, {"applied": True, "grass_frac": round(frac, 4)}

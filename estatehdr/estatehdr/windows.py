"""Window detection and window pull.

A window that needs a 'pull' is, by definition, a region whose radiance lies far
above the interior range (it is clipped in the metered frame and readable in the
darker brackets).  We therefore detect candidates physically in the merged
radiance, then classify connected regions:
  * window  - large, rectangular / straight-edged, textured or sky-coloured;
  * lamp    - small, very bright, smooth, often warm and round;
  * sun patch (sunlight on floor/wall) - lower part of the frame, texture
    continuous with the surroundings.
Windows get a log-exposure offset (computed for the tone mapper) so the view
lands at a chosen display level; the mask is refined with an edge-aware filter
guided by the dark exposure so the transition sits on the window frames.
Pixels clipped even in the darkest frame keep a reduced pull (they stay white,
as AutoHDR documents: the view is only as good as the darkest bracket).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import cv2
import numpy as np

from .imgutil import guided_filter, luminance

log = logging.getLogger(__name__)


@dataclass
class WindowInfo:
    mask: np.ndarray  # soft window mask (analysis res, 0..1)
    lamp_mask: np.ndarray  # light sources (analysis res, 0..1)
    patch_mask: np.ndarray  # sun patches (analysis res)
    clipped: np.ndarray  # darkest-frame clipping (analysis res)
    interior_level: float  # log2 luminance of the interior reference level
    regions: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _region_features(L, rgb, comp_mask, interior_level, H, W):
    ys, xs = np.nonzero(comp_mask)
    area = len(ys)
    cnts, _ = cv2.findContours(comp_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cnts, key=cv2.contourArea)
    hull = cv2.convexHull(c)
    hull_area = max(cv2.contourArea(hull), 1.0)
    rect = cv2.minAreaRect(c)
    rect_area = max(rect[1][0] * rect[1][1], 1.0)
    peri = max(cv2.arcLength(c, True), 1.0)
    approx = cv2.approxPolyDP(c, 0.02 * peri, True)
    vals = L[ys, xs]
    col = rgb[ys, xs]
    y = col @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    chroma = col / (y[:, None] + 1e-6)
    sat = float(np.median(chroma.max(1) - chroma.min(1)))
    blue = float(np.mean((chroma[:, 2] > chroma[:, 0] * 1.08) & (chroma[:, 2] > 0.9)))
    warm = float(np.mean(chroma[:, 0] > chroma[:, 2] * 1.25))
    tex = float(np.std(vals))
    # local texture: mean absolute Laplacian inside the region
    return {
        "area_frac": area / float(H * W),
        "excess_ev": float(np.median(vals) - interior_level),
        "peak_ev": float(np.percentile(vals, 95) - interior_level),
        "solidity": area / hull_area,
        "rectangularity": area / rect_area,
        "vertices": int(len(approx)),
        "cy": float(ys.mean() / H),
        "cx": float(xs.mean() / W),
        "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
        "saturation": sat,
        "blue_frac": blue,
        "warm_frac": warm,
        "texture": tex,
        "H": H,
    }


def window_score(f: dict) -> float:
    """Evidence that a bright region is a window (view to the exterior) rather than a sun
    patch or a lit surface.  Windows: far above the interior, strongly textured (a view),
    reaching into the upper half of the frame, not uniformly warm (sunlit wood/beige)."""
    top = f["bbox"][1] / max(f["H"], 1)
    s = min(f["excess_ev"] - 3.0, 3.0)
    s += 2.0 * (min(f["texture"], 2.0) - 0.7)
    s += 3.0 * (0.45 - top)
    if f["warm_frac"] > 0.7:
        s -= 2.0 * (f["warm_frac"] - 0.7)
    s += f["rectangularity"] - 0.6
    return float(s)


def classify(f: dict, cfg: dict) -> str:
    """window | lamp | sun_patch | glow (smooth bright surface, e.g. wall next to a lamp)."""
    lamp_max = float(cfg.get("lamp_max_area_frac", 0.004))
    if f["area_frac"] < lamp_max and (f["warm_frac"] > 0.5 or f["texture"] < 0.35) and f["solidity"] > 0.6:
        return "lamp"
    # exterior scenes: bright smooth/blue region touching the top border = sky, not a window
    if f["bbox"][1] <= 1 and f["area_frac"] > 0.03 and (f["blue_frac"] > 0.5 or f["texture"] < 0.5):
        return "sky"
    # small bright blob with a much brighter core = lamp with its glow
    if f["area_frac"] < 2 * lamp_max and f["peak_ev"] - f["excess_ev"] > 1.5:
        return "lamp"
    f["window_score"] = window_score(f)
    min_area = float(cfg.get("window_min_area_frac", 0.005))
    if f["window_score"] > float(cfg.get("window_score_min", 0.5)) and (f["area_frac"] >= min_area or f["window_score"] > 2.0):
        return "window"
    if f["area_frac"] < lamp_max * 0.5:
        return "lamp"
    if f["texture"] < 0.45:
        return "glow"
    top = f["bbox"][1] / max(f["H"], 1)
    return "sun_patch" if top > 0.4 else "glow"


def detect(rad_small: np.ndarray, clipped_small: np.ndarray | None, cfg: dict) -> WindowInfo | None:
    wcfg = cfg.get("windows", {})
    if not wcfg.get("enabled", True):
        return None
    H, W = rad_small.shape[:2]
    Y = luminance(rad_small)
    L = np.log2(Y + 1e-6)
    # radiance is scaled to the reference (metered) exposure, so values near 1 are what the
    # metered frame could not record: that is exactly what a window pull has to fix
    ref_clip = L > np.log2(0.92)
    inside = ~ref_clip
    interior_level = float(np.median(L[inside])) if inside.sum() > 0.2 * L.size else float(np.median(L))
    over = float(wcfg.get("over_ev", 2.5))
    thr = float(np.clip(np.log2(0.92), interior_level + over, interior_level + over + 2.0))
    cand = (L > thr).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    # bridge mullions / frames: close with a small kernel relative to the image size
    k = max(3, int(round(0.012 * max(H, W))) | 1)
    closed = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(closed, 8)
    min_area = float(wcfg.get("min_area_frac", 0.0015)) * H * W
    win = np.zeros((H, W), np.float32)
    lamp = np.zeros((H, W), np.float32)
    patch = np.zeros((H, W), np.float32)
    regions = []
    for i in range(1, n):
        comp = lab == i
        if st[i, cv2.CC_STAT_AREA] < 4:
            continue
        f = _region_features(L, rad_small, comp, interior_level, H, W)
        if st[i, cv2.CC_STAT_AREA] < min_area:
            kind = "lamp" if f["excess_ev"] > 1.0 else "small"
        else:
            kind = classify(f, wcfg)
        f["kind"] = kind
        regions.append(f)
        # the region support: original candidate pixels plus the closed gaps (frames)
        if kind == "window":
            win[comp] = 1.0
        elif kind == "lamp":
            lamp[comp] = 1.0
        elif kind == "sun_patch":
            patch[comp] = 1.0
    # soft, edge-aware window mask: within the closed region, weight by how far above the
    # threshold the radiance is; frames/mullions (dark) fall to 0, glass to 1
    if win.any():
        soft = np.clip((L - (thr - 1.0)) / 1.0, 0, 1) * win
        guide = np.clip((L - interior_level) / 8.0, -1, 1).astype(np.float32)
        r = max(1, int(round(float(wcfg.get("feather_px", 2.0)))))
        soft = guided_filter(guide, soft.astype(np.float32), r, 1e-3)
        win_soft = np.clip(soft, 0, 1)
    else:
        win_soft = win
    clipped = clipped_small if clipped_small is not None else np.zeros((H, W), np.float32)
    stats = {"windows": sum(r["kind"] == "window" for r in regions),
             "lamps": sum(r["kind"] == "lamp" for r in regions),
             "sun_patches": sum(r["kind"] == "sun_patch" for r in regions),
             "window_area_frac": float((win_soft > 0.5).mean()),
             "window_clipped_frac": float((clipped[win_soft > 0.5] > 0.5).mean()) if (win_soft > 0.5).any() else 0.0,
             "threshold_ev_above_median": float(thr - interior_level)}
    log.info("windows: %d window(s) (%.1f%% of frame, %.0f%% clipped in darkest frame), %d lamp(s), %d sun patch(es)",
             stats["windows"], 100 * stats["window_area_frac"], 100 * stats["window_clipped_frac"],
             stats["lamps"], stats["sun_patches"])
    return WindowInfo(win_soft.astype(np.float32), lamp, patch, clipped.astype(np.float32), interior_level, regions, stats)


def pull_weights(win: WindowInfo) -> np.ndarray:
    """Per-pixel weight of the window pull (analysis res). Glass clipped even in the darkest
    frame gets no pull: there is no information to recover and pulling would turn it grey."""
    return np.clip(win.mask * (1.0 - win.clipped), 0, 1).astype(np.float32)


def exclusion(win: WindowInfo) -> np.ndarray:
    return np.clip(win.mask + win.lamp_mask, 0, 1).astype(np.float32)

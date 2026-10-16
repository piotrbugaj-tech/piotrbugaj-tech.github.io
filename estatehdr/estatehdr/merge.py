"""Radiance merge with ghost rejection.

Every frame is mapped to scene radiance (linear value / relative exposure) in
reference coordinates.  Pixels are averaged with weights that favour longer
exposures (better SNR) and exclude near-saturated / near-black values.
Ghosts (moving people, curtains, trees) are found at analysis resolution by
checking each frame against a consensus that starts at the reference frame
and grows towards darker and brighter exposures; inconsistent pixels of
non-reference frames are rejected.  The full-resolution merge is streamed in
horizontal strips so 24-60 Mpx series fit in memory.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from .imgutil import chmax, chmin, luminance, resize_to

log = logging.getLogger(__name__)


@dataclass
class MergeResult:
    radiance: np.ndarray  # HxWx3 float32, scaled to the reference exposure
    clipped: np.ndarray  # HxW float32 in [0,1]: saturated even in the darkest frame
    ghost: np.ndarray | None  # analysis-res union of rejected areas (for diagnostics)
    stats: dict


def _smooth_step(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def frame_weight(x: np.ndarray, exposure: float, sat_hi: float = 0.97, sat_lo: float = 0.82,
                 dark: float = 0.003) -> np.ndarray:
    """Per-pixel weight (H,W) of one linear frame."""
    mx = chmax(x)
    w_sat = 1.0 - _smooth_step(sat_lo, sat_hi, mx)
    w_dark = _smooth_step(0.0, dark, luminance(x))
    return (w_sat * (0.02 + 0.98 * w_dark) * exposure).astype(np.float32)


def _warp_small(f, ref_shape, scale):
    H = getattr(f, "homography", None)
    if H is None or np.allclose(H, np.eye(3), atol=1e-6):
        return f.small, np.ones(f.small.shape[:2], bool)
    S = np.diag([scale, scale, 1.0])
    Hs = S @ H @ np.linalg.inv(S)
    h, w = ref_shape[:2]
    out = cv2.warpPerspective(f.small, Hs, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                              borderMode=cv2.BORDER_REPLICATE)
    valid = cv2.warpPerspective(np.ones(f.small.shape[:2], np.uint8), Hs, (w, h),
                                flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP, borderValue=0).astype(bool)
    return out, valid


def detect_ghosts(series, cfg: dict) -> list[np.ndarray]:
    """Returns per-frame rejection masks (analysis resolution, float 0..1)."""
    frames = series.frames
    ref = frames[series.ref]
    scale = ref.small.shape[0] / ref.shape[0]
    n = len(frames)
    masks = [np.zeros(ref.small.shape[:2], np.float32) for _ in range(n)]
    if n == 1 or not cfg.get("enabled", True):
        return masks
    thr = float(cfg.get("threshold_ev", 0.45))
    noise_k = float(cfg.get("noise_k", 0.035))
    min_area = float(cfg.get("min_area_frac", 0.0004)) * ref.small.shape[0] * ref.small.shape[1]
    warped = [_warp_small(f, ref.small.shape, scale) for f in frames]
    cur = ref.small / ref.exposure
    cur_valid = (chmax(ref.small) < 0.85) & (luminance(ref.small) > 0.01)
    order = sorted([i for i in range(n) if i != series.ref], key=lambda i: abs(np.log2(frames[i].exposure)))
    for i in order:
        x, valid = warped[i]
        e = frames[i].exposure
        vi = valid & (chmax(x) < 0.85) & (luminance(x) > 0.01)
        both = vi & cur_valid
        # per-channel log difference: moving objects often have a luminance similar to what they
        # cover (blue shirt vs. brown headboard) but a different colour
        floor = 0.004
        lx = np.log2(np.maximum(x / e, floor / e))
        lc = np.log2(np.maximum(cur, floor / e))
        d = np.abs(lx - lc).max(-1)
        # tolerance grows for low signal (noise) - signal measured in each frame's own scale
        sig = np.minimum(chmin(x), chmin(cur) * e)
        tol = thr + noise_k / np.sqrt(np.maximum(sig, 1e-4))
        bad = both & (d > tol)
        # clean up: remove speckles, keep blobs, grow a margin
        bad8 = bad.astype(np.uint8)
        bad8 = cv2.morphologyEx(bad8, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        cnt, lab, st, _ = cv2.connectedComponentsWithStats(bad8, 8)
        keep = np.zeros(cnt, bool)
        keep[1:] = st[1:, cv2.CC_STAT_AREA] >= min_area
        bad = keep[lab]
        r = max(2, int(round(0.006 * max(bad.shape))))
        bad = cv2.dilate(bad.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
        m = cv2.GaussianBlur(bad.astype(np.float32), (0, 0), r / 2)
        masks[i] = np.clip(m * 1.5, 0, 1)
        # grow the consensus where it had no valid data yet
        add = vi & ~cur_valid & (masks[i] < 0.5)
        cur = cur.copy()
        cur[add] = (x / e)[add]
        cur_valid = cur_valid | add
    return masks


def neutralize_black_bias(rad: np.ndarray, max_frac: float = 0.02) -> tuple[np.ndarray, list]:
    """Remove a coloured offset in the deepest shadows (sensor noise clipped at zero and then
    multiplied by white-balance gains leaves a magenta/purple floor).  The darkest pixels of a
    scene are expected to be neutral; only a small offset relative to the median is removed."""
    y = luminance(rad[::4, ::4])
    thr = np.percentile(y, 2)
    m = y <= thr
    if m.sum() < 100:
        return rad, [0.0, 0.0, 0.0]
    means = rad[::4, ::4][m].mean(0)
    off = means - means.min()
    lim = max_frac * float(np.median(y))
    off = np.minimum(off, lim)
    if off.max() <= 0:
        return rad, [0.0, 0.0, 0.0]
    rad -= off.astype(np.float32)[None, None]
    np.maximum(rad, 0, out=rad)
    return rad, off.round(6).tolist()


def merge_series(series, cfg: dict) -> MergeResult:
    frames = series.frames
    ref = frames[series.ref]
    H_full, W_full = ref.shape[:2]
    mcfg = cfg.get("merge", {})
    gcfg = cfg.get("deghost", {})
    ghost_small = detect_ghosts(series, gcfg)
    union = np.maximum.reduce(ghost_small) if len(ghost_small) > 1 else ghost_small[0]
    stats = {"ghost_fraction": float((union > 0.5).mean())}
    rad = np.zeros((H_full, W_full, 3), np.float32)
    if len(frames) == 1:
        x = ref.linear()
        rad[:] = x
        clipped = _smooth_step(0.9, 0.99, chmax(x)).astype(np.float32)
        rad, off = neutralize_black_bias(rad, float(mcfg.get("black_bias_max", 0.05)))
        return MergeResult(rad, clipped, None, {**stats, "frames": 1, "black_bias": off})
    darkest = int(np.argmin([f.exposure for f in frames]))
    strip = int(mcfg.get("strip_rows", 1024))
    sat_lo, sat_hi = float(mcfg.get("sat_lo", 0.82)), float(mcfg.get("sat_hi", 0.97))
    clipped = np.zeros((H_full, W_full), np.float32)
    ghost_full = [None if (m.max() <= 0) else m for m in ghost_small]
    for y0 in range(0, H_full, strip):
        y1 = min(H_full, y0 + strip)
        num = np.zeros((y1 - y0, W_full, 3), np.float32)
        den = np.zeros((y1 - y0, W_full), np.float32)
        dark_val = None
        for i, f in enumerate(frames):
            x = _frame_strip(f, y0, y1, W_full)
            w = frame_weight(x, f.exposure, sat_hi, sat_lo)
            if i == series.ref:
                w = w + 1e-6  # always defined
            if ghost_full[i] is not None:
                g = _mask_strip(ghost_full[i], y0, y1, H_full, W_full)
                w *= (1.0 - g)
            valid = _valid_strip(f, y0, y1, W_full)
            if valid is not None:
                w *= valid
            num += (w / f.exposure)[..., None] * x
            den += w
            if i == darkest:
                dark_val = x
        good = den > 1e-12
        out = np.where(good[..., None], num / np.maximum(den, 1e-12)[..., None], dark_val / frames[darkest].exposure)
        rad[y0:y1] = out
        clipped[y0:y1] = _smooth_step(0.9, 0.99, chmax(dark_val))
    rad, off = neutralize_black_bias(rad, float(mcfg.get("black_bias_max", 0.05)))
    stats.update({"frames": len(frames), "darkest_clipped_frac": float((clipped > 0.5).mean()), "black_bias": off,
                  "dynamic_range_ev": float(np.log2(max(np.percentile(luminance(rad[::8, ::8]), 99.9), 1e-6)
                                                    / max(np.percentile(luminance(rad[::8, ::8]), 0.5), 1e-6)))})
    return MergeResult(rad, clipped, union, stats)


def _frame_strip(f, y0, y1, W):
    """Linear float strip [y0,y1) of frame f warped into reference coordinates."""
    H = getattr(f, "homography", None)
    img = f.decoded.image
    if H is None or np.allclose(H, np.eye(3), atol=1e-6):
        sub = img[y0:y1]
    else:
        T = np.array([[1, 0, 0], [0, 1, y0], [0, 0, 1]], np.float64)
        Hs = H @ T  # strip pixel -> frame pixel
        # only the source rows that can be touched
        pts = np.float32([[0, 0], [W, 0], [W, y1 - y0], [0, y1 - y0]]).reshape(-1, 1, 2)
        src = cv2.perspectiveTransform(pts, Hs).reshape(-1, 2)
        sy0 = max(0, int(np.floor(src[:, 1].min())) - 4)
        sy1 = min(img.shape[0], int(np.ceil(src[:, 1].max())) + 4)
        if sy1 <= sy0:
            sy0, sy1 = 0, img.shape[0]
        T2 = np.array([[1, 0, 0], [0, 1, -sy0], [0, 0, 1]], np.float64)
        sub = cv2.warpPerspective(img[sy0:sy1], T2 @ Hs, (W, y1 - y0),
                                  flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
    if f.lut is not None:
        return f.lut[sub]
    return sub.astype(np.float32) * np.float32(1.0 / f.decoded.max_value)


def _valid_strip(f, y0, y1, W):
    H = getattr(f, "homography", None)
    if H is None or np.allclose(H, np.eye(3), atol=1e-6):
        return None
    h_img, w_img = f.decoded.image.shape[:2]
    ys, xs = np.mgrid[y0:y1:8, 0:W:8]
    pts = np.stack([xs.ravel(), ys.ravel()], 1).astype(np.float32).reshape(-1, 1, 2)
    m = cv2.perspectiveTransform(pts, H).reshape(-1, 2)
    ok = (m[:, 0] >= 0) & (m[:, 0] < w_img) & (m[:, 1] >= 0) & (m[:, 1] < h_img)
    ok = ok.reshape(xs.shape).astype(np.float32)
    return cv2.resize(ok, (W, y1 - y0), interpolation=cv2.INTER_LINEAR)


def _mask_strip(mask_small, y0, y1, H, W):
    sh, sw = mask_small.shape
    sy0 = y0 * sh / H
    sy1 = y1 * sh / H
    a = max(0, int(np.floor(sy0)) - 1)
    b = min(sh, int(np.ceil(sy1)) + 2)
    part = mask_small[a:b]
    up = cv2.resize(part, (W, int(round((b - a) * H / sh))), interpolation=cv2.INTER_LINEAR)
    off = int(round(y0 - a * H / sh))
    out = up[off:off + (y1 - y0)]
    if out.shape[0] < y1 - y0:
        out = np.pad(out, ((0, y1 - y0 - out.shape[0]), (0, 0)), mode="edge")
    return out

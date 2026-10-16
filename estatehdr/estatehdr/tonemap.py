"""Local + global tone mapping of merged radiance to display sRGB.

All luminance work happens in log2 units.
  1. Local: an edge-aware base layer B of log luminance (two-scale guided filter,
     analysis resolution) is compressed around the interior key - shadows and
     highlights by separate factors - and the resulting gain map is transferred
     to full resolution with guided upsampling (details stay full-res).
  2. Window pull: a per-pixel log offset on window glass (weights from
     ``windows.py``), solved iteratively so the median of the view lands on the
     configured display value after the whole mapping.
  3. Global: a monotone curve (PCHIP in log domain) anchored on *interior*
     percentiles of the locally mapped image: black percentile -> black target,
     key -> key target, white percentile -> white target, plus a soft shoulder.
     Anchoring on percentiles bounds clipping and crushed blacks directly.
  4. Colour: luminance ratio with saturation preservation, soft channel
     clipping without hue shifts, then contrast / vibrance / saturation.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np
from scipy.interpolate import PchipInterpolator

from .imgutil import LUMA, fast_guided_filter, guided_filter, linear_to_srgb, luminance, resize_max, srgb_to_linear

log = logging.getLogger(__name__)
EPS = 1e-6


def compute_base(L_small: np.ndarray, cfg: dict) -> np.ndarray:
    """Two-scale edge-aware base layer of log luminance (analysis resolution)."""
    h, w = L_small.shape
    diag = float(np.hypot(h, w))
    r1 = max(2, int(cfg.get("base_radius_frac", 0.025) * diag))
    r2 = max(r1 + 1, int(cfg.get("base_radius_frac2", 0.08) * diag))
    eps = float(cfg.get("base_eps", 0.08))  # log2 units squared
    b1 = guided_filter(L_small, L_small, r1, eps)
    b2 = guided_filter(L_small, L_small, r2, eps * 2)
    mix = float(cfg.get("base_mix", 0.5))
    return (1 - mix) * b1 + mix * b2


class ToneCurve:
    """Monotone log2-luminance -> sRGB display value mapping through anchor points."""

    def __init__(self, lo: float, key: float, hi: float, cfg: dict):
        black = float(cfg.get("black_target", 0.03))
        k_t = float(cfg.get("target_key", 0.56))
        w_t = float(cfg.get("target_white", 0.96))
        sh = float(cfg.get("shoulder_ev", 1.5))
        toe = float(cfg.get("toe_ev", 2.0))
        # keep anchors ordered with a minimum spacing
        key = max(key, lo + 0.5)
        hi = max(hi, key + 0.5)
        xs = [lo - toe, lo, key, hi, hi + sh, hi + sh + 6.0]
        ys = [0.0, black, k_t, w_t, 1.0, 1.0]
        self.f = PchipInterpolator(np.array(xs), np.array(ys), extrapolate=True)
        self.anchors = dict(lo=lo, key=key, hi=hi)
        grid = np.linspace(xs[0] - 4.0, xs[-1], 4096)
        self._gx = grid
        self._gy = np.clip(self.f(grid), 0.0, 1.0).astype(np.float32)
        self._gy[grid < xs[0]] = 0.0

    def __call__(self, L: np.ndarray) -> np.ndarray:
        return np.interp(L, self._gx, self._gy).astype(np.float32)

    def inverse(self, y: float) -> float:
        return float(np.interp(y, self._gy, self._gx))


def _compress(B, key, c_sh, c_hl):
    d = B - key
    return key + np.where(d < 0, d * c_sh, d * c_hl)


def tone_map(radiance: np.ndarray, cfg: dict, window_mask: np.ndarray | None = None,
             window_weight: np.ndarray | None = None, exclude_small: np.ndarray | None = None,
             window_cfg: dict | None = None, analysis_side: int = 1600, debug: dict | None = None,
             extra_pulls: list | None = None, clipped: np.ndarray | None = None) -> np.ndarray:
    """Radiance (HxWx3 linear) -> display-referred sRGB float32 [0,1].

    extra_pulls: [(weight_map_small, target_srgb, strength, name)] for other regions (sun patches)."""
    H, W = radiance.shape[:2]
    Y = luminance(radiance)
    L = np.log2(Y + EPS).astype(np.float32)
    L_small, s = resize_max(L, analysis_side)
    inside = (exclude_small < 0.5) if exclude_small is not None else np.ones(L_small.shape, bool)
    if inside.sum() < 0.05 * inside.size:
        inside = np.ones(L_small.shape, bool)
    c_sh = float(cfg.get("compress_shadows", 0.7))
    c_hl = float(cfg.get("compress_highlights", 0.6))
    key0 = float(np.percentile(L_small[inside], float(cfg.get("key_percentile", 50))))
    p_lo = float(cfg.get("black_percentile", 0.5))
    p_hi = float(cfg.get("white_percentile", 99.0))

    def local(offset):
        Ls = L_small + offset if offset is not None else L_small
        B = compute_base(Ls, cfg)
        g = (_compress(B, key0, c_sh, c_hl) - B).astype(np.float32)
        if offset is not None:
            g = g + offset
        return g, B

    gain_small, B = local(None)
    L1 = L_small + gain_small
    curve = ToneCurve(*np.percentile(L1[inside], [p_lo, 50, p_hi]), cfg)
    # --- regional pulls: windows (exterior view) and sun patches ---------------------------
    pulls = []  # (weight map, target sRGB, strength, name)
    if window_weight is not None and window_weight.max() > 0.5:
        wc = window_cfg or {}
        pulls.append((window_weight, float(wc.get("exterior_target", 0.62)), float(wc.get("strength", 1.0)), "window"))
    for wmap, tgt, strength, nm in extra_pulls or []:
        if wmap is not None and wmap.max() > 0.5:
            pulls.append((wmap, tgt, strength, nm))
    pull_info = {}
    if pulls:
        Os = []
        for wmap, tgt, strength, nm in pulls:
            sel = wmap > 0.5
            Os.append(curve.inverse(tgt) - float(np.median(L1[sel])))
        for _ in range(4):
            off = np.zeros_like(L_small)
            for (wmap, tgt, strength, nm), O in zip(pulls, Os):
                off += min(O, 0.0) * strength * wmap
            gain_small, B = local(off.astype(np.float32))
            L1 = L_small + gain_small
            done = True
            for i, (wmap, tgt, strength, nm) in enumerate(pulls):
                sel = wmap > 0.5
                want = curve.inverse(tgt)
                reached = float(np.median(L1[sel]))
                if abs(reached - want) > 0.05 and strength > 0.999 and Os[i] < 0:
                    Os[i] += want - reached
                    done = False
            if done:
                break
        for (wmap, tgt, strength, nm), O in zip(pulls, Os):
            pull_info[nm] = -min(O, 0.0) * strength
        curve = ToneCurve(*np.percentile(L1[inside], [p_lo, 50, p_hi]), cfg)
    pull = -pull_info.get("window", 0.0)
    # --- full-resolution transfer of the gain ------------------------------------------------
    gain_up = cv2.resize(gain_small, (W, H), interpolation=cv2.INTER_LINEAR)
    if cfg.get("guided_upsample", True) and s < 1.0:
        r = max(2, int(round(2.0 / max(s, 1e-3))))
        guide = (L - L.mean()) / max(float(L.std()), 1e-3)
        gain_up = fast_guided_filter(guide.astype(np.float32), gain_up, r, float(cfg.get("upsample_eps", 0.02)),
                                     s=max(1, int(1 / s / 2)))
    detail = float(cfg.get("detail", 1.0))
    if abs(detail - 1.0) > 1e-3:
        B_up = cv2.resize(B, (W, H), interpolation=cv2.INTER_LINEAR)
        gain_up = gain_up + (detail - 1.0) * np.clip(L - B_up, -2, 2)
        del B_up
    disp = curve(L + gain_up)  # sRGB-encoded display luminance
    del gain_up
    Yt = srgb_to_linear(disp)
    # --- colour --------------------------------------------------------------------------------
    sat_keep = float(cfg.get("saturation_preserve", 0.9))
    ratio = np.clip(radiance / (Y[..., None] + EPS), 0, 8)
    rgb = Yt[..., None] * np.power(ratio, sat_keep)
    del ratio
    rgb *= (Yt / (luminance(rgb) + EPS))[..., None]
    rgb = np.clip(rgb, 0, 1.5)
    rgb = gamut_rolloff(rgb, 0.9, 1.0)  # bring out-of-range channels into [0,1] without hue shifts
    out = finishing(linear_to_srgb(rgb), cfg)
    del rgb
    # soft highlight roll-off as the very last colour step: no channel hits 255 unless the
    # pixel carries no information (clipped in every frame, handled below)
    out = linear_to_srgb(gamut_rolloff(srgb_to_linear(out), float(cfg.get("highlight_knee", 0.88)),
                                       float(cfg.get("highlight_cap", 0.975))))
    if clipped is not None and clipped.max() > 0.5:
        # areas clipped even in the darkest frame carry no information: render them as clean
        # white with a soft edge (instead of jagged, colour-fringed plateaus)
        sig = max(1.0, 1.5 * W / 2000.0)
        c = cv2.GaussianBlur(clipped.astype(np.float32), (0, 0), sig)
        c = np.clip((c - 0.25) / 0.5, 0, 1)
        c = (c * c * (3 - 2 * c))[..., None]
        out = out * (1 - c) + c * 1.0
    if debug is not None:
        debug.update({"key_log2": key0, **{f"anchor_{k}": v for k, v in curve.anchors.items()},
                      **{f"pull_{k}_ev": v for k, v in pull_info.items()}})
    return out


def gamut_rolloff(rgb: np.ndarray, knee: float = 0.88, cap: float = 0.975) -> np.ndarray:
    """Soft highlight roll-off of the largest channel (display-linear), keeping luminance:
    saturated highlights (warm lamp glow, sunlit wood) desaturate gradually instead of
    clipping one channel at 255."""
    y = luminance(rgb)[..., None]
    m = rgb.max(-1, keepdims=True)
    head = cap - knee
    m2 = np.where(m > knee, knee + head * np.tanh((m - knee) / head), m)
    # scale chroma so the max channel becomes m2 (luminance unchanged); if y itself is > m2
    # the pixel becomes neutral at y
    k = np.where(m > knee, np.clip((m2 - y) / np.maximum(m - y, EPS), 0, 1), 1.0)
    out = y + (rgb - y) * k
    return np.clip(out, 0, 1).astype(np.float32)


def finishing(img: np.ndarray, cfg: dict) -> np.ndarray:
    """Display-space adjustments: contrast S-curve, vibrance, saturation."""
    out = img
    contrast = float(cfg.get("contrast", 0.0))
    if abs(contrast) > 1e-3:
        # S-curve around 0.5 on luminance only (keeps colour ratios), strength in [-1, 1]
        y = out @ LUMA
        y2 = np.clip(y + contrast * y * (1 - y) * (2 * y - 1) * 1.5, 0, 1)
        out = np.clip(out * (y2 / (y + EPS))[..., None], 0, 1)
    vib = float(cfg.get("vibrance", 0.0))
    sat = float(cfg.get("saturation", 1.0))
    if abs(vib) > 1e-3 or abs(sat - 1.0) > 1e-3:
        y = (out @ LUMA)[..., None]
        chroma = out - y
        cmag = np.sqrt((chroma ** 2).sum(-1, keepdims=True))
        boost = sat * (1.0 + vib * np.exp(-cmag / 0.08))
        out = np.clip(y + chroma * boost, 0, 1)
    return out.astype(np.float32)

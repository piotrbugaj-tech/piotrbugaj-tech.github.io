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

from . import accel
from .imgutil import (LUMA, box, chmax, chmin, guided_filter, linear_to_srgb, luminance, resize_max, resize_rows,
                      row_strips, srgb_to_linear)

log = logging.getLogger(__name__)
EPS = 1e-6


def noise_floor(radiance: np.ndarray, k: float = 1.5, rows: int = 768, robust: bool = False,
                min_floor: float = 0.0) -> float:
    """Linear luminance level of the sensor noise in the shadows (Immerkaer estimate on the darkest
    fifth of a full-resolution band).  Log luminance is taken of Y + floor, so pixels at or below
    the noise (zero-clipped RAW channels) do not become -20 EV outliers that local tone mapping
    turns into black specks; merged brackets have little shadow noise and get a tiny floor.
    ``robust``: low percentile over 32 px blocks of dark pixels instead of their mean, so the texture
    of a finished photo (fabric, rug, foliage in the shadows) is not taken for noise (D-49).  Blocks with
    no response at all (pure black, JPEG-flattened shadows) carry no noise information and are skipped;
    ``min_floor`` (one 8-bit code value for a finished JPEG) bounds the result from below, because a
    floor of ~0 turns code-0 pixels into -20 EV outliers that drag the black anchor down (review)."""
    H, W = radiance.shape[:2]
    best = 0.0
    for c in (0.3, 0.5, 0.7):  # a few bands: noise is a sensor property, the scene is not
        r0 = int(np.clip(c * H - rows // 2, 0, max(0, H - rows)))
        y = luminance(radiance[r0:r0 + rows]).astype(np.float32)
        if y.shape[0] < 8 or y.shape[1] < 8:
            continue
        resp = np.abs(cv2.filter2D(y, -1, np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)))[1:-1, 1:-1]
        yc = y[1:-1, 1:-1]
        dark = yc <= np.percentile(yc, 20)
        if dark.sum() < 1000:
            continue
        if robust:
            bh, bw = resp.shape[0] // 32, resp.shape[1] // 32
            if bh < 1 or bw < 2:
                continue
            crop = (slice(0, bh * 32), slice(0, bw * 32))
            rs = cv2.resize(np.where(dark, resp, 0)[crop], (bw, bh), interpolation=cv2.INTER_AREA)
            ds = cv2.resize(dark[crop].astype(np.float32), (bw, bh), interpolation=cv2.INTER_AREA)
            ok = ds > 0.5
            if ok.sum() < 4:
                continue
            rb = rs[ok] / ds[ok]
            rb = rb[rb > 1e-7]
            if rb.size < 4:
                continue
            best = max(best, float(np.sqrt(np.pi / 2) / 6.0 * np.percentile(rb, 10)))
            continue
        best = max(best, float(np.sqrt(np.pi / 2) / 6.0 * np.mean(resp[dark])))
    return max(EPS, float(min_floor), k * best)


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
             extra_pulls: list | None = None, clipped: np.ndarray | None = None,
             inplace: bool = False) -> np.ndarray:
    """Radiance (HxWx3 linear) -> display-referred sRGB float32 [0,1].

    Full-resolution work runs in row strips; with ``inplace`` the result overwrites ``radiance``
    (peak memory ~ image + two scalar maps, needed for 60 Mpx series).

    extra_pulls: [(weight_map_small, target_srgb, strength, name)] for other regions (sun patches)."""
    H, W = radiance.shape[:2]
    floor = (noise_floor(radiance, float(cfg.get("noise_floor_k", 1.5)), robust=bool(cfg.get("noise_floor_robust", False)),
                         min_floor=float(cfg.get("noise_floor_min", 0.0)))
             if cfg.get("noise_floor", True) else EPS)
    # full-resolution log luminance, computed strip by strip (the only full-res scalar map kept)
    L = np.empty((H, W), np.float32)
    acc = np.zeros(2)
    for r0, r1 in row_strips(H, W):
        Ls = np.log2(luminance(radiance[r0:r1]) + floor)
        L[r0:r1] = Ls
        acc += (float(Ls.sum(dtype=np.float64)), float(np.square(Ls, dtype=np.float64).sum()))
    L_mu = acc[0] / L.size
    L_sd = max(float(np.sqrt(max(acc[1] / L.size - L_mu * L_mu, 0.0))), 1e-3)
    L_small, s = resize_max(L, analysis_side)
    inside = (exclude_small < 0.5) if exclude_small is not None else np.ones(L_small.shape, bool)
    if inside.sum() < 0.05 * inside.size:
        inside = np.ones(L_small.shape, bool)
    c_sh = float(cfg.get("compress_shadows", 0.7))
    c_hl = float(cfg.get("compress_highlights", 0.6))
    key0 = float(np.percentile(L_small[inside], float(cfg.get("key_percentile", 50))))
    p_lo = float(cfg.get("black_percentile", 0.5))
    p_hi = float(cfg.get("white_percentile", 99.0))
    # the black anchor (darkest p_lo) is mapped to black_target: on low-contrast scenes (a daylight
    # facade with dark window panes spans ~1 EV from p_lo to the key) that stretches the
    # darkest region far beyond the real scene contrast; limit the stretch, which raises black
    raw_span = max(key0 - float(np.percentile(L_small[inside], p_lo)), 0.1)
    max_span = float(cfg.get("max_toe_expansion", 4.0)) * raw_span
    k_lin = float(srgb_to_linear(np.float32(cfg.get("target_key", 0.56))))
    black_eff = max(float(cfg.get("black_target", 0.03)), float(linear_to_srgb(np.float32(k_lin * 2.0 ** -max_span))))
    if black_eff > float(cfg.get("black_target", 0.03)) + 1e-4:
        cfg = {**cfg, "black_target": black_eff}

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
    # --- full-resolution transfer of the gain + colour, strip by strip ----------------------
    guided = bool(cfg.get("guided_upsample", True)) and s < 1.0
    if guided:
        r = max(2, int(round(2.0 / max(s, 1e-3))))
        fs = max(1, int(1 / s / 2))
        a_low, b_low = _guided_coeffs(L, gain_small, r, float(cfg.get("upsample_eps", 0.02)), fs, L_mu, L_sd)
    detail = float(cfg.get("detail", 1.0))
    sat_keep = float(cfg.get("saturation_preserve", 0.9))
    knee, cap = float(cfg.get("highlight_knee", 0.88)), float(cfg.get("highlight_cap", 0.975))
    use_clip = clipped is not None and float(clipped.max()) > 0.5
    csig = max(1.0, 1.5 * W / 2000.0)
    cpad = int(np.ceil(4 * csig)) + 2
    out = radiance if inplace else np.empty_like(radiance, dtype=np.float32)
    for r0, r1 in row_strips(H, W):
        Ls = L[r0:r1]
        if guided:
            g = resize_rows(a_low, W, H, r0, r1) * ((Ls - L_mu) / L_sd) + resize_rows(b_low, W, H, r0, r1)
        else:
            g = resize_rows(gain_small, W, H, r0, r1)
        if abs(detail - 1.0) > 1e-3:
            g += (detail - 1.0) * np.clip(Ls - resize_rows(B, W, H, r0, r1), -2, 2)
        Yt = srgb_to_linear(curve(Ls + g))  # display luminance (linear)
        del g
        rad_s = radiance[r0:r1]
        # chroma of pixels at the noise floor fades to neutral (no coloured speckle in deep shadows)
        ratio = np.clip((rad_s + floor) / (luminance(rad_s)[..., None] + floor), 0, 8)
        rgb = Yt[..., None] * np.power(ratio, sat_keep)
        del ratio
        rgb *= (Yt / (luminance(rgb) + EPS))[..., None]
        np.clip(rgb, 0, 1.5, out=rgb)
        rgb = gamut_rolloff(rgb, 0.9, 1.0)  # out-of-range channels into [0,1] without hue shifts
        o = finishing(linear_to_srgb(rgb), cfg)
        del rgb
        # soft highlight roll-off as the very last colour step: no channel hits 255 unless the
        # pixel carries no information (clipped in every frame, handled below)
        o = linear_to_srgb(gamut_rolloff(srgb_to_linear(o), knee, cap))
        if use_clip:
            # areas clipped even in the darkest frame carry no information: clean white with a
            # soft edge instead of jagged, colour-fringed plateaus (blur padded across strips)
            a0, a1 = max(0, r0 - cpad), min(H, r1 + cpad)
            c = accel.cv(cv2.GaussianBlur, np.ascontiguousarray(clipped[a0:a1], np.float32), (0, 0),
                         csig)[r0 - a0:r1 - a0]
            c = np.clip((c - 0.25) / 0.5, 0, 1)
            c = (c * c * (3 - 2 * c))[..., None]
            o = o * (1 - c) + c
        out[r0:r1] = o
    if debug is not None:
        debug.update({"noise_floor": floor, "black_out": black_eff, "key_log2": key0, **{f"anchor_{k}": v for k, v in curve.anchors.items()},
                      **{f"pull_{k}_ev": v for k, v in pull_info.items()}})
    return out


def _guided_coeffs(L, gain_small, r, eps, fs, mu, sd):
    """Guided-filter coefficients (a, b) for upsampling the gain with the full-res log luminance
    as guide; computed at 1/fs resolution (fast guided filter, He & Sun 2015)."""
    H, W = L.shape
    w, h = max(1, W // fs), max(1, H // fs)
    gs = L if fs == 1 else cv2.resize(L, (w, h), interpolation=cv2.INTER_AREA)
    gs = (gs - mu) / sd
    sh, sw = gain_small.shape
    interp = cv2.INTER_AREA if (sw > w) else cv2.INTER_LINEAR
    ps = cv2.resize(gain_small, (w, h), interpolation=interp)
    rs = max(1, r // fs)
    mean_i = box(gs, rs)
    mean_p = box(ps, rs)
    var_i = box(gs * gs, rs) - mean_i * mean_i
    a = (box(gs * ps, rs) - mean_i * mean_p) / (var_i + eps)
    b = mean_p - a * mean_i
    return box(a, rs), box(b, rs)


def gamut_rolloff(rgb: np.ndarray, knee: float = 0.88, cap: float = 0.975) -> np.ndarray:
    """Soft highlight roll-off of the largest channel (display-linear), keeping luminance:
    saturated highlights (warm lamp glow, sunlit wood) desaturate gradually instead of
    clipping one channel at 255.  Only pixels above the knee are touched."""
    out = np.clip(rgb, 0, None).astype(np.float32, copy=False)
    m = chmax(out)
    idx = np.nonzero(m > knee)
    if len(idx[0]) == 0:
        return np.minimum(out, 1.0)
    px = out[idx]
    mm = m[idx][:, None]
    y = (px @ LUMA)[:, None]
    head = cap - knee
    m2 = knee + head * np.tanh((mm - knee) / head)
    k = np.clip((m2 - y) / np.maximum(mm - y, EPS), 0, 1)
    out[idx] = np.clip(y + (px - y) * k, 0, 1)
    return np.minimum(out, 1.0)


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
        cmag = (chmax(out) - chmin(out))[..., None]  # cheap chroma magnitude
        boost = sat * (1.0 + vib * np.exp(-cmag / 0.1))
        out = np.clip(y + chroma * boost, 0, 1)
    return out.astype(np.float32)

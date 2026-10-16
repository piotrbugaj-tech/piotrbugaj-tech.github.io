"""Noise reduction on the display-referred image.

The merged radiance is already much cleaner than a single frame, so this stage
is adaptive: the noise level sigma is measured (robust MAD of a high-pass on flat
areas) and the filters scale with it.
  * luminance: self-guided filter with eps proportional to sigma^2 (removes
    variations below the noise amplitude, keeps edges), two scales;
  * chrominance: guided by luminance at half resolution (chroma noise is
    blotchy / low-frequency), then upsampled.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from . import accel
from .imgutil import LUMA, guided_filter

log = logging.getLogger(__name__)


def estimate_sigma(y: np.ndarray) -> float:
    """Noise standard deviation (Immerkaer 1996: mean |second difference| over the image),
    excluding the strongest edges so texture/structure does not inflate the estimate."""
    h, w = y.shape
    step = max(1, int(np.sqrt(h * w / 4e6)))  # subsample very large images
    ys = (y[::step, ::step] if step > 1 else y).astype(np.float32)
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    conv = np.abs(cv2.filter2D(ys, -1, k, borderType=cv2.BORDER_REFLECT))[1:-1, 1:-1]
    gx = cv2.Sobel(ys, cv2.CV_32F, 1, 0, ksize=3)[1:-1, 1:-1]
    gy = cv2.Sobel(ys, cv2.CV_32F, 0, 1, ksize=3)[1:-1, 1:-1]
    g = np.abs(gx) + np.abs(gy)
    keep = g < np.percentile(g, 85)
    return float(np.sqrt(np.pi / 2) * conv[keep].mean() / 6.0)


def noise_level_function(y: np.ndarray, bins: int = 16):
    """Noise sigma as a function of brightness (display values after tone mapping: lifted
    shadows are much noisier than the global estimate).  Immerkaer response on non-edge pixels,
    averaged per brightness quantile bin; returns a vectorised lookup y -> sigma."""
    h, w = y.shape
    step = max(1, int(np.sqrt(h * w / 4e6)))
    ys = (y[::step, ::step] if step > 1 else y).astype(np.float32)
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    resp = np.abs(cv2.filter2D(ys, -1, k, borderType=cv2.BORDER_REFLECT))[1:-1, 1:-1]
    g = (np.abs(cv2.Sobel(ys, cv2.CV_32F, 1, 0, ksize=3)) + np.abs(cv2.Sobel(ys, cv2.CV_32F, 0, 1, ksize=3)))[1:-1, 1:-1]
    yb = cv2.GaussianBlur(ys, (0, 0), 2.0)[1:-1, 1:-1]
    edges = np.quantile(yb, np.linspace(0, 1, bins + 1))
    xs, sig = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (yb >= lo) & (yb <= hi)
        if sel.sum() < 500:
            continue
        flat = sel & (g < np.percentile(g[sel], 85))
        if flat.sum() < 100:  # (nearly) constant bin, e.g. clipped white
            continue
        xs.append(float(np.median(yb[sel])))
        sig.append(float(np.sqrt(np.pi / 2) * resp[flat].mean() / 6.0))
    if not xs:
        s0 = estimate_sigma(y)
        return lambda v: np.full_like(v, s0, dtype=np.float32)
    xs, sig = np.array(xs), np.maximum.accumulate(np.array(sig)[::-1])[::-1]  # never lower in darker bins
    return lambda v: np.interp(v, xs, sig).astype(np.float32)


def denoise(img: np.ndarray, cfg: dict, single: bool = False, raw_single: bool = False) -> np.ndarray:
    """``single``: one exposure (stronger filters); ``raw_single``: one undeveloped exposure (RAW,
    linear TIFF) whose lifted shadows switch the strong mode on earlier than a finished JPEG's."""
    dcfg = cfg.get("denoise", {})
    if not dcfg.get("enabled", True):
        return img
    boost = float(cfg.get("single_image", {}).get("denoise_boost", 1.6)) if single else 1.0
    s_l = float(dcfg.get("luma", 0.6)) * boost
    s_c = float(dcfg.get("chroma", 1.0)) * boost
    y = img @ LUMA
    sigma = estimate_sigma(y)
    if sigma < 0.002:
        log.info("denoise: sigma %.4f - image clean, skipped", sigma)
        return img
    # strong mode when the global noise OR the noise of the darker part of the image is high:
    # lifted shadows of a single frame can be 3x noisier than the global estimate suggests
    sig_dark = float(noise_level_function(y)(np.float32(np.percentile(y, 25))))
    dark_lim = float(dcfg.get("strong_dark_sigma_raw" if raw_single else "strong_dark_sigma", 0.02 if raw_single else 0.03))
    if sigma > float(dcfg.get("strong_sigma", 0.015)) or sig_dark > dark_lim:
        img = _strong(img, sigma, s_l, s_c, float(dcfg.get("nlm_strength", 1.1)), int(dcfg.get("nlm_template", 5)),
                      int(dcfg.get("nlm_search", 15)))
        y = img @ LUMA
        sigma = estimate_sigma(y)
    # luminance: two scales of a self-guided filter
    eps = (2.0 * sigma * s_l) ** 2
    y1 = guided_filter(y, y, 2, eps)
    h, w = y.shape
    ys = cv2.resize(y1, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    ys2 = guided_filter(ys, ys, 3, eps * 0.5)
    y2 = y1 + cv2.resize(ys2 - ys, (w, h), interpolation=cv2.INTER_LINEAR) * min(1.0, s_l)
    a = min(1.0, s_l)
    y_out = y + a * (y2 - y)
    out = img + (y_out - y)[..., None]
    # chrominance at half resolution, guided by the denoised luminance
    if s_c > 0:
        c = out - y_out[..., None]
        cs = cv2.resize(c, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        g = cv2.resize(y_out, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        r = max(2, int(round(3 * min(2.0, s_c))))
        cd = guided_filter(g, cs, r, (3.0 * sigma) ** 2 + 1e-5)
        cd = cv2.resize(cd, (w, h), interpolation=cv2.INTER_LINEAR)
        b = min(1.0, s_c)
        out = y_out[..., None] + (1.0 - b) * c + b * cd
    out = _shadow_chroma(out, sigma)
    log.info("denoise: sigma %.4f, luma %.2f, chroma %.2f", sigma, s_l, s_c)
    return np.clip(out, 0, 1).astype(np.float32)


def _strong(img: np.ndarray, sigma: float, s_l: float, s_c: float, k_h: float = 1.1, tw: int = 5,
            sw: int = 15) -> np.ndarray:
    """Very noisy input (single under-exposed frame): non-local means at half resolution on a
    variance-stabilised image, plus the original high-frequency detail gated by the noise level.

    After tone mapping the noise depends strongly on brightness (lifted shadows are several
    times noisier than the global estimate), so a single NLM strength either leaves the
    shadows speckled or smears the mid-tones.  The noise level function sigma(y) measured on
    the half-resolution image gives the transform F(v) = integral dv / sigma(v), under which the
    noise is uniform; NLM runs on F(img) and the result is mapped back."""
    h, w = img.shape[:2]
    small = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    nlf = noise_level_function(small @ LUMA)
    grid = np.linspace(0.0, 1.0, 1025, dtype=np.float32)
    sg = np.maximum(nlf(grid), max(sigma * 0.25, 1e-3))
    F = np.concatenate([[0.0], np.cumsum(0.5 * (1 / sg[1:] + 1 / sg[:-1]) * np.diff(grid))]).astype(np.float32)
    scale = 255.0 / float(F[-1])               # 8-bit codes: noise sigma ~ scale after the transform
    fwd = np.interp(np.clip(small, 0, 1), grid, F) * scale
    s8 = np.clip(fwd + 0.5, 0, 255).astype(np.uint8)
    hl = float(np.clip(scale * k_h * s_l, 3, 30))
    hc = float(np.clip(hl * 1.3 * max(s_c, 1.0), 4, 35))
    d8 = accel.cv(cv2.fastNlMeansDenoisingColored, cv2.cvtColor(s8, cv2.COLOR_RGB2BGR), None, hl, hc, tw, sw)
    dt = cv2.cvtColor(d8, cv2.COLOR_BGR2RGB).astype(np.float32) / scale
    dn = np.interp(dt, F, grid).astype(np.float32)  # back to display values
    up = cv2.resize(dn, (w, h), interpolation=cv2.INTER_CUBIC)
    base = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    detail = (img - base) @ LUMA
    # keep only detail clearly above the noise (edges), soft-thresholded with the noise level
    # at each pixel's brightness (x2: the full-resolution noise is twice the half-res one)
    t = 2.5 * np.maximum(2.0 * nlf(up @ LUMA), sigma)
    detail = np.sign(detail) * np.maximum(np.abs(detail) - t, 0)
    log.info("denoise: strong mode (sigma %.3f, shadows %.3f, stabilised NLM h=%.1f/%.1f)", sigma,
             float(nlf(np.float32(0.15))), hl, hc)
    return np.clip(up + detail[..., None], 0, 1).astype(np.float32)


def _shadow_chroma(img: np.ndarray, sigma: float) -> np.ndarray:
    """Desaturate the deepest shadows where chroma is mostly noise (and the magenta bias of
    clipped sensor noise); strength follows the measured noise."""
    if sigma < 0.004:
        return img
    y = (img @ LUMA)[..., None]
    lim = float(np.clip(sigma * 12, 0.05, 0.3))
    k = np.clip(y / lim, 0, 1) ** 0.7
    return y + (img - y) * k

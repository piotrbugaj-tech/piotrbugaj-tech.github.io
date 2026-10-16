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

from .imgutil import LUMA, guided_filter

log = logging.getLogger(__name__)


def estimate_sigma(y: np.ndarray) -> float:
    """Noise standard deviation of a single-channel image (robust, flat regions only)."""
    h, w = y.shape
    step = max(1, int(np.sqrt(h * w / 4e6)))  # subsample very large images
    ys = y[::step, ::step] if step > 1 else y
    # second-difference high-pass (insensitive to smooth gradients); var(hp) = 6.25 * sigma^2 for white noise
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32) / 4.0
    hp = cv2.filter2D(ys, -1, k, borderType=cv2.BORDER_REFLECT)
    gx = cv2.Sobel(ys, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(ys, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt(gx * gx + gy * gy)
    flat = grad < np.percentile(grad, 40)
    if flat.sum() < 1000:
        flat = np.ones_like(grad, bool)
    sig = 1.4826 * float(np.median(np.abs(hp[flat]))) / 1.5
    return sig


def denoise(img: np.ndarray, cfg: dict, single: bool = False) -> np.ndarray:
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
    log.info("denoise: sigma %.4f, luma %.2f, chroma %.2f", sigma, s_l, s_c)
    return np.clip(out, 0, 1).astype(np.float32)

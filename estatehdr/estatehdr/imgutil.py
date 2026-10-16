"""Shared image helpers: colour transforms, luminance, guided filter, resizing."""
from __future__ import annotations

import cv2
import numpy as np

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def luminance(img: np.ndarray) -> np.ndarray:
    return (img @ LUMA).astype(np.float32)


def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0).astype(np.float32)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0).astype(np.float32)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055).astype(np.float32)


def resize_max(img: np.ndarray, max_side: int, interp=cv2.INTER_AREA) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    s = min(1.0, max_side / max(h, w))
    if s >= 1.0:
        return img, 1.0
    out = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=interp)
    return out, s


def resize_to(img: np.ndarray, shape_hw, interp=cv2.INTER_LINEAR) -> np.ndarray:
    h, w = shape_hw[:2]
    if img.shape[0] == h and img.shape[1] == w:
        return img
    return cv2.resize(img, (w, h), interpolation=interp)


def box(img: np.ndarray, r: int) -> np.ndarray:
    k = 2 * r + 1
    return cv2.boxFilter(img, -1, (k, k), borderType=cv2.BORDER_REFLECT)


def guided_filter(guide: np.ndarray, src: np.ndarray, r: int, eps: float) -> np.ndarray:
    """He et al. guided filter with a single-channel guide (float32)."""
    guide = guide.astype(np.float32)
    src = src.astype(np.float32)
    mean_i = box(guide, r)
    mean_p = box(src, r)
    if src.ndim == 3:
        gi = guide[..., None]
        mi = mean_i[..., None]
        corr_ip = box(gi * src, r)
        var_i = box(guide * guide, r) - mean_i * mean_i
        a = (corr_ip - mi * mean_p) / (var_i[..., None] + eps)
        b = mean_p - a * mi
        return box(a, r) * gi + box(b, r)
    corr_ip = box(guide * src, r)
    var_i = box(guide * guide, r) - mean_i * mean_i
    a = (corr_ip - mean_i * mean_p) / (var_i + eps)
    b = mean_p - a * mean_i
    return box(a, r) * guide + box(b, r)


def fast_guided_filter(guide: np.ndarray, src: np.ndarray, r: int, eps: float, s: int = 4) -> np.ndarray:
    """Guided filter computed at 1/s resolution, coefficients upsampled (He & Sun 2015)."""
    if s <= 1:
        return guided_filter(guide, src, r, eps)
    h, w = guide.shape[:2]
    gs = cv2.resize(guide, (max(1, w // s), max(1, h // s)), interpolation=cv2.INTER_AREA)
    ps = cv2.resize(src, (max(1, w // s), max(1, h // s)), interpolation=cv2.INTER_AREA)
    rs = max(1, r // s)
    mean_i = box(gs, rs)
    mean_p = box(ps, rs)
    if ps.ndim == 3:
        gi = gs[..., None]
        mi = mean_i[..., None]
        var_i = box(gs * gs, rs) - mean_i * mean_i
        a = (box(gi * ps, rs) - mi * mean_p) / (var_i[..., None] + eps)
        b = mean_p - a * mi
        a = cv2.resize(box(a, rs), (w, h), interpolation=cv2.INTER_LINEAR)
        b = cv2.resize(box(b, rs), (w, h), interpolation=cv2.INTER_LINEAR)
        return a * guide[..., None] + b
    var_i = box(gs * gs, rs) - mean_i * mean_i
    a = (box(gs * ps, rs) - mean_i * mean_p) / (var_i + eps)
    b = mean_p - a * mean_i
    a = cv2.resize(box(a, rs), (w, h), interpolation=cv2.INTER_LINEAR)
    b = cv2.resize(box(b, rs), (w, h), interpolation=cv2.INTER_LINEAR)
    return a * guide + b


def smooth_mask(mask: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return mask.astype(np.float32)
    return cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sigma)


def rgb_to_lab(rgb_lin: np.ndarray) -> np.ndarray:
    """Linear sRGB (D65) -> CIE L*a*b*."""
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]], np.float32)
    xyz = np.clip(rgb_lin, 0, None) @ m.T
    xyz /= np.array([0.95047, 1.0, 1.08883], np.float32)
    d = 6 / 29
    f = np.where(xyz > d ** 3, np.cbrt(xyz), xyz / (3 * d * d) + 4 / 29)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], -1).astype(np.float32)


def delta_e2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000 colour difference (vectorised)."""
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]
    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    Cm = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cm ** 7 / (Cm ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp = L2 - L1
    dCp = C2p - C1p
    dhp = h2p - h1p
    dhp = np.where(dhp > 180, dhp - 360, dhp)
    dhp = np.where(dhp < -180, dhp + 360, dhp)
    dhp = np.where(C1p * C2p == 0, 0, dhp)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp) / 2)
    Lpm = (L1 + L2) / 2
    Cpm = (C1p + C2p) / 2
    hsum = h1p + h2p
    hpm = np.where(np.abs(h1p - h2p) > 180, (hsum + 360) / 2, hsum / 2)
    hpm = np.where(C1p * C2p == 0, hsum, hpm)
    T = (1 - 0.17 * np.cos(np.radians(hpm - 30)) + 0.24 * np.cos(np.radians(2 * hpm))
         + 0.32 * np.cos(np.radians(3 * hpm + 6)) - 0.20 * np.cos(np.radians(4 * hpm - 63)))
    dtheta = 30 * np.exp(-(((hpm - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cpm ** 7 / (Cpm ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lpm - 50) ** 2 / np.sqrt(20 + (Lpm - 50) ** 2)
    Sc = 1 + 0.045 * Cpm
    Sh = 1 + 0.015 * Cpm * T
    Rt = -np.sin(np.radians(2 * dtheta)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh)).astype(np.float32)

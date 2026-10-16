"""Image quality metrics used by tools/evaluate.py, the tests and the calibration loop.

All functions take display-referred sRGB images as float32 in [0,1] (HxWx3).
"""
from __future__ import annotations


import cv2
import numpy as np

from ..imgutil import chmax, chmin, LUMA, delta_e2000, resize_max, rgb_to_lab, srgb_to_linear


def to_float(img8: np.ndarray) -> np.ndarray:
    return img8.astype(np.float32) / 255.0


def histogram_stats(img: np.ndarray, bins: int = 32) -> dict:
    y = img @ LUMA
    y8 = np.round(y * 255)
    any8 = np.round(img * 255)
    hist, _ = np.histogram(y, bins=bins, range=(0, 1))
    return {
        "clipped_pct": float(100 * (chmax(any8) >= 254).mean()),
        "clipped_all_channels_pct": float(100 * (chmin(any8) >= 254).mean()),
        "crushed_pct": float(100 * (y8 <= 1).mean()),
        "mean_luma": float(y.mean()),
        "p1": float(np.percentile(y, 1)), "p50": float(np.percentile(y, 50)), "p99": float(np.percentile(y, 99)),
        "histogram": (hist / hist.sum()).round(4).tolist(),
    }


_LSD = None


def line_segments(img: np.ndarray, max_side: int = 1600, min_len_frac: float = 0.05):
    global _LSD
    if _LSD is None:
        _LSD = cv2.createLineSegmentDetector()
    small, s = resize_max(img, max_side)
    g = np.clip((small @ LUMA) * 255, 0, 255).astype(np.uint8)
    segs = _LSD.detect(g)[0]
    if segs is None:
        return np.zeros((0, 4), np.float32), small.shape[:2]
    segs = segs.reshape(-1, 4)
    L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    return segs[L >= min_len_frac * small.shape[0]], small.shape[:2]


def verticality(img: np.ndarray, max_tilt_deg: float = 15.0) -> dict:
    """Deviation from vertical of long near-vertical lines (degrees, length-weighted)."""
    segs, _ = line_segments(img)
    if len(segs) == 0:
        return {"lines": 0, "median_abs_deg": None, "mean_abs_deg": None, "p90_abs_deg": None}
    dx = segs[:, 2] - segs[:, 0]
    dy = segs[:, 3] - segs[:, 1]
    ang = np.degrees(np.arctan2(dx, dy))
    ang = (ang + 90) % 180 - 90  # signed deviation from vertical in (-90, 90]
    L = np.hypot(dx, dy)
    sel = np.abs(ang) < max_tilt_deg
    if sel.sum() == 0:
        return {"lines": 0, "median_abs_deg": None, "mean_abs_deg": None, "p90_abs_deg": None}
    a, w = np.abs(ang[sel]), L[sel]
    o = np.argsort(a)
    cw = np.cumsum(w[o]) / w.sum()
    med = float(a[o][np.searchsorted(cw, 0.5)])
    p90 = float(a[o][min(len(a) - 1, np.searchsorted(cw, 0.9))])
    return {"lines": int(sel.sum()), "median_abs_deg": med, "mean_abs_deg": float((a * w).sum() / w.sum()),
            "p90_abs_deg": p90}


def straightness(img: np.ndarray) -> dict:
    """Total squared length of long segments (higher = straighter long lines)."""
    segs, shape = line_segments(img, min_len_frac=0.1)
    L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1]) / max(shape)
    return {"long_lines": int(len(segs)), "score": float((L ** 2).sum())}


def neutrality(img: np.ndarray, mask: np.ndarray | None = None) -> dict:
    """Colour cast of white/grey surfaces: CIEDE2000 between the surface and a neutral grey of
    the same L*.  Without a mask, bright smooth low-chroma pixels are used (likely walls)."""
    lab = rgb_to_lab(srgb_to_linear(img))
    if mask is None:
        y = img @ LUMA
        g = cv2.GaussianBlur(np.abs(cv2.Laplacian(y, cv2.CV_32F)), (0, 0), 2)
        c = np.hypot(lab[..., 1], lab[..., 2])
        mask = (y > np.percentile(y, 60)) & (y < 0.97) & (g < np.percentile(g, 50)) & (c < 20)
    if mask.sum() < 100:
        return {"pixels": int(mask.sum()), "delta_e_mean": None}
    sel = lab[mask]
    neutral = sel.copy()
    neutral[:, 1:] = 0
    de = delta_e2000(sel, neutral)
    return {"pixels": int(mask.sum()), "delta_e_mean": float(de.mean()), "delta_e_p90": float(np.percentile(de, 90)),
            "a_mean": float(sel[:, 1].mean()), "b_mean": float(sel[:, 2].mean()), "L_median": float(np.median(sel[:, 0]))}


def window_metrics(img: np.ndarray, mask: np.ndarray, reference: np.ndarray | None = None) -> dict:
    """Brightness / clipping / detail inside window areas (mask True = glass)."""
    if mask is None or mask.sum() < 50:
        return {"pixels": 0}
    y = img @ LUMA
    lab = rgb_to_lab(srgb_to_linear(img))
    gx = cv2.Sobel(y, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(y, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt(gx * gx + gy * gy)
    inner = cv2.erode(mask.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    if inner.sum() < 20:
        inner = mask
    clipped = np.round(img * 255).max(-1) >= 254
    keep = mask & ~clipped
    out = {"pixels": int(mask.sum()), "L_mean": float(lab[..., 0][mask].mean()),
           # view brightness without the clipped pixels (they carry no information)
           "L_mean_unclipped": float(lab[..., 0][keep].mean()) if keep.sum() >= 20 else None,
           "clipped_pct": float(100 * clipped[mask].mean()),
           "detail": float(grad[inner].mean())}
    if reference is not None:
        yr = reference @ LUMA
        gxr = cv2.Sobel(yr, cv2.CV_32F, 1, 0, ksize=3)
        gyr = cv2.Sobel(yr, cv2.CV_32F, 0, 1, ksize=3)
        gr = np.sqrt(gxr * gxr + gyr * gyr)
        out["detail_ratio_vs_ref"] = float(grad[inner].mean() / max(gr[inner].mean(), 1e-6))
    return out


def ssim(a: np.ndarray, b: np.ndarray, mask: np.ndarray | None = None) -> float:
    """SSIM on luminance (Wang et al. 2004, Gaussian window 11/1.5)."""
    x = (a @ LUMA).astype(np.float64)
    y = (b @ LUMA).astype(np.float64)
    C1, C2 = (0.01) ** 2, (0.03) ** 2
    mu_x = cv2.GaussianBlur(x, (11, 11), 1.5)
    mu_y = cv2.GaussianBlur(y, (11, 11), 1.5)
    sxx = cv2.GaussianBlur(x * x, (11, 11), 1.5) - mu_x ** 2
    syy = cv2.GaussianBlur(y * y, (11, 11), 1.5) - mu_y ** 2
    sxy = cv2.GaussianBlur(x * y, (11, 11), 1.5) - mu_x * mu_y
    m = ((2 * mu_x * mu_y + C1) * (2 * sxy + C2)) / ((mu_x ** 2 + mu_y ** 2 + C1) * (sxx + syy + C2))
    if mask is not None:
        return float(m[mask].mean())
    return float(m.mean())


def _ssim_terms(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Luminance term and contrast-structure term maps of SSIM (float64 luminance inputs)."""
    C1, C2 = (0.01) ** 2, (0.03) ** 2
    mu_x = cv2.GaussianBlur(x, (11, 11), 1.5)
    mu_y = cv2.GaussianBlur(y, (11, 11), 1.5)
    sxx = cv2.GaussianBlur(x * x, (11, 11), 1.5) - mu_x ** 2
    syy = cv2.GaussianBlur(y * y, (11, 11), 1.5) - mu_y ** 2
    sxy = cv2.GaussianBlur(x * y, (11, 11), 1.5) - mu_x * mu_y
    return (2 * mu_x * mu_y + C1) / (mu_x ** 2 + mu_y ** 2 + C1), (2 * sxy + C2) / (sxx + syy + C2)


MS_WEIGHTS = (0.0448, 0.2856, 0.3001, 0.2363, 0.1333)


def ms_ssim(a: np.ndarray, b: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Multi-scale SSIM (Wang, Simoncelli, Bovik 2003) on luminance; scales that would be smaller
    than the window are dropped and the remaining weights renormalised."""
    x = (a @ LUMA).astype(np.float64)
    y = (b @ LUMA).astype(np.float64)
    m = np.ones(x.shape, bool) if mask is None else mask.astype(bool)
    n = max(1, min(len(MS_WEIGHTS), int(np.log2(min(x.shape) / 11.0)) + 1))
    w = np.array(MS_WEIGHTS[:n]) / sum(MS_WEIGHTS[:n])
    vals = []
    for i in range(n):
        lum, cs = _ssim_terms(x, y)
        sel = m if m.any() else np.ones_like(m)
        vals.append(float(np.mean((lum * cs)[sel])) if i == n - 1 else float(np.mean(cs[sel])))
        if i < n - 1:
            x = cv2.resize(x, (x.shape[1] // 2, x.shape[0] // 2), interpolation=cv2.INTER_AREA)
            y = cv2.resize(y, (y.shape[1] // 2, y.shape[0] // 2), interpolation=cv2.INTER_AREA)
            m = cv2.resize(m.astype(np.uint8), (x.shape[1], x.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    return float(np.prod(np.maximum(vals, 1e-6) ** w))


def gradient_ssim(a: np.ndarray, b: np.ndarray, mask: np.ndarray | None = None) -> float:
    """SSIM of the gradient-magnitude images: structure/edges only, insensitive to tone and colour
    (how well edges, window frames and textures match)."""
    def gm(img):
        y = (img @ LUMA).astype(np.float64)
        return np.hypot(cv2.Sobel(y, cv2.CV_64F, 1, 0, ksize=3), cv2.Sobel(y, cv2.CV_64F, 0, 1, ksize=3)) / 4.0
    lum, cs = _ssim_terms(gm(a), gm(b))
    s = lum * cs
    return float(s[mask].mean() if mask is not None else s.mean())


def delta_e_images(a: np.ndarray, b: np.ndarray, mask: np.ndarray | None = None) -> dict:
    la = rgb_to_lab(srgb_to_linear(a))
    lb = rgb_to_lab(srgb_to_linear(b))
    de = delta_e2000(la, lb)
    if mask is not None:
        de = de[mask]
    return {"mean": float(de.mean()), "median": float(np.median(de)), "p90": float(np.percentile(de, 90))}


_LPIPS = None


def lpips_distance(a: np.ndarray, b: np.ndarray) -> float | None:
    """LPIPS (AlexNet) if torch + lpips + weights are available locally; otherwise None."""
    global _LPIPS
    try:
        import torch
        import lpips
    except Exception:
        return None
    try:
        if _LPIPS is None:
            _LPIPS = lpips.LPIPS(net="alex", verbose=False)
        ta = torch.from_numpy(a.transpose(2, 0, 1)[None] * 2 - 1).float()
        tb = torch.from_numpy(b.transpose(2, 0, 1)[None] * 2 - 1).float()
        with torch.no_grad():
            return float(_LPIPS(ta, tb).item())
    except Exception:
        return None


def register(src: np.ndarray, ref: np.ndarray, max_side: int = 1600) -> tuple[np.ndarray, np.ndarray]:
    """Warp src onto ref (homography from SIFT matches on luminance) for pairwise metrics.
    Returns (warped_src, valid_mask) in ref geometry."""
    a, sa = resize_max(src, max_side)
    b, sb = resize_max(ref, max_side)
    ga = np.clip((a @ LUMA) * 255, 0, 255).astype(np.uint8)
    gb = np.clip((b @ LUMA) * 255, 0, 255).astype(np.uint8)
    ga = cv2.createCLAHE(2.0, (8, 8)).apply(ga)
    gb = cv2.createCLAHE(2.0, (8, 8)).apply(gb)
    sift = cv2.SIFT_create(5000)
    ka, da = sift.detectAndCompute(ga, None)
    kb, db = sift.detectAndCompute(gb, None)
    h, w = ref.shape[:2]
    if da is None or db is None or len(ka) < 8 or len(kb) < 8:
        return cv2.resize(src, (w, h)), np.ones((h, w), bool)
    m = cv2.BFMatcher(cv2.NORM_L2).knnMatch(da, db, k=2)
    good = [x for x, y in (p for p in m if len(p) == 2) if x.distance < 0.75 * y.distance]
    if len(good) < 8:
        return cv2.resize(src, (w, h)), np.ones((h, w), bool)
    pa = np.float32([ka[g.queryIdx].pt for g in good]) / sa
    pb = np.float32([kb[g.trainIdx].pt for g in good]) / sb
    Hm, _ = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)
    if Hm is None:
        return cv2.resize(src, (w, h)), np.ones((h, w), bool)
    warped = cv2.warpPerspective(src, Hm, (w, h), flags=cv2.INTER_LINEAR)
    valid = cv2.warpPerspective(np.ones(src.shape[:2], np.uint8), Hm, (w, h), flags=cv2.INTER_NEAREST) > 0
    valid = cv2.erode(valid.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    return warped, valid


def halo_index(img: np.ndarray, mask: np.ndarray, band: int = 30) -> dict:
    """Luminance overshoot around bright regions (window frames): compares the band just
    outside the mask edge with a band further out.  A positive value means a bright halo."""
    if mask is None or mask.sum() < 100:
        return {"halo": None}
    m = mask.astype(np.uint8)
    d1 = cv2.dilate(m, np.ones((5, 5), np.uint8))
    near = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * band + 1, 2 * band + 1))).astype(bool) & ~d1.astype(bool)
    far = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (4 * band + 1, 4 * band + 1))).astype(bool) & ~near & ~d1.astype(bool)
    if near.sum() < 50 or far.sum() < 50:
        return {"halo": None}
    lab = rgb_to_lab(srgb_to_linear(img))[..., 0]
    return {"halo_dL": float(np.median(lab[near]) - np.median(lab[far]))}


def noise_sigma(img: np.ndarray) -> float:
    from ..denoise import estimate_sigma
    return float(estimate_sigma(img @ LUMA))


def sharpness(img: np.ndarray) -> float:
    """Mean gradient magnitude on the strongest 5% edges (higher = crisper)."""
    y = img @ LUMA
    gx = cv2.Sobel(y, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(y, cv2.CV_32F, 0, 1, ksize=3)
    g = np.sqrt(gx * gx + gy * gy)
    t = np.percentile(g, 95)
    return float(g[g >= t].mean())

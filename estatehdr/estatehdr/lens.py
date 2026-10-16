"""Lens corrections estimated from the image itself (no profile database).

* Lateral chromatic aberration: R and B planes are radially scaled versions of
  G.  The scale factors are found by maximising the correlation of gradient
  magnitudes with G over a search range, refined with a parabola.
* Vignetting: a radial fall-off V(r) = 1 + a r^2 + b r^4 is fitted to the median
  radial derivative of log luminance on smooth surfaces (on average, real scene
  content has no preferred radial gradient; vignetting does).  Only darkening
  corrections are accepted and they are bounded.
Both run on the linear radiance before white balance and tone mapping.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from .imgutil import chmax, luminance, resize_max

log = logging.getLogger(__name__)


def _radial_scale(ch: np.ndarray, s: float) -> np.ndarray:
    h, w = ch.shape
    M = np.array([[s, 0, (1 - s) * (w - 1) / 2], [0, s, (1 - s) * (h - 1) / 2]], np.float32)
    # warpAffine with inverse map: out(x) = ch(M x)  -> pixel at radius r samples radius s*r
    return cv2.warpAffine(ch, M, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)


def estimate_ca(img: np.ndarray, max_side: int = 2400, rng: float = 0.004, steps: int = 21) -> tuple[float, float, dict]:
    """Returns radial scale factors (sR, sB) to apply to the R and B planes."""
    small, _ = resize_max(img, max_side)
    g = np.log2(small[..., 1] + 1e-4)

    def grad(x):
        gx = cv2.Sobel(x, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(x, cv2.CV_32F, 0, 1, ksize=3)
        return np.sqrt(gx * gx + gy * gy)
    gg = grad(g)
    h, w = gg.shape
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot(xx - w / 2, yy - h / 2) / np.hypot(w / 2, h / 2)
    wmask = (r > 0.35) & (gg > np.percentile(gg, 80))  # CA is visible at strong edges far from centre
    if wmask.sum() < 500:
        return 1.0, 1.0, {"reason": "few edges"}
    out = []
    info = {}
    for c, name in ((0, "R"), (2, "B")):
        x = np.log2(small[..., c] + 1e-4)
        scales = np.linspace(1 - rng, 1 + rng, steps)
        scores = []
        for s in scales:
            gs = grad(_radial_scale(x, s))
            a, b = gg[wmask], gs[wmask]
            a = a - a.mean()
            b = b - b.mean()
            scores.append(float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum() + 1e-12)))
        scores = np.array(scores)
        i = int(np.argmax(scores))
        s_best = scales[i]
        if 0 < i < steps - 1:
            y0, y1, y2 = scores[i - 1], scores[i], scores[i + 1]
            den = y0 - 2 * y1 + y2
            if abs(den) > 1e-12:
                s_best = scales[i] + 0.5 * (y0 - y2) / den * (scales[1] - scales[0])
        gain = scores[i] - scores[steps // 2]
        info[name] = {"scale": float(s_best), "gain": float(gain)}
        out.append(float(s_best) if gain > 1e-4 else 1.0)
    return out[0], out[1], info


def _fit_profile(rc, med):
    A = np.stack([2 * rc, 4 * rc ** 3], 1)
    coef, res, *_ = np.linalg.lstsq(A, med, rcond=None)
    return float(coef[0]), float(coef[1])


def estimate_vignetting(img: np.ndarray, max_side: int = 800) -> tuple[float, float, dict]:
    """Radial fall-off from the median radial log-gradient on smooth surfaces, fitted
    separately in the four quadrants.  Interiors are naturally darker in the corners, so
    the estimate is accepted only when all quadrants agree (true vignetting is radially
    symmetric; room shading is not)."""
    small, _ = resize_max(img, max_side)
    y = luminance(small)
    ly = np.log(y + 1e-4)
    h, w = ly.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    R = np.hypot(cx, cy)
    dx, dy = (xx - cx) / R, (yy - cy) / R
    r = np.hypot(dx, dy) + 1e-6
    gx = cv2.Sobel(ly, cv2.CV_32F, 1, 0, ksize=3) / 8.0 * R
    gy = cv2.Sobel(ly, cv2.CV_32F, 0, 1, ksize=3) / 8.0 * R
    gr = (gx * dx + gy * dy) / r
    gmag = np.hypot(gx, gy)
    valid = (y > np.percentile(y, 5)) & (chmax(small) < 0.9 * small.max()) & (gmag < np.percentile(gmag, 50)) & (r > 0.15)
    bins = np.linspace(0.15, 1.0, 12)
    corners = []
    fits = []
    for qx in (-1, 1):
        for qy in (-1, 1):
            q = valid & (np.sign(dx) == qx) & (np.sign(dy) == qy)
            rc, med = [], []
            for a, b in zip(bins[:-1], bins[1:]):
                m = q & (r >= a) & (r < b)
                if m.sum() > 80:
                    rc.append((a + b) / 2)
                    med.append(float(np.median(gr[m])))
            if len(rc) < 5:
                return 0.0, 0.0, {"reason": "too few smooth pixels in a quadrant"}
            a_, b_ = _fit_profile(np.array(rc), np.array(med))
            fits.append((a_, b_))
            corners.append(1 + a_ + b_)
    corners = np.array(corners)
    a = float(np.median([f[0] for f in fits]))
    b = float(np.median([f[1] for f in fits]))
    v_corner = 1 + a + b
    info = {"a": a, "b": b, "corner": float(v_corner), "corner_spread": float(np.ptp(corners))}
    if np.ptp(corners) > 0.15:
        return 0.0, 0.0, {**info, "reason": "quadrants disagree (scene shading, not vignetting)"}
    if v_corner >= 0.97 or v_corner < 0.5:
        return 0.0, 0.0, {**info, "reason": "outside plausible range"}
    return a, b, info


def correct(rad: np.ndarray, cfg: dict) -> tuple[np.ndarray, dict]:
    lcfg = cfg.get("lens", {})
    info = {}
    if lcfg.get("ca", "auto") != "off":
        sR, sB, ci = estimate_ca(rad)
        info["ca"] = ci
        if abs(sR - 1) > 2e-5:
            rad[..., 0] = _radial_scale(rad[..., 0], sR)
        if abs(sB - 1) > 2e-5:
            rad[..., 2] = _radial_scale(rad[..., 2], sB)
        info["ca_scales"] = [sR, sB]
    vmode = lcfg.get("vignetting", "auto")
    if vmode != "off":
        if isinstance(vmode, (int, float)) and not isinstance(vmode, bool):
            # manual: corner fall-off fraction to undo, e.g. 0.25 = corners 25% darker
            a, b, vi = -float(vmode), 0.0, {"manual": float(vmode)}
        else:
            a, b, vi = estimate_vignetting(rad)
        info["vignetting"] = vi
        if a or b:
            h, w = rad.shape[:2]
            yy = ((np.arange(h, dtype=np.float32) - (h - 1) / 2) / np.hypot((w - 1) / 2, (h - 1) / 2)) ** 2
            xx = ((np.arange(w, dtype=np.float32) - (w - 1) / 2) / np.hypot((w - 1) / 2, (h - 1) / 2)) ** 2
            r2 = yy[:, None] + xx[None, :]
            V = 1 + a * r2 + b * r2 * r2
            rad /= np.maximum(V, 0.3)[..., None]
    log.info("lens: CA scales %s, vignetting %s", info.get("ca_scales"),
             {k: round(v, 3) for k, v in info.get("vignetting", {}).items() if isinstance(v, float)})
    return rad, info

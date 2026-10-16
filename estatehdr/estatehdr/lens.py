"""Lens corrections estimated from the image itself (no profile database).

* Lateral chromatic aberration: R and B planes are radially scaled versions of
  G.  The scale factors are found by maximising the correlation of gradient
  magnitudes with G over a search range, refined with a parabola.
* Vignetting: a radial fall-off V(r) = 1 - c r^2 (or a nearby r^2 / r^4 mix) is found
  from the symmetry of the radial log-luminance gradients (scene content has no
  preferred radial gradient sign; vignetting has).  Interiors often violate that assumption (light falls off
  from windows / lamps near the frame centre), so the estimate is applied only when
  the evidence looks like a lens (same in all sectors, r^2 shape, no tangential
  bias); only darkening corrections are accepted and they are bounded.
Both run on the linear radiance before white balance and tone mapping.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from .config import mode_of
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
        # equal pre-smoothing: otherwise the interpolation blur of every non-identity warp biases
        # the score towards s = 1 (and, at low resolution, the estimate off by ~2x)
        x = cv2.GaussianBlur(x, (0, 0), 1.0)
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


# --- vignetting ---------------------------------------------------------------------------------
# Model: V(r) = 1 - c q(r), q = (1 - beta) r^2 + beta r^4, r normalised by the half diagonal from the
# image centre, so c is the relative fall-off in the corner.  beta = 0 is the model of the manual
# setting and of the synthetic camera; other shapes are used only when they fit clearly better.
_VIG_RMIN = 0.25      # radial gradients near the centre carry no information about c
_VIG_SECTORS = 8      # angular sectors for the agreement test
_VIG_SHAPES = (0.0, -0.5, -0.25, 0.25, 0.5, 1.0)  # beta candidates (< 0: flatter edge, > 0: steeper edge)
_VIG_U_FULL = 0.10    # evidence uncertainty (fall-off units) up to which the estimate is applied in full ...
_VIG_U_MAX = 0.20     # ... and from which on nothing is applied (measured u: textured flat fields <= 0.13;
                      # 57 real interior / exterior photos >= 0.30; rendered synthetic rooms >= 0.82)
_VIG_MIN = 0.03       # smaller fall-off is not worth correcting
_VIG_SNR = 1.5        # the estimate must exceed this many uncertainties


def _wmedian(x: np.ndarray, w: np.ndarray) -> float:
    o = np.argsort(x)
    cw = np.cumsum(w[o])
    return float(x[o][min(int(np.searchsorted(cw, 0.5 * cw[-1])), len(x) - 1)])


def _harmonic_rms(theta: np.ndarray, v: np.ndarray, wt: np.ndarray, const: bool) -> float:
    """Weighted rms of the sector values after removing the first angular harmonic (a planar
    illumination gradient across the frame projects onto the radial / tangential direction as
    cos / sin of the sector angle) and, optionally, the mean; fitted degrees of freedom accounted for."""
    cols = [np.cos(theta), np.sin(theta)] + ([np.ones_like(theta)] if const else [])
    A = np.stack(cols, 1)
    sw = np.sqrt(wt / wt.mean())
    coef, *_ = np.linalg.lstsq(A * sw[:, None], v * sw, rcond=None)
    res = (v - A @ coef) * sw
    return float(np.sqrt((res ** 2).sum() / max(len(v) - A.shape[1], 1)))


def _vignetting_gradients(img: np.ndarray, max_side: int) -> dict | None:
    """Radial / tangential derivatives of log luminance (per unit of normalised radius) at the usable
    pixels of a <= max_side copy of the linear radiance."""
    small, _ = resize_max(img, max_side)
    if small.ndim != 3 or min(small.shape[:2]) < 32:
        return None
    y = luminance(small).astype(np.float32)
    pos = y > 0
    if pos.sum() < 1000:
        return None
    med = float(np.median(y[pos]))
    ly = cv2.GaussianBlur(np.log(np.maximum(y, 1e-3 * med)), (0, 0), 1.0)
    h, w = ly.shape
    cx, cy = (w - 1) / 2, (h - 1) / 2
    R = float(np.hypot(cx, cy))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx, dy = (xx - cx) / R, (yy - cy) / R
    r = np.hypot(dx, dy) + 1e-6
    gx = cv2.Sobel(ly, cv2.CV_32F, 1, 0, ksize=3) / 8.0 * R
    gy = cv2.Sobel(ly, cv2.CV_32F, 0, 1, ksize=3) / 8.0 * R
    gr = (gx * dx + gy * dy) / r
    gt = (gy * dx - gx * dy) / r
    # no evidence from clipped / very bright areas (windows, lamps) and their rims, or from noisy shadows
    mx = chmax(small)
    bad = (y < 0.03 * med) | (y > 12.0 * med) | (mx >= 0.98 * float(mx.max()))
    bad = cv2.dilate(bad.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    sel = ~bad & (r > _VIG_RMIN) & (r <= 1.0)
    gr, gt, r, ang = gr[sel], gt[sel], r[sel], np.arctan2(dy, dx)[sel]
    if len(gr) < 2000:
        return None
    # strong edges out; the cut is symmetric and far above any vignetting slope (no selection bias,
    # unlike a cut at a gradient-magnitude percentile, which pulls the estimate towards zero)
    s = float(np.median(np.abs(gt))) + 1e-3
    keep = (np.abs(gt) < 8 * s) & (np.abs(gr) < 8 * s)
    return {"gr": gr[keep], "gt": gt[keep], "r": r[keep], "ang": ang[keep]}


def _votes(gr: np.ndarray, r: np.ndarray, beta: float) -> tuple[np.ndarray, np.ndarray]:
    """Per-pixel fall-off c at which the corrected radial derivative g - d/dr log(1 - c q(r)) is zero,
    and the vote weight (~ its precision, q'(r)).  The corrected derivative grows with c, so the weighted
    median of the votes is the c that balances the corrected radial gradients around zero: the
    radial-gradient symmetry criterion of Zheng et al. (CVPR 2008) in its sign / L1 form."""
    q = (1 - beta) * r * r + beta * r ** 4
    dq = 2 * (1 - beta) * r + 4 * beta * r ** 3
    den = dq - gr * q
    c = np.where(den > 1e-3, -gr / np.maximum(den, 1e-3), -1e6)  # g >= q'/q: positive for every c
    return c.astype(np.float32), dq


def estimate_vignetting(img: np.ndarray, max_side: int = 800, max_falloff: float = 0.5) -> tuple[float, float, dict]:
    """Corner fall-off from the symmetry of radial log-gradients, with guards against scene shading.

    Interiors are very often darker towards the frame edges by themselves (light falls off away from
    windows / lamps near the centre; ceilings and near floors at the edges); a gradient statistic cannot
    tell this from lens vignetting.  The estimate is therefore applied only when the evidence looks like
    a lens: the same fall-off in all angular sectors (after removing a planar illumination gradient),
    the same value from the inner and the outer annulus (radial shape) and no comparable bias of the
    tangential derivatives (vignetting has none; their sector bias measures scene shading + noise).
    The worst of the three is the evidence uncertainty u; the applied fraction falls from 1
    (u <= _VIG_U_FULL) to 0 (u >= _VIG_U_MAX).  Returns (a, b, info) of V = 1 + a r^2 + b r^4 -
    zeros when nothing is applied."""
    G = _vignetting_gradients(img, max_side)
    if G is None:
        return 0.0, 0.0, {"applied": False, "reason": "too few usable pixels"}
    gr, gt, r, ang = G["gr"], G["gt"], G["r"], G["ang"]
    inner = r < 0.6
    if inner.sum() < 500 or (~inner).sum() < 500:
        return 0.0, 0.0, {"applied": False, "reason": "too few usable pixels in the frame corners"}
    # radial shape: the inner and the outer annulus must give the same fall-off; prefer r^2
    step = max(1, len(gr) // 150_000)  # the shape search runs on a subsample
    sub_in, sub_out = np.flatnonzero(inner)[::step], np.flatnonzero(~inner)[::step]
    shapes = []
    for beta in _VIG_SHAPES:
        cs, ws = _votes(gr[sub_in], r[sub_in], beta)
        c_in = _wmedian(cs, ws)
        cs, ws = _votes(gr[sub_out], r[sub_out], beta)
        c_out = _wmedian(cs, ws)
        shapes.append((abs(c_in - c_out), beta, c_in, c_out))
    dio, beta, c_in, c_out = shapes[0]
    best = min(shapes)
    if best[0] < dio - 0.02:
        dio, beta, c_in, c_out = best
    c, wv = _votes(gr, r, beta)
    est = float(np.clip(_wmedian(c, wv), -2.0, 2.0))  # votes saturate at -1e6 (brightening outwards)
    t = -gt / (2 * r)  # the tangential derivative through the same (r^2) transform: a null reference
    sect = ((ang + np.pi) / (2 * np.pi) * _VIG_SECTORS + 0.5).astype(int) % _VIG_SECTORS
    min_px = max(200, len(c) // (8 * _VIG_SECTORS))
    th, ck, tk, wk = [], [], [], []
    for k in range(_VIG_SECTORS):
        m = sect == k
        if m.sum() >= min_px:
            th.append(2 * np.pi * k / _VIG_SECTORS - np.pi)
            ck.append(float(np.clip(_wmedian(c[m], wv[m]), -2.0, 2.0)))
            tk.append(float(np.clip(_wmedian(t[m], r[m]), -2.0, 2.0)))
            wk.append(float((r[m] ** 2).sum()))  # precision of a sector (vote noise ~ 1 / r)
    info = {"estimate": round(est, 4), "shape_r4": beta, "inner": round(float(np.clip(c_in, -2, 2)), 4),
            "outer": round(float(np.clip(c_out, -2, 2)), 4),
            "sectors": [round(x, 3) for x in ck], "n_px": int(len(c))}
    if len(ck) < 6:
        return 0.0, 0.0, {**info, "applied": False, "reason": "too few usable pixels in the frame corners"}
    th, wk, ck, tk = np.array(th), np.array(wk), np.array(ck), np.array(tk)
    spread = _harmonic_rms(th, ck, wk, const=True)  # sector disagreement
    trms = _harmonic_rms(th, tk, wk, const=False)   # tangential bias = scene shading (+ noise) level
    u = max(spread, trms, dio)
    conf = float(np.clip((_VIG_U_MAX - u) / (_VIG_U_MAX - _VIG_U_FULL), 0.0, 1.0))
    info.update({"corner_spread": round(spread, 4), "tangential": round(trms, 4), "inner_outer": round(dio, 4),
                 "uncertainty": round(u, 4), "confidence": round(conf, 3)})
    if est < _VIG_MIN:
        return 0.0, 0.0, {**info, "applied": False, "reason": "no darkening towards the corners"}
    if conf <= 0.0:
        return 0.0, 0.0, {**info, "applied": False,
                          "reason": "scene shading dominates (sectors / radial shape / tangential bias)"}
    if est < _VIG_SNR * u:
        return 0.0, 0.0, {**info, "applied": False, "reason": "not significant against the scene shading"}
    fall = conf * min(est, max_falloff)
    if fall < _VIG_MIN:
        return 0.0, 0.0, {**info, "applied": False, "reason": "low confidence"}
    a, b = -fall * (1 - beta), -fall * beta
    info.update({"applied": True, "falloff": round(fall, 4), "corner": round(1.0 - fall, 4),
                 "capped": bool(est > max_falloff), "a": a, "b": b})
    return a, b, info


def correct(rad: np.ndarray, cfg: dict) -> tuple[np.ndarray, dict]:
    lcfg = cfg.get("lens", {})
    info = {}
    if mode_of(lcfg.get("ca", "auto")) != "off":
        sR, sB, ci = estimate_ca(rad)
        info["ca"] = ci
        if abs(sR - 1) > 2e-5:
            rad[..., 0] = _radial_scale(rad[..., 0], sR)
        if abs(sB - 1) > 2e-5:
            rad[..., 2] = _radial_scale(rad[..., 2], sB)
        info["ca_scales"] = [sR, sB]
    vmode = lcfg.get("vignetting", "auto")
    if mode_of(vmode) != "off":
        if isinstance(vmode, (int, float)) and not isinstance(vmode, bool):
            # manual: corner fall-off fraction to undo, e.g. 0.25 = corners 25% darker
            a, b, vi = -float(vmode), 0.0, {"manual": float(vmode)}
        else:
            a, b, vi = estimate_vignetting(rad, max_falloff=float(lcfg.get("vignetting_max", 0.5)))
        info["vignetting"] = vi
        if a or b:
            h, w = rad.shape[:2]
            yy = ((np.arange(h, dtype=np.float32) - (h - 1) / 2) / np.hypot((w - 1) / 2, (h - 1) / 2)) ** 2
            xx = ((np.arange(w, dtype=np.float32) - (w - 1) / 2) / np.hypot((w - 1) / 2, (h - 1) / 2)) ** 2
            r2 = yy[:, None] + xx[None, :]
            V = 1 + a * r2 + b * r2 * r2
            rad /= np.maximum(V, 0.3)[..., None]
    log.info("lens: CA scales %s, vignetting %s", info.get("ca_scales"),
             {k: round(v, 3) if isinstance(v, float) else v for k, v in info.get("vignetting", {}).items()
              if isinstance(v, (float, bool, str))})
    return rad, info

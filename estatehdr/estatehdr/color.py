"""White balance with mixed-light correction.

Global: illuminant estimated from bright, smooth, near-neutral interior surfaces
(walls/ceilings dominate real-estate interiors) by an iterative 'gray candidates'
search in log-chroma space (u = ln R/G, v = ln B/G).  The middle exposure is the
colour reference (radiance is expressed in its scale), as AutoHDR documents.

Local (mixed light): per-cell illuminant estimates, kept only when they are
close to the Planckian locus (tungsten <-> daylight); colourful surfaces such as
a sage-green or pink wall are far from the locus and therefore ignored.  The
sparse field is interpolated (normalised convolution), smoothed, limited in
magnitude and applied as a smooth gain field (luminance preserved).
Window regions (the exterior seen through glass) get their own, daylight-
oriented correction so the view does not turn blue when the room is warm.
"""
from __future__ import annotations

import logging
import math

import cv2
import numpy as np

from .imgutil import luminance

log = logging.getLogger(__name__)
EPS = 1e-6


def kelvin_rgb(k: float) -> np.ndarray:
    """Linear sRGB of a black body normalised to G=1 (6500K ~ neutral)."""
    t = k / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
        b = 255.0
    rgb = np.clip(np.array([r, g, b]) / 255.0, 1e-4, 1.0)
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    lin = lin / np.array([1.0, 0.9547, 0.9228])
    return lin / lin[1]


_LOCUS = None


def locus() -> np.ndarray:
    """Planckian locus in (u, v) log-chroma, 1800K..15000K."""
    global _LOCUS
    if _LOCUS is None:
        ks = np.geomspace(1800, 15000, 200)
        pts = []
        for k in ks:
            c = kelvin_rgb(k)
            pts.append((math.log(c[0] / c[1]), math.log(c[2] / c[1])))
        _LOCUS = np.array(pts, np.float64), ks
    return _LOCUS


def project_to_locus(uv: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Nearest locus point, its distance and its CCT for (N,2) uv points."""
    pts, ks = locus()
    d = ((uv[:, None, :] - pts[None]) ** 2).sum(-1)
    i = d.argmin(1)
    return pts[i], np.sqrt(d[np.arange(len(uv)), i]), ks[i]


def _uv(img: np.ndarray):
    r, g, b = img[..., 0] + EPS, img[..., 1] + EPS, img[..., 2] + EPS
    return np.log(r / g), np.log(b / g)


def _candidates(img: np.ndarray, exclude: np.ndarray | None, lo_pct: float = 35.0):
    """Bright, smooth, unclipped interior pixels (analysis resolution)."""
    y = luminance(img)
    ly = np.log2(y + EPS)
    gx = cv2.Sobel(ly, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(ly, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.GaussianBlur(np.sqrt(gx * gx + gy * gy), (0, 0), 2)
    ok = (img.max(-1) < 0.9 * img.max()) & (y > 0)
    if exclude is not None:
        ok &= exclude < 0.3
    if ok.sum() < 100:
        ok = y > 0
    lo, hi = np.percentile(ly[ok], [lo_pct, 99.5])
    cand = ok & (ly > lo) & (ly < hi) & (grad < np.percentile(grad[ok], 60))
    # brighter diffuse surfaces are more likely white walls/ceilings (wood, fabric are darker)
    w = np.clip((ly - lo) / max(hi - lo, 1e-3), 0, 1) ** 2
    # strongly saturated pixels are coloured objects, not white surfaces under coloured light
    mx, mn = img.max(-1), img.min(-1)
    sat = (mx - mn) / (mx + EPS)
    w = w * np.clip(1.0 - (sat - 0.25) / 0.35, 0.05, 1.0)
    # floors (wood, carpet) are rarely white: fade out the lower part of the frame
    H = img.shape[0]
    ramp = np.clip((0.85 - np.arange(H) / H) / 0.3, 0.05, 1.0).astype(np.float32)
    w = w * ramp[:, None]
    return cand, w


def _wmedian(x: np.ndarray, w: np.ndarray) -> float:
    o = np.argsort(x)
    cw = np.cumsum(w[o])
    return float(x[o][np.searchsorted(cw, 0.5 * cw[-1])])


def estimate_illuminant(img: np.ndarray, exclude: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """Global illuminant (u, v) from gray candidates; returns (uv, info)."""
    u, v = _uv(img)
    cand, w = _candidates(img, exclude)
    if cand.sum() < 50:
        return np.zeros(2), {"candidates": int(cand.sum())}
    uu, vv, ww = u[cand], v[cand], w[cand] + 1e-3
    est = np.array([_wmedian(uu, ww), _wmedian(vv, ww)])
    radius = 0.4
    for _ in range(4):
        d = np.hypot(uu - est[0], vv - est[1])
        sel = d < radius
        if sel.sum() < 30:
            break
        est = np.array([_wmedian(uu[sel], ww[sel]), _wmedian(vv[sel], ww[sel])])
        radius = max(0.15, radius * 0.75)
    p, dist, cct = project_to_locus(est[None])
    info = {"candidates": int(cand.sum()), "uv": est.round(4).tolist(), "cct": float(cct[0]),
            "locus_dist": float(dist[0])}
    return est, info


def local_field(img: np.ndarray, est_global: np.ndarray, exclude: np.ndarray | None, cfg: dict) -> tuple[np.ndarray, dict]:
    """Smooth (H,W,2) field of local illuminant deviation from the global estimate (log-chroma)."""
    H, W = img.shape[:2]
    n = int(cfg.get("grid", 24))
    cy = max(4, int(round(n * H / max(H, W))))
    cx = max(4, int(round(n * W / max(H, W))))
    u, v = _uv(img)
    cand, w = _candidates(img, exclude, float(cfg.get("local_lo_percentile", 10)))
    w = np.maximum(w, 0.15)  # dim walls lit only by a lamp still count (brightness is just a prior)
    field = np.zeros((cy, cx, 2), np.float64)
    conf = np.zeros((cy, cx), np.float64)
    ys = np.linspace(0, H, cy + 1).astype(int)
    xs = np.linspace(0, W, cx + 1).astype(int)
    max_loc = float(cfg.get("max_locus_dist", 0.35))
    tint = float(cfg.get("tint_strength", 0.5))
    for i in range(cy):
        for j in range(cx):
            c = cand[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            if c.sum() < 25:
                continue
            uu = u[ys[i]:ys[i + 1], xs[j]:xs[j + 1]][c]
            vv = v[ys[i]:ys[i + 1], xs[j]:xs[j + 1]][c]
            ww = w[ys[i]:ys[i + 1], xs[j]:xs[j + 1]][c] + 1e-3
            e = np.array([np.average(uu, weights=ww), np.average(vv, weights=ww)])
            p, dist, _ = project_to_locus(e[None])
            if dist[0] > max_loc:
                continue  # strongly colourful surface, not a white lit by a coloured lamp
            # spread of chroma inside the cell: a uniform surface is more trustworthy
            spread = float(np.sqrt(np.average((uu - e[0]) ** 2 + (vv - e[1]) ** 2, weights=ww)))
            # full correction along the Planckian locus (lamp vs daylight), partial for the tint
            # (green bounce from lawns, magenta LEDs) which may also be a coloured wall
            field[i, j] = p[0] + tint * (e - p[0]) - est_global
            conf[i, j] = c.sum() * min(1.0, ww.mean() * 4) / (1.0 + 10 * spread) * np.exp(-(dist[0] / 0.35) ** 2)
    if conf.max() <= 0:
        return np.zeros((H, W, 2), np.float32), {"cells": 0}
    # normalised convolution to fill and smooth
    sig = max(0.7, float(cfg.get("field_smooth", 0.04)) * max(cy, cx))
    num0 = cv2.GaussianBlur((field[..., 0] * conf).astype(np.float32), (0, 0), sig)
    num1 = cv2.GaussianBlur((field[..., 1] * conf).astype(np.float32), (0, 0), sig)
    den = cv2.GaussianBlur(conf.astype(np.float32), (0, 0), sig) + 1e-6
    f = np.stack([num0 / den, num1 / den], -1)
    # cells with no support fade to zero deviation
    support = np.clip(den / (np.percentile(den, 75) + 1e-6), 0, 1)
    f *= support[..., None]
    mag = np.sqrt((f ** 2).sum(-1, keepdims=True))
    lim = float(cfg.get("max_local_shift", 0.35))
    f = f * np.minimum(1.0, lim / (mag + 1e-9))
    full = cv2.resize(f.astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)
    full = cv2.GaussianBlur(full, (0, 0), max(2.0, 0.01 * max(H, W)))
    return full, {"cells": int((conf > 0).sum()), "max_shift": float(mag.max())}


def _apply_gains(img: np.ndarray, du: np.ndarray, dv: np.ndarray) -> np.ndarray:
    """Multiply R by exp(-du), B by exp(-dv) (G fixed), preserving luminance."""
    y0 = luminance(img)
    out = img.copy()
    out[..., 0] *= np.exp(-du)
    out[..., 2] *= np.exp(-dv)
    y1 = luminance(out)
    out *= (y0 / (y1 + EPS))[..., None]
    return out


def white_balance(rad: np.ndarray, rad_small: np.ndarray, win, cfg: dict) -> tuple[np.ndarray, dict]:
    wcfg = cfg.get("white_balance", {})
    if not wcfg.get("enabled", True):
        return rad, {"enabled": False}
    H, W = rad.shape[:2]
    exclude = None
    if win is not None:
        exclude = np.clip(win.mask + win.lamp_mask, 0, 1)
    est, info = estimate_illuminant(rad_small, exclude)
    gs = float(wcfg.get("global_strength", 0.9))
    # target white: slightly warm neutral looks natural (configurable CCT)
    tk = float(wcfg.get("target_cct", 6000))
    tc = kelvin_rgb(tk)
    target = np.array([math.log(tc[0] / tc[1]), math.log(tc[2] / tc[1])])
    # project the estimate: keep the locus component and only part of the tint
    p_est, d_est, _ = project_to_locus(est[None])
    est_eff = p_est[0] + float(wcfg.get("tint_strength", 0.6)) * (est - p_est[0])
    g = (est_eff - target) * gs
    # large corrections are less trustworthy (a room full of wood looks like tungsten light)
    mag = float(np.hypot(*g))
    lim = float(wcfg.get("max_global_shift", 0.45))
    if mag > lim:  # soft limit: the further beyond the limit, the less we trust it
        g = g / mag * lim * (lim / mag) ** 0.5
    info["target_cct"] = tk
    info["global_shift"] = g.round(4).tolist()
    small = _apply_gains(rad_small, np.full(rad_small.shape[:2], g[0], np.float32),
                         np.full(rad_small.shape[:2], g[1], np.float32))
    ml = float(wcfg.get("mixed_light_strength", 0.6))
    field_small = np.zeros(rad_small.shape[:2] + (2,), np.float32)
    if ml > 0:
        fs, linfo = local_field(small, np.zeros(2), exclude, wcfg)
        field_small = fs * ml
        info["local"] = linfo
    # exterior (window views): bring to neutral daylight independently of the room light
    if win is not None and win.mask.max() > 0.5:
        m = win.mask > 0.5
        uw, vw = _uv(small)
        ext = np.array([np.median(uw[m]), np.median(vw[m])])
        p, dist, cct = project_to_locus(ext[None])
        # only the illuminant part (projection), half strength: views may be legitimately green/blue
        ext_corr = 0.5 * p[0]
        wm = cv2.GaussianBlur(win.mask.astype(np.float32), (0, 0), 1.5)[..., None]
        field_small = field_small * (1 - wm) + ext_corr[None, None].astype(np.float32) * wm
        info["exterior_cct"] = float(cct[0])
    full = cv2.resize(field_small, (W, H), interpolation=cv2.INTER_LINEAR)
    du = (g[0] + full[..., 0]).astype(np.float32)
    dv = (g[1] + full[..., 1]).astype(np.float32)
    out = _apply_gains(rad, du, dv)
    log.info("white balance: CCT %.0fK, global shift %s, local cells %s", info.get("cct", 0), info["global_shift"],
             info.get("local", {}).get("cells"))
    return out, info

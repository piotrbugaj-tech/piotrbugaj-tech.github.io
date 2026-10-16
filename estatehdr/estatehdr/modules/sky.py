"""Sky segmentation and replacement.

Detection (analysis resolution):
  1. Column-wise sky border (Shen & Wang 2013 idea): for a range of gradient thresholds the
     border b(x) is the first strong edge from the top of each column; the threshold that
     maximises the colour-homogeneity energy of the sky/ground split wins.
  2. Validation: the "sky" must be bright, smooth, not green and touch the top edge.
  3. Refinement: sky-coloured gaps inside tree crowns and regions cut off by thin wires are
     added (colour model + vegetation ring / proximity), small islands removed.
Compositing (full resolution, row strips):
  soft alpha = luminance key between local sky and local foreground brightness inside a band
  around the border (branches, leaves), hard mask elsewhere; replacement is matting-consistent:
  out = img + alpha * (new_sky - old_sky_local).
"""
from __future__ import annotations

import glob
import hashlib
import logging
import os

import cv2
import numpy as np

from ..imgutil import LUMA, linear_to_srgb, resize_max, resize_rows, row_strips, srgb_to_linear

log = logging.getLogger(__name__)

# sRGB colours: (zenith, middle, horizon)
DAY_STYLES = {
    "clear": ((0.24, 0.47, 0.84), (0.47, 0.67, 0.90), (0.80, 0.88, 0.96)),
    "wispy": ((0.29, 0.52, 0.86), (0.52, 0.70, 0.91), (0.82, 0.89, 0.96)),
    "dramatic": ((0.15, 0.34, 0.70), (0.38, 0.56, 0.83), (0.72, 0.81, 0.92)),
}
TWILIGHT_STYLES = {
    "blue": ((0.05, 0.08, 0.26), (0.16, 0.25, 0.52), (0.46, 0.55, 0.78)),
    "pink": ((0.09, 0.11, 0.32), (0.42, 0.35, 0.60), (0.98, 0.66, 0.57)),
    "golden": ((0.11, 0.18, 0.42), (0.52, 0.48, 0.55), (1.00, 0.74, 0.40)),
}
CLOUDS = {"clear": 0.0, "wispy": 0.45, "dramatic": 0.85}


def seed_of(name: str) -> int:
    return int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16)


def nc_blur(v: np.ndarray, w: np.ndarray, sigma: float) -> np.ndarray:
    """Normalised convolution: weighted Gaussian average of v (HxW or HxWxC) with weights w."""
    w = w.astype(np.float32)
    den = cv2.GaussianBlur(w, (0, 0), sigma) + 1e-6
    if v.ndim == 3:
        num = cv2.GaussianBlur((v * w[..., None]).astype(np.float32), (0, 0), sigma)
        return num / den[..., None]
    return cv2.GaussianBlur((v * w).astype(np.float32), (0, 0), sigma) / den


def _grad(y: np.ndarray) -> np.ndarray:
    g = cv2.GaussianBlur(y, (0, 0), 1.0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    return np.sqrt(gx * gx + gy * gy)


def _energy(img: np.ndarray, sky: np.ndarray, gamma: float = 2.0) -> float:
    s = img[sky]
    g = img[~sky]
    if len(s) < 0.01 * sky.size or len(g) < 0.05 * sky.size:
        return -np.inf
    step_s = max(1, len(s) // 20000)
    step_g = max(1, len(g) // 20000)
    cs = np.cov(s[::step_s].T) + np.eye(3) * 1e-6
    cg = np.cov(g[::step_g].T) + np.eye(3) * 1e-6
    ls = np.linalg.eigvalsh(cs)[-1]
    lg = np.linalg.eigvalsh(cg)[-1]
    return float(1.0 / (gamma * np.linalg.det(cs) ** (1 / 3) + np.linalg.det(cg) ** (1 / 3) + gamma * ls + lg))


def _border(img: np.ndarray, grad: np.ndarray, n: int = 20) -> tuple[np.ndarray, float]:
    h, w = grad.shape
    best = (-np.inf, np.zeros(w, np.int64))
    rows = np.arange(h)[:, None]
    for t in np.quantile(grad, np.linspace(0.35, 0.97, n)):
        edge = grad > t
        edge[-1] = True
        b = edge.argmax(0)
        b = cv2.medianBlur(b.astype(np.float32)[None], 5)[0].astype(np.int64) if w >= 5 else b
        sky = rows < b[None]
        J = _energy(img, sky)
        if J > best[0]:
            best = (J, b)
    return best[1], best[0]


def detect_sky(img_small: np.ndarray, only_in: np.ndarray | None = None) -> tuple[np.ndarray | None, dict]:
    """Sky mask (float32 0..1, analysis resolution) of a display-referred sRGB image.
    Returns (None, info) when no plausible sky is found."""
    h, w = img_small.shape[:2]
    y = img_small @ LUMA
    grad = _grad(y)
    info: dict = {}
    if only_in is not None:
        return _sky_in_windows(img_small, y, grad, only_in)
    b, J = _border(img_small, grad)
    rows = np.arange(h)[:, None]
    sky = rows < b[None]
    frac = float(sky.mean())
    cols = float((b > 0.02 * h).mean())
    info.update(border_energy=J, raw_frac=round(frac, 4), top_cols=round(cols, 3))
    if frac < 0.03 or cols < 0.3:
        info["reason"] = "no sky region at the top"
        return None, info
    ys, yg = np.median(y[sky]), np.median(y[~sky])
    gs = float(np.mean(grad[sky]))
    px = img_small[sky]
    green = float(np.mean((px[:, 1] > px[:, 0] * 1.08) & (px[:, 1] > px[:, 2] * 1.08)))
    info.update(sky_luma=round(float(ys), 3), ground_luma=round(float(yg), 3), sky_grad=round(gs, 4),
                green_frac=round(green, 3))
    if ys < 0.45 or ys < yg + 0.05 or green > 0.3 or gs > 0.06:
        info["reason"] = "top region does not look like sky"
        return None, info
    # --- refinement: sky-coloured gaps in trees / regions behind wires --------------------------
    mu = px.mean(0)
    cov = np.cov(px[:: max(1, len(px) // 20000)].T) + np.eye(3) * 2e-4
    icov = np.linalg.inv(cov)
    d = img_small.reshape(-1, 3) - mu
    m2 = np.einsum("ij,jk,ik->i", d, icov, d).reshape(h, w)
    ylo = float(np.percentile(y[sky], 10))
    horizon = int(np.percentile(b, 90))
    cand = (m2 < 9.0) & (y >= ylo) & ~sky & (rows <= horizon)
    veg = ((img_small[..., 1] > img_small[..., 0]) & (img_small[..., 1] >= img_small[..., 2] * 0.95)) | (y < ys * 0.45)
    near = cv2.dilate(sky.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8), 8)
    add = np.zeros(n, bool)
    k = np.ones((5, 5), np.uint8)
    for i in range(1, n):
        x0, y0, ww, hh, area = stats[i]
        if area < 3:
            continue
        comp = lab[y0:y0 + hh, x0:x0 + ww] == i
        if near[y0:y0 + hh, x0:x0 + ww][comp].mean() > 0 and grad[y0:y0 + hh, x0:x0 + ww][comp].mean() < 2 * gs + 0.01:
            add[i] = True
            continue
        if area > 0.02 * h * w:
            continue
        pad = 3
        a0, a1, c0, c1 = max(0, y0 - pad), min(h, y0 + hh + pad), max(0, x0 - pad), min(w, x0 + ww + pad)
        cc = lab[a0:a1, c0:c1] == i
        ring = (cv2.dilate(cc.astype(np.uint8), k) > 0) & ~cc
        if ring.sum() and veg[a0:a1, c0:c1][ring].mean() > 0.5:
            add[i] = True
    sky = sky | add[lab]
    # remove small isolated sky islands below the border band (bright facade patches etc.)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(sky.astype(np.uint8), 8)
    if n > 2:
        keep = np.zeros(n, bool)
        big = np.argmax(stats[1:, cv2.CC_STAT_AREA]) + 1
        keep[big] = True
        for i in range(1, n):
            if i != big and (stats[i, cv2.CC_STAT_AREA] >= 4 or stats[i, cv2.CC_STAT_TOP] < horizon):
                keep[i] = True
        sky = keep[lab] & sky
    info.update(frac=round(float(sky.mean()), 4), horizon_frac=round(horizon / h, 3))
    return sky.astype(np.float32), info


def _sky_in_windows(img, y, grad, win_mask):
    """Sky inside window views of an interior: bright, smooth, non-green, at the top of each view."""
    h, w = y.shape
    wm = win_mask > 0.5
    if wm.sum() < 0.002 * h * w:
        return None, {"reason": "no window views"}
    green = (img[..., 1] > img[..., 0] * 1.08) & (img[..., 1] > img[..., 2] * 1.08)
    smooth = cv2.blur(grad, (5, 5)) < 0.04
    bright = y > np.percentile(y[wm], 40)
    cand = (wm & smooth & bright & ~green).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cand, 8)
    out = np.zeros((h, w), np.float32)
    nw, wlab, wstats, _ = cv2.connectedComponentsWithStats(wm.astype(np.uint8), 8)
    for i in range(1, n):
        x0, y0, ww, hh, area = stats[i]
        if area < 0.05 * wm.sum() / max(nw - 1, 1):
            continue
        # must touch the top part of its window region
        wid = np.bincount(wlab[lab == i]).argmax()
        top = wstats[wid, cv2.CC_STAT_TOP]
        if y0 <= top + 0.15 * wstats[wid, cv2.CC_STAT_HEIGHT]:
            out[lab == i] = 1.0
    if out.sum() < 10:
        return None, {"reason": "no sky in window views"}
    return out, {"frac": round(float(out.mean()), 4), "in_windows": True}


# ---------------------------------------------------------------------------------------------
# sky synthesis
# ---------------------------------------------------------------------------------------------

def _fbm(w: int, h: int, rng: np.random.Generator, cell: float, octaves: int = 5, aniso: float = 1.0) -> np.ndarray:
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        cx = max(2, int(w / (cell * aniso)) + 2)
        cy = max(2, int(h / cell) + 2)
        g = rng.standard_normal((cy, cx)).astype(np.float32)
        out += amp * cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC)
        tot += amp
        amp *= 0.5
        cell /= 2.0
    return out / tot


def _gradient(stops_srgb, t: np.ndarray) -> np.ndarray:
    z, m, hz = (srgb_to_linear(np.array(c, np.float32)) for c in stops_srgb)
    t = t[..., None]
    lo = z + (m - z) * np.clip(t / 0.55, 0, 1)
    return np.where(t < 0.55, lo, m + (hz - m) * np.clip((t - 0.55) / 0.45, 0, 1)).astype(np.float32)


def synth_sky(w: int, h: int, style: str, seed: int, twilight: bool = False) -> np.ndarray:
    """Procedural sky (linear RGB, h x w) whose bottom row is the horizon."""
    rng = np.random.default_rng(seed)
    stops = (TWILIGHT_STYLES if twilight else DAY_STYLES).get(style) or DAY_STYLES["clear"]
    yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    xx = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    sun_x = float(rng.uniform(0.25, 0.75))
    t = np.clip(yy ** 0.75 + 0.06 * np.exp(-((xx - sun_x) / 0.3) ** 2) * yy, 0, 1)
    sky = _gradient(stops, np.broadcast_to(t, (h, w)))
    amount = 0.25 if twilight else CLOUDS.get(style, 0.0)
    if amount > 0:
        cell = max(w, h) / (2.5 if style == "dramatic" else 1.5)
        aniso = 1.6 if style == "dramatic" else 4.0
        n = _fbm(w, h, rng, cell, 6, aniso)
        n = (n - n.mean()) / (n.std() + 1e-6)
        thr = 0.35 if style == "dramatic" else 0.6
        cover = np.clip((n - thr) / 0.9, 0, 1)
        cover = cover * cover * (3 - 2 * cover)
        haze = 1.0 - 0.65 * yy ** 2  # clouds thin out towards the horizon
        a = amount * cover * haze
        if twilight:
            ccol = _gradient(stops, np.clip(t + 0.25, 0, 1)) * 1.1  # clouds lit from below the horizon
        else:
            thick = np.clip((n - thr) / 1.6, 0, 1)
            shade = 1.0 - (0.42 if style == "dramatic" else 0.15) * thick ** 1.3
            # light from above: the upper edge of a cloud is brighter
            dy = np.zeros_like(n)
            dy[2:] = n[2:] - n[:-2]
            shade = shade * (1.0 + 0.10 * np.clip(dy * 4, 0, 1))
            base_white = srgb_to_linear(np.array((0.97, 0.97, 0.98), np.float32))
            ccol = base_white[None, None] * shade[..., None]
        sky = sky * (1 - a[..., None]) + ccol * a[..., None]
    return sky.astype(np.float32)


def load_sky_file(path: str, seed: int) -> np.ndarray | None:
    """User sky photo (file, or a directory to pick from deterministically) as linear RGB."""
    if os.path.isdir(path):
        files = sorted(f for f in glob.glob(os.path.join(path, "*")) if f.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")))
        if not files:
            return None
        path = files[seed % len(files)]
    im = cv2.imread(path, cv2.IMREAD_COLOR)
    if im is None:
        return None
    return srgb_to_linear(cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0)


def _fit_cover(src: np.ndarray, w: int, h: int) -> np.ndarray:
    """Scale to cover w x h, anchored at the bottom (horizon of a sky photo stays low)."""
    sh, sw = src.shape[:2]
    s = max(w / sw, h / sh)
    r = cv2.resize(src, (max(w, round(sw * s)), max(h, round(sh * s))), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    x0 = (r.shape[1] - w) // 2
    return r[r.shape[0] - h:, x0:x0 + w]


# ---------------------------------------------------------------------------------------------
# compositing
# ---------------------------------------------------------------------------------------------

def composite_sky(img: np.ndarray, mask_small: np.ndarray, new_sky_lin_small: np.ndarray, sky_rows: int,
                  match_luma: float | None = None, band_px: float = 2.5) -> tuple[np.ndarray, dict]:
    """Replace the sky of a display sRGB image (in place, row strips).

    mask_small: sky mask at analysis resolution; new_sky_lin_small: linear RGB sky image at the
    analysis width covering rows [0, sky_rows) of the analysis image."""
    H, W = img.shape[:2]
    hs, ws = mask_small.shape
    small = cv2.resize(img, (ws, hs), interpolation=cv2.INTER_AREA)
    lin_small = srgb_to_linear(small)
    y_small = lin_small @ LUMA
    sky_core = cv2.erode((mask_small > 0.5).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32)
    fg_core = cv2.erode((mask_small < 0.5).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32)
    sig = max(2.0, 0.01 * max(hs, ws))
    old_sky = nc_blur(lin_small, sky_core, sig)      # local old sky colour (linear)
    S = old_sky @ LUMA
    F = nc_blur(y_small, fg_core, sig)               # local foreground brightness
    # brightness of the new sky follows the old one (no dark skies over bright houses)
    new = np.zeros_like(lin_small)
    new[:sky_rows] = new_sky_lin_small[:sky_rows]
    if sky_rows < hs:
        new[sky_rows:] = new_sky_lin_small[sky_rows - 1:sky_rows]
    gain = 1.0
    if match_luma is not None:
        cur = float(np.median((new @ LUMA)[mask_small > 0.5])) if (mask_small > 0.5).any() else 1.0
        gain = match_luma / max(cur, 1e-4)
        new *= gain
    soft = cv2.GaussianBlur(mask_small.astype(np.float32), (0, 0), band_px)
    band = ((soft > 0.02) & (soft < 0.98)).astype(np.float32)
    contrast = np.clip((S - F - 0.04) / 0.08, 0, 1)   # luminance key only where the sky is clearly brighter
    for r0, r1 in row_strips(H, W):
        m = resize_rows(mask_small, W, H, r0, r1)
        bnd = resize_rows(band, W, H, r0, r1)
        if m.max() <= 0.001 and bnd.max() <= 0.001:
            continue
        lin = srgb_to_linear(img[r0:r1])
        y = lin @ LUMA
        Sr = resize_rows(S, W, H, r0, r1)
        Fr = resize_rows(F, W, H, r0, r1)
        key = np.clip((y - Fr) / np.maximum(Sr - Fr, 1e-3), 0, 1)
        c = resize_rows(contrast, W, H, r0, r1)
        a_band = c * key + (1 - c) * np.clip(m, 0, 1)
        hard = (m > 0.5).astype(np.float32)
        a = bnd * a_band + (1 - bnd) * hard
        a = a[..., None]
        nr = resize_rows(new, W, H, r0, r1)
        osr = resize_rows(old_sky, W, H, r0, r1)
        out = np.where(a >= 0.999, nr, lin + a * (nr - osr))
        img[r0:r1] = linear_to_srgb(np.clip(out, 0, 1))
    return img, {"gain": round(float(gain), 3)}


def replace_sky(img: np.ndarray, cfg: dict, name: str, win=None, style: str | None = None,
                twilight: bool = False, mask_small: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """Sky replacement on a display sRGB float image (modified in place)."""
    scfg = cfg.get("modules", {}).get("sky", {})
    style = style or str(scfg.get("style", "clear"))
    side = 1000
    small, _ = resize_max(img, side)
    info: dict = {}
    if mask_small is None:
        mask_small, info = detect_sky(small)
        if mask_small is None and scfg.get("interior_windows", False) and win is not None:
            wm = cv2.resize(win.mask.astype(np.float32), (small.shape[1], small.shape[0]))
            mask_small, info = detect_sky(small, only_in=wm)
    if mask_small is None:
        info["applied"] = False
        return img, info
    hs, ws = mask_small.shape
    rows_any = np.nonzero(mask_small.max(1) > 0.5)[0]
    sky_rows = int(min(hs, rows_any.max() + 2)) if len(rows_any) else hs
    seed = seed_of(name)
    custom = None
    if style not in DAY_STYLES and not twilight:
        custom = load_sky_file(style, seed)
        if custom is None:
            log.warning("sky file/dir %r not usable, using 'clear'", style)
            style = "clear"
    if custom is not None:
        sky = _fit_cover(custom, ws, sky_rows)
    else:
        sky = synth_sky(ws, sky_rows, style, seed, twilight=twilight)
    lin_small = srgb_to_linear(small)
    old_y = float(np.median((lin_small @ LUMA)[mask_small > 0.5]))
    if twilight:
        match = None
    else:
        # daytime: keep a bright but not blown sky (display ~0.62-0.85 of the old sky brightness)
        match = float(np.clip(old_y, srgb_to_linear(np.float32(0.62)), srgb_to_linear(np.float32(0.86))))
    img, cinfo = composite_sky(img, mask_small, sky, sky_rows, match_luma=match)
    info.update(cinfo, applied=True, style=style if custom is None else "file", sky_rows_frac=round(sky_rows / hs, 3))
    info["mask_small"] = mask_small  # removed before serialisation by run_modules
    return img, info

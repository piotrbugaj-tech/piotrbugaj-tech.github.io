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


def detect_sky(img_small: np.ndarray, only_in: np.ndarray | None = None) -> tuple[np.ndarray | None, dict]:
    """Sky mask (float32 0..1, analysis resolution) of a display-referred sRGB image.
    Returns (None, info) when no plausible sky is found."""
    h, w = img_small.shape[:2]
    y = img_small @ LUMA
    grad = _grad(y)
    if only_in is not None:
        return _sky_in_windows(img_small, y, grad, only_in)
    info: dict = {}
    tex = cv2.blur(grad, (5, 5))
    r, g, bl = img_small[..., 0], img_small[..., 1], img_small[..., 2]
    green = (g > r * 1.05) & (g > bl * 1.05)
    chroma = (np.maximum(np.maximum(r, g), bl) - np.minimum(np.minimum(r, g), bl)) / (y + 1e-3)
    # 1. seeds: smooth, non-green, not dark pixels in the top band
    top = max(2, int(0.06 * h))
    seed = np.zeros((h, w), bool)
    seed[:top] = (tex[:top] < 0.03) & ~green[:top] & (y[:top] > 0.15)
    sfrac = float(seed[:top].mean())
    info["seed_frac"] = round(sfrac, 3)
    if sfrac < 0.15:
        info["reason"] = "no smooth region at the top"
        return None, info
    # 2. candidates: like the seeds, bluish or cloud-like, and not textured (edges are barriers)
    sp = img_small[seed]
    mu = sp.mean(0)
    cov = np.cov(sp[:: max(1, len(sp) // 20000)].T) + np.eye(3) * 4e-4
    d = img_small.reshape(-1, 3) - mu
    m2 = np.einsum("ij,jk,ik->i", d, np.linalg.inv(cov), d).reshape(h, w)
    ys_seed = float(np.median(y[seed]))
    bluish = ((bl - r) / (y + 1e-3) > 0.08) & ~green & (y > 0.12)
    cloud = (chroma < 0.12) & (y > max(0.35, 0.55 * ys_seed))
    # soft cloud edges are allowed more texture than seed-coloured pixels (facades, roofs)
    cand = ((m2 < 16.0) & (tex < 0.045)) | ((bluish | cloud) & (tex < 0.08))
    cand |= seed
    n, lab = cv2.connectedComponents(cand.astype(np.uint8), connectivity=4)
    keep = np.zeros(n, bool)
    keep[np.unique(lab[seed])] = True
    keep[0] = False
    sky = keep[lab]
    # textured clouds (strong local contrast): bright, non-green regions touching the sky core
    # whose pixels mostly have sky *below* them in the same column (a facade never has)
    kx = max(1, int(0.03 * w))
    skyx = cv2.dilate(sky.astype(np.uint8), np.ones((1, 2 * kx + 1), np.uint8)) > 0
    below = np.zeros_like(sky)
    below[:-1] = np.flip(np.maximum.accumulate(np.flip(skyx, 0), 0), 0)[1:]
    ccand = (y > 0.4) & (chroma < 0.6) & ((bl - r) / (y + 1e-3) > -0.05) & ~green & (tex < 0.3) & ~sky
    near = cv2.dilate(sky.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    n, lab = cv2.connectedComponents(ccand.astype(np.uint8), connectivity=8)
    if n > 1:
        idx = lab.ravel()
        cnt = np.bincount(idx, minlength=n).astype(np.float64)
        touch = np.bincount(idx, weights=near.ravel().astype(np.float64), minlength=n)
        blw = np.bincount(idx, weights=below.ravel().astype(np.float64), minlength=n)
        ok = (touch > 0) & (blw >= 0.3 * np.maximum(cnt, 1))
        ok[0] = False
        sky |= ok[lab]
    # fill small enclosed holes (birds, wires, lamp posts)
    holes = (~sky).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(holes, 4)
    for i in range(1, n):
        x0, y0, ww, hh, area = stats[i]
        if area < 0.001 * h * w and y0 > 0 and x0 > 0 and x0 + ww < w and y0 + hh < h:
            sky[lab == i] = True
    frac = float(sky.mean())
    cols = float(sky[: max(1, int(0.02 * h))].mean(0).__gt__(0.5).mean())
    info.update(raw_frac=round(frac, 4), top_cols=round(cols, 3))
    if frac < 0.02 or cols < 0.3:
        info["reason"] = "no sky region at the top"
        return None, info
    if (~sky).sum() < 0.01 * h * w:  # the whole frame grew into one smooth region (wall / overcast blow-out)
        info["reason"] = "frame is uniformly smooth, no ground to compare with"
        return None, info
    ys, yg = float(np.median(y[sky])), float(np.median(y[~sky]))
    gs = float(np.mean(grad[sky]))
    px = img_small[sky]
    green_frac = float(np.mean(green[sky]))
    # sky vs. ceiling / bright wall: a sky is bluish, or (overcast, sunset) the brightest part of
    # the frame; interior ceilings are neutral/warm and darker than the window views
    blue = float(np.median((px[:, 2] - px[:, 0]) / (px @ LUMA + 1e-3)))
    g97 = float(np.percentile(y[~sky], 97))
    info.update(sky_luma=round(ys, 3), ground_luma=round(yg, 3), sky_grad=round(gs, 4),
                green_frac=round(green_frac, 3), blue=round(blue, 3), ground_p97=round(g97, 3))
    if green_frac > 0.3 or gs > 0.06:
        info["reason"] = "top region is green or textured"
        return None, info
    if blue >= 0.3:            # clearly blue: deep blue skies may be darker than sunlit facades
        ok = ys >= 0.2
    elif blue >= 0.08:         # pale blue: must also be bright
        ok = ys >= 0.45 and ys >= yg + 0.05
    else:                      # overcast (near white, very bright) / sunset (warm): the brightest part of
        ok = cols >= 0.5 and ((ys >= 0.85 and ys >= g97 - 0.03) or   # a wide top region
                              (ys >= 0.45 and ((blue <= -0.15 and ys >= g97 - 0.02) or
                                               (blue <= -0.04 and ys >= g97 + 0.1))))
    if not ok:
        info["reason"] = "top region is not sky-like (colour/brightness: ceiling, wall)"
        return None, info
    # 3. refinement: sky-coloured gaps inside tree crowns (enclosed by vegetation)
    rows_with = np.nonzero(sky.any(1))[0]
    horizon = int(rows_with.max()) if len(rows_with) else 0
    mu = px.mean(0)
    cov = np.cov(px[:: max(1, len(px) // 20000)].T) + np.eye(3) * 2e-4
    d = img_small.reshape(-1, 3) - mu
    m2 = np.einsum("ij,jk,ik->i", d, np.linalg.inv(cov), d).reshape(h, w)
    ylo = float(np.percentile(y[sky], 10))
    rows = np.arange(h)[:, None]
    gap = (m2 < 9.0) & (y >= ylo) & ~sky & (rows <= horizon)
    veg = green | (y < ys * 0.45)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(gap.astype(np.uint8), 8)
    add = np.zeros(n, bool)
    k = np.ones((5, 5), np.uint8)
    for i in range(1, n):
        x0, y0, ww, hh, area = stats[i]
        if area < 2 or area > 0.02 * h * w:
            continue
        pad = 3
        a0, a1, c0, c1 = max(0, y0 - pad), min(h, y0 + hh + pad), max(0, x0 - pad), min(w, x0 + ww + pad)
        cc = lab[a0:a1, c0:c1] == i
        ring = (cv2.dilate(cc.astype(np.uint8), k) > 0) & ~cc
        if ring.sum() and veg[a0:a1, c0:c1][ring].mean() > 0.5:
            add[i] = True
    sky = sky | add[lab]
    info.update(frac=round(float(sky.mean()), 4), horizon_frac=round(horizon / h, 3))
    return sky.astype(np.float32), info


def _local_chromaticity(img: np.ndarray, weight: np.ndarray, sigma: float) -> tuple[np.ndarray, np.ndarray]:
    """Chromaticity (rgb / sum) of every pixel and the chromaticity of the nearest weighted
    pixels (normalised convolution at growing scales, so far-away pixels get the closest
    estimate instead of noise)."""
    ch = (img / (img.sum(2, keepdims=True) + 1e-4)).astype(np.float32)
    h, w = weight.shape
    # smooth estimate: computed at 1/4 of the sigma in pixels (large blurs are slow otherwise)
    s = max(1.0, sigma / 4.0)
    sw, sh = max(2, round(w / s)), max(2, round(h / s))
    wl = cv2.resize(weight.astype(np.float32), (sw, sh), interpolation=cv2.INTER_AREA)
    cl = cv2.resize(ch * weight[..., None].astype(np.float32), (sw, sh), interpolation=cv2.INTER_AREA)
    out = np.empty((sh, sw, 3), np.float32)
    got = np.zeros((sh, sw), np.float32)
    for f in (4.0, 12.0, 36.0):
        num = cv2.GaussianBlur(cl, (0, 0), f)
        den = cv2.GaussianBlur(wl, (0, 0), f)
        fill = got < 1e-3
        out[fill] = (num / (den[..., None] + 1e-6))[fill]
        got = np.maximum(got, den)
    out[got < 1e-6] = ch[weight > 0].mean(0)
    return ch, cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)


def _open_top(lab: np.ndarray, i: int, stat, sky: np.ndarray, skylike: np.ndarray, green: np.ndarray) -> bool:
    """Is component i open towards the sky?  Above its upper outline there is the frame top, the
    sky, sky seen through a crown (sky-coloured pixels between twigs) or foliage.  A pale facade
    under a pale sky has a roof or an eave above it instead."""
    h = lab.shape[0]
    x0, y0, ww, hh = (int(v) for v in stat[:4])
    a0 = max(0, y0 - 3)
    c = lab[a0:y0 + hh, x0:x0 + ww] == i
    cols = np.nonzero(c.any(0))[0]
    top = c.argmax(0)[cols] + a0
    xs = cols + x0
    near = np.zeros(len(cols), bool)
    for k in (1, 2, 3):
        near |= sky[np.maximum(top - k, 0), xs] > 0.5
    if ((top == 0) | near).mean() >= 0.7:
        return True
    d = max(3, int(0.04 * h))
    sl, gr, n = 0.0, 0.0, 0
    for x, t in zip(xs, top):
        s0, s1 = max(0, t - 3 - d), max(0, t - 3)
        if s1 > s0:
            sl += float(skylike[s0:s1, x].mean())
            gr += float(green[s0:s1, x].mean())
            n += 1
    return n == 0 or sl / n >= 0.2 or gr / n >= 0.3


def extend_sky_mask(img_small: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, dict]:
    """Daytime sky left outside a detected sky mask (behind/below tree crowns, cut off by
    branches) for modules that must replace *all* of the sky (twilight).

    Added pixels match the colour model of the detected sky (Mahalanobis distance, or near-white
    haze/cloud) and the chromaticity of the nearest detected sky, and lie above the roof line:
    above the bottom-connected solid (non-sky-coloured) masses — buildings, ground, trunks —
    after an opening that removes branches and wires.  Low-texture regions must be large and
    open towards the sky (frame top, sky, sky seen through a crown or foliage above them, not a
    roof or an eave: a pale facade under a pale sky is not added);
    textured (twig) pixels are added only next to them or as bright gaps among dark twigs next to
    the sky.  Returns (mask float32, info)."""
    h, w = mask.shape
    sky = mask > 0.5
    info: dict = {}
    if sky.sum() < 50:
        return mask, info
    y = img_small @ LUMA
    tex = cv2.blur(_grad(y), (5, 5))
    px = img_small[sky]
    mu = px.mean(0)
    cov = np.cov(px[:: max(1, len(px) // 20000)].T) + np.eye(3) * 4e-4
    d = img_small.reshape(-1, 3) - mu
    m2 = np.einsum("ij,jk,ik->i", d, np.linalg.inv(cov), d).reshape(h, w)
    r, g, b = img_small[..., 0], img_small[..., 1], img_small[..., 2]
    green = (g > r * 1.05) & (g > b * 1.05)
    ylo = float(np.percentile(y[sky], 5))
    ys = float(np.median(y[sky]))
    chroma = (np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)) / (y + 1e-3)
    cloud = (chroma < 0.12) & (y > max(0.35, 0.55 * ys))
    ch, lch = _local_chromaticity(img_small, sky, 0.03 * max(h, w))
    near_col = np.sqrt(((ch - lch) ** 2).sum(2)) < 0.03   # same hue as the closest real sky (no grey roofs under a blue sky)
    loose = ((m2 < 16.0) | cloud) & (y >= 0.9 * ylo) & ~green
    col = loose & near_col
    rows = np.arange(h)[:, None]
    rows_with = np.nonzero(sky.any(1))[0]
    horizon = int(rows_with.max()) if len(rows_with) else 0
    k = max(5, int(0.03 * max(h, w))) | 1
    disk_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))

    def above_roof(skylike):
        """Rows above the roof line.  Per column, the roof line is the top of the solid (not
        sky-like) run reaching up from the bottom of the frame: masses connected to the bottom
        (buildings, ground, trunks) after an opening that removes branches and wires, with
        enclosed holes (windows reflecting the sky) filled.  A crown touching a roof does not
        hide the sky below it: the run stops at the first sky-like gap."""
        solid = cv2.morphologyEx((~(skylike | sky)).astype(np.uint8), cv2.MORPH_OPEN, disk_k)
        n, lab = cv2.connectedComponents(solid, connectivity=8)
        keep = np.zeros(n, bool)
        keep[np.unique(lab[-max(2, int(0.02 * h)):])] = True
        keep[0] = False
        cs, _ = cv2.findContours(keep[lab].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros((h, w), np.uint8)
        cv2.drawContours(filled, cs, -1, 1, -1)
        run = np.flip(np.minimum.accumulate(np.flip(filled > 0, 0), 0), 0)
        first = np.where(run.any(0), run.argmax(0), h)
        return (rows < first[None, :]) & (rows <= horizon + 0.1 * h)

    zone = above_roof(col)
    # large smooth sky-coloured regions above the roof line
    seed = (col & (tex < 0.03) & zone & ~sky).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(seed, connectivity=8)
    big = st[:, cv2.CC_STAT_AREA] >= 0.002 * h * w
    big[0] = False
    for i in np.nonzero(big)[0]:
        big[i] = _open_top(lab, i, st[i], sky, loose, green)
    add = big[lab]
    n_added = int(big.sum())
    rr = max(3, int(0.02 * max(h, w)))
    disk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rr + 1, 2 * rr + 1))
    near_add = cv2.dilate(add.astype(np.uint8), disk) > 0
    near_sky = cv2.dilate(sky.astype(np.uint8), disk) > 0
    # sky seen between twigs: bright local maxima among much darker pixels
    k7 = np.ones((7, 7), np.uint8)
    twig = (y - cv2.erode(y, k7) > 0.3) & (cv2.dilate(y, k7) - y < 0.04) & col
    dense = cv2.blur(twig.astype(np.float32), (15, 15)) > 0.15
    extra = col & zone & ~sky & ~add & (y >= ylo) & (near_add | (near_sky & twig & dense))
    out = sky | add | extra
    # wisps of cloud and haze inside the sky (pale, bright, mostly surrounded by sky; may touch
    # the roof line): enclosed holes are filled by detect_sky, these touch the foreground
    pale = (((b - r) / (y + 1e-3) > 0.0) | (chroma < 0.15)) & (y >= max(ylo, 0.6 * ys)) & ~green
    hole = (~out & zone & pale).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(hole, connectivity=8)
    k3 = np.ones((3, 3), np.uint8)
    for i in range(1, n):
        x0, y0, ww, hh, area = st[i]
        if area > 0.01 * h * w:
            continue
        a0, a1, c0, c1 = max(0, y0 - 2), min(h, y0 + hh + 2), max(0, x0 - 2), min(w, x0 + ww + 2)
        cc = lab[a0:a1, c0:c1] == i
        ring = (cv2.dilate(cc.astype(np.uint8), k3) > 0) & ~cc
        if ring.any() and out[a0:a1, c0:c1][ring].mean() >= 0.6:
            out[a0:a1, c0:c1] |= cc
    # daytime-sky-like regions above the roof line that are still not covered (seam risk),
    # relative to the sky area
    left = (loose & (tex < 0.03) & above_roof(loose) & ~(cv2.dilate(out.astype(np.uint8), k7) > 0)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(left, connectivity=8)
    big = st[:, cv2.CC_STAT_AREA] >= 0.001 * h * w
    big[0] = False
    for i in np.nonzero(big)[0]:
        big[i] = _open_top(lab, i, st[i], out, loose, green)
    info.update(added_frac=round(float((out & ~sky).mean()), 4), added_regions=n_added,
                leftover=round(float(big[lab].sum() / max(out.sum(), 1)), 4))
    return out.astype(np.float32), info


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
    """Zenith -> horizon colour as a quadratic Bezier through three sRGB stops (linear light,
    no kink/banding at the middle stop)."""
    z, m, hz = (srgb_to_linear(np.array(c, np.float32)) for c in stops_srgb)
    t = np.clip(t, 0, 1)[..., None]
    return ((1 - t) ** 2 * z + 2 * (1 - t) * t * m + t * t * hz).astype(np.float32)


def synth_sky(w: int, h: int, style: str, seed: int, twilight: bool = False) -> np.ndarray:
    """Procedural sky (linear RGB, h x w) whose bottom row is the horizon."""
    rng = np.random.default_rng(seed)
    table, fallback = (TWILIGHT_STYLES, "pink") if twilight else (DAY_STYLES, "clear")
    if style not in table:
        log.warning("unknown %s sky style %r, using %r", "twilight" if twilight else "day", style, fallback)
    stops = table.get(style) or table[fallback]
    yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    xx = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    sun_x = float(rng.uniform(0.25, 0.75))
    t = np.clip(yy ** 0.75 + 0.06 * np.exp(-((xx - sun_x) / 0.3) ** 2) * yy, 0, 1)
    sky = _gradient(stops, np.broadcast_to(t, (h, w)))
    amount = 0.25 if twilight else CLOUDS.get(style, 0.0)
    if amount > 0:
        dramatic = style == "dramatic"
        cell = max(w, h) / (2.2 if dramatic else 1.5)
        aniso = 1.8 if dramatic else 4.0
        n = _fbm(w, h, rng, cell, 6, aniso)
        n = (n - n.mean()) / (n.std() + 1e-6)
        thr = 0.15 if dramatic else 0.6
        cover = np.clip((n - thr) / (0.6 if dramatic else 0.9), 0, 1)
        cover = cover * cover * (3 - 2 * cover)
        haze = 1.0 - 0.65 * yy ** 2  # clouds thin out towards the horizon
        a = amount * cover * haze
        if twilight:
            ccol = _gradient(stops, np.clip(t + 0.25, 0, 1)) * 1.1  # clouds lit from below the horizon
        else:
            white = srgb_to_linear(np.array((0.98, 0.98, 0.99), np.float32))
            shadow = srgb_to_linear(np.array((0.55, 0.60, 0.70), np.float32))
            # thicker parts are darker (self-shadowing), upper edges are sun-lit
            thick = np.clip((n - thr) / (1.4 if dramatic else 2.0), 0, 1) ** 1.2
            if not dramatic:
                thick *= 0.35
            cb = cv2.GaussianBlur(cover, (0, 0), max(1.0, 0.01 * w))
            dy = np.zeros_like(cb)
            dy[1:] = cb[1:] - cb[:-1]
            lit = np.clip(dy * (0.6 * w), 0, 1)  # cover increasing downwards = top edge
            mix = np.clip(thick - 0.6 * lit, 0, 1)[..., None]
            ccol = white[None, None] * (1 - mix) + shadow[None, None] * mix
        sky = sky * (1 - a[..., None]) + ccol * a[..., None]
    return sky.astype(np.float32)


def load_sky_file(path: str, seed: int) -> np.ndarray | None:
    """User sky photo (file, or a directory to pick from deterministically) as 8-bit sRGB."""
    if os.path.isdir(path):
        files = sorted(f for f in glob.glob(os.path.join(path, "*")) if f.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")))
        if not files:
            return None
        path = files[seed % len(files)]
    im = cv2.imread(path, cv2.IMREAD_COLOR)
    if im is None:
        return None
    return cv2.cvtColor(im, cv2.COLOR_BGR2RGB)


def _fit_cover(src: np.ndarray, w: int, h: int) -> np.ndarray:
    """Scale to cover w x h, anchored at the top (the top of a sky photo is pure sky; trees or
    roofs at its bottom edge are cropped away)."""
    sh, sw = src.shape[:2]
    s = max(w / sw, h / sh)
    r = cv2.resize(src, (max(w, round(sw * s)), max(h, round(sh * s))), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    x0 = (r.shape[1] - w) // 2
    return r[:h, x0:x0 + w]


# ---------------------------------------------------------------------------------------------
# compositing
# ---------------------------------------------------------------------------------------------

def composite_sky(img: np.ndarray, mask_small: np.ndarray, new_sky_lin_small: np.ndarray, sky_rows: int,
                  match_luma: float | None = None, band_px: float = 2.5,
                  full_sky_u8: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """Replace the sky of a display sRGB image (in place, row strips).

    mask_small: sky mask at analysis resolution; new_sky_lin_small: linear RGB sky image at the
    analysis width covering rows [0, sky_rows) of the analysis image.  full_sky_u8 (optional):
    the same sky as 8-bit sRGB at the full output width (a user photo), used instead of the
    upsampled analysis-resolution sky so a real photo keeps its sharpness."""
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
        gain = float(np.clip(match_luma / max(cur, 1e-4), 0.5, 2.0))
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
        if full_sky_u8 is not None:
            idx = np.minimum(np.arange(r0, r1), full_sky_u8.shape[0] - 1)
            nr = srgb_to_linear(full_sky_u8[idx].astype(np.float32) * np.float32(1 / 255)) * np.float32(gain)
        else:
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
    full = None
    if custom is not None:
        sky = srgb_to_linear(_fit_cover(custom, ws, sky_rows).astype(np.float32) / 255.0)
        H, W = img.shape[:2]
        full = _fit_cover(custom, W, max(1, int(round(sky_rows * H / hs))))
    else:
        sky = synth_sky(ws, sky_rows, style, seed, twilight=twilight)
    lin_small = srgb_to_linear(small)
    old_y = float(np.median((lin_small @ LUMA)[mask_small > 0.5]))
    if twilight:
        match = None
    else:
        # daytime: keep a bright but not blown sky (display ~0.62-0.85 of the old sky brightness)
        match = float(np.clip(old_y, srgb_to_linear(np.float32(0.62)), srgb_to_linear(np.float32(0.86))))
    img, cinfo = composite_sky(img, mask_small, sky, sky_rows, match_luma=match, full_sky_u8=full)
    info.update(cinfo, applied=True, style=style if custom is None else "file", sky_rows_frac=round(sky_rows / hs, 3))
    info["mask_small"] = mask_small  # removed before serialisation by run_modules
    return img, info

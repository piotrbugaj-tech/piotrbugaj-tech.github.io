"""Small object removal: mask-guided inpainting.

Masks come from the web UI (brush) or from files next to the photos:
``<frame>.mask.png`` or ``<series>.mask.png`` (white = remove), in the coordinates of the
original frame as displayed (EXIF orientation applied); other sizes are rescaled.

Methods
  * ``patch`` - exemplar-based completion (Criminisi, Perez & Toyama 2004), batched: the fill
    front is processed in priority order (confidence x isophote term); every target patch copies
    its unknown pixels from the best matching fully-known source patch (masked SSD over all
    candidate sources as one matrix product).  It runs at a bounded working resolution and the
    resulting source-offset field is transferred to full resolution, so texture stays sharp.
    Seams between blocks copied with different offsets are softened by 1 px.
  * ``telea`` - OpenCV fast marching (Telea 2004), for thin/small masks.
  * ``auto``  - telea for components thinner than ~10 px, patch otherwise.
"""
from __future__ import annotations

import logging
import os

import cv2
import numpy as np

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------------------------
# mask discovery
# ---------------------------------------------------------------------------------------------

def find_mask(group, extra=None) -> np.ndarray | None:
    """Removal mask (uint8 0/255) for a series, from the UI (``extra``) or mask files."""
    m = None
    if isinstance(extra, dict):
        m = extra.get("remove")
    elif extra is not None:
        m = extra
    if isinstance(m, str):
        m = cv2.imread(m, cv2.IMREAD_GRAYSCALE)
    if isinstance(m, np.ndarray):
        return (m > 127).astype(np.uint8) * 255 if m.ndim == 2 else (m[..., 0] > 127).astype(np.uint8) * 255
    cands = []
    for f in group.frames:
        cands.append(os.path.splitext(f.path)[0] + ".mask.png")
    if group.frames:
        cands.append(os.path.join(os.path.dirname(group.frames[0].path), group.name + ".mask.png"))
    for p in cands:
        if os.path.exists(p):
            im = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
            if im is not None:
                return (im > 127).astype(np.uint8) * 255
    return None


# ---------------------------------------------------------------------------------------------
# PatchMatch completion
# ---------------------------------------------------------------------------------------------

def telea(img: np.ndarray, hole: np.ndarray, radius: int = 3) -> np.ndarray:
    """OpenCV Telea per channel.  cv2.inpaint on float32 assumes a 0..255 range (values in
    0..1 come back as garbage), so the data is scaled."""
    out = img.astype(np.float32).copy()
    m = hole.astype(np.uint8)
    for ch in range(out.shape[2]):
        out[..., ch] = cv2.inpaint(np.ascontiguousarray(out[..., ch]) * 255.0, m, radius, cv2.INPAINT_TELEA) / 255.0
    return out


# ---------------------------------------------------------------------------------------------
# exemplar-based completion
# ---------------------------------------------------------------------------------------------

def _offsets(patch: int) -> np.ndarray:
    r = patch // 2
    oy, ox = np.mgrid[-r:r + 1, -r:r + 1]
    return np.stack([oy.ravel(), ox.ravel()], 1)


DATA_ALPHA = 0.3   # priority = C * (D + alpha): larger alpha = weaker edge propagation
BATCH_MAX = 48     # target patches filled per iteration (non-overlapping)
UNKNOWN_W = 0.05   # weight of the unknown part of a target patch, compared with a smooth
                   # (Telea) prediction: stops "half matching" patches from pasting foreign content
CONF_FRAC = 0.7    # per iteration only fill front patches with confidence >= this x the maximum


def exemplar_inpaint(img: np.ndarray, hole: np.ndarray, patch: int = 9, max_side: int = 320,
                     ring: float = 1.0, seed: int = 0, max_sources: int = 30000) -> np.ndarray:
    """Fill ``hole`` of ``img`` (HxWx3 float32 in [0,1]); returns a new image."""
    rng = np.random.default_rng(seed)
    H0, W0 = hole.shape
    hole = hole.astype(bool)
    if not hole.any():
        return img
    s = min(1.0, max_side / max(H0, W0))
    if s < 1.0:
        size = (max(1, round(W0 * s)), max(1, round(H0 * s)))
        work = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
        hw = cv2.resize(hole.astype(np.float32), size, interpolation=cv2.INTER_AREA) > 0.01
    else:
        work, hw = img.astype(np.float32).copy(), hole.copy()
    work = telea(work, hw)  # smooth prediction of the hole (guides the unknown part of patches)
    r = patch // 2
    # pad so that patches at the crop border are defined (reflected content counts as known)
    work = cv2.copyMakeBorder(work, r, r, r, r, cv2.BORDER_REFLECT)
    hw = cv2.copyMakeBorder(hw.astype(np.uint8), r, r, r, r, cv2.BORDER_CONSTANT, value=0) > 0
    h, w = hw.shape
    off = _offsets(patch)
    filled = ~hw
    # candidate sources: fully known patches on the surface around the hole
    src = cv2.erode(filled.astype(np.uint8), np.ones((patch, patch), np.uint8),
                    borderType=cv2.BORDER_CONSTANT, borderValue=0) > 0
    src[:r] = src[h - r:] = False
    src[:, :r] = src[:, w - r:] = False
    if ring > 0:
        ys, xs = np.nonzero(hw)
        span = max(ys.max() - ys.min() + 1, xs.max() - xs.min() + 1)
        rad = int(max(3 * patch, ring * span))
        near = cv2.dilate(hw.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rad + 1, 2 * rad + 1))) > 0
        if (src & near).sum() >= 100:
            src &= near
    sy, sx = np.nonzero(src)
    if len(sy) < 10:
        return telea(img, hole)
    if len(sy) > max_sources:
        sel = rng.choice(len(sy), max_sources, replace=False)
        sy, sx = sy[sel], sx[sel]
    S = np.stack([sy, sx], 1)
    Smat = work[S[:, 0:1] + off[None, :, 0], S[:, 1:2] + off[None, :, 1]].reshape(len(S), -1)  # (M, P*P*3)
    Ssq = Smat * Smat
    conf = filled.astype(np.float32)
    src_of = -np.ones((h, w, 2), np.int32)
    k3 = np.ones((3, 3), np.uint8)
    while True:
        unf = ~filled
        if not unf.any():
            break
        front = unf & (cv2.dilate(filled.astype(np.uint8), k3) > 0)
        fy, fx = np.nonzero(front)
        if len(fy) == 0:
            break
        # priority = confidence x data term (isophote strength along the front normal)
        C = cv2.boxFilter(conf, -1, (patch, patch), normalize=True, borderType=cv2.BORDER_CONSTANT)
        gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        ok = cv2.erode(filled.astype(np.uint8), k3) > 0
        gx[~ok] = 0
        gy[~ok] = 0
        gx = cv2.dilate(np.abs(gx), k3) * np.sign(cv2.dilate(gx, k3) + cv2.erode(gx, k3))
        gy = cv2.dilate(np.abs(gy), k3) * np.sign(cv2.dilate(gy, k3) + cv2.erode(gy, k3))
        fm = cv2.GaussianBlur(filled.astype(np.float32), (0, 0), 1.0)
        nx = cv2.Sobel(fm, cv2.CV_32F, 1, 0, ksize=3)
        ny = cv2.Sobel(fm, cv2.CV_32F, 0, 1, ksize=3)
        nn = np.sqrt(nx * nx + ny * ny) + 1e-6
        D = np.abs(-gy * nx + gx * ny) / nn  # isophote = (-gy, gx)
        pri = C[fy, fx] * (D[fy, fx] + DATA_ALPHA)
        order = np.argsort(-pri)
        cmax = float(C[fy, fx].max())
        order = order[C[fy[order], fx[order]] >= CONF_FRAC * cmax]
        K = int(np.clip(len(fy) // (2 * patch), 1, BATCH_MAX))
        taken = np.zeros((h, w), bool)
        chosen = []
        for i in order:
            y, x = int(fy[i]), int(fx[i])
            if y < r or y >= h - r or x < r or x >= w - r or taken[y, x]:
                continue
            chosen.append((y, x, float(C[y, x])))
            taken[max(0, y - patch + 1):y + patch, max(0, x - patch + 1):x + patch] = True
            if len(chosen) >= K:
                break
        if not chosen:
            # remaining unfilled pixels too close to the padded border: diffuse them
            work = telea(work, unf)
            filled[:] = True
            break
        for y, x, c in chosen:
            py, px = y + off[:, 0], x + off[:, 1]
            km = filled[py, px]
            wv = np.repeat(np.where(km, 1.0, UNKNOWN_W), 3).astype(np.float32)
            tp = work[py, px].reshape(-1)
            d = Ssq @ wv - 2.0 * (Smat @ (wv * tp))
            b = int(np.argmin(d))
            by, bx = S[b]
            um = ~km
            ty, tx = py[um], px[um]
            vy, vx = by + off[um, 0], bx + off[um, 1]
            work[ty, tx] = work[vy, vx]
            conf[ty, tx] = c
            src_of[ty, tx, 0], src_of[ty, tx, 1] = vy, vx
            filled[ty, tx] = True
    work = work[r:h - r, r:w - r]
    src_of = src_of[r:h - r, r:w - r] - r
    # ---- transfer to full resolution through the source-offset field ------------------------
    out = img.astype(np.float32).copy()
    qy, qx = np.nonzero(hole)
    if s < 1.0:
        hs, ws = src_of.shape[:2]
        wy = np.clip(np.round((qy + 0.5) * s - 0.5).astype(np.int64), 0, hs - 1)
        wx = np.clip(np.round((qx + 0.5) * s - 0.5).astype(np.int64), 0, ws - 1)
        so = src_of[wy, wx]
        has = so[:, 0] >= 0
        fy_ = np.round(qy + (so[:, 0] - wy) / s).astype(np.int64)
        fx_ = np.round(qx + (so[:, 1] - wx) / s).astype(np.int64)
        inb = has & (fy_ >= 0) & (fy_ < H0) & (fx_ >= 0) & (fx_ < W0)
        inb[inb] &= ~hole[fy_[inb], fx_[inb]]
        out[qy[inb], qx[inb]] = img[fy_[inb], fx_[inb]]
        rest = ~inb  # no usable full-res source: take the upsampled working-resolution fill
        if rest.any():
            up = cv2.resize(work, (W0, H0), interpolation=cv2.INTER_LINEAR)
            out[qy[rest], qx[rest]] = up[qy[rest], qx[rest]]
            del up
        # soften seams between blocks copied with different offsets
        offy = np.zeros((H0, W0), np.float32)
        offx = np.zeros((H0, W0), np.float32)
        offy[qy, qx] = fy_ - qy
        offx[qy, qx] = fx_ - qx
        seam = np.zeros((H0, W0), bool)
        seam[:, 1:] |= (np.abs(np.diff(offy, axis=1)) + np.abs(np.diff(offx, axis=1))) > 0
        seam[1:, :] |= (np.abs(np.diff(offy, axis=0)) + np.abs(np.diff(offx, axis=0))) > 0
        seam = (cv2.dilate(seam.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & hole
        if seam.any():  # blur only the hole's bounding box (+ margin), every hole pixel is filled by now
            ys, xs = np.nonzero(seam)
            y0, y1 = max(0, ys.min() - 8), min(H0, ys.max() + 9)
            x0, x1 = max(0, xs.min() - 8), min(W0, xs.max() + 9)
            soft = cv2.GaussianBlur(out[y0:y1, x0:x1], (0, 0), 1.2)
            sm = seam[y0:y1, x0:x1]
            out[y0:y1, x0:x1][sm] = soft[sm]
    else:
        out[qy, qx] = work[qy, qx]
    out[~hole] = img[~hole]
    return np.clip(out, 0, 1)


# ---------------------------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------------------------

def remove_objects(img: np.ndarray, mask: np.ndarray, cfg: dict, seed: int = 0) -> tuple[np.ndarray, dict]:
    rcfg = cfg.get("modules", {}).get("remove", {})
    method = str(rcfg.get("method", "auto"))
    H, W = img.shape[:2]
    if mask.shape[:2] != (H, W):
        mask = cv2.resize(mask, (W, H), interpolation=cv2.INTER_NEAREST)
    m = mask > 127
    grow = max(2, int(round(float(rcfg.get("dilate_frac", 0.002)) * max(H, W))))
    m = cv2.dilate(m.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))) > 0
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
    info = {"components": int(n - 1), "pixels": int(m.sum()), "methods": []}
    for i in range(1, n):
        x0, y0, ww, hh, area = stats[i]
        span = max(ww, hh)
        thin = min(ww, hh) <= 10 or area < 120
        margin = int(max(48, 1.5 * span))
        a0, a1 = max(0, y0 - margin), min(H, y0 + hh + margin)
        c0, c1 = max(0, x0 - margin), min(W, x0 + ww + margin)
        crop = img[a0:a1, c0:c1].copy()
        hole = lab[a0:a1, c0:c1] == i
        use = "telea" if method == "telea" or (method == "auto" and thin) else "patch"
        if use == "telea":
            crop = telea(crop, hole, 5)
        else:
            crop = exemplar_inpaint(crop, hole, patch=int(rcfg.get("patch", 9)),
                                    max_side=int(rcfg.get("max_work_side", 320)), seed=seed + i)
        img[a0:a1, c0:c1][hole] = np.clip(crop[hole], 0, 1)
        info["methods"].append(use)
    return img, info

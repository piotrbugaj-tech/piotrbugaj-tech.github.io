"""Geometry: lens distortion (plumb-line), vertical lines, crop, resize back.

1. Radial distortion k1 (model r_u = r_d (1 + k1 r_d^2), r normalised by the half
   diagonal) is estimated without a lens profile: for candidate k1 the analysis
   image is undistorted and the total squared length of long line segments (LSD)
   is measured; straight lines are longest when the distortion is removed.
2. Verticals: near-vertical segments vote for a vertical vanishing point
   (RANSAC + least squares).  The camera rotation that sends this point to
   infinity (two-point perspective, like 'Upright Vertical') gives a homography
   H = K R K^-1 using the focal length from EXIF (35 mm equivalent) or a default.
3. Crop: the largest rectangle with the original aspect ratio inside the valid
   area; the result is resampled back to the input size (AutoHDR returns the
   upload's dimensions).  Distortion, rotation, crop and resize are composed into
   a single remap (one interpolation).
"""
from __future__ import annotations

import logging
import math

import cv2
import numpy as np

from . import accel
from .config import mode_of
from .imgutil import LUMA, resize_max

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# lines
# ---------------------------------------------------------------------------

_LSD = None


def detect_segments(gray8: np.ndarray, min_len: float) -> np.ndarray:
    """(N,4) array x1,y1,x2,y2 of segments longer than min_len pixels."""
    global _LSD
    if _LSD is None:
        _LSD = cv2.createLineSegmentDetector()
    segs = _LSD.detect(gray8)[0]
    if segs is None:
        return np.zeros((0, 4), np.float32)
    segs = segs.reshape(-1, 4)
    L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    return segs[L >= min_len]


def _gray8(img_disp: np.ndarray) -> np.ndarray:
    y = img_disp @ LUMA if img_disp.ndim == 3 else img_disp
    return np.clip(y * 255, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# distortion
# ---------------------------------------------------------------------------


def undistort_map(w: int, h: int, k1: float, scale: float = 1.0):
    """Remap grids producing the undistorted image (same size) from a distorted one."""
    cx, cy = (w - 1) / 2, (h - 1) / 2
    R = math.hypot(cx, cy)
    xs = (np.arange(w, dtype=np.float32) - cx) / R / scale
    ys = (np.arange(h, dtype=np.float32) - cy) / R / scale
    X, Y = np.meshgrid(xs, ys)
    Xd, Yd = _undistorted_to_distorted(X, Y, k1)
    return (Xd * R + cx).astype(np.float32), (Yd * R + cy).astype(np.float32)


def _undistorted_to_distorted(X, Y, k1, iters: int = 6):
    Xd, Yd = X.copy(), Y.copy()
    for _ in range(iters):
        r2 = Xd * Xd + Yd * Yd
        f = 1.0 + k1 * r2
        Xd, Yd = X / f, Y / f
    return Xd, Yd


def edge_chains(gray8: np.ndarray, min_len_frac: float = 0.08, max_chains: int = 400):
    """Long, nearly straight edge chains (lists of normalised points) for plumb-line fitting."""
    h, w = gray8.shape
    g = cv2.GaussianBlur(gray8, (0, 0), 1.2)
    e = (cv2.Canny(g, 30, 90) > 0).astype(np.uint8)
    # break chains at junctions (pixels with more than two edge neighbours)
    nb = cv2.filter2D(e, -1, np.ones((3, 3), np.float32), borderType=cv2.BORDER_CONSTANT) - e
    e[(e > 0) & (nb > 2)] = 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(e, connectivity=8)
    diag = math.hypot(w, h)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    R = math.hypot(cx, cy)
    chains = []
    order = np.argsort(-np.hypot(st[1:, cv2.CC_STAT_WIDTH], st[1:, cv2.CC_STAT_HEIGHT])) + 1
    for i in order[:max_chains * 3]:
        bw, bh = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        if math.hypot(bw, bh) < min_len_frac * diag:
            break
        x0, y0 = st[i, cv2.CC_STAT_LEFT], st[i, cv2.CC_STAT_TOP]
        ys, xs = np.nonzero(lab[y0:y0 + bh, x0:x0 + bw] == i)
        xs = xs + x0
        ys = ys + y0
        if len(xs) < 30:
            continue
        P = np.stack([(xs - cx) / R, (ys - cy) / R], 1)
        # must already be nearly straight (curvature from lens distortion is small)
        c = P - P.mean(0)
        ev = np.linalg.eigvalsh(c.T @ c / len(c))
        if ev[0] / max(ev[1], 1e-12) > 0.003:
            continue
        if len(P) > 400:
            P = P[np.linspace(0, len(P) - 1, 400).astype(int)]
        chains.append(P)
        if len(chains) >= max_chains:
            break
    return chains


def plumb_line_cost(chains, k1: float, trim: float = 0.2) -> float:
    """Trimmed mean of per-chain line-fit residuals (normalised units) after undistortion."""
    costs, wts = [], []
    for P in chains:
        r2 = (P * P).sum(1, keepdims=True)
        U = P * (1.0 + k1 * r2)
        c = U - U.mean(0)
        cov = c.T @ c / len(c)
        ev = np.linalg.eigvalsh(cov)
        L = math.sqrt(max(ev[1], 1e-12))
        costs.append(ev[0] / max(L * L, 1e-12))  # scale-free straightness
        wts.append(len(P))
    costs, wts = np.array(costs), np.array(wts, float)
    o = np.argsort(costs)
    keep = o[: max(1, int(len(o) * (1 - trim)))]
    return float((costs[keep] * wts[keep]).sum() / wts[keep].sum())


def estimate_distortion(gray8: np.ndarray, max_k1: float = 0.18, min_k1: float = 0.03,
                        min_gain: float = 0.05, min_chains: int = 12) -> tuple[float, dict]:
    """Radial k1 from plumb lines.  Estimates below ``min_k1`` are within the estimation error
    (measured |err| <= 0.02 on synthetic scenes) and are not applied; neither are estimates from
    few edges or at the end of the search range (curved objects - fabric, furniture - in a
    close-up are not distorted straight lines)."""
    chains = edge_chains(gray8)
    if len(chains) < max(6, min_chains):
        return 0.0, {"accepted": False, "reason": "few straight edges", "chains": len(chains)}
    ks = np.linspace(-max_k1 * 0.6, max_k1, 29)
    costs = np.array([plumb_line_cost(chains, k) for k in ks])
    i = int(np.argmin(costs))
    k_best = float(ks[i])
    if 0 < i < len(ks) - 1:
        y0, y1, y2 = costs[i - 1], costs[i], costs[i + 1]
        den = y0 - 2 * y1 + y2
        if abs(den) > 1e-18:
            k_best = float(ks[i] + 0.5 * (y0 - y2) / den * (ks[1] - ks[0]))
    base = plumb_line_cost(chains, 0.0)
    best = plumb_line_cost(chains, k_best)
    gain = 1.0 - best / max(base, 1e-18)  # fraction of curvature removed
    info = {"k1": k_best, "gain": gain, "chains": len(chains)}
    if i in (0, len(ks) - 1):
        return 0.0, {**info, "accepted": False, "reason": "minimum at the end of the search range"}
    if gain < min_gain or abs(k_best) < min_k1:
        return 0.0, {**info, "accepted": False}
    return k_best, {**info, "accepted": True}


# ---------------------------------------------------------------------------
# verticals
# ---------------------------------------------------------------------------


def _vertical_vp(segs: np.ndarray, w: int, h: int, max_angle: float = 25.0):
    """Robust vertical vanishing point in homogeneous coords (normalised by the image size)."""
    if len(segs) < 2:
        return None, 0, None
    dx = segs[:, 2] - segs[:, 0]
    dy = segs[:, 3] - segs[:, 1]
    ang = np.degrees(np.arctan2(np.abs(dx), np.abs(dy)))  # 0 = vertical
    L = np.hypot(dx, dy)
    sel = ang < max_angle
    segs, L = segs[sel], L[sel]
    if len(segs) < 2:
        return None, 0, None
    s = max(w, h)
    p1 = np.stack([(segs[:, 0] - w / 2) / s, (segs[:, 1] - h / 2) / s, np.ones(len(segs))], 1)
    p2 = np.stack([(segs[:, 2] - w / 2) / s, (segs[:, 3] - h / 2) / s, np.ones(len(segs))], 1)
    lines = np.cross(p1, p2)
    lines /= np.linalg.norm(lines[:, :2], axis=1, keepdims=True) + 1e-12
    mids = (p1 + p2) / 2
    dirs = (p2 - p1)[:, :2]
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True) + 1e-12

    def angular_err(v):
        # angle between segment direction and direction from its midpoint to v
        if abs(v[2]) < 1e-9:
            to = np.repeat(v[None, :2], len(mids), 0)
        else:
            to = v[None, :2] / v[2] - mids[:, :2]
        to = to / (np.linalg.norm(to, axis=1, keepdims=True) + 1e-12)
        c = np.abs((to * dirs).sum(1))
        return np.degrees(np.arccos(np.clip(c, -1, 1)))
    rng = np.random.default_rng(0)
    best_inl = None
    n = len(lines)
    wts = L / L.sum()
    for _ in range(min(500, n * (n - 1) // 2 + 1)):
        i, j = rng.choice(n, 2, replace=False, p=wts)
        v = np.cross(lines[i], lines[j])
        if np.linalg.norm(v) < 1e-12:
            continue
        v = v / np.linalg.norm(v)
        inl = angular_err(v) < 1.0
        if best_inl is None or (L[inl].sum() > L[best_inl].sum()):
            best_inl = inl
    if best_inl is None or best_inl.sum() < 2:
        return None, 0, None
    # least squares refinement: v minimising sum w (l . v)^2
    A = lines[best_inl] * np.sqrt(L[best_inl])[:, None]
    _, _, vt = np.linalg.svd(A)
    v = vt[-1]
    inl = angular_err(v) < 1.5
    return v, int(inl.sum()), float(np.median(angular_err(v)[inl])) if inl.any() else None


def focal_px(meta, w: int, h: int, default_35mm: float = 24.0) -> tuple[float, str]:
    diag = math.hypot(w, h)
    f35 = getattr(meta, "focal_35mm", None) if meta is not None else None
    if f35 and 10.0 <= float(f35) <= 300.0:  # implausible values (some phones write the real focal) are ignored
        return float(f35) / 43.27 * diag, "exif35"
    return default_35mm / 43.27 * diag, "default"


def rotation_from_vp(v_img: np.ndarray, f: float, strength: float):
    """Rotation R that makes the vertical direction parallel to the image y axis.
    v_img: homogeneous VP in pixel coordinates relative to the image centre."""
    d = np.array([v_img[0], v_img[1], v_img[2] * f], np.float64)
    if np.linalg.norm(d) < 1e-12:
        return np.eye(3), 0.0, 0.0
    d /= np.linalg.norm(d)
    if d[1] < 0:
        d = -d
    y = np.array([0.0, 1.0, 0.0])
    axis = np.cross(d, y)
    s = np.linalg.norm(axis)
    c = float(np.dot(d, y))
    ang = math.atan2(s, c)
    pitch = math.degrees(math.atan2(d[2], d[1]))  # tilt up/down
    roll = math.degrees(math.atan2(d[0], d[1]))   # rotation in the image plane
    if s < 1e-12:
        return np.eye(3), pitch, roll
    axis /= s
    R, _ = cv2.Rodrigues(axis * ang * strength)
    return R, pitch, roll


# ---------------------------------------------------------------------------
# crop
# ---------------------------------------------------------------------------


def largest_rect(poly: np.ndarray, aspect: float, w: int, h: int) -> tuple[float, float, float, float]:
    """Largest axis-aligned rectangle with the given aspect inside polygon (x0,y0,x1,y1)."""
    poly = poly.astype(np.float32).reshape(-1, 1, 2)
    cxp, cyp = poly.reshape(-1, 2).mean(0)

    def fits(cx, cy, hw):
        hh = hw / aspect
        pts = []
        for t in np.linspace(0, 1, 9):
            pts += [(cx - hw + 2 * hw * t, cy - hh), (cx - hw + 2 * hw * t, cy + hh),
                    (cx - hw, cy - hh + 2 * hh * t), (cx + hw, cy - hh + 2 * hh * t)]
        return all(cv2.pointPolygonTest(poly, (float(px), float(py)), False) >= 0 for px, py in pts)

    best = (0.0, cxp, cyp)
    for ox in np.linspace(-0.04, 0.04, 5) * w:
        for oy in np.linspace(-0.04, 0.04, 5) * h:
            cx, cy = cxp + ox, cyp + oy
            lo, hi = 0.0, w
            for _ in range(30):
                mid = (lo + hi) / 2
                if fits(cx, cy, mid):
                    lo = mid
                else:
                    hi = mid
            if lo > best[0]:
                best = (lo, cx, cy)
    hw, cx, cy = best
    hh = hw / aspect
    return cx - hw, cy - hh, cx + hw, cy + hh


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------


def _valid_polygon(W, H, k1, Hm):
    cx, cy = (W - 1) / 2, (H - 1) / 2
    Rn = math.hypot(cx, cy)
    t = np.linspace(0, 1, 64)
    border = np.concatenate([np.stack([t * (W - 1), np.zeros_like(t)], 1), np.stack([np.full_like(t, W - 1), t * (H - 1)], 1),
                             np.stack([(1 - t) * (W - 1), np.full_like(t, H - 1)], 1), np.stack([np.zeros_like(t), (1 - t) * (H - 1)], 1)])
    bx, by = (border[:, 0] - cx) / Rn, (border[:, 1] - cy) / Rn
    f = 1 + k1 * (bx * bx + by * by)
    ux, uy = bx * f * Rn + cx, by * f * Rn + cy
    return cv2.perspectiveTransform(np.stack([ux, uy], 1).reshape(-1, 1, 2).astype(np.float64), Hm).reshape(-1, 2)


def _crop_fraction(W, H, k1, Rm, f_full):
    cx, cy = (W - 1) / 2, (H - 1) / 2
    K = np.array([[f_full, 0, cx], [0, f_full, cy], [0, 0, 1]], np.float64)
    pts = _valid_polygon(W, H, k1, K @ Rm @ np.linalg.inv(K))
    x0, y0, x1, y1 = largest_rect(pts, W / H, W, H)
    return 1.0 - (x1 - x0) * (y1 - y0) / (W * H)


def correct(img: np.ndarray, cfg: dict, meta=None) -> tuple[np.ndarray, dict]:
    return apply(img, estimate(img, cfg, meta), cfg)


def estimate(img: np.ndarray, cfg: dict, meta=None) -> dict:
    """Distortion and camera rotation of a display image (analysis resolution).  Kept separate
    from ``apply`` so the optional modules (retouch, new sky) cannot change the geometry."""
    gcfg = cfg.get("geometry", {})
    if not gcfg.get("enabled", True):
        return {"enabled": False, "info": {"enabled": False}}
    H, W = img.shape[:2]
    side = int(cfg.get("runtime", {}).get("analysis_max_side", 1600))
    small, s = resize_max(img, side)
    g8 = _gray8(small)
    hs, ws = g8.shape
    info = {}
    # 1. distortion
    k1 = 0.0
    if mode_of(gcfg.get("distortion", "auto")) == "auto":
        k1, info["distortion"] = estimate_distortion(g8, float(gcfg.get("max_k1", 0.18)), float(gcfg.get("min_k1", 0.03)),
                                                     min_chains=int(gcfg.get("min_chains", 12)))
    if abs(k1) > 0:
        mx, my = undistort_map(ws, hs, k1)
        g8u = cv2.remap(g8, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    else:
        g8u = g8
    # 2. verticals
    Rm = np.eye(3)
    fpx_small, fsrc = focal_px(meta, ws, hs, float(gcfg.get("default_focal_35mm", 24.0)))
    info["focal"] = {"px_small": fpx_small, "source": fsrc}
    if gcfg.get("verticals", True):
        segs = detect_segments(g8u, 0.04 * hs)
        v, n_inl, err = _vertical_vp(segs, ws, hs)
        info["verticals"] = {"segments": int(len(segs)), "inliers": n_inl, "median_err_deg": err}
        if v is not None and n_inl >= int(gcfg.get("min_lines", 6)):
            s_n = max(ws, hs)
            v_px = np.array([v[0] * s_n, v[1] * s_n, v[2]])
            R, pitch, roll = rotation_from_vp(v_px, fpx_small, 1.0)
            info["verticals"].update({"pitch_deg": pitch, "roll_deg": roll})
            maxp, maxr = float(gcfg.get("max_pitch_deg", 12)), float(gcfg.get("max_roll_deg", 6))
            strength = float(gcfg.get("vertical_strength", 1.0))
            if abs(pitch) > 1.5 * maxp or abs(roll) > 1.5 * maxr:
                info["verticals"]["skipped"] = "angle beyond limits (wide-angle upward shot?)"
            else:
                strength *= min(1.0, maxp / max(abs(pitch), 1e-6), maxr / max(abs(roll), 1e-6))
                Rm, _, _ = rotation_from_vp(v_px, fpx_small, strength)
                info["verticals"]["applied_strength"] = strength
    return {"enabled": True, "k1": k1, "Rm": Rm, "f_small": fpx_small, "s": s, "size": (W, H), "info": info}


def apply(img: np.ndarray, plan: dict, cfg: dict) -> tuple[np.ndarray, dict]:
    """Undistort + rotate + crop + resize back, as estimated by ``estimate`` (full resolution)."""
    info = plan["info"]
    if not plan.get("enabled", True):
        return img, info
    gcfg = cfg.get("geometry", {})
    H, W = img.shape[:2]
    if (W, H) != tuple(plan["size"]):
        raise ValueError("geometry plan was estimated on an image of another size")
    k1, Rm, fpx_small, s = plan["k1"], plan["Rm"], plan["f_small"], plan["s"]
    # 3. compose: output pixel -> source pixel (full resolution)
    max_crop = float(gcfg.get("max_crop", 0.15))
    for _ in range(6):
        crop_try = _crop_fraction(W, H, k1, Rm, fpx_small / s)
        if crop_try <= max_crop or np.allclose(Rm, np.eye(3)):
            break
        rv, _ = cv2.Rodrigues(Rm)
        Rm, _ = cv2.Rodrigues(rv * 0.7)
        info.setdefault("verticals", {})["reduced_for_crop"] = True
    cx, cy = (W - 1) / 2, (H - 1) / 2
    f_full = fpx_small / s
    K = np.array([[f_full, 0, cx], [0, f_full, cy], [0, 0, 1]], np.float64)
    Hm = K @ Rm @ np.linalg.inv(K)  # undistorted source -> corrected
    if np.allclose(Hm, np.eye(3), atol=1e-9) and abs(k1) < 1e-9:
        return img, info
    Rn = math.hypot(cx, cy)
    pts = _valid_polygon(W, H, k1, Hm)
    if gcfg.get("crop", True):
        x0, y0, x1, y1 = largest_rect(pts, W / H, W, H)
    else:
        x0, y0, x1, y1 = 0, 0, W - 1, H - 1
    crop_frac = 1.0 - (x1 - x0) * (y1 - y0) / (W * H)
    info["crop_fraction"] = float(crop_frac)
    out_w, out_h = (W, H) if gcfg.get("resize_back", True) else (int(round(x1 - x0)), int(round(y1 - y0)))
    Hinv = np.linalg.inv(Hm)
    out = np.empty((out_h, out_w, 3), np.float32)
    strip = 512
    xs_o = x0 + (np.arange(out_w, dtype=np.float64) + 0.5) * (x1 - x0) / out_w - 0.5
    for r0 in range(0, out_h, strip):
        r1 = min(out_h, r0 + strip)
        ys_o = y0 + (np.arange(r0, r1, dtype=np.float64) + 0.5) * (y1 - y0) / out_h - 0.5
        X, Y = np.meshgrid(xs_o, ys_o)
        den = Hinv[2, 0] * X + Hinv[2, 1] * Y + Hinv[2, 2]
        ux = (Hinv[0, 0] * X + Hinv[0, 1] * Y + Hinv[0, 2]) / den
        uy = (Hinv[1, 0] * X + Hinv[1, 1] * Y + Hinv[1, 2]) / den
        Xn, Yn = (ux - cx) / Rn, (uy - cy) / Rn
        Xd, Yd = _undistorted_to_distorted(Xn, Yn, k1) if abs(k1) > 0 else (Xn, Yn)
        mx = (Xd * Rn + cx).astype(np.float32)
        my = (Yd * Rn + cy).astype(np.float32)
        out[r0:r1] = accel.cv(cv2.remap, img, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    out = np.clip(out, 0, 1)
    log.info("geometry: k1=%.3f, pitch %.2f°, roll %.2f°, crop %.1f%%", k1,
             info.get("verticals", {}).get("pitch_deg", 0), info.get("verticals", {}).get("roll_deg", 0), 100 * crop_frac)
    return out, info

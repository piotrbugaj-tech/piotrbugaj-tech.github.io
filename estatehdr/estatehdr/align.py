"""Frame alignment for handheld brackets.

For each frame a homography to the reference is estimated at analysis
resolution on exposure-normalised log-luminance (so different exposures look
alike), using SIFT + RANSAC, refined with ECC and validated against the
identity.  Translation-only MTB (Ward 2003) is the fallback.  Transforms map
reference pixel coordinates to frame pixel coordinates at full resolution.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from .imgutil import luminance

log = logging.getLogger(__name__)


def _norm_log(img: np.ndarray, exposure: float, lo: float, hi: float):
    y = luminance(img) / max(exposure, 1e-9)
    valid = (img.max(-1) < 0.92) & (luminance(img) > 0.004)
    ly = np.log2(np.maximum(y, 1e-6))
    g = np.clip((ly - lo) / (hi - lo), 0, 1)
    return (g * 255).astype(np.uint8), valid


def _ncc(a, b, mask):
    if mask.sum() < 50:
        return -1.0
    x = a[mask].astype(np.float32)
    y = b[mask].astype(np.float32)
    x -= x.mean()
    y -= y.mean()
    d = np.sqrt((x * x).sum() * (y * y).sum())
    return float((x * y).sum() / d) if d > 0 else -1.0


def _grad(img8):
    g = img8.astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.GaussianBlur(np.sqrt(gx * gx + gy * gy), (0, 0), 1.0)


def _scale_h(H: np.ndarray, s: float) -> np.ndarray:
    """Convert a homography estimated on images scaled by s to full resolution."""
    S = np.diag([s, s, 1.0])
    return np.linalg.inv(S) @ H @ S


def estimate_transform(ref_small: np.ndarray, ref_exp: float, mov_small: np.ndarray, mov_exp: float,
                       cfg: dict) -> tuple[np.ndarray, dict]:
    """Homography mapping ref coords -> moving-frame coords (analysis resolution)."""
    model = cfg.get("model", "homography")
    # common log-luminance window
    yr = np.log2(np.maximum(luminance(ref_small) / ref_exp, 1e-6))
    lo, hi = np.percentile(yr, 1), np.percentile(yr, 99.5)
    hi = max(hi, lo + 1)
    a8, va = _norm_log(ref_small, ref_exp, lo - 1, hi + 1)
    b8, vb = _norm_log(mov_small, mov_exp, lo - 1, hi + 1)
    info = {"method": "identity"}
    H = np.eye(3)
    # --- feature matching ---------------------------------------------------
    try:
        sift = cv2.SIFT_create(nfeatures=int(cfg.get("features", 4000)), contrastThreshold=0.02)
        ka, da = sift.detectAndCompute(a8, (va.astype(np.uint8) * 255))
        kb, db = sift.detectAndCompute(b8, (vb.astype(np.uint8) * 255))
        if da is not None and db is not None and len(ka) > 20 and len(kb) > 20:
            matcher = cv2.BFMatcher(cv2.NORM_L2)
            raw = matcher.knnMatch(da, db, k=2)
            good = [m for m, n in (p for p in raw if len(p) == 2) if m.distance < 0.75 * n.distance]
            if len(good) >= 12:
                pa = np.float32([ka[m.queryIdx].pt for m in good])
                pb = np.float32([kb[m.trainIdx].pt for m in good])
                if model == "translation":
                    d = np.median(pb - pa, 0)
                    Hc = np.array([[1, 0, d[0]], [0, 1, d[1]], [0, 0, 1]], np.float64)
                    inl = np.linalg.norm(pb - (pa + d), axis=1) < 2.0
                elif model == "affine":
                    A, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=2.0)
                    Hc = np.vstack([A, [0, 0, 1]]) if A is not None else None
                    inl = inl.ravel().astype(bool) if inl is not None else None
                else:
                    Hc, inl = cv2.findHomography(pa, pb, cv2.RANSAC, 2.0, maxIters=4000, confidence=0.999)
                    inl = inl.ravel().astype(bool) if inl is not None else None
                if Hc is not None and inl is not None and inl.sum() >= 10:
                    H = Hc
                    resid = np.median(np.abs(pb[inl] - pa[inl]), 0)
                    info = {"method": "sift", "matches": len(good), "inliers": int(inl.sum()),
                            "median_shift_px": float(np.linalg.norm(resid))}
    except cv2.error as exc:
        log.debug("SIFT alignment failed: %s", exc)
    # --- ECC refinement (on gradients; robust to remaining photometric differences)
    if cfg.get("ecc", True):
        try:
            ga, gb = _grad(a8), _grad(b8)
            # ECC's warp maps template (reference) coords to input (moving) coords, like H
            warp = (H / H[2, 2]).astype(np.float32)
            mode = {"translation": cv2.MOTION_TRANSLATION, "affine": cv2.MOTION_AFFINE}.get(model, cv2.MOTION_HOMOGRAPHY)
            if mode != cv2.MOTION_HOMOGRAPHY:
                warp = warp[:2]
            crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5)
            _, warp = cv2.findTransformECC(ga, gb, warp, mode, crit, vb.astype(np.uint8) * 255, 5)
            if warp.shape[0] == 2:
                warp = np.vstack([warp, [0, 0, 1]])
            H_ecc = warp.astype(np.float64)
            H_ecc /= H_ecc[2, 2]
            H = H_ecc
            info["ecc"] = True
            if info["method"] == "identity":
                info["method"] = "ecc"
        except cv2.error as exc:
            info["ecc"] = False
            log.debug("ECC refinement failed: %s", exc)
    # --- validation against identity ----------------------------------------
    h, w = a8.shape
    warped = cv2.warpPerspective(b8, H, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    vmask = cv2.warpPerspective(vb.astype(np.uint8), H, (w, h), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP).astype(bool)
    m = va & vmask
    score = _ncc(_grad(a8), _grad(warped), m)
    score_id = _ncc(_grad(a8), _grad(b8), va & vb)
    info["ncc"] = score
    info["ncc_identity"] = score_id
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
    disp = np.linalg.norm(cv2.perspectiveTransform(corners, H).reshape(-1, 2) - corners.reshape(-1, 2), axis=1)
    info["corner_disp_px"] = float(disp.max())
    if score < score_id - 0.01 or disp.max() > float(cfg.get("max_shift_frac", 0.08)) * max(w, h):
        # alignment made things worse or is implausibly large -> MTB translation fallback
        H = _mtb(ref_small, ref_exp, mov_small, mov_exp)
        info["method"] = "mtb-fallback"
    elif disp.max() < float(cfg.get("still_px", 0.25)):
        H = np.eye(3)
        info["method"] = "still"
    return H, info


def _mtb(ref_small, ref_exp, mov_small, mov_exp) -> np.ndarray:
    a = np.clip(luminance(ref_small) / ref_exp * 0.18 / max(np.median(luminance(ref_small) / ref_exp), 1e-6), 0, 1)
    b = np.clip(luminance(mov_small) / mov_exp * 0.18 / max(np.median(luminance(mov_small) / mov_exp), 1e-6), 0, 1)
    a8 = (np.power(a, 1 / 2.2) * 255).astype(np.uint8)
    b8 = (np.power(b, 1 / 2.2) * 255).astype(np.uint8)
    mtb = cv2.createAlignMTB(6, 4, True)
    shift = mtb.calculateShift(a8, b8)  # shift to apply to b to match a
    dx, dy = -float(shift[0]), -float(shift[1])
    return np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], np.float64)


def align_series(series, cfg: dict) -> list[dict]:
    """Estimates a full-resolution homography for every frame (stored on the frame)."""
    ref = series.frames[series.ref]
    h_full = ref.shape[0]
    s = ref.small.shape[0] / h_full
    infos = []
    for i, f in enumerate(series.frames):
        if i == series.ref or not cfg.get("enabled", True):
            f.homography = np.eye(3)
            infos.append({"frame": f.meta.name, "method": "reference" if i == series.ref else "disabled"})
            continue
        H, info = estimate_transform(ref.small, ref.exposure, f.small, f.exposure, cfg)
        f.homography = _scale_h(H, s)
        info["frame"] = f.meta.name
        infos.append(info)
        log.info("[%s] align %s: %s (%.2f px, ncc %.3f vs %.3f)", series.name, f.meta.name, info["method"],
                 info.get("corner_disp_px", 0) / s, info.get("ncc", 0), info.get("ncc_identity", 0))
    return infos


def warp_to_reference(img: np.ndarray, H: np.ndarray, out_shape, interp=cv2.INTER_LINEAR) -> tuple[np.ndarray, np.ndarray | None]:
    """Resample a frame into reference coordinates; returns (image, valid-mask or None)."""
    if H is None or np.allclose(H, np.eye(3), atol=1e-6):
        return img, None
    h, w = out_shape[:2]
    out = cv2.warpPerspective(img, H, (w, h), flags=interp | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
    valid = cv2.warpPerspective(np.ones(img.shape[:2], np.uint8), H, (w, h),
                                flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP, borderValue=0)
    return out, valid.astype(bool)

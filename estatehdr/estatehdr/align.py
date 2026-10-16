"""Frame alignment for handheld brackets.

For each frame a transform to the reference is estimated at analysis
resolution on exposure-normalised log-luminance (so different exposures look
alike), using SIFT + RANSAC, refined with ECC and validated against the
identity, then polished by a second ECC stage at (up to) full resolution.
Translation-only MTB (Ward 2003) is the fallback.  Transforms map reference
pixel coordinates to frame pixel coordinates at full resolution.

Motion model (``align.model``): translation / similarity / affine / homography,
or ``auto`` (default): the affine model, unless the frame's data clearly
support perspective.  For that the affine and the homography ECC estimates
(both dense, on the same images) are compared on the SIFT matches, an
independent, local measurement of the same motion that neither estimate is
fitted to: the homography is chosen when the matches favour it with a
likelihood ratio above ``auto_llr`` (log, default 3 = 20:1) and the two models
differ by more than ``auto_min_px`` at a corner (full resolution).  A dense
homography fit alone is not trusted, because ECC turns systematic differences
between exposures (clipping / noise-floor contours, moving objects) into a
spurious perspective term more easily than into an affine one.  Both ECC stages
then run in the chosen model (``info["model"]``).
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from .imgutil import chmax, luminance

log = logging.getLogger(__name__)

MODELS = ("translation", "similarity", "affine", "homography", "auto")
# ECC has no similarity model: it runs affine and is projected back to a similarity
_ECC_MODE = {"translation": cv2.MOTION_TRANSLATION, "similarity": cv2.MOTION_AFFINE,
             "affine": cv2.MOTION_AFFINE, "homography": cv2.MOTION_HOMOGRAPHY}


def _norm_log(img: np.ndarray, exposure: float, lo: float, hi: float):
    y = luminance(img) / max(exposure, 1e-9)
    valid = (chmax(img) < 0.92) & (luminance(img) > 0.004)
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


def _ecc(ga, gb, H: np.ndarray, model: str, mask: np.ndarray, gauss: int) -> np.ndarray:
    """One ECC run from H in ``model``; raises cv2.error when ECC does not converge.
    ECC's warp maps template (reference) coords to input (moving) coords, like H."""
    mode = _ECC_MODE.get(model, cv2.MOTION_HOMOGRAPHY)
    warp = (H / H[2, 2]).astype(np.float32)
    if mode != cv2.MOTION_HOMOGRAPHY:
        warp = warp[:2]
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 1e-5)
    _, warp = cv2.findTransformECC(ga, gb, warp, mode, crit, mask, gauss)
    if warp.shape[0] == 2:
        warp = np.vstack([warp, [0, 0, 1]])
    Hn = warp.astype(np.float64)
    if model == "similarity":
        a, b, c, d = Hn[0, 0], Hn[0, 1], Hn[1, 0], Hn[1, 1]
        pp, qq = (a + d) / 2, (c - b) / 2
        Hn[:2, :2] = [[pp, -qq], [qq, pp]]
    return Hn / Hn[2, 2]


def _fit_matches(pa: np.ndarray, pb: np.ndarray, model: str):
    """RANSAC fit of ``model`` to point matches pa -> pb: (H or None, inlier mask or None)."""
    if model == "translation":
        d = np.median(pb - pa, 0)
        H = np.array([[1, 0, d[0]], [0, 1, d[1]], [0, 0, 1]], np.float64)
        return H, np.linalg.norm(pb - (pa + d), axis=1) < 2.0
    if model in ("similarity", "affine"):
        fit = cv2.estimateAffinePartial2D if model == "similarity" else cv2.estimateAffine2D
        A, inl = fit(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=2.0)
        H = np.vstack([A, [0, 0, 1]]) if A is not None else None
    else:
        H, inl = cv2.findHomography(pa, pb, cv2.RANSAC, 2.0, maxIters=4000, confidence=0.999)
    return H, (inl.ravel().astype(bool) if inl is not None else None)


def _corner_diff(H1: np.ndarray, H2: np.ndarray, w: int, h: int) -> float:
    """Largest distance between where H1 and H2 map the image corners."""
    c = np.float64([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
    return float(np.linalg.norm(cv2.perspectiveTransform(c, H1) - cv2.perspectiveTransform(c, H2), axis=2).max())


def perspective_evidence(HA: np.ndarray, HH: np.ndarray, pa: np.ndarray, pb: np.ndarray, thr: float = 2.0) -> dict:
    """How strongly point matches pa -> pb favour the homography HH over the affine HA.

    Both transforms are fixed (estimated densely by ECC, not fitted to these matches), so this is a
    test between two fully specified hypotheses on independent data and needs no complexity penalty
    (as in cross-validation).  Matches within ``thr`` px of either prediction are used; with r the
    match residual under HA and D = HH(p) - HA(p) the predicted difference, the Gaussian
    log-likelihood ratio is llr = (sum|r|^2 - sum|r - D|^2) / (2 sigma^2), where sigma^2 is the
    residual variance about the best fit r ~ beta * D (beta ~ 1 when the matches follow HH,
    ~ 0 when they follow HA).  Few matches or matches only where the models agree give llr ~ 0."""
    out = {"matches": 0, "llr": 0.0, "beta": None}
    if pa is None or len(pa) < 8:
        return out
    qa = cv2.perspectiveTransform(pa.reshape(-1, 1, 2).astype(np.float64), HA).reshape(-1, 2)
    qh = cv2.perspectiveTransform(pa.reshape(-1, 1, 2).astype(np.float64), HH).reshape(-1, 2)
    inl = np.minimum(np.linalg.norm(qa - pb, axis=1), np.linalg.norm(qh - pb, axis=1)) < thr
    n = int(inl.sum())
    out["matches"] = n
    if n < 8:
        return out
    r = (pb - qa)[inl]
    D = (qh - qa)[inl]
    dd = float((D * D).sum())
    beta = float((r * D).sum() / max(dd, 1e-12))
    sig2 = max(float(((r - beta * D) ** 2).sum()) / (2 * n - 1), 1e-6)
    out.update(llr=float(((r * r).sum() - ((r - D) ** 2).sum()) / (2 * sig2)), beta=beta,
               sigma_px=float(np.sqrt(sig2)), model_diff_rms_px=float(np.sqrt(dd / n)))
    return out


def estimate_transform(ref_small: np.ndarray, ref_exp: float, mov_small: np.ndarray, mov_exp: float,
                       cfg: dict, scale: float = 1.0) -> tuple[np.ndarray, dict]:
    """Homography mapping ref coords -> moving-frame coords (analysis resolution).

    ``scale``: analysis / full resolution, so that ``auto_min_px`` is measured at full resolution.
    ``info["model"]`` is the motion model used (the per-frame choice for ``model: auto``)."""
    model = cfg.get("model", "auto")
    base = "affine" if model == "auto" else model
    # common log-luminance window
    yr = np.log2(np.maximum(luminance(ref_small) / ref_exp, 1e-6))
    lo, hi = np.percentile(yr, 1), np.percentile(yr, 99.5)
    hi = max(hi, lo + 1)
    a8, va = _norm_log(ref_small, ref_exp, lo - 1, hi + 1)
    b8, vb = _norm_log(mov_small, mov_exp, lo - 1, hi + 1)
    info = {"method": "identity"}
    H = np.eye(3)
    pa = pb = None
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
                Hc, inl = _fit_matches(pa, pb, base)
                if Hc is not None and inl is not None and inl.sum() >= 10:
                    H = Hc
                    resid = np.median(np.abs(pb[inl] - pa[inl]), 0)
                    info = {"method": "sift", "matches": len(good), "inliers": int(inl.sum()),
                            "median_shift_px": float(np.linalg.norm(resid))}
    except cv2.error as exc:
        log.debug("SIFT alignment failed: %s", exc)
    # --- ECC refinement (on gradients; robust to remaining photometric differences)
    if cfg.get("ecc", True):
        if cfg.get("ecc_input", "grad") == "log":
            ga = cv2.GaussianBlur(a8.astype(np.float32), (0, 0), 1.0)
            gb = cv2.GaussianBlur(b8.astype(np.float32), (0, 0), 1.0)
        else:
            ga, gb = _grad(a8), _grad(b8)
        mask = vb.astype(np.uint8) * 255
        try:
            H = _ecc(ga, gb, H, base, mask, 5)
            info["ecc"] = True
            if info["method"] == "identity":
                info["method"] = "ecc"
        except cv2.error as exc:
            info["ecc"] = False
            log.debug("ECC refinement failed: %s", exc)
        if model == "auto" and info["ecc"]:
            # perspective only when the (independent) feature matches support it
            h, w = a8.shape
            sel = {}
            try:
                HH = _ecc(ga, gb, H, "homography", mask, 5)
                sel = perspective_evidence(H, HH, pa, pb)
                sel["corner_diff_px"] = _corner_diff(H, HH, w, h) / scale
                if (sel["llr"] > float(cfg.get("auto_llr", 3.0))
                        and sel["corner_diff_px"] > float(cfg.get("auto_min_px", 0.5))):
                    H = HH
                    info["model"] = "homography"
            except cv2.error as exc:
                log.debug("homography ECC failed: %s", exc)
            info["model_select"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in sel.items()}
    info.setdefault("model", base)
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
    small_motion = disp.max() < 3.0
    worse = score < score_id - (0.04 if small_motion else 0.01)
    if worse or disp.max() > float(cfg.get("max_shift_frac", 0.08)) * max(w, h):
        # alignment made things worse or is implausibly large -> MTB translation fallback
        H = _mtb(ref_small, ref_exp, mov_small, mov_exp)
        info["method"] = "mtb-fallback"
        info["model"] = base
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


def _tile_signal(img_lin: np.ndarray, exposure: float):
    """Exposure-normalised log luminance of a linear tile and its validity mask."""
    y = luminance(img_lin)
    valid = (chmax(img_lin) < 0.92) & (y > 0.003)
    ly = np.log2(np.maximum(y / max(exposure, 1e-9), 1e-6)).astype(np.float32)
    return ly, valid


def _fit_correction(p: np.ndarray, q: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, str]:
    """Pick the simplest of translation / similarity / affine that explains p -> q.

    A richer model is accepted only if it lowers the weighted RMS residual clearly;
    this avoids extrapolation errors when the usable tiles are clustered."""
    W = w / w.sum()

    def rms(M):
        r = (np.hstack([p, np.ones((len(p), 1))]) @ M[:2].T) - q
        return float(np.sqrt((W * (r ** 2).sum(1)).sum()))
    t = (W[:, None] * (q - p)).sum(0)
    T = np.array([[1, 0, t[0]], [0, 1, t[1]], [0, 0, 1]], np.float64)
    best, name, err = T, "translation", rms(T)
    if len(p) >= 4:
        # weighted similarity (Umeyama without reflection)
        mp = (W[:, None] * p).sum(0)
        mq = (W[:, None] * q).sum(0)
        pc, qc = p - mp, q - mq
        a = (W * (pc[:, 0] * qc[:, 0] + pc[:, 1] * qc[:, 1])).sum()
        b = (W * (pc[:, 0] * qc[:, 1] - pc[:, 1] * qc[:, 0])).sum()
        n = (W * (pc ** 2).sum(1)).sum()
        if n > 0:
            ca, sb = a / n, b / n
            R = np.array([[ca, -sb], [sb, ca]])
            tt = mq - R @ mp
            S = np.array([[ca, -sb, tt[0]], [sb, ca, tt[1]], [0, 0, 1]], np.float64)
            e = rms(S)
            if e < 0.8 * err - 0.02:
                best, name, err = S, "similarity", e
    if len(p) >= 8:
        X = np.hstack([p, np.ones((len(p), 1))])
        sw = np.sqrt(W)[:, None]
        coef, *_ = np.linalg.lstsq(X * sw, q * sw, rcond=None)
        A = np.vstack([coef.T, [0, 0, 1]])
        e = rms(A)
        if e < 0.7 * err - 0.02:
            best, name, err = A, "affine", e
    return best, name


def refine_full_res(ref, mov, H: np.ndarray, cfg: dict) -> tuple[np.ndarray, dict]:
    """Sub-pixel refinement at full resolution: phase correlation on a grid of tiles,
    then a least-squares affine correction (applied in reference coordinates)."""
    h, w = ref.shape[:2]
    tile = int(cfg.get("tile", 256))
    grid = int(cfg.get("tile_grid", 6))
    if min(h, w) < 2 * tile:
        return H, {"tiles": 0}
    win = cv2.createHanningWindow((tile, tile), cv2.CV_32F)
    ys = np.linspace(tile // 2 + 8, h - tile // 2 - 8, grid).astype(int)
    xs = np.linspace(tile // 2 + 8, w - tile // 2 - 8, grid + 1).astype(int)
    pts, shifts, wts = [], [], []
    ref_img = ref.decoded.image
    for cy in ys:
        for cx in xs:
            y0, x0 = cy - tile // 2, cx - tile // 2
            rt = ref_img[y0:y0 + tile, x0:x0 + tile]
            rt = ref.lut[rt] if ref.lut is not None else rt.astype(np.float32) / ref.decoded.max_value
            T = np.array([[1, 0, x0], [0, 1, y0], [0, 0, 1]], np.float64)
            mt = cv2.warpPerspective(mov.decoded.image, H @ T, (tile, tile),
                                     flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)
            mt = mov.lut[mt] if mov.lut is not None else mt.astype(np.float32) / mov.decoded.max_value
            a, va = _tile_signal(rt, ref.exposure)
            b, vb = _tile_signal(mt, mov.exposure)
            # only (almost) fully valid tiles: a shared fill mask would create identical
            # artificial edges in both tiles and bias the correlation towards zero shift
            if va.mean() < 0.97 or vb.mean() < 0.97:
                continue
            if np.median(luminance(rt)) < 0.02 or np.median(luminance(mt)) < 0.02:
                continue  # too dark: log-gradients would be mostly noise
            ga = _grad(a * 64.0)
            gb = _grad(b * 64.0)
            if ga.std() < 0.05:
                continue
            (dx, dy), resp = cv2.phaseCorrelate(ga, gb, win)
            if resp < float(cfg.get("min_response", 0.15)) or abs(dx) > tile / 8 or abs(dy) > tile / 8:
                continue
            pts.append((cx, cy))
            shifts.append((dx, dy))
            wts.append(resp)
    info = {"tiles": len(pts)}
    if len(pts) < 3:
        return H, info
    p = np.float64(pts)
    d = np.float64(shifts)
    wv = np.float64(wts)
    # robust: iteratively reject tiles inconsistent with the fitted correction
    keep = np.ones(len(p), bool)
    C = np.eye(3)
    for _ in range(4):
        if keep.sum() < 3:
            break
        C, model = _fit_correction(p[keep], p[keep] + d[keep], wv[keep])
        pred = (np.hstack([p, np.ones((len(p), 1))]) @ C[:2].T) - p
        r = np.linalg.norm(pred - d, axis=1)
        thr = max(0.35, 3.0 * 1.4826 * np.median(r[keep]))
        new_keep = r < thr
        if (new_keep == keep).all():
            break
        keep = new_keep
    info["model"] = model if keep.sum() >= 3 else "none"
    info["inlier_tiles"] = int(keep.sum())
    if keep.sum() < 3:
        return H, info
    # sanity: the correction must stay small (this stage only polishes the coarse estimate)
    corners = np.float64([[0, 0], [w, 0], [w, h], [0, h]])
    cdisp = np.linalg.norm((np.hstack([corners, np.ones((4, 1))]) @ C[:2].T) - corners, axis=1).max()
    info["correction_px"] = float(cdisp)
    if cdisp > float(cfg.get("max_refine_px", 4.0)):
        info["rejected"] = True
        return H, info
    info["mean_shift_px"] = float(np.linalg.norm(d[keep], axis=1).mean())
    return H @ C, info


def _fine_image(f, side: int):
    """Linear float image of a frame at max side `side` (computed from the full-res data)."""
    img = f.decoded.image
    h, w = img.shape[:2]
    sc = min(1.0, side / max(h, w))
    if sc < 1.0:
        img = cv2.resize(img, (round(w * sc), round(h * sc)), interpolation=cv2.INTER_AREA)
    lin = f.lut[img] if f.lut is not None else img.astype(np.float32) / f.decoded.max_value
    return lin, sc


def ecc_refine(ref_img, ref_exp, mov_img, mov_exp, H: np.ndarray, model: str) -> tuple[np.ndarray, bool]:
    """Dense ECC refinement on gradient magnitude of exposure-normalised log luminance."""
    yr = np.log2(np.maximum(luminance(ref_img) / ref_exp, 1e-6))
    lo, hi = np.percentile(yr, 1), np.percentile(yr, 99.5)
    hi = max(hi, lo + 1)
    a8, va = _norm_log(ref_img, ref_exp, lo - 1, hi + 1)
    b8, vb = _norm_log(mov_img, mov_exp, lo - 1, hi + 1)
    try:
        return _ecc(_grad(a8), _grad(b8), H, model, vb.astype(np.uint8) * 255, 3), True
    except cv2.error:
        return H, False


def align_series(series, cfg: dict) -> list[dict]:
    """Estimates a full-resolution homography for every frame (stored on the frame)."""
    ref = series.frames[series.ref]
    h_full = ref.shape[0]
    s = ref.small.shape[0] / h_full
    infos = []
    ref_fine = None
    for i, f in enumerate(series.frames):
        if i == series.ref or not cfg.get("enabled", True):
            f.homography = np.eye(3)
            infos.append({"frame": f.meta.name, "method": "reference" if i == series.ref else "disabled"})
            continue
        H, info = estimate_transform(ref.small, ref.exposure, f.small, f.exposure, cfg, s)
        Hf = _scale_h(H, s)
        fine_side = int(cfg.get("fine_max_side", 3200))
        if fine_side > ref.small.shape[1] and info["method"] not in ("still",) and cfg.get("fine_ecc", True):
            if ref_fine is None:
                ref_fine = _fine_image(ref, fine_side)
            mov_img, sc = _fine_image(f, fine_side)
            S = np.diag([sc, sc, 1.0])
            Hs = S @ Hf @ np.linalg.inv(S)
            # the fine stage keeps the frame's model (auto: the per-frame choice of the coarse stage)
            Hs2, ok = ecc_refine(ref_fine[0], ref.exposure, mov_img, f.exposure, Hs, info["model"])
            if ok:
                d = np.abs(cv2.perspectiveTransform(np.float32([[[0, 0]], [[mov_img.shape[1], mov_img.shape[0]]]]), Hs2)
                           - cv2.perspectiveTransform(np.float32([[[0, 0]], [[mov_img.shape[1], mov_img.shape[0]]]]), Hs)).max()
                if d < 4.0:  # fine stage only polishes
                    Hf = np.linalg.inv(S) @ Hs2 @ S
                    info["fine_ecc_change_px"] = float(d / sc)
        if cfg.get("refine_full", False) and info["method"] not in ("still",):
            for _ in range(int(cfg.get("refine_iters", 3))):
                H_new, rinfo = refine_full_res(ref, f, Hf, cfg)
                info["refine"] = rinfo
                if rinfo.get("rejected") or "mean_shift_px" not in rinfo:
                    break
                Hf = H_new
                if rinfo["mean_shift_px"] < 0.05:
                    break
        f.homography = Hf
        info["frame"] = f.meta.name
        infos.append(info)
        log.info("[%s] align %s: %s, %s (%.2f px, ncc %.3f vs %.3f)", series.name, f.meta.name, info["method"],
                 info.get("model", "-"), info.get("corner_disp_px", 0) / s, info.get("ncc", 0), info.get("ncc_identity", 0))
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

"""Loading a bracket series: decode, linearise, estimate relative exposures.

Linearisation (per frame, by its own encoding; a series mixing encodings gets a warning):
  * RAW / float TIFF -> already linear;
  * JPEG / PNG / 8-bit TIFF -> inverse camera response.  By default the sRGB
    curve; with ``crf: auto`` a two-parameter family (sRGB + S-curve strength,
    gamma tweak) is fitted to the bracket so that exposure-normalised frames
    agree with each other (the response is invisible in one frame, but
    measurable across exposures).  Without EXIF the S-curve strength is fitted
    to the frames' brightness transfer functions with the ratios unknown (the
    gamma tweak is not identifiable then and stays at sRGB's);
  * 16-bit TIFF of unknown encoding -> linear vs. sRGB decided by agreement of
    pixel ratios with EXIF exposure ratios, without EXIF by which decoding makes
    the frames differ by one constant ratio, a linear verdict confirmed by the
    darkest frame's histogram (a pure power law looks linear to that test);
    single frame: histogram heuristic.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from .config import mode_of
from .imgutil import chmax, luminance, resize_max, linear_to_srgb
from .io.metadata import FrameMeta
from .io.reader import DecodeError, Decoded, decode

log = logging.getLogger(__name__)


@dataclass
class Frame:
    meta: FrameMeta
    decoded: Decoded
    exposure: float = 1.0  # relative exposure (reference frame = 1)
    lut: np.ndarray | None = None  # inverse response LUT for integer data (len = max_value+1)
    small: np.ndarray | None = None  # linear float32 analysis copy

    @property
    def shape(self):
        return self.decoded.image.shape

    def linear(self) -> np.ndarray:
        """Full-resolution linear float32 image (allocated on demand)."""
        img = self.decoded.image
        if self.lut is not None:
            return self.lut[img]
        return img.astype(np.float32) * np.float32(1.0 / self.decoded.max_value)


@dataclass
class Series:
    name: str
    frames: list
    ref: int = 0
    crf: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    @property
    def shape(self):
        return self.frames[self.ref].shape


# ---------------------------------------------------------------------------
# camera response
# ---------------------------------------------------------------------------


def _s_curve(y: np.ndarray, k: float) -> np.ndarray:
    return np.clip(y + k * 2.0 * y * (1 - y) * (2 * y - 1), 0, 1)


def inverse_crf_lut(n: int, k: float = 0.0, g: float = 1.0) -> np.ndarray:
    """LUT mapping code value (0..n-1) to linear light for the response
    y = S_k(sRGB(x^(1/g)))."""
    x = np.linspace(0, 1, 8192, dtype=np.float64)
    fwd = _s_curve(linear_to_srgb(x.astype(np.float32)).astype(np.float64), k)
    fwd = np.maximum.accumulate(fwd)  # monotonic
    fwd[-1] = 1.0
    codes = np.linspace(0, 1, n)
    lin = np.interp(codes, fwd + np.arange(fwd.size) * 1e-12, x)
    lin = np.clip(lin, 0, 1) ** g
    return lin.astype(np.float32)


def _pairs_inconsistency(smalls, exposures, lut_fn, n_codes, maxv) -> float:
    """Mean squared log-difference between exposure-normalised frames."""
    lut = lut_fn
    errs = []
    for i in range(len(smalls) - 1):
        for j in range(i + 1, len(smalls)):
            a = lut[np.clip((smalls[i] * (n_codes - 1)).round().astype(np.int32), 0, n_codes - 1)]
            b = lut[np.clip((smalls[j] * (n_codes - 1)).round().astype(np.int32), 0, n_codes - 1)]
            ya, yb = a.mean(-1), b.mean(-1)
            ok = (chmax(smalls[i]) < 0.92) & (chmax(smalls[j]) < 0.92) & (ya > 0.004) & (yb > 0.004)
            if ok.sum() < 100:
                continue
            d = np.log2(ya[ok] / exposures[i]) - np.log2(yb[ok] / exposures[j])
            errs.append(np.mean(np.minimum(d * d, 1.0)))
    return float(np.mean(errs)) if errs else float("inf")


def fit_crf(codes_small: list[np.ndarray], exposures: list[float], samples: int = 60000) -> tuple[float, float, float]:
    """Grid search of (k, g) minimising cross-exposure inconsistency. Returns (k, g, score).

    Works on a fixed random subset of pixel positions (the same for every frame)."""
    rng = np.random.default_rng(0)
    h, w = codes_small[0].shape[:2]
    idx = rng.choice(h * w, size=min(samples, h * w), replace=False)
    sub = [c.reshape(-1, 3)[idx][None] for c in codes_small]  # (1,N,3) keeps the image API
    best = (0.0, 1.0, float("inf"))
    n = 1024
    for k in (-0.1, -0.05, 0.0, 0.04, 0.08, 0.12, 0.16, 0.2, 0.25, 0.3):
        for g in (0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.16):
            lut = inverse_crf_lut(n, k, g)
            s = _pairs_inconsistency(sub, exposures, lut, n, 1.0)
            if s < best[2]:
                best = (k, g, s)
    return best


# ---------------------------------------------------------------------------
# camera response without EXIF: comparametric fit
# ---------------------------------------------------------------------------
# Without exposure metadata the response and the exposure ratios are estimated together.  For a
# response F (code = F(linear)) any two frames i, j obey the brightness transfer function
# c_j = F(r_ij * F^-1(c_i)) (Mann's comparametric equation; Grossberg & Nayar).  Ambiguities:
#   * scale: F^-1 -> a F^-1 leaves every ratio unchanged; anchored by F^-1(1) = 1 (as with EXIF);
#   * exponential: F^-1 -> (F^-1)^c together with r_ij -> r_ij^c explains the pixels exactly as well.
#     In the curve family used here that is precisely the exponent g, so g cannot be recovered from
#     the pixels and is fixed at the sRGB value g = 1 (JPEGs are encoded for sRGB displays).  The
#     S-curve strength k is not a power law; the shape of the transfer functions identifies it.
# The misfit is measured in code values with each pair's ratio profiled out (median log ratio under
# the candidate curve).  It is invariant to the exponential ambiguity, so no degenerate solution can
# lower it (a log-domain dispersion would favour any curve that shrinks all log ratios).  The same
# criterion decides linear vs sRGB for untagged 16-bit TIFF.


def _sample_codes(codes: list[np.ndarray], samples: int = 40000, seed: int = 0) -> list[np.ndarray]:
    """Code values (0..1) of every frame at one fixed random set of positions; channels pooled."""
    h, w = codes[0].shape[:2]
    idx = np.random.default_rng(seed).choice(h * w, size=min(samples, h * w), replace=False)
    return [c.reshape(-1, 3)[idx].ravel().astype(np.float32) for c in codes]


def _transfer_pairs(sub: list[np.ndarray], lo: float, hi: float = 0.92, max_gap: int = 2,
                    levels: int = 1000, min_n: int = 50) -> list[tuple[int, int, np.ndarray, np.ndarray]]:
    """Brightness transfer functions by histogram (rank) matching: (i, j, c_i(q), c_j(q)) = code
    values of frames i and j at the same quantiles q, for frames at most ``max_gap`` apart in
    brightness order (j brighter), kept where both are well exposed (lo < code < hi).  A monotone
    response maps ranks to ranks, so this equals the co-located relation without needing the
    frames aligned: hand-held shifts, parallax and small moving objects barely change histograms,
    while co-located pixels at shifted edges would dominate the misfit.  Pairs with < min_n
    levels in the well-exposed range are dropped."""
    order = np.argsort([float(np.mean(s)) for s in sub])
    srt = [np.sort(s) for s in sub]
    out = []
    for a in range(len(order)):
        for b in range(a + 1, min(a + 1 + max_gap, len(order))):
            i, j = int(order[a]), int(order[b])
            ranks = np.linspace(0, srt[i].size - 1, levels).round().astype(np.int64)
            ci, cj = srt[i][ranks], srt[j][ranks]
            ok = (ci > lo) & (ci < hi) & (cj > lo) & (cj < hi)
            if int(ok.sum()) >= min_n:
                out.append((i, j, ci[ok], cj[ok]))
    return out


def comparametric_score(pairs, lut: np.ndarray, cap: float = 0.05) -> tuple[float, dict]:
    """Mean squared code-value misfit (each term truncated at ``cap``) of the transfer functions
    implied by the inverse response ``lut`` (code grid 0..1 -> linear), symmetric in i and j.
    Returns (score, {(i, j): log2 exposure_j / exposure_i})."""
    grid = np.linspace(0.0, 1.0, lut.size)
    inv = lut.astype(np.float64) + np.arange(lut.size) * 1e-9  # strictly increasing for the forward map
    errs, logr = [], {}
    for i, j, ci, cj in pairs:
        li, lj = np.interp(ci, grid, inv), np.interp(cj, grid, inv)
        m = float(np.median(np.log2(np.maximum(lj, 1e-9) / np.maximum(li, 1e-9))))
        pj = np.interp(li * 2.0 ** m, inv, grid)
        pi = np.interp(lj * 2.0 ** -m, inv, grid)
        e = np.minimum(np.abs(cj - pj), cap) ** 2 + np.minimum(np.abs(ci - pi), cap) ** 2
        errs.append(0.5 * float(np.mean(e)))
        logr[(i, j)] = m
    return (float(np.mean(errs)) if errs else float("inf")), logr


K_RANGE = (-0.1, 0.3)  # S-curve strengths of the response family (the range fit_crf searches)


def fit_crf_blind(codes_small: list[np.ndarray], lo: float = 0.03) -> dict:
    """S-curve strength k (g fixed at 1, see above) from the pixels alone: grid over K_RANGE in
    0.01 steps, then a parabolic refinement.  Returns {"k", "fit_score", "srgb_score", "pairs"};
    k = 0 without usable frame pairs."""
    pairs = _transfer_pairs(_sample_codes(codes_small), lo)
    if not pairs:
        return {"k": 0.0, "fit_score": float("inf"), "srgb_score": float("inf"), "pairs": 0}
    ks = np.round(np.arange(K_RANGE[0], K_RANGE[1] + 1e-9, 0.01), 4)
    s = [comparametric_score(pairs, inverse_crf_lut(1024, k, 1.0))[0] for k in ks]
    b = int(np.argmin(s))
    k = float(ks[b])
    if 0 < b < len(ks) - 1:
        den = s[b - 1] - 2 * s[b] + s[b + 1]
        if den > 0:
            k = float(np.clip(k + 0.5 * (s[b - 1] - s[b + 1]) / den * 0.01, ks[b - 1], ks[b + 1]))
    k = round(k, 4)
    return {"k": k, "fit_score": comparametric_score(pairs, inverse_crf_lut(1024, k, 1.0))[0],
            "srgb_score": s[int(np.argmin(np.abs(ks)))], "pairs": len(pairs)}


def classify_encoding_blind(codes_small: list[np.ndarray], margin: float = 0.8) -> tuple[str | None, dict]:
    """Linear vs sRGB for an untagged 16-bit bracket from the pixels alone: under the right decoding
    two frames differ by one constant ratio at every intensity.  Both decodings are scored with the
    comparametric misfit (ratios profiled out, so the larger log ratios of the sRGB decoding are no
    handicap); one that is clearly better (score ratio < margin) wins.  Returns (choice, or None
    when undecided, and the scores).  "linear" means *linear or a pure power law* (Adobe RGB 2.2,
    ProPhoto / Apple RGB 1.8 without their profile): x -> x^(1/g) is invisible to this test
    (exponential ambiguity), only sRGB's linear toe makes "srgb" identifiable.  untagged_encoding()
    resolves that with the darkest frame's histogram."""
    pairs = _transfer_pairs(_sample_codes(codes_small), lo=0.01)
    if not pairs:
        return None, {}
    s_lin = comparametric_score(pairs, np.linspace(0, 1, 1024, dtype=np.float32))[0]
    s_srgb = comparametric_score(pairs, inverse_crf_lut(1024))[0]
    info = {"linear_score": s_lin, "srgb_score": s_srgb}
    if s_lin < margin * s_srgb:
        return "linear", info
    if s_srgb < margin * s_lin:
        return "srgb", info
    return None, info


LINEAR_DARKEST_MAX = 0.06  # darkest frame's median code above this -> not linear (see untagged_encoding)
HISTOGRAM_LINEAR_MAX = 0.12  # single frame: median code above this -> sRGB


def untagged_encoding(codes_small: list[np.ndarray]) -> tuple[str, str, dict]:
    """Linear vs sRGB for a 16-bit TIFF series of unknown encoding without EXIF.  Returns (choice,
    decided_by, info).

    Brackets: cross-frame consistency (classify_encoding_blind) first.  An "srgb" verdict is final.
    A "linear" one only says "linear or a pure power law" - the two explain the pixels equally well
    and differ by the exposure ratios (a 2 EV step of gamma 2.2 data reads as 0.9 EV), so the absolute
    level decides: every bracket has a frame at or below the metered exposure, and that frame is dark
    in linear light (metered median ~0.10, -2 EV -> 0.025) but not after a power law (0.025^(1/2.2) =
    0.19, ^(1/1.8) = 0.13).  Linear is kept only if the darkest frame's median code (channel mean)
    is < LINEAR_DARKEST_MAX, else sRGB ("histogram(darkest)").  The same rule decides when
    consistency is undecided.  sRGB is not exact for power-law data (the exponent is not
    identifiable from the pixels; with its toe sRGB acts like g ~2.0) but much closer: -2/0/+2 EV
    off by 0.14-0.29 EV (gamma 2.2) / 0.23-0.36 EV (1.8), against 1.09 / 0.89 EV read as linear.

    Threshold: with the darkest frame u EV under a metering that puts the linear median at 0.10,
    linear is kept for u > log2(0.10 / t) and a power law g caught for u < log2(0.10 / t^g):
      t = 0.06: linear u > 0.74, gamma 1.8 u < 3.98, gamma 2.2 u < 5.6
      t = 0.08: linear u > 0.32, gamma 1.8 u < 3.24, gamma 2.2 u < 4.7
      t = 0.10: linear u > 0,    gamma 1.8 u < 2.66, gamma 2.2 u < 4.0
    Generated untagged brackets (9 scenes - 3 synthetic, 6 HDR+ radiances -, metered median 0.05 /
    0.10 / 0.18, brackets -1/0/+1, -2/0/+2, -3/0/+3, -4..+4, 0/+2), darkest-frame median code:
    linear 0.003-0.048 for -2/0/+2 and wider, 0.025-0.096 for -1/0/+1, 0.05-0.19 for 0/+2; gamma
    1.8 / ProPhoto 0.086-0.18 (-2/0/+2), 0.058-0.12 (-3/0/+3), 0.039-0.084 (-4..+4); gamma 2.2
    0.134-0.25 (-2/0/+2), 0.070-0.13 (-4..+4).  t = 0.06 keeps every linear -2/0/+2 and wider
    bracket at any metering (-1/0/+1 up to metering 0.10, 0/+2 only at 0.05) and decodes every
    power-law bracket up to -2/0/+2 as sRGB, -3/0/+3 and -4..+4 too for gamma 2.2, for gamma 1.8
    from metering 0.10 (-3/0/+3) / at 0.18 (-4..+4).  Brackets with max error > 0.5 EV, of 135
    linear / 405 power-law ones: t = 0.05: 37 / 62, 0.06: 27 / 78, 0.08: 27 / 83, 0.10: 14 / 134
    (old pooled-median rule: 62 / 60; linear verdict taken as final: 0 / 351).  On this grid 0.08
    keeps no more linear brackets than 0.06 and misses more power-law ones; for a log-uniform
    metering 0.05-0.18 and a bracket mix of 10 / 50 / 15 / 25 % (-1/0/+1 / -2 / -3 / -4 EV
    darkest), 0.08 is better only when > 84 % of such untagged brackets are linear, and stripped
    ProPhoto / Adobe RGB exports with wide window brackets are a realistic source.  The bedroom
    linear bracket (darkest 0.04) keeps a 0.6 EV margin.  Failure modes: a linear bracket whose
    darkest frame is not under-exposed (0/+2, or -1/0/+1 of a bright scene) is read as sRGB (~2x
    the EV steps); a power-law bracket reaching ~4 EV (1.8) / ~5.6 EV (2.2) under metering is read
    as linear (0.56x / 0.45x the EV steps), and caught ones at -3/-4 EV are still 0.25-0.8 EV off.

    Single frame: no consistency to measure - median code < HISTOGRAM_LINEAR_MAX -> linear."""
    if len(codes_small) < 2:
        med = float(np.median(codes_small[0].mean(-1)))
        return ("linear" if med < HISTOGRAM_LINEAR_MAX else "srgb"), "histogram", {}
    choice, info = classify_encoding_blind(codes_small)
    dark = min(float(np.median(c.mean(-1))) for c in codes_small)
    info = {**info, "darkest_median": dark}
    if choice == "srgb":
        return "srgb", "pixel-consistency", info
    if dark < LINEAR_DARKEST_MAX:
        return "linear", ("pixel-consistency" if choice == "linear" else "histogram(darkest)"), info
    return "srgb", "histogram(darkest)", info


BLIND_ACCEPT = 0.5  # the fitted curve must remove more than half of plain sRGB's misfit


def _blind_response(codes_small: list[np.ndarray]) -> tuple[tuple[float, float], dict]:
    """(k, g) and crf info for sRGB-type frames without EXIF.  g = 1 (not identifiable, see above).
    Regularised towards sRGB: the fitted k is kept only when the family clearly describes the
    camera - misfit < BLIND_ACCEPT x the sRGB misfit and k inside K_RANGE, not on its bound.  A
    response outside the family (film / scanner black offset, local tone mapping, flare) leaves
    much of the misfit unexplained and pushes k to a bound, where the fitted ratios are worse than
    plain sRGB's (Debevec's Memorial Church: 1-4 EV off instead of <= 0.2)."""
    fit = fit_crf_blind(codes_small)
    inside = K_RANGE[0] + 0.01 < fit["k"] < K_RANGE[1] - 0.01
    accepted = bool(inside and fit["fit_score"] < BLIND_ACCEPT * fit["srgb_score"])
    k = fit["k"] if accepted else 0.0
    # fit_score is the misfit of the curve applied (= srgb_score when the fit is rejected); the
    # candidate's own misfit is fitted_score
    return (k, 1.0), {"model": "srgb+s-curve", "k": k, "g": 1.0, "fit": "pixels only (no EXIF), g fixed",
                      "accepted": accepted, "k_fitted": fit["k"], "fitted_score": fit["fit_score"],
                      "fit_score": fit["fit_score"] if accepted else fit["srgb_score"],
                      "srgb_score": fit["srgb_score"], "pairs": fit["pairs"]}


# ---------------------------------------------------------------------------
# exposure estimation
# ---------------------------------------------------------------------------


def pixel_exposure_ratio(a: np.ndarray, b: np.ndarray) -> tuple[float | None, int]:
    """Robust ratio exposure(b)/exposure(a) from linear analysis images."""
    ya, yb = luminance(a), luminance(b)
    ok = (chmax(a) < 0.9) & (chmax(b) < 0.9) & (ya > 0.01) & (yb > 0.01)
    n = int(ok.sum())
    if n < 100:
        return None, n
    return float(np.exp(np.median(np.log(yb[ok] / ya[ok])))), n


def choose_reference(smalls: list[np.ndarray], brightness: list[float] | None = None) -> int:
    """Middle exposure (AutoHDR's colour reference), unless it is much worse exposed
    than the best frame."""
    scores = []
    for s in smalls:
        y = luminance(s)
        scores.append(float(((y > 0.02) & (chmax(s) < 0.9)).mean()))
    if brightness is None:
        brightness = [float(np.median(luminance(s))) for s in smalls]
    order = np.argsort(brightness)
    mid = int(order[(len(order) - 1) // 2]) if len(order) % 2 == 0 else int(order[len(order) // 2])
    best = int(np.argmax(scores))
    if scores[mid] >= 0.6 * scores[best]:
        return mid
    return best


# ---------------------------------------------------------------------------
# series loading
# ---------------------------------------------------------------------------


def load_series(name: str, metas: list[FrameMeta], cfg: dict) -> Series:
    icfg = cfg.get("input", {})
    rcfg = cfg.get("runtime", {})
    analysis_side = int(rcfg.get("analysis_max_side", 1600))
    frames: list[Frame] = []
    warnings = []
    raw_cfg = dict(icfg.get("raw", {}))
    if len(metas) == 1 and raw_cfg.get("fbdd_single", True):
        raw_cfg["fbdd"] = True  # a single exposure has no merge to average noise away
    bad, icc = [], {}
    for m in metas:
        try:
            d = decode(m.path, m.orientation, raw_cfg=raw_cfg)
        except DecodeError as exc:  # a corrupt frame must not sink the readable rest of the series
            bad.append(f"{m.name} ({exc})")
            log.warning("[%s] skipping undecodable frame %s: %s", name, m.name, exc)
            if len(bad) == len(metas):
                raise
            continue
        frames.append(Frame(m, d))
        if d.icc:
            icc.setdefault(d.icc, []).append(m.name)
    for desc, names in icc.items():
        warnings.append(f"converted from ICC profile '{desc}' to sRGB: {', '.join(names)}")
        log.warning("[%s] embedded ICC profile '%s' (not sRGB) converted to sRGB: %s", name, desc, ", ".join(names))
    if bad:
        warnings.append(f"skipped undecodable frame(s): {'; '.join(bad)}")
    # all frames must share one size (portrait/landscape mixes are separate series)
    shapes = {f.shape[:2] for f in frames}
    if len(shapes) > 1:
        base = max(shapes, key=lambda s: sum(f.shape[:2] == s for f in frames))
        dropped = [f.meta.name for f in frames if f.shape[:2] != base]
        frames = [f for f in frames if f.shape[:2] == base]
        warnings.append(f"dropped frames with different size: {', '.join(dropped)}")
    # sort by brightness order (EXIF exposure value if present)
    evs = [f.meta.exposure_value for f in frames]
    have_ev = all(e is not None for e in evs)

    encodings = {f.decoded.encoding for f in frames}
    smalls_codes = []
    for f in frames:
        sm, _ = resize_max(f.decoded.image, analysis_side)
        smalls_codes.append(sm.astype(np.float32) / np.float32(f.decoded.max_value))

    # relative exposures from EXIF (if any)
    if have_ev:
        ref_ev = np.median(evs)
        exif_exp = [2.0 ** (e - ref_ev) for e in evs]
    else:
        exif_exp = None

    # each frame is linearised according to its own encoding (RAW+JPEG mixes must not push the
    # linear RAW data through the inverse sRGB curve); parameters are fitted per encoding
    mode = mode_of(icfg.get("crf", "auto"))
    params, infos = {}, {}
    for enc in sorted(encodings):
        idx = [i for i, f in enumerate(frames) if f.decoded.encoding == enc]
        codes = [smalls_codes[i] for i in idx]
        exps = [exif_exp[i] for i in idx] if exif_exp else None
        if enc == "linear":
            params[enc], infos[enc] = None, {"model": "linear"}
        elif enc == "unknown":
            # 16-bit TIFF of unknown encoding: decide linear vs sRGB
            if exps and len(idx) > 1:
                sub = [c[::4, ::4] for c in codes]
                score_lin = _pairs_inconsistency(sub, exps, np.linspace(0, 1, 1024, dtype=np.float32), 1024, 1)
                score_srgb = _pairs_inconsistency(sub, exps, inverse_crf_lut(1024), 1024, 1)
                choice = "linear" if score_lin < score_srgb else "srgb"
                infos[enc] = {"model": choice, "decided_by": "exif-consistency"}
            else:
                # no EXIF: cross-frame consistency of the two decodings (a bracket's linear frames
                # are often bright enough to fool a pooled histogram rule), a linear verdict
                # confirmed by the darkest frame (power laws look linear); histogram for one frame
                choice, by, scores = untagged_encoding(codes)
                infos[enc] = {"model": choice, "decided_by": by, **({"consistency": scores} if scores else {})}
            params[enc] = (0.0, 1.0) if choice == "srgb" else None
            if choice == "srgb" and mode == "auto" and not exps and len(idx) >= 2:
                params[enc], fit = _blind_response(codes)  # sRGB-encoded: tone curve as for JPEG
                infos[enc] = {**infos[enc], **fit}
        else:
            k, g = 0.0, 1.0
            if mode == "auto" and exps and len(idx) >= 2:
                k, g, score = fit_crf(codes, exps)
                base = _pairs_inconsistency([c[::4, ::4] for c in codes], exps, inverse_crf_lut(1024), 1024, 1)
                accepted = bool(score < 0.9 * base)  # keep plain sRGB unless the fit is clearly better
                infos[enc] = {"model": "srgb+s-curve", "k": k if accepted else 0.0, "g": g if accepted else 1.0,
                              "accepted": accepted, "k_fitted": k, "g_fitted": g, "fitted_score": score,
                              "fit_score": score if accepted else base, "srgb_score": base}  # as in _blind_response
                if not accepted:
                    k, g = 0.0, 1.0
            elif mode == "auto" and len(idx) >= 2:
                (k, g), infos[enc] = _blind_response(codes)  # no EXIF: response from the pixels alone
            else:
                infos[enc] = {"model": "srgb"}
            params[enc] = (k, g)
    if len(infos) == 1:
        crf_info = next(iter(infos.values()))
    else:
        crf_info = {"model": "mixed", "per_encoding": infos}
        warnings.append(f"series mixes pixel encodings ({', '.join(f'{f.meta.name}: {f.decoded.encoding}' for f in frames)})"
                        " - e.g. RAW with JPEG frames; each frame linearised by its own encoding")

    for f, sc in zip(frames, smalls_codes):
        p = params[f.decoded.encoding]
        if p is not None:
            n = int(f.decoded.max_value) + 1
            f.lut = inverse_crf_lut(n, *p)
            idx = np.clip(np.round(sc * (n - 1)).astype(np.int32), 0, n - 1)
            f.small = f.lut[idx]
        else:
            f.small = sc

    ref = choose_reference([f.small for f in frames])
    # relative exposures along the brightness order: each step (adjacent frames, most pixels in
    # common) uses the EXIF ratio, unless the pixels clearly disagree (> 0.4 EV on >= 2000 px)
    if have_ev:
        order = sorted(range(len(frames)), key=lambda i: evs[i])
    else:
        order = sorted(range(len(frames)), key=lambda i: float(np.mean(frames[i].small)))
    cum = {order[0]: 1.0}
    for a, b in zip(order[:-1], order[1:]):
        r_pix, n = pixel_exposure_ratio(frames[a].small, frames[b].small)
        r_exif = exif_exp[b] / exif_exp[a] if exif_exp else None
        if r_exif is not None:
            step = r_exif
            if r_pix is not None and n >= 2000 and abs(np.log2(r_exif / r_pix)) > 0.4:
                warnings.append(f"{frames[b].meta.name}: EXIF exposure ratio {r_exif:.3f} disagrees with "
                                f"pixels {r_pix:.3f}; using pixels")
                step = r_pix
        elif r_pix is not None:
            step = r_pix
        else:
            # nothing reliable in common (e.g. extreme brackets): fall back to mean brightness
            step = max(float(np.mean(frames[b].small)), 1e-6) / max(float(np.mean(frames[a].small)), 1e-6)
            warnings.append(f"{frames[b].meta.name}: exposure estimated from mean brightness")
        cum[b] = cum[a] * step
    for i, f in enumerate(frames):
        f.exposure = cum[i] / cum[ref]
    s = Series(name=name, frames=frames, ref=ref, crf=crf_info, warnings=warnings)
    log.info("[%s] %d frame(s), ref=%s, exposures=%s, crf=%s", name, len(frames), frames[ref].meta.name,
             ", ".join(f"{np.log2(f.exposure):+.2f}EV" for f in frames), crf_info.get("model"))
    return s

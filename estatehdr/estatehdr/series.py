"""Loading a bracket series: decode, linearise, estimate relative exposures.

Linearisation (per frame, by its own encoding; a series mixing encodings gets a warning):
  * RAW / float TIFF -> already linear;
  * JPEG / PNG / 8-bit TIFF -> inverse camera response.  By default the sRGB
    curve; with ``crf: auto`` a two-parameter family (sRGB + S-curve strength,
    gamma tweak) is fitted to the bracket so that exposure-normalised frames
    agree with each other (the response is invisible in one frame, but
    measurable across exposures);
  * 16-bit TIFF of unknown encoding -> linear vs. sRGB decided by agreement of
    pixel ratios with EXIF exposure ratios (single frame: histogram heuristic).
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
            else:
                med = float(np.median(np.concatenate([c.mean(-1).ravel() for c in codes])))
                choice = "linear" if med < 0.12 else "srgb"
            infos[enc] = {"model": choice, "decided_by": "exif-consistency" if exps else "histogram"}
            params[enc] = (0.0, 1.0) if choice == "srgb" else None
        else:
            mode = mode_of(icfg.get("crf", "auto"))
            k, g = 0.0, 1.0
            if mode == "auto" and exps and len(idx) >= 2:
                k, g, score = fit_crf(codes, exps)
                base = _pairs_inconsistency([c[::4, ::4] for c in codes], exps, inverse_crf_lut(1024), 1024, 1)
                if not (score < 0.9 * base):  # keep plain sRGB unless the fit is clearly better
                    k, g = 0.0, 1.0
                infos[enc] = {"model": "srgb+s-curve", "k": k, "g": g, "fit_score": score, "srgb_score": base}
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

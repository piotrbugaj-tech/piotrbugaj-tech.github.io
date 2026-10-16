"""Core stages: exposures/CRF, alignment, merge + deghosting, windows, white balance,
tone mapping, denoise, lens, geometry - against synthetic ground truth."""
import os

import cv2
import numpy as np
import pytest
import tifffile

from estatehdr import align, color, denoise, geometry, lens, merge, tonemap, windows
from estatehdr.imgutil import LUMA, luminance, resize_rows, rgb_to_lab
from estatehdr.io.metadata import read_metadata
from estatehdr.series import load_series

from .conftest import labels


def _series(synth, cfg, files):
    metas = [read_metadata(os.path.join(synth["input"], f)) for f in files]
    return load_series("t", metas, cfg)


def _gt_radiance(synth, scene):
    return tifffile.imread(os.path.join(synth["root"], "gt", scene, "radiance_capture.tif")).astype(np.float32)


# --- exposures / camera response --------------------------------------------------------------
def test_exposures_and_crf(synth, cfg):
    s = _series(synth, cfg, synth["manifest"]["series"][0]["files"])  # EVs -4..+4
    ev = np.log2([f.exposure for f in s.frames])
    assert np.allclose(np.diff(np.sort(ev)), 2.0, atol=0.15)
    assert s.frames[s.ref].exposure == pytest.approx(1.0)


def test_exposures_without_exif(synth, cfg):
    s = _series(synth, cfg, synth["manifest"]["extras"]["noexif_incomplete"])  # -2, 0 EV
    ev = sorted(np.log2([f.exposure for f in s.frames]))
    assert abs((ev[1] - ev[0]) - 2.0) < 0.35


# --- alignment --------------------------------------------------------------------------------
def test_estimate_transform_recovers_shift(synth, cfg):
    s = _series(synth, cfg, ["IMG_0002.jpg"])
    ref = s.frames[0].small
    M = np.array([[1, 0, 3.4], [0, 1, -2.1]], np.float32)
    mov = cv2.warpAffine(ref, M, (ref.shape[1], ref.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    H, info = align.estimate_transform(ref, 1.0, mov, 1.0, cfg["align"])
    # H maps reference coordinates to moving-frame coordinates
    p = H @ np.array([200.0, 150.0, 1.0])
    assert np.allclose(p[:2] / p[2], [203.4, 147.9], atol=0.5), info


@pytest.mark.parametrize("scene", ["bedroom", "living_room"])
def test_alignment_vs_ground_truth(synth, cfg, scene):
    """Estimated frame homographies vs the generator's (handheld bedroom shifts ~13 px)."""
    import json
    with open(os.path.join(synth["root"], "gt", scene, "params.json")) as fh:
        p = json.load(fh)
    s = _series(synth, cfg, [f["file"] for f in p["frames"]])
    align.align_series(s, cfg["align"])
    Hgt = [np.array(f["homography"]) for f in p["frames"]]
    pts = np.array([[x, y, 1.0] for x in np.linspace(20, 460, 6) for y in np.linspace(20, 300, 5)]).T
    for i, f in enumerate(s.frames):
        E = Hgt[i] @ np.linalg.inv(Hgt[s.ref])  # GT: reference coords -> frame coords
        a, b = f.homography @ pts, E @ pts
        err = np.hypot(*(a[:2] / a[2] - b[:2] / b[2]))
        assert err.mean() < 0.8 and err.max() < 2.0, (f.meta.name, err.mean(), err.max())


# --- merge -------------------------------------------------------------------------------------
def test_merge_matches_scene_radiance(synth, cfg):
    s = _series(synth, cfg, synth["manifest"]["series"][0]["files"])
    align.align_series(s, cfg["align"])
    m = merge.merge_series(s, cfg)
    gt = _gt_radiance(synth, "living_room")
    lab = labels(synth, "living_room")
    ok = (m.clipped < 0.01) & (luminance(gt) > np.percentile(luminance(gt), 5)) & (lab != 4)
    ok = cv2.erode(ok.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    r = np.log2(np.maximum(luminance(m.radiance), 1e-6)) - np.log2(np.maximum(luminance(gt), 1e-6))
    r = r[ok] - np.median(r[ok])
    # linear radiance up to one global scale: small spread of the log ratio
    assert np.percentile(np.abs(r), 90) < 0.25
    assert m.stats["dynamic_range_ev"] > 6


def test_deghosting_moving_object(synth, cfg):
    s = _series(synth, cfg, synth["manifest"]["series"][1]["files"])  # moving object
    align.align_series(s, cfg["align"])
    m = merge.merge_series(s, cfg)
    assert m.stats["ghost_fraction"] > 0.001
    assert m.ghost is not None


# --- windows -----------------------------------------------------------------------------------
def test_window_detection_iou(synth, cfg):
    s = _series(synth, cfg, synth["manifest"]["series"][0]["files"])
    align.align_series(s, cfg["align"])
    m = merge.merge_series(s, cfg)
    win = windows.detect(m.radiance, m.clipped, cfg)
    gt = labels(synth, "living_room") == 4
    pred = cv2.resize(win.mask, (gt.shape[1], gt.shape[0])) > 0.5
    iou = (gt & pred).sum() / max((gt | pred).sum(), 1)
    assert iou > 0.6, iou


# --- white balance -----------------------------------------------------------------------------
def test_white_balance_removes_cast(cfg):
    """A warm 4000 K cast is removed; the red accent wall keeps its colour.  (Very strong casts,
    e.g. 3000 K with daylight WB, are deliberately corrected only partially: soft limit.)"""
    rng = np.random.default_rng(0)
    base = np.full((200, 300, 3), 0.3, np.float32) * rng.uniform(0.9, 1.1, (200, 300, 1)).astype(np.float32)
    base[50:100, 60:120] = [0.30, 0.10, 0.08]  # a red accent surface
    tungsten = color.kelvin_rgb(4000) / color.kelvin_rgb(6500)
    cast = (base * (tungsten / tungsten[1])).astype(np.float32)
    out, info = color.white_balance(cast.copy(), cast.copy(), None, cfg)
    lab_in = rgb_to_lab(cast[150:, 150:]).reshape(-1, 3).mean(0)
    lab_out = rgb_to_lab(out[150:, 150:]).reshape(-1, 3).mean(0)
    assert np.hypot(*lab_out[1:]) < 0.4 * np.hypot(*lab_in[1:])
    assert abs(info["cct"] - 4000) < 300
    acc = rgb_to_lab(out[60:90, 70:110]).reshape(-1, 3).mean(0)
    assert acc[1] > 15  # the red accent stays red (no "neutralise everything")


# --- tone mapping ------------------------------------------------------------------------------
def test_tonemap_range_monotone_and_clipping(synth, cfg):
    rad = _gt_radiance(synth, "living_room")
    out = tonemap.tone_map(rad.copy(), dict(cfg["tonemap"]), analysis_side=400)
    assert out.min() >= 0 and out.max() <= 1
    y_in, y_out = luminance(rad), out @ LUMA
    lab = labels(synth, "living_room")
    # window pull deliberately renders the view darker than the bright walls around it, so the
    # order of brightness is checked on the room itself (windows and lamps excluded)
    excl = cv2.dilate(((lab == 4) | (lab == 7)).astype(np.uint8), np.ones((15, 15), np.uint8)).astype(np.float32)
    room = cv2.resize(excl, (60, 40), interpolation=cv2.INTER_AREA).ravel() < 0.01
    sm_in = np.log2(cv2.resize(y_in, (60, 40), interpolation=cv2.INTER_AREA).ravel()[room] + 1e-6)
    sm_out = cv2.resize(y_out, (60, 40), interpolation=cv2.INTER_AREA).ravel()[room]
    # local tone mapping keeps the global order of brightness: of all pairs of room areas more than
    # 1 EV apart, only a few may swap (a lifted dark corner vs. a compressed lamp-lit wall);
    # measured 3.7% at target_key 0.56 and 5.3% at the calibrated 0.70
    far = (sm_in[:, None] - sm_in[None, :]) > 1.0
    swapped = float(((sm_out[:, None] - sm_out[None, :]) < 0)[far].mean())
    assert swapped < 0.07, swapped
    lights = cv2.dilate((lab == 7).astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool) | (lab == 4)
    clipped = (np.round(out * 255).max(-1) >= 254) & ~lights
    assert clipped.mean() < 0.005


def test_tonemap_inplace_equals_copy(synth, cfg):
    rad = _gt_radiance(synth, "living_room")
    a = tonemap.tone_map(rad.copy(), dict(cfg["tonemap"]), analysis_side=300)
    b = tonemap.tone_map(rad.copy(), dict(cfg["tonemap"]), analysis_side=300, inplace=True)
    assert np.abs(a - b).max() < 1e-5


def test_resize_rows_matches_cv2():
    rng = np.random.default_rng(3)
    small = rng.random((23, 37, 2)).astype(np.float32)
    full = cv2.resize(small, (301, 199), interpolation=cv2.INTER_LINEAR)
    parts = np.concatenate([resize_rows(small, 301, 199, r, min(199, r + 31)) for r in range(0, 199, 31)])
    assert np.abs(parts - full).max() < 1e-5


# --- denoise -------------------------------------------------------------------------------------
def test_noise_estimate_and_denoise(cfg):
    rng = np.random.default_rng(1)
    x = np.linspace(0, 1, 400, dtype=np.float32)
    clean = np.stack(np.meshgrid(x, x[:300]), -1).mean(-1)[..., None].repeat(3, -1) * 0.8 + 0.1
    noisy = np.clip(clean + rng.normal(0, 0.02, clean.shape).astype(np.float32), 0, 1)
    assert denoise.estimate_sigma(noisy @ LUMA) == pytest.approx(0.02 * np.sqrt((LUMA ** 2).sum()), rel=0.25)
    out = denoise.denoise(noisy.copy(), cfg)
    assert np.abs(out - clean).mean() < 0.7 * np.abs(noisy - clean).mean()


# --- lens ----------------------------------------------------------------------------------------
def test_chromatic_aberration_estimate():
    # sharp-edged random rectangles at 1600 px (CA of 0.15% is < 1 px: needs real resolution)
    rng = np.random.default_rng(5)
    img = np.full((1067, 1600, 3), 0.5, np.float32)
    for _ in range(300):
        x, y = rng.integers(0, 1550), rng.integers(0, 1020)
        w, h = rng.integers(10, 120, 2)
        img[y:y + h, x:x + w] = rng.uniform(0.05, 0.95)
    ca = img.copy()
    ca[..., 0] = lens._radial_scale(img[..., 0], 1.0015)
    ca[..., 2] = lens._radial_scale(img[..., 2], 0.9985)
    sR, sB, _ = lens.estimate_ca(ca)
    assert abs(sR * 1.0015 - 1.0) < 0.0004 and abs(sB * 0.9985 - 1.0) < 0.0004, (sR, sB)


def test_manual_vignetting(cfg):
    img = np.full((200, 300, 3), 0.5, np.float32)
    out, info = lens.correct(img.copy(), {**cfg, "lens": {"ca": "off", "vignetting": 0.3}})
    assert out[100, 150].mean() == pytest.approx(0.5, abs=1e-3)
    assert out[0, 0].mean() > 0.6  # corners brightened


# --- geometry ------------------------------------------------------------------------------------
def _lines_image(w=600, h=400, tilt_deg=0.0):
    img = np.full((h, w, 3), 0.85, np.float32)
    for x in range(60, w, 70):
        cv2.line(img, (x, 20), (x, h - 20), (0.15, 0.15, 0.15), 3)
    cv2.line(img, (20, h // 2), (w - 20, h // 2), (0.15, 0.15, 0.15), 3)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), tilt_deg, 1.0)
    return cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)


def test_geometry_straightens_tilt(cfg):
    from estatehdr.quality.metrics import verticality
    img = _lines_image(tilt_deg=2.5)
    before = verticality(img)["median_abs_deg"]
    out, info = geometry.correct(img, cfg, None)
    after = verticality(out)["median_abs_deg"]
    assert before > 2.0 and after < 0.5, info
    assert out.shape == img.shape  # resized back to the input dimensions


def test_distortion_estimate(cfg):
    img = _lines_image(800, 600)
    k1 = 0.08
    # exact model (r normalised by the half diagonal): distorted pixel r_d shows ideal r_u = r_d (1 + k1 r_d^2)
    h, w = 600, 800
    cx, cy = (w - 1) / 2, (h - 1) / 2
    R = np.hypot(cx, cy)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    X, Y = (xx - cx) / R, (yy - cy) / R
    f = 1 + k1 * (X * X + Y * Y)
    dist = cv2.remap(img, (cx + X * f * R).astype(np.float32), (cy + Y * f * R).astype(np.float32),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    est, info = geometry.estimate_distortion(geometry._gray8(dist))
    assert info["accepted"] and abs(abs(est) - k1) < 0.03, (est, info)


# --- night exteriors -----------------------------------------------------------------------------
def test_night_detection(synth, cfg):
    from estatehdr.pipeline import detect_night
    rng = np.random.default_rng(4)
    night = np.full((300, 450, 3), 0.002, np.float32) * rng.uniform(0.9, 1.1, (300, 450, 1)).astype(np.float32)
    night[150:, :] = rng.uniform(0.005, 0.05, (150, 450, 3)).astype(np.float32)  # dim streets / buildings
    night[200:230, 100:350] = 3.0  # lit facade
    night[120:140, 200:210] = 50.0  # street lights
    assert detect_night(night, cfg)[0]
    for scene in ("living_room", "bedroom"):
        assert not detect_night(_gt_radiance(synth, scene), cfg)[0]

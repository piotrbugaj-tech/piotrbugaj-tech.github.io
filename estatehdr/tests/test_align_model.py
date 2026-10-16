"""Alignment motion model: ``align.model: auto`` models perspective only when the data support it,
and the explicit models keep working (procedural scene, so the test is self-contained and fast)."""
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from estatehdr import align

W, H = 960, 640  # "full resolution"; the analysis copies are half of it


def _scene(seed=3):
    """Linear RGB scene with plenty of corners and edges (rectangles, discs, bars)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    img = np.dstack([0.15 + 0.10 * xx / W, 0.17 + 0.08 * yy / H, 0.16 + 0.05 * (xx + yy) / (W + H)])
    for _ in range(160):
        x0, y0 = int(rng.integers(0, W - 20)), int(rng.integers(0, H - 20))
        x1, y1 = x0 + int(rng.integers(8, 90)), y0 + int(rng.integers(8, 90))
        cv2.rectangle(img, (x0, y0), (x1, y1), rng.uniform(0.03, 0.8, 3).tolist(), -1)
    for _ in range(60):
        c = (int(rng.integers(0, W)), int(rng.integers(0, H)))
        cv2.circle(img, c, int(rng.integers(4, 30)), rng.uniform(0.03, 0.8, 3).tolist(), -1)
    return np.clip(cv2.GaussianBlur(img, (0, 0), 0.8), 0.0, 1.0)


def _about_centre(M):
    T = np.array([[1, 0, W / 2], [0, 1, H / 2], [0, 0, 1]], np.float64)
    return T @ M @ np.linalg.inv(T)


def _motion(tx, ty, deg, h31=0.0, h32=0.0):
    """GT reference -> frame mapping: rotation and perspective about the centre, then a shift."""
    a = np.deg2rad(deg)
    R = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    P = np.array([[1, 0, 0], [0, 1, 0], [h31, h32, 1]])
    return np.array([[1, 0, tx], [0, 1, ty], [0, 0, 1]]) @ _about_centre(P @ R)


def _frame(lin, exposure, seed):
    """Frame object as align.align_series uses it (16-bit linear data, analysis copy at half size)."""
    rng = np.random.default_rng(seed)
    img = np.clip(lin * exposure + rng.normal(0, 0.002, lin.shape), 0, 1)
    img16 = np.round(img * 65535).astype(np.uint16)
    small = cv2.resize(img16, (W // 2, H // 2), interpolation=cv2.INTER_AREA).astype(np.float32) / 65535
    return SimpleNamespace(decoded=SimpleNamespace(image=img16, max_value=65535), lut=None, small=small,
                           exposure=exposure, shape=img16.shape, meta=SimpleNamespace(name=f"f{seed}"))


def _align(M, model, exposure=0.5):
    """Aligns a -1 EV frame moved by the GT homography M to the reference; returns (info, grid error)."""
    scene = _scene()
    mov = cv2.warpPerspective(scene, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    series = SimpleNamespace(name="t", ref=0, frames=[_frame(scene, 1.0, 1), _frame(mov, exposure, 2)])
    cfg = {"model": model, "fine_max_side": 2600}
    info = align.align_series(series, cfg)[1]
    pts = np.array([[x, y, 1.0] for x in np.linspace(40, W - 40, 9) for y in np.linspace(40, H - 40, 7)]).T
    a, b = series.frames[1].homography @ pts, M @ pts
    return info, np.hypot(*(a[:2] / a[2] - b[:2] / b[2]))


def test_auto_picks_homography_for_perspective():
    M = _motion(7, -5, 0.4, 3e-5, -2e-5)  # 4-10 px of perspective at the corners
    _, e_aff = _align(M, "affine")
    info, e = _align(M, "auto")
    assert info["model"] == "homography", info
    assert info["model_select"]["llr"] > 3.0 and info["model_select"]["corner_diff_px"] > 0.5, info
    assert e.mean() < 0.25 and e.max() < 0.6, (e.mean(), e.max())
    assert e_aff.mean() > 3 * e.mean()  # the affine model cannot represent this motion


def test_auto_keeps_affine_for_shake():
    M = _motion(6, -4, 0.35)  # hand-held shake: shift + rotation, no perspective
    info, e = _align(M, "auto")
    assert info["model"] == "affine", info
    assert e.mean() < 0.25 and e.max() < 0.5, (e.mean(), e.max())


@pytest.mark.parametrize("model", ["translation", "similarity", "affine", "homography"])
def test_explicit_models(model):
    M = _motion(6, -4, 0.0) if model == "translation" else _motion(6, -4, 0.35)
    info, e = _align(M, model)
    assert info["model"] == model and "model_select" not in info, info
    assert e.mean() < 0.3 and e.max() < 0.8, (model, e.mean(), e.max())

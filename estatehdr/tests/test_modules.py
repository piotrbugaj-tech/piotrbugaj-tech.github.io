"""Optional modules: sky detection/replacement, twilight, object removal, grass."""
import os

import cv2
import numpy as np
import tifffile

from estatehdr.modules import grass, remove, sky, twilight
from estatehdr.synthetic import render_exterior
from estatehdr.tonemap import tone_map



def _exterior_display(cfg):
    rad, lab = render_exterior(480, 320, supersample=1)
    img = tone_map(rad.copy(), dict(cfg["tonemap"]), analysis_side=480)
    return img, lab


def test_sky_detection_iou(cfg):
    img, lab = _exterior_display(cfg)
    m, info = sky.detect_sky(img)
    gt = lab == 9
    pred = m > 0.5
    iou = (gt & pred).sum() / max((gt | pred).sum(), 1)
    assert iou >= 0.85, (iou, info)


def test_no_sky_in_interior(synth, cfg):
    rad = tifffile.imread(os.path.join(synth["root"], "gt", "bedroom", "radiance_capture.tif"))
    img = tone_map(rad.astype(np.float32), dict(cfg["tonemap"]), analysis_side=480)
    m, info = sky.detect_sky(img)
    assert m is None, info


def test_sky_replacement_changes_only_sky(cfg):
    img, lab = _exterior_display(cfg)
    out, info = sky.replace_sky(img.copy(), cfg, "x", style="clear")
    assert info["applied"]
    gt = lab == 9
    house = cv2.erode((lab != 9).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    assert np.abs(out - img)[house].mean() < 0.01           # foreground untouched
    assert (out[..., 2] - out[..., 0])[gt].mean() > 0.15      # new sky is blue


def test_procedural_skies_deterministic():
    a = sky.synth_sky(200, 80, "dramatic", 7)
    b = sky.synth_sky(200, 80, "dramatic", 7)
    assert np.array_equal(a, b) and a.shape == (80, 200, 3)
    t = sky.synth_sky(200, 80, "pink", 7, twilight=True)
    assert t[-1].mean(0)[0] > t[0].mean(0)[0]  # warm horizon, dark zenith


def test_twilight_exterior(cfg):
    img, lab = _exterior_display(cfg)
    out, info = twilight.twilight(img.copy(), cfg, "x")
    assert info["exterior"] and info["windows_lit"] >= 4
    facade = (lab == 6) | (lab == 1)
    if facade.any():
        assert out[facade].mean() < img[facade].mean()  # darker dusk facade


def test_object_removal_restores_texture():
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[0:240, 0:320]
    tex = (0.5 + 0.3 * np.sin(xx / 5.0))[..., None] * np.array([0.9, 0.75, 0.6]) + rng.normal(0, 0.01, (240, 320, 3))
    img = np.clip(tex, 0, 1).astype(np.float32)
    damaged = img.copy()
    damaged[100:150, 130:180] = [0.05, 0.05, 0.05]  # "object"
    mask = np.zeros((240, 320), np.uint8)
    mask[100:150, 130:180] = 255
    out, info = remove.remove_objects(damaged.copy(), mask, {"modules": {"remove": {"method": "patch"}}})
    hole = mask > 0
    assert np.abs(out[hole] - img[hole]).mean() < 0.08
    g = lambda a: np.abs(np.diff(a[..., 1], axis=1))[hole[:, 1:]].mean()
    assert g(out) > 0.5 * g(img)  # texture continued, not a flat blur


def test_find_mask_file(tmp_path):
    from estatehdr.grouping import Group
    from estatehdr.io.metadata import FrameMeta
    p = tmp_path / "IMG_1.jpg"
    cv2.imwrite(str(p), np.zeros((20, 30, 3), np.uint8))
    m = np.zeros((20, 30), np.uint8)
    m[5:10, 5:10] = 255
    cv2.imwrite(str(tmp_path / "IMG_1.mask.png"), m)
    g = Group("IMG_1", [FrameMeta(path=str(p), kind="jpeg")])
    found = remove.find_mask(g)
    assert found is not None and found.sum() == 25 * 255


def test_grass_greener(cfg):
    img, lab = _exterior_display(cfg)
    out, info = grass.green_grass(img.copy(), cfg)
    lawn = lab == 3
    hsv_in = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)[lawn]
    hsv_out = cv2.cvtColor(out, cv2.COLOR_RGB2HSV)[lawn]
    assert info["applied"]
    assert abs(np.median(hsv_out[:, 0]) - 95) < abs(np.median(hsv_in[:, 0]) - 95)


def test_run_modules_never_raises(cfg, monkeypatch):
    from estatehdr.grouping import Group
    from estatehdr.modules import run_modules
    img, _ = _exterior_display(cfg)

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(sky, "replace_sky", boom)
    c = {**cfg, "modules": {**cfg["modules"], "sky": {"enabled": True, "style": "clear"}}}
    out, info = run_modules(img.copy(), c, Group("x", []), None, None)
    assert "error" in info["sky"] and out.shape == img.shape

"""Regression tests for the image-quality fixes found by the final audit: noisy single frames,
low-contrast exteriors, single-image clipping, retouch locality, window metrics without GT."""
import json
import os
import shutil

import cv2
import numpy as np
import tifffile

from estatehdr.batch import run_batch
from estatehdr.config import load_config
from estatehdr.quality.evaluate import evaluate_output_dir

from .conftest import series_by_first


def _specks(path):
    g = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2GRAY).astype(np.int32)
    return float(((cv2.medianBlur(g.astype(np.uint8), 7).astype(np.int32) - g) > 40).mean())


def test_noisy_single_frame_is_denoised_and_lifted_less(synth, tmp_path):
    """A dark single linear frame with strong, spatially correlated noise (like an under-exposed
    phone RAW): the shadow noise triggers the strong denoiser even though the global noise is
    moderate (before: the denoiser did nothing here), and shadows are lifted less."""
    rad = tifffile.imread(os.path.join(synth["root"], "gt", "living_room", "radiance_capture.tif")).astype(np.float32)
    rng = np.random.default_rng(3)
    x = rad * (0.01 / float(np.median(rad)))
    n = cv2.GaussianBlur(rng.normal(0, 1, x.shape).astype(np.float32), (0, 0), 1.0)
    x = np.clip(x + n / n.std() * np.sqrt(0.0004 * x + 0.006 ** 2), 0, None)
    d = tmp_path / "in"
    d.mkdir()
    tifffile.imwrite(str(d / "noisy.tif"), np.clip(x / x.max(), 0, 1).astype(np.float32))
    specks = {}
    for k, extra in (("on", []), ("off", ["denoise.enabled=false"])):
        rep = run_batch(str(d), str(tmp_path / k), load_config(None, "neutral", ["runtime.workers=1"] + extra))
        s = rep["series"][0]
        assert s["status"] == "ok", s.get("error")
        specks[k] = _specks(s["outputs"]["full"]["path"])
    assert s["single_noise"]["nsr"] > 0.03 and s["single_noise"]["compress_shadows"] > 0.8
    assert specks["on"] < 0.6 * specks["off"], specks


def test_low_contrast_exterior_not_crushed(batch, synth):
    """Daylight facade with dark panes spans ~1 EV from the darkest 0.5% to the median: black is
    raised so panes keep their tone; interiors keep the full black."""
    rep = batch["report"]
    ext = next(s for s in synth["manifest"]["series"] if s["name"] == "exterior")
    s_ext = series_by_first(rep, ext["files"][0])
    assert s_ext["tonemap"]["black_out"] > 0.08
    for ser in synth["manifest"]["series"]:
        if ser["name"] in ("living_room", "bedroom"):
            assert abs(series_by_first(rep, ser["files"][0])["tonemap"]["black_out"] - 0.03) < 1e-3


def test_single_jpeg_does_not_add_clipping(synth, tmp_path):
    src = os.path.join(synth["input"], "IMG_0011.jpg")
    rep = run_batch(None, str(tmp_path / "o"), load_config(None, "neutral", ["grouping.mode=single", "runtime.workers=1"]),
                    files=[src])
    out = cv2.imread(rep["series"][0]["outputs"]["full"]["path"])
    inp = cv2.imread(src)
    assert (out.min(-1) >= 254).mean() <= (inp.min(-1) >= 254).mean() + 0.005


def test_retouch_does_not_move_the_rest_of_the_image(synth, tmp_path):
    """Geometry is estimated before the optional modules: with and without object removal the
    output differs only around the mask."""
    ext = next(s for s in synth["manifest"]["series"] if s["name"] == "exterior")
    d = tmp_path / "ext"
    d.mkdir()
    for f in ext["files"]:
        shutil.copy(os.path.join(synth["input"], f), d / f)
    h, w = cv2.imread(str(d / ext["files"][0])).shape[:2]
    m = np.zeros((h, w), np.uint8)
    m[int(0.55 * h):int(0.7 * h), int(0.45 * w):int(0.5 * w)] = 255
    cv2.imwrite(str(d / (os.path.splitext(ext["files"][0])[0] + ".mask.png")), m)
    outs = []
    for k, extra in (("a", ["modules.remove.enabled=true"]), ("b", [])):
        rep = run_batch(str(d), str(tmp_path / k), load_config(None, "neutral", ["runtime.workers=1"] + extra))
        outs.append(cv2.imread(rep["series"][0]["outputs"]["full"]["path"]).astype(int))
    diff = np.abs(outs[0] - outs[1]).max(-1)
    far = np.ones_like(diff, bool)
    far[int(0.55 * h) - 25:int(0.7 * h) + 25, int(0.45 * w) - 25:int(0.5 * w) + 25] = False
    assert diff[~far].max() > 10      # the object was removed
    assert (diff[far] > 3).mean() < 1e-3  # nothing else moved


def test_window_metrics_without_ground_truth(batch):
    q = evaluate_output_dir(batch["out"], None, max_side=480)
    with_view = [n for n, r in q.items() if r["summary"].get("win_L") is not None]
    assert with_view, "no window metrics from the pipeline's own window mask"
    for n in with_view:
        sm = q[n]["summary"]
        assert 0 <= sm["win_clip_%"] <= 100 and sm["win_detail"] is not None
    rep = json.load(open(os.path.join(batch["out"], "report.json")))
    assert any((s.get("windows") or {}).get("view") for s in rep["series"])


def test_dng_gain_map_parsed_and_interpolated(tmp_path):
    """DNG OpcodeList2 GainMap (lens shading that LibRaw ignores): parsed per Bayer plane and
    evaluated bilinearly in normalised image coordinates."""
    import struct
    from estatehdr.io.reader import _gain_image, dng_gain_maps
    g = np.array([[1.0, 2.0], [3.0, 4.0]], np.float32)
    body = struct.pack(">10I", 0, 0, 100, 100, 0, 1, 2, 2, 2, 2) + struct.pack(">4d", 1.0, 1.0, 0.0, 0.0) \
        + struct.pack(">I", 1) + g.astype(">f4").tobytes()
    ops = struct.pack(">I", 2) + struct.pack(">IIII", 4, 0, 0, 4) + b"\0" * 4 \
        + struct.pack(">IIII", 9, 0x01030000, 0, len(body)) + body  # an unrelated opcode first
    p = str(tmp_path / "x.dng")
    tifffile.imwrite(p, np.zeros((8, 8), np.uint16), extratags=[(51009, "B", len(ops), ops, True)])
    maps = dng_gain_maps(p)
    assert len(maps) == 1 and maps[0]["gain"].shape == (2, 2)
    gi = _gain_image(maps[0], 3, 3)  # pixel centres at 1/6, 1/2, 5/6
    assert np.isclose(gi[1, 1], 2.5) and gi[0, 0] < gi[2, 2]
    assert dng_gain_maps(str(tmp_path / "missing.dng")) == []

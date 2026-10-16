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


def _fabric_photo(seed=5, h=480, w=720):
    """A clean finished photo: brown fabric with fine, strong texture next to a flat wall."""
    rng = np.random.default_rng(seed)
    t = cv2.GaussianBlur(rng.normal(0, 1, (h, w)).astype(np.float32), (0, 0), 0.7)
    t = t / t.std() * 0.25
    img = np.clip(np.array([0.45, 0.33, 0.22], np.float32) * (1 + t[..., None]), 0, 1)
    img[:, : w // 6] = 0.82 + rng.normal(0, 0.002, (h, w // 6, 1)).astype(np.float32)
    return img.astype(np.float32)


def _highpass(x):
    y = x @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    return float(np.std(y - cv2.GaussianBlur(y, (0, 0), 2.0)))


def test_texture_of_finished_photo_is_not_denoised_away():
    """D-49: fabric texture is not noise.  On a finished photo the noise is measured on the
    flattest blocks, so the texture and its colour survive; the generic estimate would have taken
    the texture for noise and smoothed / desaturated it."""
    from estatehdr import denoise
    cfg = load_config(None, "neutral", [])
    img = _fabric_photo()
    fab = (slice(None), slice(img.shape[1] // 6 + 8, None))
    out = denoise.denoise(img.copy(), cfg, single=True, developed=True)
    old = denoise.denoise(img.copy(), cfg, single=True, developed=False)
    keep, keep_old = _highpass(out[fab]) / _highpass(img[fab]), _highpass(old[fab]) / _highpass(img[fab])
    chroma = lambda x: float(np.abs(x - x.mean(-1, keepdims=True)).mean())  # noqa: E731
    y = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    assert denoise.estimate_sigma(y) > 0.015 > 0.004 > denoise.estimate_sigma_flat(y)  # texture read as noise
    assert keep > 0.85 and chroma(out[fab]) > 0.95 * chroma(img[fab]), (keep, keep_old)
    assert keep_old < 0.7  # the test is sensitive: the generic path smooths this texture away


def test_noisy_finished_photo_is_still_denoised():
    from estatehdr import denoise
    cfg = load_config(None, "neutral", [])
    rng = np.random.default_rng(1)
    clean = np.dstack([np.tile(np.linspace(0.2, 0.8, 720, dtype=np.float32), (480, 1))] * 3)
    noisy = np.clip(clean + rng.normal(0, 0.03, clean.shape).astype(np.float32), 0, 1)
    out = denoise.denoise(noisy.copy(), cfg, single=True, developed=True)
    assert np.std(out - clean) < 0.6 * np.std(noisy - clean)


def test_finished_low_key_photo_keeps_its_white(synth, tmp_path):
    """D-49: a soft, low-key edit (whites at ~0.8) is not stretched to full white; no new clipping."""
    src = cv2.imread(os.path.join(synth["input"], "IMG_0011.jpg"))
    low = np.clip(src.astype(np.float32) * 0.8, 0, 255).astype(np.uint8)
    d = tmp_path / "in"
    d.mkdir()
    cv2.imwrite(str(d / "low.jpg"), low, [cv2.IMWRITE_JPEG_QUALITY, 95])
    rep = run_batch(str(d), str(tmp_path / "o"), load_config(None, "neutral", ["grouping.mode=single", "runtime.workers=1"]))
    out = cv2.imread(rep["series"][0]["outputs"]["full"]["path"])
    yi, yo = (cv2.cvtColor(x, cv2.COLOR_BGR2GRAY) for x in (low, out))
    assert np.percentile(yo, 99) <= np.percentile(yi, 99) + 0.12 * 255 * 0.5
    assert (out.max(-1) >= 254).mean() <= (low.max(-1) >= 254).mean() + 0.005  # SPEC: < 0.5% clipped


def test_white_balance_tungsten_zone_and_accent_wall():
    """SPEC 7 mechanism: a white wall next to a 2700 K lamp in an 8000 K daylit room is corrected
    locally (before: the local correction scaled with a confidence that drops near lamps, the wall
    kept ~half of the cast, |uv| 0.07); a sage accent panel lit by daylight keeps its colour and hue
    (before: hue turned by ~50 deg).  The locus tests use camera chroma (lamps lie on the locus there)."""
    from estatehdr import color
    H, W = 400, 600
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    alb = np.full((H, W, 3), 0.8, np.float32) * rng.uniform(0.97, 1.03, (H, W, 1)).astype(np.float32)
    sage = np.array([0.42, 0.55, 0.45], np.float32)
    acc = np.zeros((H, W), bool)
    acc[80:220, 40:200] = True
    alb[acc] = sage
    floor = yy > 0.8 * H
    alb[floor] = (np.array([0.50, 0.34, 0.20], np.float32) * ((np.floor(xx / 23) % 3)[..., None] * 0.08 + 0.85))[floor]
    luma = np.array([0.2126, 0.7152, 0.0722], np.float32)
    day, tung = (color.kelvin_rgb(k).astype(np.float32) for k in (8000, 2700))
    day, tung = day / (day @ luma), tung / (tung @ luma)
    r2 = ((xx - 0.78 * W) ** 2 + (yy - 0.45 * H) ** 2) / (0.13 * W) ** 2
    et = 5.0 * np.exp(-r2 / 2)  # lamp light (luminance relative to daylight)
    img = (alb * (day[None, None] + et[..., None] * tung[None, None]) * 0.1).astype(np.float32)
    out, info = color.white_balance(img.copy(), img.copy(), None, load_config(None, "neutral"))
    u, v = color._uv(out)
    wall = ~floor & ~acc & (r2 > 0.05)
    zone, daylit = wall & (et > 1.0), wall & (et < 0.05)
    assert np.hypot(u[zone].mean(), v[zone].mean()) < 0.04
    assert np.hypot(u[daylit].mean(), v[daylit].mean()) < 0.08
    inner = cv2.erode(acc.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    rel = np.array([u[inner].mean() - u[daylit].mean(), v[inner].mean() - v[daylit].mean()])
    true = np.log(sage[[0, 2]] / sage[1])
    assert 0.7 < np.hypot(*rel) / np.hypot(*true) < 1.4  # not neutralised
    ang = np.degrees(np.arctan2(rel[1], rel[0]) - np.arctan2(true[1], true[0]))
    assert abs((ang + 180) % 360 - 180) < 20
    # camera-chroma locus distance: a white under any black body ~0, the sage under daylight ~0.33
    for k in (2700, 4000, 6500, 10000):
        c = color.kelvin_rgb(k)
        assert color.locus_distance(np.full((2, 2), np.log(c[0] / c[1]), np.float32),
                                    np.full((2, 2), np.log(c[2] / c[1]), np.float32)).max() < 0.01
    c = sage / sage[1] * color.kelvin_rgb(8000)
    d = color.locus_distance(np.full((2, 2), np.log(c[0] / c[1]), np.float32), np.full((2, 2), np.log(c[2] / c[1]), np.float32))
    assert 0.3 < d.mean() < 0.37


def _shadow_noise_photo(seed=3, h=480, w=720, sig=0.035):
    """A finished JPEG (q92) whose noise depends on brightness: a clean bright wall (35% of the
    frame, sigma 0.004 - about one code value, which JPEG flattens) above lifted, noisy shadows."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    wall = yy < 0.35 * h
    img = np.where(wall[..., None], (0.75 + 0.1 * xx / w)[..., None], np.float32(0.25)) * np.ones(3, np.float32)
    img = img + rng.normal(0, 1, img.shape).astype(np.float32) * np.where(wall, 0.004, sig)[..., None]
    ok, buf = cv2.imencode(".jpg", (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 92])
    return cv2.imdecode(buf, cv2.IMREAD_UNCHANGED).astype(np.float32) / 255, wall


def test_noisy_shadows_next_to_a_clean_wall_are_denoised():
    """Review of D-49: one flat-block percentile over the whole frame was set by the clean wall
    (sigma ~0.0006 < 0.002), so the whole stage was skipped and the lifted shadows kept their noise.
    The noise is now measured per brightness band (texture still rejected)."""
    from estatehdr import denoise
    cfg = load_config(None, "neutral", [])
    img, wall = _shadow_noise_photo()
    h = img.shape[0]
    dark = ~wall
    dark[: int(0.4 * h)] = False
    inner_wall = wall.copy()
    inner_wall[int(0.3 * h):] = False
    luma = np.array([0.2126, 0.7152, 0.0722], np.float32)
    y = img @ luma
    assert denoise.estimate_sigma_flat(y) < 0.002  # the whole-frame estimate alone would skip the image
    out = denoise.denoise(img.copy(), cfg, single=True, developed=True)
    yo = out @ luma
    hp = lambda a, m: float((a - cv2.GaussianBlur(a, (0, 0), 2.0))[m].std())  # noqa: E731
    assert hp(yo, dark) < 0.5 * hp(y, dark), (hp(y, dark), hp(yo, dark))
    assert abs(float(yo[inner_wall].mean() - y[inner_wall].mean())) < 0.003
    assert hp(yo, inner_wall) <= hp(y, inner_wall) + 1e-4


def test_finished_photo_keeps_its_white_with_a_window(synth, tmp_path):
    """Review of D-49: the author's white was measured over the whole frame, a bright window included
    (p99 ~ window), so a soft edit was still stretched to full white whenever a window was in frame.
    It is now measured on the pixels the tone curve anchors on (windows, lamps, sun patches excluded)."""
    src = cv2.imread(os.path.join(synth["input"], "IMG_0011.jpg"))
    low = np.clip(src.astype(np.float32) * 0.8, 0, 255).astype(np.uint8)
    H, W = low.shape[:2]
    win = np.zeros((H, W), bool)
    win[int(0.15 * H):int(0.33 * H), int(0.55 * W):int(0.85 * W)] = True  # ~5% of the frame
    low[win] = 250
    d = tmp_path / "in"
    d.mkdir()
    cv2.imwrite(str(d / "low_window.jpg"), low, [cv2.IMWRITE_JPEG_QUALITY, 95])
    rep = run_batch(str(d), str(tmp_path / "o"), load_config(None, "neutral", ["grouping.mode=single", "runtime.workers=1"]))
    s = rep["series"][0]
    assert s["status"] == "ok", s.get("error")
    assert (s.get("windows") or {}).get("windows", 0) >= 1  # the window is detected (and excluded)
    out = cv2.imread(s["outputs"]["full"]["path"])
    yi, yo = (cv2.cvtColor(x, cv2.COLOR_BGR2GRAY) for x in (low, out))
    inside = ~cv2.dilate(win.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    # white_range keeps target_white within [0.84, 0.96]: the interior white may rise to 0.84, not to ~0.97
    assert np.percentile(yo[inside], 99) <= max(np.percentile(yi[inside], 99), 0.84 * 255) + 8


def test_pure_black_area_does_not_drag_the_black_anchor(synth, tmp_path):
    """Review of D-49: the robust noise floor of a finished photo collapsed to 1e-6 when pure-black
    blocks (a switched-off TV) were ~10% of the dark blocks; code-0 pixels became -20 EV outliers, the
    black anchor moved ~5-8 EV down and the remaining shadows were lifted.  Zero-response blocks are
    skipped and the floor is at least one 8-bit code value."""
    src = cv2.imread(os.path.join(synth["input"], "IMG_0011.jpg"))
    H, W = src.shape[:2]
    rect = np.zeros((H, W), bool)
    h = int(0.25 * H)
    rect[int(0.4 * H):int(0.4 * H) + h, int(0.3 * W):int(0.3 * W) + int(0.04 * H * W / h)] = True  # 4% black
    blk = src.copy()
    blk[rect] = 0
    res = {}
    for name, im in (("orig", src), ("black", blk)):
        d = tmp_path / name
        d.mkdir()
        cv2.imwrite(str(d / "x.jpg"), im, [cv2.IMWRITE_JPEG_QUALITY, 95])
        rep = run_batch(str(d), str(tmp_path / (name + "_o")),
                        load_config(None, "neutral", ["grouping.mode=single", "runtime.workers=1"]))
        s = rep["series"][0]
        assert s["status"] == "ok", s.get("error")
        g = cv2.cvtColor(cv2.imread(s["outputs"]["full"]["path"]), cv2.COLOR_BGR2GRAY)
        res[name] = (s["tonemap"], g)
    away = ~cv2.dilate(rect.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    assert res["black"][0]["noise_floor"] >= 2.9e-4  # >= one code value (srgb_to_linear(1/255) = 3.04e-4)
    assert res["black"][0]["anchor_lo"] - res["orig"][0]["anchor_lo"] > -3.0  # before: -5.2 EV
    crushed = lambda g: float((g[away] < 5).mean())  # noqa: E731
    assert crushed(res["black"][1]) <= crushed(res["orig"][1]) + 0.002


def test_noise_floor_robust_mode():
    """Robust floor (finished photos): texture in the shadows is not noise, zero-response blocks are
    ignored and the floor never drops below ``min_floor``."""
    from estatehdr import tonemap
    rng = np.random.default_rng(2)
    H, W = 600, 900
    y = np.full((H, W), 0.4, np.float32)
    dark = np.zeros((H, W), bool)
    dark[:, : W // 3] = True
    tex = cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 0.7)
    y[dark] = (0.02 * (1 + 0.5 * tex / tex.std()))[dark]   # dark fabric: texture...
    y[:, W // 6: W // 3] = 0.02 + rng.normal(0, 2e-4, (H, W // 3 - W // 6))  # ... next to a dark, nearly clean wall
    rad = np.repeat(np.clip(y, 0, None)[..., None], 3, -1)
    assert tonemap.noise_floor(rad, robust=True) < 0.5 * tonemap.noise_floor(rad, robust=False)
    rad[:, : W // 3] = 0.0  # the dark third pure black: no block has any response
    assert tonemap.noise_floor(rad, robust=True) <= 1e-5
    assert abs(tonemap.noise_floor(rad, robust=True, min_floor=3e-4) - 3e-4) < 1e-9


def test_finished_neutral_photo_keeps_neutral_white_and_key_range(tmp_path):
    """D-49 settings for finished JPEGs: WB relative to the author's neutral (``wb_target_cct:
    neutral`` - 6500 K is R/G 0.96 in kelvin_rgb, which cut 1.5% red from every neutral photo), the
    key of a dark edit raised to at most target_key + key_range[0], robust noise floor (also with
    key_from_input off)."""
    rng = np.random.default_rng(4)
    H, W = 320, 480
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    v = 0.12 + 0.25 * (1 - yy / H) + 0.1 * ((xx // 60) % 2)          # dark, neutral grey room
    img = np.clip(v[..., None] * rng.uniform(0.97, 1.03, (H, W, 1)), 0, 1).astype(np.float32) * np.ones(3, np.float32)
    d = tmp_path / "in"
    d.mkdir()
    cv2.imwrite(str(d / "grey.jpg"), (img * 255 + 0.5).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 95])
    cfg = load_config(None, "neutral", ["grouping.mode=single", "runtime.workers=1"])
    rep = run_batch(str(d), str(tmp_path / "o"), cfg)
    s = rep["series"][0]
    assert s["status"] == "ok", s.get("error")
    assert cfg["single_image"]["wb_target_cct"] == "neutral"
    assert np.hypot(*s["white_balance"]["global_shift"]) < 0.003
    tk, lo = cfg["tonemap"]["target_key"], cfg["single_image"]["key_range"][0]
    assert s["input_key"] < tk + lo and abs(s["single_key_target"] - (tk + lo)) < 1e-3
    assert s["tonemap"]["noise_floor"] >= 2.9e-4
    out = cv2.imread(s["outputs"]["full"]["path"]).astype(np.float32)
    bgr = out.reshape(-1, 3).mean(0)
    assert np.abs(bgr / bgr[1] - 1).max() < 0.01  # still neutral
    # the robust floor belongs to every finished photo, not only when its key is taken over
    rep = run_batch(str(d), str(tmp_path / "o2"), load_config(None, "neutral", [
        "grouping.mode=single", "runtime.workers=1", "single_image.key_from_input=false"]))
    s = rep["series"][0]
    assert "single_key_target" not in s and s["tonemap"]["noise_floor"] >= 2.9e-4


def test_local_wb_without_evidence_does_not_pass_as_well_covered():
    """certainty() divided by the p75 of the smoothed confidence, which has a 1e-6 floor: when >= 75%
    of the grid had no evidence, evidence-free cells counted as well covered and the regional fill
    was cut to ~13% a few cells from the evidence (a hard step that flipped with coverage).  Now the
    fill falls off smoothly and does not depend on how much of the frame has evidence."""
    from estatehdr import color
    wcfg = load_config(None, "neutral")["white_balance"]
    rng = np.random.default_rng(0)
    H, W = 400, 600
    near = {}
    for size in (60, 180):
        img = np.empty((H, W, 3), np.float32)
        img[:] = np.array([0.15, 0.45, 0.12], np.float32)  # saturated green, far from the locus: no evidence
        img[100:100 + size, 100:100 + size] = 0.6 * color.kelvin_rgb(2700).astype(np.float32)  # lamp-lit white
        img[380:390, 580:590] = 5.0
        img *= rng.uniform(0.97, 1.03, (H, W, 1)).astype(np.float32)
        f, _ = color.local_field(img, np.zeros(2), None, wcfg)
        mag = np.hypot(f[..., 0], f[..., 1])
        on = mag[100 + size // 2, 100 + size // 2]
        near[size] = mag[min(H - 1, 100 + size + 50), 100 + size // 2] / on
        assert mag[300, 560] < 0.05 * on  # far from any evidence: no correction
    assert near[60] > 0.8 and near[180] > 0.8, near  # before: 0.15 for both (hard step ~4 cells out)


def test_wb_strengths_of_finished_and_night_photos():
    """Local (mixed-light) WB of a finished night photo is halved like its global WB (before: the
    developed factor replaced the night factor); brackets and day photos unchanged."""
    from estatehdr.pipeline import wb_config
    cfg = load_config(None, "neutral")
    base, si, nt = cfg["white_balance"], cfg["single_image"], cfg["night"]
    assert wb_config(cfg, False, False) is cfg
    for developed, night in ((True, False), (True, True), (False, True)):
        w = wb_config(cfg, developed, night)["white_balance"]
        fn = nt["wb_strength"] if night else 1.0
        fg = (si["wb_strength"] if developed else 1.0) * fn
        fl = si["wb_mixed_light"] * fn if developed else fg
        assert np.isclose(w["global_strength"], base["global_strength"] * fg)
        assert np.isclose(w["mixed_light_strength"], base["mixed_light_strength"] * fl)
        assert w["target_cct"] == (si["wb_target_cct"] if developed else base["target_cct"])

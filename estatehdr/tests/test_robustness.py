"""Regression tests for robustness fixes: worker crashes, name collisions, RAW+JPEG pairs,
JPEG trailers, CLI paths, ICC profiles, RAW sizes, output folder rescans, corrupt files,
``off`` switches and the configuration resolution order."""
import io
import json
import os
import shutil
import struct
import subprocess
import sys

import numpy as np
import pytest
import yaml
from PIL import Image

from estatehdr.batch import CRASH_ENV, estimate_series_bytes, run_batch
from estatehdr.config import DEFAULT_CONFIG_PATH, load_config, mode_of
from estatehdr.grouping import Group, collapse_raw_siblings, list_images, load_groups, save_groups, scan_folder
from estatehdr.io import reader, writer
from estatehdr.io.metadata import FrameMeta, largest_dimensions, read_metadata

from .conftest import ROOT


def _folder(tmp_path, synth, names, src="IMG_0011.jpg"):
    d = tmp_path / "in"
    for n in names:
        p = d / n
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(os.path.join(synth["input"], src), p)
    return str(d)


def _by_name(rep):
    return {s["name"]: s for s in rep["series"]}


SINGLE = ["grouping.mode=single", "export.save_previews=false"]


# 1. worker crash ------------------------------------------------------------------------------

def test_worker_crash_only_fails_the_crashing_series(synth, tmp_path, monkeypatch):
    inp = _folder(tmp_path, synth, ["a.jpg", "b.jpg", "c.jpg"])
    monkeypatch.setenv(CRASH_ENV, "b")
    rep = run_batch(inp, str(tmp_path / "out"), load_config(None, "neutral", SINGLE + ["runtime.workers=2"]))
    s = _by_name(rep)
    assert s["a"]["status"] == "ok" and s["c"]["status"] == "ok"
    assert s["b"]["status"] == "error" and "worker crashed" in s["b"]["error"]
    with open(tmp_path / "out" / "report.json") as fh:
        assert json.load(fh)["complete"] is True


def test_inprocess_crash_leaves_partial_report(synth, tmp_path):
    inp = _folder(tmp_path, synth, ["a.jpg", "b.jpg", "c.jpg"])
    out = str(tmp_path / "out")
    code = ("import sys; from estatehdr.batch import run_batch; from estatehdr.config import load_config; "
            f"run_batch(sys.argv[1], sys.argv[2], load_config(None, 'neutral', {SINGLE + ['runtime.workers=1']!r}))")
    r = subprocess.run([sys.executable, "-c", code, inp, out], env={**os.environ, "PYTHONPATH": ROOT, CRASH_ENV: "b"},
                       capture_output=True, text=True)
    assert r.returncode == 1
    with open(os.path.join(out, "report.json")) as fh:
        rep = json.load(fh)
    assert rep["complete"] is False and [s["name"] for s in rep["series"]] == ["a"] and rep["pending"] == ["b", "c"]


# 2. unique series names -----------------------------------------------------------------------

def test_same_file_names_in_subfolders_get_unique_outputs(synth, tmp_path, cfg):
    inp = _folder(tmp_path, synth, ["a/IMG_0001.jpg", "b/IMG_0001.jpg"])
    groups, _ = scan_folder(inp, cfg["grouping"])
    assert [g.name for g in groups] == ["IMG_0001", "IMG_0001_2"]
    out = str(tmp_path / "out")
    rep = run_batch(inp, out, load_config(None, "neutral", SINGLE + ["runtime.workers=1"]))
    assert rep["ok"] == 2
    assert os.path.exists(os.path.join(out, "IMG_0001_full.jpg")) and os.path.exists(os.path.join(out, "IMG_0001_2_full.jpg"))


def test_groups_file_names_sanitised_and_unique(synth, tmp_path):
    p = str(tmp_path / "g.json")
    f = os.path.join(synth["input"], "IMG_0011.jpg")
    with open(p, "w") as fh:
        json.dump({"groups": [{"name": "../x", "files": [f]}, {"name": "../x", "files": [f]}]}, fh)
    assert [g.name for g in load_groups(p)] == [".._x", ".._x_2"]


# 3. RAW + JPEG pairs --------------------------------------------------------------------------

def test_raw_jpeg_siblings_collapse_to_raw():
    paths = ["/s/IMG_1.CR2", "/s/IMG_1.JPG", "/s/IMG_2.jpg", "/t/IMG_1.jpg", "/s/IMG_3.NEF", "/s/img_3.tif"]
    kept, skipped = collapse_raw_siblings(paths)
    assert kept == ["/s/IMG_1.CR2", "/s/IMG_2.jpg", "/t/IMG_1.jpg", "/s/IMG_3.NEF"]
    assert [(s["file"], s["reason"]) for s in skipped] == [("/s/IMG_1.JPG", "RAW sibling used"),
                                                             ("/s/img_3.tif", "RAW sibling used")]


def test_raw_sibling_reported_in_batch(synth, tmp_path):
    inp = _folder(tmp_path, synth, ["IMG_1.jpg", "IMG_1.cr2"])  # the "RAW" is a renamed JPEG (unreadable as RAW)
    rep = run_batch(inp, str(tmp_path / "out"), load_config(None, "neutral", ["runtime.workers=1"]))
    assert [os.path.basename(s["file"]) for s in rep["skipped"]] == ["IMG_1.jpg"]


def test_mixed_encodings_linearised_per_frame(synth, cfg, tmp_path):
    import tifffile
    from estatehdr.imgutil import srgb_to_linear
    from estatehdr.series import load_series
    src = os.path.join(synth["input"], "IMG_0011.jpg")
    lin = srgb_to_linear(reader.decode(src).as_float())
    tifffile.imwrite(str(tmp_path / "lin.tif"), lin.astype(np.float32), photometric="rgb")
    s = load_series("t", [read_metadata(src), read_metadata(str(tmp_path / "lin.tif"))], cfg)
    enc = {f.meta.name: (f.decoded.encoding, f.lut is not None) for f in s.frames}
    assert enc == {"IMG_0011.jpg": ("srgb", True), "lin.tif": ("linear", False)}
    assert s.crf["model"] == "mixed" and any("mixes pixel encodings" in w for w in s.warnings)
    a, b = (np.median(f.small.mean(-1)) for f in s.frames)  # same scene: linear values agree up to exposure
    assert abs(np.log2(a / b) - np.log2(s.frames[0].exposure / s.frames[1].exposure)) < 0.1


# 4. JPEG trailers ------------------------------------------------------------------------------

def _jpeg_with_thumbnail() -> bytes:
    import piexif
    img = (np.random.default_rng(0).random((240, 320, 3)) * 255).astype(np.uint8)
    tb = io.BytesIO()
    Image.fromarray(img[::8, ::8]).save(tb, "JPEG")
    exif = piexif.dump({"0th": {piexif.ImageIFD.Make: b"Test"}, "Exif": {}, "GPS": {},
                        "1st": {piexif.ImageIFD.XResolution: (72, 1)}, "thumbnail": tb.getvalue()})
    b = io.BytesIO()
    Image.fromarray(img).save(b, "JPEG", quality=90, exif=exif)
    return b.getvalue()


def test_jpeg_with_trailing_data_decodes(synth, tmp_path):
    src = os.path.join(synth["input"], "IMG_0002.jpg")
    with open(src, "rb") as fh:
        data = fh.read()
    p = tmp_path / "trailer.jpg"
    p.write_bytes(data + b"SEFH" + bytes(range(76)))  # 80 bytes after EOI (Samsung / Motion Photo style)
    assert np.array_equal(reader.decode(str(p)).image, reader.decode(src).image)


def test_jpeg_cut_in_main_scan_is_truncated_despite_thumbnail_eoi(tmp_path):
    data = _jpeg_with_thumbnail()
    assert reader.jpeg_scan(data)[0]
    cut = data[: int(len(data) * 0.7)]
    assert b"\xff\xd9" in cut  # the EXIF thumbnail's end marker is still there
    p = tmp_path / "cut.jpg"
    p.write_bytes(cut)
    with pytest.raises(reader.DecodeError, match="truncated"):
        reader.decode(str(p))


# 5. CLI paths ----------------------------------------------------------------------------------

def _cli(args, cwd, env=None):
    return subprocess.run([sys.executable, "-m", "estatehdr"] + args, cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": ROOT, **(env or {})})


def test_cli_missing_and_empty_input(tmp_path):
    r = _cli(["process", "nie_ma"], str(tmp_path))
    assert r.returncode == 2 and not os.path.exists(tmp_path / "nie_ma")
    (tmp_path / "pusty").mkdir()
    r = _cli(["process", "pusty"], str(tmp_path))
    assert r.returncode == 1 and "brak" in r.stderr and not os.listdir(tmp_path / "pusty")


def test_cli_group_then_process_with_relative_paths(synth, tmp_path):
    _folder(tmp_path, synth, ["sesja/a.jpg"])
    os.rename(tmp_path / "in" / "sesja", tmp_path / "sesja")
    r = _cli(["group", "sesja", "-o", "g.json"], str(tmp_path))
    assert r.returncode == 0, r.stderr[-2000:]
    r = _cli(["process", "sesja", "--groups", "g.json", "-o", "out", "--workers", "1"], str(tmp_path))
    assert r.returncode == 0, r.stderr[-2000:]
    assert json.loads(r.stdout.strip().splitlines()[-1])["ok"] == 1


# 6. ICC profiles -------------------------------------------------------------------------------

ADOBE_D50 = ((0.6097559, 0.3111242, 0.0194811), (0.2052401, 0.6256560, 0.0608902), (0.1492240, 0.0632197, 0.7448387))


def _icc_v2(desc: str, colorants, gamma: float = 563 / 256) -> bytes:
    """Minimal ICC v2 matrix/TRC display profile (desc, wtpt, r/g/bXYZ, r/g/bTRC, cprt)."""
    def s15(v):
        return struct.pack(">i", int(round(v * 65536)))

    def xyz(v):
        return b"XYZ " + bytes(4) + b"".join(s15(c) for c in v)
    d = desc.encode() + b"\0"
    curv = b"curv" + bytes(4) + struct.pack(">IH", 1, int(round(gamma * 256))) + bytes(2)
    tags = [(b"desc", b"desc" + bytes(4) + struct.pack(">I", len(d)) + d + bytes(8 + 2 + 1 + 67)),
            (b"wtpt", xyz((0.9505, 1.0, 1.0891))), (b"rXYZ", xyz(colorants[0])), (b"gXYZ", xyz(colorants[1])),
            (b"bXYZ", xyz(colorants[2])), (b"rTRC", curv), (b"gTRC", curv), (b"bTRC", curv),
            (b"cprt", b"text" + bytes(4) + b"none\0" + bytes(3))]
    off = 132 + 12 * len(tags)
    table, data = b"", b""
    for sig, body in tags:
        data += bytes(-(off + len(data)) % 4)
        table += sig + struct.pack(">II", off + len(data), len(body))
        data += body
    hdr = struct.pack(">I", off + len(data)) + b"none" + struct.pack(">I", 0x02100000) + b"mntrRGB XYZ "
    hdr += bytes(12) + b"acsp" + bytes(28) + s15(0.9642) + s15(1.0) + s15(0.8249)
    return hdr + bytes(128 - len(hdr)) + struct.pack(">I", len(tags)) + table + data


def _patches() -> np.ndarray:
    img = np.zeros((64, 96, 3), np.uint8)
    img[:, :48] = (40, 180, 40)
    img[:, 48:] = (128, 128, 128)
    return img


def test_adobe_rgb_jpeg_and_tiff_converted_srgb_untouched(tmp_path, cfg):
    import tifffile
    from PIL import ImageCms
    from estatehdr.series import load_series
    adobe = _icc_v2("Adobe RGB-like test", ADOBE_D50)
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    img = _patches()
    for name, icc in (("adobe.jpg", adobe), ("srgb.jpg", srgb), ("none.jpg", None)):
        Image.fromarray(img).save(tmp_path / name, "JPEG", quality=100, subsampling=0,
                                  **({"icc_profile": icc} if icc else {}))
    naive = reader.decode(str(tmp_path / "none.jpg"))
    conv = reader.decode(str(tmp_path / "adobe.jpg"))
    assert conv.icc == "Adobe RGB-like test" and conv.encoding == "srgb"
    green, gray = conv.image[32, 20].astype(int), conv.image[32, 70].astype(int)
    assert np.abs(green - naive.image[32, 20]).max() > 20  # not the naive (Adobe codes read as sRGB) value
    assert green[0] < 10 and green[2] < 10  # saturated beyond sRGB -> clipped red / blue
    assert np.abs(gray - naive.image[32, 70]).max() <= 3  # neutral stays neutral
    untouched = reader.decode(str(tmp_path / "srgb.jpg"))
    assert untouched.icc is None and np.array_equal(untouched.image, naive.image)
    # 16-bit TIFF with the same profile: float matrix/TRC path agrees with LittleCMS
    tifffile.imwrite(str(tmp_path / "adobe16.tif"), img.astype(np.uint16) * 257, photometric="rgb",
                     extratags=[(34675, "B", len(adobe), adobe, True)])
    t = reader.decode(str(tmp_path / "adobe16.tif"))
    assert t.icc and np.abs(t.image / 257.0 - conv.image).max() < 3
    s = load_series("icc", [read_metadata(str(tmp_path / "adobe.jpg"))], cfg)
    assert any("ICC profile 'Adobe RGB-like test'" in w for w in s.warnings)


def test_icc_lut_fallback_and_srgb_detection(monkeypatch):
    from estatehdr.io import icc
    adobe = _icc_v2("Adobe RGB-like test", ADOBE_D50)
    img = np.random.default_rng(1).integers(0, 65536, (32, 40, 3)).astype(np.uint16)
    exact = icc.to_srgb(img.copy(), adobe)  # matrix/TRC path
    monkeypatch.setattr(icc, "_matrix_trc", lambda b: None)  # force the 3D LUT path
    approx = icc.to_srgb(img.copy(), adobe)
    assert np.percentile(np.abs(exact / 257.0 - approx / 257.0), 99) < 1.5
    monkeypatch.undo()
    srgb_like = _icc_v2("Camera profile", [icc._srgb()["matrix"][:, k] for k in range(3)], gamma=2.2)
    assert icc.inspect(srgb_like) == (False, "Camera profile")  # sRGB primaries + ~sRGB curve
    assert icc.inspect(adobe) == (True, "Adobe RGB-like test")


# 7. RAW sizes ------------------------------------------------------------------------------------

class _Tag:
    def __init__(self, v):
        self.values = [v]


def test_raw_size_from_largest_subifd():
    tags = {"Image ImageWidth": _Tag(160), "Image ImageLength": _Tag(120),
            "EXIF SubIFD0 ImageWidth": _Tag(8256), "EXIF SubIFD0 ImageLength": _Tag(5504),
            "EXIF SubIFD1 ImageWidth": _Tag(640), "EXIF SubIFD1 ImageLength": _Tag(424)}
    assert largest_dimensions(tags) == (8256, 5504)
    assert largest_dimensions({"Image ImageWidth": _Tag(160)}) == (None, None)
    small = Group("r", [FrameMeta(path="x.nef", kind="raw", width=160, height=120)] * 3)
    big = Group("r", [FrameMeta(path="x.nef", kind="raw", width=6000, height=4000)] * 3)
    assert estimate_series_bytes(small) == estimate_series_bytes(big)  # preview size -> 24 Mpx assumed
    assert estimate_series_bytes(Group("r", [FrameMeta(path="x.nef", kind="raw", width=8256, height=5504)] * 3)) > \
        estimate_series_bytes(big)


# 8. output folder inside the input ---------------------------------------------------------------

def test_output_inside_input_not_rescanned(synth, tmp_path):
    inp = _folder(tmp_path, synth, ["a.jpg", "gotowe/old_full.jpg"])
    out = os.path.join(inp, "gotowe")
    assert [os.path.basename(p) for p in list_images(inp, exclude=[out])] == ["a.jpg"]
    c = load_config(None, "neutral", SINGLE + ["runtime.workers=1"])
    assert [s["name"] for s in run_batch(inp, out, c)["series"]] == ["a"]
    # another output folder: the first run's results (Software=EstateHDR) are skipped, while
    # old_full.jpg (a camera file) is input now
    rep = run_batch(inp, os.path.join(inp, "gotowe2"), c)
    assert [s["name"] for s in rep["series"]] == ["a", "old_full"]
    assert {os.path.basename(e["file"]) for e in rep["skipped"] if e["reason"] == "EstateHDR output"} == \
        {"a_full.jpg", "a_mls.jpg"}


# 9. corrupt file next to a good one without EXIF -------------------------------------------------

def test_garbage_file_not_merged_into_series(synth, tmp_path, cfg):
    inp = _folder(tmp_path, synth, ["p1.jpg"], src="NOEXIF_0000.jpg")
    with open(os.path.join(inp, "p2.jpg"), "wb") as fh:
        fh.write(np.random.default_rng(3).integers(0, 256, 5000, dtype=np.uint8).tobytes())
    groups, failures = scan_folder(inp, cfg["grouping"])
    assert [[f.name for f in g.frames] for g in groups] == [["p1.jpg"]]
    assert [os.path.basename(f["file"]) for f in failures] == ["p2.jpg"]
    rep = run_batch(inp, str(tmp_path / "out"), load_config(None, "neutral", ["runtime.workers=1"]))
    assert rep["ok"] == 1 and len(rep["unreadable"]) == 1


def test_undecodable_frame_dropped_from_series(synth, cfg):
    from estatehdr.series import load_series
    metas = [read_metadata(os.path.join(synth["input"], f)) for f in ("IMG_0011.jpg", "IMG_9999.jpg")]
    s = load_series("t", metas, cfg)
    assert len(s.frames) == 1 and any("IMG_9999.jpg" in w for w in s.warnings)


# 10. "off" switches --------------------------------------------------------------------------------

def test_off_switches(tmp_path):
    from estatehdr import lens
    assert [mode_of(v) for v in (False, None, "off", "none", "False", 0, "auto", True)] == \
        ["off"] * 6 + ["auto", "auto"]
    rad = np.random.default_rng(0).random((96, 128, 3)).astype(np.float32)
    _, info = lens.correct(rad.copy(), load_config(overrides=["lens.vignetting=off", "lens.ca=off"]))
    assert "ca" not in info and "vignetting" not in info
    p = tmp_path / "u.yaml"
    p.write_text("lens:\n  ca: off\n  vignetting: off\n")
    _, info = lens.correct(rad.copy(), load_config(str(p)))
    assert "ca" not in info and "vignetting" not in info
    _, info = lens.correct(rad.copy(), load_config())
    assert "ca" in info and "vignetting" in info


# 11. configuration resolution order -----------------------------------------------------------

def test_user_config_wins_over_preset(tmp_path):
    p = tmp_path / "u.yaml"
    p.write_text("tonemap:\n  target_key: 0.66\n")
    for preset in ("airy", "premium"):
        c = load_config(str(p), preset)
        assert c["tonemap"]["target_key"] == 0.66
        assert c["tonemap"]["contrast"] == load_config(None, preset)["tonemap"]["contrast"]  # rest of the preset kept
    assert load_config(str(p), "airy", ["tonemap.target_key=0.5"])["tonemap"]["target_key"] == 0.5


def test_full_copy_of_defaults_does_not_undo_preset(tmp_path):
    p = tmp_path / "copy.yaml"
    shutil.copy(DEFAULT_CONFIG_PATH, p)
    assert load_config(str(p), "airy") == load_config(None, "airy")
    with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as fh:
        full = yaml.safe_load(fh)
    full["tonemap"]["detail"] = 1.5
    full["presets"]["airy"]["overrides"]["tonemap"]["contrast"] = 0.3
    p.write_text(yaml.safe_dump(full))
    c = load_config(str(p), "airy")
    assert c["tonemap"]["detail"] == 1.5 and c["tonemap"]["contrast"] == 0.3
    assert c["tonemap"]["target_key"] == load_config(None, "airy")["tonemap"]["target_key"]


def test_groups_file_relative_paths(synth, tmp_path, cfg):
    inp = _folder(tmp_path, synth, ["a.jpg", "sub/b.jpg"])
    groups, _ = scan_folder(inp, {**cfg["grouping"], "mode": "single"})
    p = str(tmp_path / "g.json")
    save_groups(groups, p, base=inp)
    with open(p) as fh:
        assert [g["files"] for g in json.load(fh)["groups"]] == [["a.jpg"], [os.path.join("sub", "b.jpg")]]
    assert [g.frames[0].path for g in load_groups(p, base=inp)] == [g.frames[0].path for g in groups]
    assert [g.frames[0].path for g in load_groups(p)] == [g.frames[0].path for g in groups]  # stored base


def test_writer_software_tag_read_back(synth, tmp_path):
    ref = read_metadata(os.path.join(synth["input"], "IMG_0002.jpg"))
    p = str(tmp_path / "o.jpg")
    writer.write_jpeg(p, np.zeros((8, 8, 3), np.uint8), 90, writer.build_exif(ref, 8, 8, "x"))
    assert read_metadata(p).software.startswith("EstateHDR")


# follow-up checks of the fixes ------------------------------------------------------------------

def test_profile_named_srgb_but_linear_is_converted():
    from estatehdr.io import icc
    lin = _icc_v2("sRGB linear-ish (mislabelled)", [icc._srgb()["matrix"][:, k] for k in range(3)], gamma=1.0)
    assert icc.inspect(lin)[0] is True
    bad = bytearray(_icc_v2("broken", ADOBE_D50))
    i = bad.find(b"curv")
    bad[i + 8:i + 12] = struct.pack(">I", 1 << 28)  # absurd entry count, tag far too short
    with pytest.raises(ValueError):
        icc._trc(bytes(bad[i:i + 16]))


def test_unreadable_raw_keeps_its_jpeg(synth, tmp_path):
    d = _folder(tmp_path, synth, ["IMG_1.jpg"])
    with open(os.path.join(d, "IMG_1.CR2"), "wb") as fh:
        fh.write(b"not a raw file" * 100)
    skipped = []
    groups, failures = scan_folder(d, load_config()["grouping"], skipped=skipped)
    assert [os.path.basename(f.path) for g in groups for f in g.frames] == ["IMG_1.jpg"]
    assert [os.path.basename(f["file"]) for f in failures] == ["IMG_1.CR2"] and not skipped


def test_tiff_outputs_are_recognised_as_ours(tmp_path):
    p = str(tmp_path / "out.tif")
    writer.write_tiff16(p, np.full((16, 16, 3), 0.5, np.float32))
    assert (read_metadata(p).software or "").startswith("EstateHDR")


def test_preset_calibration_file_wins_even_at_base_default(tmp_path):
    base = load_config(None, "neutral")["tonemap"]["target_key"]
    p = tmp_path / "cal.yaml"
    p.write_text(yaml.safe_dump({"presets": {"airy": {"overrides": {"tonemap": {"target_key": base}}}}}))
    assert load_config(str(p), "airy")["tonemap"]["target_key"] == base
    assert load_config(str(p), "airy")["presets"]["airy"]["label"]  # label kept


def test_web_names_match_batch_names(synth, tmp_path):
    """Names the web UI accepts are exactly the names run_batch keeps (masks / results keys)."""
    from estatehdr.grouping import Group, unique_names
    from estatehdr.web.app import _unique_names
    raw = [{"name": n} for n in ["Salon", "salon", "...", " kuchnia ", "a/b"]]
    web = [g["name"] for g in _unique_names(raw)]
    assert len({n.casefold() for n in web}) == len(web)
    again = [g.name for g in unique_names([Group(n, []) for n in web])]
    assert again == web

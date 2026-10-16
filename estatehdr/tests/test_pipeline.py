"""End-to-end: batch over a folder, error isolation, exports, quality evaluation, CLI."""
import io
import json
import os
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageCms

from estatehdr.quality import metrics as M
from estatehdr.quality.evaluate import evaluate_output_dir

from .conftest import ROOT, series_by_first


def test_batch_processes_everything_and_isolates_errors(batch, synth):
    rep = batch["report"]
    assert rep["ok"] == 5 and rep["failed"] == 1  # 4 GT series + EXIF-less pair; truncated JPEG fails
    bad = series_by_first(rep, "IMG_9999.jpg")
    assert bad["status"] == "error" and "truncated" in bad["error"].lower()
    stages = {e.get("stage") for e in batch["events"]}
    assert {"wczytywanie", "scalanie HDR", "tone mapping", "eksport", "gotowe"} <= stages  # worker progress


def test_exports_sizes_profile_exif(batch):
    for s in batch["report"]["series"]:
        if s["status"] != "ok":
            continue
        full, mls = s["outputs"]["full"], s["outputs"]["mls"]
        with Image.open(full["path"]) as im:
            assert im.size == (480, 320)  # same dimensions as the input
            prof = ImageCms.ImageCmsProfile(io.BytesIO(im.info["icc_profile"]))
            assert "sRGB" in prof.profile.profile_description
        assert max(mls["width"], mls["height"]) <= 2048
        assert os.path.exists(s["outputs"]["preview_after"]["path"])


def test_quality_targets_on_synthetic_gt(batch, synth):
    gt_map = {}
    for ser in synth["manifest"]["series"]:
        s = series_by_first(batch["report"], ser["files"][0])
        gdir = os.path.join(synth["root"], "gt", ser["name"])
        if s and os.path.exists(os.path.join(gdir, "reference_ideal.png")):
            gt_map[s["name"]] = gdir
    res = evaluate_output_dir(batch["out"], gt_map, max_side=480)
    assert len([r for r in res.values() if "vs_reference" in r]) == 2
    # 480 px test images: a 1 px registration border around fully clipped windows and the line
    # detector's precision weigh ~5x more than at 2400 px, so the limits here are relaxed; the
    # SPEC limits are checked on full-size outputs by tools/evaluate.py (README, reports/)
    for name, r in res.items():
        sm = r["summary"]
        assert sm["crushed_%"] < 0.5
        if "vs_reference" in r:
            assert sm["ssim"] > 0.8, (name, sm)
            assert sm["vert_med_deg"] is None or sm["vert_med_deg"] < 1.0
            assert sm.get("win_clip_recov_%", 0) < 5
            assert sm["clipped_nonlight_%"] < 1.0


def test_single_mode_and_groups_file(synth, tmp_path, cfg):
    from estatehdr.batch import run_batch
    from estatehdr.config import load_config
    from estatehdr.grouping import Group, save_groups
    from estatehdr.io.metadata import read_metadata
    g = Group("my_series", [read_metadata(os.path.join(synth["input"], f)) for f in ("IMG_0001.jpg", "IMG_0003.jpg")])
    p = str(tmp_path / "groups.json")
    save_groups([g], p)
    out = str(tmp_path / "o")
    rep = run_batch(synth["input"], out, load_config(None, "airy", ["runtime.workers=1"]), groups_file=p)
    assert [s["name"] for s in rep["series"]] == ["my_series"] and rep["ok"] == 1
    rep2 = run_batch(None, str(tmp_path / "o2"), load_config(None, None, ["grouping.mode=single", "runtime.workers=1"]),
                     files=[os.path.join(synth["input"], "IMG_0011.jpg")])
    assert rep2["ok"] == 1


def test_metrics_basics():
    img = np.full((120, 160, 3), 0.6, np.float32)
    for x in range(20, 160, 30):
        cv2.line(img, (x, 5), (x, 115), (0.1, 0.1, 0.1), 2)
    assert M.verticality(img)["median_abs_deg"] < 0.2
    assert M.ssim(img, img) > 0.999
    n = M.neutrality(np.full((100, 100, 3), 0.7, np.float32), np.ones((100, 100), bool))
    assert n["delta_e_mean"] < 0.5
    h = M.histogram_stats(np.ones((10, 10, 3), np.float32))
    assert h["clipped_pct"] == 100


def test_cli_presets_and_process(synth, tmp_path):
    env = {**os.environ, "PYTHONPATH": ROOT}
    r = subprocess.run([sys.executable, "-m", "estatehdr", "presets"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "neutral" in r.stdout and "premium" in r.stdout
    out = str(tmp_path / "cli")
    r = subprocess.run([sys.executable, "-m", "estatehdr", "process", os.path.join(synth["input"], "IMG_0011.jpg"),
                        "-o", out, "--preset", "premium", "--workers", "1"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr[-2000:]
    assert json.loads(r.stdout.strip().splitlines()[-1])["ok"] == 1
    assert os.path.exists(os.path.join(out, "IMG_0011_full.jpg"))
    assert os.path.exists(os.path.join(out, "estatehdr.log"))

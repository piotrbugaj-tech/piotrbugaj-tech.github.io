"""Shared fixtures: a small synthetic dataset with ground truth (generated once per session)
and one batch run over it.  Everything runs from scratch in a temporary directory."""
import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from estatehdr.config import load_config  # noqa: E402

W, H = 480, 320


@pytest.fixture(scope="session")
def synth(tmp_path_factory):
    """living room (5 JPEG brackets, EXIF), bedroom (3 TIFF16, handheld + moving object),
    exterior (3 JPEG), single JPEG, 2 frames without EXIF, 1 truncated JPEG."""
    from estatehdr.synthetic import generate_dataset
    root = str(tmp_path_factory.mktemp("synth"))
    manifest = generate_dataset(root, width=W, height=H, scenes=["living_room", "bedroom"], supersample=1)
    return {"root": root, "input": os.path.join(root, "input"), "manifest": manifest}


@pytest.fixture(scope="session")
def cfg():
    return load_config(None, "neutral")


@pytest.fixture(scope="session")
def batch(synth, tmp_path_factory):
    """One full batch run (2 worker processes) over the synthetic folder."""
    from estatehdr.batch import run_batch
    out = str(tmp_path_factory.mktemp("out"))
    c = load_config(None, "neutral", ["runtime.workers=2"])
    events = []
    report = run_batch(synth["input"], out, c, progress_cb=events.append)
    with open(os.path.join(out, "report.json")) as fh:
        assert json.load(fh)["ok"] == report["ok"]
    return {"out": out, "report": report, "events": events}


def series_by_first(report, first_file):
    for s in report["series"]:
        if os.path.basename(s["files"][0]) == first_file:
            return s
    return None


def labels(synth, scene, kind="capture"):
    import cv2
    return cv2.imread(os.path.join(synth["root"], "gt", scene, f"labels_{kind}.png"), cv2.IMREAD_GRAYSCALE)


def rng():
    return np.random.default_rng(1234)

"""GPU path (OpenCV T-API / UMat): runs on any machine (without OpenCL it executes on the CPU)
and must give the same results as the plain numpy path."""
import numpy as np
import pytest

from estatehdr import accel, denoise, geometry, tonemap
from estatehdr.imgutil import box


@pytest.fixture
def umat_on():
    accel.setup("cpu", force_umat=True)
    yield
    accel.setup("cpu")


def _image():
    rng = np.random.default_rng(2)
    yy, xx = np.mgrid[0:640, 0:900].astype(np.float32)
    img = np.stack([0.5 + 0.3 * np.sin(xx / 37), 0.5 + 0.3 * np.cos(yy / 23), 0.4 + 0.2 * np.sin((xx + yy) / 51)], -1)
    img[:, 300:303] = 0.05
    img[:, 600:603] = 0.05
    return np.clip(img + rng.normal(0, 0.01, img.shape), 0, 1).astype(np.float32)


def test_setup_falls_back_to_cpu_without_opencl():
    name = accel.setup("gpu")
    assert name == "cpu" or name.startswith("opencl")
    accel.setup("cpu")
    assert accel.device() == "cpu"


def test_umat_path_matches_numpy(cfg, umat_on):
    img = _image()
    ref = {}
    accel.setup("cpu")  # plain path
    ref["box"] = box(img, 7)
    ref["geo"] = geometry.correct(img.copy(), cfg, None)[0]
    ref["tm"] = tonemap.tone_map((img ** 2.2) * 4, dict(cfg["tonemap"]), analysis_side=300)
    ref["dn"] = denoise.denoise(img.copy(), cfg)
    accel.setup("cpu", force_umat=True)  # UMat path
    assert np.abs(box(img, 7) - ref["box"]).max() < 1e-4
    assert np.abs(geometry.correct(img.copy(), cfg, None)[0] - ref["geo"]).max() < 2e-3
    assert np.abs(tonemap.tone_map((img ** 2.2) * 4, dict(cfg["tonemap"]), analysis_side=300) - ref["tm"]).max() < 1e-3
    assert np.abs(denoise.denoise(img.copy(), cfg) - ref["dn"]).max() < 2e-3

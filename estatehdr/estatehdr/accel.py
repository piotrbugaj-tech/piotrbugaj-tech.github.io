"""Optional GPU acceleration through OpenCV's transparent API (OpenCL, ``cv2.UMat``).

``runtime.device`` in config.yaml: ``auto`` | ``gpu`` | ``cpu``.
  auto / gpu -> OpenCL when a device is present (NVIDIA, AMD, Intel, Apple drivers),
                otherwise the CPU (``gpu`` only logs a warning);
  cpu        -> OpenCL off.
Only the OpenCV calls on full-resolution data go through UMat (geometry remap, merge warps,
guided-filter box filters, Gaussian blurs, non-local means); the numpy parts stay on the CPU.
Without OpenCL the UMat code path still runs (on the CPU), which is how it is tested.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from .config import mode_of

log = logging.getLogger(__name__)
_STATE = {"device": "cpu", "umat": False}
MIN_PIXELS = 250_000  # smaller arrays are not worth the transfer


def setup(device: str = "auto", force_umat: bool = False) -> str:
    want = mode_of(device)
    name = "cpu"
    use = False
    if want not in ("cpu", "off"):
        try:
            if cv2.ocl.haveOpenCL():
                cv2.ocl.setUseOpenCL(True)
                dev = cv2.ocl.Device.getDefault()
                name = f"opencl:{dev.name()}" if dev is not None else "opencl"
                use = True
            elif want == "gpu":
                log.warning("GPU requested but no OpenCL device is available - using the CPU")
        except Exception as exc:  # broken drivers must never stop processing
            log.warning("OpenCL initialisation failed (%s) - using the CPU", exc)
    if not use:
        try:
            cv2.ocl.setUseOpenCL(False)
        except Exception:
            pass
    _STATE["device"] = name
    _STATE["umat"] = use or force_umat
    return name


def device() -> str:
    return _STATE["device"]


def cv(fn, *args, **kw):
    """Call an OpenCV function, through UMat when acceleration is on; always returns numpy."""
    if not _STATE["umat"]:
        return fn(*args, **kw)
    conv = []
    for a in args:
        if isinstance(a, np.ndarray) and a.size >= MIN_PIXELS:
            conv.append(cv2.UMat(np.ascontiguousarray(a)))
        else:
            conv.append(a)
    r = fn(*conv, **kw)
    if isinstance(r, cv2.UMat):
        return r.get()
    if isinstance(r, tuple):
        return tuple(x.get() if isinstance(x, cv2.UMat) else x for x in r)
    return r

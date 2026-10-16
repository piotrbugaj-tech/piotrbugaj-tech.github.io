"""Pixel decoding for RAW / JPEG / TIFF / PNG.

Images are returned as integer arrays (uint8 or uint16, RGB order) to keep
memory low for 24-60 Mpx files; conversion to float happens per stage.
The ``encoding`` field tells the linearisation stage what the code values
mean: ``linear`` (RAW, linear TIFF), ``srgb`` (JPEG/PNG/8-bit TIFF) or
``unknown`` (16-bit TIFF without colour information; decided per series).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from .metadata import file_kind

log = logging.getLogger(__name__)


class DecodeError(RuntimeError):
    pass


@dataclass
class Decoded:
    image: np.ndarray  # HxWx3 uint8/uint16, RGB
    encoding: str  # linear | srgb | unknown
    max_value: float

    def as_float(self) -> np.ndarray:
        return self.image.astype(np.float32) * np.float32(1.0 / self.max_value)


def _decode_raw(path: str, half: bool, raw_cfg: dict) -> Decoded:
    import rawpy
    hl = {"clip": rawpy.HighlightMode.Clip, "ignore": rawpy.HighlightMode.Ignore,
          "blend": rawpy.HighlightMode.Blend}.get(str(raw_cfg.get("highlight_mode", "clip")).lower(),
                                                 rawpy.HighlightMode.Clip)
    try:
        with rawpy.imread(path) as r:
            rgb = r.postprocess(gamma=(1, 1), no_auto_bright=True, output_bps=16,
                                use_camera_wb=bool(raw_cfg.get("use_camera_wb", True)),
                                output_color=rawpy.ColorSpace.sRGB, highlight_mode=hl,
                                half_size=half, user_sat=None,
                                demosaic_algorithm=None if half else rawpy.DemosaicAlgorithm.AHD)
    except Exception as exc:  # LibRaw errors are of several types
        raise DecodeError(f"RAW decode failed: {exc}") from exc
    return Decoded(rgb, "linear", 65535.0)


def _decode_tiff(path: str) -> Decoded:
    import tifffile
    try:
        with tifffile.TiffFile(path) as tf:
            page = tf.pages[0]
            arr = page.asarray()
            has_icc = 34675 in page.tags
    except Exception as exc:
        raise DecodeError(f"TIFF decode failed: {exc}") from exc
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, -1)
    if arr.shape[-1] == 4:
        arr = arr[..., :3]
    if arr.dtype == np.uint8:
        return Decoded(np.ascontiguousarray(arr), "srgb", 255.0)
    if arr.dtype == np.uint16:
        return Decoded(np.ascontiguousarray(arr), "srgb" if has_icc else "unknown", 65535.0)
    if arr.dtype in (np.float32, np.float64, np.float16):
        a = np.clip(arr.astype(np.float32), 0, None)
        m = max(float(a.max()), 1e-6)
        return Decoded((np.clip(a / m, 0, 1) * 65535).astype(np.uint16), "linear", 65535.0)
    raise DecodeError(f"unsupported TIFF dtype {arr.dtype}")


def _decode_cv(path: str) -> Decoded:
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        raise DecodeError("empty file")
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise DecodeError("image decoder returned nothing (corrupt or unsupported file)")
    # cv2.imdecode with IMREAD_UNCHANGED ignores EXIF orientation -> apply it ourselves
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        img = img[..., :3]
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    maxv = 65535.0 if img.dtype == np.uint16 else 255.0
    return Decoded(np.ascontiguousarray(img), "srgb", maxv)


def _check_truncated_jpeg(path: str):
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 2))
        tail = fh.read(2)
    if tail != b"\xff\xd9":
        raise DecodeError("JPEG is truncated (missing end-of-image marker)")


def apply_orientation(img: np.ndarray, orientation: int) -> np.ndarray:
    if orientation in (None, 1):
        return img
    ops = {2: lambda a: a[:, ::-1], 3: lambda a: a[::-1, ::-1], 4: lambda a: a[::-1],
           5: lambda a: np.swapaxes(a, 0, 1), 6: lambda a: np.swapaxes(a, 0, 1)[:, ::-1],
           7: lambda a: np.swapaxes(a, 0, 1)[::-1, ::-1], 8: lambda a: np.swapaxes(a, 0, 1)[::-1]}
    f = ops.get(int(orientation))
    return np.ascontiguousarray(f(img)) if f else img


def decode(path: str, orientation: int = 1, half: bool = False, raw_cfg: dict | None = None) -> Decoded:
    kind = file_kind(path)
    if kind == "raw":
        return _decode_raw(path, half, raw_cfg or {})
    if kind == "tiff":
        d = _decode_tiff(path)
        d.image = apply_orientation(d.image, orientation)
        if half:
            d.image = d.image[::2, ::2].copy()
        return d
    if kind in ("jpeg", "png"):
        if kind == "jpeg":
            _check_truncated_jpeg(path)
        d = _decode_cv(path)
        d.image = apply_orientation(d.image, orientation)
        if half:
            d.image = cv2.resize(d.image, (d.image.shape[1] // 2, d.image.shape[0] // 2),
                                 interpolation=cv2.INTER_AREA)
        return d
    raise DecodeError(f"unsupported file type: {path}")

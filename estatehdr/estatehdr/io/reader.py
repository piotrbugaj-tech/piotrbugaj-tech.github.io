"""Pixel decoding for RAW / JPEG / TIFF / PNG.

Images are returned as integer arrays (uint8 or uint16, RGB order) to keep
memory low for 24-60 Mpx files; conversion to float happens per stage.
The ``encoding`` field tells the linearisation stage what the code values
mean: ``linear`` (RAW, linear TIFF), ``srgb`` (JPEG/PNG/8-bit TIFF) or
``unknown`` (16-bit TIFF without colour information; decided per series).
Embedded ICC profiles other than sRGB are converted to sRGB (``icc.py``).
"""
from __future__ import annotations

import io
import logging
import os
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
    icc: str | None = None  # description of the input profile the pixels were converted from

    def as_float(self) -> np.ndarray:
        return self.image.astype(np.float32) * np.float32(1.0 / self.max_value)


def _decode_raw(path: str, half: bool, raw_cfg: dict) -> Decoded:
    import rawpy
    hl = {"clip": rawpy.HighlightMode.Clip, "ignore": rawpy.HighlightMode.Ignore,
          "blend": rawpy.HighlightMode.Blend}.get(str(raw_cfg.get("highlight_mode", "clip")).lower(),
                                                 rawpy.HighlightMode.Clip)
    algo = {"ahd": rawpy.DemosaicAlgorithm.AHD, "dht": rawpy.DemosaicAlgorithm.DHT,
            "aahd": rawpy.DemosaicAlgorithm.AAHD, "vng": rawpy.DemosaicAlgorithm.VNG,
            "linear": rawpy.DemosaicAlgorithm.LINEAR}.get(str(raw_cfg.get("demosaic", "dht")).lower(),
                                                         rawpy.DemosaicAlgorithm.DHT)
    fbdd = rawpy.FBDDNoiseReductionMode.Full if raw_cfg.get("fbdd") else rawpy.FBDDNoiseReductionMode.Off
    try:
        with rawpy.imread(path) as r:
            rgb = r.postprocess(gamma=(1, 1), no_auto_bright=True, output_bps=16,
                                use_camera_wb=bool(raw_cfg.get("use_camera_wb", True)),
                                output_color=rawpy.ColorSpace.sRGB, highlight_mode=hl,
                                half_size=half, user_sat=None, fbdd_noise_reduction=fbdd,
                                demosaic_algorithm=None if half else algo)
    except Exception as exc:  # LibRaw errors are of several types
        raise DecodeError(f"RAW decode failed: {exc}") from exc
    return Decoded(rgb, "linear", 65535.0)


def _decode_tiff(path: str) -> tuple[Decoded, bytes | None]:
    import tifffile
    try:
        with tifffile.TiffFile(path) as tf:
            page = tf.pages[0]
            arr = page.asarray()
            icc = page.tags[34675].value if 34675 in page.tags else None
    except Exception as exc:
        raise DecodeError(f"TIFF decode failed: {exc}") from exc
    icc = bytes(icc) if icc else None
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, -1)
    if arr.shape[-1] == 4:
        arr = arr[..., :3]
    if arr.dtype == np.uint8:
        return Decoded(np.ascontiguousarray(arr), "srgb", 255.0), icc
    if arr.dtype == np.uint16:
        return Decoded(np.ascontiguousarray(arr), "srgb" if icc else "unknown", 65535.0), icc
    if arr.dtype in (np.float32, np.float64, np.float16):
        a = np.clip(arr.astype(np.float32), 0, None)
        m = max(float(a.max()), 1e-6)
        return Decoded((np.clip(a / m, 0, 1) * 65535).astype(np.uint16), "linear", 65535.0), icc
    raise DecodeError(f"unsupported TIFF dtype {arr.dtype}")


def _decode_cv(data: np.ndarray) -> Decoded:
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


def jpeg_scan(buf: bytes) -> tuple[bool, bytes | None]:
    """(complete, embedded ICC profile) of a JPEG file's bytes.  Complete = an EOI marker follows
    the first scan of the main image.  Marker segments before it are skipped by their length
    fields (the EXIF thumbnail's own EOI inside APP1 does not count) and entropy-coded data
    cannot contain FFD9 (byte stuffing; RSTn are FFD0-FFD7), so data appended after EOI
    (Samsung trailers, Motion Photo videos, padding) is fine."""
    n = len(buf)
    if n < 4 or buf[0] != 0xFF or buf[1] != 0xD8:
        return True, None  # not a JPEG stream: the decoder reports it
    chunks = {}
    i = 2
    while i + 4 <= n:
        if buf[i] != 0xFF:  # stray byte between segments: resynchronise
            i += 1
            continue
        m = buf[i + 1]
        if m == 0xFF:  # fill byte
            i += 1
            continue
        if m == 0x01 or 0xD0 <= m <= 0xD8:  # markers without a length field
            i += 2
            continue
        if m == 0xD9:  # EOI before any image data
            break
        seg = (buf[i + 2] << 8) | buf[i + 3]
        if m == 0xE2 and seg > 16 and buf[i + 4:i + 16] == b"ICC_PROFILE\0":
            chunks[buf[i + 16]] = buf[i + 18:i + 2 + seg]
        if m == 0xDA:  # start of scan
            return buf.find(b"\xff\xd9", i + 2 + seg) >= 0, (b"".join(chunks[k] for k in sorted(chunks)) or None)
        i += 2 + seg
    return False, None


def _png_icc(buf: bytes) -> bytes | None:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(buf)) as im:
            return im.info.get("icc_profile") or None
    except Exception:
        return None


def _color_manage(d: Decoded, icc: bytes | None, path: str):
    """Convert pixels tagged with a non-sRGB ICC profile to sRGB (in place)."""
    if not icc:
        return
    from . import icc as icc_mod
    try:
        need, desc = icc_mod.inspect(icc)
        if not need:
            return
        icc_mod.to_srgb(d.image, icc, linear=d.encoding == "linear")
    except Exception as exc:  # broken / unsupported profile: keep the pixels as they are
        log.warning("%s: embedded ICC profile not applied (%s); assuming sRGB", os.path.basename(path), exc)
        return
    d.icc = desc
    log.info("%s: converted from ICC profile '%s' to sRGB", os.path.basename(path), desc)


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
        d, icc = _decode_tiff(path)
        d.image = apply_orientation(d.image, orientation)
        if half:
            d.image = d.image[::2, ::2].copy()
        _color_manage(d, icc, path)
        return d
    if kind in ("jpeg", "png"):
        try:
            with open(path, "rb") as fh:
                buf = fh.read()
        except OSError as exc:
            raise DecodeError(f"cannot read file: {exc}") from exc
        if kind == "jpeg":
            complete, icc = jpeg_scan(buf)
            if not complete:
                raise DecodeError("JPEG is truncated (missing end-of-image marker)")
        else:
            icc = _png_icc(buf)
        d = _decode_cv(np.frombuffer(buf, np.uint8))
        del buf
        d.image = apply_orientation(d.image, orientation)
        if half:
            d.image = cv2.resize(d.image, (d.image.shape[1] // 2, d.image.shape[0] // 2),
                                 interpolation=cv2.INTER_AREA)
        _color_manage(d, icc, path)
        return d
    raise DecodeError(f"unsupported file type: {path}")

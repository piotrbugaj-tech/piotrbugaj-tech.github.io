"""Export: sRGB JPEG (embedded ICC profile + EXIF) in several sizes."""
from __future__ import annotations

import io
import logging
import os
import struct
from datetime import datetime
from fractions import Fraction

import cv2
import numpy as np
from PIL import Image

from .. import __version__
from .metadata import FrameMeta

log = logging.getLogger(__name__)

_SRGB_ICC: bytes | None = None
SRGB_ICC_DESCRIPTION = "sRGB IEC61966-2.1 (EstateHDR)"
_D50 = (0xF6D6, 0x10000, 0xD32D)  # PCS illuminant, s15Fixed16
# sRGB colorants adapted to D50 (Bradford), as in LittleCMS's built-in sRGB, s15Fixed16 (columns sum to D50)
_SRGB_COLORANTS = ((0x6FA0, 0x38F5, 0x0390), (0x6297, 0xB787, 0x18D9), (0x249F, 0x0F84, 0xB6C3))


def _srgb_icc_v2() -> bytes:
    """ICC v2.1 matrix/TRC display profile of sRGB, built here byte for byte (deterministic, no profile
    files): D50 media white (display-profile convention), the colorants above, a 1024-entry 'curv' of
    the sRGB transfer function shared by the three channels, 'desc' and 'cprt'.  v2 because some
    viewers and upload pipelines ignore v4 profiles such as LittleCMS's own 'sRGB built-in' (v4.4)."""
    def xyz(v):
        return b"XYZ " + bytes(4) + struct.pack(">3i", *v)
    x = np.linspace(0.0, 1.0, 1024)
    lin = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    curv = b"curv" + bytes(4) + struct.pack(">I", x.size) + np.round(lin * 65535).astype(">u2").tobytes()
    d = SRGB_ICC_DESCRIPTION.encode("ascii") + b"\0"
    tags = [(b"desc", b"desc" + bytes(4) + struct.pack(">I", len(d)) + d + bytes(4 + 4 + 2 + 1 + 67)),
            (b"cprt", b"text" + bytes(4) + b"No copyright, use freely.\0"), (b"wtpt", xyz(_D50)),
            (b"rXYZ", xyz(_SRGB_COLORANTS[0])), (b"gXYZ", xyz(_SRGB_COLORANTS[1])),
            (b"bXYZ", xyz(_SRGB_COLORANTS[2])), (b"rTRC", curv), (b"gTRC", curv), (b"bTRC", curv)]
    table, data, offsets = b"", b"", {}
    start = 128 + 4 + 12 * len(tags)
    for sig, body in tags:
        if body not in offsets:  # identical tag data is stored once
            data += bytes(-len(data) % 4)
            offsets[body] = start + len(data)
            data += body
        table += sig + struct.pack(">II", offsets[body], len(body))
    data += bytes(-len(data) % 4)
    size = start + len(data)
    hdr = (struct.pack(">I4sI4s4s4s6H4s", size, bytes(4), 0x02100000, b"mntr", b"RGB ", b"XYZ ",
                       2026, 10, 16, 0, 0, 0, b"acsp")
           + bytes(24) + struct.pack(">I3i", 0, *_D50) + bytes(48))  # platform..attributes, intent, PCS white
    assert len(hdr) == 128
    return hdr + struct.pack(">I", len(tags)) + table + data


def srgb_icc() -> bytes:
    """The sRGB profile embedded in every export (ICC v2, see ``_srgb_icc_v2``)."""
    global _SRGB_ICC
    if _SRGB_ICC is None:
        _SRGB_ICC = _srgb_icc_v2()
    return _SRGB_ICC


def _rat(x: float, limit: int = 100000):
    fr = Fraction(float(x)).limit_denominator(limit)
    return (fr.numerator, fr.denominator)


def build_exif(ref: FrameMeta | None, width: int, height: int, description: str) -> bytes:
    import piexif
    exif = None
    if ref is not None and ref.kind == "jpeg":
        try:
            exif = piexif.load(ref.path)
        except Exception:
            exif = None
    if exif is None:
        exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
        if ref is not None:
            if ref.make:
                exif["0th"][piexif.ImageIFD.Make] = ref.make.encode(errors="ignore")
            if ref.model:
                exif["0th"][piexif.ImageIFD.Model] = ref.model.encode(errors="ignore")
            if ref.lens:
                exif["Exif"][piexif.ExifIFD.LensModel] = ref.lens.encode(errors="ignore")
            if ref.exposure_time:
                exif["Exif"][piexif.ExifIFD.ExposureTime] = _rat(ref.exposure_time)
            if ref.fnumber:
                exif["Exif"][piexif.ExifIFD.FNumber] = _rat(ref.fnumber, 100)
            if ref.iso:
                exif["Exif"][piexif.ExifIFD.ISOSpeedRatings] = int(ref.iso)
            if ref.focal_length:
                exif["Exif"][piexif.ExifIFD.FocalLength] = _rat(ref.focal_length, 1000)
            if ref.focal_35mm:
                exif["Exif"][piexif.ExifIFD.FocalLengthIn35mmFilm] = int(ref.focal_35mm)
            if ref.timestamp and ref.timestamp_source == "exif":
                s = datetime.fromtimestamp(ref.timestamp).strftime("%Y:%m:%d %H:%M:%S").encode()
                exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = s
                exif["0th"][piexif.ImageIFD.DateTime] = s
    # values that must describe the *output* file
    exif["0th"][piexif.ImageIFD.Orientation] = 1
    exif["0th"][piexif.ImageIFD.Software] = f"EstateHDR {__version__}".encode()
    exif["0th"][piexif.ImageIFD.ImageDescription] = description.encode(errors="ignore")[:250]
    for k in (piexif.ImageIFD.ImageWidth, piexif.ImageIFD.ImageLength, piexif.ImageIFD.StripOffsets,
              piexif.ImageIFD.StripByteCounts, piexif.ImageIFD.BitsPerSample, piexif.ImageIFD.Compression):
        exif["0th"].pop(k, None)
    exif["Exif"][piexif.ExifIFD.PixelXDimension] = int(width)
    exif["Exif"][piexif.ExifIFD.PixelYDimension] = int(height)
    exif["Exif"][piexif.ExifIFD.ColorSpace] = 1
    # drop maker notes and stale thumbnails (they describe the source frame)
    exif["Exif"].pop(piexif.ExifIFD.MakerNote, None)
    exif["1st"] = {}
    exif["thumbnail"] = None
    exif.pop("Interop", None)
    try:
        return piexif.dump(exif)
    except Exception as exc:  # malformed source EXIF -> minimal block
        log.warning("EXIF from source could not be re-encoded (%s); writing minimal EXIF", exc)
        return build_exif(None, width, height, description)


def resize_long_edge(img: np.ndarray, long_edge: int) -> np.ndarray:
    h, w = img.shape[:2]
    if not long_edge or max(h, w) <= long_edge:
        return img
    s = long_edge / max(h, w)
    return cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)


def to_uint8(img: np.ndarray) -> np.ndarray:
    """Float display-referred sRGB [0,1] -> uint8 with light dithering (avoids banding in skies/walls).
    Works in row strips so a 60 Mpx image needs no full-size float temporaries."""
    rng = np.random.default_rng(12345)
    h, w = img.shape[:2]
    out = np.empty(img.shape, np.uint8)
    rows = max(16, 4_000_000 // max(w, 1))
    for r0 in range(0, h, rows):
        r1 = min(h, r0 + rows)
        noise = (rng.random((r1 - r0, w), dtype=np.float32) - 0.5) * (1.0 / 255.0)
        x = img[r0:r1] + (noise[..., None] if img.ndim == 3 else noise)
        x *= 255.0
        np.round(x, out=x)
        np.clip(x, 0, 255, out=x)
        out[r0:r1] = x
    return out


def write_jpeg(path: str, img8: np.ndarray, quality: int, exif: bytes | None, progressive: bool = True,
               subsampling: str = "4:4:4", icc: bool = True):
    """``icc``: embed the sRGB profile (export.icc: srgb | none)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    im = Image.fromarray(img8, "RGB")
    kw = dict(quality=int(quality), optimize=True, progressive=progressive,
              subsampling={"4:4:4": 0, "4:2:2": 1, "4:2:0": 2}.get(subsampling, 0))
    if icc:
        kw["icc_profile"] = srgb_icc()
    if exif:
        kw["exif"] = exif
    tmp = path + ".part"
    im.save(tmp, "JPEG", **kw)
    os.replace(tmp, path)


def write_tiff16(path: str, img: np.ndarray, icc: bool = True):
    import tifffile
    arr = np.clip(np.round(img * 65535.0), 0, 65535).astype(np.uint16)
    tifffile.imwrite(path, arr, photometric="rgb", compression="zlib", software=f"EstateHDR {__version__}",
                     extratags=[(34675, "B", len(srgb_icc()), srgb_icc(), True)] if icc else [])


def jpeg_bytes(img8: np.ndarray, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(img8, "RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()

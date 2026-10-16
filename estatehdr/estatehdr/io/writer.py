"""Export: sRGB JPEG (embedded ICC profile + EXIF) in several sizes."""
from __future__ import annotations

import io
import logging
import os
from datetime import datetime
from fractions import Fraction

import cv2
import numpy as np
from PIL import Image, ImageCms

from .. import __version__
from .metadata import FrameMeta

log = logging.getLogger(__name__)

_SRGB_ICC: bytes | None = None


def srgb_icc() -> bytes:
    global _SRGB_ICC
    if _SRGB_ICC is None:
        prof = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
        _SRGB_ICC = prof.tobytes()
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
               subsampling: str = "4:4:4"):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    im = Image.fromarray(img8, "RGB")
    kw = dict(quality=int(quality), optimize=True, progressive=progressive, icc_profile=srgb_icc(),
              subsampling={"4:4:4": 0, "4:2:2": 1, "4:2:0": 2}.get(subsampling, 0))
    if exif:
        kw["exif"] = exif
    tmp = path + ".part"
    im.save(tmp, "JPEG", **kw)
    os.replace(tmp, path)


def write_tiff16(path: str, img: np.ndarray):
    import tifffile
    arr = np.clip(np.round(img * 65535.0), 0, 65535).astype(np.uint16)
    tifffile.imwrite(path, arr, photometric="rgb", compression="zlib",
                     extratags=[(34675, "B", len(srgb_icc()), srgb_icc(), True)])


def jpeg_bytes(img8: np.ndarray, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(img8, "RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()

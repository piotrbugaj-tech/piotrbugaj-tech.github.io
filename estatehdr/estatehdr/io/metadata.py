"""Fast metadata extraction (EXIF) for JPEG, TIFF and RAW files.

Never decodes pixel data unless the EXIF parser fails for a RAW file (then
LibRaw's own metadata is used).  Missing values stay ``None``; callers must
cope with partial metadata.
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from fractions import Fraction

log = logging.getLogger(__name__)
logging.getLogger("exifread").setLevel(logging.ERROR)  # "file has no EXIF" is normal, not a warning

RAW_EXTS = {".dng", ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".raf", ".orf", ".rw2", ".pef",
            ".srw", ".x3f", ".3fr", ".iiq", ".erf", ".mos", ".mrw", ".rwl", ".kdc", ".dcr"}
JPEG_EXTS = {".jpg", ".jpeg", ".jpe"}
TIFF_EXTS = {".tif", ".tiff"}
OTHER_EXTS = {".png"}
SUPPORTED_EXTS = RAW_EXTS | JPEG_EXTS | TIFF_EXTS | OTHER_EXTS


def file_kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXTS:
        return "raw"
    if ext in JPEG_EXTS:
        return "jpeg"
    if ext in TIFF_EXTS:
        return "tiff"
    if ext in OTHER_EXTS:
        return "png"
    return "unknown"


@dataclass
class FrameMeta:
    path: str
    kind: str
    width: int | None = None
    height: int | None = None
    exposure_time: float | None = None
    fnumber: float | None = None
    iso: float | None = None
    exposure_bias: float | None = None
    timestamp: float | None = None  # seconds since epoch (local time of the camera)
    timestamp_source: str = "none"  # exif | mtime | none
    make: str | None = None
    model: str | None = None
    serial: str | None = None
    lens: str | None = None
    focal_length: float | None = None
    focal_35mm: float | None = None
    orientation: int = 1
    software: str | None = None
    errors: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def camera_id(self) -> str:
        return "|".join(str(x) for x in (self.make, self.model, self.serial) if x)

    @property
    def exposure_value(self) -> float | None:
        """log2 of the photometric exposure (t * ISO / N^2); larger = brighter image."""
        if self.exposure_time is None or self.exposure_time <= 0:
            return None
        n = self.fnumber if self.fnumber and self.fnumber > 0 else 8.0
        iso = self.iso if self.iso and self.iso > 0 else 100.0
        return math.log2(self.exposure_time * iso / (n * n))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["exposure_value"] = self.exposure_value
        return d


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        vals = getattr(v, "values", v)
        if isinstance(vals, (list, tuple)):
            if not vals:
                return None
            vals = vals[0]
        if hasattr(vals, "num") and hasattr(vals, "den"):
            return float(vals.num) / float(vals.den) if vals.den else None
        if isinstance(vals, Fraction):
            return float(vals)
        s = str(vals)
        if "/" in s:
            a, b = s.split("/", 1)
            return float(a) / float(b) if float(b) else None
        return float(s)
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def _to_str(v) -> str | None:
    if v is None:
        return None
    s = str(getattr(v, "printable", v)).strip().strip("\x00").strip()
    return s or None


def _parse_dt(s: str | None, subsec: str | None = None) -> float | None:
    if not s:
        return None
    s = s.strip().strip("\x00")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S%z"):
        try:
            ts = datetime.strptime(s[:19], fmt[:17] if fmt.endswith("%z") else fmt).timestamp()
            break
        except ValueError:
            continue
    else:
        return None
    if subsec:
        digits = "".join(ch for ch in subsec if ch.isdigit())
        if digits:
            ts += float("0." + digits)
    return ts


def _pick(tags: dict, *names):
    for n in names:
        for prefix in ("EXIF ", "Image ", "MakerNote ", ""):
            k = prefix + n
            if k in tags:
                return tags[k]
    return None


def largest_dimensions(tags: dict) -> tuple[int | None, int | None]:
    """Largest width x height pair over all IFDs of an EXIF/TIFF tag dict (exifread names:
    "Image ImageWidth", "EXIF SubIFD0 ImageWidth", "EXIF ExifImageWidth", ...).  In NEF / DNG
    files IFD0 often describes a small preview; the full image is in a sub-IFD."""
    best, bw, bh = 0, None, None
    for k in tags:
        for wk, hk in (("ImageWidth", "ImageLength"), ("ExifImageWidth", "ExifImageLength")):
            if not k.endswith(" " + wk):
                continue
            w = _to_float(tags[k])
            h = _to_float(tags.get(k[: -len(wk)] + hk))
            if w and h and w * h > best:
                best, bw, bh = w * h, int(w), int(h)
    return bw, bh


RAW_MIN_PIXELS = 4_000_000  # smaller "image" sizes of a RAW file are previews, not the sensor


def read_metadata(path: str) -> FrameMeta:
    kind = file_kind(path)
    meta = FrameMeta(path=path, kind=kind)
    tags = {}
    try:
        import exifread
        with open(path, "rb") as fh:
            tags = exifread.process_file(fh, details=False, strict=False)
    except Exception as exc:  # exifread raises many kinds of errors on odd files
        meta.errors.append(f"exif: {exc}")
    if tags:
        meta.exposure_time = _to_float(_pick(tags, "ExposureTime"))
        if meta.exposure_time is None:
            sv = _to_float(_pick(tags, "ShutterSpeedValue"))
            if sv is not None:
                meta.exposure_time = 2.0 ** (-sv)
        meta.fnumber = _to_float(_pick(tags, "FNumber"))
        if meta.fnumber is None:
            av = _to_float(_pick(tags, "ApertureValue"))
            if av is not None:
                meta.fnumber = math.sqrt(2.0) ** av
        meta.iso = _to_float(_pick(tags, "ISOSpeedRatings", "PhotographicSensitivity", "ISO"))
        meta.exposure_bias = _to_float(_pick(tags, "ExposureBiasValue"))
        dt = _to_str(_pick(tags, "DateTimeOriginal")) or _to_str(_pick(tags, "DateTimeDigitized")) or _to_str(_pick(tags, "DateTime"))
        sub = _to_str(_pick(tags, "SubSecTimeOriginal", "SubSecTime"))
        ts = _parse_dt(dt, sub)
        if ts is not None:
            meta.timestamp, meta.timestamp_source = ts, "exif"
        meta.make = _to_str(_pick(tags, "Make"))
        meta.model = _to_str(_pick(tags, "Model"))
        meta.serial = _to_str(_pick(tags, "BodySerialNumber", "SerialNumber"))
        meta.lens = _to_str(_pick(tags, "LensModel"))
        meta.focal_length = _to_float(_pick(tags, "FocalLength"))
        meta.focal_35mm = _to_float(_pick(tags, "FocalLengthIn35mmFilm"))
        o = _pick(tags, "Orientation")
        if o is not None:
            try:
                meta.orientation = int(getattr(o, "values", [1])[0])
            except (ValueError, TypeError, IndexError):
                meta.orientation = 1
        meta.software = _to_str(tags.get("Image Software"))
        if kind == "raw":
            meta.width, meta.height = largest_dimensions(tags)
        else:
            meta.width = _to_float(_pick(tags, "ExifImageWidth", "ImageWidth"))
            meta.height = _to_float(_pick(tags, "ExifImageLength", "ImageLength"))
            meta.width = int(meta.width) if meta.width else None
            meta.height = int(meta.height) if meta.height else None
    if kind == "raw" and (meta.exposure_time is None or meta.timestamp is None or
                          (meta.width or 0) * (meta.height or 0) < RAW_MIN_PIXELS):
        _raw_fallback(meta)
    if kind in ("jpeg", "png", "tiff") and (meta.width is None or meta.height is None):
        try:
            from PIL import Image
            with Image.open(path) as im:
                meta.width, meta.height = im.size
        except Exception as exc:
            meta.errors.append(f"size: {exc}")
    if meta.timestamp is None:
        try:
            meta.timestamp = os.path.getmtime(path)
            meta.timestamp_source = "mtime"
        except OSError:
            pass
    return meta


def _raw_fallback(meta: FrameMeta):
    try:
        import rawpy
        with rawpy.imread(meta.path) as r:
            o = r.other
            if meta.exposure_time is None and o.shutter > 0:
                meta.exposure_time = float(o.shutter)
            if meta.fnumber is None and o.aperture > 0:
                meta.fnumber = float(o.aperture)
            if meta.iso is None and o.iso_speed > 0:
                meta.iso = float(o.iso_speed)
            if meta.focal_length is None and o.focal_len > 0:
                meta.focal_length = float(o.focal_len)
            if meta.timestamp is None and o.timestamp > 0:
                meta.timestamp, meta.timestamp_source = float(o.timestamp), "exif"
            # sensor size without unpacking / demosaicing (cheap)
            sz = r.sizes
            w, h = (sz.width, sz.height) if sz.width and sz.height else (sz.raw_width, sz.raw_height)
            if w and h and w * h > (meta.width or 0) * (meta.height or 0):
                meta.width, meta.height = int(w), int(h)
    except Exception as exc:
        meta.errors.append(f"rawpy-meta: {exc}")

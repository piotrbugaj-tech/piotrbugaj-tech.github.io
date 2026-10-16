"""Colour management of inputs: pixels tagged with an ICC profile other than sRGB (Adobe RGB
camera JPEGs, ProPhoto 16-bit TIFFs from Lightroom, Display P3, ...) are converted to sRGB,
which is what the rest of the pipeline (and the exported sRGB profile) assumes.

* 8-bit data: LittleCMS through Pillow's ImageCms, relative colorimetric, in row strips;
* 16-bit data (ImageCms has no 16-bit RGB modes): matrix/TRC profiles are evaluated in float
  (TRC tables + 3x3 matrix in the D50 PCS, as LittleCMS does); other profiles through a 3D LUT
  sampled with LittleCMS on an 8-bit grid and applied with trilinear interpolation.
"""
from __future__ import annotations

import io
import logging
import struct

import numpy as np
from PIL import Image, ImageCms

from ..imgutil import linear_to_srgb, row_strips

log = logging.getLogger(__name__)

_SRGB: dict = {}


def _srgb():
    if not _SRGB:
        prof = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
        _SRGB["profile"] = prof
        _SRGB["matrix"] = _matrix_trc(prof.tobytes())[0]
    return _SRGB


def _tags(icc: bytes) -> dict:
    n = struct.unpack(">I", icc[128:132])[0]
    out = {}
    for k in range(min(n, 200)):
        sig, off, size = struct.unpack(">4sII", icc[132 + 12 * k:144 + 12 * k])
        out[sig.decode("latin-1")] = icc[off:off + size]
    return out


def _trc(tag: bytes):
    """ICC 'curv' / 'para' tone curve -> vectorised function on [0, 1]."""
    kind = tag[:4]
    if kind == b"curv":
        n = struct.unpack(">I", tag[8:12])[0]
        if n == 0:
            return lambda x: x
        if n == 1:
            g = struct.unpack(">H", tag[12:14])[0] / 256.0
            return lambda x: np.power(x, g)
        table = np.frombuffer(tag[12:12 + 2 * n], ">u2").astype(np.float64) / 65535.0
        xs = np.linspace(0.0, 1.0, n)
        return lambda x: np.interp(x, xs, table)
    if kind == b"para":
        ftype = struct.unpack(">H", tag[8:10])[0]
        npar = {0: 1, 1: 3, 2: 4, 3: 5, 4: 7}[ftype]
        p = [v / 65536.0 for v in struct.unpack(f">{npar}i", tag[12:12 + 4 * npar])] + [0.0] * 6
        g, a, b, c, d, e, f = p[:7]

        def curve(x):
            if ftype == 0:
                return np.power(x, g)
            lin = np.power(np.maximum(a * x + b, 0.0), g)
            if ftype in (1, 2):
                thr = -b / a if a else 0.0
                off = c if ftype == 2 else 0.0
                return np.where(x >= thr, lin + off, off)
            if ftype == 3:
                return np.where(x >= d, lin, c * x)
            return np.where(x >= d, lin + e, c * x + f)
        return curve
    raise ValueError(f"unsupported tone curve type {kind!r}")


def _matrix_trc(icc: bytes):
    """(3x3 matrix RGB->XYZ(D50), [3 tone curves]) of a matrix/TRC RGB profile, else None."""
    try:
        t = _tags(icc)
        cols = []
        for c in "rgb":
            tag = t[f"{c}XYZ"]
            if tag[:4] != b"XYZ ":
                return None
            cols.append(np.array(struct.unpack(">3i", tag[8:20]), np.float64) / 65536.0)
        curves = [_trc(t[f"{c}TRC"]) for c in "rgb"]
    except (KeyError, ValueError, struct.error):
        return None
    return np.stack(cols, 1), curves


def inspect(icc: bytes) -> tuple[bool, str]:
    """(needs conversion, profile description).  sRGB = the description says so (and not
    'linear'), or the colorants and the tone curve match sRGB; non-RGB profiles are left alone."""
    p = ImageCms.ImageCmsProfile(io.BytesIO(icc)).profile
    desc = (p.profile_description or "").strip() or "unnamed ICC profile"
    if (p.xcolor_space or "").strip() != "RGB":
        return False, desc
    dl = desc.lower()
    if "srgb" in dl and "linear" not in dl:
        return False, desc
    mt = _matrix_trc(icc)
    if mt is not None:
        m, curves = mt
        same_primaries = np.allclose(m, _srgb()["matrix"], atol=0.004)
        same_curve = all(abs(float(c(np.float64(0.5))) - 0.2140) < 0.01 for c in curves)
        if same_primaries and same_curve:
            return False, desc
    return True, desc


def to_srgb(img: np.ndarray, icc: bytes, linear: bool = False) -> np.ndarray:
    """Convert integer RGB pixels (uint8 / uint16) tagged with ``icc`` to sRGB, in place.
    ``linear``: the codes are linear light (float TIFF) -> only the primaries are converted
    and the result stays linear."""
    if img.dtype == np.uint8 and not linear:
        t = ImageCms.buildTransform(ImageCms.ImageCmsProfile(io.BytesIO(icc)), _srgb()["profile"], "RGB", "RGB",
                                    renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)
        h, w = img.shape[:2]
        for r0, r1 in row_strips(h, w, 4_000_000):
            im = Image.fromarray(np.ascontiguousarray(img[r0:r1]), "RGB")
            ImageCms.applyTransform(im, t, inPlace=True)
            img[r0:r1] = np.asarray(im)
        return img
    if img.dtype != np.uint16:
        raise ValueError(f"unsupported pixel type {img.dtype}")
    mt = _matrix_trc(icc)
    if mt is not None:
        m, curves = mt
        mat = (np.linalg.inv(_srgb()["matrix"]) @ m).astype(np.float32)
        codes = np.arange(65536, dtype=np.float64) / 65535.0
        luts = [(codes if linear else np.clip(c(codes), 0, 1)).astype(np.float32) for c in curves]

        def apply(block):
            lin = np.clip(np.stack([luts[c][block[..., c]] for c in range(3)], -1) @ mat.T, 0, 1)
            return lin if linear else linear_to_srgb(lin)
    elif linear:
        raise ValueError("linear data with a non-matrix profile")
    else:
        lut = _lut3d(icc)

        def apply(block):
            return _trilinear(lut, block.astype(np.float32) * np.float32((lut.shape[0] - 1) / 65535.0))
    h, w = img.shape[:2]
    for r0, r1 in row_strips(h, w, 2_000_000):
        img[r0:r1] = np.clip(np.round(apply(img[r0:r1]) * 65535.0), 0, 65535).astype(np.uint16)
    return img


def _lut3d(icc: bytes, step: int = 3) -> np.ndarray:
    """N^3 x 3 table of the LittleCMS transform sampled on 8-bit grid nodes (multiples of ``step``)."""
    nodes = np.arange(0, 256, step, dtype=np.uint8)
    n = nodes.size
    r, g, b = np.meshgrid(nodes, nodes, nodes, indexing="ij")
    grid = np.ascontiguousarray(np.stack([r, g, b], -1).reshape(n * n, n, 3))
    to_srgb(grid, icc)
    return grid.reshape(n, n, n, 3).astype(np.float32) / 255.0


def _trilinear(lut: np.ndarray, x: np.ndarray) -> np.ndarray:
    n = lut.shape[0]
    i0 = np.clip(np.floor(x).astype(np.int32), 0, n - 2)
    f = x - i0
    out = 0.0
    for dr in (0, 1):
        wr = f[..., 0] if dr else 1 - f[..., 0]
        for dg in (0, 1):
            wg = f[..., 1] if dg else 1 - f[..., 1]
            for db in (0, 1):
                wb = f[..., 2] if db else 1 - f[..., 2]
                out = out + (wr * wg * wb)[..., None] * lut[i0[..., 0] + dr, i0[..., 1] + dg, i0[..., 2] + db]
    return out

"""Writing the final images in all configured sizes (+ small previews for the UI)."""
from __future__ import annotations

import logging
import os

import cv2
import numpy as np

from .imgutil import LUMA
from .io import writer

log = logging.getLogger(__name__)


def output_sharpen(img: np.ndarray, amount: float, radius: float, threshold: float) -> np.ndarray:
    """Unsharp mask on luminance with overshoot clamping (no bright/dark halos)."""
    if amount <= 0:
        return img
    y = img @ LUMA
    blur = cv2.GaussianBlur(y, (0, 0), max(0.3, radius))
    detail = y - blur
    detail = np.sign(detail) * np.maximum(np.abs(detail) - threshold, 0)
    ys = y + amount * detail
    # clamp to local min/max (3x3) to avoid halos
    k = np.ones((3, 3), np.uint8)
    lo = cv2.erode(y, k)
    hi = cv2.dilate(y, k)
    ys = np.clip(ys, lo - 0.02, hi + 0.02)
    out = img + (ys - y)[..., None]
    return np.clip(out, 0, 1).astype(np.float32)


def export_all(img: np.ndarray, group, ref_meta, cfg, out_dir: str, result: dict) -> dict:
    ecfg = cfg.get("export", {})
    scfg = cfg.get("sharpen", {})
    os.makedirs(out_dir, exist_ok=True)
    preset = cfg.get("preset", "neutral")
    desc = f"EstateHDR {preset}; merged {len(group.frames)} frame(s)"
    outputs = {}
    tmpl = ecfg.get("name_template", "{name}_{size}")
    h0, w0 = img.shape[:2]
    for size in ecfg.get("sizes", [{"name": "full", "long_edge": 0, "quality": 95}]):
        name = size.get("name", "full")
        im = writer.resize_long_edge(img, int(size.get("long_edge", 0) or 0))
        if scfg.get("enabled", True):
            scale = im.shape[1] / w0
            amt = float(scfg.get("amount", 0.35)) * float(size.get("sharpen", 1.0))
            rad = float(scfg.get("radius_px", 1.0)) * max(0.6, scale ** 0.5)
            im = output_sharpen(im, amt, rad, float(scfg.get("threshold", 0.01)))
        im8 = writer.to_uint8(im)
        fname = tmpl.format(name=group.name, size=name, preset=preset) + ".jpg"
        path = os.path.join(out_dir, fname)
        exif = None
        if ecfg.get("exif", "copy") != "none":
            exif = writer.build_exif(ref_meta if ecfg.get("exif", "copy") == "copy" else None,
                                     im8.shape[1], im8.shape[0], desc)
        writer.write_jpeg(path, im8, int(size.get("quality", 92)), exif, subsampling=ecfg.get("subsampling", "4:4:4"))
        outputs[name] = {"path": path, "width": int(im8.shape[1]), "height": int(im8.shape[0])}
    if ecfg.get("tiff16", False):
        path = os.path.join(out_dir, tmpl.format(name=group.name, size="full16", preset=preset) + ".tif")
        writer.write_tiff16(path, img)
        outputs["tiff16"] = {"path": path}
    if ecfg.get("save_previews", True):
        pdir = os.path.join(out_dir, ".previews")
        os.makedirs(pdir, exist_ok=True)
        after = writer.to_uint8(writer.resize_long_edge(img, 1600))
        p_after = os.path.join(pdir, f"{group.name}_after.jpg")
        writer.write_jpeg(p_after, after, 85, None)
        outputs["preview_after"] = {"path": p_after}
        before = _before_preview(group, result)
        if before is not None:
            p_before = os.path.join(pdir, f"{group.name}_before.jpg")
            writer.write_jpeg(p_before, before, 85, None)
            outputs["preview_before"] = {"path": p_before}
    return outputs


def _before_preview(group, result) -> np.ndarray | None:
    """Reference (middle) frame as the camera rendered it, for the before/after slider."""
    from .io.reader import decode
    ref_name = result.get("reference")
    meta = next((f for f in group.frames if f.name == ref_name), group.frames[len(group.frames) // 2])
    try:
        d = decode(meta.path, meta.orientation, half=True)
        img = d.as_float()
        if d.encoding == "linear":
            from .imgutil import linear_to_srgb
            y = img @ LUMA
            k = 0.18 / max(float(np.median(y)), 1e-4)
            img = linear_to_srgb(np.clip(img * k, 0, 1))
        return writer.to_uint8(writer.resize_long_edge(img, 1600))
    except Exception as exc:
        log.debug("before preview failed: %s", exc)
        return None

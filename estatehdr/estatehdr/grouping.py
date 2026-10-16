"""Automatic grouping of frames into bracket series.

Signals (in order of reliability):
  1. hard breaks: camera body, image size/orientation or focal length change;
  2. capture time gaps (EXIF DateTimeOriginal + SubSec, corrected by exposure time);
  3. exposure repetition: a bracket set never contains the same exposure twice;
  4. content similarity of tiny thumbnails (rank correlation is invariant to exposure);
  5. optional fixed bracket size from the configuration.
Groups can be corrected manually through a JSON file (see ``save_groups``/``load_groups``).
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from .io.metadata import FrameMeta, SUPPORTED_EXTS, read_metadata

log = logging.getLogger(__name__)


@dataclass
class Group:
    name: str
    frames: list  # list[FrameMeta]
    warnings: list = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.frames)

    def to_dict(self) -> dict:
        return {"name": self.name, "files": [f.path for f in self.frames], "warnings": self.warnings,
                "exposure_values": [f.exposure_value for f in self.frames]}


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def list_images(folder: str, recursive: bool = True) -> list[str]:
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ("estatehdr_output", "output"))
        for f in files:
            # <name>.mask.png files are removal masks, not photos
            if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS and not f.startswith(".") and \
                    not f.lower().endswith(".mask.png"):
                out.append(os.path.join(root, f))
        if not recursive:
            break
    return sorted(out, key=natural_key)


def thumbnail(meta: FrameMeta, size: int = 48) -> np.ndarray | None:
    """Small grayscale thumbnail (float32) used for content similarity."""
    img = None
    try:
        if meta.kind == "raw":
            import rawpy
            with rawpy.imread(meta.path) as r:
                try:
                    th = r.extract_thumb()
                    if th.format == rawpy.ThumbFormat.JPEG:
                        img = cv2.imdecode(np.frombuffer(th.data, np.uint8), cv2.IMREAD_GRAYSCALE)
                    else:
                        img = cv2.cvtColor(np.asarray(th.data), cv2.COLOR_RGB2GRAY)
                except Exception:
                    rgb = r.postprocess(half_size=True, output_bps=8)
                    img = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        elif meta.kind == "jpeg":
            img = cv2.imread(meta.path, cv2.IMREAD_REDUCED_GRAYSCALE_8)
        else:
            img = cv2.imread(meta.path, cv2.IMREAD_GRAYSCALE | cv2.IMREAD_ANYDEPTH)
            if img is not None and img.dtype != np.uint8:
                img = (img.astype(np.float32) / max(1.0, float(img.max())) * 255).astype(np.uint8)
    except Exception as exc:
        log.debug("thumbnail failed for %s: %s", meta.path, exc)
        return None
    if img is None:
        return None
    h, w = img.shape[:2]
    s = size / max(h, w)
    return cv2.resize(img, (max(2, round(w * s)), max(2, round(h * s))), interpolation=cv2.INTER_AREA).astype(np.float32)


def rank_similarity(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """Spearman correlation of gradient magnitudes: robust to exposure differences."""
    if a is None or b is None:
        return 1.0
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)

    def feat(x):
        x = cv2.GaussianBlur(x, (3, 3), 0)
        valid = (x > 3) & (x < 250)
        return x, valid
    xa, va = feat(a)
    xb, vb = feat(b)
    m = va & vb
    if m.sum() < 0.15 * m.size:
        m = np.ones_like(m)
    ra = np.argsort(np.argsort(xa[m])).astype(np.float32)
    rb = np.argsort(np.argsort(xb[m])).astype(np.float32)
    if ra.std() < 1e-6 or rb.std() < 1e-6:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def estimate_brightness_ev(thumb: np.ndarray | None) -> float | None:
    if thumb is None:
        return None
    lin = (thumb / 255.0) ** 2.2
    return float(np.log2(max(np.mean(lin), 1e-5)))


def group_frames(metas: list[FrameMeta], cfg: dict | None = None) -> list[Group]:
    cfg = cfg or {}
    mode = cfg.get("mode", "auto")
    fixed = int(cfg.get("bracket_size", 0) or 0)
    max_gap = float(cfg.get("max_gap_s", 6.0))
    min_sim = float(cfg.get("min_similarity", 0.35))
    ev_tol = float(cfg.get("ev_tolerance", 0.2))
    focal_tol = float(cfg.get("focal_tolerance", 0.05))
    if not metas:
        return []
    have_exif_time = sum(m.timestamp_source == "exif" for m in metas) >= 0.8 * len(metas)
    if have_exif_time:
        metas = sorted(metas, key=lambda m: (m.timestamp or 0.0, natural_key(m.name)))
    else:
        metas = sorted(metas, key=lambda m: natural_key(m.name))
    if mode == "single":
        return [Group(os.path.splitext(m.name)[0], [m]) for m in metas]
    thumbs = [thumbnail(m) for m in metas]
    # EXIF-based rules are applied per pair of frames, so a folder mixing camera files with
    # EXIF-less files (exports, screenshots) still groups the camera files by exposure/time
    evs = [m.exposure_value for m in metas]
    # without EXIF a bracket is recognised by a clear brightness step between near-identical
    # frames (measured: true brackets >= 1 EV / similarity >= 0.83, different photos of the same
    # property <= 0.3 EV / <= 0.63)
    bevs = [estimate_brightness_ev(t) if e is None else None for t, e in zip(thumbs, evs)]
    nx_step = float(cfg.get("noexif_min_ev_step", 0.4))
    nx_sim = float(cfg.get("noexif_min_similarity", 0.6))

    groups: list[list[int]] = [[0]]
    reasons = []
    for i in range(1, len(metas)):
        a, b = metas[i - 1], metas[i]
        cur = groups[-1]
        reason = None
        if a.camera_id and b.camera_id and a.camera_id != b.camera_id:
            reason = "camera"
        elif a.width and b.width and a.height and b.height and {a.width, a.height} != {b.width, b.height}:
            reason = "size"
        elif (a.width and b.width and a.height and b.height and
              (a.width > a.height) != (b.width > b.height)):
            reason = "orientation"
        elif a.focal_length and b.focal_length and abs(a.focal_length - b.focal_length) > focal_tol * a.focal_length:
            reason = "focal"
        elif (evs[i - 1] is None) != (evs[i] is None):
            # frames of one camera bracket carry the same kind of metadata
            reason = "metadata"
        elif a.timestamp_source == "exif" and b.timestamp_source == "exif" and \
                a.timestamp is not None and b.timestamp is not None and \
                abs(b.timestamp - a.timestamp) - (a.exposure_time or 0.0) > max_gap:
            reason = "time-gap"
        elif mode != "fixed" and evs[i] is not None and \
                any(evs[j] is not None and abs(evs[j] - evs[i]) < ev_tol for j in cur):
            reason = "exposure-repeat"
        elif fixed and len(cur) >= fixed:
            reason = "bracket-size"
        elif mode != "fixed" and evs[i] is None and bevs[i] is not None and \
                any(bevs[j] is not None and abs(bevs[j] - bevs[i]) < nx_step for j in cur):
            reason = "no-exposure-step"
        else:
            sim = rank_similarity(thumbs[i - 1], thumbs[i])
            if sim < (min_sim if evs[i] is not None else nx_sim):
                reason = f"content({sim:.2f})"
        if reason:
            groups.append([i])
            reasons.append(reason)
        else:
            cur.append(i)
    # fixed bracket size: split longer runs
    if fixed > 1:
        split = []
        for g in groups:
            for k in range(0, len(g), fixed):
                split.append(g[k:k + fixed])
        groups = split
    out = []
    sizes = [len(g) for g in groups]
    common = max(set(sizes), key=sizes.count) if sizes else 1
    for g in groups:
        frames = [metas[i] for i in g]
        name = os.path.splitext(frames[0].name)[0]
        grp = Group(name, frames)
        if fixed and len(g) != fixed:
            grp.warnings.append(f"incomplete series: {len(g)} of {fixed} frames")
        elif common > 1 and len(g) not in (1, common):
            grp.warnings.append(f"series has {len(g)} frames, most series have {common}")
        if len(frames) > 1 and any(f.exposure_value is None for f in frames):
            grp.warnings.append("no EXIF exposure data - exposures estimated from pixels")
        out.append(grp)
    log.info("grouped %d frames into %d series (sizes: %s)", len(metas), len(out),
             ", ".join(str(len(g.frames)) for g in out))
    return out


def scan_folder(folder: str, cfg: dict | None = None, recursive: bool = True):
    """Read metadata for all images; returns (groups, failures)."""
    paths = list_images(folder, recursive)
    metas, failures = [], []
    for p in paths:
        try:
            m = read_metadata(p)
            if os.path.getsize(p) == 0:
                raise ValueError("empty file")
            metas.append(m)
        except Exception as exc:
            failures.append({"file": p, "error": str(exc)})
            log.warning("skipping %s: %s", p, exc)
    return group_frames(metas, cfg), failures


def save_groups(groups: list[Group], path: str):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "groups": [g.to_dict() for g in groups]}, fh, indent=1)


def load_groups(path: str, base: str | None = None) -> list[Group]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for g in data.get("groups", []):
        frames = []
        for f in g["files"]:
            p = f if os.path.isabs(f) or base is None else os.path.join(base, f)
            frames.append(read_metadata(p))
        if frames:
            out.append(Group(g.get("name") or os.path.splitext(os.path.basename(frames[0].path))[0], frames,
                             list(g.get("warnings", []))))
    return out

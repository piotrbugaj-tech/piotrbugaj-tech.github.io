"""Automatic grouping of bracket series (EXIF + visual), manual groups file, robustness."""
import os
import shutil

import cv2
import numpy as np

from estatehdr.grouping import group_frames, list_images, load_groups, save_groups, scan_folder
from estatehdr.io.metadata import read_metadata


def _names(groups):
    return [[os.path.basename(f.path) for f in g.frames] for g in groups]


def test_groups_match_manifest(synth, cfg):
    groups, failures = scan_folder(synth["input"], cfg["grouping"])
    got = _names(groups)
    for ser in synth["manifest"]["series"]:
        assert ser["files"] in got, (ser["name"], got)
    assert synth["manifest"]["extras"]["noexif_incomplete"] in got  # EXIF-less pair kept together
    # truncated file: its pixels cannot be decoded, so it is reported as unreadable, not grouped
    assert "IMG_9999.jpg" not in [f for g in got for f in g]
    assert [os.path.basename(f["file"]) for f in failures] == ["IMG_9999.jpg"]


def test_mask_files_ignored(synth, tmp_path):
    d = tmp_path / "f"
    d.mkdir()
    shutil.copy(os.path.join(synth["input"], "IMG_0011.jpg"), d / "a.jpg")
    cv2.imwrite(str(d / "a.mask.png"), np.zeros((10, 10), np.uint8))
    assert [os.path.basename(p) for p in list_images(str(d))] == ["a.jpg"]


def test_noexif_different_photos_not_grouped(synth, cfg, tmp_path):
    """Two different, similarly exposed photos without EXIF must not be merged into a bracket."""
    a = cv2.imread(os.path.join(synth["input"], "IMG_0011.jpg"))      # living room
    b = cv2.imread(os.path.join(synth["input"], "IMG_0006.tif"), cv2.IMREAD_UNCHANGED)  # bedroom
    b = (b / 257).astype(np.uint8)
    cv2.imwrite(str(tmp_path / "p1.png"), a)
    cv2.imwrite(str(tmp_path / "p2.png"), b)
    metas = [read_metadata(str(tmp_path / f)) for f in ("p1.png", "p2.png")]
    assert len(group_frames(metas, cfg["grouping"])) == 2


def test_fixed_bracket_size(synth, cfg):
    metas = [read_metadata(os.path.join(synth["input"], f"IMG_000{i}.jpg")) for i in range(5)]
    g = group_frames(metas, {**cfg["grouping"], "mode": "fixed", "bracket_size": 3})
    assert [len(x.frames) for x in g] == [3, 2]
    assert "incomplete" in " ".join(g[1].warnings)


def test_groups_file_roundtrip(synth, cfg, tmp_path):
    groups, _ = scan_folder(synth["input"], cfg["grouping"])
    p = str(tmp_path / "groups.json")
    save_groups(groups, p)
    back = load_groups(p)
    assert _names(back) == _names(groups)

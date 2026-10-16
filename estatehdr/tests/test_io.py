"""Input/output: metadata, decoding, corrupt files, JPEG export with ICC + EXIF."""
import io
import os

import numpy as np
import pytest
from PIL import Image

from estatehdr.io import reader, writer
from estatehdr.io.metadata import read_metadata


def test_metadata_from_exif(synth):
    m = read_metadata(os.path.join(synth["input"], "IMG_0002.jpg"))
    assert m.exposure_time and m.fnumber == pytest.approx(8.0) and m.iso == 100
    assert m.timestamp_source == "exif" and m.exposure_value is not None
    assert m.width == 480 and m.height == 320


def test_metadata_without_exif(synth):
    m = read_metadata(os.path.join(synth["input"], "NOEXIF_0000.jpg"))
    assert m.exposure_value is None
    assert m.timestamp is not None and m.timestamp_source != "exif"  # file time fallback


def test_decode_formats(synth):
    j = reader.decode(os.path.join(synth["input"], "IMG_0002.jpg"))
    assert j.encoding == "srgb" and j.image.dtype == np.uint8 and j.image.shape == (320, 480, 3)
    t = reader.decode(os.path.join(synth["input"], "IMG_0005.tif"))
    assert t.image.dtype == np.uint16 and t.max_value == 65535


def test_truncated_jpeg_raises(synth):
    with pytest.raises(Exception) as e:
        reader.decode(os.path.join(synth["input"], "IMG_9999.jpg"))
    assert "trunc" in str(e.value).lower() or "decode" in type(e.value).__name__.lower()


def test_orientation():
    img = np.arange(6 * 4 * 3, dtype=np.uint8).reshape(6, 4, 3)
    assert reader.apply_orientation(img, 6).shape == (4, 6, 3)
    assert np.array_equal(reader.apply_orientation(img, 1), img)


def test_jpeg_has_srgb_icc_and_exif(synth, tmp_path):
    ref = read_metadata(os.path.join(synth["input"], "IMG_0002.jpg"))
    img = np.random.default_rng(0).random((64, 96, 3)).astype(np.float32)
    exif = writer.build_exif(ref, 96, 64, "test")
    p = str(tmp_path / "x.jpg")
    writer.write_jpeg(p, writer.to_uint8(img), 90, exif)
    with Image.open(p) as im:
        from PIL import ImageCms
        prof = ImageCms.ImageCmsProfile(io.BytesIO(im.info["icc_profile"]))
        assert "sRGB" in prof.profile.profile_description
        ex = im.getexif()
        assert ex.get(0x0112) == 1                       # orientation reset (pixels are upright)
        assert ex.get(0x010F) == ref.make                 # camera make copied
        assert "EstateHDR" in str(ex.get(0x0131))         # software
    assert not os.path.exists(p + ".part")


def test_to_uint8_dither_unbiased():
    img = np.full((200, 300, 3), 0.5004, np.float32)
    u = writer.to_uint8(img)
    assert abs(u.astype(float).mean() / 255 - 0.5004) < 1e-3

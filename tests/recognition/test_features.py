from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from fatball.recognition.features import feature_print, from_blob, similarity, to_blob

FULL = (0.0, 0.0, 1.0, 1.0)


def _scene(path: Path, shape: str, at: tuple[int, int], colour: str) -> Path:
    im = Image.new("RGB", (320, 240), (40, 140, 50))
    d = ImageDraw.Draw(im)
    x, y = at
    box = (x - 50, y - 50, x + 50, y + 50)
    if shape == "disc":
        d.ellipse(box, fill=colour)
    else:
        d.rectangle(box, fill=colour)
    im.save(path)
    return path


def test_same_crop_twice_is_identical(tmp_path):
    img = _scene(tmp_path / "a.png", "disc", (160, 120), "red")
    assert similarity(feature_print(img, FULL), feature_print(img, FULL)) > 0.999


def test_unit_length(tmp_path):
    v = feature_print(_scene(tmp_path / "a.png", "disc", (160, 120), "red"), FULL)
    assert v.dtype == np.float32
    assert abs(np.linalg.norm(v) - 1) < 1e-5


def test_different_objects_less_similar_than_same(tmp_path):
    red = feature_print(_scene(tmp_path / "r.png", "disc", (110, 100), "red"), FULL)
    red2 = feature_print(_scene(tmp_path / "r2.png", "disc", (210, 140), "red"), FULL)
    blue = feature_print(_scene(tmp_path / "b.png", "square", (160, 120), "blue"), FULL)
    assert similarity(red, red2) > similarity(red, blue)


def test_box_padding_is_clamped_to_the_image(tmp_path):
    img = _scene(tmp_path / "a.png", "disc", (160, 120), "red")
    v = feature_print(img, (0.0, 0.0, 0.4, 0.4))
    assert v.shape[0] > 0
    feature_print(img, (0.6, 0.6, 1.0, 1.0))


def test_box_selects_the_region(tmp_path):
    img = _scene(tmp_path / "a.png", "disc", (80, 60), "red")  # top-left of the image
    top_left = feature_print(img, (0.0, 0.0, 0.5, 0.5))
    bottom_right = feature_print(img, (0.5, 0.5, 1.0, 1.0))
    assert similarity(top_left, bottom_right) < 0.99


def test_zero_area_box_raises(tmp_path):
    import pytest

    img = _scene(tmp_path / "a.png", "disc", (160, 120), "red")
    with pytest.raises(ValueError):
        feature_print(img, (0.5, 0.5, 0.5, 0.9))


def test_blob_round_trip(tmp_path):
    v = feature_print(_scene(tmp_path / "a.png", "disc", (160, 120), "red"), FULL)
    back = from_blob(to_blob(v))
    assert back.dtype == np.float32
    assert np.array_equal(v, back)

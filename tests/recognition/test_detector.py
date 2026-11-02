import os
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fatball.recognition.detector import (
    INPUT_SIZE,
    Detection,
    Detector,
    ModelMissing,
    compiled_model,
    decode,
    letterbox,
)


def row(cx, cy, w, h, animal=0.0, person=0.0, vehicle=0.0):
    return [cx, cy, w, h, animal, person, vehicle]


def test_decode_letterbox_maps_back_to_normalised_box():
    # 1280x720 scaled by 0.5 to 640x360, centred in 640x640 with 140 px above and below.
    raw = np.array([row(320, 320, 64, 36, animal=0.9)], dtype=np.float32)
    [det] = decode(raw, 1280, 720)
    x1, y1, x2, y2 = det.box
    assert det.cls == "animal"
    assert det.conf == pytest.approx(0.9)
    assert (x1 + x2) / 2 == pytest.approx(0.5)
    assert (y1 + y2) / 2 == pytest.approx(0.5)
    assert x2 - x1 == pytest.approx(0.1)
    assert y2 - y1 == pytest.approx(0.1)


def test_decode_drops_below_conf_min_and_picks_class_argmax():
    raw = np.array(
        [
            row(100, 320, 40, 40, animal=0.05, person=0.04, vehicle=0.02),
            row(300, 320, 40, 40, animal=0.2, person=0.6, vehicle=0.1),
            row(500, 320, 40, 40, vehicle=0.4),
        ],
        dtype=np.float32,
    )
    dets = decode(raw, 640, 640, conf_min=0.1)
    assert [(d.cls, round(d.conf, 2)) for d in dets] == [("person", 0.6), ("vehicle", 0.4)]


def test_decode_nms_keeps_best_of_overlapping_boxes():
    # Two 100x100 boxes shifted by 12 px overlap with IoU 0.78; shifted by 150 px they do not.
    near = np.array([row(300, 300, 100, 100, animal=0.9), row(312, 300, 100, 100, animal=0.6)])
    far = np.array([row(200, 300, 100, 100, animal=0.9), row(350, 300, 100, 100, animal=0.6)])
    [kept] = decode(near.astype(np.float32), 640, 640)
    assert kept.conf == pytest.approx(0.9)
    assert len(decode(far.astype(np.float32), 640, 640)) == 2


def test_decode_nms_is_per_class():
    raw = np.array([row(300, 300, 100, 100, animal=0.9), row(300, 300, 100, 100, person=0.8)], dtype=np.float32)
    assert [d.cls for d in decode(raw, 640, 640)] == ["animal", "person"]


def test_decode_clips_box_to_the_image():
    raw = np.array([row(10, 320, 100, 100, animal=0.9)], dtype=np.float32)
    [det] = decode(raw, 640, 640)
    assert det.box[0] == 0.0
    assert isinstance(det, Detection)


GREY = (114, 114, 114)


def test_letterbox_scales_to_fit_and_centres_on_grey():
    # 1280x720 scales by 0.5 to 640x360, centred with 140 grey rows above and below.
    out = letterbox(Image.new("RGB", (1280, 720), (255, 0, 0)))
    assert out.size == (INPUT_SIZE, INPUT_SIZE) and out.mode == "RGB"
    assert out.getpixel((320, 139)) == GREY and out.getpixel((320, 500)) == GREY
    assert out.getpixel((0, 140)) == (255, 0, 0) and out.getpixel((639, 499)) == (255, 0, 0)
    assert out.getpixel((0, 0)) == GREY and out.getpixel((639, 639)) == GREY


def test_letterbox_truncates_size_and_floors_the_offset_like_pytorchwildlife():
    # 1280x723 scales by 0.5 to 640x361.5: int() keeps 361 rows, and (640 - 361) // 2 puts the first at row 139.
    out = letterbox(Image.new("RGB", (1280, 723), (0, 0, 255)))
    assert out.getpixel((320, 138)) == GREY and out.getpixel((320, 139)) == (0, 0, 255)
    assert out.getpixel((320, 499)) == (0, 0, 255) and out.getpixel((320, 500)) == GREY


def test_letterbox_converts_to_rgb():
    assert letterbox(Image.new("L", (720, 1280), 200)).getpixel((320, 320)) == (200, 200, 200)


def test_decode_undoes_the_letterbox():
    # A white block at x 320..640, y 180..540 of a dark 1280x720 frame; find it in the letterboxed image and decode.
    frame = Image.new("RGB", (1280, 720), (0, 0, 0))
    frame.paste((255, 255, 255), (320, 180, 640, 540))
    pixels = np.asarray(letterbox(frame)).min(axis=2) > 200
    ys, xs = np.nonzero(pixels)
    x1, y1, x2, y2 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    raw = np.array([row((x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1, animal=0.9)], dtype=np.float32)
    [det] = decode(raw, 1280, 720)
    assert det.box == pytest.approx((0.25, 0.25, 0.5, 0.75), abs=1 / 640)


def test_detector_missing_model_raises(tmp_path):
    with pytest.raises(ModelMissing):
        Detector(tmp_path / "nope.mlpackage")


@pytest.mark.skipif(not os.environ.get("FATBALL_DETECTOR"), reason="FATBALL_DETECTOR (path to the .mlpackage) not set")
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_detector_on_real_model(tmp_path):
    frame = tmp_path / "frame.jpg"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720", "-frames:v", "1", str(frame)],
        check=True,
    )
    detector = Detector(Path(os.environ["FATBALL_DETECTOR"]))
    detector.detect(frame)  # the first call warms the model up
    start = time.perf_counter()
    result = detector.detect(frame)
    assert isinstance(result, list)
    assert time.perf_counter() - start < 0.5


@pytest.mark.skipif(
    not (os.environ.get("FATBALL_DETECTOR") and os.environ.get("FATBALL_TEST_FRAME")),
    reason="FATBALL_DETECTOR (the .mlpackage) and FATBALL_TEST_FRAME (a private close-up bird frame) not both set",
)
def test_detector_calls_a_close_up_bird_an_animal():
    # A close-up great tit at the feeder: MegaDetector as published says animal; eval-mode BatchNorm said person.
    detections = Detector(Path(os.environ["FATBALL_DETECTOR"])).detect(Path(os.environ["FATBALL_TEST_FRAME"]))
    assert max((d.conf for d in detections if d.cls == "animal"), default=0.0) >= 0.8
    assert not [d for d in detections if d.cls == "person" and d.conf >= 0.3]


def _package(tmp_path):
    package = tmp_path / "models" / "md.mlpackage"
    package.mkdir(parents=True)
    (package / "Manifest.json").write_text("{}")
    return package


def test_compiled_model_is_cached_next_to_the_package_until_it_changes(tmp_path):
    package = _package(tmp_path)
    scratch = tmp_path / "tmp"
    compiles = []

    def compile_fn(path):
        out = scratch / f"c{len(compiles)}.mlmodelc"
        out.mkdir(parents=True)
        (out / "model.mil").write_text(str(len(compiles)))
        compiles.append(path)
        return out

    first = compiled_model(package, compile_fn)
    assert compiled_model(package, compile_fn) == first
    assert len(compiles) == 1 and first.parent == package.parent and (first / "model.mil").exists()
    assert list(scratch.iterdir()) == []  # moved out of the temporary folder, not copied
    later = (package / "Manifest.json").stat().st_mtime_ns + 5_000_000_000
    os.utime(package / "Manifest.json", ns=(later, later))  # the model was exported again
    second = compiled_model(package, compile_fn)
    assert len(compiles) == 2 and second != first
    assert not first.exists()  # the stale compiled copy is removed


def test_decode_drops_boxes_with_no_area_after_clipping():
    # 1280x720: the image spans y 140..500 of the 640 input. Row 1 lies wholly in the top padding, so it clips to
    # zero height; row 2 is a normal box.
    raw = np.array([row(320, 100, 200, 60, animal=0.9), row(320, 320, 64, 36, animal=0.8)], dtype=np.float32)
    [det] = decode(raw, 1280, 720)
    assert det.conf == pytest.approx(0.8)

import os
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from fatball.recognition.detector import Detection, Detector, ModelMissing, decode


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

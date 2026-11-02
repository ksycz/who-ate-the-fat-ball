import json
import subprocess
from datetime import datetime, timedelta

import numpy as np
import pytest

from fatball.config import Settings
from fatball.library import repo
from fatball.library.db import connect
from fatball.media.convert import FFMPEG
from fatball.recognition import qos
from fatball.recognition.detector import Detection
from fatball.recognition.fake import FakeDetector
from fatball.recognition.recognizer import Recognizer, verdict_to_json

BOX = (0.2, 0.2, 0.6, 0.6)
GREAT_TIT = "Parus major"


@pytest.fixture
def setup(tmp_path):
    settings = Settings(data_dir=tmp_path)
    conn = connect(settings.db_path)
    repo.ensure_catalog(conn)
    cam = repo.upsert_camera(conn, "feeder", None, None)
    begin = datetime(2026, 10, 30, 8, 0, 0)
    clip_id = repo.add_clip(conn, cam, "/a.h265", begin, begin + timedelta(seconds=4), "video", 1)
    web = settings.media_dir / "clips" / str(clip_id) / "web.mp4"
    web.parent.mkdir(parents=True)
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10",
                    "-t", "4", "-pix_fmt", "yuv420p", str(web)], check=True)
    rel = web.relative_to(settings.media_dir).as_posix()
    repo.set_clip_status(conn, clip_id, "ready", web_path=rel)
    clip = repo.list_clips(conn, 1, None)[0]
    yield settings, conn, clip
    conn.close()


class Spy:
    """A stand-in for feature_print that records its calls."""

    def __init__(self):
        self.calls = []

    def __call__(self, path, box):
        self.calls.append((path, box))
        return np.array([1.0, 0.0], dtype=np.float32)


def _animal(conf=0.9):
    return Detection("animal", conf, BOX)


def test_recognize_stores_detections_and_verdict(setup):
    settings, conn, clip = setup
    # Teach it: a labelled example of a great tit from another clip.
    other = repo.add_clip(conn, 1, "/b.h265", datetime(2026, 10, 30, 9), datetime(2026, 10, 30, 9, 0, 4), "video", 1)
    conn.execute(
        "INSERT INTO detection(clip_id, frame_index, cls, conf, x1, y1, x2, y2, feature, label) "
        "VALUES (?, 0, 'animal', 0.9, 0, 0, 1, 1, ?, ?)",
        (other, np.array([1.0, 0.0], dtype=np.float32).tobytes(), GREAT_TIT),
    )
    conn.commit()
    script = {2: [_animal(0.8)], 3: [_animal(0.9), Detection("person", 0.4, BOX), Detection("vehicle", 0.9, BOX)]}
    verdict = Recognizer(settings, conn, FakeDetector(script), Spy()).recognize(clip)

    assert (verdict.category, verdict.species, verdict.subject) == ("birds", GREAT_TIT, "species")
    rows = conn.execute("SELECT frame_index, cls, feature FROM detection WHERE clip_id = ? ORDER BY id", (clip.id,)).fetchall()
    assert [(r["frame_index"], r["cls"], r["feature"] is not None) for r in rows] == [
        (2, "animal", True), (3, "animal", True), (3, "person", False)]
    stored = conn.execute("SELECT verdict_json, recognized_at, best_frame_path FROM clip WHERE id = ?", (clip.id,)).fetchone()
    data = json.loads(stored["verdict_json"])
    assert data["category"] == "birds" and data["species"] == GREAT_TIT and data["subject"] == "species"
    assert data["confidence"] == 1.0 and data["guesses"] == [[GREAT_TIT, 1.0]]
    assert stored["recognized_at"] is not None


def test_temp_frames_deleted_best_frame_kept(setup):
    settings, conn, clip = setup
    detector = FakeDetector({1: [_animal()]})
    verdict = Recognizer(settings, conn, detector, Spy()).recognize(clip)
    assert verdict.best is not None and verdict.best.frame_index == 1
    best = settings.media_dir / "clips" / str(clip.id) / "best.jpg"
    assert best.exists()
    assert conn.execute("SELECT best_frame_path FROM clip WHERE id = ?", (clip.id,)).fetchone()[0] == f"clips/{clip.id}/best.jpg"
    assert all(not p.exists() for p in detector.calls)


def test_temp_frames_deleted_when_detection_raises(setup):
    settings, conn, clip = setup

    class Boom:
        def __init__(self):
            self.seen = []

        def detect(self, path):
            self.seen.append(path)
            raise RuntimeError("boom")

    boom = Boom()
    with pytest.raises(RuntimeError):
        Recognizer(settings, conn, boom, Spy()).recognize(clip)
    assert boom.seen and not boom.seen[0].parent.exists()


def test_no_best_frame_stores_null(setup):
    settings, conn, clip = setup
    verdict = Recognizer(settings, conn, FakeDetector({}), Spy()).recognize(clip)
    assert verdict.subject == "nothing"
    assert conn.execute("SELECT best_frame_path FROM clip WHERE id = ?", (clip.id,)).fetchone()[0] is None
    assert not (settings.media_dir / "clips" / str(clip.id) / "best.jpg").exists()


def test_features_only_for_confident_animal_boxes(setup):
    settings, conn, clip = setup
    script = {0: [_animal(0.29), _animal(0.3), Detection("person", 0.9, BOX), Detection("vehicle", 0.9, BOX)]}
    spy = Spy()
    Recognizer(settings, conn, FakeDetector(script), spy).recognize(clip)
    assert len(spy.calls) == 1
    rows = conn.execute("SELECT cls, conf, feature IS NULL AS no_feature FROM detection ORDER BY conf").fetchall()
    assert [(r["cls"], r["conf"], bool(r["no_feature"])) for r in rows] == [
        ("animal", 0.29, True), ("animal", 0.3, False), ("person", 0.9, True)]


def test_rerecognize_keeps_labelled_detections(setup):
    settings, conn, clip = setup
    Recognizer(settings, conn, FakeDetector({0: [_animal(), _animal(0.5)]}), Spy()).recognize(clip)
    first = conn.execute("SELECT id FROM detection ORDER BY id LIMIT 1").fetchone()[0]
    conn.execute("UPDATE detection SET label = ? WHERE id = ?", (GREAT_TIT, first))
    conn.commit()
    Recognizer(settings, conn, FakeDetector({0: [_animal(0.7)]}), Spy()).recognize(clip)
    rows = conn.execute("SELECT id, conf, label FROM detection ORDER BY id").fetchall()
    assert [(r["id"] == first, r["conf"], r["label"]) for r in rows] == [(True, 0.9, GREAT_TIT), (False, 0.7, None)]


def test_rerecognize_adds_no_duplicate_of_a_labelled_detection(setup):
    settings, conn, clip = setup
    Recognizer(settings, conn, FakeDetector({0: [_animal(), _animal(0.5)]}), Spy()).recognize(clip)
    first = conn.execute("SELECT id FROM detection ORDER BY id LIMIT 1").fetchone()[0]
    conn.execute("UPDATE detection SET label = ? WHERE id = ?", (GREAT_TIT, first))
    conn.commit()
    Recognizer(settings, conn, FakeDetector({0: [_animal(), _animal(0.5)]}), Spy()).recognize(clip)  # a retry
    rows = conn.execute("SELECT id, conf, label FROM detection ORDER BY id").fetchall()
    assert [(r["id"] == first, r["conf"], r["label"]) for r in rows] == [(True, 0.9, GREAT_TIT), (False, 0.5, None)]


def test_examples_are_loaded_once_until_labels_change(setup, monkeypatch):
    settings, conn, clip = setup
    other = repo.add_clip(conn, 1, "/b.h265", datetime(2026, 10, 30, 9), datetime(2026, 10, 30, 9, 0, 4), "video", 1)
    conn.execute(
        "INSERT INTO detection(clip_id, frame_index, cls, conf, x1, y1, x2, y2, feature, label, labelled_at) "
        "VALUES (?, 0, 'animal', 0.9, 0, 0, 1, 1, ?, ?, 'T')",
        (other, np.array([1.0, 0.0], dtype=np.float32).tobytes(), GREAT_TIT),
    )
    conn.commit()
    loads = []
    real = repo.examples
    monkeypatch.setattr(repo, "examples", lambda c: loads.append(1) or real(c))
    recognizer = Recognizer(settings, conn, FakeDetector(lambda i: [_animal()]), Spy())
    assert recognizer.recognize(clip).species == GREAT_TIT
    recognizer.recognize(clip)
    assert len(loads) == 1
    repo.label_detections(conn, clip.id, GREAT_TIT, "import")  # new examples: the cache is stale
    recognizer.recognize(clip)
    assert len(loads) == 2


def test_verdict_to_json_shape(setup):
    settings, conn, clip = setup
    verdict = Recognizer(settings, conn, FakeDetector({}), Spy()).recognize(clip)
    assert json.loads(verdict_to_json(verdict)) == {
        "category": "other", "species": None, "subject": "nothing", "confidence": 1.0, "guesses": []}


def test_set_background_priority_returns_bool():
    assert isinstance(qos.set_background_priority(), bool)

import logging
from datetime import datetime, timedelta

import numpy as np
import pytest

from fatball.config import Settings
from fatball.ingest import processor as processor_mod
from fatball.ingest.processor import Processor
from fatball.library import repo
from fatball.library.db import connect
from fatball.recognition.detector import Detection, ModelMissing
from fatball.recognition.fake import FakeDetector
from fatball.recognition.matcher import Verdict
from fatball.recognition.recognizer import Recognizer

BEGIN = datetime(2026, 10, 31, 9, 0, 0)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "lib.db")
    yield c
    c.close()


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path)


def _clip(conn, settings, data: bytes, kind: str = "h264", status: str = "downloaded"):
    cam = repo.upsert_camera(conn, "feeder", None, None)
    clip_id = repo.add_clip(conn, cam, f"/idea0/{kind}", BEGIN, BEGIN, kind, len(data))
    raw = settings.media_dir / "raw" / f"{clip_id}.raw"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(data)
    repo.set_clip_status(conn, clip_id, status, raw_path=f"raw/{clip_id}.raw")
    return clip_id, raw


def _get(conn, clip_id):
    return next(c for s in ("downloading", "downloaded", "processing", "ready", "failed")
                for c in repo.clips_with_status(conn, s) if c.id == clip_id)


def test_processes_downloaded_clip_to_ready_with_paths(settings, conn, xm_clip_bytes):
    clip_id, raw = _clip(conn, settings, xm_clip_bytes)
    assert Processor(settings, conn).process_pending() == 1
    clip = _get(conn, clip_id)
    assert clip.status == "ready"
    assert clip.web_path == f"clips/{clip_id}/web.mp4"
    assert clip.original_path == f"clips/{clip_id}/original.mp4"
    assert clip.poster_path == f"clips/{clip_id}/poster.jpg"
    assert clip.preview_path == f"clips/{clip_id}/preview.mp4"
    assert clip.duration_s == pytest.approx(2, abs=0.5)
    for p in (clip.web_path, clip.original_path, clip.poster_path, clip.preview_path):
        assert (settings.media_dir / p).stat().st_size > 0
    assert (settings.media_dir / "clips" / str(clip_id) / "thumb.jpg").exists()
    assert raw.exists()


def test_failed_conversion_marks_failed_and_keeps_raw(settings, conn):
    clip_id, raw = _clip(conn, settings, b"not a clip")
    assert Processor(settings, conn).process_pending() == 1
    assert _get(conn, clip_id).status == "failed"
    assert raw.exists()


def test_unexpected_error_fails_that_clip_only(settings, conn, xm_clip_bytes, monkeypatch):
    bad, _ = _clip(conn, settings, xm_clip_bytes)
    cam = repo.get_camera(conn).id
    good = repo.add_clip(conn, cam, "/idea0/b", BEGIN.replace(hour=10), BEGIN, "h264", 1)
    raw = settings.media_dir / "raw" / f"{good}.raw"
    raw.write_bytes(xm_clip_bytes)
    repo.set_clip_status(conn, good, "downloaded", raw_path=f"raw/{good}.raw")
    real = processor_mod.convert_clip

    def flaky(raw_path, out_dir):
        if out_dir.name == str(bad):
            raise FileNotFoundError("ffmpeg")
        return real(raw_path, out_dir)

    monkeypatch.setattr(processor_mod, "convert_clip", flaky)
    assert Processor(settings, conn).process_pending() == 2
    assert _get(conn, bad).status == "failed"
    assert _get(conn, good).status == "ready"


def test_photo_goes_to_photos_dir(settings, conn, monkeypatch):
    monkeypatch.setattr(processor_mod, "extract_jpeg", lambda raw: b"\xff\xd8jpeg\xff\xd9")
    clip_id, _ = _clip(conn, settings, b"raw", kind="jpg")
    assert Processor(settings, conn).process_pending() == 1
    clip = _get(conn, clip_id)
    assert clip.status == "ready"
    assert clip.poster_path == f"photos/{clip_id}.jpg"
    assert (settings.media_dir / clip.poster_path).read_bytes().startswith(b"\xff\xd8")


def test_processing_is_resumable_after_crash(settings, conn):
    clip_id, _ = _clip(conn, settings, b"x", status="processing")
    Processor(settings, conn)
    assert _get(conn, clip_id).status == "downloaded"


def test_in_flight_downloading_clip_is_not_processed(settings, conn):
    cam = repo.upsert_camera(conn, "feeder", None, None)
    clip_id = repo.add_clip(conn, cam, "/idea0/inflight", BEGIN, BEGIN, "h264", 1)
    assert Processor(settings, conn).process_pending() == 0
    assert _get(conn, clip_id).status == "downloading"


def test_skips_a_clip_another_worker_already_claimed(settings, conn, monkeypatch):
    clip_id, _ = _clip(conn, settings, b"x")
    real = repo.clips_with_status
    converted = []

    def snapshot_then_lose_race(c, status):
        clips = real(c, status)
        c.execute("UPDATE clip SET status = 'processing' WHERE id = ?", (clip_id,))  # the other worker
        c.commit()
        return clips

    p = Processor(settings, conn)
    monkeypatch.setattr(processor_mod.repo, "clips_with_status", snapshot_then_lose_race)
    monkeypatch.setattr(p, "_convert", lambda clip: converted.append(clip) or {})
    assert p.process_pending() == 0
    assert converted == []
    assert _get(conn, clip_id).status == "processing"


def test_processor_uses_raw_path_read_at_claim_time(settings, conn, monkeypatch):
    clip_id, _ = _clip(conn, settings, b"x", kind="jpg")
    real = repo.clips_with_status

    def stale_snapshot(c, status):
        clips = real(c, status)
        for clip in clips:
            clip.raw_path = None  # snapshot taken before the watcher filled raw_path in
        return clips

    seen = []
    monkeypatch.setattr(processor_mod.repo, "clips_with_status", stale_snapshot)
    monkeypatch.setattr(processor_mod, "extract_jpeg", lambda raw: seen.append(raw) or b"\xff\xd8\xff\xd9")
    assert Processor(settings, conn).process_pending() == 1
    assert seen == [b"x"]
    assert _get(conn, clip_id).status == "ready"


GREAT_TIT = "Parus major"
BIRD = np.array([1.0, 0.0], dtype=np.float32)


def _teach_great_tit(conn):
    """A labelled great tit example on another clip, so a detected bird is recognised as one."""
    repo.ensure_catalog(conn)
    cam = repo.upsert_camera(conn, "feeder", None, None)
    holder = repo.add_clip(conn, cam, "/examples", BEGIN - timedelta(days=9), BEGIN, "h264", 1)
    conn.execute(
        "INSERT INTO detection(clip_id, frame_index, cls, conf, x1, y1, x2, y2, feature, label) "
        "VALUES (?, 0, 'animal', 0.9, 0, 0, 1, 1, ?, ?)",
        (holder, BIRD.tobytes(), GREAT_TIT),
    )
    conn.commit()


def _bird_detector():
    return FakeDetector(lambda i: [Detection("animal", 0.9, (0.2, 0.2, 0.6, 0.6))])


def _real_recognizer(settings, conn):
    return Recognizer(settings, conn, _bird_detector(), lambda path, box: BIRD)


class StubRecognizer:
    """Records the clips it is asked about; raises for the ids in `fail`."""

    def __init__(self, conn, fail=()):
        self.conn, self.fail, self.seen = conn, set(fail), []

    def recognize(self, clip):
        self.seen.append(clip.id)
        if clip.id in self.fail:
            raise RuntimeError("model blew up")
        repo.set_recognition(self.conn, clip.id, best_frame_path=None, verdict_json="{}",
                             recognized_at=datetime.now())
        return Verdict("birds", GREAT_TIT, 1.0, [(GREAT_TIT, 1.0)], "species", None)


def _ready_clip(conn, hour: int):
    repo.ensure_catalog(conn)
    cam = repo.upsert_camera(conn, "feeder", None, None)
    begin = BEGIN.replace(hour=hour)
    clip_id = repo.add_clip(conn, cam, f"/idea0/{hour}", begin, begin + timedelta(seconds=2), "h264", 1)
    repo.set_clip_status(conn, clip_id, "ready", web_path=f"clips/{clip_id}/web.mp4")
    return clip_id


def _recognition(conn, clip_id):
    row = conn.execute("SELECT recognized_at, recognition_error FROM clip WHERE id = ?", (clip_id,)).fetchone()
    return row["recognized_at"], row["recognition_error"]


def test_downloaded_clip_is_recognised_and_in_a_visit(settings, conn, xm_clip_bytes):
    _teach_great_tit(conn)
    clip_id, _ = _clip(conn, settings, xm_clip_bytes)
    assert Processor(settings, conn, _real_recognizer(settings, conn)).process_pending() == 1
    assert _get(conn, clip_id).status == "ready"
    assert _recognition(conn, clip_id)[0] is not None
    visit_id = repo.visit_for_clip(conn, clip_id)
    assert visit_id is not None
    species = conn.execute(
        "SELECT s.scientific_name FROM visit v JOIN species s ON s.id = v.species_id WHERE v.id = ?", (visit_id,)
    ).fetchone()
    assert species[0] == GREAT_TIT


def test_backfill_does_one_clip_per_pass_oldest_first(settings, conn):
    _teach_great_tit(conn)
    repo.set_setting(conn, "recognize_old_clips", "on")
    late, early, mid = _ready_clip(conn, 15), _ready_clip(conn, 8), _ready_clip(conn, 11)
    stub = StubRecognizer(conn)
    p = Processor(settings, conn, stub)
    for expected in ([early], [early, mid], [early, mid, late], [early, mid, late]):
        p.process_pending()
        assert stub.seen == expected
    assert all(repo.visit_for_clip(conn, c) is not None for c in (late, early, mid))


def test_recognition_error_keeps_clip_playable(settings, conn, xm_clip_bytes, caplog):
    _teach_great_tit(conn)
    clip_id, _ = _clip(conn, settings, xm_clip_bytes)
    stub = StubRecognizer(conn, fail=[clip_id])
    with caplog.at_level(logging.ERROR):
        assert Processor(settings, conn, stub).process_pending() == 1
    clip = _get(conn, clip_id)
    assert clip.status == "ready" and (settings.media_dir / clip.web_path).exists()
    recognized_at, error = _recognition(conn, clip_id)
    assert recognized_at is None and "model blew up" in error
    assert f"recognising clip {clip_id} failed" in caplog.text


def test_failed_clip_is_skipped_by_later_passes(settings, conn):
    _teach_great_tit(conn)
    repo.set_setting(conn, "recognize_old_clips", "on")
    bad, good = _ready_clip(conn, 8), _ready_clip(conn, 9)
    stub = StubRecognizer(conn, fail=[bad])
    p = Processor(settings, conn, stub)
    p.process_pending()
    p.process_pending()
    assert stub.seen == [bad, good]
    assert _recognition(conn, good)[0] is not None


def test_missing_model_keeps_clips_ready_and_unrecognised(settings, conn, xm_clip_bytes):
    clip_id, _ = _clip(conn, settings, xm_clip_bytes)
    assert Processor(settings, conn).process_pending() == 1
    assert _get(conn, clip_id).status == "ready"
    assert _recognition(conn, clip_id) == (None, None)
    assert repo.visit_for_clip(conn, clip_id) is None


def test_no_examples_keeps_clips_ready_and_pending(settings, conn, xm_clip_bytes):
    repo.ensure_catalog(conn)
    clip_id, _ = _clip(conn, settings, xm_clip_bytes)
    p = Processor(settings, conn, _real_recognizer(settings, conn))
    assert p.process_pending() == 1
    assert _get(conn, clip_id).status == "ready"
    assert _recognition(conn, clip_id) == (None, None) and repo.visit_for_clip(conn, clip_id) is None
    assert repo.recognition_counts(conn)["old_waiting"] == 1
    _teach_great_tit(conn)
    repo.requeue_recognition(conn, clip_id)  # asked for, so it is recognised once there is an example
    p.process_pending()
    visit_id = repo.visit_for_clip(conn, clip_id)
    assert visit_id is not None
    assert conn.execute("SELECT s.scientific_name FROM visit v JOIN species s ON s.id = v.species_id "
                        "WHERE v.id = ?", (visit_id,)).fetchone()[0] == GREAT_TIT


def test_model_appearing_later_starts_recognition(settings, conn, xm_clip_bytes, caplog):
    _teach_great_tit(conn)
    clip_id, _ = _clip(conn, settings, xm_clip_bytes)
    repo.set_setting(conn, "recognize_old_clips", "on")  # converted before any model, so it is "old"
    detectors = [None, None, _bird_detector()]
    p = Processor(settings, conn, detector_loader=lambda: detectors.pop(0), features=lambda path, box: BIRD)
    with caplog.at_level(logging.WARNING):
        p.process_pending()
        p.process_pending()
    assert not p.has_detector
    assert _get(conn, clip_id).status == "ready" and _recognition(conn, clip_id)[0] is None
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1  # warned once, not per pass
    p.process_pending()
    assert p.has_detector
    assert _recognition(conn, clip_id)[0] is not None and repo.visit_for_clip(conn, clip_id) is not None


def test_loader_failure_is_survived(settings, conn, xm_clip_bytes):
    def load():
        raise ModelMissing("run scripts/export_detector.py")

    clip_id, _ = _clip(conn, settings, xm_clip_bytes)
    p = Processor(settings, conn, detector_loader=load)
    assert p.process_pending() == 1
    assert _get(conn, clip_id).status == "ready" and not p.has_detector


def test_photos_are_never_recognised(settings, conn, monkeypatch):
    _teach_great_tit(conn)
    monkeypatch.setattr(processor_mod, "extract_jpeg", lambda raw: b"\xff\xd8jpeg\xff\xd9")
    clip_id, _ = _clip(conn, settings, b"raw", kind="jpg")
    stub = StubRecognizer(conn)
    Processor(settings, conn, stub).process_pending()
    assert _get(conn, clip_id).status == "ready" and stub.seen == []
    assert repo.recognition_counts(conn) == {"pending": 0, "old_waiting": 0, "errors": 0}


def test_old_clips_wait_by_default(settings, conn, xm_clip_bytes):
    _teach_great_tit(conn)
    old = _ready_clip(conn, 8)
    new, _ = _clip(conn, settings, xm_clip_bytes)
    stub = StubRecognizer(conn)
    Processor(settings, conn, stub).process_pending()
    Processor(settings, conn, stub).process_pending()
    assert stub.seen == [new]
    assert _recognition(conn, old) == (None, None) and repo.visit_for_clip(conn, old) is None


def test_background_setting_on_recognises_old_clips(settings, conn):
    _teach_great_tit(conn)
    old = _ready_clip(conn, 8)
    stub = StubRecognizer(conn)
    p = Processor(settings, conn, stub)
    p.process_pending()
    assert stub.seen == []
    repo.set_setting(conn, "recognize_old_clips", "on")
    p.process_pending()
    assert stub.seen == [old]
    repo.set_setting(conn, "recognize_old_clips", "off")
    later = _ready_clip(conn, 9)
    p.process_pending()
    assert stub.seen == [old]  # off again: later is left waiting
    assert _recognition(conn, later) == (None, None)


def test_retry_is_recognised_with_backfill_off(settings, conn):
    _teach_great_tit(conn)
    asked, other = _ready_clip(conn, 9), _ready_clip(conn, 8)
    assert repo.requeue_recognition(conn, asked)
    stub = StubRecognizer(conn)
    p = Processor(settings, conn, stub)
    p.process_pending()
    p.process_pending()
    assert stub.seen == [asked]
    assert _recognition(conn, asked)[0] is not None
    assert conn.execute("SELECT recognition_wanted FROM clip WHERE id = ?", (asked,)).fetchone()[0] == 0
    assert _recognition(conn, other) == (None, None)


def test_a_wanted_clip_that_fails_is_not_wanted_any_more(settings, conn):
    _teach_great_tit(conn)
    bad = _ready_clip(conn, 8)
    repo.requeue_recognition(conn, bad)
    Processor(settings, conn, StubRecognizer(conn, fail=[bad])).process_pending()
    assert conn.execute("SELECT recognition_wanted FROM clip WHERE id = ?", (bad,)).fetchone()[0] == 0
    assert _recognition(conn, bad)[1] is not None

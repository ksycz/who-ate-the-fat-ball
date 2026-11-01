from datetime import datetime

import pytest

from fatball.config import Settings
from fatball.ingest import processor as processor_mod
from fatball.ingest.processor import Processor
from fatball.library import repo
from fatball.library.db import connect

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
    repo.set_clip_status(conn, clip_id, status, raw_path=str(raw))
    return clip_id, raw


def _get(conn, clip_id):
    return next(c for s in ("downloaded", "processing", "ready", "failed")
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
    repo.set_clip_status(conn, good, "downloaded", raw_path=str(raw))
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

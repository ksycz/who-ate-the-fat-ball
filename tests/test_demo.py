from datetime import datetime, timedelta

import pytest

from fatball import demo
from fatball.config import Settings
from fatball.ingest.processor import Processor
from fatball.ingest.watcher import Watcher
from fatball.library import repo
from fatball.library.db import connect

NOW = datetime(2026, 11, 1, 12, 0, 0)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "lib.db")
    yield c
    c.close()


def test_build_demo_camera_spreads_distinct_clips_over_two_days():
    cam = demo.build_demo_camera(n_clips=12, days=2, now=NOW)
    assert len(cam.files) == 12
    assert all(f.kind == "h264" and f.end <= NOW for f in cam.files)
    assert min(f.begin for f in cam.files) >= NOW - timedelta(days=2)
    assert len({f.begin.date() for f in cam.files}) >= 2
    assert len({f.sd_path for f in cam.files}) == 12
    assert len({f.payload for f in cam.files}) > 1  # different colours look different


def test_demo_ingests_all_clips_to_ready(tmp_path, conn):
    with demo.build_demo_camera(n_clips=12, days=2) as cam:
        settings = Settings(data_dir=tmp_path, camera_port=cam.port)
        repo.upsert_camera(conn, "feeder", None, "127.0.0.1")
        watcher = Watcher(settings, conn, **demo.watcher_options())
        result = watcher.tick()
        assert result.error is None and result.downloaded == 12
    assert Processor(settings, conn).process_pending() == 12
    assert len(repo.clips_with_status(conn, "ready")) == 12


def test_demo_watcher_never_touches_the_keychain(monkeypatch):
    def boom():
        raise AssertionError("demo read the Keychain")
    monkeypatch.setattr("fatball.secrets.get_password", boom)
    assert demo.watcher_options()["password"]() == ""

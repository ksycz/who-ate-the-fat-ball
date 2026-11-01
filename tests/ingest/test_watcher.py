from collections import namedtuple
from datetime import datetime, timedelta

import pytest

from fatball.camera.client import XMClient
from fatball.camera.fake import FakeFile
from fatball.config import Settings
from fatball.ingest import watcher as watcher_mod
from fatball.ingest.watcher import TickResult, Watcher
from fatball.library import repo
from fatball.library.db import connect

NOW = datetime(2026, 10, 31, 12, 0, 0)
PAYLOAD = bytes(range(256)) * 160  # 40 KiB


class Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "lib.db")
    yield c
    c.close()


@pytest.fixture
def cam(fake_camera):
    fake_camera.clock = NOW
    return fake_camera


def _file(begin: datetime, seconds: int = 30) -> FakeFile:
    return FakeFile(begin, begin + timedelta(seconds=seconds), "h264", PAYLOAD)


def _watcher(tmp_path, conn, cam, clock, *, ip="127.0.0.1", **kw):
    repo.upsert_camera(conn, "feeder", None, ip)
    settings = Settings(data_dir=tmp_path, camera_port=cam.port)
    kw.setdefault("find", lambda subnet, port, mac: None)
    kw.setdefault("sleep", lambda s: None)
    return Watcher(settings, conn, now=clock, password=lambda: "",
                   client_timeout=2.0, silence_s=1.0, probe_timeout=0.2, **kw)


def _downloaded(conn):
    return repo.clips_with_status(conn, "downloaded")


def test_first_tick_catches_up_seven_days_newest_first(tmp_path, conn, cam):
    for days in range(7):
        cam.add_file(_file(NOW.replace(hour=9) - timedelta(days=days)))
    cam.add_file(_file(NOW.replace(hour=9) - timedelta(days=9)))  # beyond the catch-up window
    w = _watcher(tmp_path, conn, cam, Clock(NOW))

    result = w.tick()

    assert result == TickResult(reachable=True, downloaded=7, error=None)
    clips = _downloaded(conn)
    assert len(clips) == 7
    by_id = sorted(clips, key=lambda c: c.id)
    assert [c.begin_at for c in by_id] == sorted((c.begin_at for c in clips), reverse=True)
    for c in clips:
        assert c.raw_path == str(tmp_path / "media" / "raw" / f"{c.id}.raw")
        assert (tmp_path / "media" / "raw" / f"{c.id}.raw").read_bytes() == PAYLOAD
    camera = repo.get_camera(conn)
    assert camera.last_error is None
    assert camera.last_seen_at == NOW.astimezone()


def test_second_tick_only_downloads_new_files(tmp_path, conn, cam):
    cam.add_file(_file(NOW.replace(hour=9)))
    clock = Clock(NOW)
    w = _watcher(tmp_path, conn, cam, clock)
    assert w.tick().downloaded == 1

    old_day = _file(NOW.replace(hour=9) - timedelta(days=2))  # only the first tick looks back
    cam.add_file(old_day)
    cam.add_file(_file(NOW.replace(hour=11)))
    clock.t = NOW + timedelta(seconds=5)

    assert w.tick().downloaded == 1
    assert sorted(c.begin_at.hour for c in _downloaded(conn)) == [9, 11]


def test_clip_filed_under_yesterday_just_after_midnight_is_still_fetched(tmp_path, conn, cam):
    midnight = NOW.replace(hour=0, minute=0)
    clock = Clock(midnight + timedelta(minutes=1))
    cam.clock = clock.t
    w = _watcher(tmp_path, conn, cam, clock)
    w.tick()  # catch-up
    clock.t = midnight + timedelta(minutes=5)
    w.tick()  # clean tick shortly after midnight
    cam.add_file(_file(midnight - timedelta(seconds=40)))  # finished being written just after midnight
    clock.t = midnight + timedelta(minutes=6)
    assert w.tick().downloaded == 1


def test_lists_days_missed_while_mac_was_asleep(tmp_path, conn, cam):
    clock = Clock(NOW)
    w = _watcher(tmp_path, conn, cam, clock)
    assert w.tick().error is None  # clean tick on day D
    cam.add_file(_file(NOW.replace(hour=9) + timedelta(days=1)))
    clock.t = NOW + timedelta(days=2)
    cam.clock = clock.t
    assert w.tick() == TickResult(reachable=True, downloaded=1, error=None)


def test_file_failing_three_times_is_skipped_and_older_files_still_download(tmp_path, conn, cam):
    poison = FakeFile(NOW.replace(hour=11), NOW.replace(hour=11, second=30), "h264", PAYLOAD, reported_kb=1000)
    cam.add_file(poison)
    cam.add_file(_file(NOW.replace(hour=9)))
    clock = Clock(NOW)
    w = _watcher(tmp_path, conn, cam, clock)

    for n in range(3):
        clock.t = NOW + timedelta(seconds=5 * n)
        assert w.tick() == TickResult(reachable=True, downloaded=0, error="download_interrupted")

    clock.t = NOW + timedelta(seconds=15)
    assert w.tick() == TickResult(reachable=True, downloaded=1, error=None)
    assert [c.begin_at.hour for c in repo.list_clips(conn, 10, None)] == [9]
    assert list((tmp_path / "media" / "raw").glob("*.part")) == []


def test_clock_query_failure_does_not_stop_downloads(tmp_path, conn, cam, monkeypatch):
    def broken(self):
        raise KeyError("OPTimeQuery")

    monkeypatch.setattr(XMClient, "camera_time", broken)
    cam.add_file(_file(NOW.replace(hour=9)))
    w = _watcher(tmp_path, conn, cam, Clock(NOW))

    assert w.tick() == TickResult(reachable=True, downloaded=1, error="clock_error")
    assert len(_downloaded(conn)) == 1
    assert repo.get_camera(conn).last_error == "clock_error"


def test_unexpected_tick_exception_is_recorded_and_polling_continues(tmp_path, conn, cam):
    def connect(*a, **k):
        raise RuntimeError("bug")

    sleeps = []
    w = _watcher(tmp_path, conn, cam, Clock(NOW), connect=connect,
                 sleep=lambda s: (sleeps.append(s), len(sleeps) == 2 and w.stop()))
    w.run_forever()
    assert len(sleeps) == 2
    assert repo.get_camera(conn).last_error == "internal_error"


def test_partial_download_is_discarded_and_retried(tmp_path, conn, cam):
    cam.add_file(_file(NOW.replace(hour=9)))
    cam.drop_after_bytes = 10_000
    clock = Clock(NOW)
    w = _watcher(tmp_path, conn, cam, clock)

    first = w.tick()

    assert first.downloaded == 0 and first.error is not None
    assert repo.list_clips(conn, 10, None) == []
    raw = tmp_path / "media" / "raw"
    assert list(raw.glob("*.part")) == [] and list(raw.iterdir()) == []

    cam.drop_after_bytes = None
    clock.t = NOW + timedelta(seconds=5)
    assert w.tick() == TickResult(reachable=True, downloaded=1, error=None)
    assert len(_downloaded(conn)) == 1
    assert repo.get_camera(conn).last_error is None


def test_clock_fixed_when_off_by_more_than_two_minutes(tmp_path, conn, cam):
    cam.clock = NOW + timedelta(hours=7)
    clock = Clock(NOW)
    w = _watcher(tmp_path, conn, cam, clock)

    w.tick()
    assert cam.set_time_calls == [NOW]
    assert repo.get_camera(conn).clock_offset_s == 0  # fixed

    cam.clock = NOW + timedelta(seconds=65)  # within tolerance: left alone
    clock.t = NOW + timedelta(seconds=5)
    w.tick()
    assert cam.set_time_calls == [NOW]
    assert repo.get_camera(conn).clock_offset_s == 60


def test_wrong_password_backs_off_ten_minutes(tmp_path, conn, cam):
    cam.password = "not-empty"
    clock = Clock(NOW)
    w = _watcher(tmp_path, conn, cam, clock)

    first = w.tick()
    assert first.error == "wrong_password"
    assert repo.get_camera(conn).last_error == "wrong_password"
    assert cam.login_attempts == 1

    for t in (5, 300, 599):
        clock.t = NOW + timedelta(seconds=t)
        assert w.tick().error == "wrong_password"
    assert cam.login_attempts == 1

    clock.t = NOW + timedelta(seconds=601)
    w.tick()
    assert cam.login_attempts == 2


def test_missing_password_does_not_connect(tmp_path, conn, cam):
    repo.upsert_camera(conn, "feeder", None, "127.0.0.1")
    w = Watcher(Settings(data_dir=tmp_path, camera_port=cam.port), conn, now=Clock(NOW),
                password=lambda: None, find=lambda *a: None)
    assert w.tick() == TickResult(reachable=False, downloaded=0, error="no_password")
    assert repo.get_camera(conn).last_error == "no_password"
    assert cam.login_attempts == 0


def test_unreachable_camera_records_nothing(tmp_path, conn, cam):
    cam.awake = False
    calls = []
    w = _watcher(tmp_path, conn, cam, Clock(NOW), find=lambda *a: calls.append(a))
    assert w.tick() == TickResult(reachable=False, downloaded=0, error=None)
    assert len(calls) == 1
    camera = repo.get_camera(conn)
    assert (camera.last_seen_at, camera.last_error, camera.last_ip) == (None, None, "127.0.0.1")


def test_rediscovers_camera_after_ip_change(tmp_path, conn, cam):
    cam.add_file(_file(NOW.replace(hour=9)))
    calls = []

    def find(subnet, port, mac):
        calls.append((subnet, port, mac))
        return "127.0.0.1"

    w = _watcher(tmp_path, conn, cam, Clock(NOW), ip="10.255.255.1", find=find)

    assert w.tick() == TickResult(reachable=True, downloaded=1, error=None)
    assert calls == [("10.255.255.1", cam.port, None)]
    assert repo.get_camera(conn).last_ip == "127.0.0.1"


def test_low_disk_stops_downloads(tmp_path, conn, cam, monkeypatch):
    cam.add_file(_file(NOW.replace(hour=9)))
    cam.add_file(_file(NOW.replace(hour=10)))
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(watcher_mod.shutil, "disk_usage", lambda path: usage(10**12, 10**12, 1_000))
    w = _watcher(tmp_path, conn, cam, Clock(NOW))

    result = w.tick()

    assert result == TickResult(reachable=True, downloaded=0, error="low_disk")
    assert repo.list_clips(conn, 10, None) == []
    assert repo.get_camera(conn).last_error == "low_disk"


def test_run_forever_ticks_and_sleeps_until_stopped(tmp_path, conn, cam):
    sleeps = []
    w = _watcher(tmp_path, conn, cam, Clock(NOW), sleep=lambda s: (sleeps.append(s), len(sleeps) == 3
                                                                   and w.stop()))
    w.run_forever()
    assert sleeps == [5.0, 5.0, 5.0]

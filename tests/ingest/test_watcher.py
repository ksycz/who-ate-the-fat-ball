from collections import namedtuple
from datetime import datetime, timedelta

import pytest

from fatball.camera.client import CameraError, XMClient
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
    kw.setdefault("mac_of", lambda ip: None)  # the fake camera has no MAC address
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
        assert c.raw_path == f"raw/{c.id}.raw"  # relative to media_dir
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


def test_file_failing_three_times_is_skipped_and_older_files_still_download(tmp_path, conn, cam, monkeypatch):
    real_download = XMClient.download

    def download(self, f, dest):
        if f.begin.hour == 11:
            raise CameraError("unexpected reply")
        return real_download(self, f, dest)

    monkeypatch.setattr(XMClient, "download", download)
    cam.add_file(_file(NOW.replace(hour=11)))
    cam.add_file(_file(NOW.replace(hour=9)))
    clock = Clock(NOW)
    w = _watcher(tmp_path, conn, cam, clock)

    for n in range(3):
        clock.t = NOW + timedelta(seconds=5 * n)
        assert w.tick() == TickResult(reachable=True, downloaded=0, error="camera_error")

    clock.t = NOW + timedelta(seconds=15)
    assert w.tick() == TickResult(reachable=True, downloaded=1, error=None)
    assert [c.begin_at.hour for c in repo.list_clips(conn, 10, None)] == [9]


def test_interrupted_downloads_never_mark_file_as_poison(tmp_path, conn, cam):
    cam.add_file(_file(NOW.replace(hour=9)))
    cam.drop_after_bytes = 10_000
    clock = Clock(NOW)
    w = _watcher(tmp_path, conn, cam, clock)

    for n in range(4):
        clock.t = NOW + timedelta(seconds=5 * n)
        assert w.tick() == TickResult(reachable=True, downloaded=0, error="download_interrupted")

    cam.drop_after_bytes = None
    clock.t = NOW + timedelta(seconds=20)
    assert w.tick() == TickResult(reachable=True, downloaded=1, error=None)
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


def test_an_old_error_is_cleared_as_soon_as_the_login_works(tmp_path, conn, cam):
    cam.add_file(_file(NOW.replace(hour=9)))
    w = _watcher(tmp_path, conn, cam, Clock(NOW))
    repo.update_camera_status(conn, repo.get_camera(conn).id, last_error="wrong_password")
    seen_while_downloading = []
    download = w._download

    def spy(client, camera_id, f):
        seen_while_downloading.append(repo.get_camera(conn).last_error)
        return download(client, camera_id, f)

    w._download = spy
    assert w.tick().downloaded == 1
    assert seen_while_downloading == [None]


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


def test_more_than_64_clips_in_one_day_are_all_ingested(tmp_path, conn, cam):
    start = NOW.replace(hour=6)
    for i in range(70):
        b = start + timedelta(minutes=4 * i)
        cam.add_file(FakeFile(b, b + timedelta(seconds=8), "h264", b"c" * 1024))
    w = _watcher(tmp_path, conn, cam, Clock(NOW))
    assert w.tick() == TickResult(reachable=True, downloaded=70, error=None)
    assert len(_downloaded(conn)) == 70


def test_clip_is_downloading_while_its_download_runs(tmp_path, conn, cam, monkeypatch):
    real_download = XMClient.download
    statuses = []

    def download(self, f, dest):
        statuses.extend(c.status for c in repo.list_clips(conn, 10, None))
        return real_download(self, f, dest)

    monkeypatch.setattr(XMClient, "download", download)
    cam.add_file(_file(NOW.replace(hour=9)))
    w = _watcher(tmp_path, conn, cam, Clock(NOW))
    assert w.tick().downloaded == 1
    assert statuses == ["downloading"]
    assert [c.status for c in repo.list_clips(conn, 10, None)] == ["downloaded"]


def test_crash_leftovers_are_cleaned_on_start_and_the_clip_refetched(tmp_path, conn, cam):
    f = _file(NOW.replace(hour=9))
    cam.add_file(f)
    camera_id = repo.upsert_camera(conn, "feeder", None, "127.0.0.1")
    crashed = repo.add_clip(conn, camera_id, f.sd_path, f.begin, f.end, "h264", 1)  # left 'downloading'
    kept = repo.add_clip(conn, camera_id, "/other", NOW.replace(hour=8), NOW.replace(hour=8), "h264", 1)
    repo.set_clip_status(conn, kept, "ready", raw_path=f"raw/{kept}.raw")
    raw = tmp_path / "media" / "raw"
    raw.mkdir(parents=True)
    (raw / f"{crashed}.raw.part").write_bytes(b"half")
    (raw / f"{crashed}.raw").write_bytes(b"renamed but row never flipped")
    (raw / "12345.raw").write_bytes(b"orphan")
    (raw / f"{kept}.raw").write_bytes(b"keep me")

    w = _watcher(tmp_path, conn, cam, Clock(NOW))

    assert repo.clips_with_status(conn, "downloading") == []
    assert sorted(p.name for p in raw.iterdir()) == [f"{kept}.raw"]
    assert w.tick() == TickResult(reachable=True, downloaded=1, error=None)
    [again] = _downloaded(conn)
    assert again.sd_path == f.sd_path and (tmp_path / "media" / again.raw_path).read_bytes() == PAYLOAD


def _scan_log():
    calls = []

    def find(subnet, port, mac):
        calls.append(subnet)

    return calls, find


def test_sleeping_camera_seen_within_the_hour_is_never_scanned_for(tmp_path, conn, cam):
    cam.awake = False
    calls, find = _scan_log()
    clock = Clock(NOW)
    w = _watcher(tmp_path, conn, cam, clock, find=find, arp_lookup=lambda mac: None)
    repo.update_camera_status(conn, repo.get_camera(conn).id, last_seen_at=NOW - timedelta(minutes=1))
    for minute in range(60):
        clock.t = NOW + timedelta(minutes=minute)
        assert w.tick() == TickResult(reachable=False, downloaded=0, error=None)
    assert calls == []


def test_arp_table_finds_camera_at_a_new_ip_without_scanning(tmp_path, conn, cam):
    cam.add_file(_file(NOW.replace(hour=9)))
    calls, find = _scan_log()
    looked_up = []
    w = _watcher(tmp_path, conn, cam, Clock(NOW), ip="10.255.255.1", find=find,
                 arp_lookup=lambda mac: looked_up.append(mac) or "127.0.0.1", mac_of=lambda ip: "aa:bb:cc:dd:ee:ff")
    camera_id = repo.upsert_camera(conn, "feeder", "aa:bb:cc:dd:ee:ff", None)
    repo.update_camera_status(conn, camera_id, last_seen_at=NOW - timedelta(minutes=5))

    assert w.tick() == TickResult(reachable=True, downloaded=1, error=None)
    assert looked_up == ["aa:bb:cc:dd:ee:ff"] and calls == []
    assert repo.get_camera(conn).last_ip == "127.0.0.1"


def test_full_scans_back_off_exponentially_up_to_four_hours(tmp_path, conn, cam):
    cam.awake = False  # never seen, so scanning is allowed, but with back-off
    calls = []
    clock = Clock(NOW)
    w = _watcher(tmp_path, conn, cam, clock, find=lambda s, p, m: (calls.append(clock.t), None)[1],
                 arp_lookup=lambda mac: None)
    for minute in range(12 * 60):
        clock.t = NOW + timedelta(minutes=minute)
        w.tick()
    minutes = [int((t - NOW).total_seconds() // 60) for t in calls]
    assert minutes == [0, 15, 45, 105, 225, 465, 705]


def test_scan_back_off_resets_once_the_camera_is_found(tmp_path, conn, cam):
    cam.add_file(_file(NOW.replace(hour=9)))
    clock = Clock(NOW)
    scans = []

    def find(subnet, port, mac):
        scans.append(clock.t)
        return "127.0.0.1" if len(scans) == 3 else None

    w = _watcher(tmp_path, conn, cam, clock, ip="10.255.255.1", find=find, arp_lookup=lambda mac: None)
    expected = {0: False, 14: False, 15: False, 44: False, 45: True}
    for minute, reachable in expected.items():
        clock.t = NOW + timedelta(minutes=minute)
        assert w.tick().reachable is reachable
    assert len(scans) == 3

    cam.awake = False  # seen at minute 45 on 127.0.0.1, then asleep
    for minute in (100, 105):  # within the hour since last seen: no scan
        clock.t = NOW + timedelta(minutes=minute)
        w.tick()
    assert len(scans) == 3
    for minute in (106, 120, 121):  # unseen > 1 h: scan, then back off 15 min (reset), not 4 h
        clock.t = NOW + timedelta(minutes=minute)
        w.tick()
    assert [int((t - NOW).total_seconds() // 60) for t in scans[3:]] == [106, 121]


def test_first_run_without_an_ip_scans_the_local_subnet_with_back_off(tmp_path, conn, cam, monkeypatch):
    monkeypatch.setattr(watcher_mod.discovery, "local_ipv4", lambda: "192.168.1.5")
    calls, find = _scan_log()
    clock = Clock(NOW)
    w = _watcher(tmp_path, conn, cam, clock, ip=None, find=find, arp_lookup=lambda mac: None)
    for minute in (0, 1, 14):
        clock.t = NOW + timedelta(minutes=minute)
        assert w.tick().reachable is False
    assert calls == ["192.168.1.5"]


CAMERA_MAC = "aa:bb:cc:dd:ee:ff"
OTHER_MAC = "11:22:33:44:55:66"


def test_first_good_login_remembers_the_cameras_mac(tmp_path, conn, cam):
    w = _watcher(tmp_path, conn, cam, Clock(NOW), mac_of=lambda ip: CAMERA_MAC)

    assert w.tick().error is None
    assert repo.get_camera(conn).mac == CAMERA_MAC


def test_no_mac_in_the_arp_table_leaves_the_camera_unpinned(tmp_path, conn, cam):
    w = _watcher(tmp_path, conn, cam, Clock(NOW), mac_of=lambda ip: None)

    assert w.tick().error is None
    assert repo.get_camera(conn).mac is None


def test_another_device_at_the_cameras_ip_never_gets_the_login(tmp_path, conn, cam):
    cam.add_file(_file(NOW.replace(hour=9)))
    w = _watcher(tmp_path, conn, cam, Clock(NOW), mac_of=lambda ip: OTHER_MAC, arp_lookup=lambda mac: None)
    camera_id = repo.upsert_camera(conn, "feeder", CAMERA_MAC, None)
    repo.update_camera_status(conn, camera_id, last_seen_at=NOW - timedelta(minutes=5))

    assert w.tick() == TickResult(reachable=False, downloaded=0, error="other_device")
    assert cam.login_attempts == 0
    camera = repo.get_camera(conn)
    assert camera.last_error == "other_device"
    assert camera.last_seen_at == (NOW - timedelta(minutes=5)).astimezone()


def test_camera_is_found_by_its_mac_when_another_device_took_its_old_ip(tmp_path, conn, cam):
    cam.add_file(_file(NOW.replace(hour=9)))
    macs = {"localhost": OTHER_MAC, "127.0.0.1": CAMERA_MAC}
    w = _watcher(tmp_path, conn, cam, Clock(NOW), ip="localhost", mac_of=macs.get,
                 arp_lookup=lambda mac: "127.0.0.1" if mac == CAMERA_MAC else None)
    repo.upsert_camera(conn, "feeder", CAMERA_MAC, None)

    assert w.tick() == TickResult(reachable=True, downloaded=1, error=None)
    assert repo.get_camera(conn).last_ip == "127.0.0.1"


def test_a_scan_hit_with_another_mac_gets_no_login(tmp_path, conn, cam):
    w = _watcher(tmp_path, conn, cam, Clock(NOW), ip=None, find=lambda subnet, port, mac: "127.0.0.1",
                 mac_of=lambda ip: OTHER_MAC, arp_lookup=lambda mac: None)
    repo.upsert_camera(conn, "feeder", CAMERA_MAC, None)

    assert w.tick().reachable is False
    assert cam.login_attempts == 0

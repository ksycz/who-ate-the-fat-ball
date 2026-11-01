from datetime import date, datetime, timedelta

import pytest

from fatball.camera.client import (
    CameraUnreachable,
    DownloadInterrupted,
    WrongPassword,
    XMClient,
)
from fatball.camera.fake import FakeFile

BEGIN = datetime(2026, 10, 30, 7, 15, 2)
END = datetime(2026, 10, 30, 7, 15, 40)


def _client(cam, **kw):
    return XMClient("127.0.0.1", cam.port, timeout=2.0, silence_s=0.5, **kw)


def _file(payload=b"x" * 5000, kind="h264"):
    return FakeFile(BEGIN, END, kind, payload)


def test_login_wrong_password_raises(fake_camera):
    fake_camera.password = "secret"
    with _client(fake_camera) as cam, pytest.raises(WrongPassword):
        cam.login("admin", "nope")


def test_login_ok_and_system_info(fake_camera):
    with _client(fake_camera) as cam:
        cam.login("admin", "")
        assert cam.system_info()["SerialNo"] == "FAKE0000"


def test_unreachable_raises():
    with pytest.raises(CameraUnreachable), XMClient("127.0.0.1", 1, timeout=0.5) as cam:
        cam.login("admin", "")


def test_list_files_parses_begin_end_and_size(fake_camera):
    fake_camera.add_file(_file(b"x" * 5000))
    fake_camera.add_file(FakeFile(datetime(2026, 10, 29, 8, 0, 0), datetime(2026, 10, 29, 8, 1, 0), "h264", b"y"))
    with _client(fake_camera) as cam:
        cam.login("admin", "")
        files = cam.list_files(date(2026, 10, 30), "h264")
        assert cam.list_files(date(2026, 10, 30), "jpg") == []
    assert len(files) == 1
    f = files[0]
    assert (f.begin, f.end, f.size_kb, f.kind) == (BEGIN, END, 5, "h264")
    assert f.sd_path == fake_camera.files[0].sd_path


def test_download_writes_exact_payload(fake_camera, tmp_path):
    payload = bytes(range(256)) * 400
    fake_camera.add_file(_file(payload))
    dest = tmp_path / "clip.raw"
    with _client(fake_camera) as cam:
        cam.login("admin", "")
        [f] = cam.list_files(date(2026, 10, 30), "h264")
        assert cam.download(f, dest) == len(payload)
    assert dest.read_bytes() == payload
    assert not dest.with_suffix(".raw.part").exists()


def test_download_interrupted_raises_and_leaves_no_file(fake_camera, tmp_path):
    fake_camera.add_file(_file(b"z" * 50000))
    fake_camera.drop_after_bytes = 1000
    dest = tmp_path / "clip.raw"
    with _client(fake_camera) as cam:
        cam.login("admin", "")
        [f] = cam.list_files(date(2026, 10, 30), "h264")
        with pytest.raises(DownloadInterrupted):
            cam.download(f, dest)
    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []


def test_camera_time_and_set_time_sends_mac_time(fake_camera):
    fake_camera.clock = datetime(2026, 1, 1, 0, 0, 0)
    target = datetime(2026, 10, 31, 12, 30, 5)
    with _client(fake_camera) as cam:
        cam.login("admin", "")
        assert cam.camera_time() == datetime(2026, 1, 1, 0, 0, 0)
        cam.set_time(target)
        assert cam.camera_time() == target
    assert fake_camera.set_time_calls == [target]


def test_download_accepts_camera_size_overreport(fake_camera, tmp_path):
    payload = b"q" * 100_000
    fake_camera.add_file(FakeFile(BEGIN, END, "h264", payload, reported_kb=101))  # advertises ~1% more than it sends
    dest = tmp_path / "clip.raw"
    with _client(fake_camera) as cam:
        cam.login("admin", "")
        [f] = cam.list_files(date(2026, 10, 30), "h264")
        assert f.size_kb * 1024 > len(payload)
        assert cam.download(f, dest) == len(payload)
    assert dest.read_bytes() == payload


def test_list_files_pages_past_the_64_result_limit(fake_camera):
    day = datetime(2026, 10, 30)
    for i in range(150):
        b = day + timedelta(minutes=5 * i, seconds=i % 3)
        fake_camera.add_file(FakeFile(b, b + timedelta(seconds=10), "h264", b"x"))
    with _client(fake_camera) as cam:
        cam.login("admin", "")
        files = cam.list_files(date(2026, 10, 30), "h264")
    assert len(files) == 150
    assert len({(f.sd_path, f.begin) for f in files}) == 150
    assert sorted(f.begin for f in files) == sorted(f.begin for f in fake_camera.files)


def test_list_files_stops_when_a_page_adds_nothing_new(fake_camera):
    # 70 files sharing one begin second: re-querying from that second returns the same 64 forever.
    b = datetime(2026, 10, 30, 9, 0, 0)
    for i in range(70):
        fake_camera.add_file(FakeFile(b, b + timedelta(seconds=10 + i), "h264", b"x"))
    with _client(fake_camera) as cam:
        cam.login("admin", "")
        files = cam.list_files(date(2026, 10, 30), "h264")
    assert len(files) == 64

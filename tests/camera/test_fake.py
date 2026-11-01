import socket
from datetime import datetime, timedelta

import pytest

from fatball.camera.fake import FakeCamera, FakeFile
from fatball.camera.protocol import (
    FILE_QUERY,
    HEADER,
    LOGIN,
    PLAY_CLAIM,
    PLAY_DATA,
    PLAY_REQ,
    TIME_QUERY,
    TIME_SET,
    decode_header,
    decode_payload,
    encode,
    sofia_hash,
)


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


def _read(sock):
    _, msg_id, length = decode_header(_recv_exact(sock, HEADER.size))
    return msg_id, _recv_exact(sock, length)


def _ask(sock, msg_id, payload, session=0):
    sock.sendall(encode(session, 0, msg_id, payload))
    msg_id, body = _read(sock)
    return msg_id, decode_payload(body)


def _connect(cam):
    s = socket.create_connection(("127.0.0.1", cam.port), timeout=5)
    return s


def _login(sock, password=""):
    return _ask(sock, LOGIN, {"EncryptType": "MD5", "LoginType": "DVRIP-Web",
                              "PassWord": sofia_hash(password), "UserName": "admin"})[1]


def _query(sock, day, kind="h264"):
    return _ask(sock, FILE_QUERY, {"Name": "OPFileQuery", "OPFileQuery": {
        "BeginTime": f"{day} 00:00:00", "EndTime": f"{day} 23:59:59", "Type": kind}})[1]


def test_login_ok_and_wrong_password(fake_camera):
    with _connect(fake_camera) as s:
        assert _login(s)["Ret"] == 100
    with _connect(fake_camera) as s:
        assert _login(s, "x")["Ret"] == 205
    assert fake_camera.login_attempts == 2


def test_file_query_caps_at_64(fake_camera):
    for n in range(70):
        begin = datetime(2026, 10, 31, 8, 0, 0) + timedelta(minutes=n)
        fake_camera.add_file(FakeFile(begin, begin + timedelta(seconds=5), "h264", b"x"))
    fake_camera.add_file(FakeFile(datetime(2026, 10, 30, 8, 0, 0), datetime(2026, 10, 30, 8, 0, 5), "h264", b"x"))
    with _connect(fake_camera) as s:
        _login(s)
        files = _query(s, "2026-10-31")["OPFileQuery"]
    assert len(files) == 64
    assert [f["BeginTime"] for f in files] == sorted(f["BeginTime"] for f in files)
    assert files[0]["BeginTime"] == "2026-10-31 08:00:00"


def test_sleeping_camera_refuses_connection(fake_camera):
    fake_camera.awake = False
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", fake_camera.port), timeout=2).close()
    fake_camera.awake = True
    _connect(fake_camera).close()


def test_sd_path_follows_real_naming():
    f = FakeFile(datetime(2026, 10, 31, 9, 12, 0), datetime(2026, 10, 31, 9, 12, 11), "h264", b"")
    assert f.sd_path == "/mnt/sd0/2026-10-31/001/09.12.00-09.12.11[A][@7][0](0).h264"


def _download(cam, f, expect_all=True):
    main, data = _connect(cam), _connect(cam)
    with main, data:
        sess = int(_login(main)["SessionID"], 16)
        pb = {"Name": "OPPlayBack", "OPPlayBack": {"Action": "Claim", "Parameter": {"FileName": f.sd_path}},
              "SessionID": f"0x{sess:08X}"}
        data.sendall(encode(sess, 0, PLAY_CLAIM, pb))
        pb["OPPlayBack"]["Action"] = "DownloadStart"
        assert _ask(main, PLAY_REQ, pb, sess)[1]["Ret"] == 100
        got = b""
        try:
            while True:
                msg_id, body = _read(data)
                if msg_id == PLAY_DATA:
                    assert len(body) <= 32 * 1024
                    got += body
        except ConnectionError:
            pass
        pb["OPPlayBack"]["Action"] = "DownloadStop"
        assert _ask(main, PLAY_REQ, pb, sess)[1]["Ret"] == 100
    return got


def test_download_streams_payload(fake_camera):
    f = FakeFile(datetime(2026, 10, 31, 9, 0, 0), datetime(2026, 10, 31, 9, 0, 9), "h264", bytes(range(256)) * 400)
    fake_camera.add_file(f)
    assert _download(fake_camera, f) == f.payload


def test_drop_after_bytes_cuts_stream(fake_camera):
    f = FakeFile(datetime(2026, 10, 31, 9, 0, 0), datetime(2026, 10, 31, 9, 0, 9), "h264", b"a" * 100_000)
    fake_camera.add_file(f)
    fake_camera.drop_after_bytes = 40_000
    got = _download(fake_camera, f)
    assert 0 < len(got) <= 40_000


def test_time_query_and_set(fake_camera):
    fake_camera.clock = datetime(2026, 10, 31, 12, 0, 0)
    with _connect(fake_camera) as s:
        _login(s)
        assert _ask(s, TIME_QUERY, {"Name": "OPTimeQuery"})[1]["OPTimeQuery"] == "2026-10-31 12:00:00"
        reply = _ask(s, TIME_SET, {"Name": "OPTimeSetting", "OPTimeSetting": "2026-10-31 13:30:05"})[1]
    assert reply["Ret"] == 100
    assert fake_camera.set_time_calls == [datetime(2026, 10, 31, 13, 30, 5)]
    assert fake_camera.clock == datetime(2026, 10, 31, 13, 30, 5)


def test_xm_clip_bytes_starts_with_fc_frame(xm_clip_bytes):
    assert xm_clip_bytes[:4] == b"\x00\x00\x01\xfc"
    assert xm_clip_bytes[4] & 0x0F == 3
    assert xm_clip_bytes.count(b"\x00\x00\x01\xfd") > 5


def test_context_manager_stops_server():
    with FakeCamera() as cam:
        port = cam.port
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()

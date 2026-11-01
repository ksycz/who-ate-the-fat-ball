import logging
import shutil
from datetime import datetime, timedelta

import pytest

from fatball.library import repo

from .conftest import NOW


def _status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    return r.json()


def test_status_ok_asleep_problem(local, conn, cam):
    assert _status(local)["camera"]["state"] == "problem"  # never seen

    repo.update_camera_status(conn, cam, last_seen_at=NOW - timedelta(minutes=30))
    body = _status(local)["camera"]
    assert body["state"] == "ok" and body["last_error"] is None and body["last_seen_at"]

    repo.update_camera_status(conn, cam, last_seen_at=NOW - timedelta(hours=5))
    assert _status(local)["camera"]["state"] == "asleep"

    repo.update_camera_status(conn, cam, last_seen_at=NOW - timedelta(days=1, hours=1))
    assert _status(local)["camera"]["state"] == "problem"

    repo.update_camera_status(conn, cam, last_seen_at=NOW - timedelta(minutes=1), last_error="wrong password")
    body = _status(local)["camera"]
    assert body["state"] == "problem" and body["last_error"] == "wrong password"


def test_status_viewable_from_lan_and_reports_queue(lan, conn, cam):
    for i, st in enumerate(["downloaded", "processing", "failed", "ready"]):
        cid = repo.add_clip(conn, cam, f"/p{i}", datetime(2026, 10, 31, 8, i), datetime(2026, 10, 31, 8, i), "video", 1)
        repo.set_clip_status(conn, cid, st)
    assert _status(lan)["queue"] == {"downloaded": 1, "processing": 1, "failed": 1}


def test_status_reports_low_disk(local, monkeypatch, settings):
    usage = shutil._ntuple_diskusage
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(100, 90, settings.min_free_bytes - 1))
    assert _status(local)["disk"] == {"free_bytes": settings.min_free_bytes - 1, "low": True}
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(100, 90, settings.min_free_bytes))
    assert _status(local)["disk"]["low"] is False


def test_clips_ready_only_newest_first_with_urls_and_cursor(local, conn, cam):
    ids = []
    for i in range(3):
        b = datetime(2026, 10, 31, 8, i * 10)
        cid = repo.add_clip(conn, cam, f"/p{i}", b, b + timedelta(seconds=20), "video", 1)
        repo.set_clip_status(
            conn, cid, "ready", web_path=f"clips/{cid}/web.mp4", poster_path=f"clips/{cid}/poster.jpg", duration_s=20.0
        )
        ids.append(cid)
    repo.add_clip(conn, cam, "/pending", datetime(2026, 10, 31, 12), datetime(2026, 10, 31, 12), "video", 1)

    body = local.get("/api/clips").json()
    assert [c["id"] for c in body] == ids[::-1]
    assert body[0]["web_url"] == f"/media/clips/{ids[2]}/web.mp4"
    assert body[0]["poster_url"] == f"/media/clips/{ids[2]}/poster.jpg"
    assert body[0]["original_url"] is None and body[0]["duration_s"] == 20.0

    assert len(local.get("/api/clips?limit=2").json()) == 2
    before = body[1]["begin_at"]
    older = local.get("/api/clips", params={"before": before}).json()
    assert [c["id"] for c in older] == [ids[0]]


def test_clips_rejects_bad_params(local):
    assert local.get("/api/clips?limit=0").status_code == 422
    assert local.get("/api/clips?before=nope").status_code == 422


def _media_file(settings, size=1000):
    d = settings.media_dir / "clips" / "1"
    d.mkdir(parents=True)
    (d / "web.mp4").write_bytes((bytes(range(256)) * 4)[:size])
    return "/media/clips/1/web.mp4"


def test_media_supports_range_requests(lan, settings):
    url = _media_file(settings)
    r = lan.get(url, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert len(r.content) == 100
    assert r.headers["content-range"] == "bytes 0-99/1000"
    full = lan.get(url)
    assert full.status_code == 200 and len(full.content) == 1000


def test_media_rejects_path_traversal(local, settings):
    settings.db_path.touch()
    for url in ("/media/../library.sqlite", "/media/%2e%2e/library.sqlite", "/media/clips/%2e%2e/%2e%2e/library.sqlite"):
        assert local.get(url).status_code == 404
    (settings.data_dir / "secret.txt").write_text("x")
    assert local.get("/media/..%2fsecret.txt").status_code == 404


def test_media_rejects_symlink_escape_and_missing_and_dirs(local, settings):
    outside = settings.data_dir / "outside.txt"
    outside.write_text("x")
    (settings.media_dir / "link.txt").symlink_to(outside)
    assert local.get("/media/link.txt").status_code == 404
    assert local.get("/media/nothing.mp4").status_code == 404
    (settings.media_dir / "dir").mkdir()
    assert local.get("/media/dir").status_code == 404


def test_setup_forbidden_from_lan_ip(lan, stored_passwords, conn):
    r = lan.put("/api/setup", json={"password": "pw", "edit_pin": "1234", "ip": "10.0.0.1"})
    assert r.status_code == 403
    assert stored_passwords == []
    assert repo.get_setting(conn, "edit_pin_hash") is None


def test_setup_from_local_stores_ip_password_pin(local, stored_passwords, conn):
    r = local.put("/api/setup", json={"ip": "192.168.1.77", "password": "pw", "edit_pin": "1234"})
    assert r.status_code == 204
    assert stored_passwords == ["pw"]
    assert repo.get_camera(conn).last_ip == "192.168.1.77"
    assert repo.get_setting(conn, "edit_pin_hash")


def test_setup_fields_optional(local, stored_passwords, conn):
    assert local.put("/api/setup", json={}).status_code == 204
    assert stored_passwords == []


def test_setup_rejects_bad_pin(local, conn):
    for pin in ("123", "12345", "abcd", "12 4", "١٢٣٤"):
        assert local.put("/api/setup", json={"edit_pin": pin}).status_code == 422
    assert repo.get_setting(conn, "edit_pin_hash") is None


def test_setup_password_never_in_db_or_logs(local, conn, caplog, stored_passwords):
    caplog.set_level(logging.DEBUG)
    secret_pw, pin = "hunter2-camera-pw", "4821"
    assert local.put("/api/setup", json={"password": secret_pw, "edit_pin": pin}).status_code == 204
    local.post("/api/unlock", json={"pin": pin})
    dump = "\n".join(conn.iterdump())
    assert secret_pw not in dump and secret_pw not in caplog.text
    assert pin not in caplog.text
    assert f"'{pin}'" not in dump


def test_media_nul_byte_is_404_not_500(local):
    assert local.get("/media/a%00b").status_code == 404


def test_concurrent_requests_each_use_their_own_connection(make_client, conn, cam, monkeypatch):
    import sqlite3
    import threading

    from fatball.library import db

    repo.update_camera_status(conn, cam, last_seen_at=NOW - timedelta(minutes=1))
    make_client().put("/api/setup", json={"edit_pin": "1234"})
    real_connect = db.connect
    opened: list[tuple[sqlite3.Connection, int]] = []
    lock = threading.Lock()

    def spy(path):
        c = real_connect(path)
        with lock:
            opened.append((c, threading.get_ident()))
        return c

    monkeypatch.setattr(db, "connect", spy)
    n = 16
    barrier = threading.Barrier(n)
    results = []

    def hit(i):
        client = make_client((f"192.168.1.{60 + i}", 5000))
        barrier.wait()
        # An exception here is an unhandled thread exception, which -W error turns into a failure.
        if i % 2:
            results.append(client.get("/api/status").status_code)
        else:
            results.append(client.post("/api/unlock", json={"pin": "1234"}).status_code)

    threads = [threading.Thread(target=hit, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [200] * (n // 2) + [204] * (n // 2)
    assert len({id(c) for c, _ in opened}) >= n  # at least one fresh connection per request
    for c, _ in opened:  # and every one was closed afterwards
        with pytest.raises(sqlite3.ProgrammingError):
            c.execute("SELECT 1")


def test_connect_waits_for_a_busy_database(settings):
    from fatball.library import db

    c = db.connect(settings.db_path)
    try:
        assert c.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
    finally:
        c.close()

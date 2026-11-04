import hashlib
import json

from fastapi import Depends, FastAPI

from fatball.api import auth
from fatball.library import repo

from .conftest import LAN, LOCAL, TestClient


def _set_pin(local, pin="1234"):
    assert local.put("/api/setup", json={"edit_pin": pin}).status_code == 204


def test_pin_stored_hashed_not_plaintext(local, conn):
    _set_pin(local, "4821")
    stored = repo.get_setting(conn, "edit_pin_hash")
    scheme, salt, digest = stored.split("$")
    assert scheme == "scrypt" and len(bytes.fromhex(salt)) == 16 and bytes.fromhex(digest)
    expected = hashlib.scrypt(b"4821", salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    assert expected.hex() == digest
    _set_pin(local, "4821")  # new salt each time
    assert repo.get_setting(conn, "edit_pin_hash") != stored


def test_unlock_right_pin_sets_cookie_and_me_can_edit(make_client, conn):
    _set_pin(make_client(LOCAL))
    lan = make_client(LAN)
    assert lan.get("/api/me").json() == {"can_edit": False}
    r = lan.post("/api/unlock", json={"pin": "1234"})
    assert r.status_code == 204
    header = r.headers["set-cookie"].lower()
    assert "fatball_editor=" in header and "httponly" in header and "samesite=strict" in header
    assert f"max-age={400 * 86400}" in header and "path=/" in header
    assert lan.get("/api/me").json() == {"can_edit": True}
    # token stored hashed
    token = lan.cookies["fatball_editor"]
    stored = json.loads(repo.get_setting(conn, "editor_tokens"))
    assert hashlib.sha256(token.encode()).hexdigest() in stored and token not in stored
    # another browser without the cookie still cannot edit
    assert make_client(LAN).get("/api/me").json() == {"can_edit": False}


def test_me_local_can_edit(local):
    assert local.get("/api/me").json() == {"can_edit": True}


def test_bogus_cookie_cannot_edit(lan):
    lan.cookies.set("fatball_editor", "forged")
    assert lan.get("/api/me").json() == {"can_edit": False}


def test_unlock_without_pin_configured_is_401(lan):
    assert lan.post("/api/unlock", json={"pin": "1234"}).status_code == 401


def test_unlock_wrong_pin_401_and_locks_after_five_for_15_min(make_client, clock):
    _set_pin(make_client(LOCAL))
    lan = make_client(LAN)
    for _ in range(5):
        assert lan.post("/api/unlock", json={"pin": "0000"}).status_code == 401
    assert lan.post("/api/unlock", json={"pin": "1234"}).status_code == 429  # even the right one
    assert make_client(("192.168.1.51", 1)).post("/api/unlock", json={"pin": "1234"}).status_code == 204
    clock.advance(minutes=14, seconds=59)
    assert lan.post("/api/unlock", json={"pin": "1234"}).status_code == 429
    clock.advance(seconds=2)
    assert lan.post("/api/unlock", json={"pin": "1234"}).status_code == 204


def test_ten_wrong_pins_from_any_addresses_lock_every_device_for_the_hour(make_client, clock):
    """Per-address lockout alone lets a device that switches addresses keep guessing the 4-digit PIN."""
    _set_pin(make_client(LOCAL))
    for i in range(10):
        clock.advance(minutes=1)
        assert make_client((f"192.168.1.{60 + i}", 1)).post("/api/unlock", json={"pin": "0000"}).status_code == 401
    phone = make_client(("192.168.1.99", 1))
    assert phone.post("/api/unlock", json={"pin": "1234"}).status_code == 429  # even the right one
    clock.advance(minutes=50, seconds=59)  # the first wrong PIN is still under an hour old
    assert phone.post("/api/unlock", json={"pin": "1234"}).status_code == 429
    clock.advance(seconds=2)
    assert phone.post("/api/unlock", json={"pin": "1234"}).status_code == 204


def test_a_right_pin_does_not_count_towards_the_overall_limit(make_client):
    _set_pin(make_client(LOCAL))
    for i in range(12):
        assert make_client((f"192.168.1.{60 + i}", 1)).post("/api/unlock", json={"pin": "1234"}).status_code == 204


def test_success_resets_failure_count(make_client):
    _set_pin(make_client(LOCAL))
    lan = make_client(LAN)
    for _ in range(4):
        lan.post("/api/unlock", json={"pin": "0000"})
    assert lan.post("/api/unlock", json={"pin": "1234"}).status_code == 204
    for _ in range(4):
        assert lan.post("/api/unlock", json={"pin": "0000"}).status_code == 401


def test_unlock_rejects_malformed_pin(lan):
    assert lan.post("/api/unlock", json={}).status_code == 422


def test_require_editor_allows_local_rejects_lan_without_cookie(app, make_client):
    @app.put("/api/_protected", dependencies=[Depends(auth.require_editor)])
    def protected():
        return {"ok": True}

    _set_pin(make_client(LOCAL))
    assert make_client(LOCAL).put("/api/_protected").status_code == 200
    lan = make_client(LAN)
    assert lan.put("/api/_protected").status_code == 403
    lan.post("/api/unlock", json={"pin": "1234"})
    assert lan.put("/api/_protected").status_code == 200


def test_require_editor_without_auth_state_fails_closed():
    bare = FastAPI()

    @bare.get("/x", dependencies=[Depends(auth.require_editor)])
    def x():
        return 1

    assert TestClient(bare, client=LAN).get("/x").status_code == 403


def test_concurrent_wrong_pins_get_at_most_five_401s(app, make_client):
    import threading

    _set_pin(make_client(LOCAL))
    n = 20
    barrier = threading.Barrier(n)
    codes = []

    def guess():
        client = make_client(LAN)
        barrier.wait()
        codes.append(client.post("/api/unlock", json={"pin": "0000"}).status_code)

    threads = [threading.Thread(target=guess) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes.count(401) <= 5
    assert codes.count(401) + codes.count(429) == n


def test_malformed_pin_hash_is_no_match_not_500(make_client, conn):
    repo.set_setting(conn, "edit_pin_hash", "garbage")
    assert make_client(LAN).post("/api/unlock", json={"pin": "1234"}).status_code == 401
    repo.set_setting(conn, "edit_pin_hash", "scrypt$zz$zz")
    assert make_client(LAN).post("/api/unlock", json={"pin": "1234"}).status_code == 401


def test_setup_rejects_loopback_with_foreign_host_header(make_client):
    c = make_client(LOCAL)
    assert c.put("/api/setup", json={}, headers={"Host": "evil.example"}).status_code == 403
    assert c.put("/api/setup", json={}, headers={"Host": "localhost:8000"}).status_code == 204
    assert c.put("/api/setup", json={}, headers={"Host": "[::1]:8000"}).status_code == 204
    assert c.get("/api/me", headers={"Host": "evil.example"}).json() == {"can_edit": False}


def test_setup_rejects_loopback_with_foreign_origin(make_client):
    c = make_client(LOCAL)
    assert c.put("/api/setup", json={}, headers={"Origin": "http://evil.example"}).status_code == 403
    assert c.put("/api/setup", json={}, headers={"Origin": "http://localhost:5173"}).status_code == 204


def test_setup_with_a_new_camera_ip_forgets_the_remembered_mac(local, conn):
    repo.upsert_camera(conn, "feeder", "aa:bb:cc:dd:ee:ff", "192.168.1.40")

    assert local.put("/api/setup", json={"ip": "192.168.1.41"}).status_code == 204

    camera = repo.get_camera(conn)
    assert (camera.last_ip, camera.mac) == ("192.168.1.41", None)


def test_setup_without_an_ip_keeps_the_remembered_mac(local, conn):
    repo.upsert_camera(conn, "feeder", "aa:bb:cc:dd:ee:ff", "192.168.1.40")

    assert local.put("/api/setup", json={"edit_pin": "1234"}).status_code == 204

    assert repo.get_camera(conn).mac == "aa:bb:cc:dd:ee:ff"

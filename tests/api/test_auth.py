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
    assert "4821" not in stored
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

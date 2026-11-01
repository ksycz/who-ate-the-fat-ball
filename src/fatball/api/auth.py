"""Who may change things: the Mac itself, or a browser that unlocked with the edit PIN.

Viewing needs no login. The edit PIN is 4 digits, kept only as a salted scrypt hash in the `setting`
table. A correct PIN earns a random editor token (stored hashed) delivered as a long-lived cookie.
"""

import hashlib
import hmac
import json
import re
import secrets as pysecrets
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from fastapi import HTTPException, Request

from fatball.library import repo

LOCAL_HOSTS = frozenset({"127.0.0.1", "::1"})
COOKIE = "fatball_editor"
COOKIE_MAX_AGE_S = 400 * 24 * 3600
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=15)
PIN_KEY = "edit_pin_hash"
TOKENS_KEY = "editor_tokens"
PIN_RE = re.compile(r"[0-9]{4}")  # ASCII digits only
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def is_local(request: Request) -> bool:
    return request.client is not None and request.client.host in LOCAL_HOSTS


def valid_pin_format(pin: str) -> bool:
    return PIN_RE.fullmatch(pin) is not None


def _scrypt(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode(), salt=salt, **_SCRYPT)


def _sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Auth:
    """PIN, editor tokens and the per-IP lockout. Writes to the shared connection hold `lock`."""

    def __init__(self, conn, now: Callable[[], datetime], lock: threading.Lock):
        self.conn = conn
        self.now = now
        self.lock = lock
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, datetime] = {}

    def set_edit_pin(self, pin: str) -> None:
        if not valid_pin_format(pin):
            raise ValueError("the edit PIN must be exactly 4 digits")
        salt = pysecrets.token_bytes(16)
        with self.lock:
            repo.set_setting(self.conn, PIN_KEY, f"scrypt${salt.hex()}${_scrypt(pin, salt).hex()}")

    def _pin_matches(self, pin: str) -> bool:
        stored = repo.get_setting(self.conn, PIN_KEY)
        if not stored:
            return False
        _, salt, digest = stored.split("$")
        return hmac.compare_digest(_scrypt(pin, bytes.fromhex(salt)), bytes.fromhex(digest))

    def is_locked(self, ip: str) -> bool:
        until = self._locked_until.get(ip)
        if until is None:
            return False
        if self.now() >= until:
            del self._locked_until[ip]
            self._failures.pop(ip, None)
            return False
        return True

    def try_unlock(self, ip: str, pin: str) -> str | None:
        """A new editor token if the PIN is right, else None. Call only when not locked."""
        if valid_pin_format(pin) and self._pin_matches(pin):
            self._failures.pop(ip, None)
            return self._issue_token()
        self._failures[ip] = self._failures.get(ip, 0) + 1
        if self._failures[ip] >= MAX_FAILURES:
            self._locked_until[ip] = self.now() + LOCKOUT
        return None

    def _issue_token(self) -> str:
        token = pysecrets.token_urlsafe(32)
        with self.lock:
            hashes = json.loads(repo.get_setting(self.conn, TOKENS_KEY) or "[]")
            hashes.append(_sha256(token))
            repo.set_setting(self.conn, TOKENS_KEY, json.dumps(hashes))
        return token

    def token_is_valid(self, token: str | None) -> bool:
        if not token:
            return False
        hashes = json.loads(repo.get_setting(self.conn, TOKENS_KEY) or "[]")
        candidate = _sha256(token)
        return any(hmac.compare_digest(candidate, h) for h in hashes)


def can_edit(request: Request) -> bool:
    if is_local(request):
        return True
    auth: Auth | None = getattr(request.app.state, "auth", None)
    return auth is not None and auth.token_is_valid(request.cookies.get(COOKIE))


def require_editor(request: Request) -> None:
    """FastAPI dependency for every data-changing endpoint."""
    if not can_edit(request):
        raise HTTPException(status_code=403, detail="editing needs the edit PIN")

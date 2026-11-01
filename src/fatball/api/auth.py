"""Who may change things: the Mac itself, or a browser that unlocked with the edit PIN.

Viewing needs no login. The edit PIN is 4 digits, kept only as a salted scrypt hash in the `setting`
table. A correct PIN earns a random editor token (stored hashed) delivered as a long-lived cookie.
"""

import hashlib
import hmac
import json
import re
import secrets as pysecrets
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from urllib.parse import urlsplit

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


LOCAL_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})


class Locked(Exception):
    """Too many wrong PINs from this IP."""


def _hostname_is_local(value: str | None) -> bool:
    try:
        host = urlsplit(f"//{value}").hostname if value is not None else None
    except ValueError:
        return False
    return host in LOCAL_NAMES


def is_local(request: Request) -> bool:
    """Client is the Mac itself, and the request names a local host (blocks DNS rebinding)."""
    if request.client is None or request.client.host not in LOCAL_HOSTS:
        return False
    if not _hostname_is_local(request.headers.get("host")):
        return False
    origin = request.headers.get("origin")
    if origin is not None:
        try:
            origin_host = urlsplit(origin).hostname
        except ValueError:
            return False
        return origin_host in LOCAL_NAMES
    return True


def valid_pin_format(pin: str) -> bool:
    return PIN_RE.fullmatch(pin) is not None


def _scrypt(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode(), salt=salt, **_SCRYPT)


def _sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Auth:
    """PIN, editor tokens and the per-IP lockout.

    Every database operation opens its own short-lived connection from `connect`, so Auth is safe to
    call from FastAPI's thread pool. Only the in-memory lockout state is shared, under its own lock.
    """

    def __init__(self, connect: Callable[[], sqlite3.Connection], now: Callable[[], datetime]):
        self._connect = connect
        self.now = now
        self._lockout_lock = threading.Lock()
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, datetime] = {}

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def set_edit_pin(self, pin: str) -> None:
        if not valid_pin_format(pin):
            raise ValueError("the edit PIN must be exactly 4 digits")
        salt = pysecrets.token_bytes(16)
        with self._db() as conn:
            repo.set_setting(conn, PIN_KEY, f"scrypt${salt.hex()}${_scrypt(pin, salt).hex()}")

    def _pin_matches(self, pin: str) -> bool:
        with self._db() as conn:
            stored = repo.get_setting(conn, PIN_KEY)
        if not stored:
            return False
        try:
            _, salt, digest = stored.split("$")
            expected = bytes.fromhex(digest)
            salt_bytes = bytes.fromhex(salt)
        except ValueError:
            return False  # malformed stored hash: no PIN can match
        return hmac.compare_digest(_scrypt(pin, salt_bytes), expected)

    def try_unlock(self, ip: str, pin: str) -> str | None:
        """A new editor token if the PIN is right, None if wrong; raises Locked if the IP is locked out.

        The attempt is counted as a failure *before* the (slow) hash check, under a dedicated lock, so
        concurrent guesses cannot slip past the limit; a success clears the count.
        """
        with self._lockout_lock:
            until = self._locked_until.get(ip)
            if until is not None and self.now() >= until:
                del self._locked_until[ip]
                self._failures.pop(ip, None)
            if self._failures.get(ip, 0) >= MAX_FAILURES:
                raise Locked
            self._failures[ip] = self._failures.get(ip, 0) + 1
            if self._failures[ip] >= MAX_FAILURES:
                self._locked_until[ip] = self.now() + LOCKOUT
        if valid_pin_format(pin) and self._pin_matches(pin):
            with self._lockout_lock:
                self._failures.pop(ip, None)
                self._locked_until.pop(ip, None)
            return self._issue_token()
        return None

    def _issue_token(self) -> str:
        token = pysecrets.token_urlsafe(32)
        with self._db() as conn:
            # BEGIN IMMEDIATE takes the write lock before reading, so concurrent unlocks never drop a token.
            conn.execute("BEGIN IMMEDIATE")
            try:
                hashes = json.loads(repo.get_setting(conn, TOKENS_KEY) or "[]")
                hashes.append(_sha256(token))
                repo.set_setting(conn, TOKENS_KEY, json.dumps(hashes))  # commits
            except BaseException:
                conn.rollback()
                raise
        return token

    def token_is_valid(self, token: str | None) -> bool:
        if not token:
            return False
        with self._db() as conn:
            hashes = json.loads(repo.get_setting(conn, TOKENS_KEY) or "[]")
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

"""SQLite connection and schema bootstrap. The library is the only code that touches the database."""

import re
import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 6
BUSY_TIMEOUT_S = 5.0


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the library database.

    check_same_thread=False lets a connection be created in one thread and handed to another, but
    sqlite3 connections are still not safe for concurrent use: callers use one connection per thread
    (the API opens one per request). A busy timeout makes concurrent writers wait instead of failing.
    """
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_S, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _migrate(conn, Path(path))
    return conn


def begin_immediate(conn: sqlite3.Connection) -> None:
    """Take the write lock now, inside a `with conn:` block, so what the transaction reads cannot change
    under it (another connection's write either finished before, or waits until this one commits)."""
    conn.execute("BEGIN IMMEDIATE")


def _read(name: str) -> str:
    return resources.files("fatball.library").joinpath(name).read_text(encoding="utf-8")


def _migrations() -> list[tuple[int, str]]:
    """The packaged migrations/NNN_*.sql files as (version, script), in order."""
    found = []
    for entry in resources.files("fatball.library").joinpath("migrations").iterdir():
        match = re.fullmatch(r"(\d{3})_.+\.sql", entry.name)
        if match:
            found.append((int(match.group(1)), entry.read_text(encoding="utf-8")))
    return sorted(found)


def _migrate(conn: sqlite3.Connection, path: Path) -> None:
    """A fresh database is created at v1 from schema.sql, then every later migration is applied in order.

    An existing library is copied to `<name>.v<N>.bak` before it is migrated past version N: migrations
    can't be reversed, and the library is the owner's only record of their clips."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        conn.executescript(f"BEGIN;\n{_read('schema.sql')}\nPRAGMA user_version = 1;\nCOMMIT;")
        version = 1
    elif any(number > version for number, _ in _migrations()):
        _backup(conn, path.with_name(f"{path.name}.v{version}.bak"))
    for number, script in _migrations():
        if number > version:
            conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")


def _backup(conn: sqlite3.Connection, dest: Path) -> None:
    """A consistent copy through SQLite's backup API (safe in WAL mode); an existing backup is kept."""
    if dest.exists():
        return
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
    finally:
        target.close()

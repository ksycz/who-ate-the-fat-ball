"""SQLite connection and schema bootstrap. The library is the only code that touches the database."""

import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 1
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
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        script = resources.files("fatball.library").joinpath("schema.sql").read_text(encoding="utf-8")
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;")
    return conn

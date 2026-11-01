"""Clip/camera repository.

Datetimes are stored as ISO 8601 text in local time with the local UTC offset
(``datetime.astimezone().isoformat()``). Naive inputs are interpreted as local time; aware inputs are
converted to local time. Datetimes read back from the database are *aware* local datetimes, except
``known_clip_keys``, which returns *naive* local datetimes so keys compare equal to the naive local
times a RemoteFile carries. Each write commits immediately.
"""

import sqlite3
from dataclasses import dataclass, fields
from datetime import date, datetime
from typing import Literal

# downloading: row reserved, file still coming (raw_path NULL); downloaded: raw file complete at raw_path.
Status = Literal["downloading", "downloaded", "processing", "ready", "failed"]
_STATUSES = ("downloading", "downloaded", "processing", "ready", "failed")
_PATH_COLUMNS = frozenset(
    {"original_path", "web_path", "poster_path", "preview_path", "raw_path", "duration_s"}
)
_CAMERA_COLUMNS = ("last_seen_at", "last_ip", "last_error", "clock_offset_s")


@dataclass
class Clip:
    id: int
    camera_id: int
    sd_path: str
    begin_at: datetime
    end_at: datetime
    kind: str
    status: str
    raw_path: str | None
    original_path: str | None
    web_path: str | None
    poster_path: str | None
    preview_path: str | None
    duration_s: float | None
    size_bytes: int


@dataclass
class Camera:
    id: int
    name: str
    mac: str | None
    last_ip: str | None
    last_seen_at: datetime | None
    last_error: str | None
    clock_offset_s: float | None


def _iso(dt: datetime) -> str:
    return dt.astimezone().isoformat()


def _clip(row: sqlite3.Row) -> Clip:
    values = {f.name: row[f.name] for f in fields(Clip)}
    values["begin_at"] = datetime.fromisoformat(values["begin_at"])
    values["end_at"] = datetime.fromisoformat(values["end_at"])
    return Clip(**values)


def upsert_camera(conn: sqlite3.Connection, name: str, mac: str | None, ip: str | None) -> int:
    conn.execute(
        "INSERT INTO camera(name, mac, last_ip) VALUES (?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET mac = COALESCE(excluded.mac, mac), "
        "last_ip = COALESCE(excluded.last_ip, last_ip)",
        (name, mac, ip),
    )
    conn.commit()
    return conn.execute("SELECT id FROM camera WHERE name = ?", (name,)).fetchone()[0]


def get_camera(conn: sqlite3.Connection) -> Camera | None:
    """The camera row (there is one camera); None before it has been set up."""
    row = conn.execute("SELECT * FROM camera ORDER BY id LIMIT 1").fetchone()
    if row is None:
        return None
    values = {f.name: row[f.name] for f in fields(Camera)}
    if values["last_seen_at"] is not None:
        values["last_seen_at"] = datetime.fromisoformat(values["last_seen_at"])
    return Camera(**values)


def update_camera_status(
    conn: sqlite3.Connection,
    camera_id: int,
    *,
    last_seen_at=None,
    last_ip=None,
    last_error=None,
    clock_offset_s=None,
    clear_error: bool = False,
) -> None:
    """Set the given fields; arguments left as None are not touched. clear_error sets last_error NULL."""
    given = {
        "last_seen_at": _iso(last_seen_at) if isinstance(last_seen_at, datetime) else last_seen_at,
        "last_ip": last_ip,
        "last_error": last_error,
        "clock_offset_s": clock_offset_s,
    }
    updates = {k: v for k, v in given.items() if v is not None}
    if clear_error:
        updates["last_error"] = None
    if not updates:
        return
    assignments = ", ".join(f"{k} = ?" for k in updates)  # keys come from the fixed tuple above
    conn.execute(f"UPDATE camera SET {assignments} WHERE id = ?", (*updates.values(), camera_id))
    conn.commit()


def add_clip(
    conn: sqlite3.Connection,
    camera_id: int,
    sd_path: str,
    begin_at: datetime,
    end_at: datetime,
    kind: str,
    size_bytes: int,
) -> int | None:
    """Insert a clip with status 'downloading'. Returns None if (sd_path, begin_at) already exists.

    The caller marks it 'downloaded' (with raw_path) once the file is complete, or deletes it.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO clip(camera_id, sd_path, begin_at, end_at, kind, size_bytes, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'downloading')",
        (camera_id, sd_path, _iso(begin_at), _iso(end_at), kind, size_bytes),
    )
    conn.commit()
    return cur.lastrowid if cur.rowcount else None


def delete_clip(conn: sqlite3.Connection, clip_id: int) -> None:
    """Remove a clip row (used to forget a download that did not complete, so it is retried)."""
    conn.execute("DELETE FROM clip WHERE id = ?", (clip_id,))
    conn.commit()


def delete_clips_with_status(conn: sqlite3.Connection, status: Status) -> int:
    """Remove every clip in `status`; returns how many. Used to forget downloads a crash cut short."""
    cur = conn.execute("DELETE FROM clip WHERE status = ?", (status,))
    conn.commit()
    return cur.rowcount


def referenced_raw_paths(conn: sqlite3.Connection) -> set[str]:
    """raw_path of every clip whose download completed (any status but 'downloading')."""
    rows = conn.execute("SELECT raw_path FROM clip WHERE status != 'downloading' AND raw_path IS NOT NULL")
    return {r["raw_path"] for r in rows}


def claim_for_processing(conn: sqlite3.Connection, clip_id: int) -> Clip | None:
    """Atomically move a 'downloaded' clip to 'processing' and return it as now stored.

    None if the clip is not (or no longer) 'downloaded', e.g. another worker claimed it first.
    """
    cur = conn.execute("UPDATE clip SET status = 'processing' WHERE id = ? AND status = 'downloaded'", (clip_id,))
    conn.commit()
    if cur.rowcount != 1:
        return None
    row = conn.execute("SELECT * FROM clip WHERE id = ?", (clip_id,)).fetchone()
    return _clip(row) if row is not None else None


def known_clip_keys(conn: sqlite3.Connection, day: date) -> set[tuple[str, datetime]]:
    """(sd_path, naive local begin) of clips that began on the given local date."""
    rows = conn.execute(
        "SELECT sd_path, begin_at FROM clip WHERE substr(begin_at, 1, 10) = ?", (day.isoformat(),)
    )
    return {(r["sd_path"], datetime.fromisoformat(r["begin_at"]).replace(tzinfo=None)) for r in rows}


def set_clip_status(conn: sqlite3.Connection, clip_id: int, status: Status, **paths) -> None:
    if status not in _STATUSES:
        raise ValueError(f"unknown status: {status!r}")
    unknown = set(paths) - _PATH_COLUMNS
    if unknown:
        raise ValueError(f"unknown clip columns: {sorted(unknown)}")
    assignments = ", ".join(["status = ?", *(f"{k} = ?" for k in paths)])  # keys validated above
    conn.execute(f"UPDATE clip SET {assignments} WHERE id = ?", (status, *paths.values(), clip_id))
    conn.commit()


def clips_with_status(conn: sqlite3.Connection, status: str) -> list[Clip]:
    rows = conn.execute("SELECT * FROM clip WHERE status = ? ORDER BY begin_at, id", (status,))
    return [_clip(r) for r in rows]


def list_clips(
    conn: sqlite3.Connection, limit: int, before: datetime | None, *, status: str | None = None
) -> list[Clip]:
    """Newest first. `before` is an exclusive cursor on begin_at (pass the last clip's begin_at)."""
    where, args = [], []
    if before is not None:
        where.append("begin_at < ?")
        args.append(_iso(before))
    if status is not None:
        where.append("status = ?")
        args.append(status)
    clause = f"WHERE {' AND '.join(where)} " if where else ""  # fragments are fixed strings above
    rows = conn.execute(f"SELECT * FROM clip {clause}ORDER BY begin_at DESC, id DESC LIMIT ?", (*args, limit))
    return [_clip(r) for r in rows]


def queue_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """How many clips are waiting to be (or failed to be) processed."""
    counts = {"downloaded": 0, "processing": 0, "failed": 0}
    for r in conn.execute("SELECT status, COUNT(*) AS n FROM clip GROUP BY status"):
        if r["status"] in counts:
            counts[r["status"]] = r["n"]
    return counts


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO setting(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()

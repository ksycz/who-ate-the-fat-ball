"""What the Today page shows: the day's champion, a new-species banner, clips still being checked or failed.

Days are the local date at the start of the stored local-time ISO text, as in `repo.list_visits`.
"""

import sqlite3
from datetime import date, datetime

from fatball.library import repo
from fatball.library.repo import Clip, iso, row_to_clip

_BIRD_VISIT = "v.category = 'birds'"
_NAMES = "LEFT JOIN species_name n ON n.species_id = s.id AND n.lang = 'en' "


def summary(conn: sqlite3.Connection, day: date) -> dict:
    """How many visits the day had, and how many different bird species were among them."""
    row = conn.execute(
        "SELECT COUNT(*) AS visits, COUNT(DISTINCT CASE WHEN category = 'birds' THEN species_id END) AS species "
        "FROM visit WHERE substr(started_at, 1, 10) = ?",
        (day.isoformat(),),
    ).fetchone()
    return {"visits": row["visits"], "species": row["species"]}


def champion(conn: sqlite3.Connection, day: date) -> dict | None:
    """The bird species with the most visits that day (the earlier first visit wins a tie), with the
    sharpest frame of its most confident visit; None when no visit has a named bird."""
    row = conn.execute(
        "SELECT s.id AS species_id, s.scientific_name, n.name, COUNT(*) AS count, MIN(v.started_at) AS first_at "
        "FROM visit v JOIN species s ON s.id = v.species_id "
        f"{_NAMES}"
        f"WHERE {_BIRD_VISIT} AND substr(v.started_at, 1, 10) = ? "
        "GROUP BY s.id ORDER BY count DESC, first_at, s.id LIMIT 1",
        (day.isoformat(),),
    ).fetchone()
    if row is None:
        return None
    frame = conn.execute(
        "SELECT best_frame_path FROM visit WHERE species_id = ? AND category = 'birds' "
        "AND substr(started_at, 1, 10) = ? AND best_frame_path IS NOT NULL "
        "ORDER BY confidence DESC, started_at, id LIMIT 1",
        (row["species_id"], day.isoformat()),
    ).fetchone()
    return {
        "scientific": row["scientific_name"],
        "name": row["name"],
        "count": row["count"],
        "first_at": row["first_at"],
        "best_frame_path": frame["best_frame_path"] if frame else None,
    }


def new_species(conn: sqlite3.Connection) -> dict | None:
    """The newest bird visit that is its species' first sighting (first_seen_at falls inside the visit) and
    that the owner has not watched yet."""
    row = conn.execute(
        "SELECT v.id, s.scientific_name, n.name, v.started_at FROM visit v JOIN species s ON s.id = v.species_id "
        f"{_NAMES}"
        f"WHERE {_BIRD_VISIT} AND v.watched_at IS NULL AND s.first_seen_at IS NOT NULL "
        "AND julianday(s.first_seen_at) BETWEEN julianday(v.started_at) AND julianday(v.ended_at) "
        "ORDER BY v.started_at DESC, v.id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return {
        "visit_id": row["id"], "scientific": row["scientific_name"], "name": row["name"],
        "started_at": row["started_at"],
    }


def checking(conn: sqlite3.Connection, day: date) -> list[Clip]:
    """The day's videos still on their way to a visit: being downloaded or converted, or converted and
    waiting to be recognised (asked for, or older ones while the backfill is on) and not failed at it."""
    waiting = "recognition_wanted = 1 AND " if not repo.recognize_old_clips(conn) else ""
    rows = conn.execute(
        "SELECT * FROM clip WHERE kind = 'h264' AND substr(begin_at, 1, 10) = ? AND ("
        "status IN ('downloaded', 'processing') "
        f"OR (status = 'ready' AND web_path IS NOT NULL AND recognized_at IS NULL AND recognition_error IS NULL "
        f"AND {waiting}id NOT IN (SELECT clip_id FROM visit_clip))) "
        "ORDER BY begin_at, id",
        (day.isoformat(),),
    )
    return [row_to_clip(r) for r in rows]


def failed(conn: sqlite3.Connection, day: date) -> list[Clip]:
    """The day's videos that could not be converted, or could not be recognised."""
    rows = conn.execute(
        "SELECT * FROM clip WHERE kind = 'h264' AND substr(begin_at, 1, 10) = ? "
        "AND (status = 'failed' OR recognition_error IS NOT NULL) ORDER BY begin_at, id",
        (day.isoformat(),),
    )
    return [row_to_clip(r) for r in rows]


def last_visitor(conn: sqlite3.Connection, before: date) -> dict | None:
    """The newest bird visit before that day; `name` is None when the bird was not identified."""
    row = conn.execute(
        "SELECT n.name, v.started_at FROM visit v LEFT JOIN species s ON s.id = v.species_id "
        f"{_NAMES}"
        f"WHERE {_BIRD_VISIT} AND substr(v.started_at, 1, 10) < ? ORDER BY v.started_at DESC, v.id DESC LIMIT 1",
        (before.isoformat(),),
    ).fetchone()
    return {"name": row["name"], "started_at": row["started_at"]} if row else None


def mark_watched(conn: sqlite3.Connection, visit_id: int, now: datetime) -> bool:
    """Record that the owner watched the visit (the first time counts); False for an unknown visit."""
    cur = conn.execute(
        "UPDATE visit SET watched_at = COALESCE(watched_at, ?) WHERE id = ?", (iso(now), visit_id)
    )
    conn.commit()
    return cur.rowcount == 1

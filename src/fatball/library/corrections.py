"""The owner's corrections to a visit, and undoing them.

A correction changes the visit's category/species and labels the visit's confident animal detections
(label_source 'correction'), which teaches the matcher, and can make the species' first sighting earlier.
Undo restores the visit fields, each labelled detection's previous label, label time and label source, and
the first sighting exactly, then recomputes the visit. Each runs in one write transaction, taken before
the first read.
"""

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from fatball.library import visits
from fatball.library.db import begin_immediate
from fatball.library.repo import category_for, iso
from fatball.recognition.matcher import DET_MIN

UNDO_TTL = timedelta(hours=24)
CATEGORIES = ("birds", "other_animals", "other")
NOTHING = "nothing"  # the label for a false box
UNSET = object()  # a Change field left out: keep the current value


class VisitNotFound(LookupError):
    pass


class InvalidChange(ValueError):
    pass


class UnknownToken(LookupError):
    """The undo token does not exist, or is older than 24 hours."""


@dataclass(frozen=True)
class Change:
    """species: a scientific name, None for 'no species', or UNSET to keep it."""

    species: object = UNSET
    category: str | None = None
    is_favourite: bool | None = None
    teach: bool = True  # False: a plain move, no detections labelled and the first sighting left alone


def apply(conn: sqlite3.Connection, visit_id: int, change: Change, now: datetime | None = None) -> str:
    """Apply the change and return an undo token. Raises VisitNotFound or InvalidChange."""
    now = now or datetime.now().astimezone()
    _check_category(change)
    with conn:
        begin_immediate(conn)
        before = _apply_in_tx(conn, visit_id, change, now)
        return _store_undo(conn, visit_id, before, now)


def apply_many(
    conn: sqlite3.Connection, visit_ids: list[int], change: Change, now: datetime | None = None
) -> tuple[str, int]:
    """Move and/or favourite several visits under one undo token; returns (token, how many changed).
    Only category and is_favourite are allowed. Visits that already match are skipped. An unknown id raises
    VisitNotFound and nothing changes."""
    now = now or datetime.now().astimezone()
    if change.species is not UNSET:
        raise InvalidChange("a bulk change cannot set the species")
    _check_category(change)
    ids = list(dict.fromkeys(visit_ids))
    if not ids:
        raise InvalidChange("no visits given")
    with conn:
        begin_immediate(conn)
        items = []
        for visit_id in ids:
            before = _apply_in_tx(conn, visit_id, change, now, skip_noop=True)
            if before is not None:
                items.append({"visit_id": visit_id, "before": before})
        token = _store_undo(conn, ids[0], {"bulk": items}, now)
    return token, len(items)


def _check_category(change: Change) -> None:
    if change.category is not None and change.category not in CATEGORIES:
        raise InvalidChange(f"unknown category {change.category!r}")


def _store_undo(conn: sqlite3.Connection, visit_id: int, before: dict, now: datetime) -> str:
    _purge_expired(conn, now)
    token = secrets.token_urlsafe(16)
    conn.execute(
        "INSERT INTO undo(token, visit_id, before_json, created_at) VALUES (?, ?, ?, ?)",
        (token, visit_id, json.dumps(before), iso(now)),
    )
    return token


def _apply_in_tx(
    conn: sqlite3.Connection, visit_id: int, change: Change, now: datetime, skip_noop: bool = False
) -> dict | None:
    """Apply the change inside the caller's write transaction and return the 'before' snapshot undo needs,
    or None when skip_noop is set and the visit already matches the change."""
    visit = conn.execute("SELECT * FROM visit WHERE id = ?", (visit_id,)).fetchone()
    if visit is None:
        raise VisitNotFound(visit_id)
    if skip_noop and (change.category is None or change.category == visit["category"]) and (
        change.is_favourite is None or int(change.is_favourite) == visit["is_favourite"]
    ):
        return None
    species_given = change.species is not UNSET
    if species_given and change.species is not None:
        species_id = _species_id(conn, change.species)
        if species_id is None:
            raise InvalidChange(f"unknown species {change.species!r}")
        scientific = change.species
        if change.category is not None and change.category != category_for(conn, scientific):
            raise InvalidChange(f"{scientific!r} does not belong in {change.category!r}")
    elif species_given:
        species_id, scientific = None, None
    else:
        species_id, scientific = visit["species_id"], _scientific(conn, visit["species_id"])
    corrected = species_given or change.category is not None
    category = change.category or (category_for(conn, scientific) if species_given else visit["category"])
    if not species_given and category != category_for(conn, scientific):
        species_id, scientific = None, None  # a category that contradicts the species drops the species
    before = {
        "category": visit["category"], "species_id": visit["species_id"], "subject": visit["subject"],
        "moved_by_user": visit["moved_by_user"], "is_favourite": visit["is_favourite"],
        "labelled": [], "correction_id": None, "first_seen": None,
    }
    updates = {}
    if change.is_favourite is not None:
        updates["is_favourite"] = int(change.is_favourite)
    if corrected:
        # Only a taught choice says "nothing there": a plain move to Other could be a dog, a person or an
        # empty clip, so it stays unknown and never becomes a deletable empty clip (R24).
        empty = change.teach and category == "other"
        subject = "species" if scientific else (NOTHING if empty else "unknown")
        updates |= {"category": category, "species_id": species_id, "subject": subject, "moved_by_user": 1}
        if change.teach:  # a plain move must not teach the matcher or move the first sighting
            label = scientific or (NOTHING if category == "other" else None)
            if label is not None:
                before["labelled"] = _label(conn, visit_id, label, now)
            if scientific:
                before["first_seen"] = _see_first(conn, scientific, visit["started_at"])
        cur = conn.execute(
            "INSERT INTO correction(visit_id, from_species_id, to_species_id, from_category, to_category, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (visit_id, visit["species_id"], species_id, visit["category"], category, iso(now)),
        )
        before["correction_id"] = cur.lastrowid
    if updates:
        assignments = ", ".join(f"{k} = ?" for k in updates)  # keys are the fixed names above
        conn.execute(f"UPDATE visit SET {assignments} WHERE id = ?", (*updates.values(), visit_id))
    return before


def undo(conn: sqlite3.Connection, token: str, now: datetime | None = None) -> None:
    """Restore what `apply` or `apply_many` changed, then recompute the visits from their clips. Raises
    UnknownToken when the token is unknown, expired or its visit is gone. A bulk token restores the visits
    that still exist and skips the deleted ones; it is unknown only when none is left."""
    now = now or datetime.now().astimezone()
    expired = False
    with conn:
        begin_immediate(conn)
        row = conn.execute("SELECT * FROM undo WHERE token = ?", (token,)).fetchone()
        if row is None:
            raise UnknownToken(token)
        if now - datetime.fromisoformat(row["created_at"]) > UNDO_TTL:
            conn.execute("DELETE FROM undo WHERE token = ?", (token,))
            expired = True
        else:
            payload = json.loads(row["before_json"])
            if "bulk" in payload:
                items = [(i["visit_id"], i["before"]) for i in reversed(payload["bulk"])]
            else:
                items = [(row["visit_id"], payload)]
            restored = [_restore(conn, visit_id, before) for visit_id, before in items]
            if restored and not any(restored):
                raise UnknownToken(token)
            conn.execute("DELETE FROM undo WHERE token = ?", (token,))
    if expired:
        raise UnknownToken(token)


def _restore(conn: sqlite3.Connection, visit_id: int, before: dict) -> bool:
    """Put one visit back; False (and nothing changed) when the visit no longer exists."""
    if conn.execute("SELECT 1 FROM visit WHERE id = ?", (visit_id,)).fetchone() is None:
        return False
    conn.execute(
        "UPDATE visit SET category = ?, species_id = ?, subject = ?, moved_by_user = ?, is_favourite = ? "
        "WHERE id = ?",
        (before["category"], before["species_id"], before["subject"], before["moved_by_user"],
         before["is_favourite"], visit_id),
    )
    conn.executemany(
        "UPDATE detection SET label = ?, labelled_at = ?, label_source = ? WHERE id = ?",
        [(d["label"], d["labelled_at"], d["label_source"], d["id"]) for d in before["labelled"]],
    )
    seen = before.get("first_seen")
    if seen is not None:  # put back the value the correction replaced, unless a clip has lowered it since
        conn.execute(
            "UPDATE species SET first_seen_at = ? WHERE scientific_name = ? AND first_seen_at IS ?",
            (seen["previous"], seen["species"], seen["set"]),
        )
    if before["correction_id"] is not None:
        conn.execute("DELETE FROM correction WHERE id = ?", (before["correction_id"],))
    visits.recompute(conn, visit_id)
    return True


def _see_first(conn: sqlite3.Connection, scientific: str, started_at: str) -> dict:
    """The owner named this species for the visit: it was seen at the visit's start. Returns what undo needs."""
    previous = visits.note_first_seen(conn, scientific, datetime.fromisoformat(started_at))
    now_set = conn.execute("SELECT first_seen_at FROM species WHERE scientific_name = ?", (scientific,)).fetchone()[0]
    return {"species": scientific, "previous": previous, "set": now_set}


def _label(conn: sqlite3.Connection, visit_id: int, label: str, now: datetime) -> list[dict]:
    """Label the visit's confident animal detections that have a feature, overwriting any earlier label
    (an import or an older correction). Returns each one's previous values, for undo."""
    rows = conn.execute(
        "SELECT d.id, d.label, d.labelled_at, d.label_source FROM detection d "
        "JOIN visit_clip vc ON vc.clip_id = d.clip_id "
        "WHERE vc.visit_id = ? AND d.cls = 'animal' AND d.conf >= ? AND d.feature IS NOT NULL ORDER BY d.id",
        (visit_id, DET_MIN),
    ).fetchall()
    conn.executemany(
        "UPDATE detection SET label = ?, labelled_at = ?, label_source = 'correction' WHERE id = ?",
        [(label, iso(now), r["id"]) for r in rows],
    )
    return [dict(r) for r in rows]


def _purge_expired(conn: sqlite3.Connection, now: datetime) -> None:
    for row in conn.execute("SELECT token, created_at FROM undo").fetchall():
        if now - datetime.fromisoformat(row["created_at"]) > UNDO_TTL:
            conn.execute("DELETE FROM undo WHERE token = ?", (row["token"],))


def _species_id(conn: sqlite3.Connection, scientific: str) -> int | None:
    row = conn.execute("SELECT id FROM species WHERE scientific_name = ?", (scientific,)).fetchone()
    return row["id"] if row else None


def _scientific(conn: sqlite3.Connection, species_id: int | None) -> str | None:
    if species_id is None:
        return None
    return conn.execute("SELECT scientific_name FROM species WHERE id = ?", (species_id,)).fetchone()[0]

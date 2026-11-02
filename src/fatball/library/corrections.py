"""The owner's corrections to a visit, and undoing them.

A correction changes the visit's category/species and labels the visit's confident animal detections
(label_source 'correction'), which teaches the matcher. Undo restores the visit fields and each labelled
detection's previous label, label time and label source exactly. Both run in one transaction.
"""

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from fatball.library.repo import _iso, category_for
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


def apply(conn: sqlite3.Connection, visit_id: int, change: Change, now: datetime | None = None) -> str:
    """Apply the change and return an undo token. Raises VisitNotFound or InvalidChange."""
    now = now or datetime.now().astimezone()
    visit = conn.execute("SELECT * FROM visit WHERE id = ?", (visit_id,)).fetchone()
    if visit is None:
        raise VisitNotFound(visit_id)
    if change.category is not None and change.category not in CATEGORIES:
        raise InvalidChange(f"unknown category {change.category!r}")
    species_given = change.species is not UNSET
    if species_given and change.species is not None:
        species_id = _species_id(conn, change.species)
        if species_id is None:
            raise InvalidChange(f"unknown species {change.species!r}")
        scientific = change.species
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
        "labelled": [], "correction_id": None,
    }
    with conn:
        updates = {}
        if change.is_favourite is not None:
            updates["is_favourite"] = int(change.is_favourite)
        if corrected:
            subject = "species" if scientific else (NOTHING if category == "other" else "unknown")
            updates |= {"category": category, "species_id": species_id, "subject": subject, "moved_by_user": 1}
            label = scientific or (NOTHING if category == "other" else None)
            if label is not None:
                before["labelled"] = _label(conn, visit_id, label, now)
            cur = conn.execute(
                "INSERT INTO correction(visit_id, from_species_id, to_species_id, from_category, to_category, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (visit_id, visit["species_id"], species_id, visit["category"], category, _iso(now)),
            )
            before["correction_id"] = cur.lastrowid
        if updates:
            assignments = ", ".join(f"{k} = ?" for k in updates)  # keys are the fixed names above
            conn.execute(f"UPDATE visit SET {assignments} WHERE id = ?", (*updates.values(), visit_id))
        _purge_expired(conn, now)
        token = secrets.token_urlsafe(16)
        conn.execute(
            "INSERT INTO undo(token, visit_id, before_json, created_at) VALUES (?, ?, ?, ?)",
            (token, visit_id, json.dumps(before), _iso(now)),
        )
    return token


def undo(conn: sqlite3.Connection, token: str, now: datetime | None = None) -> None:
    """Restore what `apply` changed. Raises UnknownToken when the token is unknown, expired or its visit is gone."""
    now = now or datetime.now().astimezone()
    row = conn.execute("SELECT * FROM undo WHERE token = ?", (token,)).fetchone()
    if row is None:
        raise UnknownToken(token)
    if now - datetime.fromisoformat(row["created_at"]) > UNDO_TTL:
        with conn:
            conn.execute("DELETE FROM undo WHERE token = ?", (token,))
        raise UnknownToken(token)
    before = json.loads(row["before_json"])
    with conn:
        if conn.execute("SELECT 1 FROM visit WHERE id = ?", (row["visit_id"],)).fetchone() is None:
            raise UnknownToken(token)
        conn.execute(
            "UPDATE visit SET category = ?, species_id = ?, subject = ?, moved_by_user = ?, is_favourite = ? "
            "WHERE id = ?",
            (before["category"], before["species_id"], before["subject"], before["moved_by_user"],
             before["is_favourite"], row["visit_id"]),
        )
        conn.executemany(
            "UPDATE detection SET label = ?, labelled_at = ?, label_source = ? WHERE id = ?",
            [(d["label"], d["labelled_at"], d["label_source"], d["id"]) for d in before["labelled"]],
        )
        if before["correction_id"] is not None:
            conn.execute("DELETE FROM correction WHERE id = ?", (before["correction_id"],))
        conn.execute("DELETE FROM undo WHERE token = ?", (token,))


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
        [(label, _iso(now), r["id"]) for r in rows],
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

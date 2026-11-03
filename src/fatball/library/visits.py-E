"""Group recognised clips into visits: one bird's stay at the feeder, possibly several clips.

A visit is recomputed from the verdicts stored on its clips (`clip.verdict_json`), so it always agrees
with them; the verdict passed to `assign_visit` stands in for the current clip's. Everything happens in
one write transaction, taken before the first read. Only data rows are ever deleted, never media files.
"""

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from fatball.library.db import begin_immediate
from fatball.library.repo import Clip, _iso
from fatball.recognition.matcher import Verdict

GAP = timedelta(seconds=60)  # a clip joins a visit when its gap to one of the visit's clips is under this
_MARGIN = timedelta(days=1)  # visit rows fetched around a clip before the exact gap test (covers DST shifts)
_NO_VISIT_SUBJECTS = ("person", "nothing")


@dataclass(frozen=True)
class _Member:
    clip_id: int
    begin_text: str
    end_text: str
    begin: datetime
    end: datetime
    best_frame_path: str | None
    category: str | None
    species: str | None
    subject: str | None
    confidence: float
    guesses: dict[str, float]
    has_verdict: bool

    @property
    def is_sure(self) -> bool:
        return self.subject == "species"


def assign_visit(conn: sqlite3.Connection, clip: Clip, verdict: Verdict) -> int:
    """Put the clip into the right visit (creating, joining or merging) and return that visit's id.

    A clip the owner's visit already holds (moved_by_user) stays there: re-recognising it only recomputes
    that visit's derived fields, so the pipeline never empties or splits an owner-moved visit."""
    with conn:
        begin_immediate(conn)
        current = conn.execute(
            "SELECT v.id, v.moved_by_user FROM visit_clip vc JOIN visit v ON v.id = vc.visit_id WHERE vc.clip_id = ?",
            (clip.id,),
        ).fetchone()
        if current is not None and current["moved_by_user"]:
            visit_id = current["id"]
        else:
            if current is not None:
                _remove_from_visit(conn, clip.id, current["id"])
            visit_id = _join_or_create(conn, clip, verdict)
            conn.execute("INSERT INTO visit_clip(visit_id, clip_id) VALUES (?, ?)", (visit_id, clip.id))
        _recompute(conn, visit_id, clip, verdict)
        if verdict.subject == "species" and verdict.species:
            note_first_seen(conn, verdict.species, clip.begin_at)
    return visit_id


def recompute(conn: sqlite3.Connection, visit_id: int) -> None:
    """Rebuild a visit's derived fields from its clips' stored verdicts (the caller holds the transaction)."""
    _recompute(conn, visit_id, None, None)


def note_first_seen(conn: sqlite3.Connection, scientific: str, when: datetime) -> str | None:
    """Lower the species' first_seen_at to `when` when that is earlier, or when it has none yet: it is the
    earliest sighting, whatever order clips are recognised in. Returns the previous stored value."""
    row = conn.execute("SELECT first_seen_at FROM species WHERE scientific_name = ?", (scientific,)).fetchone()
    if row is None:
        return None
    previous = row["first_seen_at"]
    if previous is None or when.astimezone() < datetime.fromisoformat(previous):
        conn.execute("UPDATE species SET first_seen_at = ? WHERE scientific_name = ?", (_iso(when), scientific))
    return previous


def _join_or_create(conn: sqlite3.Connection, clip: Clip, verdict: Verdict) -> int:
    compatible = _compatible_visits(conn, clip, verdict)
    if not compatible:
        return _create_visit(conn, verdict)
    visit_id = compatible[0]["id"]
    if not compatible[0]["moved_by_user"]:
        species = compatible[0]["species_id"]  # the target's effective species as merges happen
        for other in compatible[1:]:
            if _can_merge(species, other):
                _merge_into(conn, visit_id, other["id"])
                species = species if species is not None else other["species_id"]
    return visit_id


def _remove_from_visit(conn: sqlite3.Connection, clip_id: int, visit_id: int) -> None:
    """A re-recognised clip leaves its old (not owner-moved) visit first; an emptied visit is deleted,
    others recomputed."""
    conn.execute("DELETE FROM visit_clip WHERE clip_id = ?", (clip_id,))
    if conn.execute("SELECT 1 FROM visit_clip WHERE visit_id = ?", (visit_id,)).fetchone() is None:
        _delete_visit(conn, visit_id)
    else:
        _recompute(conn, visit_id, None, None)


def _delete_visit(conn: sqlite3.Connection, visit_id: int) -> None:
    # An owner-edited visit has correction and undo rows: they go first (foreign keys), and a stale undo
    # token must not survive to hit a new visit that reuses this id.
    conn.execute("DELETE FROM undo WHERE visit_id = ?", (visit_id,))
    conn.execute("DELETE FROM correction WHERE visit_id = ?", (visit_id,))
    conn.execute("DELETE FROM guess WHERE visit_id = ?", (visit_id,))
    conn.execute("DELETE FROM visit WHERE id = ?", (visit_id,))


def _species_id(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute("SELECT id FROM species WHERE scientific_name = ?", (name,)).fetchone()
    return row["id"] if row else None


def _compatible_visits(conn: sqlite3.Connection, clip: Clip, verdict: Verdict) -> list[sqlite3.Row]:
    """Visits this clip may join, earliest first."""
    candidates = conn.execute(
        "SELECT * FROM visit WHERE started_at <= ? AND ended_at >= ? ORDER BY started_at, id",
        (_iso(clip.end_at + _MARGIN), _iso(clip.begin_at - _MARGIN)),
    ).fetchall()
    sure_id = _species_id(conn, verdict.species) if verdict.subject == "species" and verdict.species else None
    if verdict.subject == "species" and sure_id is None:
        raise ValueError(f"species {verdict.species!r} is not in the catalog")
    found = []
    for visit in candidates:
        if _species_compatible(visit, verdict, sure_id) and _near(conn, visit["id"], clip):
            found.append(visit)
    return found


def _species_compatible(visit: sqlite3.Row, verdict: Verdict, sure_id: int | None) -> bool:
    if visit["category"] != verdict.category:
        return False
    if visit["moved_by_user"]:
        return visit["species_id"] == sure_id  # the owner's visit: exact category and species only
    if verdict.subject in _NO_VISIT_SUBJECTS or visit["subject"] in _NO_VISIT_SUBJECTS:
        return visit["species_id"] is None and visit["subject"] == verdict.subject
    if verdict.subject == "unknown":
        return True
    return visit["species_id"] == sure_id or (visit["species_id"] is None and visit["subject"] == "unknown")


def _near(conn: sqlite3.Connection, visit_id: int, clip: Clip) -> bool:
    rows = conn.execute(
        "SELECT c.begin_at, c.end_at FROM visit_clip vc JOIN clip c ON c.id = vc.clip_id WHERE vc.visit_id = ?",
        (visit_id,),
    )
    for row in rows:
        begin, end = datetime.fromisoformat(row["begin_at"]), datetime.fromisoformat(row["end_at"])
        # naive Clip times are read as local time, like repo does when it stores them
        gap = max(clip.begin_at.astimezone() - end, begin - clip.end_at.astimezone())
        if gap < GAP:
            return True
    return False


def _can_merge(target_species: int | None, other: sqlite3.Row) -> bool:
    """Never merge an owner's visit, nor two visits of different sure species (an unknown clip can bridge them)."""
    if other["moved_by_user"]:
        return False
    return target_species is None or other["species_id"] is None or target_species == other["species_id"]


def _merge_into(conn: sqlite3.Connection, target_id: int, other_id: int) -> None:
    """Move the other visit's clips into the target; a favourite on either side is kept."""
    conn.execute("UPDATE visit_clip SET visit_id = ? WHERE visit_id = ?", (target_id, other_id))
    conn.execute(
        "UPDATE visit SET is_favourite = MAX(is_favourite, (SELECT is_favourite FROM visit WHERE id = ?)) "
        "WHERE id = ?",
        (other_id, target_id),
    )
    _delete_visit(conn, other_id)


def _create_visit(conn: sqlite3.Connection, verdict: Verdict) -> int:
    # started_at/ended_at/subject are placeholders: _recompute fills them from the clips straight after.
    cur = conn.execute(
        "INSERT INTO visit(started_at, ended_at, category, subject) VALUES ('', '', ?, ?)",
        (verdict.category, verdict.subject),
    )
    return cur.lastrowid


def _members(conn: sqlite3.Connection, visit_id: int, clip: Clip | None, verdict: Verdict | None) -> list[_Member]:
    rows = conn.execute(
        "SELECT c.id, c.begin_at, c.end_at, c.best_frame_path, c.verdict_json FROM visit_clip vc "
        "JOIN clip c ON c.id = vc.clip_id WHERE vc.visit_id = ? ORDER BY c.begin_at, c.id",
        (visit_id,),
    ).fetchall()
    members = []
    for row in rows:
        if clip is not None and verdict is not None and row["id"] == clip.id:
            data = {"category": verdict.category, "species": verdict.species, "subject": verdict.subject,
                    "confidence": verdict.confidence, "guesses": verdict.guesses}
        elif row["verdict_json"]:
            data = json.loads(row["verdict_json"])
        else:
            data = None
        members.append(_Member(
            row["id"], row["begin_at"], row["end_at"],
            datetime.fromisoformat(row["begin_at"]), datetime.fromisoformat(row["end_at"]),
            row["best_frame_path"],
            data and data["category"], data and data["species"], data and data["subject"],
            float(data["confidence"]) if data else 0.0,
            {name: float(share) for name, share in data["guesses"]} if data else {},
            data is not None,
        ))
    return members


def _recompute(conn: sqlite3.Connection, visit_id: int, clip: Clip | None, verdict: Verdict | None) -> None:
    """Rebuild the visit's derived fields from its clips' verdicts (an owner's visit keeps its category/species/subject)."""
    members = _members(conn, visit_id, clip, verdict)
    judged = [m for m in members if m.has_verdict]
    sure = [m for m in judged if m.is_sure]
    best = max(sure or judged, key=lambda m: m.confidence, default=members[0])
    started = min(members, key=lambda m: m.begin)
    ended = max(members, key=lambda m: m.end)
    updates = {
        "started_at": started.begin_text,
        "ended_at": ended.end_text,
        "confidence": max((m.confidence for m in judged), default=None),
        "best_clip_id": best.clip_id,
        "best_frame_path": best.best_frame_path,
    }
    if not conn.execute("SELECT moved_by_user FROM visit WHERE id = ?", (visit_id,)).fetchone()[0]:
        if sure:
            species_id = _species_id(conn, best.species)
            subject = "species"
        else:
            species_id = None
            subject = Counter(m.subject for m in judged).most_common(1)[0][0] if judged else None
        updates |= {
            "category": best.category if sure else Counter(m.category for m in judged).most_common(1)[0][0],
            "species_id": species_id,
            "subject": subject,
        }
    assignments = ", ".join(f"{k} = ?" for k in updates)  # keys are the fixed names above
    conn.execute(f"UPDATE visit SET {assignments} WHERE id = ?", (*updates.values(), visit_id))
    _write_guesses(conn, visit_id, judged)


def _write_guesses(conn: sqlite3.Connection, visit_id: int, judged: list[_Member]) -> None:
    """Replace the visit's guess rows with its 3 best species, shares averaged over its judged clips."""
    totals: Counter[str] = Counter()
    for member in judged:
        totals.update(member.guesses)
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    conn.execute("DELETE FROM guess WHERE visit_id = ?", (visit_id,))
    rank = 0
    for name, total in ranked:
        species_id = _species_id(conn, name)
        if species_id is None:
            continue
        rank += 1
        conn.execute(
            "INSERT INTO guess(visit_id, species_id, confidence, rank) VALUES (?, ?, ?, ?)",
            (visit_id, species_id, total / len(judged), rank),
        )
        if rank == 3:
            break

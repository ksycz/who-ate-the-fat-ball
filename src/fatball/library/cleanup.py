"""Deleting empty clips: the files go, the clip rows stay as tombstones so the camera's copy is never fetched again."""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from fatball.library.db import begin_immediate
from fatball.library.repo import iso

log = logging.getLogger("fatball.cleanup")

_CLIP_FILES = ("raw_path", "original_path", "web_path", "poster_path", "preview_path", "best_frame_path")


class VisitNotFound(LookupError):
    pass


class NotEmpty(ValueError):
    """A visit that is not an empty clip (category 'other', subject 'nothing')."""


def delete_empty_visits(conn: sqlite3.Connection, media_dir: Path, visit_ids: list[int], now: datetime) -> int:
    """Delete empty-clip visits and their media; returns how many. Raises VisitNotFound / NotEmpty (nothing
    changes). The clip rows stay with `deleted_at` set and their paths cleared; detections are kept.

    Files are removed after the database commit, so a failure never leaves a visit pointing at missing files.
    A file that cannot be removed then is logged and left; the delete has happened."""
    ids = list(dict.fromkeys(visit_ids))
    files: list[Path] = []
    with conn:
        begin_immediate(conn)
        for visit_id in ids:
            visit = conn.execute(
                "SELECT category, subject FROM visit WHERE id = ?", (visit_id,)
            ).fetchone()
            if visit is None:
                raise VisitNotFound(visit_id)
            if visit["category"] != "other" or visit["subject"] != "nothing":
                raise NotEmpty(visit_id)
        for visit_id in ids:
            clips = conn.execute(
                f"SELECT c.id, {', '.join('c.' + f for f in _CLIP_FILES)} FROM clip c "
                "JOIN visit_clip vc ON vc.clip_id = c.id WHERE vc.visit_id = ?",
                (visit_id,),
            ).fetchall()
            files += [media_dir / c[f] for c in clips for f in _CLIP_FILES if c[f]]
            visit_frame = conn.execute("SELECT best_frame_path FROM visit WHERE id = ?", (visit_id,)).fetchone()[0]
            if visit_frame:
                files.append(media_dir / visit_frame)
            nulls = ", ".join(f"{f} = NULL" for f in _CLIP_FILES)  # fixed names above
            conn.executemany(
                f"UPDATE clip SET {nulls}, deleted_at = ? WHERE id = ?", [(iso(now), c["id"]) for c in clips]
            )
            for table in ("visit_clip", "guess", "undo", "correction"):
                conn.execute(f"DELETE FROM {table} WHERE visit_id = ?", (visit_id,))
            conn.execute("DELETE FROM visit WHERE id = ?", (visit_id,))
    media_root = media_dir.resolve()
    for path in files:
        try:
            if not path.resolve().is_relative_to(media_root):
                log.warning("not removing %s: outside the media folder", path)
                continue
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("could not remove %s: %s", path, exc)
    return len(ids)

"""Clip/camera repository.

Datetimes are stored as ISO 8601 text in local time with the local UTC offset
(``datetime.astimezone().isoformat()``). Naive inputs are interpreted as local time; aware inputs are
converted to local time. Datetimes read back from the database are *aware* local datetimes, except
``known_clip_keys``, which returns *naive* local datetimes so keys compare equal to the naive local
times a RemoteFile carries. Each write commits immediately.
"""

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from typing import Literal

from fatball.recognition.catalog import CATALOG, DOG
from fatball.recognition.features import from_blob
from fatball.recognition.matcher import DET_MIN, Example

# downloading: row reserved, file still coming (raw_path NULL); downloaded: raw file complete at raw_path.
Status = Literal["downloading", "downloaded", "processing", "ready", "failed"]
Category = Literal["birds", "other_animals", "other"]
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


def ensure_catalog(conn: sqlite3.Connection) -> None:
    """Make sure every catalog species has a row and an English name. Safe to call any number of times."""
    for english, scientific, group in CATALOG:
        conn.execute(
            'INSERT INTO species(scientific_name, "group") VALUES (?, ?) '
            'ON CONFLICT(scientific_name) DO UPDATE SET "group" = excluded."group"',
            (scientific, group),
        )
        species_id = conn.execute("SELECT id FROM species WHERE scientific_name = ?", (scientific,)).fetchone()[0]
        conn.execute(
            "INSERT INTO species_name(species_id, lang, name) VALUES (?, 'en', ?) "
            "ON CONFLICT(species_id, lang) DO UPDATE SET name = excluded.name",
            (species_id, english),
        )
    conn.commit()


def category_for(conn: sqlite3.Connection, scientific_name: str | None) -> Category:
    """birds for a bird, other for a dog, other_animals for any other mammal, other for everything else."""
    if scientific_name is None or scientific_name == DOG:
        return "other"
    row = conn.execute('SELECT "group" FROM species WHERE scientific_name = ?', (scientific_name,)).fetchone()
    if row is None:
        return "other"
    return "birds" if row["group"] == "bird" else "other_animals"


@dataclass(frozen=True)
class NewDetection:
    frame_index: int
    cls: str
    conf: float
    box: tuple[float, float, float, float]
    feature: bytes | None = None


def replace_detections(conn: sqlite3.Connection, clip_id: int, rows: Iterable[NewDetection]) -> None:
    """Swap the clip's unlabelled detections for `rows`, all or nothing. Labelled ones are never deleted, and a
    row the clip already holds labelled (same frame, class, confidence and box: a retry) is not added again."""
    with conn:
        labelled = {
            _detection_key(r["frame_index"], r["cls"], r["conf"], (r["x1"], r["y1"], r["x2"], r["y2"]))
            for r in conn.execute(
                "SELECT frame_index, cls, conf, x1, y1, x2, y2 FROM detection WHERE clip_id = ? AND label IS NOT NULL",
                (clip_id,),
            )
        }
        conn.execute("DELETE FROM detection WHERE clip_id = ? AND label IS NULL", (clip_id,))
        conn.executemany(
            "INSERT INTO detection(clip_id, frame_index, cls, conf, x1, y1, x2, y2, feature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(clip_id, r.frame_index, r.cls, r.conf, *r.box, r.feature) for r in rows
             if _detection_key(r.frame_index, r.cls, r.conf, r.box) not in labelled],
        )


def _detection_key(frame_index: int, cls: str, conf: float, box) -> tuple:
    return (frame_index, cls, round(conf, 6), *(round(v, 6) for v in box))


def examples(conn: sqlite3.Connection) -> list[Example]:
    """Every labelled detection that has a feature, as matcher examples."""
    rows = conn.execute(
        "SELECT label, feature, clip_id FROM detection WHERE label IS NOT NULL AND feature IS NOT NULL ORDER BY id"
    )
    return [Example(r["label"], from_blob(r["feature"]), r["clip_id"]) for r in rows]


def examples_version(conn: sqlite3.Connection) -> tuple[int, str | None]:
    """(how many examples, latest label time): changes whenever examples are added, removed or relabelled,
    so a cached copy of `examples` can tell it is stale without reading the features."""
    row = conn.execute(
        "SELECT COUNT(*) AS n, MAX(labelled_at) AS latest FROM detection WHERE label IS NOT NULL AND feature IS NOT NULL"
    ).fetchone()
    return row["n"], row["latest"]


def example_count(conn: sqlite3.Connection) -> int:
    return examples_version(conn)[0]


def set_recognition(
    conn: sqlite3.Connection, clip_id: int, *, best_frame_path: str | None, verdict_json: str, recognized_at: datetime
) -> None:
    conn.execute(
        "UPDATE clip SET best_frame_path = ?, verdict_json = ?, recognized_at = ?, recognition_error = NULL, "
        "recognition_wanted = 0 WHERE id = ?",
        (best_frame_path, verdict_json, _iso(recognized_at), clip_id),
    )
    conn.commit()


def get_clip(conn: sqlite3.Connection, clip_id: int) -> Clip | None:
    row = conn.execute("SELECT * FROM clip WHERE id = ?", (clip_id,)).fetchone()
    return _clip(row) if row is not None else None


def is_recognized(conn: sqlite3.Connection, clip_id: int) -> bool:
    row = conn.execute("SELECT recognized_at FROM clip WHERE id = ?", (clip_id,)).fetchone()
    return row is not None and row["recognized_at"] is not None


def scientific_name_for(conn: sqlite3.Connection, name: str) -> str | None:
    """A catalog species' scientific name from its English name (any case) or its exact scientific name."""
    row = conn.execute(
        "SELECT s.scientific_name FROM species s LEFT JOIN species_name n ON n.species_id = s.id AND n.lang = 'en' "
        "WHERE s.scientific_name = ? OR lower(n.name) = lower(?) LIMIT 1",
        (name, name),
    ).fetchone()
    return row["scientific_name"] if row else None


def label_detections(conn: sqlite3.Connection, clip_id: int, label: str, source: str) -> int:
    """Label the clip's confident animal detections that have a feature; returns how many were labelled.

    A detection the owner has corrected (label_source 'correction') is never overwritten."""
    cur = conn.execute(
        "UPDATE detection SET label = ?, labelled_at = ?, label_source = ? "
        "WHERE clip_id = ? AND cls = 'animal' AND conf >= ? AND feature IS NOT NULL "
        "AND (label_source IS NULL OR label_source != 'correction')",
        (label, _iso(datetime.now()), source, clip_id, DET_MIN),
    )
    conn.commit()
    return cur.rowcount


def unlabel_detections(conn: sqlite3.Connection, ids: list[int]) -> None:
    conn.executemany(
        "UPDATE detection SET label = NULL, labelled_at = NULL, label_source = NULL WHERE id = ?",
        [(i,) for i in ids],
    )
    conn.commit()


def visit_for_clip(conn: sqlite3.Connection, clip_id: int) -> int | None:
    """The id of the visit this clip belongs to, or None."""
    row = conn.execute("SELECT visit_id FROM visit_clip WHERE clip_id = ?", (clip_id,)).fetchone()
    return row["visit_id"] if row else None


RECOGNIZE_OLD_KEY = "recognize_old_clips"
_NEEDS_RECOGNITION = "status = 'ready' AND web_path IS NOT NULL AND recognized_at IS NULL AND recognition_error IS NULL"


def recognize_old_clips(conn: sqlite3.Connection) -> bool:
    """Whether the processor works through older unrecognised clips by itself (the setting, off when absent)."""
    return get_setting(conn, RECOGNIZE_OLD_KEY) == "on"


def clips_needing_recognition(
    conn: sqlite3.Connection, limit: int, *, wanted_only: bool = False, newest_first: bool = False
) -> list[Clip]:
    """Ready videos not yet recognised and not failed at it, oldest first (newest first on request), or only
    those the owner asked for. Photos have no video, so never."""
    where = _NEEDS_RECOGNITION + (" AND recognition_wanted = 1" if wanted_only else "")
    order = "begin_at DESC, id DESC" if newest_first else "begin_at, id"
    rows = conn.execute(f"SELECT * FROM clip WHERE {where} ORDER BY {order} LIMIT ?", (limit,))
    return [_clip(r) for r in rows]


def count_needing_recognition(conn: sqlite3.Connection) -> int:
    """How many ready videos are still unrecognised and not failed, whatever the setting."""
    return conn.execute(f"SELECT COUNT(*) FROM clip WHERE {_NEEDS_RECOGNITION}").fetchone()[0]


HEARTBEAT_KEY = "processor_heartbeat"
HEARTBEAT_FRESH_S = 30


def beat(conn: sqlite3.Connection, now: datetime) -> None:
    """The running app's processor says it is alive (UTC ISO time in the settings)."""
    set_setting(conn, HEARTBEAT_KEY, now.astimezone(UTC).isoformat())


def app_is_running(conn: sqlite3.Connection, now: datetime) -> bool:
    """True when the processor beat less than HEARTBEAT_FRESH_S ago."""
    value = get_setting(conn, HEARTBEAT_KEY)
    if value is None:
        return False
    try:
        age = (now - datetime.fromisoformat(value)).total_seconds()
    except ValueError:
        return False
    return age < HEARTBEAT_FRESH_S


def set_recognition_error(conn: sqlite3.Connection, clip_id: int, message: str) -> None:
    conn.execute("UPDATE clip SET recognition_error = ?, recognition_wanted = 0 WHERE id = ?", (message, clip_id))
    conn.commit()


def recognition_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """pending: ready videos the processor will recognise (the ones asked for, and every older one while the
    setting is on); old_waiting: older ones that wait until asked for; errors: clips whose recognition failed."""
    row = conn.execute(
        f"SELECT COALESCE(SUM({_NEEDS_RECOGNITION} AND recognition_wanted = 1), 0) AS wanted, "
        f"COALESCE(SUM({_NEEDS_RECOGNITION} AND recognition_wanted = 0), 0) AS old, "
        "COALESCE(SUM(recognition_error IS NOT NULL), 0) AS errors FROM clip"
    ).fetchone()
    if recognize_old_clips(conn):
        return {"pending": row["wanted"] + row["old"], "old_waiting": 0, "errors": row["errors"]}
    return {"pending": row["wanted"], "old_waiting": row["old"], "errors": row["errors"]}


def clips_for_visit(conn: sqlite3.Connection, visit_id: int) -> list[Clip]:
    rows = conn.execute(
        "SELECT c.* FROM clip c JOIN visit_clip vc ON vc.clip_id = c.id WHERE vc.visit_id = ? "
        "ORDER BY c.begin_at, c.id",
        (visit_id,),
    )
    return [_clip(r) for r in rows]


def requeue_recognition(conn: sqlite3.Connection, clip_id: int) -> bool:
    """Clear both recognition markers and mark the clip wanted, so the processor recognises it again even with
    the backfill off; False for an unknown clip."""
    cur = conn.execute(
        "UPDATE clip SET recognition_error = NULL, recognized_at = NULL, recognition_wanted = 1 WHERE id = ?",
        (clip_id,),
    )
    conn.commit()
    return cur.rowcount == 1


# One column of the visit's best clip, or of its first clip when it has no best one.
_VISIT_CLIP_PICK = (
    "(SELECT c.%s FROM visit_clip vc JOIN clip c ON c.id = vc.clip_id WHERE vc.visit_id = v.id "
    "ORDER BY (c.id = v.best_clip_id) DESC, c.begin_at, c.id LIMIT 1)"
)
_VISIT_SELECT = (
    "SELECT v.*, s.scientific_name AS species_scientific, n.name AS species_name, "
    "(SELECT COUNT(*) FROM visit_clip vc WHERE vc.visit_id = v.id) AS clip_count, "
    "(SELECT COALESCE(SUM(c.duration_s), 0) FROM visit_clip vc JOIN clip c ON c.id = vc.clip_id "
    "WHERE vc.visit_id = v.id) AS duration_s, "
    f"{_VISIT_CLIP_PICK % 'poster_path'} AS poster_path, {_VISIT_CLIP_PICK % 'preview_path'} AS preview_path, "
    "v.moved_by_user AS corrected "
    "FROM visit v LEFT JOIN species s ON s.id = v.species_id "
    "LEFT JOIN species_name n ON n.species_id = s.id AND n.lang = 'en' "
)


def list_visits(
    conn: sqlite3.Connection,
    limit: int,
    *,
    after: tuple[str, int] | None = None,
    category: str | None = None,
    species: str | None = None,
    day: date | None = None,
    favourite: bool | None = None,
) -> list[sqlite3.Row]:
    """Visits newest first (`favourite` keeps only starred or only unstarred ones). `after` is the (started_at, id) of the last visit already seen; `day` is the
    local date of started_at (stored as local-time ISO text, like clips)."""
    where, args = [], []
    if after is not None:
        where.append("(v.started_at < ? OR (v.started_at = ? AND v.id < ?))")
        args += [after[0], after[0], after[1]]
    if category is not None:
        where.append("v.category = ?")
        args.append(category)
    if species is not None:
        where.append("s.scientific_name = ?")
        args.append(species)
    if day is not None:
        where.append("substr(v.started_at, 1, 10) = ?")
        args.append(day.isoformat())
    if favourite is not None:
        where.append("v.is_favourite = ?")
        args.append(int(favourite))
    clause = f"WHERE {' AND '.join(where)} " if where else ""  # fragments are fixed strings above
    return conn.execute(f"{_VISIT_SELECT}{clause}ORDER BY v.started_at DESC, v.id DESC LIMIT ?", (*args, limit)).fetchall()


def sorted_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """How many visits are in each category, and how many are favourites."""
    counts = {"birds": 0, "other_animals": 0, "other": 0}
    for r in conn.execute("SELECT category, COUNT(*) AS n FROM visit GROUP BY category"):
        counts[r["category"]] = r["n"]
    favourites = conn.execute("SELECT COUNT(*) FROM visit WHERE is_favourite = 1").fetchone()[0]
    return {**counts, "favourites": favourites}


def species_overview(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every species in the catalog with its visit count and last sighting: birds first, then most visits, then name."""
    return conn.execute(
        "SELECT s.scientific_name, n.name, s.\"group\" AS grp, COUNT(v.id) AS visits, MAX(v.started_at) AS last_seen_at "
        "FROM species s LEFT JOIN species_name n ON n.species_id = s.id AND n.lang = 'en' "
        "LEFT JOIN visit v ON v.species_id = s.id GROUP BY s.id "
        "ORDER BY (s.\"group\" != 'bird'), visits DESC, n.name, s.id"
    ).fetchall()


def get_visit(conn: sqlite3.Connection, visit_id: int) -> sqlite3.Row | None:
    return conn.execute(f"{_VISIT_SELECT}WHERE v.id = ?", (visit_id,)).fetchone()


def visit_guesses(conn: sqlite3.Connection, visit_id: int) -> list[sqlite3.Row]:
    """The visit's best species guesses in rank order, with English names."""
    return conn.execute(
        "SELECT s.scientific_name, n.name, g.confidence FROM guess g JOIN species s ON s.id = g.species_id "
        "LEFT JOIN species_name n ON n.species_id = s.id AND n.lang = 'en' WHERE g.visit_id = ? ORDER BY g.rank",
        (visit_id,),
    ).fetchall()

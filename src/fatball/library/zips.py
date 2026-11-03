"""Downloading visits as one .zip: a plan (names, sizes) made first, then a stream that never holds a file in memory."""

import sqlite3
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fatball.library import repo

MAX_VISITS = 500
CHUNK = 1024 * 1024
_OTHER_LABELS = {"nothing": "Empty clip", "person": "Person"}
_ANIMAL_LABELS = {"birds": "Unknown bird", "other_animals": "Other animal"}
DOG = "Canis lupus familiaris"


class TooMany(ValueError):
    pass


class NothingToDownload(LookupError):
    pass


@dataclass(frozen=True)
class ZipPlan:
    entries: list[tuple[str, Path]]
    size_bytes: int
    visits: int
    filename: str


def _label(row: sqlite3.Row) -> str:
    name = (row["species_name"] or "").replace("/", " ").replace("\\", " ").strip().lstrip(".").strip()
    if name:
        return name[:1].upper() + name[1:]
    if row["category"] == "other":
        if row["species_scientific"] == DOG:
            return "Dog"
        return _OTHER_LABELS.get(row["subject"], "Other")
    return _ANIMAL_LABELS.get(row["category"], "Other")


def _time_label(started_at: str) -> str:
    """'2026-11-02T09:12:..' -> '2026-11-02 09-12', straight from the stored local text."""
    return f"{started_at[:10]} {started_at[11:13]}-{started_at[14:16]}"


def plan_zip(
    conn: sqlite3.Connection,
    media_dir: Path,
    *,
    visit_ids: list[int] | None = None,
    day: date | None = None,
    category: str | None = None,
    favourite: bool | None = None,
) -> ZipPlan:
    if visit_ids is not None:
        ids = list(dict.fromkeys(visit_ids))
        if len(ids) > MAX_VISITS:
            raise TooMany(f"Too many visits for one .zip (max {MAX_VISITS})")
        rows = [r for r in (repo.get_visit(conn, i) for i in ids) if r is not None]
    else:
        rows = repo.list_visits(conn, MAX_VISITS + 1, day=day, category=category, favourite=favourite)
        if len(rows) > MAX_VISITS:
            raise TooMany(f"Too many visits for one .zip (max {MAX_VISITS})")
    rows.sort(key=lambda r: (r["started_at"], r["id"]))

    root = media_dir.resolve()

    def inside(rel: str | None) -> Path | None:
        """The file under media_dir, or None (missing, or a path that escapes it)."""
        if not rel:
            return None
        try:
            target = (root / rel).resolve()
            return target if target.is_relative_to(root) and target.is_file() else None
        except (ValueError, OSError):
            return None

    entries: list[tuple[str, Path]] = []
    used: set[str] = set()
    visits = 0
    for row in rows:
        files: list[tuple[str, Path]] = []  # (extension, path)
        for clip in repo.clips_for_visit(conn, row["id"]):
            if (p := inside(clip.web_path)) is not None:
                files.append((".mp4", p))
        if (p := inside(row["best_frame_path"])) is not None:
            files.append((".jpg", p))
        if not files:
            continue
        visits += 1
        base = f"{_time_label(row['started_at'])} {_label(row)}"
        for ext, path in files:
            name, n = f"{base}{ext}", 1
            while name.lower() in used:
                n += 1
                name = f"{base} ({n}){ext}"
            used.add(name.lower())
            entries.append((name, path))
    if not entries:
        raise NothingToDownload("nothing to download")
    filename = f"fat-ball-{day.isoformat()}.zip" if day is not None else f"fat-ball-{visits}-visits.zip"
    return ZipPlan(entries, sum(p.stat().st_size for _, p in entries), visits, filename)


class _Sink:
    """A non-seekable writer: ZipFile appends here and the generator drains it after every chunk."""

    def __init__(self) -> None:
        self.parts: list[bytes] = []
        self.pos = 0

    def write(self, data: bytes) -> int:
        self.parts.append(bytes(data))
        self.pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self.pos

    def flush(self) -> None:
        pass

    def drain(self) -> bytes:
        data, self.parts = b"".join(self.parts), []
        return data


def stream_zip(plan: ZipPlan) -> Iterator[bytes]:
    sink = _Sink()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED) as zf:  # type: ignore[arg-type]
        for name, path in plan.entries:
            with path.open("rb") as src, zf.open(zipfile.ZipInfo(name, _mtime(path)), "w", force_zip64=True) as dst:
                while chunk := src.read(CHUNK):
                    dst.write(chunk)
                    if data := sink.drain():
                        yield data
            if data := sink.drain():
                yield data
    if data := sink.drain():
        yield data


def _mtime(path: Path) -> tuple[int, int, int, int, int, int]:
    t = time.localtime(path.stat().st_mtime)
    return (max(t.tm_year, 1980), t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)

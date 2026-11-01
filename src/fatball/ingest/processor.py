"""Convert downloaded raw clips into web-friendly files.

Paths written to the database are relative to ``settings.media_dir`` (POSIX strings) so the API can
serve them under /media/. ``raw_path`` is left as the watcher wrote it. The thumbnail has no column;
by convention it lives at ``clips/<id>/thumb.jpg``. The raw file is never deleted.
"""

import logging
import sqlite3
from pathlib import Path

from fatball.config import Settings
from fatball.library import repo
from fatball.library.repo import Clip
from fatball.media.convert import convert_clip
from fatball.media.demux import extract_jpeg

log = logging.getLogger(__name__)


class Processor:
    def __init__(self, settings: Settings, conn: sqlite3.Connection) -> None:
        self.settings = settings
        self.conn = conn
        # A crash mid-conversion leaves clips in "processing": retry them.
        for clip in repo.clips_with_status(conn, "processing"):
            repo.set_clip_status(conn, clip.id, "downloaded")

    def process_pending(self) -> int:
        """Process every downloaded clip; returns how many were attempted."""
        clips = repo.clips_with_status(self.conn, "downloaded")
        for clip in clips:
            repo.set_clip_status(self.conn, clip.id, "processing")
            try:
                paths = self._convert(clip)
            except Exception:  # any failure (ffmpeg missing, bad data...) only fails this clip
                log.exception("processing clip %s failed; raw file kept", clip.id)
                repo.set_clip_status(self.conn, clip.id, "failed")
                continue
            repo.set_clip_status(self.conn, clip.id, "ready", **paths)
        return len(clips)

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.settings.media_dir).as_posix()

    def _convert(self, clip: Clip) -> dict:
        media = self.settings.media_dir
        raw = media / (clip.raw_path or "")  # absolute raw_path wins over media_dir
        if clip.kind == "jpg":
            dest = media / "photos" / f"{clip.id}.jpg"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(extract_jpeg(raw.read_bytes()))
            return {"poster_path": self._rel(dest)}
        out = convert_clip(raw, media / "clips" / str(clip.id))
        return {
            "original_path": self._rel(out.original),
            "web_path": self._rel(out.web),
            "poster_path": self._rel(out.poster),
            "preview_path": self._rel(out.preview),
            "duration_s": out.duration_s,
        }

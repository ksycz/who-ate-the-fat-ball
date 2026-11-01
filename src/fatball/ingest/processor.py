"""Convert downloaded raw clips into web-friendly files.

Paths in the database, ``raw_path`` included, are relative to ``settings.media_dir`` (POSIX strings) so
the API can serve them under /media/. The thumbnail has no column; by convention it lives at
``clips/<id>/thumb.jpg``. The raw file is never deleted.
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
        """Process every downloaded clip; returns how many were attempted.

        Each clip is claimed atomically just before converting and re-read by id, so a clip someone
        else claimed is skipped and the raw_path used is the one stored now, not the listing's.
        """
        attempted = 0
        for listed in repo.clips_with_status(self.conn, "downloaded"):
            clip = repo.claim_for_processing(self.conn, listed.id)
            if clip is None:
                continue
            attempted += 1
            try:
                paths = self._convert(clip)
            except Exception:  # any failure (ffmpeg missing, bad data...) only fails this clip
                log.exception("processing clip %s failed; raw file kept", clip.id)
                repo.set_clip_status(self.conn, clip.id, "failed")
                continue
            repo.set_clip_status(self.conn, clip.id, "ready", **paths)
        return attempted

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.settings.media_dir).as_posix()

    def _convert(self, clip: Clip) -> dict:
        media = self.settings.media_dir
        if not clip.raw_path:
            raise ValueError(f"clip {clip.id} has no raw file")
        raw = media / clip.raw_path
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

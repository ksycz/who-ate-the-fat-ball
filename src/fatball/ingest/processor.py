"""Convert downloaded raw clips into web-friendly files.

Paths in the database, ``raw_path`` included, are relative to ``settings.media_dir`` (POSIX strings) so
the API can serve them under /media/. The thumbnail has no column; by convention it lives at
``clips/<id>/thumb.jpg``. The raw file is never deleted.
"""

import dataclasses
import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

from fatball.config import Settings
from fatball.library import repo, visits
from fatball.library.repo import Clip
from fatball.media.convert import convert_clip
from fatball.media.demux import extract_jpeg
from fatball.recognition.features import feature_print
from fatball.recognition.recognizer import DetectorLike, Recognizer

log = logging.getLogger(__name__)


class Processor:
    """Converts downloaded clips, recognises them and backfills old ones, one clip at a time.

    Recognition is off when neither `recognizer` nor `detector_loader` is given, and waits while the
    library has no examples yet: every clip would come out "unknown" and never be looked at again, so clips
    go ready and stay pending until the owner imports or corrects one (then the backfill catches up). A `detector_loader`
    returns a detector or None (the model file is not there yet); while no detector is loaded it is
    called again on every pass, so a model that appears later starts recognition without a restart. A
    missing model is logged once, not every pass.
    """

    def __init__(
        self,
        settings: Settings,
        conn: sqlite3.Connection,
        recognizer: Recognizer | None = None,
        *,
        detector_loader: Callable[[], DetectorLike | None] | None = None,
        features: Callable = feature_print,
    ) -> None:
        self.settings = settings
        self.conn = conn
        self.recognizer = recognizer
        self._detector_loader = detector_loader
        self._features = features
        self._warned_no_model = False
        self._warned_no_examples = False
        # A crash mid-conversion leaves clips in "processing": retry them.
        for clip in repo.clips_with_status(conn, "processing"):
            repo.set_clip_status(conn, clip.id, "downloaded")

    @property
    def has_detector(self) -> bool:
        return self.recognizer is not None

    def _current_recognizer(self) -> Recognizer | None:
        if self.recognizer is None and self._detector_loader is not None:
            try:
                detector = self._detector_loader()
            except Exception as e:  # noqa: BLE001  e.g. ModelMissing, a bad model: go on without recognition
                detector = None
                reason = f"{type(e).__name__}: {e}"
            else:
                reason = "model file not found"
            if detector is not None:
                self.recognizer = Recognizer(self.settings, self.conn, detector, self._features)
                self._warned_no_model = False
                log.info("detector loaded; recognition is on")
            elif not self._warned_no_model:
                self._warned_no_model = True
                log.warning("no detector (%s); clips stay unrecognised until it appears", reason)
        return self.recognizer

    def process_pending(self) -> int:
        """Convert every downloaded clip (recognising each before it becomes ready), then recognise at most
        one older ready clip (the backfill). Returns how many clips were attempted for conversion.

        Each clip is claimed atomically just before converting and re-read by id, so a clip someone
        else claimed is skipped and the raw_path used is the one stored now, not the listing's.
        """
        recognizer = self._current_recognizer()
        if recognizer is not None and not self._has_examples():
            recognizer = None
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
            if recognizer is not None and clip.kind != "jpg":
                self._recognize(recognizer, dataclasses.replace(clip, **paths))
            repo.set_clip_status(self.conn, clip.id, "ready", **paths)
        if recognizer is not None:
            for clip in repo.clips_needing_recognition(self.conn, 1):
                self._recognize(recognizer, clip)
        return attempted

    def _has_examples(self) -> bool:
        if repo.example_count(self.conn) > 0:
            self._warned_no_examples = False
            return True
        if not self._warned_no_examples:
            self._warned_no_examples = True
            log.warning("no examples yet (run `fatball examples-import`); clips stay unrecognised until there are")
        return False

    def _recognize(self, recognizer: Recognizer, clip: Clip) -> None:
        recognize_and_group(self.conn, recognizer, clip)

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


def recognize_and_group(conn: sqlite3.Connection, recognizer: Recognizer, clip: Clip) -> str | None:
    """Recognise one clip and put it in a visit. A failure is recorded on the clip (and returned), never raised,
    so it stops nothing else. The processor and `fatball examples-import` both go through here."""
    try:
        verdict = recognizer.recognize(clip)
        visits.assign_visit(conn, clip, verdict)
    except Exception as e:
        log.exception("recognising clip %s failed; the video is kept", clip.id)
        message = f"{type(e).__name__}: {e}"[:200]
        repo.set_recognition_error(conn, clip.id, message)
        return message
    return None

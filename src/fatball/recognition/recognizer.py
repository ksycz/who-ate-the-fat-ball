"""Recognise one clip end to end: frames -> detections -> features -> stored rows -> verdict -> best frame."""

import json
import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from fatball.config import Settings
from fatball.library import repo
from fatball.library.repo import Clip, NewDetection
from fatball.media.convert import extract_frames
from fatball.recognition.detector import Detection
from fatball.recognition.features import feature_print, to_blob
from fatball.recognition.matcher import DET_MIN, Crop, Verdict, match


class DetectorLike(Protocol):
    def detect(self, image_path: Path) -> list[Detection]: ...


def verdict_to_json(v: Verdict) -> str:
    return json.dumps({
        "category": v.category,
        "species": v.species,
        "subject": v.subject,
        "confidence": float(v.confidence),
        "guesses": [[name, float(share)] for name, share in v.guesses],
    })


class Recognizer:
    def __init__(self, settings: Settings, conn, detector: DetectorLike, features: Callable = feature_print):
        self.settings = settings
        self.conn = conn
        self.detector = detector
        self.features = features

    def recognize(self, clip: Clip) -> Verdict:
        if not clip.web_path:
            raise ValueError(f"clip {clip.id} has no converted video")
        media = self.settings.media_dir
        with tempfile.TemporaryDirectory(prefix="fatball-frames-") as tmp:
            frames = extract_frames(media / clip.web_path, Path(tmp))
            crops, rows = self._detect(frames)
            repo.replace_detections(self.conn, clip.id, rows)
            verdict = match(
                crops,
                repo.examples(self.conn),
                lambda name: repo.category_for(self.conn, name),
                exclude_clip=clip.id,
            )
            best_rel = None
            if verdict.best is not None:
                dest = media / "clips" / str(clip.id) / "best.jpg"
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(frames[verdict.best.frame_index], dest)
                best_rel = dest.relative_to(media).as_posix()
        repo.set_recognition(
            self.conn, clip.id,
            best_frame_path=best_rel, verdict_json=verdict_to_json(verdict), recognized_at=datetime.now(),
        )
        return verdict

    def _detect(self, frames: list[Path]) -> tuple[list[Crop], list[NewDetection]]:
        import objc  # lazy, like the Apple frameworks: pyobjc objects autoreleased here are drained per clip

        crops: list[Crop] = []
        rows: list[NewDetection] = []
        with objc.autorelease_pool():
            for index, frame in enumerate(frames):
                for det in self.detector.detect(frame):
                    if det.cls == "vehicle":
                        continue
                    feature = None
                    if det.cls == "animal" and det.conf >= DET_MIN:
                        feature = self.features(frame, det.box)
                    crops.append(Crop(index, det, feature))
                    rows.append(NewDetection(index, det.cls, det.conf, det.box,
                                             None if feature is None else to_blob(feature)))
        return crops, rows

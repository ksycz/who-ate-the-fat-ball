"""A scripted stand-in for the Core ML detector, for tests and `fatball demo`."""

from collections.abc import Callable, Mapping
from pathlib import Path

from fatball.recognition.detector import Detection


class FakeDetector:
    """Returns scripted detections. Frames are told apart by call order: the Nth `detect` call (from 0)
    is frame N, which is the order the recognizer feeds them in. `script` is a mapping frame_index ->
    detections (missing frames detect nothing) or a callable taking the frame index."""

    def __init__(self, script: Mapping[int, list[Detection]] | Callable[[int], list[Detection]]):
        self._script = script
        self.calls: list[Path] = []

    def detect(self, image_path: Path) -> list[Detection]:
        index = len(self.calls)
        self.calls.append(Path(image_path))
        if callable(self._script):
            return list(self._script(index))
        return list(self._script.get(index, []))

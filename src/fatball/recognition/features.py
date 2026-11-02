"""Apple Vision feature prints of detector crops.

The crop is made by Vision itself (`regionOfInterest`), so the file is not re-encoded.
Vision's origin is bottom-left; detector boxes are top-left, so y is flipped.
"""

from pathlib import Path

import numpy as np

_FLOAT32 = 1  # VNElementType.float


def _padded_roi(box: tuple[float, float, float, float], pad: float) -> tuple[float, float, float, float]:
    """Padded, clamped box as Vision's (x, y, w, h), origin bottom-left."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    x1, x2 = max(0.0, x1 - pad * w), min(1.0, x2 + pad * w)
    y1, y2 = max(0.0, y1 - pad * h), min(1.0, y2 + pad * h)
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"box has no area inside the image: {box}")
    return x1, 1.0 - y2, x2 - x1, y2 - y1


def feature_print(image_path: Path, box: tuple[float, float, float, float], pad: float = 0.15) -> np.ndarray:
    """A float32 unit vector describing the padded box of the image."""
    import Foundation
    import Vision

    x, y, w, h = _padded_roi(box, pad)
    url = Foundation.NSURL.fileURLWithPath_(str(image_path))
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
    request = Vision.VNGenerateImageFeaturePrintRequest.alloc().init()
    request.setRegionOfInterest_(((x, y), (w, h)))
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"feature print failed for {image_path}: {error}")
    obs = request.results()[0]
    if obs.elementType() != _FLOAT32:
        raise RuntimeError(f"unexpected feature print element type {obs.elementType()}")
    v = np.frombuffer(bytes(obs.data()), dtype=np.float32).copy()
    return v / np.linalg.norm(v)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32).copy()

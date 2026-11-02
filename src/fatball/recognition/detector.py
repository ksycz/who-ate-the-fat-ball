"""MegaDetector v6 (MIT, yolov9-c) through Core ML and Vision.

The model is built by scripts/export_detector.py. It returns one row per anchor,
[cx, cy, w, h, p_animal, p_person, p_vehicle], in 640x640 input pixels, with no NMS.
Vision letterboxes the frame into the square input (scale to fit, centred); `decode` undoes that.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

MODEL_FILENAME = "md_v6_mit_c.mlpackage"
INPUT_SIZE = 640
NMS_IOU = 0.5
CLASSES: tuple[Literal["animal", "person", "vehicle"], ...] = ("animal", "person", "vehicle")

_FLOAT16, _FLOAT32 = 0x10000 | 16, 0x10000 | 32  # MLMultiArrayDataType


class ModelMissing(Exception):
    """The Core ML detector file is not there; run scripts/export_detector.py."""


@dataclass(frozen=True)
class Detection:
    cls: Literal["animal", "person", "vehicle"]
    conf: float
    box: tuple[float, float, float, float]  # normalised x1, y1, x2, y2; origin top-left


def decode(raw: np.ndarray, image_w: int, image_h: int, conf_min: float = 0.1) -> list[Detection]:
    """Turn the model's (N, 7) output into detections on the original image, best first."""
    rows = np.asarray(raw, dtype=np.float32).reshape(-1, 7)
    probs = rows[:, 4:7]
    cls_idx = probs.argmax(axis=1)
    conf = probs[np.arange(len(rows)), cls_idx]
    keep = conf >= conf_min
    rows, cls_idx, conf = rows[keep], cls_idx[keep], conf[keep]

    scale = INPUT_SIZE / max(image_w, image_h)
    new_w, new_h = image_w * scale, image_h * scale
    pad_x, pad_y = (INPUT_SIZE - new_w) / 2, (INPUT_SIZE - new_h) / 2
    cx, cy, w, h = rows[:, 0], rows[:, 1], rows[:, 2], rows[:, 3]
    boxes = np.stack(
        [
            (cx - w / 2 - pad_x) / new_w,
            (cy - h / 2 - pad_y) / new_h,
            (cx + w / 2 - pad_x) / new_w,
            (cy + h / 2 - pad_y) / new_h,
        ],
        axis=1,
    ).clip(0.0, 1.0)

    detections = []
    for i in _nms(boxes, conf, cls_idx):
        x1, y1, x2, y2 = (float(v) for v in boxes[i])
        detections.append(Detection(CLASSES[cls_idx[i]], float(conf[i]), (x1, y1, x2, y2)))
    return detections


def _nms(boxes: np.ndarray, conf: np.ndarray, cls_idx: np.ndarray) -> list[int]:
    """Greedy per-class NMS; returns the indexes to keep, best confidence first."""
    kept: list[int] = []
    for i in np.argsort(-conf, kind="stable"):
        if all(cls_idx[j] != cls_idx[i] or _iou(boxes[i], boxes[j]) <= NMS_IOU for j in kept):
            kept.append(int(i))
    return kept


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / union)


class Detector:
    def __init__(self, model_path: Path):
        model_path = Path(model_path)
        if not model_path.exists():
            raise ModelMissing(f"{model_path} not found; build it with scripts/export_detector.py")
        # Imported here so the pure-numpy decode works (and tests run) without the Apple frameworks.
        import CoreML
        import Vision
        from Foundation import NSURL

        self._CoreML, self._Vision, self._NSURL = CoreML, Vision, NSURL
        compiled_url, error = CoreML.MLModel.compileModelAtURL_error_(NSURL.fileURLWithPath_(str(model_path)), None)
        if compiled_url is None:
            raise ModelMissing(f"could not compile {model_path}: {error}")
        ml_model, error = CoreML.MLModel.modelWithContentsOfURL_error_(compiled_url, None)
        if ml_model is None:
            raise ModelMissing(f"could not load {model_path}: {error}")
        self._model, error = Vision.VNCoreMLModel.modelForMLModel_error_(ml_model, None)
        if self._model is None:
            raise ModelMissing(f"Vision rejected {model_path}: {error}")

    def detect(self, image_path: Path) -> list[Detection]:
        from PIL import Image

        with Image.open(image_path) as img:
            width, height = img.size
        request = self._Vision.VNCoreMLRequest.alloc().initWithModel_(self._model)
        request.setImageCropAndScaleOption_(self._Vision.VNImageCropAndScaleOptionScaleFit)
        handler = self._Vision.VNImageRequestHandler.alloc().initWithURL_options_(
            self._NSURL.fileURLWithPath_(str(image_path)), {}
        )
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise RuntimeError(f"Vision failed on {image_path}: {error}")
        results = request.results()
        if not results:
            return []
        return decode(_to_numpy(results[0].featureValue().multiArrayValue()), width, height)


def _to_numpy(array) -> np.ndarray:
    """Copy an MLMultiArray (rows, 7) into numpy with a single buffer copy.

    Core ML pads each row (the row stride is 32 elements for 7 columns), so the strides are honoured.
    """
    kind = int(array.dataType())
    if kind == _FLOAT16:
        dtype = np.float16
    elif kind == _FLOAT32:
        dtype = np.float32
    else:
        raise RuntimeError(f"unexpected detector output type {kind}")
    rows, cols = (int(n) for n in array.shape())
    row_stride, col_stride = (int(n) for n in array.strides())
    if col_stride != 1 or cols != 7 or row_stride < cols:
        raise RuntimeError(f"unexpected detector output layout {array.shape()} / {array.strides()}")
    buffer = array.dataPointer().as_buffer(rows * row_stride * np.dtype(dtype).itemsize)
    padded = np.frombuffer(buffer, dtype=dtype, count=rows * row_stride).reshape(rows, row_stride)
    return padded[:, :cols].astype(np.float32)

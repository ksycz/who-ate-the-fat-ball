"""Export MegaDetector v6 (MIT, yolov9-c) to a Core ML package for the app.

Run this once, in its own environment. PytorchWildlife itself is MIT, but it depends on ultralytics and
yolov5, which are AGPL, so they are all used only here, at export time, and never imported by anything
under src/. Any Python 3.12 environment with
torch, coremltools and PytorchWildlife works:

    uv run --python 3.12 --with torch --with coremltools --with PytorchWildlife \\
        scripts/export_detector.py OUT_DIR

The result is OUT_DIR/md_v6_mit_c.mlpackage (about 20 MB, never committed). The app looks for it at
<data_dir>/models/md_v6_mit_c.mlpackage. The model returns one tensor (N, 7) with one row per anchor:
[cx, cy, w, h, p_animal, p_person, p_vehicle], in 640-pixel input coordinates. There is no NMS in the model;
fatball.recognition.detector does the thresholding and NMS.

MegaDetector as published runs with per-image normalisation: PytorchWildlife never calls .eval(), so its
BatchNorm layers normalise each image by its own statistics (training mode, batch size 1). The export keeps
that behaviour by swapping every BatchNorm2d for instance normalisation with the same weights; running
statistics would call close-up birds "person". The app letterboxes frames on grey 114, as PytorchWildlife does.
"""

import sys
from pathlib import Path

import coremltools as ct
import torch
import torch.nn.functional as F
from PytorchWildlife.models import detection as pw_detection

MODEL_NAME = "md_v6_mit_c.mlpackage"
SIZE = 640


class Wrapped(torch.nn.Module):
    """YOLO-MIT backbone and head, with PytorchWildlife's anchor decode but without its NMS."""

    def __init__(self, model, converter):
        super().__init__()
        self.model = model
        self.converter = converter

    def forward(self, x):
        # Vec2Box.__call__ with static reshapes (the anchor-decode shape unpacking does not trace to Core ML).
        cls_logits, boxes = [], []
        for pred_cls, _, pred_box in self.model(x)["Main"]:
            cls_logits.append(pred_cls.flatten(2).permute(0, 2, 1))
            boxes.append(pred_box.flatten(2).permute(0, 2, 1))
        cls_logits, boxes = torch.cat(cls_logits, dim=1), torch.cat(boxes, dim=1)
        ltrb = boxes * self.converter.scaler.view(1, -1, 1)
        lt, rb = ltrb.chunk(2, dim=-1)
        x1y1, x2y2 = self.converter.anchor_grid - lt, self.converter.anchor_grid + rb
        wh = x2y2 - x1y1
        return torch.cat([(x1y1 + x2y2) / 2, wh, cls_logits.sigmoid()], dim=-1)[0]


class PerImageNorm(torch.nn.Module):
    """A BatchNorm2d in training mode at batch size 1: each image normalised by its own statistics.

    Unlike a train-mode BatchNorm it never updates (or reads) the running statistics."""

    def __init__(self, bn: torch.nn.BatchNorm2d):
        super().__init__()
        self.weight, self.bias, self.eps = bn.weight, bn.bias, bn.eps

    def forward(self, x):
        return F.instance_norm(x, weight=self.weight, bias=self.bias, eps=self.eps)


def _per_image_norm(module: torch.nn.Module) -> None:
    for name, child in module.named_children():
        if isinstance(child, torch.nn.BatchNorm2d):
            setattr(module, name, PerImageNorm(child))
        else:
            _per_image_norm(child)


def _patch_anchor2vec(model) -> None:
    """Anchor2Vec unpacks x.shape into reshape(), which coremltools cannot convert; use -1 instead."""

    def forward(self, anchor_x):
        anchor_x = anchor_x.unflatten(1, (4, -1)).permute(0, 2, 1, 3, 4)
        vector_x = self.anc2vec(anchor_x.softmax(dim=1))[:, 0]
        return anchor_x, vector_x

    for module in model.modules():
        if type(module).__name__ == "Anchor2Vec":
            module.forward = forward.__get__(module)


def main(out_dir: Path) -> None:
    detector = pw_detection.MegaDetectorV6MIT(device="cpu", pretrained=True, version="MDV6-mit-yolov9-c")
    # The YOLO-MIT wrapper only builds its model lazily, inside single_image_detection().
    detector._load_model(weights=detector.weights, device=detector.device, url=detector.url)
    _patch_anchor2vec(detector.model)
    _per_image_norm(detector.model)
    wrapped = Wrapped(detector.model, detector.converter).eval()
    example = torch.zeros(1, 3, SIZE, SIZE)
    with torch.no_grad():
        traced = torch.jit.trace(wrapped, example)
    mlmodel = ct.convert(
        traced,
        inputs=[ct.ImageType(name="image", shape=example.shape, scale=1 / 255, color_layout=ct.colorlayout.RGB)],
        outputs=[ct.TensorType(name="detections")],
        compute_precision=ct.precision.FLOAT16,
        minimum_deployment_target=ct.target.macOS14,
        convert_to="mlprogram",
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / MODEL_NAME
    mlmodel.save(str(target))
    print(f"saved {target}")
    print("output shape:", tuple(wrapped(example).shape))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))

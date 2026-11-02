"""Nearest-example matcher: a clip's animal crops plus the owner's labelled examples -> a verdict.

Pure numpy; the category rules arrive as a function so nothing here touches the library or Vision.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np

from fatball.recognition.detector import Detection

DET_MIN = 0.3
PERSON_MIN = 0.5
PERSON_FRAMES = 2
K = 5
SURE_SHARE = 0.65
NOTHING = "nothing"


@dataclass(frozen=True)
class Crop:
    frame_index: int
    det: Detection
    feature: np.ndarray | None


@dataclass(frozen=True)
class Example:
    label: str
    feature: np.ndarray
    clip_id: int


@dataclass(frozen=True)
class Verdict:
    category: str
    species: str | None
    confidence: float
    guesses: list[tuple[str, float]]
    subject: Literal["species", "unknown", "person", "nothing"]
    best: Crop | None


def _area(crop: Crop) -> float:
    x1, y1, x2, y2 = crop.det.box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _best(crops: list[Crop]) -> Crop | None:
    return max(crops, key=lambda c: c.det.conf * _area(c), default=None)


def match(
    crops: list[Crop],
    examples: list[Example],
    category_for: Callable[[str | None], str],
    *,
    exclude_clip: int | None = None,
) -> Verdict:
    person_frames = {c.frame_index for c in crops if c.det.cls == "person" and c.det.conf >= PERSON_MIN}
    if len(person_frames) >= PERSON_FRAMES:
        return Verdict(category_for(None), None, 1.0, [], "person", None)

    animals = [c for c in crops if c.det.cls == "animal" and c.det.conf >= DET_MIN]
    if not animals:
        return Verdict(category_for(None), None, 1.0, [], "nothing", None)

    usable = [e for e in examples if e.clip_id != exclude_clip]
    voters = [c for c in animals if c.feature is not None]
    weights: dict[str, float] = defaultdict(float)
    nearest: list[str] = []  # each voter's own top-1 label, aligned with `voters`
    if usable and voters:
        labels = np.array([e.label for e in usable], dtype=object)
        matrix = np.stack([np.asarray(e.feature, dtype=np.float32) for e in usable])
        queries = np.stack([np.asarray(c.feature, dtype=np.float32) for c in voters])
        sims = queries @ matrix.T  # (voters, examples)
        k = min(K, len(usable))
        order = np.argsort(-sims, axis=1, kind="stable")[:, :k]
        for crop, row in zip(voters, order, strict=True):
            nearest.append(str(labels[row[0]]))
            for label in labels[row]:
                weights[str(label)] += crop.det.conf

    total = sum(weights.values())
    shares = {label: w / total for label, w in weights.items()} if total else {}
    ranked = sorted(shares.items(), key=lambda kv: (-kv[1], kv[0]))
    species_ranked = [(label, s) for label, s in ranked if label != NOTHING]
    guesses = species_ranked[:3]

    if ranked and ranked[0][0] == NOTHING:
        return Verdict(category_for(None), None, ranked[0][1], guesses, "nothing", None)

    if ranked and ranked[0][1] >= SURE_SHARE:
        label, share = ranked[0]
        winners = [c for c, n in zip(voters, nearest, strict=True) if n == label]
        return Verdict(category_for(label), label, share, guesses, "species", _best(winners) or _best(voters))

    if species_ranked:
        category, confidence = category_for(species_ranked[0][0]), ranked[0][1]
    else:
        category, confidence = "birds", 0.0
    return Verdict(category, None, confidence, guesses, "unknown", _best(animals))

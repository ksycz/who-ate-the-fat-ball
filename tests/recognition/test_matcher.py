import numpy as np

from fatball.recognition.catalog import DOG
from fatball.recognition.detector import Detection
from fatball.recognition.matcher import Crop, Example, match

GREAT = "Parus major"
BLUE = "Cyanistes caeruleus"
SPARROW = "Passer domesticus"
FOX = "Vulpes vulpes"
DIM = 8
AXIS = {GREAT: 0, BLUE: 1, SPARROW: 2, DOG: 3, "nothing": 4, FOX: 5}
CATEGORY = {GREAT: "birds", BLUE: "birds", SPARROW: "birds", DOG: "other", FOX: "other_animals"}
BOX = (0.1, 0.1, 0.5, 0.5)


def category_for(name):
    return CATEGORY.get(name, "other")


def vec(label, wobble=0.0):
    v = np.zeros(DIM, dtype=np.float32)
    v[AXIS[label]] = 1.0
    v[7] = wobble
    return v / np.linalg.norm(v)


def crop(label, frame=0, conf=0.9, box=BOX, cls="animal"):
    feature = vec(label) if label else None
    return Crop(frame, Detection(cls, conf, box), feature)


def examples(label, n, clip_id=1):
    return [Example(label, vec(label, 0.01 * i), clip_id) for i in range(n)]


def test_clear_species_majority():
    ex = examples(GREAT, 5) + examples(BLUE, 5, clip_id=2)
    v = match([crop(GREAT, 0), crop(GREAT, 1), crop(GREAT, 2)], ex, category_for)
    assert (v.subject, v.species, v.category) == ("species", GREAT, "birds")
    assert v.confidence == 1.0
    assert v.best is not None


def test_person_rule_wins_over_animals():
    crops = [crop(GREAT, 0), crop(None, 1, 0.8, cls="person"), crop(None, 2, 0.7, cls="person")]
    v = match(crops, examples(GREAT, 5), category_for)
    assert (v.subject, v.category, v.species, v.best) == ("person", "other", None, None)


def test_single_person_frame_is_not_enough():
    crops = [crop(GREAT, 0), crop(None, 1, 0.8, cls="person"), crop(None, 1, 0.9, cls="person")]
    v = match(crops, examples(GREAT, 5), category_for)
    assert v.subject == "species"


def test_no_animal_crops_is_nothing():
    v = match([crop(GREAT, 0, conf=0.1), crop(None, 1, cls="vehicle")], examples(GREAT, 5), category_for)
    assert (v.subject, v.category, v.species) == ("nothing", "other", None)


def test_low_share_is_unknown_bird():
    ex = examples(GREAT, 3) + examples(BLUE, 3, clip_id=2) + examples(SPARROW, 3, clip_id=3)
    # each query is equidistant-ish: wobble between three directions
    q = vec(GREAT) + vec(BLUE) * 0.99 + vec(SPARROW) * 0.98
    q = (q / np.linalg.norm(q)).astype(np.float32)
    c = Crop(0, Detection("animal", 0.9, BOX), q)
    v = match([c], ex, category_for)
    assert (v.subject, v.species, v.category) == ("unknown", None, "birds")
    assert v.confidence < 0.65


def test_no_examples_gives_unknown_not_error():
    v = match([crop(GREAT)], [], category_for)
    assert (v.subject, v.species, v.category, v.guesses) == ("unknown", None, "birds", [])
    assert v.best is not None


def test_dog_label_maps_to_other():
    ex = examples(DOG, 5) + examples(GREAT, 5, clip_id=2)
    v = match([crop(DOG, 0), crop(DOG, 1)], ex, category_for)
    assert (v.subject, v.species, v.category) == ("species", DOG, "other")


def test_nothing_majority_is_other():
    ex = examples("nothing", 5) + examples(GREAT, 5, clip_id=2)
    v = match([crop("nothing", 0), crop("nothing", 1)], ex, category_for)
    assert (v.subject, v.category, v.species) == ("nothing", "other", None)


def test_exclude_clip_ignores_own_examples():
    ex = examples(GREAT, 5, clip_id=7) + examples(BLUE, 5, clip_id=8)
    assert match([crop(GREAT)], ex, category_for).species == GREAT
    v = match([crop(GREAT)], ex, category_for, exclude_clip=7)
    assert v.species == BLUE
    assert match([crop(GREAT)], ex[:5], category_for, exclude_clip=7).subject == "unknown"


def test_guesses_top3_sorted():
    ex = (
        examples(GREAT, 2)
        + examples(BLUE, 2, clip_id=2)
        + examples(SPARROW, 2, clip_id=3)
        + examples(FOX, 2, clip_id=4)
    )

    def leaning(*labels):
        q = sum(vec(label) * w for label, w in zip(labels, (1.0, 0.8, 0.6, 0.4)))
        return (q / np.linalg.norm(q)).astype(np.float32)

    first = Crop(0, Detection("animal", 0.9, BOX), leaning(GREAT, BLUE, SPARROW, FOX))
    second = Crop(1, Detection("animal", 0.5, BOX), leaning(GREAT, SPARROW, BLUE, FOX))
    third = Crop(2, Detection("animal", 0.3, BOX), leaning(FOX, GREAT, BLUE, SPARROW))
    v = match([first, second, third], ex, category_for)
    assert [g for g, _ in v.guesses] == [GREAT, BLUE, SPARROW]
    assert FOX not in dict(v.guesses)
    shares = [s for _, s in v.guesses]
    assert shares == sorted(shares, reverse=True)
    assert sum(shares) < 1.0  # the fourth label took the rest


def test_best_crop_is_largest_confident_winner():
    ex = examples(GREAT, 5) + examples(BLUE, 5, clip_id=2)
    small = crop(GREAT, 0, 0.9, (0.1, 0.1, 0.2, 0.2))
    big = crop(GREAT, 1, 0.8, (0.1, 0.1, 0.6, 0.6))
    huge_loser = crop(BLUE, 2, 0.6, (0.0, 0.0, 1.0, 1.0))
    v = match([small, big, huge_loser], ex, category_for)
    assert v.species == GREAT
    assert v.best is big


def test_species_verdict_always_has_best_crop():
    # B wins on neighbours 2..K while every crop's own top-1 is A.
    ex = examples(GREAT, 1) + examples(BLUE, 4, clip_id=2)
    q = vec(GREAT) + vec(BLUE) * 0.5
    c = Crop(0, Detection("animal", 0.9, BOX), (q / np.linalg.norm(q)).astype(np.float32))
    v = match([c], ex, category_for)
    assert (v.subject, v.species) == ("species", BLUE)
    assert v.best is c

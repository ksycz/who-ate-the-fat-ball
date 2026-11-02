# Plan 2: Bird Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every clip the app downloads gets a section (Birds, Other animals, Other), a species with a confidence and top 3 guesses, a best frame, and a place in a visit. The owner can correct any of this through the API, every correction teaches the matcher at once, and it all stays light enough for an 8 GB MacBook Air.

**Architecture:**
- A new package, `fatball/recognition/`, has four pieces:
  - `detector.py`: MegaDetector v6 MIT, converted once to Core ML, run through Apple Vision.
  - `features.py`: Apple Vision feature prints of the detector's crops.
  - `matcher.py`: a pure function from crops to a verdict (k nearest labelled examples).
  - `recognizer.py`: frames → detections → verdict → best frame, for one clip.
- Visit grouping lives in `library/visits.py`. Labelled examples are simply `detection` rows that carry a human label.
- The existing `Processor` runs recognition after conversion. A clip becomes `ready` only once it's recognised. Clips already `ready` without recognition are backfilled one at a time.
- New API endpoints list and correct visits, with undo.
- The gallery UI stays in Plan 3.

**Tech Stack:**
- Already used: Python 3.12+ with `uv`, FastAPI, SQLite, ffmpeg.
- New: `pyobjc-framework-Vision` and `pyobjc-framework-CoreML` (MIT), `numpy` (BSD), `pillow` (HPND).
- Export-time only, in a throwaway environment that is never an app dependency: `torch`, `coremltools`, and PytorchWildlife's `yolo_mit` code.

**Spec:** `docs/superpowers/specs/2026-10-31-who-ate-the-fat-ball-design.md` (§2, §4, §6.2–6.4, §7, §10 subset, §11 memory budget, §12, §14). Read the spike result `docs/spikes/2026-11-02-bird-recognition.md` first: it is the evidence for every threshold below.

**Out of scope (Plan 3 or later):**
- the gallery
- the Mac banner (§6.5)
- the endpoints `/api/today`, `/api/species`, `/api/stats`, `/api/videos`, `/api/visits/bulk` and zip downloads
- correcting the timestamps of clips recorded before the clock fix

## Global Constraints

- Everything from Plan 1's Global Constraints still holds: licences compatible with MIT, privacy, no automatic deletion of media, no pushing to GitHub unless the owner asks.
- **Memory and priority:**
  - Recognition must stay under **300 MB** of extra resident memory.
  - It runs on the processor thread at macOS QoS class **`QOS_CLASS_UTILITY`**, one clip at a time.
  - No PyTorch, ONNX Runtime or other ML framework is an app dependency. Inference goes through Core ML and Vision only.
- **Detector:**
  - Model `MDV6-mit-yolov9-c`, 640×640 input, classes `0 animal, 1 person, 2 vehicle`.
  - App file: `<data_dir>/models/md_v6_mit_c.mlpackage`.
  - It is **never committed** (≈20 MB binary). `scripts/export_detector.py` builds it.
- **Frames:** sampled at **2 fps**, scaled to **1280 px wide**, by ffmpeg into a temporary directory. The directory is deleted after the clip, except the best frame.
- **Thresholds (from the spike):**
  - `DET_MIN = 0.3`: detector confidence for an animal crop to count.
  - `PERSON_MIN = 0.5` and `PERSON_FRAMES = 2`: the person rule.
  - `K = 5`: neighbours per crop.
  - `SURE_SHARE = 0.65`: vote share for a species to count as sure.
  - Task 10 may retune these and records any change in the spike doc.
- **Labels:** a detection's `label` is one of:
  - a species' `scientific_name` from the catalog
  - `"nothing"` (a false box: leaves, glare, an arm)
  - NULL (no human label)
  - The dog is the catalog species `Canis lupus familiaris`.
- **Category rules (§6.2, §17):**
  - a bird species → `birds`
  - `Canis lupus familiaris` → `other` (any dog goes to Other)
  - any other mammal → `other_animals`
  - a person, `"nothing"` or no detection → `other`
- **Visits (§6.3):** a clip joins a visit when the gap to one of that visit's clips is **under 60 s** and the category and species are the same. A clip with no sure species joins any visit it falls within 60 s of, if the category matches.
- **Undo tokens:** random 22-character URL-safe strings (`secrets.token_urlsafe(16)`), kept for 24 h.

## Review Focus

1. **A model file is missing or corrupt** (fresh install, or a failed export). Clips must still convert and show up, with recognition marked pending, not failed. Recognition resumes once the file appears. *(Task 7: `test_missing_model_keeps_clips_ready_and_unrecognised`)*
2. **An empty example library** (first run, before any import). Every animal clip becomes "Unknown bird" or an unknown animal. Nothing crashes, and person and empty clips still go to Other. *(Task 4: `test_no_examples_gives_unknown_not_error`)*
3. **The owner corrects a visit, then undoes it.** The examples that correction added must disappear again. Otherwise a mistaken correction would quietly keep teaching the matcher. *(Task 9: `test_undo_removes_examples_added_by_the_correction`)*
4. **Clips recognised out of order** (the 627-clip backfill runs newest first, catch-up downloads too). Visits must come out the same as in time order, including a late clip that bridges two visits. *(Task 6: `test_out_of_order_clip_bridges_two_visits`)*
5. **A visit the owner moved by hand.** A clip recognised later must not be merged into it, or pull it apart, against the owner's choice. *(Task 6: `test_visit_moved_by_user_is_not_merged`)*

---

### Task 1: Detector in Core ML

**Files:**
- Create: `scripts/export_detector.py`
- Create: `src/fatball/recognition/__init__.py`
- Create: `src/fatball/recognition/detector.py`
- Test: `tests/recognition/test_detector.py`
- Modify: `pyproject.toml` (add `pyobjc-framework-Vision`, `pyobjc-framework-CoreML`, `numpy`, `pillow`)
- Modify: `README.md` (one "Bird recognition model" paragraph: how to run the export)

**Interfaces:**
- Produces:
  - `Detection` (frozen dataclass): `cls: Literal["animal", "person", "vehicle"]`, `conf: float`, `box: tuple[float, float, float, float]`. The box is normalised 0–1 `(x1, y1, x2, y2)`, origin top-left.
  - `class Detector`: `__init__(self, model_path: Path)` loads and compiles the model once; `detect(self, image_path: Path) -> list[Detection]`.
  - `decode(raw: np.ndarray, image_w: int, image_h: int, conf_min: float = 0.1) -> list[Detection]`: pure numpy, so it can be tested without the model.
  - `MODEL_FILENAME = "md_v6_mit_c.mlpackage"`
  - `class ModelMissing(Exception)`

- [ ] **Step 1: Write the export script.**
  - It runs in its own environment, not the project venv:
    ```bash
    uv run --python 3.12 --with torch --with coremltools --with PytorchWildlife scripts/export_detector.py OUT_DIR
    ```
  - It loads `MegaDetectorV6MIT(version="MDV6-mit-yolov9-c")` and wraps `model.model` in a `torch.nn.Module` whose forward returns one tensor `(N, 7)` = `[cx, cy, w, h, p_animal, p_person, p_vehicle]` in 640-pixel input coordinates. Take the decode from PytorchWildlife's `yolo_mit` post-processing, without NMS.
  - It traces at `1×3×640×640` and converts with `coremltools` (`ct.ImageType`, scale 1/255, fp16, `minimum_deployment_target=ct.target.macOS14`).
  - It saves `OUT_DIR/md_v6_mit_c.mlpackage` and prints the output shape.
- [ ] **Step 2: Write the failing tests for `decode`:**
  - `test_decode_letterbox_maps_back_to_normalised_box`: a 1280×720 image letterboxed into 640×640 (vertical padding 140 px). A raw row at `cx=320, cy=320, w=64, h=36` comes back with a box centred at (0.5, 0.5), width 0.1 and height 0.1.
  - `test_decode_drops_below_conf_min_and_picks_class_argmax`
  - `test_decode_nms_keeps_best_of_overlapping_boxes`: two boxes with IoU 0.8 → one; two with IoU 0.1 → two. The NMS IoU threshold is 0.5.
  - `test_detector_missing_model_raises`: `Detector(tmp_path / "nope.mlpackage")` raises `ModelMissing`.
- [ ] **Step 3: Run them.** `uv run pytest tests/recognition/test_detector.py -v`. Expected: FAIL (module not found).
- [ ] **Step 4: Implement `decode` and `Detector`.**
  - `Detector` uses `MLModel.compileModelAtURL_error_`, `VNCoreMLModel.modelForMLModel_error_`, and a `VNCoreMLRequest` with `imageCropAndScaleOption = VNImageCropAndScaleOptionScaleFit` (Vision letterboxes, and `decode` undoes it).
  - Read the output `MLMultiArray` into numpy with one buffer copy (`dataPointer().as_buffer(count)`), never element by element.
- [ ] **Step 5: Add `test_detector_on_real_model`.** Mark it `@pytest.mark.skipif` when `FATBALL_DETECTOR` (a path to the model) isn't set. It runs `detect` on a generated 1280×720 frame (ffmpeg `testsrc`) and asserts it returns a list in under 0.5 s.
- [ ] **Step 6: Run the export once and check parity locally.**
  - Export to `~/Library/Application Support/WhoAteTheFatBall/models/`.
  - Compare against the spike: run `Detector.detect` on 3 spike frames (`local/spike/test2fps/22/f010.jpg`, `.../314/f010.jpg`, `.../600/f010.jpg`) and check the best animal box against `local/spike/results_bc.json`. Expected: same class, IoU ≥ 0.8, confidence within 0.1.
  - Record the result and the ms per frame in the spike doc under "Not yet measured". Nothing from `local/` is committed.
- [ ] **Step 7: Run all tests and lint.** `uv run pytest -q && uv run ruff check`. Expected: all pass, and the real-model test is skipped in CI.
- [ ] **Step 8: Commit.** `git commit -m "feat(recognition): MegaDetector v6 MIT through Core ML, with export script"`

**Ruling, if the Core ML conversion fails:** stop and report. Don't fall back to PyTorch at runtime; that breaks the memory constraint.

### Task 2: Feature prints

**Files:**
- Create: `src/fatball/recognition/features.py`
- Test: `tests/recognition/test_features.py`

**Interfaces:**
- Consumes: `Detection.box` from Task 1.
- Produces:
  - `feature_print(image_path: Path, box: tuple[float, float, float, float], pad: float = 0.15) -> np.ndarray`: a float32 unit vector.
  - `similarity(a: np.ndarray, b: np.ndarray) -> float`: a dot product.
  - `to_blob(v: np.ndarray) -> bytes` and `from_blob(b: bytes) -> np.ndarray`.

- [ ] **Step 1: Write the failing tests** (the images are generated with Pillow in `tmp_path`):
  - `test_same_crop_twice_is_identical`: similarity > 0.999.
  - `test_unit_length`: `abs(np.linalg.norm(v) - 1) < 1e-5`.
  - `test_different_objects_less_similar_than_same`: a red disc on grass-green vs a red disc at another position (high similarity) and vs a blue square (lower). Assert `sim(red, red2) > sim(red, blue)`.
  - `test_box_padding_is_clamped_to_the_image`: a box touching the edge doesn't raise.
  - `test_blob_round_trip`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** with `VNGenerateImageFeaturePrintRequest`.
  - Set `regionOfInterest` to the padded box, converted to Vision's bottom-left origin. Don't crop with Pillow.
  - Read the observation's `data()` as float32 and normalise it.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(recognition): Apple Vision feature prints of detector crops"`

### Task 3: Schema v2 with migrations, and the species catalog

**Files:**
- Modify: `src/fatball/library/db.py`
- Create: `src/fatball/library/migrations/002_recognition.sql`
- Create: `src/fatball/recognition/catalog.py`
- Modify: `src/fatball/library/repo.py` (new dataclasses and functions below)
- Test: `tests/library/test_migrations.py`, `tests/library/test_repo.py`

**Interfaces:**
- Produces:
  - `SCHEMA_VERSION = 2`. `connect()` creates a fresh database at v1 from `schema.sql`, then applies `migrations/00N_*.sql` in order. Each runs in a transaction and sets `PRAGMA user_version = N`.
  - Migration 002:
    - `ALTER TABLE clip ADD COLUMN recognized_at TEXT`
    - `ALTER TABLE clip ADD COLUMN best_frame_path TEXT`
    - `ALTER TABLE clip ADD COLUMN recognition_error TEXT`
    - `ALTER TABLE clip ADD COLUMN verdict_json TEXT`: the clip's own verdict (`category`, `species`, `subject`, `confidence`, `guesses`), which visits recompute from.
    - `ALTER TABLE visit ADD COLUMN subject TEXT`: `species`, `unknown`, `person` or `nothing`.
    - Table `detection`: `id` PK; `clip_id` FK; `frame_index` INT; `cls` TEXT; `conf` REAL; `x1`, `y1`, `x2`, `y2` REAL; `feature` BLOB nullable; `label` TEXT nullable; `labelled_at` TEXT nullable; `label_source` TEXT nullable, CHECK in `('import', 'correction')`.
      - Indexes: `detection(clip_id)`, and a partial index `detection(label) WHERE label IS NOT NULL`.
    - Table `undo`: `token` PK, `visit_id`, `before_json` TEXT, `created_at` TEXT.
    - Index `visit(started_at)`.
    - The `species."group"` CHECK is unchanged: the dog is `group='mammal'`, and the category rule special-cases its scientific name.
  - `catalog.CATALOG: list[tuple[str, str, str]]` of `(english, scientific, group)`.
    - Take the spike's list (`local/spike/species.py`), but with `("dog", "Canis lupus familiaris", "mammal")` instead of `Canis familiaris`.
  - `catalog.DOG = "Canis lupus familiaris"`
  - `repo.ensure_catalog(conn) -> None`: idempotent upsert into `species` and `species_name` (lang `en`).
  - `repo.category_for(conn, scientific_name: str | None) -> Literal["birds", "other_animals", "other"]`: applies the category rules.

- [ ] **Step 1: Write the failing tests:**
  - `test_fresh_database_is_v2`
  - `test_v1_database_upgrades_and_keeps_clips`: build a v1 database with the Plan 1 `schema.sql`, add a clip, connect, and assert v2, the clip still there and `recognized_at IS NULL`.
  - `test_migration_is_idempotent`: connecting twice causes no error.
  - `test_ensure_catalog_twice_no_duplicates`
  - `test_category_rules`: great tit → birds; DOG → other; red fox → other_animals; None → other; `"nothing"` → other.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement the migration runner, migration 002, the catalog and the repo functions.**
- [ ] **Step 4: Run all tests.** Expected: PASS. The existing tests are unchanged.
- [ ] **Step 5: Commit.** `git commit -m "feat(library): schema v2 with migrations; detections, undo and species catalog"`

### Task 4: Matcher

**Files:**
- Create: `src/fatball/recognition/matcher.py`
- Test: `tests/recognition/test_matcher.py`

**Interfaces:**
- Consumes: `Detection` (Task 1); `similarity` (Task 2); the category rules (Task 3, passed in as a function so the matcher stays pure).
- Produces:
  - `Crop` (frozen dataclass): `frame_index: int`, `det: Detection`, `feature: np.ndarray | None`.
  - `Example` (frozen dataclass): `label: str`, `feature: np.ndarray`, `clip_id: int`.
  - `Verdict` (frozen dataclass):
    - `category: str`
    - `species: str | None`: a scientific name; None means unknown, person or nothing.
    - `confidence: float`
    - `guesses: list[tuple[str, float]]`: up to 3 species labels with their vote shares, best first.
    - `subject: Literal["species", "unknown", "person", "nothing"]`
    - `best: Crop | None`
  - `match(crops: list[Crop], examples: list[Example], category_for: Callable[[str | None], str], *, exclude_clip: int | None = None) -> Verdict`
  - The constants `DET_MIN`, `PERSON_MIN`, `PERSON_FRAMES`, `K`, `SURE_SHARE`, with the values in Global Constraints.

**Algorithm:**
1. If `PERSON_FRAMES` or more distinct frames have a person with confidence ≥ `PERSON_MIN`, return `other` / `person`.
2. Take the animal crops with confidence ≥ `DET_MIN`. If there are none, return `other` / `nothing`.
3. For each crop, find the K most similar examples (skipping `exclude_clip`). Each neighbour's vote is weighted by the crop's `conf`.
4. Add up the votes per label, and compute each label's share of the total.
5. Decide:
   - The top label is `"nothing"` → `other` / `nothing`.
   - The top label is a species with share ≥ `SURE_SHARE` → that species and its category.
   - Otherwise → `subject="unknown"`, `species=None`, `confidence=share`. The category is that of the best *species* label among the votes. If there are no species votes, or no examples at all, the category is `birds`.
6. Pick `best`: the crop with the highest `conf × box area`, among the crops whose own nearest neighbour has the winning label (all crops when the result is unknown).

- [ ] **Step 1: Write the failing tests** with synthetic 8-dimensional unit vectors (one direction per label):
  - `test_clear_species_majority`
  - `test_person_rule_wins_over_animals`
  - `test_no_animal_crops_is_nothing`
  - `test_low_share_is_unknown_bird`
  - `test_no_examples_gives_unknown_not_error` (Review Focus 2)
  - `test_dog_label_maps_to_other`: the shiba case.
  - `test_nothing_majority_is_other`
  - `test_exclude_clip_ignores_own_examples`
  - `test_guesses_top3_sorted`
  - `test_best_crop_is_largest_confident_winner`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement `match`.** Use numpy matrix products, not Python loops over examples.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(recognition): nearest-example matcher with person and unknown rules"`

### Task 5: Recognizer (one clip, end to end)

**Files:**
- Create: `src/fatball/recognition/recognizer.py`
- Create: `src/fatball/recognition/qos.py`
- Modify: `src/fatball/media/convert.py` (add `extract_frames`)
- Test: `tests/recognition/test_recognizer.py`, `tests/media/test_convert.py`

**Interfaces:**
- Consumes: `Detector` (1), `feature_print` and `to_blob` (2), `match` (4), the repo (3).
- Produces:
  - `convert.extract_frames(video: Path, out_dir: Path, fps: float = 2.0, width: int = 1280) -> list[Path]`
  - `qos.set_background_priority() -> bool`: calls `pthread_set_qos_class_self_np(QOS_CLASS_UTILITY, 0)` through `ctypes`. Returns False instead of raising if that isn't available.
  - `class Recognizer`:
    - `__init__(self, settings: Settings, conn, detector: DetectorLike, features: Callable = feature_print)`. `DetectorLike` is a `Protocol` with `detect(Path) -> list[Detection]`, so tests pass a fake.
    - `recognize(self, clip: Clip) -> Verdict`. It:
      - extracts the frames,
      - detects in each frame,
      - computes features for animal boxes with confidence ≥ `DET_MIN` only,
      - replaces the clip's `detection` rows (keeping any labelled ones; see below),
      - loads the examples (`repo.examples(conn)`) and calls `match` with `exclude_clip=clip.id`,
      - copies the best crop's frame to `clips/<id>/best.jpg`,
      - sets `best_frame_path`, `verdict_json` and `recognized_at`,
      - deletes the temporary frames.
  - `repo.replace_detections(conn, clip_id, rows) -> None`. Labelled detections are never deleted. Recognizing a clip again only replaces the unlabelled ones.
  - `repo.examples(conn) -> list[Example]`

- [ ] **Step 1: Write the failing tests** using a generated 4 s `testsrc` video and a `FakeDetector` that returns scripted detections per frame index:
  - `test_extract_frames_two_per_second`: 4 s → 8 frames, each 1280 px wide.
  - `test_recognize_stores_detections_and_verdict`
  - `test_temp_frames_deleted_best_frame_kept`
  - `test_features_only_for_confident_animal_boxes`: the spy `features` is called only for animal boxes with confidence ≥ 0.3.
  - `test_rerecognize_keeps_labelled_detections`
  - `test_set_background_priority_returns_bool`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(recognition): recognise one clip end to end at background priority"`

### Task 6: Visits

**Files:**
- Create: `src/fatball/library/visits.py`
- Test: `tests/library/test_visits.py`

**Interfaces:**
- Consumes: `Verdict` (4), the catalog (3).
- Produces: `assign_visit(conn, clip: Clip, verdict: Verdict) -> int` (a visit id). In one transaction it:
  1. Finds the compatible visits: at least one of their clips is under 60 s from this clip (gap between end and begin, either direction), and their category matches. Their species must also match, unless the verdict is unknown, or the visit's species is NULL and the visit is unknown. Visits with `moved_by_user=1` are compatible only on an exact match of category and species.
  2. No compatible visit → create one.
  3. One → join it.
  4. Several → join the earliest, and merge the others into it, unless any of them has `moved_by_user=1`; those stay separate.
  5. Recompute the visit:
     - `started_at` / `ended_at`
     - `confidence`: the maximum over its clips
     - `best_clip_id` / `best_frame_path`: from the clip with the most confident verdict (read from `clip.verdict_json`)
     - `subject`: `species` if any clip is sure, else the most common clip subject
     - the `guess` rows (rank 1–3): replaced with the 3 best species, confidences averaged over the visit's clips
  6. Set `species.first_seen_at` when it's NULL and the species is sure.
- Also produces `repo.visit_for_clip(conn, clip_id) -> int | None`.

- [ ] **Step 1: Write the failing tests:**
  - `test_clips_45s_apart_same_species_join`
  - `test_clips_75s_apart_split`
  - `test_different_species_split`
  - `test_unknown_clip_joins_neighbouring_visit`
  - `test_out_of_order_clip_bridges_two_visits` (Review Focus 4): recognise 0 s and 100 s first, then 50 s. The result is one visit with 3 clips.
  - `test_visit_moved_by_user_is_not_merged` (Review Focus 5)
  - `test_first_seen_set_once_for_sure_species_only`
  - `test_guesses_written_top3`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(library): group recognised clips into visits"`

### Task 7: Processor integration and backfill

**Files:**
- Modify: `src/fatball/ingest/processor.py`
- Modify: `src/fatball/cli.py`: build the `Detector` in `serve`. Missing model → log one warning, and pass `detector=None`.
- Modify: `src/fatball/demo.py`: the demo uses a `FakeDetector` and seeded examples, so `fatball demo` shows birds without the model.
- Test: `tests/ingest/test_processor.py`, `tests/test_demo.py`

**Interfaces:**
- Consumes: `Recognizer` (5), `assign_visit` (6).
- Produces:
  - `Processor.__init__(settings, conn, recognizer: Recognizer | None = None)`
  - `process_pending()` now:
    1. converts the downloaded clips (as before);
    2. recognises each one that converted, then calls `assign_visit` and sets `ready`;
    3. then recognises at most **one** clip that is `ready` with `recognized_at IS NULL` (the backfill), oldest `begin_at` first.
  - A recognition error sets `recognition_error`, leaves the clip `ready` (the video still plays) and logs. Retry clears it.
  - `recognizer is None`: clips go `ready` and stay unrecognised.
- Also produces:
  - `repo.clips_needing_recognition(conn, limit: int) -> list[Clip]`
  - `GET /api/status` gains `"recognition": {"pending": int, "errors": int, "model": bool}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_downloaded_clip_is_recognised_and_in_a_visit`
  - `test_backfill_does_one_clip_per_pass_oldest_first`
  - `test_recognition_error_keeps_clip_playable`
  - `test_missing_model_keeps_clips_ready_and_unrecognised` (Review Focus 1)
  - `test_status_reports_recognition_counts`
  - `test_demo_shows_a_bird_visit`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** `processor_loop` calls `qos.set_background_priority()` once, at thread start.
- [ ] **Step 4: Run all tests and lint.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(ingest): recognise after conversion; backfill old clips one at a time"`

### Task 8: Importing examples

**Files:**
- Modify: `src/fatball/cli.py` (add the subcommand `examples-import`)
- Modify: `src/fatball/library/repo.py`
- Test: `tests/test_cli.py`, `tests/library/test_repo.py`

**Interfaces:**
- Produces:
  - `fatball examples-import CSV`. The CSV has the columns `clip_id,label`, where `label` is:
    - an English or scientific catalog name, or
    - `dog`, `nothing`, `person`, or `skip`.
  - For each clip, it recognises the clip if needed, then labels its confident animal detections (`label_source='import'`). `person` and `skip` rows add no examples.
  - It prints `"N examples from M clips"`. Unknown names are listed, and the command exits 1 without writing anything.
  - `repo.label_detections(conn, clip_id: int, label: str, source: str) -> int`
  - `repo.unlabel_detections(conn, ids: list[int]) -> None`

- [ ] **Step 1: Write the failing tests:**
  - `test_import_labels_animal_detections`
  - `test_import_rejects_unknown_name_and_writes_nothing`
  - `test_import_person_and_skip_add_nothing`
  - `test_import_twice_is_idempotent`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(cli): import labelled examples from a CSV"`

### Task 9: Visit API with corrections and undo

**Files:**
- Modify: `src/fatball/api/app.py`
- Create: `src/fatball/library/corrections.py`
- Test: `tests/api/test_visits_api.py`

**Interfaces:**
- Consumes: `require_editor` (Plan 1), `visits` (6), `label_detections` / `unlabel_detections` (8).
- Produces:
  - `GET /api/visits?category=&species=&day=YYYY-MM-DD&cursor=&limit=`:
    - Visits newest first. Cursor = `started_at|id` of the last item (opaque base64 to the client).
    - Each item: `id`, `started_at`, `ended_at`, `category`, `species` `{scientific, name} | null`, `subject`, `confidence`, `is_favourite`, `best_frame_url`, `clip_count`.
  - `GET /api/visits/{id}`: the item fields, plus `clips` (Plan 1 clip shape) and `guesses` `[{scientific, name, confidence}]`.
  - `PATCH /api/visits/{id}`, editor only. Body `{species?: scientific | null, category?: str, is_favourite?: bool}`. Returns `{undo_token}`.
    - Changing the species also sets the category from the rules, unless a category is given.
    - Any species or category change sets `moved_by_user=1`, writes a `correction` row, and labels the visit's confident animal detections: with the species, or with `"nothing"` when the category is `other` and the species is null (`label_source='correction'`).
    - `before_json` stores the old visit fields and the ids of the detections the correction labelled.
  - `POST /api/undo/{token}`, editor only. Restores the fields, unlabels exactly those detections, deletes the correction row and the token. 404 when the token is unknown or older than 24 h.
  - `POST /api/retry/{clip_id}`, editor only. Clears `recognition_error` and `recognized_at`, so the backfill picks the clip up. 204.
  - `corrections.apply(conn, visit_id, change) -> str` (a token), `corrections.undo(conn, token) -> None`.

- [ ] **Step 1: Write the failing tests:**
  - `test_list_visits_filters_and_paginates`
  - `test_visit_detail_has_clips_and_guesses`
  - `test_patch_needs_editor` (403 from a LAN client without the cookie)
  - `test_patch_species_sets_category_and_labels_examples`
  - `test_patch_to_other_labels_nothing`
  - `test_undo_restores_visit`
  - `test_undo_removes_examples_added_by_the_correction` (Review Focus 3)
  - `test_undo_unknown_or_expired_token_404`
  - `test_retry_requeues_recognition`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all tests and lint.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(api): visits list and detail, corrections with undo, retry"`

### Task 10: Real-camera check and tuning (on the owner's Mac)

**Files:**
- Modify: `docs/spikes/2026-11-02-bird-recognition.md` (a "Plan 2 results" section)
- Modify: `README.md` ("What works today": recognition; the example import; the model export)
- Modify: `src/fatball/recognition/matcher.py` (constants only, if tuning changes them)

**Before running anything heavier than a few seconds, tell the owner and wait for their go-ahead.** Run at low priority and watch memory; stop if free memory falls under 15% (`memory_pressure`).

- [ ] **Step 1: Seed the examples.** Convert `local/spike/labels.csv` to the import format (`clip_id,label`):
  - great tit / blue tit / house sparrow → that species
  - dog → `dog`
  - empty → `nothing`
  - person → `person`
  - everything unsure → `skip`
  - Then run `fatball examples-import`.
- [ ] **Step 2: Measure leave-one-clip-out accuracy** on the 63 spike clips through the app's own code (`match(..., exclude_clip=id)`).
  - Expected: right section on at least 55 of 63, and right species on at least 13 of 17.
  - Retune `SURE_SHARE` only if that improves both numbers. Record before and after.
- [ ] **Step 3: Start `fatball serve`** from the Terminal app and let the backfill run.
  - Record the seconds per clip, the peak extra memory (`ps -o rss`, must be under 300 MB), and whether the Mac stays responsive. Ask the owner.
- [ ] **Step 4: End to end.** Ask the owner to wake the camera. Record the time from download to `recognized_at` (target: under 30 s, §11).
- [ ] **Step 5: Write the results into the spike doc and README.** No IPs, serials or footage.
- [ ] **Step 6: Commit.** `git commit -m "docs: Plan 2 results on the real camera"`

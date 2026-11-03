# Plan 4: the gallery, part 2 (videos, species, bulk, stats) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the phase-1 gallery. The owner gets the full menus (phone **Today · Videos · Birds · Stats · More**), the Videos feed, Birds › By species, Select with **Move to… / Download .zip** and Undo, Mac drag-and-drop and the card ⋯ menu, the Other filters with deleting empty clips, Stats with the busiest-times heatmap, and a Mac banner for new bird visits.

**Architecture:**
- The service gains bulk changes, deletion of empty clips, read-only queries for species periods, stats and the videos feed, streamed .zip downloads and a notifier thread. All SQL stays in `src/fatball/library/`; the API only shapes JSON.
- The gallery adds the Videos and Stats pages, a By species view and a species list under Birds, and a select mode, a filter row, drag-and-drop and a ⋯ menu on the existing `VisitList`.
- Plan 3's leftovers (`local/plan-3-ledger.md`, gitignored) are cleared first, in Tasks 1 and 7, so the new work builds on clean code.

**Tech Stack:** unchanged from Plan 3: Python 3.12, FastAPI, SQLite; Svelte 5, Vite, TypeScript, Vitest; Playwright with `@axe-core/playwright`. `zipfile` from the standard library, and `osascript` for the Mac banner. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-31-who-ate-the-fat-ball-design.md` (§6 step 5, §8 pages and Mac cards, §9, §10 API, §14 e2e list). Design references, local only (`design/` is untracked): `design/prototypes/project/Videos.dc.html`, `Stats.dc.html` and `Desktop.dc.html` (select bar, drag, ⋯ menu, Other filters, species cards), `design/prototypes/build_birds.py` (phone Birds with Select), and `robin.py` for icons.

## Rulings made while planning (cost if wrong in brackets)

- **R1 Bulk and drag moves don't teach.** A move by Select, drag or the ⋯ menu changes the category, marks the visit "Corrected by you" and records a correction, but labels no detections: "Other" could mean a dog, a person or an empty clip. Only the picker teaches, as in Plan 3. [Drag moves never improve recognition.]
- **R2 A deleted clip keeps its row.** Deleting an empty clip removes its media files and its visit, and sets `clip.deleted_at`. The row stays so the watcher never downloads it again from the SD card, and its detections stay because they may be labelled examples. [A slightly bigger database.]
- **R3 One migration, 005.** It adds `clip.deleted_at` and `visit.notified_at` together, so the owner's library upgrades once, with one backup. Existing visits get `notified_at = started_at`, so the first start doesn't send a flood of banners. [Task 3 adds a column that only Task 6 uses.]
- **R4 Zips are streamed, uncompressed.** Videos are already compressed. `POST` returns the size and a token, and `GET .../{token}` streams the file, so the browser downloads it with its own progress and "done" display. The shown size is the sum of the files ("about 14.2 MB"). [No in-app "done" message.]
- **R5 Periods are rolling.** "This week" is the last 7 days including today, "This month" the last 30 days, using the Mac's date. A species card is "New" when the species was first seen in the last 7 days. [Monday-morning counts look bigger than a calendar week.]
- **R6 The heatmap covers 6 am–8 pm.** It has seven 2-hour slots, Mon–Sun, over the last 4 weeks, birds only. Visits outside 6 am–8 pm count in the totals but not in the heatmap. "Busiest" is the slot with the most visits. [A dawn visitor at 5:50 is missing from the heatmap.]
- **R7 Videos feed.** It shows bird visits that have a web video, newest first. The filter chips are "All birds" plus the 4 species with the most visits in the last 30 days. Swiping left or up, or **Next clip**, goes forward; swiping right or down, or **Previous**, goes back. There is no wrap-around: **Next clip** is disabled on the last visit. Video autoplays muted, with native controls. A visit moved away by the picker stays in place until you move on. [The feed feels different from the prototype's loop.]
- **R8 Mac-only controls.** Drag-and-drop and the ⋯ menu are on cards only at ≥768 px wide and only for editors. Select works on every width; its Move and Delete buttons appear only for editors, while Download .zip is open to all (downloading is viewing). [iPad users drag less naturally than they tap.]
- **R9 Birds routes.** `/birds` is All visits, `/birds/species` is By species, and `/birds/species/<scientific name, URL-encoded>` is one species' visits. The period choice is kept for the session and defaults to **This week**. [A different default period.]
- **R10 Mac banner.** Birds only, sent at most once a minute, after a visit has had 90 s with no new clip. Body: "3 new visits: great tit, blue tit" (up to 3 names, then "and 2 more"); a new species gets its own banner, "New species: eurasian nuthatch". It is on by default and switched with `fatball notifications on|off`. There are no banners in demo mode. [Banners arrive about 2 minutes after the visit.]
- **R11 Screenshot tests run only in the `chromium` project**, at 1280×800 and 390×844, with snapshots made on the owner's Mac and committed. If the CI macOS runner renders differently, take its snapshots from the failed run's artifacts. [One round of snapshot updates.]

## Global Constraints

- Everything in Plan 3's Global Constraints still holds: the Robin colour values, Plus Jakarta Sans 400/500/600/800 and never 700, 11 px minimum, 44 px tap targets, contrast, `aria-current`/`aria-pressed`, dialogs that keep focus and close with Esc, Back = browser history, no real footage, workers 1, English only. The heatmap scale may also use `#E39A72` (spec §9).
- Wording, copied exactly:
  - **Lists:** "Select" / "Done", "Select all", "1 visit selected" / "3 visits selected", "Move to Birds" / "Move to Other animals" / "Move to Other", "Download .zip", "Download this day (.zip)".
  - **Birds:** "All visits", "By species", "This week", "This month", "All time", "42 visits" / "1 visit", "Last seen today 08:47", "New".
  - **Other:** "All", "Only dogs", "Empty clips", "Delete", "Delete 3 empty clips? This can't be undone.", "3 empty clips deleted".
  - **Videos:** "Videos", "3 of 12", "Favourite" / "Saved", "What is it?", "Download", "Previous", "Next clip".
  - **Stats:** "Stats", "Last 4 weeks", "Visits", "Species", "Busiest", "Busiest times", "Tap a square to see the number of visits", "Fewer", "More visits", "Visits per bird", "Tue 8–10 am · 12 visits".
  - **Move toasts:** "3 visits moved to Other · Undo" and, for one visit, "Great tit moved to Other · Undo".
  - **Zip:** "Download 3 visits (14.2 MB)?", "Downloading 3 visits (14.2 MB)…".
- Slot labels, exactly: `6–8 am`, `8–10 am`, `10 am–12 pm`, `12–2 pm`, `2–4 pm`, `4–6 pm`, `6–8 pm`. Column heads: `6am 8am 10am 12pm 2pm 4pm 6pm`. Rows: `Mon … Sun`.
- Menus: the phone bar is **Today · Videos · Birds · Stats · More**. The side menu is Today, Videos, Favourites, the Sorted-into box, Stats, App status, with the camera status at the bottom. Each new page adds its own tab in its own task, so there is never a dead tab.
- On a locked device, Move, Delete, drag and ⋯ are **not rendered**.
- **8 GB Mac:** a zip is never built in memory (it streams in 1 MB chunks). Stats queries run in SQL, not by loading every visit.
- The real library (`~/Library/Application Support/WhoAteTheFatBall/`) is never touched by tests. Port 8080 may be the owner's running app.

## Review Focus

1. **A deleted empty clip must never come back.** The watcher sees its SD-card file again, and must neither download it again nor recognise it again. Pinned in Task 3 (`known_clip_keys` still holds it; `clips_needing_recognition` skips it).
2. **Undoing a bulk move of a mixed selection** (one Great tit favourite, one Unknown bird, one already in the target) restores each visit exactly: category, species, subject, favourite and "Corrected by you". Pinned in Task 2.
3. **A zip of 500 visits, some with a media file missing on disk,** streams without loading files into memory, skips the missing ones, and refuses 501 visits with a clear message. Pinned in Task 5.
4. **The Videos feed at its edges:** a bird visit whose web video isn't ready never appears; **Next clip** on the last visit loads the next page or is disabled at the very end. Pinned in Tasks 4 and 12.
5. **Stats across local time:** a visit stored at 07:59 falls in `6–8 am` on its local weekday, read from the stored local text, never converted to UTC. Pinned in Task 4.

---

## File structure

```text
src/fatball/
  library/
    migrations/005_deleted_and_notified.sql   Task 3
    corrections.py     + apply_many, bulk undo (Task 2)
    cleanup.py         delete_empty_visits (Task 3)
    stats.py           species_for_period, stats, videos feed queries (Task 4)
    zips.py            plan_zip, stream_zip (Task 5)
    repo.py            public row helpers (Task 1), `only=` filter (Task 3), notifier queries (Task 6)
  notify.py            notifier loop, message text, osascript sender (Task 6)
  api/app.py           + bulk, delete, species?period, stats, videos, zip endpoints
  cli.py               + notifier thread in serve, `notifications on|off`
web/src/
  lib/       api.ts (+types), format.ts (+sizeText, slot labels), select.ts (selection store), zip.ts
  components/ SelectBar, CardMenu, ZipConfirm, FilterChips, SpeciesCard, Heatmap
  pages/     Videos, Stats, Species (By species), VisitList (+select, filters, species), App routes
web/tests/   unit tests per task; e2e: select, drag, videos, downloads, stats, screens
```

---

### Task 1: Plan 3's server leftovers

**Files:**
- Modify: `src/fatball/library/repo.py`, `today.py`, `corrections.py`, `src/fatball/api/app.py`
- Test: `tests/library/test_today.py`, `tests/library/test_repo.py`, `tests/api/test_static.py`, `tests/api/test_today_api.py`

**Interfaces:**
- Produces: `repo.iso(dt) -> str` and `repo.row_to_clip(row) -> Clip` (public names for `_iso` and `_clip`, with every import updated); `repo.list_visits(conn, limit: int | None, ...)` where `None` means no limit; a `now` field (the server's ISO time with offset) in `/api/status` and `/api/today`.

- [ ] **Step 1: Write the failing tests**
  - `test_new_species_ignores_first_seen_outside_any_visit`: a species whose `first_seen_at` is before every one of its visits' windows gives `new_species(conn) is None`.
  - `test_champion_photo_comes_from_most_confident_visit`: of 3 Great tit visits today with confidences 0.6, 0.9 and 0.7, `champion(...)["best_frame_path"]` is the 0.9 visit's path.
  - `test_species_overview_orders_mammals_after_birds_by_visits`: squirrel (2 visits) comes before dog (1 visit), and both come after every bird.
  - `test_media_rejects_traversal`: `GET /media/../library.sqlite` gives 404, and the body doesn't start with `SQLite`.
  - `test_media_rejects_symlink_outside`: a symlink in `media/` pointing at `tmp_path/secret.txt` gives 404.
  - `test_unknown_post_is_json_404`: `POST /nowhere` and `POST /api/nowhere` give 404 with `{"detail": "Not Found"}`.
  - `test_status_and_today_report_server_now`: with a fixed clock of 2026-11-02 10:00, both have `now == "2026-11-02T10:00:00+01:00"`.
- [ ] **Step 2: Run them and see them fail:** `uv run pytest tests/library tests/api -q`
- [ ] **Step 3: Implement**
  - Rename the helpers.
  - Replace the `"1"` trick in `today.checking` with a plain boolean condition.
  - `list_visits` takes `limit=None`, and `/api/today` uses it.
  - Any non-GET to a path outside `/api` and `/media` returns JSON 404.
  - Add `now`.
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check`. Everything passes.
- [ ] **Step 5: Commit:** `refactor(library,api): Plan 3 leftovers on the server`

### Task 2: Bulk move and favourite, with one Undo

**Files:**
- Modify: `src/fatball/library/corrections.py`, `src/fatball/api/app.py`
- Test: `tests/library/test_corrections_bulk.py`, `tests/api/test_bulk_api.py`

**Interfaces:**
- Consumes: `corrections.Change`, `apply`, `undo`, the `undo` table (`token, visit_id, before_json, created_at`).
- Produces:
  - `Change.teach: bool = True`. When False, no detections are labelled and the first sighting is unchanged (R1).
  - `corrections.apply_many(conn, visit_ids: list[int], change: Change, now) -> tuple[str, int]` returns `(undo_token, changed_count)`.
    - It allows only `category` and/or `is_favourite`; a `species` raises `InvalidChange`.
    - Visits already matching the change are skipped.
    - An unknown id raises `VisitNotFound`, and nothing changes.
    - The undo row stores `visit_id` = the first id and `before_json = {"bulk": [{"visit_id": id, "before": {...}}, ...]}`.
  - `undo` restores every item of a bulk token in one transaction.
  - `POST /api/visits/bulk` (editor only), body `{"visit_ids": [int, ...] (1–500), "category"?: Category, "is_favourite"?: bool}`, returns `{"undo_token": str, "changed": int}`. It gives 404 for an unknown id and 422 for no change field or more than 500 ids.

- [ ] **Step 1: Write the failing tests**
  - `test_bulk_move_then_undo_restores_each_visit` (Review Focus 2):
    - Visits: A is a Great tit favourite in birds; B is an Unknown bird in birds; C is already in other.
    - `apply_many([A, B, C], Change(category="other", teach=False))` returns changed = 2.
    - A and B are in other with `moved_by_user = 1`, and C is untouched.
    - After `undo(token)`, A, B and C equal their snapshots taken before (category, species_id, subject, is_favourite, moved_by_user).
  - `test_bulk_move_does_not_label_detections`: the labels of A's detections are unchanged after the move.
  - `test_bulk_rejects_species`: `Change(species="Parus major")` raises `InvalidChange`.
  - `test_bulk_unknown_id_changes_nothing`: with ids `[A, 999]`, `VisitNotFound` is raised and A is unchanged.
  - API:
    - `test_bulk_needs_editor`: from a non-local client without the cookie, the endpoint gives 403.
    - `test_bulk_returns_token_and_count`.
    - `test_bulk_501_ids_is_422`.
- [ ] **Step 2: Run them and see them fail:** `uv run pytest tests/library/test_corrections_bulk.py tests/api/test_bulk_api.py -q`
- [ ] **Step 3: Implement.** Move `apply`'s body into `_apply_in_tx(conn, visit_id, change, now) -> dict | None` (the "before" snapshot, or None when nothing changed). Then `apply` and `apply_many` each run it inside one `begin_immediate` transaction. `_restore` is reused per item.
- [ ] **Step 4: Run** `uv run pytest -q`. Everything passes, including the Plan 2 correction tests, unchanged.
- [ ] **Step 5: Commit:** `feat(library,api): bulk move and favourite with one Undo`

### Task 3: Other filters and deleting empty clips

**Files:**
- Create: `src/fatball/library/migrations/005_deleted_and_notified.sql`, `src/fatball/library/cleanup.py`
- Modify: `src/fatball/library/repo.py`, `today.py`, `src/fatball/api/app.py`, `src/fatball/library/schema.sql` (only if new libraries are created from it; follow how migration 004 was added)
- Test: `tests/library/test_migration_005.py`, `tests/library/test_cleanup.py`, `tests/api/test_delete_api.py`, `tests/api/test_visits_api.py`

**Interfaces:**
- Produces:
  - Schema v5: `clip.deleted_at TEXT`, `visit.notified_at TEXT` (existing visits get `notified_at = started_at`), backup `library.sqlite.v4.bak` (R3).
  - An empty clip is a visit with `category = 'other' AND subject = 'nothing'`; a dog is one with species `DOG`.
  - `repo.list_visits(..., only: Literal["dogs", "empty"] | None = None)`, and `GET /api/visits?category=other&only=dogs|empty`, returning 422 when `only` is used with any other category.
  - `cleanup.delete_empty_visits(conn, media_dir: Path, visit_ids: list[int], now) -> int`, in one transaction:
    - It raises `NotEmpty` if any id is not an empty clip, and `VisitNotFound` for an unknown id; in both cases nothing changes.
    - For each visit, it deletes the media files of its clips (raw, original, web, poster, preview) and its `best_frame_path`, skipping files that are already gone.
    - It sets the clips' paths to NULL and their `deleted_at` to now.
    - It deletes the visit's `visit_clip`, `guess`, `undo` and `correction` rows and the visit itself.
    - It keeps the detections and the clip rows (R2).
  - Every clip query skips `deleted_at IS NOT NULL`, except `known_clip_keys` and the duplicate check in `add_clip`.
  - `POST /api/visits/delete` (editor only), body `{"visit_ids": [...] (1–500)}`, returns `{"deleted": n}`. It gives 409 `{"detail": "Only empty clips can be deleted"}` and 404 for an unknown id.

- [ ] **Step 1: Write the failing tests**
  - `test_migration_005_adds_columns_and_marks_old_visits_notified`, plus `.v4.bak` existing afterwards.
  - `test_only_dogs_and_only_empty`, on a seed with a dog, an empty clip and a person in Other.
  - `test_delete_removes_files_and_visit_but_keeps_clip_row`.
  - `test_deleted_clip_is_never_fetched_or_recognised_again` (Review Focus 1): after deletion, `known_clip_keys(day)` contains the clip's `(sd_path, begin_at)`, and `clips_needing_recognition`, `list_clips` and `today.checking`/`failed` don't contain it.
  - `test_delete_refuses_a_bird_visit_and_changes_nothing`.
  - `test_delete_keeps_labelled_detections`.
  - API: `test_delete_needs_editor`, `test_delete_409_for_bird`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement**, following migration 004's pattern (schema version bump, backup).
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check`.
- [ ] **Step 5: Commit:** `feat(library,api): Other filters and deleting empty clips`

### Task 4: Species by period, Stats and the Videos feed (read-only queries)

**Files:**
- Create: `src/fatball/library/stats.py`
- Modify: `src/fatball/api/app.py`
- Test: `tests/library/test_stats.py`, `tests/api/test_stats_api.py`

**Interfaces:**
- Produces:
  - `stats.SLOTS = ["6–8 am", "8–10 am", "10 am–12 pm", "12–2 pm", "2–4 pm", "4–6 pm", "6–8 pm"]`, starting at hours `[6, 8, 10, 12, 14, 16, 18]`.
  - `stats.species_for_period(conn, today: date, period: Literal["week", "month", "all"]) -> list[dict]`:
    - Birds with at least one visit in the period, by visits descending, then name.
    - Keys: `scientific, name, visits` (in the period), `last_seen_at` (all time), `first_seen_at`, `is_new` (first seen in the last 7 days), `photo_url` (best frame of the species' most confident visit in the period, or None).
  - `stats.summary(conn, today: date, weeks: int) -> dict`, birds only, over the window of the last `weeks*7` days including today:
    - `{"weeks": 4, "visits": int, "species": int, "busiest": str | None, "slots": SLOTS, "heatmap": [{"day": "Mon", "cells": [int]*7}, ...7 rows Mon..Sun], "per_species": [{"scientific", "name", "visits"}]}`.
    - Weekday and hour come from the stored local text (`started_at[:10]` and `started_at[11:13]`). Hours outside 6–20 aren't in the heatmap (R6). `busiest` is the label of the slot whose column total is largest.
  - `stats.videos(conn, limit, after, species: str | None) -> list[Row]`: bird visits whose best clip (or first clip with one) has a `web_path`, newest first, with `video_path`, `video_clip_id` and the usual visit columns.
  - `stats.top_species(conn, today, n=4) -> list[dict]`: `{scientific, name}`, the most visits in the last 30 days.
  - Endpoints:
    - `GET /api/species?period=week|month|all` returns the period view. Without `period` it is unchanged, because the picker uses it.
    - `GET /api/stats?weeks=4` (1–52) returns `summary`.
    - `GET /api/videos?species=&cursor=&limit=` returns `{"items": [visit json + "video_url", "video_clip_id"], "next_cursor", "total", "filters": top_species}`.

- [ ] **Step 1: Write the failing tests**
  - `test_heatmap_uses_local_wall_clock` (Review Focus 5): a visit stored `2026-11-02T07:59:00+01:00` (a Monday) counts in row `Mon`, cell 0 (`6–8 am`), and one at `05:50` counts in `visits` but in no cell.
  - `test_busiest_is_largest_slot_column`.
  - `test_stats_birds_only_and_window`: a dog visit and a 29-day-old bird visit are excluded when `weeks=4`.
  - `test_species_week_is_rolling_7_days`: a visit 6 days ago counts, one 7 days ago doesn't.
  - `test_species_is_new_within_7_days`.
  - `test_videos_skip_visits_without_web_video` (Review Focus 4).
  - `test_videos_species_filter_and_total`.
  - `test_top_species_last_30_days`.
  - API shape tests for the three endpoints, plus `test_species_without_period_unchanged`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** with SQL `GROUP BY` (no Python loops over every visit). Use the existing cursor helpers for `/api/videos`.
- [ ] **Step 4: Run** `uv run pytest -q`.
- [ ] **Step 5: Commit:** `feat(library,api): species periods, stats and the videos feed`

### Task 5: Downloading a .zip

**Files:**
- Create: `src/fatball/library/zips.py`
- Modify: `src/fatball/api/app.py`
- Test: `tests/library/test_zips.py`, `tests/api/test_zip_api.py`

**Interfaces:**
- Produces:
  - `zips.MAX_VISITS = 500`.
  - `zips.plan_zip(conn, media_dir, *, visit_ids: list[int] | None = None, day: date | None = None, category: str | None = None, favourite: bool | None = None) -> ZipPlan`:
    - `ZipPlan(entries: list[tuple[str, Path]], size_bytes: int, visits: int, filename: str)`.
    - Entries are each clip's web MP4 and the visit's best-frame JPG, named `"2026-11-02 09-12 Great tit.mp4"`, with `" (2)"` etc. for a visit's further clips and `.jpg` for the photo.
    - Labels: the species name capitalised, otherwise "Unknown bird" (birds), "Other animal", "Dog" or "Empty clip".
    - Files missing on disk are skipped.
    - `filename` is `"fat-ball-2026-11-02.zip"` for a day, otherwise `"fat-ball-3-visits.zip"`.
    - It raises `TooMany` above 500 visits and `NothingToDownload` when no file exists.
  - `zips.stream_zip(plan) -> Iterator[bytes]` uses `ZIP_STORED`, writes to a non-seekable sink and reads files in 1 MB chunks.
  - `POST /api/downloads/zip` (open to all), body `{"visit_ids"?: [...]} | {"day": "YYYY-MM-DD", "category"?: Category, "favourite"?: true}`, returns `{"token", "size_bytes", "visits", "files", "filename"}`. It gives 422 for too many visits ("Too many visits for one .zip (max 500)") and 404 when there is nothing to download.
  - `GET /api/downloads/zip/{token}` streams with `Content-Disposition: attachment; filename="..."`.
    - Tokens are kept in memory for 10 minutes, at most 20; an unknown or expired token gives 404.
    - A token can be used again within its 10 minutes, because browsers sometimes retry.

- [ ] **Step 1: Write the failing tests**
  - `test_plan_names_and_skips_missing_files` (Review Focus 3, part).
  - `test_plan_refuses_501_visits` (Review Focus 3, part).
  - `test_stream_zip_is_valid_and_chunked`: a generated 3 MB file comes out in more than one chunk, and `zipfile.ZipFile(BytesIO(b"".join(chunks))).testzip() is None`.
  - `test_day_zip_for_category`.
  - API: `test_zip_round_trip`, `test_zip_token_expires` (fixed clock + 11 min), `test_zip_open_without_pin`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** The stream wraps `zipfile.ZipFile(sink, "w", ZIP_STORED)`, where the sink is a small writer collecting bytes that the generator yields after each chunk.
- [ ] **Step 4: Run** `uv run pytest -q`.
- [ ] **Step 5: Commit:** `feat(library,api): streamed .zip downloads with the size first`

### Task 6: The Mac banner notifier

**Files:**
- Create: `src/fatball/notify.py`
- Modify: `src/fatball/library/repo.py`, `src/fatball/cli.py`, `README.md` (one line on `fatball notifications`)
- Test: `tests/test_notify.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `visit.notified_at` (Task 3).
- Produces:
  - `repo.unnotified_bird_visits(conn, settled_before: datetime) -> list[Row]` returns bird visits with `notified_at IS NULL` and `ended_at <= settled_before`, oldest first, with `species_name` and `is_new_species` (the species' `first_seen_at` lies within the visit's start and end).
  - `repo.mark_notified(conn, ids, now) -> None`.
  - `notify.messages(rows) -> list[str]` (R10):
    - `["3 new visits: great tit, blue tit"]` for 3 visits of 2 species; `"1 new visit: unknown bird"` for one Unknown bird.
    - More than 3 names give `"…, robin and 2 more"`.
    - Each new species adds `"New species: eurasian nuthatch"`.
  - `notify.send_banner(title, body)` runs `osascript` with `on run argv … display notification (item 2 of argv) with title (item 1 of argv)` and the text passed as arguments (never put into the script), with a 10 s timeout. Failures are logged, never raised.
  - `notify.notifier_loop(conn, stop: threading.Event, now: Callable[[], datetime], send=send_banner, interval_s=60)`:
    - Each pass checks the `notifications` setting (default `"on"`).
    - Then, with `settled_before = now() - 90 s`, it sends one banner per message with the title "Who Ate the Fat Ball?" and marks the visits notified, even when the setting is off, so turning it back on doesn't flood.
  - `serve` starts it on its own connection; `run_demo` doesn't.
  - `fatball notifications on|off` sets the setting and prints `Mac banners are on.` / `Mac banners are off.`; with no argument it prints the current state.

- [ ] **Step 1: Write the failing tests**
  - `test_messages_group_and_name`, `test_messages_new_species_separate`, `test_messages_more_than_three_names`.
  - `test_loop_waits_until_settled`: a visit that ended 30 s ago isn't sent, and after 90 s it is.
  - `test_loop_off_marks_without_sending`.
  - `test_send_banner_passes_text_as_arguments` (monkeypatch `subprocess.run`, assert the body isn't inside the `-e` script).
  - `test_cli_notifications_toggle`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check`.
- [ ] **Step 5: Commit:** `feat: Mac banner for new bird visits`

### Task 7: Plan 3's gallery leftovers

**Files:**
- Modify: `web/src/lib/{api,format,session,listCache}.ts`, `web/src/components/{CameraStatus,VisitCard,Icon,Toast,Picker}.svelte`, `web/src/pages/{Today,Visit,VisitList,More,AppStatus}.svelte`, `web/public/sw.js`, `web/tests/e2e/*.spec.ts`
- Test: matching `web/tests/*.test.ts`

**Interfaces:**
- Consumes: `now` from `/api/status` and `/api/today` (Task 1).
- Produces:
  - `format.minutesAgo(at: string, serverNow: string, fetchedAt: number, nowMs: number) -> number`: "N min ago" counts from the server's clock plus the time since the response arrived, never the browser's clock.
  - `api.ts` exports `VisitDetail` and `Guess` (moved from `Visit.svelte`).
  - `VisitCard` gains `pending?: boolean` (the "Checking who it is…" card), so Today's duplicate markup goes.
  - The Favourites and App status icons move into `Icon` (`Star`, `Camera`).
  - The phone bar's height is the CSS variable `--nav-phone-h`, used by Toast instead of `100px`.

- [ ] **Step 1: Write the failing tests** (Vitest), one per leftover:
  - `cameraStatus` for "ok" seen 90 min ago and "asleep" seen yesterday (shows "since yesterday 18:40").
  - The minutes come from server time.
  - The Visit Download menu isn't rendered when there's no video and no photo.
  - `onEnded` skips clips that aren't ready.
  - The failed-PATCH toast reads `NETWORK_TEXT`.
  - The Visit time line shows once `/api/status` fails and `/api/visits/{id}` succeeds (uses `day` from Today's cache or the visit's own date).
  - An undo network failure keeps the Undo button.
  - VisitList's first-page failure shows "Couldn't load visits. Check the Wi-Fi and try again." with **Try again**; VisitList with `/api/status` failing still renders, with day headings from the dates.
  - More's camera text updates each 30 s.
  - A 403 in the Picker sets `canEdit` false.
  - AppStatus shows the waiting count once.
  - "Or maybe" is hidden on a corrected visit.
  - `sw.js` caches only HTML navigations under `/` and keeps one `/api|/media` check.
- [ ] **Step 2: Run them and see them fail:** `npm --prefix web test -- --run`
- [ ] **Step 3: Implement**, and fix the e2e leftovers:
  - Specs that change data call `reseed` in `beforeEach`.
  - The unlock test asserts the return to `/more`.
  - More doesn't flash its h1 before the wide-layout redirect.
- [ ] **Step 4: Run** `npm --prefix web test -- --run && npm --prefix web run check`, then the Playwright `chromium` project (`cd web && npx playwright test --project=chromium`).
- [ ] **Step 5: Commit:** `refactor(gallery): Plan 3 leftovers`

### Task 8: Select, Move to… and Download .zip on the lists

**Files:**
- Create: `web/src/lib/select.ts`, `web/src/lib/zip.ts`, `web/src/components/SelectBar.svelte`, `web/src/components/ZipConfirm.svelte`
- Modify: `web/src/pages/VisitList.svelte`, `web/src/components/VisitCard.svelte`, `web/src/lib/{api,format}.ts`
- Test: `web/tests/select.test.ts`, `web/tests/zip.test.ts`, `web/tests/e2e/select.spec.ts`

**Interfaces:**
- Consumes: `POST /api/visits/bulk` (Task 2), `POST /api/downloads/zip` + `GET …/{token}` (Task 5).
- Produces:
  - `format.sizeText(bytes) -> string`: `"820 KB"`, `"14.2 MB"` (1 decimal from 1 MB), `"1.3 GB"`.
  - `select.ts` holds a store `{ on: boolean, ids: Set<number> }` with `toggle(id)`, `selectAll(ids)`, `clear()`; it clears when the route changes.
  - `zip.ts`: `askZip(body) -> Promise<{token, size_bytes, visits, filename}>` and `startDownload(token, filename)`, which clicks a temporary `<a download>` pointing at the GET url.
  - `<ZipConfirm>` is a dialog: "Download 3 visits (14.2 MB)?" with **Download** and **Cancel**. Download starts it and shows the toast "Downloading 3 visits (14.2 MB)…".
  - `VisitCard` gains `selecting`, `selected` and `onselect` props:
    - In select mode the card is a checkbox (44×44 box top-left, `aria-label="Select Great tit at 09:12"`) with a 3 px `--robin` ring when selected, and the link is inert.
  - `VisitList` header:
    - **Select** / **Done** (`aria-pressed`), and in select mode **Select all** (all loaded visits).
    - At ≥768 px each day heading has **Download this day (.zip)**, which sends `{day, category}` or `{day, favourite: true}`.
  - `<SelectBar>` is sticky: "3 visits selected", **Move to …** for the two other categories (editors only, not on Favourites, where it offers all three), and **Download .zip**. After a move: the toast "3 visits moved to Other · Undo" (or the single visit's name), `noteChanged()`, and select mode closes.

- [ ] **Step 1: Write the failing tests:**
  - `sizeText` cases.
  - The select store.
  - SelectBar hides Move when locked.
  - The toast text for 1 and 3 visits.
  - ZipConfirm text.
  - e2e `select.spec.ts` (spec §14: "moving a visit to Other from Birds Select, then undoing it"): on Birds tap Select, select 2 cards, Move to Other, the toast shows, Other's count is +2, then Undo puts them back. Download .zip on 1 selected card gives a `download` event whose `suggestedFilename()` is `fat-ball-1-visits.zip`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement**, matching `Desktop.dc.html` (select bar dark `--ink` with white text, buttons with a 1 px `rgba(255,255,255,0.45)` border, and Download .zip as a white button with `--robin-dark` text) and `build_birds.py` for the phone.
- [ ] **Step 4: Run** the unit tests, `svelte-check`, and Playwright `chromium` for `select.spec.ts`.
- [ ] **Step 5: Commit:** `feat(gallery): Select, Move to… and Download .zip`

### Task 9: Other filters and deleting empty clips in the gallery

**Files:**
- Create: `web/src/components/FilterChips.svelte`
- Modify: `web/src/pages/VisitList.svelte`, `web/src/components/SelectBar.svelte`, `web/src/lib/listCache.ts`
- Test: `web/tests/other.test.ts`, `web/tests/e2e/other.spec.ts`

**Interfaces:**
- Consumes: `?only=dogs|empty` and `POST /api/visits/delete` (Task 3).
- Produces:
  - `<FilterChips options={["All","Only dogs","Empty clips"]} value onchange>` uses `role="group"` and `aria-label="Show"`, with `aria-pressed` buttons (the selected one has a 1.5 px `--robin-dark` border, `--robin-dark` text and weight 600; the others a 1 px `--line-strong` border and `--ink-2` text). It is reused by Task 11 (periods) and Task 12 (species chips, dark variant `tone="dark"`).
  - The Other page shows the chips under the title. The chosen filter is part of the list-cache key (`other:empty`).
  - With **Empty clips** chosen and the device unlocked, the SelectBar adds **Delete** → a confirm dialog "Delete 3 empty clips? This can't be undone." with **Delete** (`--robin` fill) and **Cancel** → the toast "3 empty clips deleted", and `noteChanged()`.
  - The empty text for each filter: All "Nothing here: no dogs, people or empty clips", Only dogs "No dogs here", Empty clips "No empty clips".

- [ ] **Step 1: Write the failing tests:**
  - The chips' `aria-pressed`.
  - Delete isn't rendered when locked, or when the filter isn't Empty clips.
  - e2e `other.spec.ts`: Only dogs shows the dog and not the empty clip; Empty clips → Select all → Delete → confirm → "1 empty clip deleted", and the list shows "No empty clips". The spec reseeds in `beforeEach`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the unit tests, `svelte-check`, and Playwright `chromium` for `other.spec.ts`.
- [ ] **Step 5: Commit:** `feat(gallery): Other filters and deleting empty clips`

### Task 10: Mac cards: drag onto a category, and the ⋯ menu

**Files:**
- Create: `web/src/components/CardMenu.svelte`, `web/src/lib/drag.ts`
- Modify: `web/src/components/VisitCard.svelte`, `web/src/components/SortedInto.svelte`, `web/src/components/NavSide.svelte`
- Test: `web/tests/cardmenu.test.ts`, `web/tests/e2e/drag.spec.ts`

**Interfaces:**
- Consumes: `POST /api/visits/bulk` with one id (Task 2), and the toast wording from Task 8.
- Produces:
  - `drag.ts` exports `dragged` (a store of the visit being dragged, or null) and `moveVisits(ids, category, names)`, shared with SelectBar.
  - At ≥768 px for editors (R8), `VisitCard` is `draggable` and has a ⋯ button (36 px circle, top-right, `aria-label="More actions for Great tit"`, `aria-haspopup="menu"`, `aria-expanded`) that opens `<CardMenu>`:
    - `role="menu"` with the heading "Move to" and `role="menuitem"` entries for the two other categories, each with its dot.
    - Arrow keys move between items, Enter chooses, Esc closes and returns focus to ⋯.
  - `SortedInto` rows are drop targets while a card is being dragged:
    - The hovered row gets the `--robin-tint` background and a 2 px dashed `--robin` border.
    - Dropping on the visit's own category does nothing.
  - The dragged card's opacity is 0.45. There is no visible move control under the photo (spec §8).

- [ ] **Step 1: Write the failing tests:**
  - CardMenu keyboard (arrows, Enter, Esc returns focus).
  - The ⋯ button isn't rendered when locked or under 768 px.
  - e2e `drag.spec.ts` (spec §14: "dragging a card onto Other animals on the Mac, and the same move done with the keyboard"), with `chromium` at 1280×800:
    - `dragTo` a Birds card onto "Other animals" in the side menu: the toast "… moved to Other animals · Undo", and the count goes up.
    - Then a keyboard-only move: Tab to ⋯, Enter, ArrowDown, Enter.
    - Reseed in `beforeEach`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement**, with HTML5 drag and drop (`dataTransfer.setData("text/plain", id)` inside try/catch, as in the prototype).
- [ ] **Step 4: Run** the unit tests, `svelte-check`, and Playwright `chromium` for `drag.spec.ts`.
- [ ] **Step 5: Commit:** `feat(gallery): drag cards onto a category, and the ⋯ menu`

### Task 11: Birds › By species, and one species' visits

**Files:**
- Create: `web/src/pages/Species.svelte`, `web/src/components/SpeciesCard.svelte`
- Modify: `web/src/lib/router.ts`, `web/src/App.svelte`, `web/src/pages/VisitList.svelte`, `web/src/lib/session.ts`
- Test: `web/tests/species.test.ts`, `web/tests/router.test.ts`, `web/tests/e2e/species.spec.ts`

**Interfaces:**
- Consumes: `GET /api/species?period=` (Task 4), `GET /api/visits?species=`, and `FilterChips` (Task 9).
- Produces:
  - Routes (R9): `birds-species` for `/birds/species`, and `species` for `/birds/species/:scientific` (decoded param).
  - `session.period` is a store with `"week" | "month" | "all"`, default `"week"`.
  - The Birds page top has a two-part switch, **All visits | By species** (`role="group"`, `aria-pressed`, the active part white with a 1 px `#C9BBA8` border), which navigates between `/birds` and `/birds/species` with `replace`.
  - `Species.svelte` (By species):
    - Period chips (This week · This month · All time), shown only in this view.
    - A grid of `SpeciesCard`s (photo 120 px, "New" tag in `--robin`, name 600, the count `42` at weight 800 24 px with " visits" at 12 px, and "Last seen today 08:47" using `whenText`).
    - The subtitle "6 species · this week".
    - Empty: "No birds this week".
  - A card links to `/birds/species/<encoded>`, which is a `VisitList` with `kind="birds"` and the `species` filter, titled with the species name; Back returns to By species. The list cache key is `species:<scientific>`.

- [ ] **Step 1: Write the failing tests:**
  - `matchRoute("/birds/species/Parus%20major")` gives `{name: "species", params: {scientific: "Parus major"}}`.
  - The switch's `aria-pressed`.
  - Period chips aren't rendered on All visits.
  - The "1 visit" / "42 visits" plural.
  - e2e `species.spec.ts`: Birds → By species → This week shows a Great tit card whose count matches `GET /api/species?period=week` → open it → only Great tit visits → Back → By species again.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the unit tests, `svelte-check`, and Playwright `chromium`.
- [ ] **Step 5: Commit:** `feat(gallery): Birds by species with a period filter`

### Task 12: The Videos feed

**Files:**
- Create: `web/src/pages/Videos.svelte`
- Modify: `web/src/lib/router.ts`, `web/src/App.svelte`, `web/src/components/NavPhone.svelte`, `web/src/components/NavSide.svelte`, `web/src/lib/api.ts`
- Test: `web/tests/videos.test.ts`, `web/tests/e2e/videos.spec.ts`

**Interfaces:**
- Consumes: `GET /api/videos` (Task 4), `Picker` (Plan 3), `PATCH` for favourites, `FilterChips tone="dark"`.
- Produces:
  - The route `videos` at `/videos`.
  - The phone bar gains **Videos** (it now has 4 tabs; grid `repeat(4, …)` until Task 13 makes 5). The side menu gains Videos after Today.
  - `Videos.svelte` (R7), matching `Videos.dc.html`:
    - A dark full-height page (`--ink` background, white text).
    - A header overlay `rgba(46,33,22,0.6)` with "Videos", the position "3 of 12" (from `total`), and chips "All birds" plus `filters`.
    - The video (`playsinline muted autoplay controls`, the poster as a placeholder).
    - Right-side actions: **Favourite**/**Saved** (`aria-pressed`, editors only), **What is it?** (editors only), **Download** (the video's `web` URL with `download`).
    - At the bottom: the name, the time line plus "94% sure", and **Previous** / **Next clip**.
  - Swipes use pointer events: a horizontal or vertical move over 50 px. Keyboard: ArrowRight/ArrowLeft.
  - Next on the last loaded item fetches `next_cursor` first; at the end it is disabled (Review Focus 4).
  - The picker opens on top; the feed keeps its index. After a change the item shows its new name, or "moved by you", until you move on.
  - At ≥768 px the feed sits inside `main` with the video at most 960 px wide.

- [ ] **Step 1: Write the failing tests:**
  - Position text.
  - Next disabled at the end with no cursor.
  - Next fetches the next page when there is a cursor.
  - A swipe over 50 px moves, and one under doesn't.
  - Favourite and What is it? aren't rendered when locked.
  - e2e `videos.spec.ts` (spec §14: "the Videos picker used without leaving the feed"):
    - Open Videos, then Next clip: the position reads "2 of N".
    - What is it? → Blue tit: the toast "Changed to Blue tit", the URL is still `/videos`, and the position is still "2 of N".
    - Undo.
    - Reseed in `beforeEach`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the unit tests, `svelte-check`, and Playwright `chromium`.
- [ ] **Step 5: Commit:** `feat(gallery): the Videos feed`

### Task 13: Stats and the busiest-times heatmap

**Files:**
- Create: `web/src/pages/Stats.svelte`, `web/src/components/Heatmap.svelte`
- Modify: `web/src/lib/router.ts`, `web/src/App.svelte`, `NavPhone.svelte`, `NavSide.svelte`, `web/src/lib/format.ts`
- Test: `web/tests/stats.test.ts`, `web/tests/e2e/stats.spec.ts`

**Interfaces:**
- Consumes: `GET /api/stats?weeks=4` (Task 4).
- Produces:
  - The route `stats` at `/stats`. The phone bar becomes the full **Today · Videos · Birds · Stats · More** (`repeat(5, …)`); the side menu gains Stats just above App status.
  - `format.heatLevel(n, max) -> 0|1|2|3|4`: 0 when n = 0, otherwise `Math.ceil(4 * n / max)`. Colours by level: `#F1E8DC` (with a `#C9BBA8` border), `#F7E1D3`, `#E39A72`, `#B4491A`, `#8F3712`.
  - `format.cellText(day, slot, n) -> string`: "Tue 8–10 am · 12 visits" or "· 1 visit".
  - `Stats.svelte`, matching `Stats.dc.html`:
    - "Stats" with "Last 4 weeks".
    - Three tiles: Visits, Species, Busiest ("—" when null).
    - The "Busiest times" section with `<Heatmap>`: 7×7 buttons (32 px high, 6 px radius, `aria-label` = the cell text, `aria-pressed` when chosen, a 2 px `--ink` ring), a `role="status"` line that defaults to "Tap a square to see the number of visits", and the legend "Fewer … More visits".
    - "Visits per bird" bars (10 px high, `--robin` on `--sand`, width relative to the top bird, at least 2%).
  - Values show on tap or focus, never on hover only (spec §9).

- [ ] **Step 1: Write the failing tests:**
  - `heatLevel` edges (0, max, max/4).
  - `cellText` plural.
  - Tapping a cell sets the status text, and tapping it again clears it.
  - e2e `stats.spec.ts` (spec §14: "Stats heatmap values shown on tap"): tap the busy seed's busiest cell (found from `GET /api/stats`), and the status reads exactly its `cellText`; NavPhone at 390 px shows 5 tabs.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the unit tests, `svelte-check`, and Playwright `chromium`.
- [ ] **Step 5: Commit:** `feat(gallery): Stats with the busiest-times heatmap`

### Task 14: Downloads end to end, axe on every page, and screenshot tests

**Files:**
- Create: `web/tests/e2e/downloads.spec.ts`, `web/tests/e2e/screens.spec.ts`, `web/tests/e2e/screens.spec.ts-snapshots/` (committed)
- Modify: `web/tests/e2e/a11y.spec.ts`, `scripts/e2e_server.py` (more seed if a screen needs it), `.github/workflows/ci.yml` (upload `test-results/` as an artifact on failure)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the specs**
  - `downloads.spec.ts` (spec §14: "downloading a single photo and a .zip"):
    - On a Visit, Download ▾ → Photo gives a `download` whose filename ends in `.jpg`.
    - On Birds at 1280 px, "Download this day (.zip)" → confirm → a `download` named `fat-ball-2026-11-02.zip`. Save it, and its size matches `size_bytes` within 5%.
  - `a11y.spec.ts`: add Videos, Stats, By species, the Other filters, the select bar open, the card menu open and the zip and delete dialogs. Each has no axe violations.
  - `screens.spec.ts` (R11): `toHaveScreenshot` for Today, Birds, By species, Visit, Videos (video masked), Stats, More (phone) and App status.
    - Sizes: 1280×800, and 390×844 via `test.use`.
    - Settings: `animations: "disabled"`, masks for `video` and the camera-status minutes, `maxDiffPixelRatio: 0.02`.
    - Only in the `chromium` project (`test.skip(testInfo.project.name !== "chromium")`).
- [ ] **Step 2: Make the snapshots:** `cd web && npx playwright test screens.spec.ts --project=chromium --update-snapshots`. Then look at every PNG yourself against the prototypes, and list any visible difference in the report.
- [ ] **Step 3: Run** the full Playwright `chromium` project: everything passes, 2 times in a row (so reseeding is idempotent).
- [ ] **Step 4: Commit:** `test(gallery): downloads, axe on every page and screenshot tests`

### Task 15: Try it on the owner's devices, and the README

**Files:**
- Create: `docs/plan-4-results.md`, new demo screenshots in `docs/screenshots/`
- Modify: `README.md`

- [ ] **Step 1: Tell the owner, then run the real app** (`uv run fatball serve` from Terminal.app). Check on the Pixel 9a and the Mac, and on the iPad if the owner is ready:
  - Videos: swipe, Next clip, the picker in the feed.
  - Select → Move to Other → Undo.
  - A day .zip downloads and opens.
  - Drag a card on the Mac.
  - Stats: tap a square.
  - A Mac banner appears about 2 minutes after a bird visit.
- [ ] **Step 2: Record what the owner saw** in `docs/plan-4-results.md`. Screenshots come from `uv run fatball demo` only.
- [ ] **Step 3: Update the README.**
  - The status line becomes "phase 1 complete".
  - Add bullets for Videos, By species, Select and .zip, Stats and Mac banners.
  - Move Plan 4 out of "What's coming" (phase 2 is the Raspberry Pi and phone notifications).
  - Add Mac and phone screenshots of Videos and Stats.
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check && npm --prefix web test -- --run && npm --prefix web run check`.
- [ ] **Step 5: Commit:** `docs: Plan 4 results; phase 1 complete in the README`

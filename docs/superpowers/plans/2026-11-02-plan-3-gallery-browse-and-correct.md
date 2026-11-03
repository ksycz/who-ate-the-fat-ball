# Plan 3: the gallery, part 1 (browse, watch, correct) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner opens the gallery on her Android phone, iPad or Mac, sees today's visits, watches a visit and fixes its name with "What is it?". Everything works without the PIN on the Mac and stays view-only on a locked device.

**Architecture:**
- A Svelte 5 + TypeScript app lives in `web/`. Vite builds it to static files in `src/fatball/api/static/` (gitignored), and the existing FastAPI process serves them, with every non-API path falling back to `index.html`.
- The gallery talks only to the JSON API (spec §4). This plan adds the few endpoints the pages need: `/api/today`, `/api/species`, marking a visit as watched, and the Sorted-into counts.
- Responsive layout: under 768 px wide the app uses the phone layout (floating bottom menu); from 768 px it uses the side menu (iPad and Mac).

**Tech Stack:** Python 3.12, FastAPI, SQLite (existing). Svelte 5, Vite, TypeScript, Vitest, `@fontsource/plus-jakarta-sans`. Playwright with `@axe-core/playwright`.

**Spec:** `docs/superpowers/specs/2026-10-31-who-ate-the-fat-ball-design.md` (§8 pages, §9 Robin, §10 API, §14 tests). Design references: `design/prototypes/` (gitignored, local only: `robin.py` holds the tokens, icons and logo SVGs; `build_main.py`, `build_more_visit.py` and `build_birds.py` hold the Today, Visit, More and Birds markup) and `design/changes-combined.md`.

## What this plan covers, and what waits for Plan 4

The gallery is two plans, so that each one ends in something the owner can use and review.

| Plan 3 (this plan) | Plan 4 |
|---|---|
| App shell: phone bottom menu, iPad/Mac side menu with Sorted into + counts, camera status | Videos feed (swipe, Previous / Next, filter chips, picker on top) |
| Today (all states), Visit, the "What is it?" picker with Undo | Birds › By species, period filter |
| Visit lists: Birds › All visits (by day), Other animals, Other, Favourites | Select mode, Move to…, bulk Undo, Download .zip |
| More, App status, Unlock editing, Setup (Mac only) | Mac drag and drop and the card ⋯ menu |
| PWA install, favicon | Other filters (All · Only dogs · Empty clips), deleting empty clips |
| Playwright + axe for these pages, in CI | Stats and heatmap; screenshot tests; the Mac banner notifier |

**Ruling (interim menu):** until Plan 4, the phone menu shows **Today · Birds · More** and the side menu has no Videos or Stats. Dead tabs would break "all screens behave as shown" more than missing ones. Plan 4 adds them back in the spec's order.

**Ruling (names):** names come from the catalog (`recognition/catalog.py`), shown with a capital first letter ("Great tit"). Renaming the catalog to the longer IOC names ("Eurasian nuthatch") is a question for the owner, not part of this plan.

## Global Constraints

- Colours are CSS variables with exactly the spec §9 values: `--robin #B4491A`, `--robin-dark #8F3712`, `--robin-tint #F7E1D3`, `--peach #FFEDE3`, `--sand #F1E8DC`, `--ink #2E2116`, `--ink-2 #5E5040`, `--olive #6E5B3A`, `--line #E9E0D4`, `--line-strong #E0D5C6`, `--field #A8998A`, `--chip #E3EBF0`, `--chip-ink #34505F`, `--dot-animals #8FA6B4`, `--dot-other #C9BBA8`, `--ok #2E8B57`. No other colours except white, and the overlays `rgba(46,33,22,0.45)` (dialog backdrop) and `rgba(46,33,22,0.78)` (clip badge).
- Plus Jakarta Sans everywhere, bundled with the app (no Google Fonts, no request leaves the home network). Weights 400, 500, 600 and 800 only. **Never 700**, no bold on the banner. Smallest text 11 px.
- Cards are white with a 16–18 px radius, pills 999 px, and the floating menu bar 24 px. Icons are outline icons with a 1.9 px stroke, taken from `ICONS` in `design/prototypes/robin.py`.
- Phone tap targets are at least 44 px. Contrast is at least 4.5:1 for text and 3:1 for icons and borders. Selected items use `aria-current` / `aria-pressed` and more than colour alone. Dialogs keep focus and close with Esc.
- Wording is copied exactly from spec §8, for example "Camera seen 5 min ago", "Quiet so far", "Checking who it is…", "1 clip couldn't be fetched · Retry", "94% sure", "Not right? Change", "Or maybe", "Corrected by you", "Changed to …", "Moved to … · Undo", "App status", "Last seen".
- Formats: "09:12 · stayed 2 min" (with "Yesterday" or a date for older visits); "▶ 0:24 · 3 clips"; "94% sure" on a blue-grey chip.
- On a locked device edit controls are **not rendered** (not just disabled), and the menu shows "Unlock editing" instead.
- Back returns to the screen you came from (browser history), not to a fixed page.
- No real footage, camera IPs, MACs or passwords in the repo or in test fixtures. Test media is made with ffmpeg.
- 8 GB Mac: Playwright runs with `workers: 1`, one browser project at a time locally. Warn the owner before the first full run.
- English only.

## Review Focus

1. **Thousands of visits:** list pages load 50 at a time with the cursor, and more as you scroll. They never fetch everything. Pinned in Task 8 (300 seeded visits, the first request has `limit=50`).
2. **"Today" around midnight and across time zones:** "today" is the Mac's local date as the server reports it, never the browser's clock. Pinned in Task 1 (fixed `now` at 00:30) and Task 5.
3. **A visit whose clip has no poster or web video yet:** the card shows a sand placeholder, with no broken image, and the player shows "Video not ready yet". Pinned in Tasks 5 and 6.
4. **The editor cookie expires mid-session:** a 403 from PATCH shows "Editing is locked on this device · Unlock" and the picker stays open. Pinned in Task 7.
5. **Undo after the change has expired or was already undone:** a 404 from `/api/undo` shows "Couldn't undo that" and nothing breaks. Pinned in Task 7.

---

## File structure

```text
src/fatball/
├── api/app.py                 # + /api/today, /api/species, POST /api/visits/{id}/watched, sorted counts,
│                              #   favourites filter, richer visit JSON, static gallery + SPA fallback
├── api/static/                # Vite build output (gitignored)
└── library/
    ├── migrations/004_watched.sql
    └── today.py               # champion, new-species banner, checking/failed clips, last visitor
web/
├── package.json, vite.config.ts, tsconfig.json, playwright.config.ts
├── public/                    # manifest.webmanifest, icons, favicon.svg, sw.js
├── src/
│   ├── main.ts, App.svelte    # shell + router outlet
│   ├── lib/tokens.css         # Robin tokens, base type
│   ├── lib/api.ts             # typed fetch client
│   ├── lib/router.ts          # tiny history router
│   ├── lib/format.ts          # all display strings (unit-tested)
│   ├── lib/session.ts         # can_edit store, toast + undo store
│   ├── components/            # Logo, Icon, CameraStatus, NavPhone, NavSide, VisitCard, Chip, Toast, Picker
│   └── pages/                 # Today, Visit, VisitList, More, AppStatus, Unlock, Setup, NotFound
└── tests/                     # *.test.ts (Vitest), e2e/*.spec.ts (Playwright)
scripts/e2e_server.py          # seeds a throwaway library and serves it for Playwright
```

---

### Task 1: Today data in the library

**Files:**
- Create: `src/fatball/library/migrations/004_watched.sql`, `src/fatball/library/today.py`
- Modify: `src/fatball/library/repo.py` (`_VISIT_SELECT`, `list_visits`), `src/fatball/library/db.py` if migrations are listed explicitly
- Test: `tests/library/test_today.py`, `tests/library/test_migrations.py`

**Interfaces:**
- Produces:
  - `visit.watched_at TEXT` (migration 004, `user_version` 4). The existing backup-before-migrate rule covers it.
  - `_VISIT_SELECT` adds the columns `duration_s` (sum of the visit's clip durations), `poster_path` and `preview_path` (from `best_clip_id`, falling back to the first clip), and `corrected` (`moved_by_user`).
  - `list_visits(..., favourite: bool | None = None)`
  - `today.summary(conn, day: date) -> dict` with keys `visits` (int) and `species` (distinct bird species).
  - `today.champion(conn, day: date) -> dict | None` with keys `scientific`, `name`, `count`, `first_at` (ISO), `best_frame_path`. It is the bird species with the most visits that day; a tie goes to the earlier first visit. None when there are no bird visits with a species.
  - `today.new_species(conn) -> dict | None` with keys `visit_id`, `scientific`, `name`, `started_at`. It is the newest birds visit whose species' `first_seen_at` lies within that visit's `[started_at, ended_at]` and whose `watched_at` is NULL.
  - `today.checking(conn, day: date) -> list[Clip]`: that day's video clips that are downloaded, processing, or ready but not yet in any visit.
  - `today.failed(conn, day: date) -> list[Clip]`: that day's clips with status `failed`, or with a `recognition_error`.
  - `today.last_visitor(conn, before: date) -> dict | None` with keys `name` and `started_at`: the newest birds visit before that day. `name` is None for an unknown bird.
  - `today.mark_watched(conn, visit_id: int, now: datetime) -> bool`, False for an unknown visit.
  - `repo.sorted_counts(conn) -> dict` with keys `birds`, `other_animals`, `other` and `favourites`.

- [ ] **Step 1: Write the failing tests** in `tests/library/test_today.py`, using the existing library fixtures (`tests/library/test_visits.py` shows how visits are built):
  - `test_champion_is_the_species_with_most_visits_today`: 3 great tit visits and 2 blue tit visits today, plus 5 blue tit visits yesterday. `champion(...)` is great tit with `count == 3` and `first_at` equal to the earliest of the three.
  - `test_champion_tie_goes_to_earlier_first_visit`
  - `test_champion_none_without_named_birds`: only an unknown bird and a dog visit.
  - `test_today_uses_the_given_local_day_not_utc`: a visit at 00:30 local time on 2026-11-03 counts for `date(2026, 11, 3)`, and nothing counts for the 2nd.
  - `test_new_species_until_watched`: a visit of a species seen for the first time is returned. After `mark_watched` it is None. A second visit of the same species never shows up.
  - `test_checking_lists_clips_not_yet_in_a_visit` and `test_failed_lists_conversion_and_recognition_failures`
  - `test_last_visitor_is_newest_bird_before_day`
  - `test_sorted_counts`
  - `test_visit_row_has_duration_poster_and_corrected`
  - In `test_migrations.py`: `test_v3_library_migrates_to_v4_with_backup`.
- [ ] **Step 2: Run them and see them fail:** `uv run pytest tests/library/test_today.py tests/library/test_migrations.py -q`
- [ ] **Step 3: Implement** the migration, `today.py` and the repo changes. Days compare on `substr(started_at, 1, 10)`, as `list_visits` already does: stored times are local ISO text.
- [ ] **Step 4: Run them and see them pass**, then `uv run pytest -q && uv run ruff check`.
- [ ] **Step 5: Commit:** `feat(library): today's champion, new-species banner, watched visits`

### Task 2: API for the gallery pages

**Files:**
- Modify: `src/fatball/api/app.py`
- Test: `tests/api/test_today_api.py`, `tests/api/test_visits_api.py`, `tests/api/test_api.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `_visit_json` adds `duration_s`, `poster_url`, `preview_url`, `corrected` (bool) and `watched` (bool).
  - `GET /api/visits?favourite=true`
  - `GET /api/today` returns:
    - `day` (ISO date, the Mac's local date from `now()`), `summary`, `champion` (with `best_frame_url`) or null, `new_species` or null
    - `visits`: every visit that day, newest first, as `_visit_json`
    - `checking`: clips as `_clip_json`; `failed`: `[{clip_id, begin_at, can_retry}]`
    - `last_visitor` (relative to that day) or null, `camera` (the same object as in `/api/status`)
  - `POST /api/visits/{id}/watched` returns 204, needs no PIN (watching is viewing), and returns 404 for an unknown visit.
  - `GET /api/species` returns `[{scientific, name, group, visits, last_seen_at}]` for the whole catalog, birds first, then by visits (descending), then by name. Plan 4 adds `?period=`.
  - `GET /api/status` adds `sorted` (from `repo.sorted_counts`).
  - `POST /api/retry/{clip_id}`:
    - A `failed` clip whose raw file still exists goes back to `downloaded`, so the processor converts it again.
    - A `ready` clip behaves as today.
    - Anything else still returns 409.
    - `failed[].can_retry` uses the same rule.

- [ ] **Step 1: Write the failing tests:**
  - `test_today_empty_day_has_last_visitor`
  - `test_today_lists_visits_newest_first_with_champion`
  - `test_today_day_comes_from_server_clock`: `now` fixed at 2026-11-03 00:30 local gives `"day": "2026-11-03"`.
  - `test_watched_needs_no_pin_and_hides_banner`: the client is not local and has no cookie, and still gets 204.
  - `test_species_lists_catalog_with_counts`
  - `test_status_has_sorted_counts`
  - `test_visits_favourite_filter`
  - `test_retry_failed_clip_with_raw_requeues_conversion`
  - `test_retry_failed_clip_without_raw_is_409`
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, then the full suite and ruff.
- [ ] **Step 5: Commit:** `feat(api): today, species and watched endpoints for the gallery`

### Task 3: Gallery skeleton, served by the app

**Files:**
- Create:
  - `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/index.html`
  - `web/src/main.ts`, `web/src/App.svelte`, `web/src/lib/tokens.css`, `web/src/lib/router.ts`, `web/src/lib/api.ts`
  - `web/src/components/Logo.svelte`, `web/src/components/Icon.svelte`
  - `web/tests/router.test.ts`, `tests/api/test_static.py`
- Modify: `src/fatball/api/app.py`, `.gitignore` (`src/fatball/api/static/`, `web/node_modules/`, `web/test-results/`), `.github/workflows/ci.yml`, `pyproject.toml` (hatch: include `src/fatball/api/static` as an artifact)

**Interfaces:**
- Produces:
  - Vite `build.outDir = "../src/fatball/api/static"`, `emptyOutDir: true`; dev server proxies `/api` and `/media` to `http://localhost:8080`.
  - `router.ts`:
    - `route` (a Svelte store of `{name, params}`), `navigate(path)` (pushState) and `back(fallback = "/")` (`history.back()` when the app has its own history, else `navigate(fallback)`)
    - Routes: `/` Today, `/visit/:id`, `/birds`, `/other-animals`, `/other`, `/favourites`, `/more`, `/status`, `/unlock`, `/setup`. Anything else goes to NotFound.
  - `api.ts`: `getJSON<T>(path)`, `send<T>(method, path, body?)`, and `ApiError {status, detail}`. Typed `Visit`, `Clip`, `Today`, `Status`, `Species` match Task 2 exactly.
  - `create_app` mounts `/assets` from the static dir. Any other GET that isn't `/api/*` or `/media/*` returns `index.html`. When the static dir has no `index.html`, it returns a plain 503 page: "The gallery isn't built yet. Run: npm --prefix web ci && npm --prefix web run build".
  - `tokens.css` holds the Global Constraints colours as `:root` variables, `body { background: var(--sand); color: var(--ink); font-family: 'Plus Jakarta Sans', system-ui, sans-serif }`, and the `@fontsource/plus-jakarta-sans` 400/500/600/800 imports.
  - `Logo.svelte` (`size`, `variant: "tile" | "mark"`) uses the `LOGO_N4` paths from `robin.py`. `variant="mark"` is the white roof + face with no tile, for the banner. `Icon.svelte` (`name`) uses `ICONS` from `robin.py`.

- [ ] **Step 1: Write the failing tests:**
  - `tests/api/test_static.py`:
    - `test_spa_fallback_serves_index_for_page_paths`: a temp static dir with `index.html` gives 200 for `/visit/3` and `/birds`.
    - `test_api_404_stays_json`
    - `test_unbuilt_gallery_explains_how_to_build`
  - `web/tests/router.test.ts`: `/visit/12` parses to `{name: "visit", params: {id: "12"}}`; an unknown path goes to `notfound`; `back()` with no history goes to the fallback.
- [ ] **Step 2: Run them and see them fail:** `uv run pytest tests/api/test_static.py -q` and `npm --prefix web test`.
- [ ] **Step 3: Implement.** Use `npm create vite@latest` (template `svelte-ts`) inside `web/`, then trim it. Dev dependencies: `vitest`, `jsdom`, `@testing-library/svelte`, `svelte-check`, `@playwright/test`, `@axe-core/playwright` (Vitest runs with `environment: "jsdom"`). Pin exact versions in `package.json` and commit `package-lock.json`. `create_app` takes `static_dir: Path | None = None` (default: the package's `api/static`), so tests can point it elsewhere.
- [ ] **Step 4: Run them and see them pass.** Add a CI step after `uv sync`:
  - `actions/setup-node@v4` with node 22
  - `npm --prefix web ci`, `npm --prefix web test`, `npm --prefix web run check` (svelte-check), `npm --prefix web run build`
- [ ] **Step 5: Commit:** `feat(gallery): Svelte app skeleton served by the service`

### Task 4: Display strings

**Files:**
- Create: `web/src/lib/format.ts`
- Test: `web/tests/format.test.ts`

**Interfaces:**
- Produces, all pure functions taking `now: Date` or `today: string` explicitly:
  - `visitTime(startedAt, endedAt, today)`
  - `clipBadge(durationS, clipCount)`
  - `sureChip(confidence)`
  - `visitName(visit)`
  - `cameraStatus(camera, now)`, returning `{dot: "ok" | "asleep" | "problem", text}`
  - `durationText(seconds)`

- [ ] **Step 1: Write the failing tests** with these exact expectations:
  - `visitTime("2026-11-02T09:12:00", "2026-11-02T09:14:10", "2026-11-02")` is `"09:12 · stayed 2 min"`. Under 1 minute gives `"· stayed under 1 min"`. Yesterday gives `"Yesterday 09:12 · stayed 2 min"`. Older gives `"31 Oct 09:12 · stayed 2 min"`.
  - `clipBadge(24, 3)` is `"▶ 0:24 · 3 clips"`, `clipBadge(9, 1)` is `"▶ 0:09 · 1 clip"` and `clipBadge(65, 2)` is `"▶ 1:05 · 2 clips"`.
  - `sureChip(0.94)` is `"94% sure"`, `sureChip(0.999)` is `"99% sure"` (never 100%), and `sureChip(null)` is `null`.
  - `visitName`:
    - a species gives a capital first letter ("Great tit")
    - birds with no species gives "Unknown bird"
    - other_animals with no species gives "Unknown animal"
    - in `other`: subject `person` gives "Person", species dog gives "Dog", subject `nothing` gives "Empty clip"
  - `cameraStatus`:
    - seen 5 min ago gives `{dot: "ok", text: "Camera seen 5 min ago"}`
    - state `asleep`, seen at 06:10, gives `"Camera asleep · seen 06:10"`
    - state `problem`, seen yesterday at 18:40, gives `"Camera not seen since yesterday 18:40 · Check App status"`
    - never seen gives `"Camera not seen yet · Check App status"`
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Use the server's `camera.state` for the dot. Parse times as local wall-clock text (no `Z`), so the browser's time zone can't shift them.
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit:** `feat(gallery): display strings in one tested module`

### Task 5: App shell and Today

**Files:**
- Create:
  - `web/src/components/NavPhone.svelte`, `NavSide.svelte`, `CameraStatus.svelte`, `VisitCard.svelte`, `Chip.svelte`
  - `web/src/lib/session.ts`, `web/src/pages/Today.svelte`
- Modify: `web/src/App.svelte`
- Test: `web/tests/today.test.ts` (Vitest + `@testing-library/svelte`, with `fetch` mocked)

**Interfaces:**
- Consumes: `api.ts`, `format.ts`, `router.ts`.
- Produces:
  - `session.ts`: `canEdit` store, loaded from `/api/me` at start; `toast` store `{text, undoToken?}`; `showToast(text, undoToken?)`.
  - `VisitCard.svelte` (`visit`, `today`) is the card from `build_main.py`:
    - best frame (else poster, else a sand placeholder)
    - the clip badge
    - name, time line and chip
    - "Corrected by you" under the time when `corrected`
    - the whole card is a link to `/visit/{id}`
  - `NavPhone`: floating 24 px bar at the bottom, **Today · Birds · More**, active item with a `--robin-tint` pill and `aria-current="page"`.
  - `NavSide`:
    1. Today, Favourites
    2. the "Sorted into" box with Birds / Other animals / Other, each with its dot and its count from `status.sorted`
    3. App status
    4. "Unlock editing" when locked
    5. the camera status at the bottom
  - The breakpoint is `768px`, done with CSS (`@media`), not JS.
- Today shows, in this order:
  1. a header with the logo, "Who Ate the Fat Ball?" and the camera status pill
  2. a camera-problem notice when the state is `problem`, linking to App status
  3. the New species banner when there is one: dark robin, the white logo mark, a pale-peach "New species" heading at 500 weight, "<Name> · 09:12" at 400 weight, and one white **Watch** button linking to the visit
  4. the "Today" title, with "14 visits · 6 species" (or "No visits yet")
  5. the "Today's fat-ball champion" card ("6 visits · first at 07:21")
  6. the "Checking who it is…" cards (pending chip "Checking…" on sand)
  7. the visit cards, newest first
  8. "1 clip couldn't be fetched" (or "N clips couldn't be fetched") with a Retry button, shown only to an editor and only when `can_retry`
  9. the empty state: the logo, "Quiet so far", and "No visitors yet today. Last visitor: Great tit, yesterday 16:20. The camera was last seen at 06:10." The last-visitor sentence is left out when there is none.
- On the side layout (768 px and wider) the banner sits at the top of Birds, not Today (spec §8). Task 8 adds it there, and Today leaves it out on that layout.

- [ ] **Step 1: Write the failing tests:**
  - `renders_empty_state_with_last_visitor`
  - `renders_champion_and_visits_newest_first`
  - `checking_card_for_unrecognised_clip`
  - `retry_hidden_when_locked`
  - `retry_posts_and_hides_row`
  - `camera_problem_notice_links_to_status`
  - `card_without_any_image_shows_placeholder_not_broken_img`
  - `today_label_uses_server_day`: the browser clock is on the 2nd while the server says the 3rd, and the cards show times without "Yesterday".
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** to the prototype look in `build_main.py`. Today refreshes `/api/today` every 30 s while the page is visible (`document.visibilityState`), so new visits appear without a reload.
- [ ] **Step 4: Run them and see them pass**, then `npm --prefix web run check`.
- [ ] **Step 5: Commit:** `feat(gallery): app shell and the Today page`

### Task 6: The Visit page

**Files:**
- Create: `web/src/pages/Visit.svelte`
- Test: `web/tests/visit.test.ts`

**Interfaces:**
- Consumes: `GET /api/visits/{id}`, `POST /api/visits/{id}/watched`, `PATCH /api/visits/{id}`, `session.ts`.
- Behaviour, to the Visit prototype (`build_more_visit.py`):
  - **Header:** a back button (`router.back("/")`).
  - **Player:** a `<video controls playsinline preload="metadata">` with the poster.
    - Under it, the visit's clips as a list. The one playing is marked "playing" in text, with `aria-current="true"`. Selecting another clip plays it. When a clip ends, the next one starts.
    - A clip with no `web_url` shows "Video not ready yet" instead of the player.
  - **Name:** the name with the "94% sure" chip.
    - "Corrected by you" replaces the chip when `corrected`.
    - Editors get a **"Not right? Change"** button, which opens the picker (Task 7).
  - **"Or maybe":** the guesses ranked 2 and 3, each a button "Blue tit · 4%", which saves that species straight away. The buttons appear for editors only; locked devices see the same list as plain text.
  - **Favourite:** a star toggle with `aria-pressed`, editors only. It uses PATCH `{is_favourite}`, and its toast is "Added to Favourites" / "Removed from Favourites" with Undo.
  - **Download ▾:** a white button that opens a small menu with "Video (.mp4)" (`web_url` of the clip playing) and "Photo (.jpg)" (`best_frame_url`). Both are `<a download>` links. It is shown to everyone.
  - **Watched:** `POST …/watched` once, on the first `play` event.
  - **Unknown id:** shows "This visit doesn't exist any more" with a link to Today.

- [ ] **Step 1: Write the failing tests:**
  - `marks_playing_clip_and_advances_on_end`
  - `watched_posted_once_on_first_play`
  - `or_maybe_tap_patches_species_and_toasts_changed_to`
  - `locked_device_has_no_change_or_favourite_controls`: the elements are absent, not disabled.
  - `clip_without_web_video_says_not_ready`
  - `download_menu_links_point_at_media`
  - `unknown_visit_shows_message`
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit:** `feat(gallery): the Visit page`

### Task 7: The "What is it?" picker, toast and Undo

**Files:**
- Create: `web/src/components/Picker.svelte`, `web/src/components/Toast.svelte`
- Modify: `web/src/pages/Visit.svelte`, `web/src/App.svelte` (one Toast for the whole app)
- Test: `web/tests/picker.test.ts`

**Interfaces:**
- Consumes: `GET /api/species`, `PATCH /api/visits/{id}`, `POST /api/undo/{token}`.
- Produces: `Picker.svelte` (`visit`, `onclose`, `onchanged(visit)`). Visit re-fetches itself after a change or an undo.
- **Layout:** a bottom sheet under 768 px and a centred dialog from 768 px, both `role="dialog" aria-modal="true"` with the heading "What is it?". The contents follow `PICKER` in `robin.py`, from top to bottom:
  1. A close button.
  2. "Search all birds", which filters the whole catalog by English or scientific name as you type. With no match it shows "No bird called "…". Try a shorter name."
  3. **Birds seen at your feeder:** catalog birds with `visits > 0`. The current species is marked with `aria-pressed="true"`, a 2 px robin border and 600 weight.
  4. **Not a bird?** Three buttons with their dots and hints:
     - "Other animal" with the hint "Squirrel, cat…" sends `{category: "other_animals"}`
     - "Dog" with the hint "Moves to Other" sends `{species: "Canis lupus familiaris"}`
     - "Nothing" with the hint "Empty clip" sends `{species: null, category: "other"}`
- **Behaviour:**
  - Focus is trapped while the picker is open, Esc closes it, and focus goes back to the button that opened it.
  - Choosing an option saves straight away and closes the picker.
  - The toast reads "Changed to Blue tit" (a bird) or "Moved to Other" / "Moved to Other animals" (a category change), with an **Undo** button. It stays 8 s and is `role="status"`.
- **Errors:**
  - A 403 from PATCH keeps the picker open and shows "Editing is locked on this device · Unlock", where Unlock links to `/unlock`.
  - A 404 from undo shows "Couldn't undo that".
  - A network error shows "Couldn't save. Check the Wi-Fi and try again."

- [ ] **Step 1: Write the failing tests:**
  - `seen_birds_listed_and_current_marked_pressed`
  - `search_filters_catalog_and_shows_no_match_text`
  - `choosing_bird_patches_species_and_toasts_with_undo`
  - `not_a_bird_options_send_exact_bodies`: asserts all three request bodies above.
  - `undo_posts_token_and_refreshes`
  - `undo_404_shows_couldnt_undo`
  - `patch_403_keeps_picker_open_with_unlock_link`
  - `esc_closes_and_returns_focus`
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit:** `feat(gallery): the What is it? picker with Undo`

### Task 8: Visit lists (Birds, Other animals, Other, Favourites)

**Files:**
- Create: `web/src/pages/VisitList.svelte`
- Test: `web/tests/visitlist.test.ts`

**Interfaces:**
- Consumes: `GET /api/visits?category=|favourite=true&limit=50&cursor=`, `VisitCard`.
- Produces: `VisitList.svelte` (`kind: "birds" | "other_animals" | "other" | "favourites"`).
- **Titles:** "Birds", "Other animals", "Other" and "Favourites".
- **Grouping:** visits are grouped by day, with the headings "Today", "Yesterday", then "Saturday 31 October".
- **Loading more:**
  - An `IntersectionObserver` sentinel loads the next page with `next_cursor`. There is also a "Show more" button as a fallback for keyboards.
  - Pages are appended. A day heading isn't repeated when a day spans two pages.
- **Banner:** on the 768 px+ layout, Birds shows the New species banner at the top (from `/api/today`), with the same look as Today.
- **Empty states:**
  - Birds: "No bird visits yet"
  - Other animals: "No other animals yet"
  - Other: "Nothing here: no dogs, people or empty clips"
  - Favourites: "No favourites yet. Tap ☆ on a visit to keep it here."
- Phone: Birds is a menu tab. Other animals, Other and Favourites are reached from More (Task 9). Side layout: from the menu.

- [ ] **Step 1: Write the failing tests:**
  - `first_request_asks_for_50`: a mocked API with 300 visits, and the first fetch URL has `limit=50` and no cursor.
  - `scrolling_sentinel_loads_next_cursor_and_appends`
  - `day_heading_not_repeated_across_pages`
  - `favourites_uses_favourite_filter`
  - `empty_state_texts`
  - `birds_shows_banner_only_on_wide_layout`
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit:** `feat(gallery): Birds, Other animals, Other and Favourites lists`

### Task 9: More, App status, Unlock and Setup

**Files:**
- Create: `web/src/pages/More.svelte`, `AppStatus.svelte`, `Unlock.svelte`, `Setup.svelte`
- Test: `web/tests/more_status.test.ts`

**Interfaces:**
- Consumes: `/api/status`, `/api/me`, `POST /api/unlock`, `PUT /api/setup`.
- **More** (phone only; the side layout redirects to Today), to the More prototype:
  1. Favourites
  2. the "Sorted into" box (Birds / Other animals / Other with dots and counts)
  3. App status
  4. "Unlock editing" when locked
- **App status:**
  - Camera: reachable or not, "Last seen" time, and the last error in plain words. The error texts:
    - `wrong_password`: "The camera rejected the password. Set it again in Setup."
    - `account_locked`: "The camera locked the login after wrong passwords. The app tries again in 10 minutes."
    - `no_password`: "The camera has no password. Set one in Setup."
    - `low_disk`: "The Mac is nearly out of space."
    - anything else: "Something went wrong (code). The app keeps trying."
  - The processing queue (`queue` counts and `recognition.pending`), and free disk space as "12.4 GB free". When `disk.low` is true it shows "Disk nearly full".
  - A **Setup** link, shown only when the page is opened on the Mac itself. The rule is `location.hostname` in `localhost`, `127.0.0.1` or `::1`; the server enforces it anyway.
- **Unlock:**
  - A 4-digit PIN field (`inputmode="numeric"`, `autocomplete="one-time-code"`) and an "Unlock" button.
  - Messages: wrong PIN gives "That PIN isn't right"; 429 gives "Too many tries. Wait 15 minutes and try again."; success returns you to where you came from, and editing is on.
- **Setup** (Mac only): the camera address, the camera password (`type="password"`, never shown again or prefilled) and the edit PIN. Saving sends one `PUT /api/setup`, followed by "Saved". Off the Mac it shows "Setup only works on the Mac itself."

- [ ] **Step 1: Write the failing tests:**
  - `more_lists_sorted_counts_and_links`
  - `status_explains_wrong_password`
  - `status_shows_low_disk_warning`
  - `setup_link_only_on_localhost`
  - `unlock_wrong_pin_message`
  - `unlock_429_message`
  - `unlock_success_enables_editing_and_goes_back`
  - `setup_sends_only_filled_fields`
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit:** `feat(gallery): More, App status, Unlock editing and Setup`

### Task 10: Install to the home screen

**Files:**
- Create: `web/public/manifest.webmanifest`, `web/public/favicon.svg`, `web/public/icon-192.png`, `web/public/icon-512.png`, `web/public/apple-touch-icon.png`, `web/public/sw.js`
- Modify: `web/index.html`, `web/src/main.ts`
- Test: `tests/api/test_static.py`, `web/tests/sw.test.ts`

**Interfaces:**
- **Manifest:**
  - `name` "Who Ate the Fat Ball?", `short_name` "Fat Ball"
  - `display` "standalone", `background_color` "#F1E8DC", `theme_color` "#B4491A", `start_url` "/"
  - the PNG icons, rendered once from `design/logo.svg` with `rsvg-convert` or Pillow; record the command in the commit message
- **Favicon:** the N4b tile with the roof stroke thickened to 5 (from 3.4) so it reads at 16 px (spec §9, C6).
- **Service worker:** caches only the app shell (`/`, `/assets/*`, icons). `/api/*` and `/media/*` always go to the network, so data is never stale. It is registered only in production builds.
- **Server:** serves `manifest.webmanifest` with `application/manifest+json` and `sw.js` with `Cache-Control: no-cache`.

- [ ] **Step 1: Write the failing tests:**
  - `test_manifest_served_with_manifest_type`
  - `test_sw_not_cached`
  - `sw_never_caches_api_or_media`: unit-test the worker's `shouldCache(url)`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass.** Then check by hand at 16 px that the favicon roof is visible, and attach a zoomed screenshot to the task report.
- [ ] **Step 5: Commit:** `feat(gallery): installable on phone and iPad`

### Task 11: End-to-end tests with Playwright and axe

**Files:**
- Create: `scripts/e2e_server.py`, `web/playwright.config.ts`, `web/tests/e2e/today.spec.ts`, `visit.spec.ts`, `lists.spec.ts`, `more.spec.ts`, `a11y.spec.ts`
- Modify: `web/package.json` (`e2e` script), `.github/workflows/ci.yml`

**Interfaces:**
- **`scripts/e2e_server.py --data-dir DIR --port 8765 [--empty]`:**
  - It wipes `DIR` and seeds a library through `repo`/`visits` functions, with 2-second ffmpeg test-pattern clips (`demo.make_xm_clip` + `convert_clip`).
  - The busy day, relative to a fixed `now` of 2026-11-02 10:00 local:
    - today: 4 great tit visits, 2 blue tit, 1 nuthatch (a new species, not watched), 1 unknown bird, 1 clip still checking, 1 failed clip with its raw file
    - yesterday: 3 visits
    - Other: 1 dog visit and 1 empty visit
    - Other animals: 1 squirrel visit
  - `--empty` seeds only yesterday's visits.
  - It serves `create_app(settings, now=fixed)` with uvicorn on 127.0.0.1. Requests come from the Mac itself, so editing works without the PIN.
- **`playwright.config.ts`:**
  - `workers: 1`, `retries: 0` locally and 1 on CI
  - projects: `chromium` (1280×800), `webkit-ipad` (`devices["iPad (gen 7)"]`) and `mobile-chrome` (`devices["Pixel 7"]`)
  - `webServer` runs `uv run python ../scripts/e2e_server.py --data-dir ../.e2e-data --port 8765`
  - Each test sets `page.clock.setFixedTime("2026-11-02T10:00:00")`.
  - Add `.e2e-data/` to `.gitignore`.
- **Specs (spec §14, the parts that are in this plan):**
  - `today.spec.ts`:
    - busy day: the champion is "Great tit, 4 visits", the banner says "New species" and "Nuthatch · …", and there are "Checking who it is…" and "1 clip couldn't be fetched"
    - empty state, through a second server on port 8766 started with `--empty`
    - a camera-problem state
  - `visit.spec.ts`:
    - open a visit from Today, play it, and the "playing" mark moves
    - correct the species with the picker, the toast reads "Changed to Blue tit", Undo restores "Great tit"
    - "Nothing" gives "Moved to Other", Undo
    - Watch on the banner, come back, and the banner is gone
  - `lists.spec.ts`:
    - Birds is grouped by day, with "Today" and "Yesterday" headings
    - Other shows the dog and the empty clip
    - Favourites: favourite a visit, and it shows up there
  - `more.spec.ts` (mobile-chrome only):
    - More → Other animals → back returns to More
    - More → App status shows "Camera seen…"
  - `a11y.spec.ts`: `AxeBuilder` with tags `wcag2a`, `wcag2aa`, `wcag21aa` on Today, Visit, the open picker, Birds, Other, More, App status and Unlock. No violations are allowed.
- **CI:** a second job `gallery-e2e` on `macos-15`:
  - ffmpeg, uv, node 22, `npm --prefix web ci`, `npx --prefix web playwright install --with-deps chromium webkit`, build
  - then `npm --prefix web run e2e`; upload `web/test-results` when it fails

- [ ] **Step 1: Write the specs** and run them against the built gallery: `npm --prefix web run build && npm --prefix web run e2e -- --project=chromium`. Expected: they pass, because Tasks 5–9 built the pages. Any failure is a real bug: fix it in the page with a Vitest test first, then here.
- [ ] **Step 2: Tell the owner before running the WebKit and mobile projects**, one at a time: `--project=webkit-ipad`, then `--project=mobile-chrome`.
- [ ] **Step 3: Fix the axe violations** in the components, not by disabling rules.
- [ ] **Step 4: Push** the CI change on the branch and confirm the job is green (Auto-fix watches it).
- [ ] **Step 5: Commit:** `test(gallery): Playwright end-to-end and axe checks`

### Task 12: Try it on the owner's devices, and the README

**Files:**
- Create: `docs/plan-3-results.md`
- Modify: `README.md`

- [ ] **Step 1: Tell the owner, then run the real app** (`uv run fatball serve` from Terminal.app, as before). She opens `http://<Mac name>.local:8080` on the Android phone and the iPad. Check:
  - Today loads in under 1 s on Wi-Fi (Chrome DevTools remote, or a stopwatch is enough)
  - a real clip plays
  - correcting a visit on the phone needs the PIN, and works after Unlock
  - "Add to Home screen" installs it with the logo
- [ ] **Step 2: Record what she saw**, with timings and anything that looked wrong, in `docs/plan-3-results.md`. Screenshots come from **demo mode only** (`uv run fatball demo`), never from real footage.
- [ ] **Step 3: Update the README:**
  - "What works today" gets a gallery bullet
  - "Try the demo" becomes: build the gallery once (`npm --prefix web ci && npm --prefix web run build`), then `uv run fatball demo` and open <http://localhost:8080>
  - screenshots from the demo
  - the status line becomes "phase 1: gallery part 1"
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check && npm --prefix web test && npm --prefix web run check`.
- [ ] **Step 5: Commit:** `docs: Plan 3 results and gallery in the README`

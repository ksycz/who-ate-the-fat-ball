# Plan 1: Foundation and Camera Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a background service that automatically downloads every new clip from the sleeping iCSee camera, converts it into web-playable video, and stores it in a library served by a small JSON API. It also gets a demo mode with a fake camera, CI, and a portfolio-ready README.

**Architecture:**
- A single Python package, `fatball`, holds four pieces:
  - a Xiongmai DVRIP client (`camera/`)
  - a polling watcher and downloader (`ingest/`)
  - ffmpeg-based conversion (`media/`)
  - an SQLite library (`library/`)
- A FastAPI app (`api/`) sits on top of the library.
- An in-process **fake camera** speaks the same protocol. It drives every test and the `fatball demo` command.

Bird recognition (Plan 2) and the gallery UI (Plan 3) build on this plan's interfaces.

**Tech Stack:** Python 3.12 managed by `uv`, FastAPI + Uvicorn, SQLite (stdlib `sqlite3`), ffmpeg (Homebrew binary), `keyring` (macOS Keychain), pytest + pytest-asyncio, ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-31-who-ate-the-fat-ball-design.md` (§4, §5, §6.1, §7, §10 subset, §11, §12, §14, §16). The camera protocol facts are in `HANDOFF.md` ("Protocol notes", "File formats").

## Global Constraints

- **Python and dependencies:**
  - Python **3.12+**.
  - Every dependency's licence must be compatible with MIT. No GPL Python dependencies.
  - ffmpeg is called as an external binary, never linked.
- **Package and data:**
  - Package name: `fatball`. CLI entry point: `fatball` with the subcommands `serve`, `demo` and `setup`.
  - Default data directory: `~/Library/Application Support/WhoAteTheFatBall/`. It can be overridden with the env var `FATBALL_DATA_DIR`.
- **Camera:**
  - Port **34567**. Header struct `"<BB2xII2xHI"`. Payload = JSON + `b"\x0a\x00"`.
  - Message ids: login **1000**, sysinfo **1020**, file query **1440**, play/download request **1420**, claim **1424**, media data **1426**, time set **1450**, time query **1452**. The two time ids come from python-dvr and aren't verified on this camera yet; Task 11 checks them.
  - File queries go **one day at a time**, because each returns at most 64 results.
  - The empty-password hash is `tlJwpbo6`.
- **Watcher:**
  - Polls every **5 s** with a plain TCP connect.
  - On start-up it catches up on **7 days**, newest first.
  - Fixes the camera clock when the difference is **more than 2 min**.
  - After a wrong password it pauses **10 min**.
- **Privacy:**
  - The password lives only in the macOS Keychain (service `who-ate-the-fat-ball`, account `camera`). It is never written to the database, files or logs.
  - Never commit real footage or any camera identifier. Test video is generated with ffmpeg `testsrc`.
- **Web copy:** H.264 MP4 (`libx264`, `-movflags +faststart`). The original H.265 file is kept.
- **Network:**
  - The API listens on the LAN with no login.
  - `/api/setup` accepts requests only from `127.0.0.1` / `::1`.
- **Never delete media automatically.**
- **Git:** never push to GitHub unless the owner asks. Work on a feature branch and commit after every task.

## Review Focus

1. **The camera's IP changes** after a router restart. The watcher should find it again by MAC address or a port scan without anyone touching it. *(Task 7: `test_rediscovers_camera_after_ip_change`)*
2. **The camera falls asleep mid-download.** The partial file must be deleted, nothing marked as downloaded, and the clip fetched again on the next wake-up. *(Task 7: `test_partial_download_is_discarded_and_retried`)*
3. **The same file appears in two day-queries** (around midnight, or because of clock skew). It must be stored only once. *(Task 6: `test_add_clip_is_idempotent_on_sd_path_and_begin`)*
4. **The disk is nearly full.** Downloads stop and App status shows a warning, instead of crashing or deleting anything. *(Task 9: `test_status_reports_low_disk`)*
5. **Wrong password.** The watcher must not hammer the camera, because that locks the account. It backs off 10 min and reports `last_error = "wrong_password"`. *(Task 7: `test_wrong_password_backs_off_ten_minutes`)*

---

## File Structure

```
pyproject.toml                       uv project, deps, ruff, pytest config, [project.scripts] fatball
.github/workflows/ci.yml             ruff + pytest on macOS runner (installs ffmpeg)
src/fatball/__init__.py
src/fatball/config.py                Settings dataclass: data_dir, poll_interval_s, catchup_days, …
src/fatball/camera/protocol.py       header pack/unpack, sofia_hash, payload encode/decode
src/fatball/camera/client.py         XMClient: login, system_info, list_files, download, set_time
src/fatball/camera/fake.py           FakeCamera: threaded TCP server speaking the same protocol
src/fatball/camera/discovery.py      find_camera(subnet, mac, port) → ip
src/fatball/media/demux.py           unwrap Xiongmai frames → (codec, fps, elementary stream)
src/fatball/media/convert.py         ffmpeg: original mp4, web h264 mp4, poster jpg, preview loop, thumb
src/fatball/library/schema.sql       all tables from spec §7
src/fatball/library/db.py            connect(path) with WAL + migrations
src/fatball/library/repo.py          camera/clip functions used by ingest + api
src/fatball/ingest/watcher.py        Watcher: poll loop, catch-up, clock fix, back-off, discovery
src/fatball/ingest/processor.py      Processor: converts downloaded clips → ready/failed
src/fatball/secrets.py               get_password()/set_password() via keyring
src/fatball/api/app.py               FastAPI app factory: /api/status, /api/clips, /media, /api/setup
src/fatball/cli.py                   serve / demo / setup commands
src/fatball/demo.py                  build demo: fake camera + generated clips
scripts/install-launchagent.sh       writes ~/Library/LaunchAgents/com.whoatethefatball.plist
tests/...                            mirrors src layout; tests/conftest.py makes tmp data dirs + fake camera
```

The root scripts `camera_test.py`, `download_test.py` and `xm_convert.py` are reference material. Task 11 deletes them after their logic has moved into the package.

---

### Task 1: Project scaffold and CI

**Files:**
- Create: `pyproject.toml`, `src/fatball/__init__.py`, `src/fatball/config.py`, `tests/test_config.py`, `.github/workflows/ci.yml`
- Modify: `.gitignore` (add `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `dist/`)

**Interfaces:**
- Produces: `fatball.config.Settings` (frozen dataclass) with these fields:
  - `data_dir: Path`
  - `camera_port: int = 34567`
  - `poll_interval_s: float = 5.0`
  - `catchup_days: int = 7`
  - `clock_tolerance_s: int = 120`
  - `wrong_password_backoff_s: int = 600`
  - `min_free_bytes: int = 2_000_000_000`
  
  Also `Settings.load() -> Settings`, which reads `FATBALL_DATA_DIR` or falls back to the default, and properties `media_dir` and `db_path`.

- [ ] **Step 1: Write the failing tests**

```python
def test_default_data_dir_is_application_support(monkeypatch):
    monkeypatch.delenv("FATBALL_DATA_DIR", raising=False)
    s = Settings.load()
    assert s.data_dir == Path.home() / "Library/Application Support/WhoAteTheFatBall"

def test_env_overrides_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("FATBALL_DATA_DIR", str(tmp_path))
    s = Settings.load()
    assert s.data_dir == tmp_path and s.db_path == tmp_path / "library.sqlite" and s.media_dir == tmp_path / "media"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_config.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `pyproject.toml` (deps: fastapi, uvicorn, keyring; dev: pytest, pytest-asyncio, httpx, ruff; `requires-python = ">=3.12"`; script `fatball = "fatball.cli:main"`) and `config.py`.
- [ ] **Step 4: Write `ci.yml`.** It runs on push and pull request, on `macos-14`, with these steps: `brew install ffmpeg`, `astral-sh/setup-uv`, `uv sync`, `uv run ruff check`, `uv run pytest -q`.
- [ ] **Step 5: Run** `uv run ruff check && uv run pytest -q`. Expected: all pass.
- [ ] **Step 6: Commit** with the message `chore: scaffold fatball package, config and CI`.

### Task 2: DVRIP protocol primitives

**Files:**
- Create: `src/fatball/camera/protocol.py`, `tests/camera/test_protocol.py`

**Interfaces:**
- Produces:
  - `HEADER: struct.Struct`
  - `sofia_hash(password: str) -> str`
  - `encode(session: int, seq: int, msg_id: int, payload: dict) -> bytes`
  - `decode_header(raw: bytes) -> tuple[int, int, int]` (session, msg_id, length)
  - `decode_payload(raw: bytes) -> dict`
  - constants `LOGIN=1000`, `SYSINFO=1020`, `FILE_QUERY=1440`, `PLAY_REQ=1420`, `PLAY_CLAIM=1424`, `PLAY_DATA=1426`, `TIME_SET=1450`, `TIME_QUERY=1452`

- [ ] **Step 1: Write the failing tests**

```python
def test_sofia_hash_of_empty_password():
    assert sofia_hash("") == "tlJwpbo6"

def test_encode_header_and_terminator():
    raw = encode(session=6, seq=3, msg_id=1000, payload={"Name": "x"})
    session, msg_id, length = decode_header(raw[:20])
    assert (raw[0], session, msg_id) == (0xFF, 6, 1000)
    assert raw.endswith(b"\x0a\x00") and length == len(raw) - 20

def test_decode_payload_strips_terminator():
    assert decode_payload(b'{"Ret": 100}\x0a\x00') == {"Ret": 100}
```

- [ ] **Step 2: Run** `uv run pytest tests/camera/test_protocol.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Port the logic from `camera_test.py` (`sofia_hash`, the header format).
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(camera): DVRIP framing and sofia hash`.

### Task 3: Fake camera

**Files:**
- Create: `src/fatball/camera/fake.py`, `tests/camera/test_fake.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: `protocol.*`
- Produces: `FakeCamera(password: str = "", files: list[FakeFile] = [], clock: datetime | None = None)`, a context manager that starts a threaded TCP server on `127.0.0.1` with a random port.

  Attributes and methods:
  - `.port`, `.awake: bool` (it doesn't accept connections when `False`)
  - `.drop_after_bytes: int | None`, which simulates the camera falling asleep mid-download
  - `.clock`, `.set_time_calls: list[datetime]`, `.login_attempts: int`
  - `add_file(f: FakeFile)`

  `FakeFile(begin: datetime, end: datetime, kind: Literal["h264", "jpg"], payload: bytes)`. Its `sd_path` follows the real naming, e.g. `/mnt/sd0/2026-10-31/001/09.12.00-09.12.11[A][@7][0](0).h264`.

  Behaviour:
  - Login returns `Ret 100`, or `205` for a wrong password.
  - File query returns at most **64** files for the requested day, sorted oldest first, as the real camera does.
  - Download works as on the real camera: claim (1424) on a second connection plus `DownloadStart` (1420) on the main one, then streams `payload` in 1426 packets of up to 32 KB.
  - Time set (1450) records the time.
  - The `tests/conftest.py` fixture `fake_camera` yields a `FakeCamera`. The fixture `xm_clip_bytes` produces a valid Xiongmai-wrapped H.265 clip: ffmpeg `testsrc` → hevc → wrapped in `00 00 01 FC/FD` frames.

- [ ] **Step 1: Write the failing tests**
  - `test_login_ok_and_wrong_password`: the empty password gives 100, `"x"` gives 205.
  - `test_file_query_caps_at_64`: with 70 files on one day, the query returns 64.
  - `test_sleeping_camera_refuses_connection`: with `awake=False`, the connection fails.
  - `test_xm_clip_bytes_starts_with_fc_frame`: `xm_clip_bytes[:4] == b"\x00\x00\x01\xfc"` and byte 4 & 0x0F equals 3 (HEVC).
- [ ] **Step 2: Run** `uv run pytest tests/camera/test_fake.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** with `socketserver.ThreadingTCPServer`. When `awake` is False, close new connections immediately.
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit** with the message `test(camera): fake Xiongmai camera and xm clip fixture`.

### Task 4: Camera client

**Files:**
- Create: `src/fatball/camera/client.py`, `tests/camera/test_client.py`

**Interfaces:**
- Consumes: `protocol.*`, plus `FakeCamera` in tests.
- Produces:
  - `class XMClient(host: str, port: int = 34567, timeout: float = 8.0)`, a context manager.
  - `.login(user: str, password: str) -> None`. It raises `WrongPassword` (Ret 203 or 205), `AccountLocked` (206), or `CameraUnreachable` (OSError or timeout).
  - `.system_info() -> dict`
  - `.list_files(day: date, kind: Literal["h264", "jpg"]) -> list[RemoteFile]`
  - `.download(f: RemoteFile, dest: Path) -> int`, which returns the bytes written and raises `DownloadInterrupted` on a short read.
  - `.camera_time() -> datetime` (`OPTimeQuery` via 1452)
  - `.set_time(dt: datetime) -> None`
  - `RemoteFile(sd_path: str, begin: datetime, end: datetime, size_kb: int, kind: str)`, a frozen dataclass.

- [ ] **Step 1: Write the failing tests** (against `fake_camera`)
  - `test_login_wrong_password_raises`
  - `test_list_files_parses_begin_end_and_size`
  - `test_download_writes_exact_payload`: the file bytes equal `FakeFile.payload`
  - `test_download_interrupted_raises_and_leaves_no_file`: with `drop_after_bytes=1000`, `dest` doesn't exist afterwards
  - `test_set_time_sends_mac_time`
- [ ] **Step 2: Run** `uv run pytest tests/camera/test_client.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Port `download_test.py`'s working path: a separate connection for the claim, `DownloadStart`, then read 1426 packets until 6 s of silence or the expected size × 1.5. Write to `dest.with_suffix(".part")` and rename only when complete.
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(camera): XMClient login, list, download, set_time`.

### Task 5: Demux and conversion

**Files:**
- Create: `src/fatball/media/demux.py`, `src/fatball/media/convert.py`, `tests/media/test_demux.py`, `tests/media/test_convert.py`

**Interfaces:**
- Produces:
  - `demux(raw: bytes) -> Demuxed(codec: Literal["hevc", "h264"], fps: int, video: bytes)`. It skips frames before the first key frame and raises `NotXiongmai` if no `FC` frame is found.
  - `extract_jpeg(raw: bytes) -> bytes`, for the `FE`-wrapped photo.
  - `convert_clip(raw_path: Path, out_dir: Path) -> ConvertedClip(original: Path, web: Path, poster: Path, preview: Path, thumb: Path, duration_s: float)`
  - Output names inside `out_dir`:
    - `original.mp4`: H.265 copy, tag `hvc1`
    - `web.mp4`: H.264 `libx264 -crf 23 -preset veryfast -movflags +faststart`, no audio
    - `poster.jpg`: the frame at 1 s
    - `preview.mp4`: the first 3 s, muted, 480 px wide
    - `thumb.jpg`: 480 px wide
  - It raises `ConversionFailed(stderr)` if ffmpeg fails.

- [ ] **Step 1: Write the failing tests**
  - `test_demux_reads_hevc_and_fps(xm_clip_bytes)`: codec is `"hevc"` and fps equals the fixture's fps.
  - `test_demux_skips_frames_before_keyframe`: an FD frame placed before the first FC is dropped.
  - `test_convert_produces_playable_h264(tmp_path, xm_clip_bytes)`: `ffprobe` of `web.mp4` reports `codec_name=h264`, and `poster.jpg`, `preview.mp4` and `thumb.jpg` all exist.
  - `test_convert_garbage_raises_conversion_failed`
- [ ] **Step 2: Run** `uv run pytest tests/media -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Port `xm_convert.py`, including the codec mask `media & 0x0F`. Run ffmpeg with `subprocess.run(check=False)` and parse ffprobe's JSON.
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(media): demux xiongmai frames and convert to web formats`.

### Task 6: Library (schema and repository)

**Files:**
- Create: `src/fatball/library/schema.sql`, `src/fatball/library/db.py`, `src/fatball/library/repo.py`, `tests/library/test_repo.py`

**Interfaces:**
- Produces:
  - `connect(path: Path) -> sqlite3.Connection`. It turns on WAL and foreign keys, applies `schema.sql` once, and records `user_version = 1`.
  - Schema: every table in spec §7 (`camera`, `clip`, `visit`, `visit_clip`, `species`, `species_name`, `guess`, `correction`, `setting`), with a unique index on `clip(sd_path, begin_at)`.
  - `repo.upsert_camera(conn, name: str, mac: str | None, ip: str | None) -> int`
  - `repo.update_camera_status(conn, camera_id: int, *, last_seen_at=None, last_ip=None, last_error=None, clock_offset_s=None) -> None`
  - `repo.add_clip(conn, camera_id: int, sd_path: str, begin_at: datetime, end_at: datetime, kind: str, size_bytes: int) -> int | None`. It returns `None` when the clip already exists.
  - `repo.known_clip_keys(conn, day: date) -> set[tuple[str, datetime]]`
  - `repo.set_clip_status(conn, clip_id: int, status: Literal["downloaded", "processing", "ready", "failed"], **paths) -> None`
  - `repo.clips_with_status(conn, status: str) -> list[Clip]`
  - `repo.list_clips(conn, limit: int, before: datetime | None) -> list[Clip]`
  - `Clip`: a dataclass mirroring the `clip` row.

- [ ] **Step 1: Write the failing tests**
  - `test_connect_creates_all_tables`: `sqlite_master` contains the 9 table names.
  - `test_add_clip_is_idempotent_on_sd_path_and_begin`: adding the same clip twice gives an id first, then `None`, and one row.
  - `test_status_transitions_and_paths`
  - `test_list_clips_newest_first_with_cursor`
- [ ] **Step 2: Run** `uv run pytest tests/library -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Store datetimes as ISO 8601 text in local time with an offset.
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(library): sqlite schema and clip repository`.

### Task 7: Watcher and downloader

**Files:**
- Create: `src/fatball/ingest/watcher.py`, `src/fatball/camera/discovery.py`, `src/fatball/secrets.py`, `tests/ingest/test_watcher.py`

**Interfaces:**
- Consumes: `XMClient`, `repo.*`, `Settings`
- Produces:
  - `secrets.get_password() -> str | None` and `secrets.set_password(pw: str) -> None` (keyring service `who-ate-the-fat-ball`, account `camera`).
  - `discovery.find_camera(subnet: str, port: int, mac: str | None) -> str | None`. It tries the cached IP first, then checks the ARP table for the MAC, then scans the `/24` for an open `port`.
  - `class Watcher(settings, conn, *, connect=XMClient, now=datetime.now, sleep=time.sleep, find=discovery.find_camera, password=secrets.get_password)` with these methods:
    - `.tick() -> TickResult(reachable: bool, downloaded: int, error: str | None)`: one poll.
    - `.run_forever()`
  - Behaviour of each tick:
    - If the camera isn't reachable, try discovery and record nothing else.
    - If it's reachable: log in, fix the clock if the offset is over `clock_tolerance_s`, then list today plus every earlier day back to `catchup_days` on the first tick (only today afterwards, plus yesterday until 00:10). Download unknown files **newest first** into `media_dir/raw/<clip_id>.raw`, setting status `downloaded`.
    - Stop early when free disk space is below `min_free_bytes`, setting `last_error="low_disk"`.
    - After `WrongPassword`, set `last_error="wrong_password"` and skip ticks until `wrong_password_backoff_s` has passed.

- [ ] **Step 1: Write the failing tests** (`fake_camera`, a temp DB and an injected `now`)
  - `test_first_tick_catches_up_seven_days_newest_first`
  - `test_second_tick_only_downloads_new_files`
  - `test_partial_download_is_discarded_and_retried`: the first tick has `drop_after_bytes` set, so there's no `downloaded` row and no `.part` file; the second tick, with no drop, downloads it.
  - `test_clock_fixed_when_off_by_more_than_two_minutes`: a camera clock 7 h ahead gives one `set_time_calls` entry.
  - `test_wrong_password_backs_off_ten_minutes`: one login attempt across ticks within 600 s, then another after that.
  - `test_rediscovers_camera_after_ip_change`: the injected `find` returns the new port or host, and `last_ip` is updated.
  - `test_low_disk_stops_downloads` (monkeypatched `shutil.disk_usage`)
- [ ] **Step 2: Run** `uv run pytest tests/ingest/test_watcher.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(ingest): watcher with catch-up, clock fix, back-off and discovery`.

### Task 8: Processor

**Files:**
- Create: `src/fatball/ingest/processor.py`, `tests/ingest/test_processor.py`

**Interfaces:**
- Consumes: `convert_clip`, `extract_jpeg`, `repo.*`
- Produces: `class Processor(settings, conn)` with `.process_pending() -> int`, which returns how many clips it processed.
  - For each `downloaded` clip it sets `processing`, then converts into `media_dir/clips/<clip_id>/`, then sets `ready` with the paths. Photos (`jpg`) go to `media_dir/photos/<clip_id>.jpg`.
  - On `ConversionFailed` it sets `failed` and **keeps the raw file**.
  - Plan 2 adds bird recognition and visit grouping after `ready`.

- [ ] **Step 1: Write the failing tests**
  - `test_processes_downloaded_clip_to_ready_with_paths(xm_clip_bytes)`
  - `test_failed_conversion_marks_failed_and_keeps_raw`
  - `test_processing_is_resumable_after_crash`: a clip stuck in `processing` at start-up goes back to `downloaded`.
- [ ] **Step 2: Run** `uv run pytest tests/ingest/test_processor.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(ingest): processor converts downloaded clips`.

### Task 9: API

**Files:**
- Create: `src/fatball/api/app.py`, `tests/api/test_api.py`

**Interfaces:**
- Consumes: `repo.*`, `Settings`, `secrets.set_password`
- Produces: `create_app(settings, conn) -> FastAPI` with these routes:
  - `GET /api/status` returns `{camera: {state: "ok"|"asleep"|"problem", last_seen_at, last_error}, queue: {downloaded, processing, failed}, disk: {free_bytes, low: bool}}`.
    - `ok` means seen within 1 h.
    - `asleep` means seen earlier today.
    - `problem` means anything else, or any `last_error`.
  - `GET /api/clips?limit=50&before=<iso>` returns ready clips, newest first, with media URLs. Plan 3 replaces this with visit endpoints.
  - `GET /media/{path}` serves files from `media_dir` only and supports HTTP Range. It returns 404 for paths that try to escape `media_dir`.
  - `PUT /api/setup` takes `{ip, password}` and stores the password through `secrets`. It answers **403 unless the request comes from the Mac itself**.

- [ ] **Step 1: Write the failing tests** (FastAPI `TestClient`)
  - `test_status_ok_asleep_problem`: drive `last_seen_at` and `last_error`.
  - `test_status_reports_low_disk`
  - `test_media_supports_range_requests`: `Range: bytes=0-99` gives a 206 with 100 bytes.
  - `test_media_rejects_path_traversal`: `/media/../library.sqlite` gives a 404.
  - `test_setup_forbidden_from_lan_ip`: a client host of `192.168.50.9` gives a 403.
  - `test_setup_password_never_in_db_or_logs(caplog)`
- [ ] **Step 2: Run** `uv run pytest tests/api -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Use `FileResponse`, or a small range handler if FastAPI's version can't do ranges.
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit** with the message `feat(api): status, clips, media with range, local-only setup`.

### Task 10: Service, CLI, LaunchAgent and demo mode

**Files:**
- Create: `src/fatball/cli.py`, `src/fatball/demo.py`, `scripts/install-launchagent.sh`, `tests/test_cli.py`, `tests/test_demo.py`

**Interfaces:**
- Consumes: everything above
- Produces:
  - `fatball serve [--host 0.0.0.0] [--port 8080]`: starts the Uvicorn API and runs `Watcher.run_forever` and a processor loop (every 2 s) in background threads.
  - `fatball setup`: prompts with `getpass` and calls `secrets.set_password`.
  - `fatball demo [--port 8080]` uses a temporary data dir. It starts a `FakeCamera` loaded with **12 generated clips over 2 days**, points the watcher at it, and serves the API, so the result looks exactly like real use.
  - `demo.build_demo_camera(n_clips: int, days: int) -> FakeCamera`
  - The `install-launchagent.sh` script writes `com.whoatethefatball.plist` (RunAtLoad, KeepAlive, logs in the data dir) and runs `launchctl bootstrap`.

- [ ] **Step 1: Write the failing tests**
  - `test_demo_ingests_all_clips_to_ready`: run the watcher and processor ticks on the demo camera; expect 12 `ready` clips.
  - `test_cli_help_lists_serve_demo_setup`
- [ ] **Step 2: Run** `uv run pytest tests/test_demo.py tests/test_cli.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Use `argparse`. Generated demo clips use ffmpeg `testsrc2` in different colours, so they look distinct.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: the whole suite passes.
- [ ] **Step 5: Run the demo by hand:** `uv run fatball demo`, then `curl localhost:8080/api/status` and `curl localhost:8080/api/clips`. Expected: status `ok` and 12 clips.
- [ ] **Step 6: Commit** with the message `feat: serve, setup and demo commands; LaunchAgent installer`.

### Task 11: Real-camera check, clean-up and README

**Files:**
- Delete: `camera_test.py`, `download_test.py`, `xm_convert.py`
- Modify: `README.md`
- Create: `docs/spikes/2026-11-wake-window-and-playback.md`

- [ ] **Step 1: Owner-run check with the real camera.** On the owner's Mac, run `uv run fatball setup`, then `uv run fatball serve`, and trigger motion at the feeder. Record in the spike doc:
  - the seconds between the camera becoming reachable and becoming unreachable, from watcher logs (spec spike 1)
  - whether `web.mp4` plays on the Android phone, iPad and Mac (spec spike 3)
  - the conversion time per clip
  - whether time query (1452) and time set (1450) work. If not, record the correct ids and fix `protocol.py` with a test.
  
  The spike doc must not include IPs, MAC addresses or serial numbers.
- [ ] **Step 2: Delete the three root scripts**, since their logic now lives in `fatball.camera` and `fatball.media`.
- [ ] **Step 3: Write the README for the portfolio:**
  - The problem.
  - What it does, with today's status: phase 1 foundation.
  - **How to run the demo:** `brew install ffmpeg uv`, `uv run fatball demo`.
  - An architecture diagram (Mermaid, matching spec §4).
  - The CI badge.
  - A design-process section linking the spec and `design/` (prototypes, critiques), with screenshots added in Plan 3.
  - A privacy note.
- [ ] **Step 4: Run** `uv run ruff check && uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** with the message `docs: README for portfolio, spike results; remove prototype scripts`.

---

## Next plans

- **Plan 2: Bird recognition and visits** (after spike 2: comparing models on about 50 real clips). Detector + classifier, category rules, visit grouping, guesses, new-species and champion logic, corrections with undo, and the visit, species and stats API.
- **Plan 3: Gallery (web app).** Svelte + Vite PWA implementing the prototypes with the Robin tokens, Playwright E2E tests in Chromium, WebKit and mobile, axe accessibility checks, screenshot tests, the Mac banner notifier, and README screenshots from demo mode.

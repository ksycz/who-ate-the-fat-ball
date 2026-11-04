"""The HTTP API: status, clips, visits (with corrections and undo), media, local-only setup and edit unlock."""

import base64
import binascii
import secrets as token_secrets
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

from fatball import secrets as camera_secrets
from fatball.api import auth as auth_mod
from fatball.api.auth import Auth
from fatball.config import Settings
from fatball.ingest.watcher import CAMERA_NAME
from fatball.library import cleanup, corrections, db, repo, stats, today, zips

STATIC_DIR = Path(__file__).parent / "static"
NOT_BUILT = "The gallery isn't built yet. Run: npm --prefix web ci && npm --prefix web run build"
# The service worker must always be re-fetched, or a stale one keeps serving an old app shell.
ROOT_FILE_OPTIONS = {
    "manifest.webmanifest": {"media_type": "application/manifest+json"},
    "sw.js": {"media_type": "text/javascript", "headers": {"Cache-Control": "no-cache"}},
}
RECENT = timedelta(hours=1)
# Watcher errors the owner has to fix: these turn the dot orange even if the camera was seen just now.
# Everything else (an interrupted download, a clock that could not be set...) is reported in last_error
# but leaves the dot to follow last_seen_at.
ACTIONABLE_ERRORS = frozenset(
    {"wrong_password", "account_locked", "no_password", "low_disk", "internal_error", "other_device"}
)
SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
}
_KIND_NAMES = {"h264": "video", "jpg": "photo"}
Pin = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}$")]


class SetupBody(BaseModel):
    ip: str | None = None
    password: str | None = None
    edit_pin: Pin | None = None


class UnlockBody(BaseModel):
    pin: str


class VisitPatch(BaseModel):
    """`species` present as null means 'no species'; absent means unchanged."""

    species: str | None = None
    category: Literal["birds", "other_animals", "other"] | None = None
    is_favourite: bool | None = None


class BulkPatch(BaseModel):
    visit_ids: Annotated[list[int], Field(min_length=1, max_length=500)]
    category: Literal["birds", "other_animals", "other"] | None = None
    is_favourite: bool | None = None


class DeleteBody(BaseModel):
    visit_ids: Annotated[list[int], Field(min_length=1, max_length=500)]


class ZipBody(BaseModel):
    """Either some visits, or a whole day (optionally one category and/or favourites only)."""

    visit_ids: Annotated[list[int], Field(min_length=1)] | None = None
    day: date | None = None
    category: Literal["birds", "other_animals", "other"] | None = None
    favourite: Literal[True] | None = None


ZIP_TOKEN_TTL = timedelta(minutes=10)
ZIP_TOKEN_MAX = 20


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _camera_state(cam: repo.Camera | None, now: datetime) -> str:
    """ok = seen within the hour; asleep = seen earlier today; problem = not seen today, or an actionable error."""
    if cam is None or cam.last_seen_at is None or cam.last_error in ACTIONABLE_ERRORS:
        return "problem"
    if now - cam.last_seen_at <= RECENT:
        return "ok"
    if cam.last_seen_at.astimezone().date() == now.date():
        return "asleep"
    return "problem"


def _media_url(path: str | None) -> str | None:
    return f"/media/{path}" if path else None


def _clip_json(c: repo.Clip) -> dict:
    return {
        "id": c.id,
        "begin_at": c.begin_at.isoformat(),
        "end_at": c.end_at.isoformat(),
        "kind": _KIND_NAMES.get(c.kind, c.kind),
        "duration_s": c.duration_s,
        "web_url": _media_url(c.web_path),
        "original_url": _media_url(c.original_path),
        "poster_url": _media_url(c.poster_path),
        "preview_url": _media_url(c.preview_path),
    }


def _visit_json(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "category": row["category"],
        "species": (
            {"scientific": row["species_scientific"], "name": row["species_name"]}
            if row["species_scientific"] else None
        ),
        "subject": row["subject"],
        "confidence": row["confidence"],
        "is_favourite": bool(row["is_favourite"]),
        "best_frame_url": _media_url(row["best_frame_path"]),
        "clip_count": row["clip_count"],
        "duration_s": row["duration_s"],
        "poster_url": _media_url(row["poster_path"]),
        "preview_url": _media_url(row["preview_path"]),
        "corrected": bool(row["corrected"]),
        "watched": row["watched_at"] is not None,
    }


def _encode_cursor(row: sqlite3.Row) -> str:
    return base64.urlsafe_b64encode(f"{row['started_at']}|{row['id']}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        started_at, _, visit_id = base64.urlsafe_b64decode(cursor.encode()).decode().rpartition("|")
        if not started_at:
            raise ValueError
        return started_at, int(visit_id)
    except (ValueError, binascii.Error):  # UnicodeDecodeError is a ValueError
        raise HTTPException(status_code=400, detail="invalid cursor") from None


def create_app(
    settings: Settings,
    *,
    now: Callable[[], datetime] = _local_now,
    model_loaded: Callable[[], bool] = lambda: False,
    static_dir: Path | None = None,
) -> FastAPI:
    """Build the API. `model_loaded` says whether the processor currently has a detector. Each request gets its own database connection (sqlite3 connections must not be
    shared across FastAPI's thread pool); the database is created up front so requests never race to."""
    db.connect(settings.db_path).close()
    app = FastAPI(title="Who Ate the Fat Ball?")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """No other site may frame the app: on the Mac every request may edit, so a framed gallery could
        be clicked through by a hostile page (clickjacking)."""
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response
    auth = Auth(lambda: db.connect(settings.db_path), lambda: now().astimezone())
    app.state.auth = auth

    def get_conn() -> Iterator[sqlite3.Connection]:
        conn = db.connect(settings.db_path)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def camera_json(conn: sqlite3.Connection) -> dict:
        cam = repo.get_camera(conn)
        return {
            "state": _camera_state(cam, now().astimezone()),
            "last_seen_at": cam.last_seen_at.isoformat() if cam and cam.last_seen_at else None,
            "last_error": cam.last_error if cam else None,
        }

    def now_json() -> str:
        """The server's time with its UTC offset, so the browser can tell how far its own clock is off."""
        t = now()
        return (t if t.tzinfo else t.astimezone()).isoformat(timespec="seconds")

    def can_retry(clip: repo.Clip) -> bool:
        """A ready clip can be recognised again; a failed one can be converted again while its raw file exists."""
        if clip.status == "ready":
            return True
        return clip.status == "failed" and bool(clip.raw_path) and (settings.media_dir / clip.raw_path).is_file()

    @app.get("/api/status")
    def status(conn: Conn, request: Request):
        free = shutil.disk_usage(settings.data_dir).free
        return {
            "day": now().astimezone().date().isoformat(),
            "now": now_json(),
            "local": auth_mod.is_local(request),
            "camera": camera_json(conn),
            "sorted": repo.sorted_counts(conn),
            "queue": repo.queue_counts(conn),
            "recognition": {
                **repo.recognition_counts(conn), "model": model_loaded(), "examples": repo.example_count(conn),
            },
            "disk": {"free_bytes": free, "low": free < settings.min_free_bytes},
        }

    @app.get("/api/today")
    def today_page(conn: Conn):
        day = now().astimezone().date()
        champ = today.champion(conn, day)
        return {
            "day": day.isoformat(),
            "now": now_json(),
            "summary": today.summary(conn, day),
            "champion": (
                {**{k: v for k, v in champ.items() if k != "best_frame_path"},
                 "best_frame_url": _media_url(champ["best_frame_path"])}
                if champ else None
            ),
            "new_species": today.new_species(conn),
            "visits": [_visit_json(r) for r in repo.list_visits(conn, None, day=day)],
            "checking": [_clip_json(c) for c in today.checking(conn, day)],
            "failed": [
                {"clip_id": c.id, "begin_at": c.begin_at.isoformat(), "can_retry": can_retry(c)}
                for c in today.failed(conn, day)
            ],
            "last_visitor": today.last_visitor(conn, day),
            "camera": camera_json(conn),
        }

    @app.get("/api/species")
    def species_list(conn: Conn, period: Literal["week", "month", "all"] | None = None):
        if period is not None:
            return [
                {**{k: v for k, v in r.items() if k != "photo_path"}, "photo_url": _media_url(r["photo_path"])}
                for r in stats.species_for_period(conn, now().astimezone().date(), period)
            ]
        return [
            {
                "scientific": r["scientific_name"], "name": r["name"], "group": r["grp"],
                "visits": r["visits"], "last_seen_at": r["last_seen_at"],
            }
            for r in repo.species_overview(conn)
        ]

    @app.get("/api/stats")
    def stats_page(conn: Conn, weeks: Annotated[int, Query(ge=1, le=52)] = 4):
        return stats.summary(conn, now().astimezone().date(), weeks)

    @app.get("/api/videos")
    def videos_feed(
        conn: Conn,
        limit: Annotated[int, Query(ge=1, le=200)] = 24,
        cursor: str | None = None,
        species: str | None = None,
    ):
        """Bird visits with a playable video, newest first; `filters` are the busiest species lately."""
        after = _decode_cursor(cursor) if cursor else None
        rows = stats.videos(conn, limit + 1, after, species)
        page = rows[:limit]
        return {
            "items": [
                {**_visit_json(r), "video_url": _media_url(r["video_path"]), "video_clip_id": r["video_clip_id"]}
                for r in page
            ],
            "next_cursor": _encode_cursor(page[-1]) if len(rows) > limit else None,
            "total": stats.videos_total(conn, species),
            "filters": stats.top_species(conn, now().astimezone().date()),
        }

    @app.get("/api/clips")
    def clips(conn: Conn, limit: Annotated[int, Query(ge=1, le=200)] = 50, before: datetime | None = None):
        rows = repo.list_clips(conn, limit, before, status="ready")
        return [_clip_json(c) for c in rows]

    @app.get("/api/visits")
    def visits(
        conn: Conn,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        cursor: str | None = None,
        category: Literal["birds", "other_animals", "other"] | None = None,
        species: str | None = None,
        day: date | None = None,
        favourite: bool | None = None,
        only: Literal["dogs", "empty"] | None = None,
    ):
        """Newest first. `day` is the local date of the visit's start (as stored). `only` narrows Other."""
        if only is not None and category != "other":
            raise HTTPException(status_code=422, detail="only goes with category=other")
        after = _decode_cursor(cursor) if cursor else None
        rows = repo.list_visits(
            conn, limit + 1, after=after, category=category, species=species, day=day, favourite=favourite,
            only=only,
        )
        page = rows[:limit]
        return {
            "items": [_visit_json(r) for r in page],
            "next_cursor": _encode_cursor(page[-1]) if len(rows) > limit else None,
        }

    @app.get("/api/visits/{visit_id}")
    def visit_detail(visit_id: int, conn: Conn):
        row = repo.get_visit(conn, visit_id)
        if row is None:
            raise HTTPException(status_code=404)
        return {
            **_visit_json(row),
            "clips": [_clip_json(c) for c in repo.clips_for_visit(conn, visit_id)],
            "guesses": [
                {"scientific": g["scientific_name"], "name": g["name"], "confidence": g["confidence"]}
                for g in repo.visit_guesses(conn, visit_id)
            ],
        }

    @app.post("/api/visits/{visit_id}/watched", status_code=204)
    def watched(visit_id: int, conn: Conn):
        """Watching is viewing, so no PIN: it only clears the new-species banner."""
        if not today.mark_watched(conn, visit_id, now().astimezone()):
            raise HTTPException(status_code=404)

    @app.post("/api/visits/bulk", dependencies=[Depends(auth_mod.require_editor)])
    def bulk_visits(body: BulkPatch, conn: Conn):
        """Move and/or favourite several visits; one undo token covers them all. A plain move teaches nothing."""
        if body.category is None and body.is_favourite is None:
            raise HTTPException(status_code=422, detail="give a category or is_favourite")
        change = corrections.Change(category=body.category, is_favourite=body.is_favourite, teach=False)
        try:
            token, changed = corrections.apply_many(conn, body.visit_ids, change, now().astimezone())
        except corrections.VisitNotFound:
            raise HTTPException(status_code=404) from None
        except corrections.InvalidChange as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        return {"undo_token": token, "changed": changed}

    @app.post("/api/visits/delete", dependencies=[Depends(auth_mod.require_editor)])
    def delete_visits(body: DeleteBody, conn: Conn):
        """Delete empty clips for good (their files too; the camera's copy is not fetched again)."""
        try:
            n = cleanup.delete_empty_visits(conn, settings.media_dir, body.visit_ids, now().astimezone())
        except cleanup.VisitNotFound:
            raise HTTPException(status_code=404) from None
        except cleanup.NotEmpty:
            raise HTTPException(status_code=409, detail="Only empty clips can be deleted") from None
        return {"deleted": n}

    @app.patch("/api/visits/{visit_id}", dependencies=[Depends(auth_mod.require_editor)])
    def patch_visit(visit_id: int, body: VisitPatch, conn: Conn):
        change = corrections.Change(
            species=body.species if "species" in body.model_fields_set else corrections.UNSET,
            category=body.category,
            is_favourite=body.is_favourite,
        )
        try:
            return {"undo_token": corrections.apply(conn, visit_id, change, now().astimezone())}
        except corrections.VisitNotFound:
            raise HTTPException(status_code=404) from None
        except corrections.InvalidChange as e:
            raise HTTPException(status_code=422, detail=str(e)) from None

    @app.post("/api/undo/{token}", status_code=204, dependencies=[Depends(auth_mod.require_editor)])
    def undo(token: str, conn: Conn):
        try:
            corrections.undo(conn, token, now().astimezone())
        except corrections.UnknownToken:
            raise HTTPException(status_code=404) from None

    @app.post("/api/retry/{clip_id}", status_code=204, dependencies=[Depends(auth_mod.require_editor)])
    def retry(clip_id: int, conn: Conn):
        """Recognise a ready clip again, or convert a failed one again while its raw file exists; 409 otherwise."""
        clip = repo.get_clip(conn, clip_id)
        if clip is None:
            raise HTTPException(status_code=404)
        if not can_retry(clip):
            raise HTTPException(status_code=409, detail=f"clip is {clip.status} and cannot be retried")
        if clip.status == "failed":
            repo.set_clip_status(conn, clip_id, "downloaded")
        else:
            repo.requeue_recognition(conn, clip_id)

    zip_lock = threading.Lock()  # sync endpoints run in a thread pool
    zip_plans: dict[str, tuple[datetime, zips.ZipPlan]] = {}  # token -> (expires, plan); pruned on each POST

    @app.post("/api/downloads/zip")
    def make_zip(body: ZipBody, conn: Conn):
        """Plan a .zip and say how big it is; the browser then fetches the token. Downloading is viewing: no PIN."""
        if (body.visit_ids is None) == (body.day is None):
            raise HTTPException(status_code=422, detail="give visit_ids or a day")
        try:
            plan = zips.plan_zip(
                conn, settings.media_dir, visit_ids=body.visit_ids, day=body.day, category=body.category,
                favourite=body.favourite,
            )
        except zips.TooMany as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        except zips.NothingToDownload:
            raise HTTPException(status_code=404, detail="Nothing to download") from None
        t = now()
        token = token_secrets.token_urlsafe(16)
        with zip_lock:
            for k in [k for k, (expires, _) in zip_plans.items() if expires <= t]:
                del zip_plans[k]
            while len(zip_plans) >= ZIP_TOKEN_MAX:
                del zip_plans[next(iter(zip_plans))]  # dicts keep insertion order: the oldest goes
            zip_plans[token] = (t + ZIP_TOKEN_TTL, plan)
        return {
            "token": token, "size_bytes": plan.size_bytes, "visits": plan.visits, "files": len(plan.entries),
            "filename": plan.filename,
        }

    @app.get("/api/downloads/zip/{token}")
    def download_zip(token: str):
        with zip_lock:
            entry = zip_plans.get(token)
        if entry is None or entry[0] <= now():
            raise HTTPException(status_code=404)
        plan = entry[1]
        return StreamingResponse(
            zips.stream_zip(plan), media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{plan.filename}"'},
        )

    @app.get("/media/{path:path}")
    def media(path: str):
        root = settings.media_dir.resolve()
        try:
            target = (root / path).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                raise HTTPException(status_code=404)
        except (ValueError, OSError):
            raise HTTPException(status_code=404) from None
        return FileResponse(target)  # Starlette answers Range requests with 206

    @app.put("/api/setup", status_code=204)
    def setup(body: SetupBody, request: Request, conn: Conn):
        if not auth_mod.is_local(request):
            raise HTTPException(status_code=403, detail="setup only works from the Mac itself")
        if body.ip is not None:
            repo.set_camera_ip(conn, CAMERA_NAME, body.ip)
        if body.password is not None:
            camera_secrets.set_password(body.password)
        if body.edit_pin is not None:
            auth.set_edit_pin(body.edit_pin)

    @app.post("/api/unlock", status_code=204)
    def unlock(body: UnlockBody, request: Request, response: Response):
        ip = request.client.host if request.client else "unknown"
        try:
            token = auth.try_unlock(ip, body.pin)
        except auth_mod.Locked:
            raise HTTPException(status_code=429, detail="too many wrong PINs; try again later") from None
        if token is None:
            raise HTTPException(status_code=401, detail="wrong PIN")
        response.set_cookie(
            auth_mod.COOKIE,
            token,
            max_age=auth_mod.COOKIE_MAX_AGE_S,
            httponly=True,
            samesite="strict",
            path="/",
        )

    @app.get("/api/me")
    def me(request: Request):
        return {"can_edit": auth_mod.can_edit(request)}

    # The gallery: registered after every API route so /api/* and /media/* 404s stay JSON.
    static_root = (static_dir or STATIC_DIR).resolve()
    app.mount("/assets", StaticFiles(directory=static_root / "assets", check_dir=False), name="assets")

    @app.exception_handler(405)
    async def method_not_allowed(request: Request, exc: StarletteHTTPException):
        """Only the GET-only gallery fallback matched this path: the URL is unknown, so a JSON 404.
        A wrong method on a real route stays a 405."""
        for route in app.routes:
            if getattr(route, "path", None) != "/{path:path}" and route.matches(request.scope)[0] != Match.NONE:
                return await http_exception_handler(request, exc)
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    @app.get("/{path:path}", include_in_schema=False)
    def gallery(path: str):
        if "\0" in path or path.split("/")[0] in ("api", "media"):
            raise HTTPException(status_code=404)
        # Root files from web/public (manifest, service worker, icons); never anything outside the static dir.
        if path and "/" not in path:
            target = (static_root / path).resolve()
            if target.parent == static_root and target.name != "index.html" and target.is_file():
                return FileResponse(target, **ROOT_FILE_OPTIONS.get(path, {}))
        index = static_root / "index.html"
        if not index.is_file():
            return PlainTextResponse(NOT_BUILT, status_code=503)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})  # a stale shell would pin old assets

    return app



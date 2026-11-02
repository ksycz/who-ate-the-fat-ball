"""The HTTP API: status, clips, visits (with corrections and undo), media, local-only setup and edit unlock."""

import base64
import binascii
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints

from fatball import secrets as camera_secrets
from fatball.api import auth as auth_mod
from fatball.api.auth import Auth
from fatball.config import Settings
from fatball.ingest.watcher import CAMERA_NAME
from fatball.library import corrections, db, repo, today

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
ACTIONABLE_ERRORS = frozenset({"wrong_password", "account_locked", "no_password", "low_disk", "internal_error"})
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

    def can_retry(clip: repo.Clip) -> bool:
        """A ready clip can be recognised again; a failed one can be converted again while its raw file exists."""
        if clip.status == "ready":
            return True
        return clip.status == "failed" and bool(clip.raw_path) and (settings.media_dir / clip.raw_path).is_file()

    @app.get("/api/status")
    def status(conn: Conn):
        free = shutil.disk_usage(settings.data_dir).free
        return {
            "day": now().astimezone().date().isoformat(),
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
            "summary": today.summary(conn, day),
            "champion": (
                {**{k: v for k, v in champ.items() if k != "best_frame_path"},
                 "best_frame_url": _media_url(champ["best_frame_path"])}
                if champ else None
            ),
            "new_species": today.new_species(conn),
            "visits": [_visit_json(r) for r in repo.list_visits(conn, 100_000, day=day)],
            "checking": [_clip_json(c) for c in today.checking(conn, day)],
            "failed": [
                {"clip_id": c.id, "begin_at": c.begin_at.isoformat(), "can_retry": can_retry(c)}
                for c in today.failed(conn, day)
            ],
            "last_visitor": today.last_visitor(conn, day),
            "camera": camera_json(conn),
        }

    @app.get("/api/species")
    def species_list(conn: Conn):
        return [
            {
                "scientific": r["scientific_name"], "name": r["name"], "group": r["grp"],
                "visits": r["visits"], "last_seen_at": r["last_seen_at"],
            }
            for r in repo.species_overview(conn)
        ]

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
    ):
        """Newest first. `day` is the local date of the visit's start (as stored)."""
        after = _decode_cursor(cursor) if cursor else None
        rows = repo.list_visits(
            conn, limit + 1, after=after, category=category, species=species, day=day, favourite=favourite,
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
            repo.upsert_camera(conn, CAMERA_NAME, None, body.ip)
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

    @app.get("/{path:path}", include_in_schema=False)
    def gallery(path: str):
        if path.split("/")[0] in ("api", "media"):
            raise HTTPException(status_code=404)
        # Root files from web/public (manifest, service worker, icons); never anything outside the static dir.
        if path and "/" not in path:
            target = (static_root / path).resolve()
            if target.parent == static_root and target.name != "index.html" and target.is_file():
                return FileResponse(target, **ROOT_FILE_OPTIONS.get(path, {}))
        index = static_root / "index.html"
        if not index.is_file():
            return PlainTextResponse(NOT_BUILT, status_code=503)
        return FileResponse(index)

    return app



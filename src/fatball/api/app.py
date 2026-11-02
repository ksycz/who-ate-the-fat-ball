"""The HTTP API: status, clips, media, local-only setup and edit unlock."""

import shutil
import sqlite3
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, StringConstraints

from fatball import secrets as camera_secrets
from fatball.api import auth as auth_mod
from fatball.api.auth import Auth
from fatball.config import Settings
from fatball.ingest.watcher import CAMERA_NAME
from fatball.library import db, repo

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


def create_app(
    settings: Settings,
    *,
    now: Callable[[], datetime] = _local_now,
    model_loaded: Callable[[], bool] = lambda: False,
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

    @app.get("/api/status")
    def status(conn: Conn):
        current = now().astimezone()
        cam = repo.get_camera(conn)
        free = shutil.disk_usage(settings.data_dir).free
        return {
            "camera": {
                "state": _camera_state(cam, current),
                "last_seen_at": cam.last_seen_at.isoformat() if cam and cam.last_seen_at else None,
                "last_error": cam.last_error if cam else None,
            },
            "queue": repo.queue_counts(conn),
            "recognition": {**repo.recognition_counts(conn), "model": model_loaded()},
            "disk": {"free_bytes": free, "low": free < settings.min_free_bytes},
        }

    @app.get("/api/clips")
    def clips(conn: Conn, limit: Annotated[int, Query(ge=1, le=200)] = 50, before: datetime | None = None):
        rows = repo.list_clips(conn, limit, before, status="ready")
        return [
            {
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
            for c in rows
        ]

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

    return app



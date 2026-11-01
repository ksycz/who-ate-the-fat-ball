"""The HTTP API: status, clips, media, local-only setup and edit unlock."""

import shutil
import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, StringConstraints

from fatball import secrets as camera_secrets
from fatball.api import auth as auth_mod
from fatball.api.auth import Auth
from fatball.config import Settings
from fatball.ingest.watcher import CAMERA_NAME
from fatball.library import repo

RECENT = timedelta(hours=1)
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
    if cam is None or cam.last_seen_at is None or cam.last_error:
        return "problem"
    if now - cam.last_seen_at <= RECENT:
        return "ok"
    if cam.last_seen_at.astimezone().date() == now.date():
        return "asleep"
    return "problem"


def _media_url(path: str | None) -> str | None:
    return f"/media/{path}" if path else None


def create_app(
    settings: Settings, conn: sqlite3.Connection, *, now: Callable[[], datetime] = _local_now
) -> FastAPI:
    """Build the API. Writes to `conn` made here hold a lock, but that only orders this app's own writes;
    it does not make a connection shared with other code safe, so give the API its own connection."""
    app = FastAPI(title="Who Ate the Fat Ball?")
    lock = threading.Lock()
    auth = Auth(conn, lambda: now().astimezone(), lock)
    app.state.auth = auth

    @app.get("/api/status")
    def status():
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
            "disk": {"free_bytes": free, "low": free < settings.min_free_bytes},
        }

    @app.get("/api/clips")
    def clips(limit: Annotated[int, Query(ge=1, le=200)] = 50, before: datetime | None = None):
        rows = repo.list_clips(conn, limit, before, status="ready")
        return [
            {
                "id": c.id,
                "begin_at": c.begin_at.isoformat(),
                "end_at": c.end_at.isoformat(),
                "kind": c.kind,
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
    def setup(body: SetupBody, request: Request):
        if not auth_mod.is_local(request):
            raise HTTPException(status_code=403, detail="setup only works from the Mac itself")
        with lock:
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



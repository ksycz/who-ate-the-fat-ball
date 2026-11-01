"""Polls the camera, catches up on missed clips and downloads new ones (newest first)."""

import logging
import shutil
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fatball import secrets
from fatball.camera import discovery
from fatball.camera.client import (
    AccountLocked,
    CameraError,
    CameraUnreachable,
    DownloadInterrupted,
    RemoteFile,
    WrongPassword,
    XMClient,
)
from fatball.config import Settings
from fatball.library import repo

log = logging.getLogger(__name__)

CAMERA_NAME = "feeder"
CAMERA_USER = "admin"
# A clip begun just before midnight is filed under yesterday but may only appear once it has been written,
# so a clean tick counts as covering "now minus this" rather than now.
LISTING_GRACE = timedelta(minutes=10)
MAX_DOWNLOAD_FAILURES = 3
KIND = "h264"


@dataclass(frozen=True)
class TickResult:
    reachable: bool
    downloaded: int
    error: str | None


class _LowDisk(Exception):
    pass


class Watcher:
    def __init__(
        self,
        settings: Settings,
        conn: sqlite3.Connection,
        *,
        connect: Callable[..., XMClient] = XMClient,
        now: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], None] = time.sleep,
        find: Callable[[str, int, str | None], str | None] = discovery.find_camera,
        password: Callable[[], str | None] = secrets.get_password,
        client_timeout: float = 8.0,
        silence_s: float = 6.0,
        probe_timeout: float = 1.0,
        discovery_interval_s: float = 60.0,
    ) -> None:
        self.settings, self.conn = settings, conn
        self._connect, self._now, self._sleep, self._find, self._password = connect, now, sleep, find, password
        self._client_timeout, self._silence_s = client_timeout, silence_s
        self._probe_timeout, self._discovery_interval_s = probe_timeout, discovery_interval_s
        self._covered_through: date | None = None  # files up to the start of this day are known
        self._failures: dict[tuple[str, datetime], int] = {}
        self._backoff_until: datetime | None = None
        self._backoff_reason = "wrong_password"
        self._last_discovery: datetime | None = None
        self._stop = threading.Event()

    # public API
    def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # keep polling whatever goes wrong in one tick
                self._record_internal_error()
                log.exception("watcher tick failed")
            self._sleep(self.settings.poll_interval_s)

    def stop(self) -> None:
        self._stop.set()

    def _record_internal_error(self) -> None:
        try:
            camera = repo.get_camera(self.conn)
            if camera is not None:
                repo.update_camera_status(self.conn, camera.id, last_error="internal_error")
        except Exception:
            log.exception("could not record the watcher error")

    def tick(self) -> TickResult:
        now = self._local_now()
        if self._backoff_until is not None:
            if now < self._backoff_until:
                return TickResult(False, 0, self._backoff_reason)
            self._backoff_until = None

        camera = repo.get_camera(self.conn)
        if camera is None:
            repo.upsert_camera(self.conn, CAMERA_NAME, None, None)
            camera = repo.get_camera(self.conn)
            assert camera is not None
        camera_id = camera.id
        password = self._password()
        if password is None:
            repo.update_camera_status(self.conn, camera_id, last_error="no_password")
            return TickResult(False, 0, "no_password")

        host = self._locate(camera, now)
        if host is None:
            return TickResult(False, 0, None)
        repo.update_camera_status(self.conn, camera_id, last_seen_at=now, last_ip=host)

        downloaded = 0
        error: str | None = None
        try:
            with self._connect(host, self.settings.camera_port, self._client_timeout,
                               silence_s=self._silence_s) as client:
                client.login(CAMERA_USER, password)
                clock_ok = self._fix_clock(client, camera_id, now)
                files = self._unknown_files(client, now)
                for f in files:
                    downloaded += self._download(client, camera_id, f)
                self._covered_through = (now - LISTING_GRACE).date()
                if not clock_ok:
                    error = "clock_error"
        except (WrongPassword, AccountLocked) as e:
            error = "wrong_password" if isinstance(e, WrongPassword) else "account_locked"
            self._backoff_reason = error
            self._backoff_until = now + timedelta(seconds=self.settings.wrong_password_backoff_s)
            log.warning("camera login refused (%s); retrying in %d s", error,
                        self.settings.wrong_password_backoff_s)
        except _LowDisk:
            error = "low_disk"
            log.warning("free disk space below %d bytes; downloads paused", self.settings.min_free_bytes)
        except DownloadInterrupted as e:
            error = "download_interrupted"
            log.info("download interrupted, will retry: %s", e)
        except CameraUnreachable as e:
            error = "unreachable"
            log.info("camera went away mid-tick: %s", e)
        except CameraError as e:
            error = "camera_error"
            log.warning("camera error: %s", e)

        if error is None:
            repo.update_camera_status(self.conn, camera_id, clear_error=True)
        else:
            repo.update_camera_status(self.conn, camera_id, last_error=error)
        return TickResult(True, downloaded, error)

    # steps
    def _local_now(self) -> datetime:
        now = self._now()
        return now.astimezone().replace(tzinfo=None) if now.tzinfo else now

    def _locate(self, camera: repo.Camera, now: datetime) -> str | None:
        """The camera's address if it answers a TCP connect; otherwise try discovery (rate-limited)."""
        port = self.settings.camera_port
        if camera.last_ip and discovery.is_open(camera.last_ip, port, self._probe_timeout):
            return camera.last_ip
        if (self._last_discovery is not None
                and (now - self._last_discovery).total_seconds() < self._discovery_interval_s):
            return None
        self._last_discovery = now
        subnet = camera.last_ip or discovery.local_ipv4()
        if subnet is None:
            return None
        found = self._find(subnet, port, camera.mac)
        if found is None or not discovery.is_open(found, port, self._probe_timeout):
            return None
        log.info("camera rediscovered at %s", found)
        return found

    def _fix_clock(self, client: XMClient, camera_id: int, now: datetime) -> bool:
        """Best effort (the time message ids are unverified on the real camera). False if it failed."""
        try:
            offset = (client.camera_time() - now).total_seconds()
            if abs(offset) > self.settings.clock_tolerance_s:
                log.info("camera clock off by %.0f s; setting it", offset)
                client.set_time(self._local_now())
                offset = 0.0  # the camera now matches our clock
        except CameraUnreachable:
            raise
        except (CameraError, KeyError, ValueError, TypeError) as e:
            log.warning("could not check or set the camera clock: %r", e)
            return False
        repo.update_camera_status(self.conn, camera_id, clock_offset_s=offset)
        return True

    def _days(self, now: datetime) -> list[date]:
        """Every day since the last clean tick (all of the catch-up window before the first), newest first."""
        today = now.date()
        oldest = today - timedelta(days=self.settings.catchup_days)
        if self._covered_through is not None:
            oldest = max(oldest, min(self._covered_through, today))
        return [today - timedelta(days=n) for n in range((today - oldest).days + 1)]

    def _unknown_files(self, client: XMClient, now: datetime) -> list[RemoteFile]:
        unknown: list[RemoteFile] = []
        for day in self._days(now):
            known = repo.known_clip_keys(self.conn, day)
            unknown += [f for f in client.list_files(day, KIND) if (f.sd_path, f.begin) not in known
                        and self._failures.get((f.sd_path, f.begin), 0) < MAX_DOWNLOAD_FAILURES]
        return sorted(unknown, key=lambda f: f.begin, reverse=True)

    def _download(self, client: XMClient, camera_id: int, f: RemoteFile) -> int:
        raw_dir = self.settings.media_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        # client.download reports local write errors as CameraUnreachable, so check space up front.
        if shutil.disk_usage(raw_dir).free < self.settings.min_free_bytes:
            raise _LowDisk
        clip_id = repo.add_clip(self.conn, camera_id, f.sd_path, f.begin, f.end, f.kind, f.size_kb * 1024)
        if clip_id is None:  # appeared since we listed
            return 0
        dest = raw_dir / f"{clip_id}.raw"
        try:
            size = client.download(f, dest)
        except BaseException:
            repo.delete_clip(self.conn, clip_id)  # forget it so the next wake retries
            dest.unlink(missing_ok=True)
            key = (f.sd_path, f.begin)
            self._failures[key] = self._failures.get(key, 0) + 1
            if self._failures[key] == MAX_DOWNLOAD_FAILURES:
                log.warning("giving up on %s after %d failed downloads", f.sd_path, MAX_DOWNLOAD_FAILURES)
            raise
        repo.set_clip_status(self.conn, clip_id, "downloaded", raw_path=str(dest))
        log.info("downloaded %s (%d bytes) as clip %d", f.sd_path, size, clip_id)
        return 1

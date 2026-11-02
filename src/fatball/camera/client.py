"""Client for the Xiongmai DVRIP protocol: login, file listing, download, clock."""

import socket
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Self

from fatball.camera.protocol import (
    FILE_QUERY,
    HEADER,
    LOGIN,
    MODIFY_PASSWORD,
    PLAY_CLAIM,
    PLAY_DATA,
    PLAY_REQ,
    SYSINFO,
    TIME_QUERY,
    TIME_SET,
    decode_header,
    decode_payload,
    encode,
    sofia_hash,
)

_TIME_FMT = "%Y-%m-%d %H:%M:%S"
_WRONG_PASSWORD = {203, 205}
_LOCKED = 206
# The real camera's FileLength over-reports by ~1%, so a complete file can be a bit under size_kb*1024.
MIN_COMPLETE_RATIO = 0.9
QUERY_PAGE_SIZE = 64  # the camera returns at most this many files per query


class CameraError(Exception):
    """Base class for camera problems."""


class WrongPassword(CameraError):
    pass


class AccountLocked(CameraError):
    pass


class CameraUnreachable(CameraError):
    pass


class DownloadInterrupted(CameraError):
    pass


@dataclass(frozen=True)
class RemoteFile:
    sd_path: str
    begin: datetime
    end: datetime
    size_kb: int
    kind: str


class _Conn:
    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)

    def send(self, session: int, seq: int, msg_id: int, payload: dict) -> None:
        self.sock.sendall(encode(session, seq, msg_id, payload))

    def read_packet(self) -> tuple[int, bytes]:
        """Return (msg_id, body). Raises ConnectionError if the peer closed."""
        _, msg_id, length = decode_header(self._read(HEADER.size))
        return msg_id, self._read(length) if length else b""

    def _read(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("camera closed the connection")
            buf += chunk
        return bytes(buf)

    def close(self) -> None:
        self.sock.close()


class XMClient:
    def __init__(self, host: str, port: int = 34567, timeout: float = 8.0, *, silence_s: float = 6.0) -> None:
        self.host, self.port, self.timeout, self.silence_s = host, port, timeout, silence_s
        self._conn: _Conn | None = None
        self._session = 0
        self._seq = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # plumbing
    def _connect(self) -> _Conn:
        try:
            return _Conn(self.host, self.port, self.timeout)
        except OSError as e:  # includes timeouts
            raise CameraUnreachable(str(e)) from e

    def _sid(self) -> str:
        return f"0x{self._session:08X}"

    def _request(self, msg_id: int, payload: dict) -> dict:
        if self._conn is None:
            self._conn = self._connect()
        self._seq += 1
        try:
            self._conn.send(self._session, self._seq, msg_id, payload)
            _, body = self._conn.read_packet()
        except OSError as e:
            raise CameraUnreachable(str(e)) from e
        return decode_payload(body)

    # API
    def login(self, user: str, password: str) -> None:
        reply = self._request(LOGIN, {"EncryptType": "MD5", "LoginType": "DVRIP-Web",
                                      "PassWord": sofia_hash(password), "UserName": user})
        ret = reply.get("Ret")
        if ret in _WRONG_PASSWORD:
            raise WrongPassword(f"camera refused the password (Ret {ret})")
        if ret == _LOCKED:
            raise AccountLocked("camera account is locked")
        if ret != 100:
            raise CameraError(f"login failed (Ret {ret})")
        self._session = int(reply["SessionID"], 16)

    def change_password(self, user: str, old: str, new: str) -> None:
        """Give `user` a new password (needs a login first). Raises WrongPassword if `old` is wrong."""
        reply = self._request(MODIFY_PASSWORD, {"EncryptType": "MD5", "NewPassWord": sofia_hash(new),
                                                "PassWord": sofia_hash(old), "SessionID": self._sid(),
                                                "UserName": user})
        ret = reply.get("Ret")
        if ret in _WRONG_PASSWORD:
            raise WrongPassword(f"camera refused the old password (Ret {ret})")
        if ret != 100:
            raise CameraError(f"password change failed (Ret {ret})")

    def system_info(self) -> dict:
        reply = self._request(SYSINFO, {"Name": "SystemInfo", "SessionID": self._sid()})
        return reply.get("SystemInfo", {})

    def list_files(self, day: date, kind: Literal["h264", "jpg"]) -> list[RemoteFile]:
        """Every file of `kind` that began on `day`, oldest first.

        The camera answers at most 64 entries per query (oldest first), so a full page is followed by
        another query starting at the last entry's begin time (inclusive), de-duplicated on
        (sd_path, begin), until a page is short or adds nothing new.
        """
        found: dict[tuple[str, datetime], RemoteFile] = {}
        begin = f"{day:%Y-%m-%d} 00:00:00"
        while True:
            page = self._query_files(begin, f"{day:%Y-%m-%d} 23:59:59", kind)
            new = [f for f in page if (f.sd_path, f.begin) not in found]
            for f in new:
                found[(f.sd_path, f.begin)] = f
            if len(page) < QUERY_PAGE_SIZE or not new:
                break
            begin = page[-1].begin.strftime(_TIME_FMT)
        return sorted(found.values(), key=lambda f: f.begin)

    def _query_files(self, begin: str, end: str, kind: str) -> list[RemoteFile]:
        reply = self._request(FILE_QUERY, {
            "Name": "OPFileQuery",
            "OPFileQuery": {"BeginTime": begin, "EndTime": end,
                            "Channel": 0, "DriverTypeMask": "0x0000FFFF", "Event": "*", "Type": kind},
            "SessionID": self._sid(),
        })
        return [RemoteFile(sd_path=e["FileName"],
                           begin=datetime.strptime(e["BeginTime"], _TIME_FMT),
                           end=datetime.strptime(e["EndTime"], _TIME_FMT),
                           size_kb=int(e["FileLength"], 16), kind=kind)
                for e in reply.get("OPFileQuery") or []]

    def _playback(self, action: str, f: RemoteFile) -> dict:
        return {"Name": "OPPlayBack",
                "OPPlayBack": {"Action": action,
                               "Parameter": {"PlayMode": "ByName", "FileName": f.sd_path, "StreamType": 0,
                                             "Value": 0, "TransMode": "TCP"},
                               "StartTime": f.begin.strftime(_TIME_FMT), "EndTime": f.end.strftime(_TIME_FMT)},
                "SessionID": self._sid()}

    def download(self, f: RemoteFile, dest: Path) -> int:
        expected = f.size_kb * 1024
        part = dest.with_suffix(dest.suffix + ".part")
        data_conn = self._connect()
        total = 0
        try:
            # The claim opens the data channel; its reply may only come once the download starts.
            self._seq += 1
            data_conn.send(self._session, self._seq, PLAY_CLAIM, self._playback("Claim", f))
            self._request(PLAY_REQ, self._playback("DownloadStart", f))
            data_conn.sock.settimeout(self.silence_s)
            with part.open("wb") as out:
                while True:
                    try:
                        msg_id, body = data_conn.read_packet()
                    except (TimeoutError, ConnectionError):
                        break
                    if not body:
                        break
                    if msg_id != PLAY_DATA:  # JSON status message, not media
                        continue
                    out.write(body)
                    total += len(body)
                    if expected and total >= expected * 1.5:
                        break
            self._stop_download(f)
        except OSError as e:
            part.unlink(missing_ok=True)
            raise CameraUnreachable(str(e)) from e
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        finally:
            data_conn.close()
        if f.size_kb > 0 and total < expected * MIN_COMPLETE_RATIO:
            part.unlink(missing_ok=True)
            raise DownloadInterrupted(f"got {total} of {expected} bytes for {f.sd_path}")
        part.replace(dest)
        return total

    def _stop_download(self, f: RemoteFile) -> None:
        try:
            self._request(PLAY_REQ, self._playback("DownloadStop", f))
        except CameraError:
            pass

    def camera_time(self) -> datetime:
        reply = self._request(TIME_QUERY, {"Name": "OPTimeQuery", "SessionID": self._sid()})
        return datetime.strptime(reply["OPTimeQuery"], _TIME_FMT)

    def set_time(self, dt: datetime) -> None:
        self._request(TIME_SET, {"Name": "OPTimeSetting", "OPTimeSetting": dt.strftime(_TIME_FMT),
                                 "SessionID": self._sid()})

"""An in-process fake Xiongmai camera that speaks the same wire protocol as the real one.

Used by the client tests, the watcher tests and `fatball demo`.
"""

import socket
import socketserver
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Self

from fatball.camera.protocol import (
    FILE_QUERY,
    HEADER,
    LOGIN,
    PLAY_CLAIM,
    PLAY_DATA,
    PLAY_REQ,
    SYSINFO,
    TIME_QUERY,
    TIME_SET,
    decode_payload,
    encode,
    sofia_hash,
)

SESSION_ID = 0x0B
MAX_QUERY_RESULTS = 64
CHUNK = 32 * 1024
STATUS_ID = 1425  # JSON status the real camera sends before the media packets
_TIME_FMT = "%Y-%m-%d %H:%M:%S"


@dataclass
class FakeFile:
    begin: datetime
    end: datetime
    kind: Literal["h264", "jpg"]
    payload: bytes

    @property
    def sd_path(self) -> str:
        return (f"/mnt/sd0/{self.begin:%Y-%m-%d}/001/"
                f"{self.begin:%H.%M.%S}-{self.end:%H.%M.%S}[A][@7][0](0).{self.kind}")


class _Claim:
    def __init__(self) -> None:
        self.start = threading.Event()


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False

    def __init__(self, port: int, owner: "FakeCamera") -> None:
        self.owner = owner
        super().__init__(("127.0.0.1", port), _Handler)


class _Handler(socketserver.BaseRequestHandler):
    server: _Server

    def handle(self) -> None:
        cam = self.server.owner
        cam._track(self.request)
        try:
            while True:
                header = self._recv(HEADER.size)
                if header is None:
                    return
                _, _, session, seq, msg_id, length = HEADER.unpack(header)
                body = self._recv(length) if length else b""
                if body is None:
                    return
                if msg_id == PLAY_CLAIM:
                    self._claim(session, decode_payload(body))
                    return
                reply = cam._dispatch(session, seq, msg_id, decode_payload(body))
                if reply is not None:
                    self.request.sendall(reply)
        except OSError:
            pass
        finally:
            cam._untrack(self.request)

    def _recv(self, n: int) -> bytes | None:
        buf = b""
        while len(buf) < n:
            chunk = self.request.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _claim(self, session: int, payload: dict) -> None:
        """Data connection: wait for DownloadStart on the main one, then stream the file."""
        cam = self.server.owner
        name = payload["OPPlayBack"]["Parameter"]["FileName"]
        claim = _Claim()
        with cam._lock:
            cam._claims[name] = claim
        try:
            if not claim.start.wait(10) or cam._stopping.is_set():
                return
            file = cam._find(name)
            if file is None:
                return
            self.request.sendall(encode(session, 0, STATUS_ID, {"Name": "OPPlayBack", "Ret": 100}))
            limit = cam.drop_after_bytes
            sent = 0
            data = file.payload
            while sent < len(data) and (limit is None or sent < limit):
                end = min(sent + CHUNK, len(data))
                if limit is not None:
                    end = min(end, limit)
                self.request.sendall(encode_raw(session, PLAY_DATA, data[sent:end]))
                sent = end
        finally:
            with cam._lock:
                if cam._claims.get(name) is claim:
                    del cam._claims[name]


def encode_raw(session: int, msg_id: int, data: bytes) -> bytes:
    """A packet whose body is raw media bytes (no JSON, no terminator)."""
    return HEADER.pack(0xFF, 0, session, 0, msg_id, len(data)) + data


class FakeCamera:
    def __init__(self, password: str = "", files: list[FakeFile] | None = None,
                 clock: datetime | None = None) -> None:
        self.password = password
        self.files: list[FakeFile] = list(files or [])
        self.clock = clock or datetime.now().replace(microsecond=0)
        self.set_time_calls: list[datetime] = []
        self.login_attempts = 0
        self.drop_after_bytes: int | None = None
        self._lock = threading.Lock()
        self._claims: dict[str, _Claim] = {}
        self._conns: set[socket.socket] = set()
        self._stopping = threading.Event()
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self.port = 0
        self._awake = False

    # lifecycle
    def __enter__(self) -> Self:
        self.awake = True
        return self

    def __exit__(self, *exc) -> None:
        self._stopping.set()
        self._sleep()

    @property
    def awake(self) -> bool:
        return self._awake

    @awake.setter
    def awake(self, value: bool) -> None:
        if value and not self._awake:
            self._wake()
        elif not value and self._awake:
            self._sleep()

    def _wake(self) -> None:
        self._stopping.clear()
        self._server = _Server(self.port, self)  # port 0 the first time, then the same port again
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._awake = True

    def _sleep(self) -> None:
        server, thread = self._server, self._thread
        self._server = self._thread = None
        self._awake = False
        if server is None or thread is None:
            return
        server.shutdown()
        thread.join()
        server.server_close()
        with self._lock:
            conns = list(self._conns)
            for claim in self._claims.values():
                claim.start.set()
        self._stopping.set()
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def add_file(self, f: FakeFile) -> None:
        with self._lock:
            self.files.append(f)

    # internals
    def _track(self, conn: socket.socket) -> None:
        with self._lock:
            self._conns.add(conn)

    def _untrack(self, conn: socket.socket) -> None:
        with self._lock:
            self._conns.discard(conn)

    def _find(self, sd_path: str) -> FakeFile | None:
        with self._lock:
            return next((f for f in self.files if f.sd_path == sd_path), None)

    def _dispatch(self, session: int, seq: int, msg_id: int, payload: dict) -> bytes | None:
        if msg_id == LOGIN:
            return self._login(seq, payload)
        if msg_id == SYSINFO:
            info = {"SerialNo": "FAKE0000", "HardWare": "FAKE", "SoftWareVersion": "V0.0.0"}
            return encode(session, seq, msg_id + 1, {"Name": "SystemInfo", "Ret": 100, "SystemInfo": info})
        if msg_id == FILE_QUERY:
            return encode(session, seq, msg_id + 1, {"Name": "OPFileQuery", "Ret": 100,
                                                     "OPFileQuery": self._query(payload["OPFileQuery"])})
        if msg_id == PLAY_REQ:
            if payload["OPPlayBack"]["Action"] == "DownloadStart":
                self._start_download(payload["OPPlayBack"]["Parameter"]["FileName"])
            return encode(session, seq, msg_id + 1, {"Name": "OPPlayBack", "Ret": 100})
        if msg_id == TIME_QUERY:
            return encode(session, seq, msg_id + 1, {"Name": "OPTimeQuery",
                                                     "OPTimeQuery": self.clock.strftime(_TIME_FMT), "Ret": 100})
        if msg_id == TIME_SET:
            when = datetime.strptime(payload["OPTimeSetting"], _TIME_FMT)
            self.set_time_calls.append(when)
            self.clock = when
            return encode(session, seq, msg_id + 1, {"Name": "OPTimeSetting", "Ret": 100})
        return encode(session, seq, msg_id + 1, {"Ret": 100})

    def _login(self, seq: int, payload: dict) -> bytes:
        self.login_attempts += 1
        if payload.get("PassWord") != sofia_hash(self.password):
            return encode(0, seq, LOGIN + 1, {"Ret": 205})
        return encode(SESSION_ID, seq, LOGIN + 1, {"Ret": 100, "SessionID": f"0x{SESSION_ID:08X}"})

    def _query(self, q: dict) -> list[dict]:
        day = q["BeginTime"][:10]
        with self._lock:
            hits = sorted((f for f in self.files if f.kind == q.get("Type", "h264")
                           and f"{f.begin:%Y-%m-%d}" == day), key=lambda f: f.begin)
        return [{"BeginTime": f.begin.strftime(_TIME_FMT), "EndTime": f.end.strftime(_TIME_FMT),
                 "FileLength": f"0x{-(-len(f.payload) // 1024):08X}", "FileName": f.sd_path,
                 "DiskNo": 0, "SerialNo": 0} for f in hits[:MAX_QUERY_RESULTS]]

    def _start_download(self, name: str) -> None:
        # The claim arrives on another connection without being awaited, so it may lag a moment.
        for _ in range(200):
            with self._lock:
                claim = self._claims.get(name)
            if claim:
                claim.start.set()
                return
            self._stopping.wait(0.01)

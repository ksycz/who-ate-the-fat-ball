"""Demo mode: a fake camera full of generated clips, so the app can be tried without the real camera.

The clips are synthetic HEVC (ffmpeg test patterns, never real footage) wrapped in the Xiongmai
``00 00 01 FC/FD`` framing the real camera uses, so they go through exactly the same download and
conversion path. The tests use `make_xm_clip` too.
"""

import functools
import shutil
import struct
import subprocess
from datetime import datetime, timedelta

from fatball.camera.fake import FakeCamera, FakeFile

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
_PARAM_SETS = {32, 33, 34, 35, 39}  # VPS, SPS, PPS, AUD, prefix SEI: start a new access unit
_KEY_SLICES = range(16, 22)
DEMO_CLIP_SECONDS = 2


def _split_access_units(stream: bytes) -> list[tuple[bool, bytes]]:
    """Split an Annex-B HEVC stream into (is_key, bytes) access units."""
    starts = []
    i = stream.find(b"\x00\x00\x01")
    while i >= 0:
        starts.append(i)
        i = stream.find(b"\x00\x00\x01", i + 3)
    nals = []
    for n, s in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(stream)
        body = stream[s:end].rstrip(b"\x00")
        nals.append((body[3] >> 1 & 0x3F, body[5] & 0x80 != 0, body))
    units: list[list] = []
    has_slice = False
    for kind, first_slice, body in nals:
        is_slice = kind < 32
        if units and has_slice and (kind in _PARAM_SETS or (is_slice and first_slice)):
            units.append([False, b""])
            has_slice = False
        if not units:
            units.append([False, b""])
        units[-1][1] += b"\x00" + body
        if is_slice:
            has_slice = True
            units[-1][0] = units[-1][0] or kind in _KEY_SLICES
    return [(key, data) for key, data in units]


@functools.cache
def make_xm_clip(seconds: float = 2, fps: int = 12, *, width: int = 320, height: int = 180,
                 source: str = "testsrc", hue: int = 0) -> bytes:
    """A synthetic HEVC clip (ffmpeg `source` pattern, hue-shifted by `hue` degrees) in Xiongmai framing."""
    video = f"{source}=size={width}x{height}:rate={fps}"
    cmd = [FFMPEG, "-loglevel", "error", "-f", "lavfi", "-i", video, "-t", str(seconds)]
    if hue:
        cmd += ["-vf", f"hue=h={hue}"]
    cmd += ["-c:v", "libx265", "-x265-params", f"log-level=error:keyint={fps}", "-f", "hevc", "-"]
    stream = subprocess.run(cmd, capture_output=True, check=True).stdout
    out = bytearray()
    for is_key, data in _split_access_units(stream):
        if is_key:
            out += b"\x00\x00\x01\xfc" + bytes([0x13, fps, width // 8, height // 8]) + bytes(4)
            out += struct.pack("<I", len(data)) + data
        else:
            out += b"\x00\x00\x01\xfd" + struct.pack("<I", len(data)) + data
    return bytes(out)


def build_demo_camera(n_clips: int = 12, days: int = 2, *, now: datetime | None = None) -> FakeCamera:
    """A (not yet started) FakeCamera holding `n_clips` distinct clips spread over the `days` days to now."""
    now = (now or datetime.now()).replace(microsecond=0)
    step = timedelta(days=days) / n_clips
    files = []
    for i in range(n_clips):
        end = now - timedelta(minutes=1) - i * step
        begin = end - timedelta(seconds=DEMO_CLIP_SECONDS)
        payload = make_xm_clip(DEMO_CLIP_SECONDS, source="testsrc2", hue=(i * 360 // n_clips) % 360)
        files.append(FakeFile(begin, end, "h264", payload))
    return FakeCamera(password="", files=files, clock=now)


def watcher_options() -> dict:
    """Watcher keyword arguments for the demo: empty password (never the Keychain), no LAN discovery."""
    return {"password": lambda: "", "find": lambda subnet, port, mac: None}

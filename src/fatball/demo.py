"""Demo mode: a fake camera full of generated clips, so the app can be tried without the real camera.

The clips are synthetic HEVC (ffmpeg test patterns, never real footage) wrapped in the Xiongmai
``00 00 01 FC/FD`` framing the real camera uses, so they go through exactly the same download and
conversion path. The tests use `make_xm_clip` too.
"""

import functools
import shutil
import sqlite3
import struct
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta

import numpy as np

from fatball.camera.fake import FakeCamera, FakeFile
from fatball.library import repo
from fatball.recognition.detector import Detection
from fatball.recognition.fake import FakeDetector
from fatball.recognition.features import to_blob

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
_PARAM_SETS = {32, 33, 34, 35, 39}  # VPS, SPS, PPS, AUD, prefix SEI: start a new access unit
_KEY_SLICES = range(16, 22)
DEMO_CLIP_SECONDS = 2
# Calm single-colour clips for the demo (and so for the README screenshots): soft tones that sit
# with the gallery's cream and robin palette instead of a busy test pattern.
DEMO_COLOURS = ("A9B79F", "D8C7AE", "B9C6CC", "C9A991", "9FAE93", "CFC3B4")


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
    joiner = ":" if "=" in source else "="  # a source may bring its own options, e.g. "color=c=0xA9B79F"
    video = f"{source}{joiner}size={width}x{height}:rate={fps}"
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
        payload = make_xm_clip(DEMO_CLIP_SECONDS, source=f"color=c=0x{DEMO_COLOURS[i % len(DEMO_COLOURS)]}")
        files.append(FakeFile(begin, end, "h264", payload))
    return FakeCamera(password="", files=files, clock=now)


def watcher_options() -> dict:
    """Watcher keyword arguments for the demo: empty password (never the Keychain), no LAN discovery."""
    return {"password": lambda: "", "find": lambda subnet, port, mac: None}


DEMO_SPECIES = "Parus major"  # great tit
_BIRD_FEATURE = np.array([1.0, 0.0], dtype=np.float32)
_DEMO_BOX = (0.25, 0.25, 0.75, 0.75)


def fake_recognition() -> tuple[FakeDetector, Callable]:
    """A detector that sees one animal in every frame, and a feature function that makes it look like the
    seeded great tit examples. No model, no Vision: the demo shows bird visits on any machine, instantly."""
    detector = FakeDetector(lambda index: [Detection("animal", 0.9, _DEMO_BOX)])
    return detector, lambda path, box: _BIRD_FEATURE


def seed_examples(conn: sqlite3.Connection) -> None:
    """Three labelled great tit examples, kept on a placeholder clip that is never shown (status failed)."""
    repo.ensure_catalog(conn)
    cam = repo.upsert_camera(conn, "feeder", None, None)
    when = datetime(2000, 1, 1)
    holder = repo.add_clip(conn, cam, "/demo/examples", when, when, "h264", 0)
    repo.set_clip_status(conn, holder, "failed")
    conn.executemany(
        "INSERT INTO detection(clip_id, frame_index, cls, conf, x1, y1, x2, y2, feature, label, label_source) "
        "VALUES (?, ?, 'animal', 0.9, ?, ?, ?, ?, ?, ?, 'import')",
        [(holder, i, *_DEMO_BOX, to_blob(_BIRD_FEATURE), DEMO_SPECIES) for i in range(3)],
    )
    conn.commit()

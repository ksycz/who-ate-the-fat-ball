import shutil
import struct
import subprocess

import pytest

from fatball.camera.fake import FakeCamera

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
WIDTH, HEIGHT, FPS = 320, 180, 12
_PARAM_SETS = {32, 33, 34, 35, 39}  # VPS, SPS, PPS, AUD, prefix SEI: start a new access unit
_KEY_SLICES = range(16, 22)


@pytest.fixture
def fake_camera():
    with FakeCamera() as cam:
        yield cam


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


@pytest.fixture(scope="session")
def xm_clip_bytes() -> bytes:
    """A 2 s synthetic HEVC clip wrapped in Xiongmai 00 00 01 FC/FD frames."""
    result = subprocess.run(
        [FFMPEG, "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={WIDTH}x{HEIGHT}:rate={FPS}",
         "-t", "2", "-c:v", "libx265", "-x265-params", "log-level=error:keyint=12", "-f", "hevc", "-"],
        capture_output=True, check=True,
    )
    out = bytearray()
    for is_key, data in _split_access_units(result.stdout):
        if is_key:
            out += b"\x00\x00\x01\xfc" + bytes([0x13, FPS, WIDTH // 8, HEIGHT // 8]) + bytes(4)
            out += struct.pack("<I", len(data)) + data
        else:
            out += b"\x00\x00\x01\xfd" + struct.pack("<I", len(data)) + data
    return bytes(out)

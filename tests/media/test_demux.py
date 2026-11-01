import struct

import pytest

from conftest import FPS
from fatball.media.demux import NotXiongmai, demux, extract_jpeg


def test_demux_reads_hevc_and_fps(xm_clip_bytes):
    result = demux(xm_clip_bytes)
    assert result.codec == "hevc"
    assert result.fps == FPS
    assert result.video.startswith(b"\x00\x00\x00\x01") or result.video.startswith(b"\x00\x00\x01")


def test_demux_skips_frames_before_keyframe(xm_clip_bytes):
    junk = b"\x00\x00\x01\xfd" + struct.pack("<I", 4) + b"JUNK"
    plain = demux(xm_clip_bytes)
    with_junk = demux(junk + xm_clip_bytes)
    assert b"JUNK" not in with_junk.video
    assert with_junk.video == plain.video


def test_demux_without_keyframe_raises():
    with pytest.raises(NotXiongmai):
        demux(b"just some random bytes" * 10)


def test_extract_jpeg_returns_payload():
    jpeg = b"\xff\xd8\xff\xe0body\xff\xd9"
    raw = b"\x00\x00\x01\xfe" + bytes(8) + struct.pack("<I", len(jpeg)) + jpeg
    assert extract_jpeg(raw) == jpeg

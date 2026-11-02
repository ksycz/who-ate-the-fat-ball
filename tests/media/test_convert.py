import json
import struct
import subprocess

import pytest

from fatball.media.convert import FFPROBE, ConversionFailed, convert_clip


def _probe(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, check=True, text=True,
    )
    return json.loads(out.stdout)


def test_convert_produces_playable_h264(tmp_path, xm_clip_bytes):
    raw = tmp_path / "clip.raw"
    raw.write_bytes(xm_clip_bytes)
    out = tmp_path / "out"
    result = convert_clip(raw, out)
    web = _probe(result.web)
    assert web["streams"][0]["codec_name"] == "h264"
    assert len(web["streams"]) == 1
    assert _probe(result.original)["streams"][0]["codec_name"] == "hevc"
    assert result.poster.exists() and result.preview.exists() and result.thumb.exists()
    assert result.thumb.name == "thumb.jpg" and result.original.name == "original.mp4"
    assert _probe(result.thumb)["streams"][0]["width"] == 480
    assert _probe(result.preview)["streams"][0]["width"] == 480
    assert 1.5 < result.duration_s < 2.5
    assert sorted(p.name for p in out.iterdir()) == [
        "original.mp4", "poster.jpg", "preview.mp4", "thumb.jpg", "web.mp4"]


def test_convert_garbage_raises_conversion_failed(tmp_path):
    raw = tmp_path / "bad.raw"
    body = b"garbage" * 20
    raw.write_bytes(b"\x00\x00\x01\xfc" + bytes([0x13, 12, 0, 0]) + bytes(4) + struct.pack("<I", len(body)) + body)
    with pytest.raises(ConversionFailed):
        convert_clip(raw, tmp_path / "out")

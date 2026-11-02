"""Turn a raw camera download into web-friendly files with ffmpeg."""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from fatball.media.demux import demux

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"


class ConversionFailed(Exception):
    """ffmpeg or ffprobe failed; the message is its stderr."""


@dataclass(frozen=True)
class ConvertedClip:
    original: Path
    web: Path
    poster: Path
    preview: Path
    thumb: Path
    duration_s: float


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ConversionFailed(result.stderr)
    return result.stdout


def _ffmpeg(*args: str) -> None:
    _run([FFMPEG, "-y", "-loglevel", "error", *args])


def _duration(path: Path) -> float:
    out = _run([FFPROBE, "-v", "error", "-show_format", "-of", "json", str(path)])
    return float(json.loads(out)["format"]["duration"])


def convert_clip(raw_path: Path, out_dir: Path) -> ConvertedClip:
    out_dir.mkdir(parents=True, exist_ok=True)
    demuxed = demux(raw_path.read_bytes())
    original, web = out_dir / "original.mp4", out_dir / "web.mp4"
    poster, preview, thumb = out_dir / "poster.jpg", out_dir / "preview.mp4", out_dir / "thumb.jpg"
    stream = out_dir / f"stream.{demuxed.codec}"
    stream.write_bytes(demuxed.video)
    try:
        tag = "hvc1" if demuxed.codec == "hevc" else "avc1"
        _ffmpeg("-r", str(demuxed.fps or 15), "-f", demuxed.codec, "-i", str(stream),
                "-c", "copy", "-tag:v", tag, str(original))
    finally:
        stream.unlink(missing_ok=True)
    _ffmpeg("-i", str(original), "-an", "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(web))
    duration = _duration(web)
    _ffmpeg("-ss", "1" if duration >= 1 else "0", "-i", str(web), "-frames:v", "1",
            "-vf", "scale=480:-2", str(poster))
    _ffmpeg("-i", str(web), "-t", "3", "-an", "-vf", "scale=480:-2", "-c:v", "libx264",
            "-crf", "28", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(preview))
    _ffmpeg("-i", str(web), "-frames:v", "1", "-vf", "scale=480:-2", str(thumb))
    return ConvertedClip(original, web, poster, preview, thumb, duration)

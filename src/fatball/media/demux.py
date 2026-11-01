"""Strip Xiongmai frame headers from a raw camera download.

  00 00 01 FC / FE  key frame / jpeg   16-byte header, length (u32) at bytes 12-16
  00 00 01 FD       other video frame   8-byte header, length (u32) at bytes 4-8
  00 00 01 FA / F9  audio / info        8-byte header, length (u16) at bytes 6-8
"""

import struct
from dataclasses import dataclass
from typing import Literal

CODECS: dict[int, Literal["hevc", "h264"]] = {2: "h264", 3: "hevc"}


class NotXiongmai(Exception):
    """The bytes do not contain Xiongmai video frames."""


@dataclass(frozen=True)
class Demuxed:
    codec: Literal["hevc", "h264"]
    fps: int
    video: bytes


def _frames(raw: bytes):
    """Yield (kind, header, payload) for each well-formed frame."""
    i = 0
    while True:
        i = raw.find(b"\x00\x00\x01", i)
        if i < 0 or i + 8 > len(raw):
            return
        kind = raw[i + 3]
        if kind in (0xFC, 0xFE) and i + 16 <= len(raw):
            (length,) = struct.unpack_from("<I", raw, i + 12)
            start = i + 16
        elif kind == 0xFD:
            (length,) = struct.unpack_from("<I", raw, i + 4)
            start = i + 8
        elif kind in (0xFA, 0xF9):
            (length,) = struct.unpack_from("<H", raw, i + 6)
            start = i + 8
        else:
            i += 3
            continue
        if start + length > len(raw):
            return
        yield kind, raw[i:start], raw[start : start + length]
        i = start + length


def demux(raw: bytes) -> Demuxed:
    video = bytearray()
    codec = None
    fps = 0
    for kind, header, payload in _frames(raw):
        if kind == 0xFC:
            if codec is None:
                codec = CODECS.get(header[4] & 0x0F)  # high bits carry other flags
                if codec is None:
                    raise NotXiongmai("unsupported codec")
                fps = header[5]
            video += payload
        elif kind == 0xFD and codec:  # frames before the first key frame can't be decoded
            video += payload
    if codec is None:
        raise NotXiongmai("no key frame found")
    return Demuxed(codec, fps, bytes(video))


def extract_jpeg(raw: bytes) -> bytes:
    for kind, _header, payload in _frames(raw):
        if kind == 0xFE:
            end = payload.rfind(b"\xff\xd9")
            return payload[: end + 2] if end >= 0 else payload
    raise NotXiongmai("no jpeg frame found")

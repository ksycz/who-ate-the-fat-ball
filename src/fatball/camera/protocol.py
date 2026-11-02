"""Xiongmai DVRIP framing: header struct, password hash, JSON payload codec."""

import hashlib
import json
import struct

# head, version, session, sequence, msg id, data length (little-endian, 20 bytes)
HEADER = struct.Struct("<BB2xII2xHI")
TERMINATOR = b"\x0a\x00"

LOGIN = 1000
SYSINFO = 1020
PLAY_REQ = 1420
PLAY_CLAIM = 1424
PLAY_DATA = 1426
FILE_QUERY = 1440
TIME_SET = 1450
TIME_QUERY = 1452
MODIFY_PASSWORD = 1488

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def sofia_hash(password: str) -> str:
    digest = hashlib.md5(password.encode()).digest()
    return "".join(_CHARS[(digest[2 * i] + digest[2 * i + 1]) % 62] for i in range(8))


def encode(session: int, seq: int, msg_id: int, payload: dict) -> bytes:
    body = json.dumps(payload).encode() + TERMINATOR
    return HEADER.pack(0xFF, 0, session, seq, msg_id, len(body)) + body


def decode_header(raw: bytes) -> tuple[int, int, int]:
    """Return (session, msg_id, length) from a 20-byte header."""
    _, _, session, _, msg_id, length = HEADER.unpack(raw)
    return session, msg_id, length


def decode_payload(raw: bytes) -> dict:
    body = raw.rstrip(b"\x00\x0a").decode("utf-8", "replace")
    return json.loads(body) if body else {}

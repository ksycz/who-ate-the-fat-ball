from fatball.camera.protocol import TIME_QUERY, decode_header, decode_payload, encode, sofia_hash


def test_sofia_hash_of_empty_password():
    assert sofia_hash("") == "tlJwpbo6"


def test_encode_header_and_terminator():
    raw = encode(session=6, seq=3, msg_id=1000, payload={"Name": "x"})
    session, msg_id, length = decode_header(raw[:20])
    assert (raw[0], session, msg_id) == (0xFF, 6, 1000)
    assert raw.endswith(b"\x0a\x00") and length == len(raw) - 20


def test_decode_payload_strips_terminator():
    assert decode_payload(b'{"Ret": 100}\x0a\x00') == {"Ret": 100}


def test_decode_payload_empty_body():
    assert decode_payload(b"\x0a\x00") == {}


def test_time_query_constant():
    assert TIME_QUERY == 1452

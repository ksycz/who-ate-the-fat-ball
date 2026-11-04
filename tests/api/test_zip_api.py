import io
import zipfile

import pytest

from fatball.library import repo

from .test_visits_api import T0, add_visit, sure


@pytest.fixture(autouse=True)
def catalog(conn):
    repo.ensure_catalog(conn)


def make_files(settings, conn, clip_id, video=b"video-bytes"):
    (settings.media_dir / f"c{clip_id}.mp4").write_bytes(video)
    (settings.media_dir / "frames").mkdir(exist_ok=True)
    (settings.media_dir / "frames" / f"{clip_id}.jpg").write_bytes(b"jpg")


def test_zip_round_trip(local, settings, conn, cam):
    c, v = add_visit(conn, cam, 0, sure())
    make_files(settings, conn, c)
    r = local.post("/api/downloads/zip", json={"visit_ids": [v]})
    assert r.status_code == 200
    body = r.json()
    assert body["size_bytes"] == len(b"video-bytes") + 3 and body["visits"] == 1 and body["files"] == 2
    assert body["filename"] == "fat-ball-1-visits.zip"
    g = local.get(f"/api/downloads/zip/{body['token']}")
    assert g.status_code == 200
    assert g.headers["content-disposition"] == 'attachment; filename="fat-ball-1-visits.zip"'
    z = zipfile.ZipFile(io.BytesIO(g.content))
    assert z.testzip() is None
    assert z.read("2026-10-30 08-00 Great tit.mp4") == b"video-bytes"
    assert local.get(f"/api/downloads/zip/{body['token']}").status_code == 200  # a retry works


def test_zip_by_day_and_errors(local, settings, conn, cam):
    c, _ = add_visit(conn, cam, 0, sure())
    make_files(settings, conn, c)
    r = local.post("/api/downloads/zip", json={"day": T0.date().isoformat(), "category": "birds"})
    assert r.json()["filename"] == "fat-ball-2026-10-30.zip"
    assert local.post("/api/downloads/zip", json={"day": "2020-01-01"}).status_code == 404
    r = local.post("/api/downloads/zip", json={"visit_ids": list(range(1, 502))})
    assert r.status_code == 422 and "max 500" in r.json()["detail"]
    assert local.post("/api/downloads/zip", json={}).status_code == 422
    assert local.get("/api/downloads/zip/nope").status_code == 404


def test_zip_token_expires(local, settings, conn, cam, clock):
    c, v = add_visit(conn, cam, 0, sure())
    make_files(settings, conn, c)
    token = local.post("/api/downloads/zip", json={"visit_ids": [v]}).json()["token"]
    clock.advance(minutes=9)
    assert local.get(f"/api/downloads/zip/{token}").status_code == 200
    clock.advance(minutes=2)
    assert local.get(f"/api/downloads/zip/{token}").status_code == 404


def test_zip_keeps_at_most_20_tokens(local, settings, conn, cam):
    c, v = add_visit(conn, cam, 0, sure())
    make_files(settings, conn, c)
    tokens = [local.post("/api/downloads/zip", json={"visit_ids": [v]}).json()["token"] for _ in range(21)]
    assert local.get(f"/api/downloads/zip/{tokens[0]}").status_code == 404
    assert local.get(f"/api/downloads/zip/{tokens[-1]}").status_code == 200


def test_zip_open_without_pin(lan, settings, conn, cam):
    c, v = add_visit(conn, cam, 0, sure())
    make_files(settings, conn, c)
    r = lan.post("/api/downloads/zip", json={"visit_ids": [v]})
    assert r.status_code == 200
    assert lan.get(f"/api/downloads/zip/{r.json()['token']}").status_code == 200

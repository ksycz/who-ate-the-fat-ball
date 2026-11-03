import json
from datetime import datetime, timedelta

import pytest

from fatball.library import repo
from fatball.library.visits import assign_visit
from fatball.recognition.matcher import Verdict
from fatball.recognition.recognizer import verdict_to_json

GREAT, BLUE, FOX = "Parus major", "Cyanistes caeruleus", "Vulpes vulpes"
TODAY = datetime(2026, 10, 31, 8, 0, 0)  # the same local day as conftest.NOW


@pytest.fixture(autouse=True)
def catalog(conn):
    repo.ensure_catalog(conn)


def visit(conn, cam, begin, species=GREAT, category="birds", conf=0.9):
    clip_id = repo.add_clip(
        conn, cam, f"/c{begin.isoformat()}.h265", begin, begin + timedelta(seconds=10), "video", 1,
    )
    repo.set_clip_status(
        conn, clip_id, "ready", web_path=f"c{clip_id}.mp4", poster_path=f"c{clip_id}.jpg", duration_s=10.0,
    )
    verdict = Verdict(category, species, conf, [(species, conf)], "species", None)
    repo.set_recognition(
        conn, clip_id, best_frame_path=f"frames/{clip_id}.jpg", verdict_json=verdict_to_json(verdict),
        recognized_at=begin,
    )
    conn.execute(
        "INSERT INTO detection(clip_id, frame_index, cls, conf, x1, y1, x2, y2, feature) "
        "VALUES (?, 0, 'animal', 0.9, 0, 0, 1, 1, ?)", (clip_id, b"\x00" * 8),
    )
    conn.commit()
    return assign_visit(conn, repo.get_clip(conn, clip_id), verdict)


def test_today_empty_day_has_last_visitor(local, conn, cam):
    visit(conn, cam, datetime(2026, 10, 30, 17, 0))
    body = local.get("/api/today").json()
    assert body["day"] == "2026-10-31"
    assert body["summary"] == {"visits": 0, "species": 0}
    assert body["visits"] == [] and body["checking"] == [] and body["failed"] == []
    assert body["champion"] is None
    assert body["new_species"]["scientific"] == GREAT  # yesterday's first sighting, not watched yet
    assert body["last_visitor"]["name"] == "great tit"
    assert body["last_visitor"]["started_at"].startswith("2026-10-30T17:00")
    assert body["camera"]["state"] == "problem"


def test_today_lists_visits_newest_first_with_champion(local, conn, cam):
    first = visit(conn, cam, TODAY)
    blue = visit(conn, cam, TODAY + timedelta(hours=1), BLUE)
    third = visit(conn, cam, TODAY + timedelta(hours=2))
    fox = visit(conn, cam, TODAY + timedelta(hours=3), FOX, "other_animals")
    body = local.get("/api/today").json()
    ids = [v["id"] for v in body["visits"]]
    assert ids[0] == fox and ids[1] == third and ids[-1] == first and len(ids) == 4
    assert body["summary"] == {"visits": 4, "species": 2}
    champ = body["champion"]
    assert (champ["scientific"], champ["name"], champ["count"]) == (GREAT, "great tit", 2)
    assert champ["best_frame_url"].startswith("/media/frames/")
    v = body["visits"][-1]
    assert v["duration_s"] == 10.0 and v["poster_url"].endswith(".jpg")
    assert v["corrected"] is False and v["watched"] is False
    assert body["new_species"]["visit_id"] == blue  # the newest first sighting
    json.dumps(body)


def test_today_day_comes_from_server_clock(local, clock, conn, cam):
    clock.t = datetime(2026, 11, 3, 0, 30).astimezone()
    visit(conn, cam, datetime(2026, 11, 3, 0, 10))
    visit(conn, cam, datetime(2026, 11, 2, 23, 50))
    body = local.get("/api/today").json()
    assert body["day"] == "2026-11-03"
    assert body["summary"]["visits"] == 1
    assert body["last_visitor"]["started_at"].startswith("2026-11-02T23:50")


def test_today_checking_and_failed(local, conn, cam, settings):
    def clip(name, status, **kw):
        cid = repo.add_clip(conn, cam, f"/{name}", TODAY, TODAY + timedelta(seconds=10), "h264", 1)
        repo.set_clip_status(conn, cid, status, **kw)
        return cid

    waiting = clip("a", "downloaded", raw_path="raw/a.raw")
    with_raw = clip("b", "failed", raw_path="raw/b.raw")
    (settings.media_dir / "raw").mkdir()
    (settings.media_dir / "raw/b.raw").write_bytes(b"x")
    no_raw = clip("c", "failed", raw_path="raw/c.raw")
    body = local.get("/api/today").json()
    assert [c["id"] for c in body["checking"]] == [waiting]
    by_id = {f["clip_id"]: f for f in body["failed"]}
    assert set(by_id) == {with_raw, no_raw}
    assert by_id[with_raw]["can_retry"] is True and by_id[no_raw]["can_retry"] is False
    assert by_id[with_raw]["begin_at"].startswith("2026-10-31T08:00")


def test_watched_needs_no_pin_and_hides_banner(lan, conn, cam):
    v = visit(conn, cam, TODAY)
    assert lan.get("/api/today").json()["new_species"]["visit_id"] == v
    assert lan.post(f"/api/visits/{v}/watched").status_code == 204
    body = lan.get("/api/today").json()
    assert body["new_species"] is None
    assert body["visits"][0]["watched"] is True
    assert lan.post("/api/visits/999/watched").status_code == 404


def test_species_lists_catalog_with_counts(local, conn, cam):
    visit(conn, cam, TODAY, BLUE)
    visit(conn, cam, TODAY + timedelta(hours=1), GREAT)
    visit(conn, cam, TODAY + timedelta(hours=2), GREAT)
    visit(conn, cam, TODAY + timedelta(hours=3), FOX, "other_animals")
    rows = local.get("/api/species").json()
    assert len(rows) == conn.execute("SELECT COUNT(*) FROM species").fetchone()[0]
    assert set(rows[0]) == {"scientific", "name", "group", "visits", "last_seen_at"}
    assert [r["scientific"] for r in rows[:2]] == [GREAT, BLUE]
    assert rows[0]["visits"] == 2 and rows[0]["last_seen_at"].startswith("2026-10-31T10:00")
    assert rows[0]["name"] == "great tit" and rows[0]["group"] == "bird"
    groups = [r["group"] for r in rows]
    assert groups == sorted(groups, key=lambda g: g != "bird")  # birds first
    fox = next(r for r in rows if r["scientific"] == FOX)
    assert fox["group"] == "mammal" and fox["visits"] == 1
    unseen = [r for r in rows if r["visits"] == 0]
    assert unseen and all(r["last_seen_at"] is None for r in unseen)
    birds = [r for r in rows if r["group"] == "bird"]
    assert [(-r["visits"], r["name"]) for r in birds] == sorted((-r["visits"], r["name"]) for r in birds)


def test_status_has_sorted_counts(local, conn, cam):
    visit(conn, cam, TODAY)
    visit(conn, cam, TODAY + timedelta(hours=1), FOX, "other_animals")
    body = local.get("/api/status").json()
    assert body["sorted"] == {"birds": 1, "other_animals": 1, "other": 0, "favourites": 0}


def test_visits_favourite_filter(local, conn, cam):
    a = visit(conn, cam, TODAY)
    visit(conn, cam, TODAY + timedelta(hours=1))
    conn.execute("UPDATE visit SET is_favourite = 1 WHERE id = ?", (a,))
    conn.commit()
    assert [v["id"] for v in local.get("/api/visits?favourite=true").json()["items"]] == [a]
    assert len(local.get("/api/visits?favourite=false").json()["items"]) == 1
    assert len(local.get("/api/visits").json()["items"]) == 2


def test_retry_failed_clip_with_raw_requeues_conversion(local, conn, cam, settings):
    cid = repo.add_clip(conn, cam, "/r", TODAY, TODAY + timedelta(seconds=10), "video", 1)
    repo.set_clip_status(conn, cid, "failed", raw_path="raw/r.raw")
    (settings.media_dir / "raw").mkdir()
    (settings.media_dir / "raw/r.raw").write_bytes(b"x")
    assert local.post(f"/api/retry/{cid}").status_code == 204
    assert repo.get_clip(conn, cid).status == "downloaded"


def test_retry_failed_clip_without_raw_is_409(local, conn, cam):
    cid = repo.add_clip(conn, cam, "/r", TODAY, TODAY + timedelta(seconds=10), "video", 1)
    repo.set_clip_status(conn, cid, "failed", raw_path="raw/gone.raw")
    assert local.post(f"/api/retry/{cid}").status_code == 409
    assert repo.get_clip(conn, cid).status == "failed"


def test_status_says_whether_the_request_is_from_the_mac(local, lan):
    assert local.get("/api/status").json()["local"] is True
    assert lan.get("/api/status").json()["local"] is False


def test_status_and_today_report_server_now(settings, stored_passwords):
    from datetime import timezone

    from fatball.api.app import create_app

    from .conftest import LOCAL, TestClient

    fixed = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone(timedelta(hours=1)))
    c = TestClient(create_app(settings, now=lambda: fixed), client=LOCAL)
    assert c.get("/api/status").json()["now"] == "2026-11-02T10:00:00+01:00"
    assert c.get("/api/today").json()["now"] == "2026-11-02T10:00:00+01:00"

import itertools
from datetime import datetime

import pytest

from fatball.library import repo

GREAT, BLUE = "Parus major", "Cyanistes caeruleus"
# conftest.NOW is 2026-10-31 15:00 local


@pytest.fixture(autouse=True)
def catalog(conn):
    repo.ensure_catalog(conn)

_n = itertools.count()


def add_visit(conn, cam, started, species=GREAT, conf=0.9):
    clip_id = repo.add_clip(conn, cam, f"/c{started}-{next(_n)}.h265", datetime.fromisoformat(started),
                            datetime.fromisoformat(started), "video", 1)
    repo.set_clip_status(conn, clip_id, "ready", web_path=f"c{clip_id}.mp4")
    sid = conn.execute("SELECT id FROM species WHERE scientific_name = ?", (species,)).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO visit(started_at, ended_at, category, species_id, confidence, best_clip_id, best_frame_path) "
        "VALUES (?, ?, 'birds', ?, ?, ?, ?)", (started, started, sid, conf, clip_id, f"frames/{clip_id}.jpg"),
    )
    conn.execute("INSERT INTO visit_clip VALUES (?, ?)", (cur.lastrowid, clip_id))
    conn.commit()
    return cur.lastrowid


def test_species_period_shape(local, conn, cam):
    add_visit(conn, cam, "2026-10-30T09:00:00+01:00")
    add_visit(conn, cam, "2026-10-01T09:00:00+01:00", BLUE)
    week = local.get("/api/species?period=week").json()
    assert [r["scientific"] for r in week] == [GREAT]
    assert set(week[0]) == {"scientific", "name", "visits", "last_seen_at", "first_seen_at", "is_new", "photo_url"}
    assert week[0]["photo_url"].startswith("/media/frames/")
    assert len(local.get("/api/species?period=all").json()) == 2
    assert local.get("/api/species?period=year").status_code == 422


def test_species_without_period_unchanged(local, conn, cam):
    add_visit(conn, cam, "2026-10-30T09:00:00+01:00")
    body = local.get("/api/species").json()
    assert set(body[0]) == {"scientific", "name", "group", "visits", "last_seen_at"}
    assert any(r["scientific"] == BLUE and r["visits"] == 0 for r in body)  # the whole catalog


def test_stats_shape_and_weeks_bounds(local, conn, cam):
    add_visit(conn, cam, "2026-10-30T09:00:00+01:00")  # Friday
    body = local.get("/api/stats").json()
    assert body["weeks"] == 4 and body["visits"] == 1 and body["species"] == 1
    assert body["busiest"] == "8–10 am"
    assert body["heatmap"][4] == {"day": "Fri", "cells": [0, 1, 0, 0, 0, 0, 0]}
    assert body["per_species"] == [{"scientific": GREAT, "name": "great tit", "visits": 1}]
    assert local.get("/api/stats?weeks=0").status_code == 422
    assert local.get("/api/stats?weeks=53").status_code == 422
    assert local.get("/api/stats?weeks=52").status_code == 200


def test_videos_shape_paging_and_filters(local, conn, cam):
    ids = [add_visit(conn, cam, f"2026-10-{d}T09:00:00+01:00") for d in (28, 29, 30)]
    blue = add_visit(conn, cam, "2026-10-30T10:00:00+01:00", BLUE)
    body = local.get("/api/videos?limit=2").json()
    assert [i["id"] for i in body["items"]] == [blue, ids[2]]
    assert body["items"][0]["video_url"].startswith("/media/c") and body["items"][0]["video_clip_id"]
    assert body["total"] == 4
    assert [f["scientific"] for f in body["filters"]] == [GREAT, BLUE]
    rest = local.get(f"/api/videos?limit=2&cursor={body['next_cursor']}").json()
    assert [i["id"] for i in rest["items"]] == [ids[1], ids[0]] and rest["next_cursor"] is None
    only = local.get(f"/api/videos?species={BLUE}").json()
    assert [i["id"] for i in only["items"]] == [blue] and only["total"] == 1

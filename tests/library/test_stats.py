import itertools
from datetime import date, datetime

import pytest

from fatball.library import repo, stats
from fatball.library.db import connect

TODAY = date(2026, 11, 3)  # a Tuesday
GREAT, BLUE, DOG = "Parus major", "Cyanistes caeruleus", "Canis lupus familiaris"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "lib.db")
    repo.ensure_catalog(c)
    yield c
    c.close()


@pytest.fixture
def cam(conn):
    return repo.upsert_camera(conn, "feeder", None, None)

_n = itertools.count()


def add_visit(conn, cam, started, species=GREAT, category="birds", conf=0.9, video=True, deleted=False, frame=True):
    """A visit starting at the local text `started` (e.g. 2026-11-02T07:59:00+01:00) with one clip."""
    begin = datetime.fromisoformat(started)
    clip_id = repo.add_clip(conn, cam, f"/c{started}-{next(_n)}.h265", begin, begin, "video", 1)
    repo.set_clip_status(conn, clip_id, "ready", web_path=f"c{clip_id}.mp4" if video else None)
    if deleted:
        conn.execute("UPDATE clip SET deleted_at = ? WHERE id = ?", (started, clip_id))
    sid = conn.execute("SELECT id FROM species WHERE scientific_name = ?", (species,)).fetchone()[0] if species else None
    cur = conn.execute(
        "INSERT INTO visit(started_at, ended_at, category, species_id, confidence, best_clip_id, best_frame_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (started, started, category, sid, conf, clip_id, f"frames/{clip_id}.jpg" if frame else None),
    )
    conn.execute("INSERT INTO visit_clip VALUES (?, ?)", (cur.lastrowid, clip_id))
    conn.commit()
    return cur.lastrowid


def day(n_ago, time="09:00:00"):
    d = date.fromordinal(TODAY.toordinal() - n_ago)
    return f"{d.isoformat()}T{time}+01:00"


def test_heatmap_uses_local_wall_clock(conn, cam):
    add_visit(conn, cam, "2026-11-02T07:59:00+01:00")  # Monday
    add_visit(conn, cam, "2026-11-02T05:50:00+01:00")
    s = stats.summary(conn, TODAY, 4)
    assert s["visits"] == 2
    assert s["heatmap"][0] == {"day": "Mon", "cells": [1, 0, 0, 0, 0, 0, 0]}
    assert sum(sum(r["cells"]) for r in s["heatmap"]) == 1
    assert [r["day"] for r in s["heatmap"]] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert s["slots"] == stats.SLOTS and s["weeks"] == 4


def test_heatmap_sunday_is_last_row(conn, cam):
    add_visit(conn, cam, "2026-11-01T19:30:00+01:00")  # Sunday
    assert stats.summary(conn, TODAY, 1)["heatmap"][6]["cells"][6] == 1


def test_busiest_is_largest_slot_column(conn, cam):
    for t in ("09:00:00", "09:30:00", "13:00:00"):
        add_visit(conn, cam, day(1, t))
    s = stats.summary(conn, TODAY, 4)
    assert s["busiest"] == "8–10 am"
    assert stats.summary(conn, date(2020, 1, 1), 4)["busiest"] is None


def test_stats_birds_only_and_window(conn, cam):
    add_visit(conn, cam, day(1), GREAT)
    add_visit(conn, cam, day(2), BLUE)
    add_visit(conn, cam, day(1), DOG, category="other_animals")
    add_visit(conn, cam, day(29), GREAT)  # outside 4 weeks (28 days: today and the 27 before)
    add_visit(conn, cam, day(27), None)  # unknown bird: a visit, not a species
    s = stats.summary(conn, TODAY, 4)
    assert (s["visits"], s["species"]) == (3, 2)
    assert {p["scientific"] for p in s["per_species"]} == {GREAT, BLUE}
    assert all(p["visits"] == 1 for p in s["per_species"])


def test_species_week_is_rolling_7_days(conn, cam):
    add_visit(conn, cam, day(6), GREAT)
    add_visit(conn, cam, day(7), BLUE)
    week = stats.species_for_period(conn, TODAY, "week")
    assert [r["scientific"] for r in week] == [GREAT]
    assert {r["scientific"] for r in stats.species_for_period(conn, TODAY, "month")} == {GREAT, BLUE}
    assert week[0]["visits"] == 1


def test_species_all_and_order_and_all_time_fields(conn, cam):
    add_visit(conn, cam, day(40), GREAT)
    add_visit(conn, cam, day(1), GREAT)
    add_visit(conn, cam, day(2), GREAT)
    add_visit(conn, cam, day(1), BLUE)
    add_visit(conn, cam, day(1), DOG, category="other_animals")
    add_visit(conn, cam, day(1), None)
    allp = stats.species_for_period(conn, TODAY, "all")
    assert [(r["scientific"], r["visits"]) for r in allp] == [(GREAT, 3), (BLUE, 1)]
    month = stats.species_for_period(conn, TODAY, "month")
    assert month[0]["visits"] == 2
    assert month[0]["last_seen_at"] == day(1)
    assert month[0]["first_seen_at"] == day(40)  # no stored first_seen_at: falls back to the earliest visit


def test_species_photo_is_most_confident_visit_in_period(conn, cam):
    old = add_visit(conn, cam, day(20), GREAT, conf=0.99)
    low = add_visit(conn, cam, day(1), GREAT, conf=0.5)
    high = add_visit(conn, cam, day(2), GREAT, conf=0.8)

    def path(v):
        return conn.execute("SELECT best_frame_path FROM visit WHERE id = ?", (v,)).fetchone()[0]

    assert stats.species_for_period(conn, TODAY, "week")[0]["photo_path"] == path(high)
    assert stats.species_for_period(conn, TODAY, "all")[0]["photo_path"] == path(old)
    assert low != high


def test_species_is_new_within_7_days(conn, cam):
    conn.execute("UPDATE species SET first_seen_at = ? WHERE scientific_name = ?", (day(6), GREAT))
    conn.execute("UPDATE species SET first_seen_at = ? WHERE scientific_name = ?", (day(7), BLUE))
    add_visit(conn, cam, day(1), GREAT)
    add_visit(conn, cam, day(1), BLUE)
    new = {r["scientific"]: r["is_new"] for r in stats.species_for_period(conn, TODAY, "week")}
    assert new == {GREAT: True, BLUE: False}


def test_videos_skip_visits_without_web_video(conn, cam):
    with_video = add_visit(conn, cam, day(1))
    add_visit(conn, cam, day(2), video=False)
    add_visit(conn, cam, day(3), deleted=True)
    add_visit(conn, cam, day(1), DOG, category="other_animals")
    rows = stats.videos(conn, 10, None, None)
    assert [r["id"] for r in rows] == [with_video]
    assert rows[0]["video_path"].endswith(".mp4") and rows[0]["video_clip_id"] is not None
    assert rows[0]["clip_count"] == 1
    assert stats.videos_total(conn, None) == 1


def test_videos_species_filter_total_and_paging(conn, cam):
    ids = [add_visit(conn, cam, day(i), GREAT) for i in (1, 2, 3)]
    blue = add_visit(conn, cam, day(1, "10:00:00"), BLUE)
    assert [r["id"] for r in stats.videos(conn, 10, None, GREAT)] == ids
    assert [r["id"] for r in stats.videos(conn, 10, None, BLUE)] == [blue]
    assert stats.videos_total(conn, GREAT) == 3 and stats.videos_total(conn, None) == 4
    first = stats.videos(conn, 2, None, GREAT)
    rest = stats.videos(conn, 2, (first[-1]["started_at"], first[-1]["id"]), GREAT)
    assert [r["id"] for r in first + rest] == ids


def test_top_species_last_30_days(conn, cam):
    for i in (1, 2):
        add_visit(conn, cam, day(i), BLUE)
    add_visit(conn, cam, day(3), GREAT)
    add_visit(conn, cam, day(30), GREAT)  # outside
    add_visit(conn, cam, day(30), GREAT)
    add_visit(conn, cam, day(1), DOG, category="other_animals")
    assert stats.top_species(conn, TODAY) == [
        {"scientific": BLUE, "name": "blue tit"}, {"scientific": GREAT, "name": "great tit"},
    ]
    assert stats.top_species(conn, TODAY, n=1) == [{"scientific": BLUE, "name": "blue tit"}]

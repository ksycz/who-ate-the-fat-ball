from datetime import date, datetime, timedelta

import pytest

from fatball.library import repo, today
from fatball.library.db import connect
from fatball.library.visits import assign_visit
from fatball.recognition.matcher import Verdict
from fatball.recognition.recognizer import verdict_to_json

DAY = date(2026, 11, 2)
GREAT = "Parus major"
BLUE = "Cyanistes caeruleus"
DOG = "Canis lupus familiaris"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "lib.db")
    repo.ensure_catalog(c)
    yield c
    c.close()


@pytest.fixture
def cam(conn):
    return repo.upsert_camera(conn, "feeder", None, None)


def sure(species=GREAT, conf=0.9, category="birds"):
    return Verdict(category, species, conf, [(species, conf)], "species", None)


def unknown_bird():
    return Verdict("birds", None, 0.4, [], "unknown", None)


def at(hour, minute=0, day=DAY):
    return datetime(day.year, day.month, day.day, hour, minute)


def clip_at(conn, cam, begin, *, kind="h264", length=10, path=None):
    return repo.add_clip(conn, cam, path or f"/c{begin.isoformat()}.h265", begin, begin + timedelta(seconds=length), kind, 1)


def visit_at(conn, cam, begin, verdict, *, length=10):
    """A recognised clip starting at `begin`, assigned to a visit; returns (clip_id, visit_id)."""
    clip_id = clip_at(conn, cam, begin, length=length)
    repo.set_recognition(
        conn, clip_id, best_frame_path=f"frames/{clip_id}.jpg", verdict_json=verdict_to_json(verdict), recognized_at=begin
    )
    clip = repo.get_clip(conn, clip_id)
    return clip_id, assign_visit(conn, clip, verdict)


def test_champion_is_the_species_with_most_visits_today(conn, cam):
    visit_at(conn, cam, at(11), sure(GREAT))
    visit_at(conn, cam, at(9), sure(GREAT))
    visit_at(conn, cam, at(14), sure(GREAT))
    visit_at(conn, cam, at(10), sure(BLUE))
    visit_at(conn, cam, at(12), sure(BLUE))
    for hour in range(8, 13):
        visit_at(conn, cam, at(hour, 30, DAY - timedelta(days=1)), sure(BLUE))
    champ = today.champion(conn, DAY)
    assert champ["scientific"] == GREAT
    assert champ["name"] == "great tit"
    assert champ["count"] == 3
    assert champ["first_at"] == at(9).astimezone().isoformat()
    assert champ["best_frame_path"].startswith("frames/")


def test_champion_tie_goes_to_earlier_first_visit(conn, cam):
    visit_at(conn, cam, at(8), sure(BLUE))
    visit_at(conn, cam, at(9), sure(GREAT))
    visit_at(conn, cam, at(10), sure(BLUE))
    visit_at(conn, cam, at(11), sure(GREAT))
    assert today.champion(conn, DAY)["scientific"] == BLUE


def test_champion_none_without_named_birds(conn, cam):
    visit_at(conn, cam, at(9), unknown_bird())
    visit_at(conn, cam, at(10), sure(DOG, category="other"))
    assert today.champion(conn, DAY) is None


def test_today_uses_the_given_local_day_not_utc(conn, cam):
    visit_at(conn, cam, datetime(2026, 11, 3, 0, 30), sure(GREAT))
    assert today.summary(conn, date(2026, 11, 3)) == {"visits": 1, "species": 1}
    assert today.summary(conn, date(2026, 11, 2)) == {"visits": 0, "species": 0}
    assert today.champion(conn, date(2026, 11, 2)) is None


def test_summary_counts_visits_and_distinct_bird_species(conn, cam):
    visit_at(conn, cam, at(8), sure(GREAT))
    visit_at(conn, cam, at(9), sure(GREAT))
    visit_at(conn, cam, at(10), sure(BLUE))
    visit_at(conn, cam, at(11), unknown_bird())
    assert today.summary(conn, DAY) == {"visits": 4, "species": 2}


def test_new_species_until_watched(conn, cam):
    _, first = visit_at(conn, cam, at(9), sure(GREAT))
    news = today.new_species(conn)
    assert news == {
        "visit_id": first, "scientific": GREAT, "name": "great tit", "started_at": at(9).astimezone().isoformat()
    }
    assert today.mark_watched(conn, first, at(9, 5)) is True
    assert today.new_species(conn) is None
    visit_at(conn, cam, at(15), sure(GREAT))  # same species again: not new
    assert today.new_species(conn) is None


def test_mark_watched_unknown_visit(conn):
    assert today.mark_watched(conn, 999, at(9)) is False


def test_checking_lists_clips_not_yet_in_a_visit(conn, cam):
    repo.set_setting(conn, repo.RECOGNIZE_OLD_KEY, "on")
    downloaded = clip_at(conn, cam, at(8))
    repo.set_clip_status(conn, downloaded, "downloaded", raw_path="r")
    processing = clip_at(conn, cam, at(9))
    repo.set_clip_status(conn, processing, "processing")
    ready = clip_at(conn, cam, at(10))
    repo.set_clip_status(conn, ready, "ready", web_path="w")
    in_visit, _ = visit_at(conn, cam, at(11), sure())
    repo.set_clip_status(conn, in_visit, "ready", web_path="w")
    nothing = clip_at(conn, cam, at(12))  # recognised as nothing: no visit, but nothing left to wait for
    repo.set_clip_status(conn, nothing, "ready", web_path="w")
    repo.set_recognition(conn, nothing, best_frame_path=None, verdict_json="{}", recognized_at=at(12))
    photo = clip_at(conn, cam, at(13), kind="jpg")
    repo.set_clip_status(conn, photo, "ready", web_path="w")
    downloading = clip_at(conn, cam, at(14))
    other_day = clip_at(conn, cam, at(8, day=DAY - timedelta(days=1)))
    repo.set_clip_status(conn, other_day, "processing")
    assert {c.id for c in today.checking(conn, DAY)} == {downloaded, processing, ready}
    assert downloading not in {c.id for c in today.checking(conn, DAY)}


def test_checking_leaves_out_old_clips_the_backfill_will_not_recognise(conn, cam):
    wanted = clip_at(conn, cam, at(8))
    repo.set_clip_status(conn, wanted, "ready", web_path="w")
    repo.requeue_recognition(conn, wanted)
    old = clip_at(conn, cam, at(9))
    repo.set_clip_status(conn, old, "ready", web_path="w")
    assert [c.id for c in today.checking(conn, DAY)] == [wanted]
    repo.set_setting(conn, repo.RECOGNIZE_OLD_KEY, "on")
    assert {c.id for c in today.checking(conn, DAY)} == {wanted, old}


def test_failed_lists_conversion_and_recognition_failures(conn, cam):
    repo.set_setting(conn, repo.RECOGNIZE_OLD_KEY, "on")
    convert = clip_at(conn, cam, at(8))
    repo.set_clip_status(conn, convert, "failed")
    recog = clip_at(conn, cam, at(9))
    repo.set_clip_status(conn, recog, "ready", web_path="w")
    repo.set_recognition_error(conn, recog, "boom")
    fine = clip_at(conn, cam, at(10))
    repo.set_clip_status(conn, fine, "ready", web_path="w")
    elsewhere = clip_at(conn, cam, at(8, day=DAY + timedelta(days=1)))
    repo.set_clip_status(conn, elsewhere, "failed")
    assert {c.id for c in today.failed(conn, DAY)} == {convert, recog}
    assert [c.id for c in today.checking(conn, DAY)] == [fine]  # a recognition error is failed, not checking


def test_last_visitor_is_newest_bird_before_day(conn, cam):
    assert today.last_visitor(conn, DAY) is None
    yesterday = DAY - timedelta(days=1)
    visit_at(conn, cam, at(8, day=yesterday), sure(BLUE))
    visit_at(conn, cam, at(16, day=yesterday), sure(GREAT))
    visit_at(conn, cam, at(17, day=yesterday), sure(DOG, category="other"))
    visit_at(conn, cam, at(9), sure(BLUE))  # today: not before today
    assert today.last_visitor(conn, DAY) == {"name": "great tit", "started_at": at(16, day=yesterday).astimezone().isoformat()}
    visit_at(conn, cam, at(20, day=yesterday), unknown_bird())
    assert today.last_visitor(conn, DAY)["name"] is None


def test_sorted_counts(conn, cam):
    _, a = visit_at(conn, cam, at(8), sure(GREAT))
    visit_at(conn, cam, at(9), sure(BLUE))
    visit_at(conn, cam, at(10), sure("Vulpes vulpes", category="other_animals"))
    visit_at(conn, cam, at(11), sure(DOG, category="other"))
    visit_at(conn, cam, at(12), sure(DOG, category="other"))
    conn.execute("UPDATE visit SET is_favourite = 1 WHERE id = ?", (a,))
    conn.commit()
    assert repo.sorted_counts(conn) == {"birds": 2, "other_animals": 1, "other": 2, "favourites": 1}


def test_visit_row_has_duration_poster_and_corrected(conn, cam):
    first, visit_id = visit_at(conn, cam, at(8), sure(), length=10)
    second, same = visit_at(conn, cam, at(8, 0) + timedelta(seconds=40), sure(conf=0.95), length=20)
    assert same == visit_id
    repo.set_clip_status(conn, first, "ready", poster_path="p1.jpg", preview_path="v1.mp4", duration_s=10.0)
    repo.set_clip_status(conn, second, "ready", poster_path="p2.jpg", preview_path="v2.mp4", duration_s=20.0)
    row = repo.get_visit(conn, visit_id)
    assert row["duration_s"] == 30.0
    assert (row["poster_path"], row["preview_path"]) == ("p2.jpg", "v2.mp4")  # the best clip's
    assert row["corrected"] == 0
    conn.execute("UPDATE visit SET best_clip_id = NULL, moved_by_user = 1 WHERE id = ?", (visit_id,))
    row = repo.get_visit(conn, visit_id)
    assert (row["poster_path"], row["preview_path"]) == ("p1.jpg", "v1.mp4")  # falls back to the first clip
    assert row["corrected"] == 1


def test_list_visits_filters_favourites(conn, cam):
    _, a = visit_at(conn, cam, at(8), sure(GREAT))
    _, b = visit_at(conn, cam, at(9), sure(BLUE))
    conn.execute("UPDATE visit SET is_favourite = 1 WHERE id = ?", (b,))
    conn.commit()
    assert [r["id"] for r in repo.list_visits(conn, 10, favourite=True)] == [b]
    assert [r["id"] for r in repo.list_visits(conn, 10, favourite=False)] == [a]
    assert [r["id"] for r in repo.list_visits(conn, 10)] == [b, a]


SQUIRREL = "Sciurus vulgaris"


def test_new_species_ignores_first_seen_outside_any_visit(conn, cam):
    visit_at(conn, cam, at(9), sure(GREAT))
    visit_at(conn, cam, at(13), sure(GREAT))
    conn.execute("UPDATE species SET first_seen_at = ? WHERE scientific_name = ?", (at(7).astimezone().isoformat(), GREAT))
    conn.commit()
    assert today.new_species(conn) is None


def test_champion_photo_comes_from_most_confident_visit(conn, cam):
    paths = {}
    for hour, conf in ((9, 0.6), (11, 0.9), (13, 0.7)):
        clip_id, _ = visit_at(conn, cam, at(hour), sure(GREAT, conf=conf))
        paths[conf] = f"frames/{clip_id}.jpg"
    assert today.champion(conn, DAY)["best_frame_path"] == paths[0.9]


def test_species_overview_orders_mammals_after_birds_by_visits(conn, cam):
    visit_at(conn, cam, at(8), sure(DOG, category="other"))
    visit_at(conn, cam, at(10), sure(SQUIRREL, category="other_animals"))
    visit_at(conn, cam, at(12), sure(SQUIRREL, category="other_animals"))
    groups = [(r["scientific_name"], r["grp"], r["visits"]) for r in repo.species_overview(conn)]
    mammals = [i for i, g in enumerate(groups) if g[1] != "bird"]
    assert min(mammals) > max(i for i, g in enumerate(groups) if g[1] == "bird")
    names = [g[0] for g in groups]
    assert names.index(SQUIRREL) < names.index(DOG)
    assert {g[0]: g[2] for g in groups}[SQUIRREL] == 2

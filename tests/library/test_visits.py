from datetime import datetime, timedelta

import pytest

from fatball.library import repo
from fatball.library.db import connect
from fatball.library.visits import assign_visit
from fatball.recognition.matcher import Verdict
from fatball.recognition.recognizer import verdict_to_json

T0 = datetime(2026, 10, 30, 8, 0, 0)
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


def sure(species=GREAT, conf=0.9, category="birds", guesses=None):
    return Verdict(category, species, conf, guesses or [(species, conf)], "species", None)


def unknown(conf=0.4, category="birds"):
    return Verdict(category, None, conf, [], "unknown", None)


def person():
    return Verdict("other", None, 0.9, [], "person", None)


def recognise(conn, cam, offset_s, verdict, *, length=10, store=True):
    """Add a clip `offset_s` after T0 with the given verdict stored, and assign it to a visit."""
    begin = T0 + timedelta(seconds=offset_s)
    clip_id = repo.add_clip(conn, cam, f"/c{offset_s}.h265", begin, begin + timedelta(seconds=length), "video", 1)
    if store:
        repo.set_recognition(
            conn, clip_id, best_frame_path=f"frames/{clip_id}.jpg", verdict_json=verdict_to_json(verdict),
            recognized_at=begin,
        )
    clip = next(c for c in repo.list_clips(conn, 100, None) if c.id == clip_id)
    return clip, assign_visit(conn, clip, verdict)


def visit_count(conn):
    return conn.execute("SELECT COUNT(*) FROM visit").fetchone()[0]


def test_clips_45s_apart_same_species_join(conn, cam):
    _, v1 = recognise(conn, cam, 0, sure())  # ends at 10 s
    _, v2 = recognise(conn, cam, 55, sure())  # gap 45 s
    assert v1 == v2
    assert visit_count(conn) == 1
    row = conn.execute("SELECT * FROM visit WHERE id = ?", (v1,)).fetchone()
    assert row["category"] == "birds"
    assert row["subject"] == "species"
    assert row["species_id"] is not None
    assert row["started_at"] == T0.astimezone().isoformat()
    assert row["ended_at"] == (T0 + timedelta(seconds=65)).astimezone().isoformat()


def test_clips_75s_apart_split(conn, cam):
    _, v1 = recognise(conn, cam, 0, sure())
    _, v2 = recognise(conn, cam, 85, sure())  # gap 75 s
    assert v1 != v2


def test_gap_of_exactly_60s_splits(conn, cam):
    _, v1 = recognise(conn, cam, 0, sure())
    _, v2 = recognise(conn, cam, 70, sure())  # gap 60 s
    assert v1 != v2


def test_different_species_split(conn, cam):
    _, v1 = recognise(conn, cam, 0, sure(GREAT))
    _, v2 = recognise(conn, cam, 20, sure(BLUE))
    assert v1 != v2


def test_unknown_clip_joins_neighbouring_visit(conn, cam):
    _, v1 = recognise(conn, cam, 0, sure(GREAT))
    _, v2 = recognise(conn, cam, 30, unknown())
    assert v1 == v2
    row = conn.execute("SELECT species_id, subject FROM visit WHERE id = ?", (v1,)).fetchone()
    assert row["species_id"] is not None and row["subject"] == "species"


def test_sure_clip_joins_unknown_only_visit_and_names_it(conn, cam):
    _, v1 = recognise(conn, cam, 0, unknown())
    row = conn.execute("SELECT species_id, subject FROM visit WHERE id = ?", (v1,)).fetchone()
    assert row["species_id"] is None and row["subject"] == "unknown"
    _, v2 = recognise(conn, cam, 20, sure(BLUE))
    assert v1 == v2
    row = conn.execute(
        "SELECT s.scientific_name AS name, v.subject FROM visit v JOIN species s ON s.id = v.species_id"
    ).fetchone()
    assert (row["name"], row["subject"]) == (BLUE, "species")


def test_person_visits_group_by_subject_and_category(conn, cam):
    _, p1 = recognise(conn, cam, 0, person())
    _, p2 = recognise(conn, cam, 20, person())
    _, b = recognise(conn, cam, 25, sure())
    assert p1 == p2 and b != p1


def test_out_of_order_clip_bridges_two_visits(conn, cam):
    _, a = recognise(conn, cam, 0, sure())
    _, b = recognise(conn, cam, 100, sure())
    assert a != b
    _, c = recognise(conn, cam, 50, sure())  # 40 s after the first ends, 40 s before the second begins
    assert visit_count(conn) == 1
    assert c == a  # the earliest survives
    assert conn.execute("SELECT COUNT(*) FROM visit_clip WHERE visit_id = ?", (a,)).fetchone()[0] == 3
    assert conn.execute("SELECT ended_at FROM visit").fetchone()[0] == (T0 + timedelta(seconds=110)).astimezone().isoformat()


def test_merge_removes_guess_rows_of_merged_visits(conn, cam):
    recognise(conn, cam, 0, sure())
    _, b = recognise(conn, cam, 100, sure())
    recognise(conn, cam, 50, sure())
    assert conn.execute("SELECT COUNT(*) FROM guess WHERE visit_id = ?", (b,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM guess").fetchone()[0] == 1


def test_visit_moved_by_user_is_not_merged(conn, cam):
    _, a = recognise(conn, cam, 0, sure())
    _, b = recognise(conn, cam, 100, sure())
    conn.execute("UPDATE visit SET moved_by_user = 1 WHERE id = ?", (b,))
    conn.commit()
    _, c = recognise(conn, cam, 50, sure())
    assert c == a
    assert visit_count(conn) == 2
    assert conn.execute("SELECT COUNT(*) FROM visit_clip WHERE visit_id = ?", (b,)).fetchone()[0] == 1


def test_moved_visit_needs_exact_species_and_keeps_owner_values(conn, cam):
    _, a = recognise(conn, cam, 0, sure(GREAT))
    blue_id = conn.execute("SELECT id FROM species WHERE scientific_name = ?", (BLUE,)).fetchone()[0]
    conn.execute("UPDATE visit SET moved_by_user = 1, species_id = ? WHERE id = ?", (blue_id, a))
    conn.commit()
    _, same = recognise(conn, cam, 20, sure(GREAT))  # the owner says blue; a great tit clip is not compatible
    assert same != a
    _, joined = recognise(conn, cam, 30, sure(BLUE))
    assert joined == a
    row = conn.execute("SELECT species_id, subject FROM visit WHERE id = ?", (a,)).fetchone()
    assert row["species_id"] == blue_id


def test_first_seen_set_once_for_sure_species_only(conn, cam):
    recognise(conn, cam, 0, unknown())
    assert conn.execute("SELECT COUNT(*) FROM species WHERE first_seen_at IS NOT NULL").fetchone()[0] == 0
    recognise(conn, cam, 200, sure(GREAT))
    first = conn.execute("SELECT first_seen_at FROM species WHERE scientific_name = ?", (GREAT,)).fetchone()[0]
    assert first == (T0 + timedelta(seconds=200)).astimezone().isoformat()
    recognise(conn, cam, 500, sure(GREAT))
    again = conn.execute("SELECT first_seen_at FROM species WHERE scientific_name = ?", (GREAT,)).fetchone()[0]
    assert again == first
    assert conn.execute("SELECT COUNT(*) FROM species WHERE first_seen_at IS NOT NULL").fetchone()[0] == 1


def test_guesses_written_top3(conn, cam):
    g1 = [(GREAT, 0.7), (BLUE, 0.2), ("Passer domesticus", 0.06), ("Fringilla coelebs", 0.04)]
    g2 = [(GREAT, 0.9), (BLUE, 0.1)]
    _, v = recognise(conn, cam, 0, sure(GREAT, 0.7, guesses=g1))
    recognise(conn, cam, 20, sure(GREAT, 0.9, guesses=g2))
    rows = conn.execute(
        "SELECT g.rank, s.scientific_name AS name, g.confidence FROM guess g JOIN species s ON s.id = g.species_id "
        "WHERE g.visit_id = ? ORDER BY g.rank", (v,)
    ).fetchall()
    assert [r["name"] for r in rows] == [GREAT, BLUE, "Passer domesticus"]
    assert [r["rank"] for r in rows] == [1, 2, 3]
    assert rows[0]["confidence"] == pytest.approx(0.8)
    assert rows[1]["confidence"] == pytest.approx(0.15)
    assert rows[2]["confidence"] == pytest.approx(0.03)


def test_best_clip_and_confidence(conn, cam):
    _, v = recognise(conn, cam, 0, sure(GREAT, 0.7))
    c2, _ = recognise(conn, cam, 20, sure(GREAT, 0.95))
    recognise(conn, cam, 40, unknown(0.99))
    row = conn.execute("SELECT * FROM visit WHERE id = ?", (v,)).fetchone()
    assert row["best_clip_id"] == c2.id
    assert row["best_frame_path"] == f"frames/{c2.id}.jpg"
    assert row["confidence"] == pytest.approx(0.99)


def test_re_recognising_a_clip_moves_it_and_drops_empty_visit(conn, cam):
    clip, _ = recognise(conn, cam, 0, sure(GREAT))
    again = assign_visit(conn, clip, sure(BLUE, guesses=[(BLUE, 0.9)]))  # the emptied visit's id may be reused
    assert visit_count(conn) == 1
    assert repo.visit_for_clip(conn, clip.id) == again
    names = [r[0] for r in conn.execute("SELECT s.scientific_name FROM guess g JOIN species s ON s.id = g.species_id")]
    assert names == [BLUE]


def test_re_recognising_a_clip_recomputes_the_old_visit(conn, cam):
    clip, v1 = recognise(conn, cam, 0, sure(GREAT))
    recognise(conn, cam, 20, sure(GREAT))
    again = assign_visit(conn, clip, sure(BLUE))
    assert again != v1
    assert visit_count(conn) == 2
    row = conn.execute("SELECT started_at FROM visit WHERE id = ?", (v1,)).fetchone()
    assert row["started_at"] == (T0 + timedelta(seconds=20)).astimezone().isoformat()


def test_unknown_bridging_two_species_does_not_merge_them(conn, cam):
    _, a = recognise(conn, cam, 0, sure(GREAT))
    recognise(conn, cam, 100, sure(BLUE))
    _, c = recognise(conn, cam, 50, unknown())
    assert visit_count(conn) == 2
    assert c == a


def test_visit_for_clip_none_when_unassigned(conn, cam):
    assert repo.visit_for_clip(conn, 12345) is None


def test_passed_verdict_used_when_not_stored(conn, cam):
    _, v = recognise(conn, cam, 0, sure(), store=False)
    row = conn.execute("SELECT confidence, best_clip_id FROM visit WHERE id = ?", (v,)).fetchone()
    assert row["confidence"] == pytest.approx(0.9)
    assert row["best_clip_id"] is not None


def test_dog_is_category_other_and_species_matched(conn, cam):
    dog = Verdict("other", DOG, 0.9, [(DOG, 0.9)], "species", None)
    _, d = recognise(conn, cam, 0, dog)
    _, p = recognise(conn, cam, 20, person())
    assert d != p


def test_unknown_first_visit_never_collapses_two_species(conn, cam):
    recognise(conn, cam, 0, unknown())
    recognise(conn, cam, 70, sure(GREAT))
    recognise(conn, cam, 100, sure(BLUE))
    assert visit_count(conn) == 3
    recognise(conn, cam, 40, unknown())
    assert visit_count(conn) == 2
    species = {r[0] for r in conn.execute("SELECT species_id FROM visit")}
    assert len(species) == 2

from datetime import datetime, timedelta

import pytest

from fatball.library import corrections, repo
from fatball.library.corrections import Change
from fatball.library.db import connect
from fatball.library.visits import assign_visit
from fatball.recognition.matcher import Verdict
from fatball.recognition.recognizer import verdict_to_json

T0 = datetime(2026, 10, 30, 8, 0, 0).astimezone()
GREAT = "Parus major"
FIELDS = "category, species_id, subject, is_favourite, moved_by_user"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "lib.db")
    repo.ensure_catalog(c)
    yield c
    c.close()


@pytest.fixture
def cam(conn):
    return repo.upsert_camera(conn, "feeder", None, None)


def add_visit(conn, cam, offset_s, verdict):
    begin = T0 + timedelta(seconds=offset_s)
    clip_id = repo.add_clip(conn, cam, f"/c{offset_s}.h265", begin, begin + timedelta(seconds=10), "video", 1)
    repo.set_clip_status(conn, clip_id, "ready", web_path=f"c{clip_id}.mp4", poster_path=f"c{clip_id}.jpg")
    repo.set_recognition(conn, clip_id, best_frame_path=f"frames/{clip_id}.jpg",
                         verdict_json=verdict_to_json(verdict), recognized_at=begin)
    conn.execute(
        "INSERT INTO detection(clip_id, frame_index, cls, conf, x1, y1, x2, y2, feature) "
        "VALUES (?, 0, 'animal', 0.9, 0, 0, 1, 1, ?)", (clip_id, b"\x00" * 8))
    conn.commit()
    return clip_id, assign_visit(conn, repo.get_clip(conn, clip_id), verdict)


def snap(conn, visit_id):
    return tuple(conn.execute(f"SELECT {FIELDS} FROM visit WHERE id = ?", (visit_id,)).fetchone())


def delete_visits(conn, *visit_ids):
    """Delete visit rows directly (foreign keys off, so the undo row stays), as a purge might."""
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    for v in visit_ids:
        conn.execute("DELETE FROM visit_clip WHERE visit_id = ?", (v,))
        conn.execute("DELETE FROM visit WHERE id = ?", (v,))
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def labels(conn, clip_id):
    return [tuple(r) for r in conn.execute(
        "SELECT label, label_source FROM detection WHERE clip_id = ? ORDER BY id", (clip_id,))]


@pytest.fixture
def trio(conn, cam):
    """A: Great tit favourite in birds; B: unknown bird; C: already in other."""
    ca, a = add_visit(conn, cam, 0, Verdict("birds", GREAT, 0.9, [(GREAT, 0.9)], "species", None))
    _, b = add_visit(conn, cam, 1000, Verdict("birds", None, 0.4, [], "unknown", None))
    _, c = add_visit(conn, cam, 2000, Verdict("other", None, 0.9, [], "nothing", None))
    corrections.apply(conn, a, Change(is_favourite=True))
    corrections.apply(conn, c, Change(species=None, category="other"))
    return ca, a, b, c


def test_bulk_move_then_undo_restores_each_visit(conn, trio):
    _, a, b, c = trio
    before = {v: snap(conn, v) for v in (a, b, c)}
    token, changed = corrections.apply_many(conn, [a, b, c], Change(category="other", teach=False), T0)
    assert changed == 2
    for v in (a, b):
        category, species_id, subject, _fav, moved = snap(conn, v)
        assert category == "other" and moved == 1 and subject == "unknown" and species_id is None
    assert snap(conn, c) == before[c]
    corrections.undo(conn, token, T0)
    assert {v: snap(conn, v) for v in (a, b, c)} == before


def test_plain_move_to_other_is_not_an_empty_clip(conn, trio, tmp_path):
    """R24: only the picker's taught choice (or the recogniser) makes an empty clip."""
    from fatball.library import cleanup

    _, a, b, _ = trio
    corrections.apply_many(conn, [a], Change(category="other", teach=False), T0)
    corrections.apply(conn, b, Change(category="other", teach=False), T0)
    assert [v["id"] for v in repo.list_visits(conn, None, category="other", only="empty")] == [trio[3]]
    for v in (a, b):
        with pytest.raises(cleanup.NotEmpty):
            cleanup.delete_empty_visits(conn, tmp_path, [v], T0)


def test_taught_move_to_other_is_an_empty_clip(conn, trio):
    _, a, _, _ = trio
    corrections.apply(conn, a, Change(species=None, category="other"), T0)
    assert snap(conn, a)[2] == "nothing"


def test_bulk_move_does_not_label_detections(conn, trio):
    ca, a, b, _ = trio
    before = labels(conn, ca)
    seen = conn.execute("SELECT scientific_name, first_seen_at FROM species ORDER BY id").fetchall()
    corrections.apply_many(conn, [a, b], Change(category="other", teach=False), T0)
    assert labels(conn, ca) == before
    assert conn.execute("SELECT scientific_name, first_seen_at FROM species ORDER BY id").fetchall() == seen


def test_bulk_favourite(conn, trio):
    _, a, b, _ = trio
    token, changed = corrections.apply_many(conn, [a, b], Change(is_favourite=True), T0)
    assert changed == 1  # A already is one
    assert snap(conn, b)[3] == 1
    corrections.undo(conn, token, T0)
    assert snap(conn, b)[3] == 0 and snap(conn, a)[3] == 1


def test_bulk_rejects_species(conn, trio):
    _, a, _, _ = trio
    with pytest.raises(corrections.InvalidChange):
        corrections.apply_many(conn, [a], Change(species=GREAT), T0)


def test_bulk_unknown_id_changes_nothing(conn, trio):
    _, a, _, _ = trio
    before = snap(conn, a)
    undos = conn.execute("SELECT COUNT(*) FROM undo").fetchone()[0]
    with pytest.raises(corrections.VisitNotFound):
        corrections.apply_many(conn, [a, 999], Change(category="other", teach=False), T0)
    assert snap(conn, a) == before
    assert conn.execute("SELECT COUNT(*) FROM undo").fetchone()[0] == undos


def test_bulk_undo_skips_deleted_visit(conn, trio):
    _, a, b, _ = trio
    token, _ = corrections.apply_many(conn, [a, b], Change(category="other", teach=False), T0)
    delete_visits(conn, a)
    corrections.undo(conn, token, T0)
    assert snap(conn, b)[0] == "birds"
    with pytest.raises(corrections.UnknownToken):
        corrections.undo(conn, token, T0)


def test_bulk_undo_with_every_visit_gone_is_unknown(conn, trio):
    _, a, b, _ = trio
    token, _ = corrections.apply_many(conn, [a, b], Change(category="other", teach=False), T0)
    delete_visits(conn, a, b)
    with pytest.raises(corrections.UnknownToken):
        corrections.undo(conn, token, T0)


def test_single_move_without_teach_leaves_labels_and_first_seen(conn, trio):
    ca, a, _, _ = trio
    before = labels(conn, ca)
    corrections.apply(conn, a, Change(category="other", teach=False), T0)
    assert labels(conn, ca) == before
    assert snap(conn, a)[0] == "other"

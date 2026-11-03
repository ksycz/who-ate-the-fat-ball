from datetime import datetime, timedelta

import pytest

from fatball.library import cleanup, corrections, repo, today
from fatball.library.corrections import Change
from fatball.library.db import connect
from fatball.library.visits import assign_visit
from fatball.recognition.matcher import Verdict
from fatball.recognition.recognizer import verdict_to_json

T0 = datetime(2026, 10, 30, 8, 0, 0).astimezone()
GREAT, DOG = "Parus major", "Canis lupus familiaris"
KINDS = ("raw", "original", "web", "poster", "preview")


def empty():
    return Verdict("other", None, 0.9, [], "nothing", None)


def bird():
    return Verdict("birds", GREAT, 0.9, [(GREAT, 0.9)], "species", None)


def dog():
    return Verdict("other", DOG, 0.9, [(DOG, 0.9)], "species", None)


def person():
    return Verdict("other", None, 0.9, [], "person", None)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "lib.db")
    repo.ensure_catalog(c)
    yield c
    c.close()


@pytest.fixture
def media(tmp_path):
    d = tmp_path / "media"
    d.mkdir()
    return d


@pytest.fixture
def cam(conn):
    return repo.upsert_camera(conn, "feeder", None, None)


def add_visit(conn, cam, media, offset_s, verdict):
    begin = T0 + timedelta(seconds=offset_s)
    clip_id = repo.add_clip(conn, cam, f"/c{offset_s}.h265", begin, begin + timedelta(seconds=10), "video", 1)
    paths = {f"{k}_path": f"{k}/{clip_id}.bin" for k in KINDS}
    repo.set_clip_status(conn, clip_id, "ready", **paths)
    frame = f"frames/{clip_id}.jpg"
    for rel in (*paths.values(), frame):
        (media / rel).parent.mkdir(parents=True, exist_ok=True)
        (media / rel).write_bytes(b"x")
    repo.set_recognition(
        conn, clip_id, best_frame_path=frame, verdict_json=verdict_to_json(verdict), recognized_at=begin
    )
    conn.execute(
        "INSERT INTO detection(clip_id, frame_index, cls, conf, x1, y1, x2, y2, feature) "
        "VALUES (?, 0, 'animal', 0.9, 0, 0, 1, 1, ?)", (clip_id, b"\x00" * 8))
    conn.commit()
    return clip_id, assign_visit(conn, repo.get_clip(conn, clip_id), verdict)


def count(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def test_only_dogs_and_only_empty(conn, cam, media):
    _, d = add_visit(conn, cam, media, 0, dog())
    _, e = add_visit(conn, cam, media, 1000, empty())
    _, p = add_visit(conn, cam, media, 2000, person())
    ids = lambda only: {r["id"] for r in repo.list_visits(conn, None, category="other", only=only)}
    assert ids(None) == {d, e, p}
    assert ids("dogs") == {d}
    assert ids("empty") == {e}


def test_delete_removes_files_and_visit_but_keeps_clip_row(conn, cam, media):
    clip, v = add_visit(conn, cam, media, 0, empty())
    corrections.apply(conn, v, Change(is_favourite=True))
    conn.execute("INSERT INTO guess(visit_id, species_id, confidence, rank) "
                 "SELECT ?, id, 0.5, 1 FROM species LIMIT 1", (v,))
    conn.execute("INSERT INTO correction(visit_id, created_at) VALUES (?, 'now')", (v,))
    conn.commit()
    clip_row = repo.get_clip(conn, clip)
    files = [media / getattr(clip_row, f"{k}_path") for k in KINDS] + [media / f"frames/{clip}.jpg"]
    assert all(f.exists() for f in files)
    # one file is already gone: skipped
    files[1].unlink()
    now = T0 + timedelta(hours=1)

    assert cleanup.delete_empty_visits(conn, media, [v], now) == 1

    assert not any(f.exists() for f in files)
    assert count(conn, "SELECT COUNT(*) FROM visit") == 0
    for table in ("visit_clip", "guess", "correction", "undo"):
        assert count(conn, f"SELECT COUNT(*) FROM {table}") == 0, table
    row = conn.execute("SELECT * FROM clip WHERE id = ?", (clip,)).fetchone()
    assert row["deleted_at"] is not None
    assert all(row[f"{k}_path"] is None for k in KINDS) and row["best_frame_path"] is None


def test_deleted_clip_is_never_fetched_or_recognised_again(conn, cam, media):
    clip, v = add_visit(conn, cam, media, 0, empty())
    repo.requeue_recognition(conn, clip)  # would be picked up again if it were not deleted
    cleanup.delete_empty_visits(conn, media, [v], T0)
    day = T0.date()
    assert (("/c0.h265", T0.replace(tzinfo=None)) in repo.known_clip_keys(conn, day))
    assert repo.clips_needing_recognition(conn, 10) == []
    assert repo.count_needing_recognition(conn) == 0
    assert repo.list_clips(conn, 10, None) == []
    assert repo.clips_with_status(conn, "ready") == []
    assert repo.recognition_counts(conn) == {"pending": 0, "old_waiting": 0, "errors": 0}
    assert today.checking(conn, day) == [] and today.failed(conn, day) == []
    assert repo.add_clip(conn, cam, "/c0.h265", T0, T0 + timedelta(seconds=10), "video", 1) is None


def test_deleted_failed_clip_is_not_counted_as_failed(conn, cam, media):
    clip, v = add_visit(conn, cam, media, 0, empty())
    conn.execute("UPDATE clip SET status = 'failed', recognition_error = 'x' WHERE id = ?", (clip,))
    conn.commit()
    cleanup.delete_empty_visits(conn, media, [v], T0)
    assert repo.queue_counts(conn)["failed"] == 0
    assert today.failed(conn, T0.date()) == []
    assert repo.referenced_raw_paths(conn) == set()


def test_delete_refuses_a_bird_visit_and_changes_nothing(conn, cam, media):
    clip_e, e = add_visit(conn, cam, media, 0, empty())
    clip_b, b = add_visit(conn, cam, media, 1000, bird())
    with pytest.raises(cleanup.NotEmpty):
        cleanup.delete_empty_visits(conn, media, [e, b], T0)
    with pytest.raises(cleanup.VisitNotFound):
        cleanup.delete_empty_visits(conn, media, [e, 999], T0)
    assert count(conn, "SELECT COUNT(*) FROM visit") == 2
    assert count(conn, "SELECT COUNT(*) FROM clip WHERE deleted_at IS NOT NULL") == 0
    assert (media / f"frames/{clip_e}.jpg").exists() and (media / f"web/{clip_b}.bin").exists()
    # a person or dog visit in Other is not empty either
    _, p = add_visit(conn, cam, media, 2000, person())
    with pytest.raises(cleanup.NotEmpty):
        cleanup.delete_empty_visits(conn, media, [p], T0)


def test_delete_keeps_labelled_detections(conn, cam, media):
    clip, v = add_visit(conn, cam, media, 0, empty())
    conn.execute("UPDATE detection SET label = 'nothing', labelled_at = 't', label_source = 'correction'")
    conn.commit()
    cleanup.delete_empty_visits(conn, media, [v], T0)
    assert labelsof(conn, clip) == [("nothing", "correction")]


def labelsof(conn, clip_id):
    return [tuple(r) for r in conn.execute(
        "SELECT label, label_source FROM detection WHERE clip_id = ?", (clip_id,))]


def test_bulk_undo_token_is_removed_with_its_visit(conn, cam, media):
    _, a = add_visit(conn, cam, media, 0, empty())
    _, b = add_visit(conn, cam, media, 1000, empty())
    token, _ = corrections.apply_many(conn, [a, b], Change(is_favourite=True))
    cleanup.delete_empty_visits(conn, media, [a], T0)
    assert count(conn, "SELECT COUNT(*) FROM undo") == 0  # token's visit_id was a
    with pytest.raises(corrections.UnknownToken):
        corrections.undo(conn, token)

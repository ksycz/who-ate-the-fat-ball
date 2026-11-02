import base64
from datetime import datetime, timedelta

import pytest

from fatball.library import corrections, repo
from fatball.library.visits import assign_visit
from fatball.recognition.matcher import Verdict
from fatball.recognition.recognizer import verdict_to_json

T0 = datetime(2026, 10, 30, 8, 0, 0)
GREAT, BLUE, DOG, FOX = "Parus major", "Cyanistes caeruleus", "Canis lupus familiaris", "Vulpes vulpes"


@pytest.fixture(autouse=True)
def catalog(conn):
    repo.ensure_catalog(conn)


def sure(species=GREAT, conf=0.9, category="birds", guesses=None):
    return Verdict(category, species, conf, guesses or [(species, conf)], "species", None)


def unknown(conf=0.4):
    return Verdict("birds", None, conf, [], "unknown", None)


def first_seen(conn, species):
    return conn.execute("SELECT first_seen_at FROM species WHERE scientific_name = ?", (species,)).fetchone()[0]


def add_visit(conn, cam, offset_s, verdict, *, detections=1, **clip_paths):
    begin = T0 + timedelta(seconds=offset_s)
    clip_id = repo.add_clip(conn, cam, f"/c{offset_s}.h265", begin, begin + timedelta(seconds=10), "video", 1)
    repo.set_clip_status(conn, clip_id, "ready", web_path=f"c{clip_id}.mp4", poster_path=f"c{clip_id}.jpg")
    repo.set_recognition(
        conn, clip_id, best_frame_path=f"frames/{clip_id}.jpg", verdict_json=verdict_to_json(verdict),
        recognized_at=begin,
    )
    for _ in range(detections):
        conn.execute(
            "INSERT INTO detection(clip_id, frame_index, cls, conf, x1, y1, x2, y2, feature) "
            "VALUES (?, 0, 'animal', 0.9, 0, 0, 1, 1, ?)",
            (clip_id, b"\x00" * 8),
        )
    conn.commit()
    return clip_id, assign_visit(conn, repo.get_clip(conn, clip_id), verdict)


def labels(conn, clip_id):
    return [tuple(r) for r in conn.execute(
        "SELECT label, label_source FROM detection WHERE clip_id = ? ORDER BY id", (clip_id,))]


def test_list_visits_filters_and_paginates(local, conn, cam):
    ids = [add_visit(conn, cam, 200 * i, sure(GREAT if i % 2 == 0 else BLUE))[1] for i in range(4)]
    add_visit(conn, cam, 3000, sure(FOX, category="other_animals"))
    fox = local.get("/api/visits?category=other_animals").json()["items"]
    assert [v["species"]["scientific"] for v in fox] == [FOX]
    assert fox[0]["species"]["name"] == "red fox"
    got = local.get(f"/api/visits?species={GREAT}").json()["items"]
    assert [v["id"] for v in got] == [ids[2], ids[0]]  # newest first
    assert local.get("/api/visits?day=2026-10-30").json()["items"] != []
    assert local.get("/api/visits?day=2026-10-29").json()["items"] == []

    first = local.get("/api/visits?limit=2").json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = local.get(f"/api/visits?limit=2&cursor={first['next_cursor']}").json()
    third = local.get(f"/api/visits?limit=2&cursor={second['next_cursor']}").json()
    seen = [v["id"] for page in (first, second, third) for v in page["items"]]
    assert seen == [v for v in sorted(seen, reverse=True)] and len(seen) == 5 and len(set(seen)) == 5
    assert third["next_cursor"] is None
    item = first["items"][0]
    assert set(item) == {"id", "started_at", "ended_at", "category", "species", "subject", "confidence",
                         "is_favourite", "best_frame_url", "clip_count"}
    assert item["best_frame_url"].startswith("/media/frames/")


def test_list_visits_bad_cursor_and_limit(local):
    assert local.get("/api/visits?cursor=!!!").status_code == 400
    assert local.get("/api/visits?cursor=" + base64.urlsafe_b64encode(b"nopipe").decode()).status_code == 400
    assert local.get("/api/visits?limit=201").status_code == 422


def test_visit_detail_has_clips_and_guesses(local, conn, cam):
    guesses = [(GREAT, 0.7), (BLUE, 0.2)]
    clip_id, v = add_visit(conn, cam, 0, sure(GREAT, 0.7, guesses=guesses))
    body = local.get(f"/api/visits/{v}").json()
    assert body["species"] == {"scientific": GREAT, "name": "great tit"}
    assert [c["id"] for c in body["clips"]] == [clip_id]
    assert body["clips"][0]["web_url"] == f"/media/c{clip_id}.mp4"
    assert [(g["scientific"], g["name"]) for g in body["guesses"]] == [(GREAT, "great tit"), (BLUE, "blue tit")]
    assert body["guesses"][0]["confidence"] == pytest.approx(0.7)
    assert local.get("/api/visits/999").status_code == 404


def test_patch_needs_editor(lan, conn, cam):
    _, v = add_visit(conn, cam, 0, sure())
    assert lan.patch(f"/api/visits/{v}", json={"is_favourite": True}).status_code == 403
    assert lan.post("/api/undo/whatever").status_code == 403
    assert lan.post("/api/retry/1").status_code == 403


def test_patch_species_sets_category_and_labels_examples(local, conn, cam):
    clip, v = add_visit(conn, cam, 0, sure(GREAT), detections=2)
    # an earlier import label and an older correction are both overwritten (R16)
    conn.execute("UPDATE detection SET label = ?, label_source = 'correction' WHERE id = "
                 "(SELECT MIN(id) FROM detection)", (BLUE,))
    conn.commit()
    r = local.patch(f"/api/visits/{v}", json={"species": FOX})
    assert r.status_code == 200 and len(r.json()["undo_token"]) == 22
    row = conn.execute("SELECT * FROM visit WHERE id = ?", (v,)).fetchone()
    assert (row["category"], row["subject"], row["moved_by_user"]) == ("other_animals", "species", 1)
    assert labels(conn, clip) == [(FOX, "correction")] * 2
    c = conn.execute("SELECT * FROM correction WHERE visit_id = ?", (v,)).fetchone()
    assert (c["from_category"], c["to_category"]) == ("birds", "other_animals")
    assert local.get(f"/api/visits/{v}").json()["species"]["scientific"] == FOX


def test_patch_to_other_labels_nothing(local, conn, cam):
    clip, v = add_visit(conn, cam, 0, sure(GREAT))
    assert local.patch(f"/api/visits/{v}", json={"species": None, "category": "other"}).status_code == 200
    row = conn.execute("SELECT * FROM visit WHERE id = ?", (v,)).fetchone()
    assert (row["category"], row["species_id"], row["subject"], row["moved_by_user"]) == ("other", None, "nothing", 1)
    assert labels(conn, clip) == [("nothing", "correction")]


def test_patch_dog_goes_to_other_and_category_only_drops_contradicting_species(local, conn, cam):
    _, v = add_visit(conn, cam, 0, sure(GREAT))
    local.patch(f"/api/visits/{v}", json={"species": DOG})
    assert conn.execute("SELECT category FROM visit WHERE id = ?", (v,)).fetchone()[0] == "other"
    _, w = add_visit(conn, cam, 5000, sure(GREAT))
    local.patch(f"/api/visits/{w}", json={"category": "other"})
    assert conn.execute("SELECT species_id FROM visit WHERE id = ?", (w,)).fetchone()[0] is None


def test_patch_validation(local, conn, cam):
    _, v = add_visit(conn, cam, 0, sure())
    assert local.patch(f"/api/visits/{v}", json={"species": "Nope nope"}).status_code == 422
    assert local.patch(f"/api/visits/{v}", json={"category": "sky"}).status_code == 422
    assert local.patch("/api/visits/999", json={"is_favourite": True}).status_code == 404


def test_favourite_only_patch_writes_no_correction_but_is_undoable(local, conn, cam):
    clip, v = add_visit(conn, cam, 0, sure())
    token = local.patch(f"/api/visits/{v}", json={"is_favourite": True}).json()["undo_token"]
    assert conn.execute("SELECT COUNT(*) FROM correction").fetchone()[0] == 0
    assert labels(conn, clip) == [(None, None)]
    row = conn.execute("SELECT is_favourite, moved_by_user FROM visit WHERE id = ?", (v,)).fetchone()
    assert tuple(row) == (1, 0)
    assert local.post(f"/api/undo/{token}").status_code == 204
    assert conn.execute("SELECT is_favourite FROM visit WHERE id = ?", (v,)).fetchone()[0] == 0


def test_undo_restores_visit(local, conn, cam):
    _, v = add_visit(conn, cam, 0, sure(GREAT))
    before = dict(conn.execute("SELECT * FROM visit WHERE id = ?", (v,)).fetchone())
    token = local.patch(f"/api/visits/{v}", json={"species": FOX}).json()["undo_token"]
    assert local.post(f"/api/undo/{token}").status_code == 204
    assert dict(conn.execute("SELECT * FROM visit WHERE id = ?", (v,)).fetchone()) == before
    assert conn.execute("SELECT COUNT(*) FROM correction").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM undo").fetchone()[0] == 0
    assert local.post(f"/api/undo/{token}").status_code == 404  # single use


def test_undo_removes_examples_added_by_the_correction(local, conn, cam):
    clip, v = add_visit(conn, cam, 0, sure(GREAT), detections=3)
    # one detection already carries an import label: undo must bring it back, not just clear it
    conn.execute("UPDATE detection SET label = ?, labelled_at = 'T', label_source = 'import' WHERE id = "
                 "(SELECT MIN(id) FROM detection)", (BLUE,))
    conn.commit()
    unrelated = repo.add_clip(conn, cam, "/other.h265", T0 + timedelta(hours=5), T0 + timedelta(hours=5, seconds=9),
                              "video", 1)
    conn.execute("INSERT INTO detection(clip_id, frame_index, cls, conf, x1, y1, x2, y2, feature) "
                 "VALUES (?, 0, 'animal', 0.9, 0, 0, 1, 1, ?)", (unrelated, b"\x00" * 8))
    conn.commit()
    token = local.patch(f"/api/visits/{v}", json={"species": FOX}).json()["undo_token"]
    assert len(repo.examples(conn)) == 3
    local.post(f"/api/undo/{token}")
    assert labels(conn, clip) == [(BLUE, "import"), (None, None), (None, None)]
    assert conn.execute("SELECT labelled_at FROM detection ORDER BY id LIMIT 1").fetchone()[0] == "T"
    assert len(repo.examples(conn)) == 1
    assert labels(conn, unrelated) == [(None, None)]


def test_undo_unknown_or_expired_token_404(local, conn, cam, clock):
    _, v = add_visit(conn, cam, 0, sure())
    assert local.post("/api/undo/nonsense").status_code == 404
    token = local.patch(f"/api/visits/{v}", json={"species": FOX}).json()["undo_token"]
    clock.advance(hours=24, seconds=1)
    assert local.post(f"/api/undo/{token}").status_code == 404
    assert conn.execute("SELECT category FROM visit WHERE id = ?", (v,)).fetchone()[0] == "other_animals"
    fresh = local.patch(f"/api/visits/{v}", json={"is_favourite": True}).json()["undo_token"]
    clock.advance(hours=23)
    assert local.post(f"/api/undo/{fresh}").status_code == 204


def test_retry_requeues_recognition(local, conn, cam):
    clip, _ = add_visit(conn, cam, 0, sure())
    repo.set_recognition_error(conn, clip, "boom")
    assert repo.clips_needing_recognition(conn, 10) == []
    assert local.post(f"/api/retry/{clip}").status_code == 204
    row = conn.execute("SELECT recognition_error, recognized_at FROM clip WHERE id = ?", (clip,)).fetchone()
    assert tuple(row) == (None, None)
    assert [c.id for c in repo.clips_needing_recognition(conn, 10)] == [clip]
    assert local.post("/api/retry/999").status_code == 404


def test_retry_refuses_a_clip_that_is_not_ready(local, conn, cam):
    clip = repo.add_clip(conn, cam, "/broken.h265", T0, T0 + timedelta(seconds=10), "video", 1)
    repo.set_clip_status(conn, clip, "failed", raw_path="raw/broken.raw")  # the conversion failed
    assert local.post(f"/api/retry/{clip}").status_code == 409


def test_patch_rejects_a_species_that_contradicts_the_category(local, conn, cam):
    _, v = add_visit(conn, cam, 0, sure())
    assert local.patch(f"/api/visits/{v}", json={"species": DOG, "category": "birds"}).status_code == 422
    assert local.patch(f"/api/visits/{v}", json={"species": FOX, "category": "birds"}).status_code == 422
    assert conn.execute("SELECT COUNT(*) FROM correction").fetchone()[0] == 0
    assert local.patch(f"/api/visits/{v}", json={"species": BLUE, "category": "birds"}).status_code == 200


def test_correction_lowers_first_seen_and_undo_restores_it(local, conn, cam):
    _, v = add_visit(conn, cam, 0, unknown())
    add_visit(conn, cam, 5000, sure(GREAT))
    later = (T0 + timedelta(seconds=5000)).astimezone().isoformat()
    assert first_seen(conn, GREAT) == later
    token = local.patch(f"/api/visits/{v}", json={"species": GREAT}).json()["undo_token"]
    assert first_seen(conn, GREAT) == T0.astimezone().isoformat()  # the owner named an earlier sighting
    assert local.post(f"/api/undo/{token}").status_code == 204
    assert first_seen(conn, GREAT) == later
    token = local.patch(f"/api/visits/{v}", json={"species": BLUE}).json()["undo_token"]
    assert first_seen(conn, BLUE) == T0.astimezone().isoformat()
    local.post(f"/api/undo/{token}")
    assert first_seen(conn, BLUE) is None


def test_undo_recomputes_the_visit_from_its_clips(local, conn, cam):
    _, v = add_visit(conn, cam, 0, sure(GREAT, 0.7))
    token = local.patch(f"/api/visits/{v}", json={"species": BLUE}).json()["undo_token"]
    clip2, joined = add_visit(conn, cam, 20, sure(BLUE, 0.95))  # joins only because the owner said blue tit
    assert joined == v
    assert local.post(f"/api/undo/{token}").status_code == 204
    body = local.get(f"/api/visits/{v}").json()
    assert body["species"]["scientific"] == BLUE  # the visit agrees with its clips again: the best is a blue tit
    assert conn.execute("SELECT best_clip_id, moved_by_user FROM visit WHERE id = ?", (v,)).fetchone()[:] == (clip2, 0)


def test_correction_and_undo_take_the_write_lock_before_reading(conn, cam):
    _, v = add_visit(conn, cam, 0, sure())
    statements = []
    conn.set_trace_callback(statements.append)
    try:
        token = corrections.apply(conn, v, corrections.Change(is_favourite=True))
        first_apply = statements[0]
        statements.clear()
        corrections.undo(conn, token)
    finally:
        conn.set_trace_callback(None)
    assert (first_apply, statements[0]) == ("BEGIN IMMEDIATE", "BEGIN IMMEDIATE")

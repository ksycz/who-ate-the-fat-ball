import sqlite3
from datetime import date, datetime, timedelta

import pytest

from fatball.library import repo
from fatball.library.db import connect

TABLES = {
    "camera",
    "clip",
    "visit",
    "visit_clip",
    "species",
    "species_name",
    "guess",
    "correction",
    "setting",
}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "lib.db")
    yield c
    c.close()


@pytest.fixture
def cam(conn):
    return repo.upsert_camera(conn, "feeder", "aa:bb", "192.168.1.5")


def _add(conn, cam, path="/idea/a.h265", begin=datetime(2026, 10, 30, 8, 0, 0), kind="video"):
    return repo.add_clip(conn, cam, path, begin, begin + timedelta(seconds=30), kind, 1000)


def test_connect_creates_all_tables(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_connect_twice_is_safe(tmp_path):
    connect(tmp_path / "x.db").close()
    connect(tmp_path / "x.db").close()


def test_upsert_camera_updates_in_place(conn):
    a = repo.upsert_camera(conn, "feeder", "aa:bb", "1.1.1.1")
    b = repo.upsert_camera(conn, "feeder", "aa:bb", "2.2.2.2")
    assert a == b
    repo.update_camera_status(conn, a, last_error="boom", clock_offset_s=3.5)
    row = conn.execute("SELECT last_ip, last_error, clock_offset_s FROM camera").fetchone()
    assert tuple(row) == ("2.2.2.2", "boom", 3.5)


def test_add_clip_is_idempotent_on_sd_path_and_begin(conn, cam):
    first = _add(conn, cam)
    assert isinstance(first, int)
    assert _add(conn, cam) is None
    assert conn.execute("SELECT COUNT(*) FROM clip").fetchone()[0] == 1


def test_known_clip_keys_round_trips_naive_local(conn, cam):
    begin = datetime(2026, 10, 30, 8, 0, 0)
    _add(conn, cam, begin=begin)
    _add(conn, cam, path="/idea/b.h265", begin=datetime(2026, 10, 31, 9, 0, 0))
    keys = repo.known_clip_keys(conn, date(2026, 10, 30))
    assert keys == {("/idea/a.h265", begin)}
    assert repo.known_clip_keys(conn, date(2026, 11, 2)) == set()


def test_aware_input_is_normalised_to_local(conn, cam):
    aware = datetime(2026, 10, 30, 8, 0, 0).astimezone()
    _add(conn, cam, begin=aware)
    assert _add(conn, cam, begin=datetime(2026, 10, 30, 8, 0, 0)) is None
    stored = conn.execute("SELECT begin_at FROM clip").fetchone()[0]
    assert datetime.fromisoformat(stored).utcoffset() == aware.utcoffset()


def test_new_clip_is_downloading_until_marked_downloaded(conn, cam):
    cid = _add(conn, cam)
    assert [c.id for c in repo.clips_with_status(conn, "downloading")] == [cid]
    assert repo.clips_with_status(conn, "downloaded") == []
    repo.set_clip_status(conn, cid, "downloaded", raw_path=f"raw/{cid}.raw")
    assert [c.raw_path for c in repo.clips_with_status(conn, "downloaded")] == [f"raw/{cid}.raw"]


def test_schema_rejects_unknown_status(conn, cam):
    import sqlite3

    cid = _add(conn, cam)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE clip SET status = 'bogus' WHERE id = ?", (cid,))


def test_claim_for_processing_is_atomic_and_rereads_the_row(conn, cam):
    cid = _add(conn, cam)
    assert repo.claim_for_processing(conn, cid) is None  # still downloading
    repo.set_clip_status(conn, cid, "downloaded", raw_path=f"raw/{cid}.raw")
    claimed = repo.claim_for_processing(conn, cid)
    assert claimed is not None and claimed.status == "processing" and claimed.raw_path == f"raw/{cid}.raw"
    assert repo.claim_for_processing(conn, cid) is None  # already claimed
    assert repo.claim_for_processing(conn, 9999) is None


def test_delete_clips_with_status_and_referenced_raw_paths(conn, cam):
    a = _add(conn, cam, path="/a")
    b = _add(conn, cam, path="/b")
    repo.set_clip_status(conn, b, "ready", raw_path="raw/b.raw")
    assert repo.delete_clips_with_status(conn, "downloading") == 1
    assert [c.id for c in repo.list_clips(conn, 10, None)] == [b]
    assert a not in {c.id for c in repo.list_clips(conn, 10, None)}
    assert repo.referenced_raw_paths(conn) == {"raw/b.raw"}


def test_status_transitions_and_paths(conn, cam):
    cid = _add(conn, cam)
    repo.set_clip_status(conn, cid, "downloaded")
    assert [c.id for c in repo.clips_with_status(conn, "downloaded")] == [cid]
    repo.set_clip_status(conn, cid, "processing", raw_path="/r/a.h265")
    repo.set_clip_status(
        conn, cid, "ready", web_path="w.mp4", poster_path="p.jpg", preview_path="v.mp4", duration_s=12.5
    )
    (clip,) = repo.clips_with_status(conn, "ready")
    assert (clip.raw_path, clip.web_path, clip.poster_path, clip.preview_path, clip.duration_s) == (
        "/r/a.h265",
        "w.mp4",
        "p.jpg",
        "v.mp4",
        12.5,
    )
    assert clip.status == "ready" and clip.kind == "video"
    assert repo.clips_with_status(conn, "downloaded") == []


def test_set_clip_status_rejects_bad_input(conn, cam):
    cid = _add(conn, cam)
    with pytest.raises(ValueError):
        repo.set_clip_status(conn, cid, "ready", **{"web_path = 'x', status": "y"})
    with pytest.raises(ValueError):
        repo.set_clip_status(conn, cid, "bogus")


def test_list_clips_newest_first_with_cursor(conn, cam):
    base = datetime(2026, 10, 30, 8, 0, 0)
    for i in range(5):
        _add(conn, cam, path=f"/c/{i}", begin=base + timedelta(hours=i))
    page = repo.list_clips(conn, 2, None)
    assert [c.sd_path for c in page] == ["/c/4", "/c/3"]
    assert isinstance(page[0].begin_at, datetime)
    nxt = repo.list_clips(conn, 2, page[-1].begin_at)
    assert [c.sd_path for c in nxt] == ["/c/2", "/c/1"]
    assert [c.sd_path for c in repo.list_clips(conn, 10, nxt[-1].begin_at)] == ["/c/0"]


def test_update_camera_status_can_clear_error(conn, cam):
    repo.update_camera_status(conn, cam, last_error="boom")
    repo.update_camera_status(conn, cam, clear_error=True)
    assert conn.execute("SELECT last_error FROM camera").fetchone()[0] is None


def test_upsert_camera_keeps_stored_mac_and_ip_when_given_none(conn, cam):
    assert repo.upsert_camera(conn, "feeder", None, None) == cam
    assert tuple(conn.execute("SELECT mac, last_ip FROM camera").fetchone()) == ("aa:bb", "192.168.1.5")


def test_get_camera_reads_the_row(conn):
    assert repo.get_camera(conn) is None
    cam = repo.upsert_camera(conn, "feeder", "aa:bb", "192.168.1.5")
    repo.update_camera_status(conn, cam, last_seen_at=datetime(2026, 10, 30, 8, 0), clock_offset_s=1.5)
    got = repo.get_camera(conn)
    assert (got.id, got.name, got.mac, got.last_ip, got.last_error, got.clock_offset_s) == (
        cam, "feeder", "aa:bb", "192.168.1.5", None, 1.5)
    assert got.last_seen_at == datetime(2026, 10, 30, 8, 0).astimezone()


def test_delete_clip(conn, cam):
    clip_id = _add(conn, cam)
    repo.delete_clip(conn, clip_id)
    assert repo.list_clips(conn, 10, None) == []


def test_queue_counts_only_pending_states(conn, cam):
    for i, status in enumerate(["downloaded", "downloaded", "processing", "failed", "ready"]):
        cid = _add(conn, cam, path=f"/p/{i}", begin=datetime(2026, 10, 30, 8, i, 0))
        repo.set_clip_status(conn, cid, status)
    assert repo.queue_counts(conn) == {"downloaded": 2, "processing": 1, "failed": 1}


def test_queue_counts_empty(conn):
    assert repo.queue_counts(conn) == {"downloaded": 0, "processing": 0, "failed": 0}


def test_settings_get_set_overwrite(conn):
    assert repo.get_setting(conn, "k") is None
    repo.set_setting(conn, "k", "v1")
    repo.set_setting(conn, "k", "v2")
    assert repo.get_setting(conn, "k") == "v2"


def test_list_clips_status_filter(conn, cam):
    a = _add(conn, cam, path="/a", begin=datetime(2026, 10, 30, 8, 0, 0))
    _add(conn, cam, path="/b", begin=datetime(2026, 10, 30, 9, 0, 0))
    repo.set_clip_status(conn, a, "ready")
    assert [c.id for c in repo.list_clips(conn, 10, None, status="ready")] == [a]
    assert len(repo.list_clips(conn, 10, None)) == 2


def _detection(conn, clip, cls="animal", conf=0.9, feature=b"\x00" * 8, label=None, source=None):
    return conn.execute(
        "INSERT INTO detection(clip_id, frame_index, cls, conf, x1, y1, x2, y2, feature, label, label_source) "
        "VALUES (?, 0, ?, ?, 0, 0, 1, 1, ?, ?, ?)",
        (clip, cls, conf, feature, label, source),
    ).lastrowid


def _labels(conn, clip):
    return [(r["label"], r["label_source"]) for r in
            conn.execute("SELECT label, label_source FROM detection WHERE clip_id = ? ORDER BY id", (clip,))]


def test_label_detections_labels_only_confident_animals_with_features(conn, cam):
    clip = _add(conn, cam)
    _detection(conn, clip)
    _detection(conn, clip, cls="person")
    _detection(conn, clip, conf=0.1)
    _detection(conn, clip, feature=None)
    assert repo.label_detections(conn, clip, "Parus major", "import") == 1
    assert _labels(conn, clip) == [("Parus major", "import"), (None, None), (None, None), (None, None)]


def test_label_detections_never_overwrites_a_correction(conn, cam):
    clip = _add(conn, cam)
    _detection(conn, clip, label="Passer domesticus", source="correction")
    _detection(conn, clip)
    assert repo.label_detections(conn, clip, "Parus major", "import") == 1
    assert _labels(conn, clip) == [("Passer domesticus", "correction"), ("Parus major", "import")]


def test_unlabel_detections_clears_label_time_and_source(conn, cam):
    clip = _add(conn, cam)
    d = _detection(conn, clip)
    repo.label_detections(conn, clip, "Parus major", "import")
    repo.unlabel_detections(conn, [d])
    row = conn.execute("SELECT label, labelled_at, label_source FROM detection WHERE id = ?", (d,)).fetchone()
    assert tuple(row) == (None, None, None)


def test_scientific_name_for_english_any_case_or_scientific(conn):
    repo.ensure_catalog(conn)
    assert repo.scientific_name_for(conn, "great tit") == "Parus major"
    assert repo.scientific_name_for(conn, "Parus major") == "Parus major"
    assert repo.scientific_name_for(conn, "unicorn") is None


def test_replace_detections_is_all_or_nothing(conn, cam):
    clip = _add(conn, cam)
    repo.replace_detections(conn, clip, [repo.NewDetection(0, "animal", 0.9, (0, 0, 1, 1))])
    with pytest.raises(sqlite3.IntegrityError):
        repo.replace_detections(conn, clip, [repo.NewDetection(0, "animal", 0.8, (0, 0, 1, 1)),
                                             repo.NewDetection(1, None, 0.5, (0, 0, 1, 1))])  # cls is NOT NULL
    assert [r[0] for r in conn.execute("SELECT conf FROM detection")] == [0.9]

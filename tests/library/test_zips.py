import zipfile
from datetime import date, datetime, timedelta
from io import BytesIO

import pytest

from fatball.library import repo, zips
from fatball.library.db import connect
from fatball.library.visits import assign_visit
from fatball.recognition.matcher import Verdict
from fatball.recognition.recognizer import verdict_to_json

GREAT, DOG, FOX = "Parus major", "Canis lupus familiaris", "Vulpes vulpes"


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


def sure(species=GREAT, category="birds"):
    return Verdict(category, species, 0.9, [(species, 0.9)], "species", None)


def add_visit(conn, media, cam, begin, verdict=None, *, video=b"mp4", frame=b"jpg", clip_id_hint=None):
    verdict = verdict or sure()
    cid = repo.add_clip(conn, cam, f"/c{begin.isoformat()}.h265", begin, begin + timedelta(seconds=10), "video", 1)
    repo.set_clip_status(conn, cid, "ready", web_path=f"c{cid}.mp4")
    repo.set_recognition(
        conn, cid, best_frame_path=f"frames/{cid}.jpg", verdict_json=verdict_to_json(verdict), recognized_at=begin
    )
    if video is not None:
        (media / f"c{cid}.mp4").write_bytes(video)
    if frame is not None:
        (media / "frames").mkdir(exist_ok=True)
        (media / "frames" / f"{cid}.jpg").write_bytes(frame)
    return cid, assign_visit(conn, repo.get_clip(conn, cid), verdict)


def test_plan_names_and_skips_missing_files(conn, media, cam):
    t = datetime(2026, 11, 2, 9, 12, 5)
    _, v1 = add_visit(conn, media, cam, t)
    _, v2 = add_visit(conn, media, cam, t + timedelta(hours=1), frame=None)  # photo missing
    _, v3 = add_visit(conn, media, cam, t + timedelta(hours=2), video=None)  # video missing
    # a second clip of v1, 20 s later: same visit
    cid = repo.add_clip(conn, cam, "/x.h265", t + timedelta(seconds=20), t + timedelta(seconds=30), "video", 1)
    repo.set_clip_status(conn, cid, "ready", web_path=f"c{cid}.mp4")
    (media / f"c{cid}.mp4").write_bytes(b"more")
    repo.set_recognition(conn, cid, best_frame_path=None, verdict_json=verdict_to_json(sure()), recognized_at=t)
    assert assign_visit(conn, repo.get_clip(conn, cid), sure()) == v1

    plan = zips.plan_zip(conn, media, visit_ids=[v3, v1, v2, 9999])
    names = [n for n, _ in plan.entries]
    assert names == [
        "2026-11-02 09-12 Great tit.mp4",
        "2026-11-02 09-12 Great tit (2).mp4",
        "2026-11-02 09-12 Great tit.jpg",
        "2026-11-02 10-12 Great tit.mp4",
        "2026-11-02 11-12 Great tit.jpg",
    ]
    assert plan.visits == 3 and plan.size_bytes == 3 + 4 + 3 + 3 + 3
    assert plan.filename == "fat-ball-3-visits.zip"


def test_plan_makes_names_unique_and_labels(conn, media, cam):
    t = datetime(2026, 11, 2, 9, 12, 5)
    _, a = add_visit(conn, media, cam, t)
    _, b = add_visit(conn, media, cam, t + timedelta(minutes=5))
    conn.execute("UPDATE visit SET started_at = ? WHERE id = ?", (t.isoformat(), b))  # same minute and label
    _, d = add_visit(conn, media, cam, t + timedelta(minutes=30), sure(DOG, "other"))
    _, u = add_visit(conn, media, cam, t + timedelta(minutes=60), Verdict("birds", None, 0.3, [], "unknown", None))
    _, e = add_visit(conn, media, cam, t + timedelta(minutes=90), Verdict("other", None, 0.9, [], "nothing", None))
    _, p = add_visit(conn, media, cam, t + timedelta(minutes=120), Verdict("other", None, 0.9, [], "person", None))
    _, f = add_visit(conn, media, cam, t + timedelta(minutes=150), sure(FOX, "other_animals"))
    plan = zips.plan_zip(conn, media, visit_ids=list(dict.fromkeys([a, b, d, u, e, p, f])))
    names = [n for n, _ in plan.entries if n.endswith(".mp4")]
    assert len(set(names)) == len(names) and "2026-11-02 09-12 Great tit (2).mp4" in names
    for label in ("Dog", "Unknown bird", "Empty clip", "Person", "Red fox"):
        assert any(n.endswith(f" {label}.mp4") for n in names), (label, names)


def test_plan_refuses_501_visits(conn, media, cam):
    with pytest.raises(zips.TooMany):
        zips.plan_zip(conn, media, visit_ids=list(range(1, 502)))
    assert zips.MAX_VISITS == 500


def test_plan_nothing_to_download(conn, media, cam):
    _, v = add_visit(conn, media, cam, datetime(2026, 11, 2, 9, 0), video=None, frame=None)
    with pytest.raises(zips.NothingToDownload):
        zips.plan_zip(conn, media, visit_ids=[v])
    with pytest.raises(zips.NothingToDownload):
        zips.plan_zip(conn, media, day=date(2026, 1, 1))


def test_stream_zip_is_valid_and_chunked(conn, media, cam):
    big = bytes(range(256)) * (3 * 1024 * 4)  # 3 MB
    _, v = add_visit(conn, media, cam, datetime(2026, 11, 2, 9, 0), video=big)
    plan = zips.plan_zip(conn, media, visit_ids=[v])
    chunks = list(zips.stream_zip(plan))
    assert len(chunks) > 1
    z = zipfile.ZipFile(BytesIO(b"".join(chunks)))
    assert z.testzip() is None
    assert z.read("2026-11-02 09-00 Great tit.mp4") == big
    assert all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist())


def test_stream_skips_a_file_gone_since_the_plan(conn, media, cam, caplog):
    _, gone = add_visit(conn, media, cam, datetime(2026, 11, 2, 9, 0))
    _, kept = add_visit(conn, media, cam, datetime(2026, 11, 2, 10, 0))
    plan = zips.plan_zip(conn, media, visit_ids=[gone, kept])
    first = plan.entries[0]
    first[1].unlink()  # deleted (e.g. an empty clip) between planning and streaming
    with caplog.at_level("WARNING", logger="fatball.zips"):
        z = zipfile.ZipFile(BytesIO(b"".join(zips.stream_zip(plan))))
    assert z.testzip() is None
    assert first[0] not in z.namelist()
    assert z.namelist() == [name for name, _ in plan.entries[1:]]
    assert first[0] in caplog.text


def test_day_zip_for_category(conn, media, cam):
    t = datetime(2026, 11, 2, 9, 0)
    add_visit(conn, media, cam, t)
    add_visit(conn, media, cam, t + timedelta(hours=1), sure(FOX, "other_animals"))
    add_visit(conn, media, cam, t + timedelta(days=1))
    plan = zips.plan_zip(conn, media, day=date(2026, 11, 2), category="birds")
    assert plan.filename == "fat-ball-2026-11-02.zip"
    assert plan.visits == 1 and [n for n, _ in plan.entries] == [
        "2026-11-02 09-00 Great tit.mp4", "2026-11-02 09-00 Great tit.jpg"]
    assert zips.plan_zip(conn, media, day=date(2026, 11, 2)).visits == 2


def test_plan_skips_paths_outside_media_dir(conn, media, cam, tmp_path):
    t = datetime(2026, 11, 2, 9, 0)
    cid, v = add_visit(conn, media, cam, t, video=None, frame=None)
    (tmp_path / "outside.mp4").write_bytes(b"secret")
    (tmp_path / "outside.jpg").write_bytes(b"secret")
    conn.execute("UPDATE clip SET web_path = '../outside.mp4' WHERE id = ?", (cid,))
    conn.execute("UPDATE clip SET best_frame_path = ? WHERE id = ?", (str(tmp_path / "outside.jpg"), cid))
    conn.execute("UPDATE visit SET best_frame_path = ? WHERE id = ?", (str(tmp_path / "outside.jpg"), v))
    conn.commit()
    with pytest.raises(zips.NothingToDownload):
        zips.plan_zip(conn, media, visit_ids=[v])
    _, v2 = add_visit(conn, media, cam, t + timedelta(hours=1))
    plan = zips.plan_zip(conn, media, visit_ids=[v, v2])
    assert plan.size_bytes == 6 and plan.visits == 1


def test_plan_names_distinct_with_multi_clip_and_same_minute(conn, media, cam):
    t = datetime(2026, 11, 2, 9, 12, 0)
    _, a = add_visit(conn, media, cam, t)
    cid = repo.add_clip(conn, cam, "/x.h265", t + timedelta(seconds=20), t + timedelta(seconds=30), "video", 1)
    repo.set_clip_status(conn, cid, "ready", web_path=f"c{cid}.mp4")
    (media / f"c{cid}.mp4").write_bytes(b"x")
    repo.set_recognition(conn, cid, best_frame_path=None, verdict_json=verdict_to_json(sure()), recognized_at=t)
    assert assign_visit(conn, repo.get_clip(conn, cid), sure()) == a
    _, b = add_visit(conn, media, cam, t + timedelta(minutes=5))
    conn.execute("UPDATE visit SET started_at = ? WHERE id IN (?, ?)", (t.isoformat(), a, b))
    conn.commit()
    names = [n for n, _ in zips.plan_zip(conn, media, visit_ids=[a, b]).entries]
    assert len(names) == 5 and len({n.lower() for n in names}) == 5


def test_plan_label_cannot_make_folders(conn, media, cam):
    _, v = add_visit(conn, media, cam, datetime(2026, 11, 2, 9, 0))
    conn.execute("UPDATE species_name SET name = '..x/a\\c' WHERE species_id = (SELECT id FROM species WHERE scientific_name = ?)", (GREAT,))
    conn.commit()
    for name, _ in zips.plan_zip(conn, media, visit_ids=[v]).entries:
        assert "/" not in name and "\\" not in name and not name[len("2026-11-02 09-00 "):].startswith(".")


def test_plan_accepts_exactly_500_visit_ids(conn, media, cam):
    _, v = add_visit(conn, media, cam, datetime(2026, 11, 2, 9, 0))
    assert zips.plan_zip(conn, media, visit_ids=[v] + list(range(1000, 1499))).visits == 1

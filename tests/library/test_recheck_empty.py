from datetime import datetime, timedelta

from fatball.library import repo
from fatball.library.db import connect

T0 = datetime(2026, 11, 4, 9, 0, 0)


def _visit(conn, cam, n, subject, *, moved=False, deleted=False):
    begin = T0 + timedelta(minutes=n)
    clip = repo.add_clip(conn, cam, f"/{n}.h265", begin, begin + timedelta(seconds=10), "video", 1)
    repo.set_clip_status(conn, clip, "ready", web_path=f"c{clip}.mp4")
    conn.execute("UPDATE clip SET recognized_at = ?, deleted_at = ? WHERE id = ?",
                 (begin.isoformat(), begin.isoformat() if deleted else None, clip))
    category = "birds" if subject == "species" else "other"
    cur = conn.execute("INSERT INTO visit(started_at, ended_at, category, subject, moved_by_user) VALUES (?, ?, ?, ?, ?)",
                       (begin.isoformat(), begin.isoformat(), category, subject, int(moved)))
    conn.execute("INSERT INTO visit_clip VALUES (?, ?)", (cur.lastrowid, clip))
    conn.commit()
    return clip


def _wanted(conn, clip):
    row = conn.execute("SELECT recognized_at, recognition_wanted FROM clip WHERE id = ?", (clip,)).fetchone()
    return row["recognized_at"] is None and row["recognition_wanted"] == 1


def test_only_empty_visits_the_owner_did_not_move_are_queued_again(tmp_path):
    conn = connect(tmp_path / "lib.db")
    cam = repo.upsert_camera(conn, "feeder", None, None)
    empty = _visit(conn, cam, 0, "nothing")
    moved = _visit(conn, cam, 1, "nothing", moved=True)
    bird = _visit(conn, cam, 2, "species")
    gone = _visit(conn, cam, 3, "nothing", deleted=True)

    assert repo.requeue_empty_visits(conn) == 1

    assert _wanted(conn, empty)
    assert not any(_wanted(conn, c) for c in (moved, bird, gone))

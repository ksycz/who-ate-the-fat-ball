import subprocess
import threading
from datetime import datetime, timedelta

import pytest

from fatball import notify
from fatball.library import corrections, repo
from fatball.library.db import connect
from fatball.library.visits import assign_visit
from fatball.recognition.matcher import Verdict
from fatball.recognition.recognizer import verdict_to_json

START = datetime(2026, 11, 3, 9, 0)


def row(name, new=False):
    return {"species_name": name, "is_new_species": new}


def test_messages_group_and_name():
    assert notify.messages([row("great tit"), row("blue tit"), row("great tit")]) == [
        "3 new visits: great tit, blue tit"]
    assert notify.messages([row(None)]) == ["1 new visit: unknown bird"]
    assert notify.messages([]) == []


def test_messages_new_species_separate():
    out = notify.messages([row("great tit"), row("eurasian nuthatch", True)])
    assert out == ["2 new visits: great tit, eurasian nuthatch", "New species: eurasian nuthatch"]


def test_messages_more_than_three_names():
    rows = [row(n) for n in ("great tit", "blue tit", "robin", "wren", "dunnock")]
    assert notify.messages(rows) == ["5 new visits: great tit, blue tit, robin and 2 more"]


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "lib.db")
    repo.ensure_catalog(c)
    yield c
    c.close()


def add_visit(conn, species, begin=START, length=10):
    cam = repo.upsert_camera(conn, "feeder", None, None)
    cid = repo.add_clip(conn, cam, f"/c{begin.isoformat()}.h265", begin, begin + timedelta(seconds=length), "h264", 1)
    verdict = Verdict("birds", species, 0.9 if species else 0.4,
                      [(species, 0.9)] if species else [], "species" if species else "unknown", None)
    repo.set_recognition(conn, cid, best_frame_path="f.jpg", verdict_json=verdict_to_json(verdict), recognized_at=begin)
    return assign_visit(conn, repo.get_clip(conn, cid), verdict)


def run_one_pass(conn, now, send):
    stop = threading.Event()
    sent = []

    def fake(title, body):
        sent.append((title, body))
        send(title, body)

    # one pass: the fake send never stops it, so stop after the first wait
    stop.wait = lambda _t: stop.set()
    notify.notifier_loop(conn, stop, lambda: now, send=fake, interval_s=0)
    return sent


def test_loop_waits_until_settled(conn):
    add_visit(conn, "Parus major")  # ends 09:00:10
    assert run_one_pass(conn, START + timedelta(seconds=40), lambda *a: None) == []  # ended 30 s ago
    sent = run_one_pass(conn, START + timedelta(seconds=100), lambda *a: None)  # ended 90 s ago
    assert sent[0][0] == "Who Ate the Fat Ball?"
    assert sent[0][1] == "1 new visit: great tit"
    assert ("Who Ate the Fat Ball?", "New species: great tit") in sent
    assert run_one_pass(conn, START + timedelta(hours=1), lambda *a: None) == []  # marked, not repeated


def test_unknown_bird_is_announced(conn):
    add_visit(conn, None)
    sent = run_one_pass(conn, START + timedelta(minutes=5), lambda *a: None)
    assert [b for _, b in sent] == ["1 new visit: unknown bird"]


def test_loop_off_marks_without_sending(conn):
    repo.set_setting(conn, "notifications", "off")
    add_visit(conn, "Parus major")
    later = START + timedelta(minutes=5)
    assert run_one_pass(conn, later, lambda *a: None) == []
    repo.set_setting(conn, "notifications", "on")
    assert run_one_pass(conn, later + timedelta(minutes=1), lambda *a: None) == []  # no flood
    assert conn.execute("SELECT COUNT(*) FROM visit WHERE notified_at IS NULL").fetchone()[0] == 0


def test_loop_survives_a_failing_send(conn):
    add_visit(conn, "Parus major")

    def boom(*a):
        raise RuntimeError("no")

    run_one_pass(conn, START + timedelta(minutes=5), boom)  # must not raise
    assert conn.execute("SELECT COUNT(*) FROM visit WHERE notified_at IS NULL").fetchone()[0] == 0


def test_send_banner_passes_text_as_arguments(monkeypatch):
    monkeypatch.setattr(notify, "terminal_notifier", lambda: None)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)))
    notify.send_banner("The title", "secret body text")
    cmd, kw = calls[0]
    assert cmd[0] == "osascript" and kw["timeout"] == 10
    script = cmd[cmd.index("-e") + 1]
    assert "secret body text" not in script and "The title" not in script
    assert "item 2 of argv" in script and "item 1 of argv" in script
    assert cmd[-2:] == ["The title", "secret body text"]


TN = "/opt/homebrew/bin/terminal-notifier"


def test_with_terminal_notifier_a_click_opens_the_gallery(monkeypatch):
    monkeypatch.setattr(notify, "terminal_notifier", lambda: TN)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)))
    notify.send_banner("The title", "2 new visits: great tit", url="http://localhost:8080/")
    [(cmd, kw)] = calls
    assert cmd == [TN, "-title", "The title", "-message", "2 new visits: great tit",
                   "-open", "http://localhost:8080/"]
    assert kw["timeout"] == 10


def test_a_failing_terminal_notifier_falls_back_to_osascript(monkeypatch):
    monkeypatch.setattr(notify, "terminal_notifier", lambda: TN)
    calls = []

    def run(cmd, **kw):
        calls.append(cmd[0])
        if cmd[0] == TN:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", run)
    notify.send_banner("t", "b", url="http://localhost:8080/")
    assert calls == [TN, "osascript"]


def test_terminal_notifier_is_found_in_homebrew_even_off_the_path(monkeypatch, tmp_path):
    tool = tmp_path / "terminal-notifier"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    monkeypatch.setattr(notify.shutil, "which", lambda name: None)  # a LaunchAgent's PATH has no Homebrew
    monkeypatch.setattr(notify, "TERMINAL_NOTIFIER_PLACES", (tmp_path / "missing", tool))
    assert notify.terminal_notifier() == str(tool)


def test_send_banner_never_raises(monkeypatch):
    def fail(*a, **kw):
        raise subprocess.TimeoutExpired("osascript", 10)

    monkeypatch.setattr(subprocess, "run", fail)
    notify.send_banner("t", "b")


def test_old_clip_recognised_now_is_marked_without_a_banner(conn):
    month_ago = START - timedelta(days=30)
    add_visit(conn, "Parus major", begin=month_ago)  # a backfill: also the species' first sighting
    assert run_one_pass(conn, START, lambda *a: None) == []
    assert conn.execute("SELECT COUNT(*) FROM visit WHERE notified_at IS NULL").fetchone()[0] == 0


def test_other_visit_moved_to_birds_gets_no_banner(conn):
    cam = repo.upsert_camera(conn, "feeder", None, None)
    cid = repo.add_clip(conn, cam, "/other.h265", START, START + timedelta(seconds=10), "h264", 1)
    verdict = Verdict("other", None, 0.9, [], "nothing", None)
    repo.set_recognition(conn, cid, best_frame_path="f.jpg", verdict_json=verdict_to_json(verdict), recognized_at=START)
    visit_id = assign_visit(conn, repo.get_clip(conn, cid), verdict)
    assert run_one_pass(conn, START + timedelta(minutes=5), lambda *a: None) == []
    corrections.apply_many(conn, [visit_id], corrections.Change(category="birds", teach=False))
    assert run_one_pass(conn, START + timedelta(minutes=6), lambda *a: None) == []


def test_retrying_an_old_clip_gets_no_banner(conn):
    month_ago = START - timedelta(days=30)
    add_visit(conn, "Parus major", begin=month_ago)
    run_one_pass(conn, START, lambda *a: None)
    clip = repo.get_clip(conn, conn.execute("SELECT id FROM clip").fetchone()[0])
    verdict = Verdict("birds", "Parus major", 0.9, [("Parus major", 0.9)], "species", None)
    assign_visit(conn, clip, verdict)  # Retry: the clip leaves its visit and gets a fresh one
    assert conn.execute("SELECT COUNT(*) FROM visit WHERE notified_at IS NULL").fetchone()[0] == 1
    assert run_one_pass(conn, START + timedelta(minutes=1), lambda *a: None) == []

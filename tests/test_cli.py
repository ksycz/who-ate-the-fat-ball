import os
import signal
import socket
import subprocess
import sys
import threading
import time
import warnings
from datetime import datetime, timedelta

import numpy as np
import pytest

from fatball import cli
from fatball.api.auth import PIN_KEY
from fatball.camera.client import XMClient
from fatball.camera.protocol import sofia_hash
from fatball.config import Settings
from fatball.library import repo
from fatball.library.db import connect
from fatball.media.convert import FFMPEG
from fatball.recognition.detector import Detection
from fatball.recognition.fake import FakeDetector

GREAT_TIT = "Parus major"


def test_cli_help_lists_all_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in ("serve", "demo", "setup", "set-camera-password", "examples-import"):
        assert command in out


def test_serve_defaults_listen_on_lan_port_8080():
    args = cli.build_parser().parse_args(["serve"])
    assert (args.host, args.port) == ("0.0.0.0", 8080)
    assert cli.build_parser().parse_args(["demo"]).port == 8080


def test_demo_listens_on_this_mac_only_by_default():
    assert cli.build_parser().parse_args(["demo"]).host == "127.0.0.1"
    assert cli.build_parser().parse_args(["demo", "--host", "0.0.0.0"]).host == "0.0.0.0"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_sigterm_runs_the_shutdown_clean_up(tmp_path):
    port = _free_port()
    env = {**os.environ, "FATBALL_DATA_DIR": str(tmp_path / "data"), "PYTHONUNBUFFERED": "1",
           # The child must never reach the real Keychain: with no password the watcher contacts nothing.
           "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
    cmd = [sys.executable, "-c", "import sys; from fatball.cli import main; sys.exit(main())",
           "serve", "--host", "127.0.0.1", "--port", str(port)]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)
        else:
            pytest.fail(f"server never listened: {proc.communicate(timeout=5)[0]}")
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=8)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert proc.returncode == 0, out
    assert "Stopped." in out


class Prompts:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked: list[str] = []

    def __call__(self, prompt=""):
        self.asked.append(prompt)
        return self.answers.pop(0)


@pytest.fixture
def setup_cli(tmp_path):
    conns = []

    def run(*, typed, secret, stored=None):
        saved: list[str] = []
        settings = Settings(data_dir=tmp_path / "data")
        code = cli.run_setup(settings, input_fn=Prompts(*typed), getpass_fn=Prompts(*secret),
                             get_password=lambda: stored, set_password=saved.append)
        conns.append(connect(settings.db_path))
        return code, saved, conns[-1]

    yield run
    for c in conns:
        c.close()


def test_setup_stores_ip_password_and_pin_hash(setup_cli, capsys):
    code, saved, conn = setup_cli(typed=["192.168.1.40"], secret=["hunter2", "1234"])
    assert code == 0
    assert saved == ["hunter2"]
    assert repo.get_camera(conn).last_ip == "192.168.1.40"
    stored = repo.get_setting(conn, PIN_KEY)
    assert stored.startswith("scrypt$") and "1234" not in stored.split("$")  # a random hex hash may contain "1234"
    out = capsys.readouterr().out
    assert "hunter2" not in out and "1234" not in out


def test_setup_fills_the_species_catalog(setup_cli):
    _, _, conn = setup_cli(typed=[""], secret=["", ""], stored="old")
    assert conn.execute("SELECT COUNT(*) FROM species").fetchone()[0] == 48


def test_serve_fills_the_species_catalog_so_a_first_correction_works(tmp_path, monkeypatch):
    import uvicorn

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*starlette.testclient.*")  # as in tests/api/conftest.py
        from fastapi.testclient import TestClient

    from fatball.api.app import create_app
    from fatball.library.visits import assign_visit
    from fatball.recognition.matcher import Verdict

    def stop_at_once(server):
        raise KeyboardInterrupt

    monkeypatch.setattr(uvicorn.Server, "run", stop_at_once)
    settings = Settings(data_dir=tmp_path / "data")  # a fresh install: nothing pre-fills the catalog
    cli.serve(settings, host="127.0.0.1", port=_free_port(), detector_loader=lambda: None)
    conn = connect(settings.db_path)
    try:
        cam = repo.upsert_camera(conn, "feeder", None, None)
        begin = datetime(2026, 10, 30, 8)
        clip = repo.add_clip(conn, cam, "/a.h265", begin, begin + timedelta(seconds=10), "video", 1)
        visit = assign_visit(conn, repo.get_clip(conn, clip), Verdict("birds", None, 0.4, [], "unknown", None))
        client = TestClient(create_app(settings), client=("127.0.0.1", 5000), base_url="http://localhost")
        assert client.patch(f"/api/visits/{visit}", json={"species": GREAT_TIT}).status_code == 200
        assert repo.category_for(conn, GREAT_TIT) == "birds"
    finally:
        conn.close()


def test_setup_blank_keeps_everything(setup_cli):
    code, saved, conn = setup_cli(typed=[""], secret=["", ""], stored="old")
    assert code == 0
    assert saved == []
    assert repo.get_camera(conn) is None
    assert repo.get_setting(conn, PIN_KEY) is None


def test_setup_reasks_a_bad_pin(setup_cli):
    code, _, conn = setup_cli(typed=[""], secret=["", "12a4", "99999", "4321"], stored="old")
    assert code == 0
    assert repo.get_setting(conn, PIN_KEY) is not None


def test_setup_rejects_a_bad_ip(setup_cli):
    code, _, conn = setup_cli(typed=["not an ip", "10.0.0.9"], secret=["", ""], stored="old")
    assert code == 0
    assert repo.get_camera(conn).last_ip == "10.0.0.9"


def test_setup_can_store_an_empty_camera_password_when_none_is_kept(setup_cli):
    code, saved, _ = setup_cli(typed=["", "y"], secret=["", ""], stored=None)
    assert code == 0
    assert saved == [""]


def test_processor_loop_survives_errors_and_stops(tmp_path, monkeypatch):
    calls = []
    qos_calls = []
    monkeypatch.setattr(cli.qos, "set_background_priority", lambda: qos_calls.append(1) or True)
    stop = threading.Event()

    class Flaky:
        def process_pending(self):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("database is locked")
            if len(calls) >= 3:
                stop.set()
            return 0

    cli.processor_loop(Flaky(), stop, interval_s=0.01)
    assert len(calls) == 3
    assert qos_calls == [1]  # once, at thread start


@pytest.fixture
def set_pw_cli(tmp_path, fake_camera):
    def run(*, secret, stored="", ip="127.0.0.1"):
        saved: list[str] = []
        settings = Settings(data_dir=tmp_path / "data", camera_port=fake_camera.port)
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        if ip:
            c = connect(settings.db_path)
            repo.upsert_camera(c, "feeder", None, ip)
            c.close()
        code = cli.run_set_camera_password(
            settings, getpass_fn=Prompts(*secret), get_password=lambda: stored, set_password=saved.append,
            connect=lambda host, port: XMClient(host, port, timeout=2.0, silence_s=0.5))
        return code, saved

    return run


def test_set_camera_password_changes_checks_and_saves(set_pw_cli, fake_camera, capsys):
    code, saved = set_pw_cli(secret=["garden-robin", "garden-robin"])
    assert code == 0
    assert saved == ["garden-robin"]
    assert fake_camera.password_hash == sofia_hash("garden-robin")
    assert "garden-robin" not in capsys.readouterr().out


def test_set_camera_password_mismatch_or_short_changes_nothing(set_pw_cli, fake_camera):
    assert set_pw_cli(secret=["garden-robin", "garden-robim"]) == (1, [])
    assert set_pw_cli(secret=["abc", "abc"]) == (1, [])
    assert fake_camera.password_hash == sofia_hash("")


def test_set_camera_password_refuses_when_the_saved_password_is_wrong(set_pw_cli, fake_camera):
    fake_camera.password = "something-else"
    assert set_pw_cli(secret=[]) == (1, [])
    assert fake_camera.password == "something-else"


def test_set_camera_password_needs_a_known_camera_ip(set_pw_cli):
    assert set_pw_cli(secret=[], ip=None) == (1, [])


# examples-import


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.qos, "set_background_priority", lambda: True)  # never lower the test runner itself
    settings = Settings(data_dir=tmp_path / "data")
    settings.data_dir.mkdir()
    conn = connect(settings.db_path)
    repo.ensure_catalog(conn)
    cam = repo.upsert_camera(conn, "feeder", None, None)
    clips = []
    for i in range(3):
        begin = datetime(2026, 10, 30, 8 + i)
        clip = repo.add_clip(conn, cam, f"/{i}.h265", begin, begin + timedelta(seconds=4), "video", 1)
        conn.execute("UPDATE clip SET recognized_at = ? WHERE id = ?", (begin.isoformat(), clip))
        for cls, conf in (("animal", 0.9), ("animal", 0.9), ("person", 0.9), ("animal", 0.1)):
            conn.execute("INSERT INTO detection(clip_id, frame_index, cls, conf, x1, y1, x2, y2, feature) "
                         "VALUES (?, 0, ?, ?, 0, 0, 1, 1, ?)", (clip, cls, conf, b"\x00" * 8))
        clips.append(clip)
    conn.commit()
    yield settings, conn, clips
    conn.close()


def _csv(tmp_path, *rows):
    path = tmp_path / "labels.csv"
    path.write_text("clip_id,label\n" + "".join(f"{c},{label}\n" for c, label in rows))
    return path


def _stored(conn):
    return [tuple(r) for r in conn.execute("SELECT clip_id, label, label_source FROM detection ORDER BY id")]


def _no_model():
    return None


def test_import_labels_animal_detections(library, tmp_path, capsys):
    settings, conn, (a, b, c) = library
    path = _csv(tmp_path, (a, "Great Tit"), (b, "dog"), (c, "nothing"))
    assert cli.run_examples_import(settings, path, detector_loader=_no_model) == 0
    assert capsys.readouterr().out.strip() == "6 examples from 3 clips"
    rows = _stored(conn)
    assert [r for r in rows if r[0] == a and r[1]] == [(a, GREAT_TIT, "import")] * 2
    assert {r[1] for r in rows if r[0] == b} == {repo.DOG, None}
    assert {r[1] for r in rows if r[0] == c} == {"nothing", None}
    assert sum(r[1] is None for r in rows) == 6  # the person and the weak animal box stay unlabelled


def test_import_rejects_unknown_name_and_writes_nothing(library, tmp_path, capsys):
    settings, conn, (a, b, _) = library
    path = _csv(tmp_path, (a, "great tit"), (b, "unicorn"), (999, "dog"))
    assert cli.run_examples_import(settings, path, detector_loader=_no_model) == 1
    out = capsys.readouterr().out
    assert "unicorn" in out and "999" in out
    assert all(r[1] is None for r in _stored(conn))


def test_import_person_and_skip_add_nothing(library, tmp_path, capsys):
    settings, conn, (a, b, _) = library
    path = _csv(tmp_path, (a, "person"), (b, "skip"))
    assert cli.run_examples_import(settings, path, detector_loader=_no_model) == 0
    assert capsys.readouterr().out.strip() == "0 examples from 0 clips"
    assert all(r[1] is None for r in _stored(conn))


def test_import_twice_is_idempotent(library, tmp_path, capsys):
    settings, conn, (a, b, _) = library
    path = _csv(tmp_path, (a, "Parus major"), (b, "Passer domesticus"))
    for _ in range(2):
        assert cli.run_examples_import(settings, path, detector_loader=_no_model) == 0
        assert capsys.readouterr().out.strip() == "4 examples from 2 clips"
    assert sorted({(r[0], r[1]) for r in _stored(conn) if r[1]}) == [(a, GREAT_TIT), (b, "Passer domesticus")]


def test_import_keeps_a_later_correction(library, tmp_path, capsys):
    settings, conn, (a, _, _) = library
    conn.execute("UPDATE detection SET label = 'Passer domesticus', label_source = 'correction' "
                 "WHERE id = (SELECT MIN(id) FROM detection WHERE clip_id = ?)", (a,))
    conn.commit()
    assert cli.run_examples_import(settings, _csv(tmp_path, (a, "Parus major")), detector_loader=_no_model) == 0
    assert capsys.readouterr().out.strip() == "1 examples from 1 clips"
    assert {r[1:] for r in _stored(conn) if r[0] == a and r[1]} == {("Passer domesticus", "correction"),
                                                                    (GREAT_TIT, "import")}


def test_import_needing_recognition_without_a_model_writes_nothing(library, tmp_path, capsys):
    settings, conn, (a, b, _) = library
    conn.execute("UPDATE clip SET recognized_at = NULL WHERE id = ?", (b,))
    conn.commit()
    path = _csv(tmp_path, (a, "Parus major"), (b, "Parus major"))
    assert cli.run_examples_import(settings, path, detector_loader=_no_model) == 1
    assert f"{b}" in capsys.readouterr().out
    assert all(r[1] is None for r in _stored(conn))


def _unrecognise_with_video(settings, conn, clip_id):
    """Make the clip a converted video that has not been recognised yet (a real 2 s test pattern)."""
    conn.execute("DELETE FROM detection WHERE clip_id = ?", (clip_id,))
    conn.execute("UPDATE clip SET recognized_at = NULL WHERE id = ?", (clip_id,))
    web = settings.media_dir / "clips" / str(clip_id) / "web.mp4"
    web.parent.mkdir(parents=True)
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10",
                    "-t", "2", "-pix_fmt", "yuv420p", str(web)], check=True)
    repo.set_clip_status(conn, clip_id, "ready", web_path=web.relative_to(settings.media_dir).as_posix())


def test_import_recognises_an_unrecognised_clip_first(library, tmp_path, capsys):
    settings, conn, (a, _, _) = library
    _unrecognise_with_video(settings, conn, a)
    detector = FakeDetector({1: [Detection("animal", 0.9, (0.2, 0.2, 0.6, 0.6))]})
    features = lambda path, box: np.array([1.0, 0.0], dtype=np.float32)
    code = cli.run_examples_import(settings, _csv(tmp_path, (a, "Parus major")),
                                   detector_loader=lambda: detector, features=features)
    assert code == 0
    assert capsys.readouterr().out.strip() == "1 examples from 1 clips"
    assert repo.is_recognized(conn, a)
    assert repo.visit_for_clip(conn, a) is not None  # in a visit, like any clip the processor recognises


class BrokenDetector:
    def detect(self, image_path):
        raise RuntimeError("model blew up")


def test_import_recognition_failure_is_reported_and_labels_nothing(library, tmp_path, capsys):
    settings, conn, (a, b, _) = library
    _unrecognise_with_video(settings, conn, b)
    path = _csv(tmp_path, (a, "Parus major"), (b, "Parus major"))  # a is already recognised, b is not
    code = cli.run_examples_import(settings, path, detector_loader=lambda: BrokenDetector(),
                                   features=lambda path, box: np.array([1.0, 0.0], dtype=np.float32))
    assert code == 1
    out = capsys.readouterr().out
    assert f"clip {b}" in out and "model blew up" in out
    assert all(r[1] is None for r in _stored(conn))  # nothing labelled, not even the recognised clip a
    assert conn.execute("SELECT recognition_error FROM clip WHERE id = ?", (b,)).fetchone()[0] is not None


def test_import_runs_at_background_priority(library, tmp_path, monkeypatch, capsys):
    settings, _, (a, _, _) = library
    calls = []
    monkeypatch.setattr(cli.qos, "set_background_priority", lambda: calls.append(1) or True)
    assert cli.run_examples_import(settings, _csv(tmp_path, (a, "Parus major")), detector_loader=_no_model) == 0
    assert calls == [1]

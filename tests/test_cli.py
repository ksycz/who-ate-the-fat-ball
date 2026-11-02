import os
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest

from fatball import cli
from fatball.api.auth import PIN_KEY
from fatball.camera.client import XMClient
from fatball.camera.protocol import sofia_hash
from fatball.config import Settings
from fatball.library import repo
from fatball.library.db import connect


def test_cli_help_lists_all_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in ("serve", "demo", "setup", "set-camera-password"):
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


def test_processor_loop_survives_errors_and_stops(tmp_path):
    calls = []
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

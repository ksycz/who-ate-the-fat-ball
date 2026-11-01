import threading

import pytest

from fatball import cli
from fatball.api.auth import PIN_KEY
from fatball.config import Settings
from fatball.library import repo
from fatball.library.db import connect


def test_cli_help_lists_serve_demo_setup(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in ("serve", "demo", "setup"):
        assert command in out


def test_serve_defaults_listen_on_lan_port_8080():
    args = cli.build_parser().parse_args(["serve"])
    assert (args.host, args.port) == ("0.0.0.0", 8080)
    assert cli.build_parser().parse_args(["demo"]).port == 8080


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
    assert stored.startswith("scrypt$") and "1234" not in stored
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

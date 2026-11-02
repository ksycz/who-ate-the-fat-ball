import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("e2e_server", Path(__file__).parent.parent / "scripts" / "e2e_server.py")
e2e_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(e2e_server)


def test_wipe_refuses_a_folder_it_did_not_seed(tmp_path):
    (tmp_path / "precious.txt").write_text("keep")
    with pytest.raises(SystemExit) as e:
        e2e_server.wipe(tmp_path)
    assert ".fatball-e2e" in str(e.value)
    assert (tmp_path / "precious.txt").exists()


def test_wipe_accepts_missing_and_empty_folders(tmp_path):
    e2e_server.wipe(tmp_path / "new")
    assert (tmp_path / "new").is_dir()
    e2e_server.wipe(tmp_path / "new")


def test_wipe_clears_a_marked_folder(tmp_path):
    (tmp_path / ".fatball-e2e").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x").write_text("x")
    e2e_server.wipe(tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == [".fatball-e2e"]


def test_wipe_still_refuses_the_real_library_name(tmp_path):
    real = tmp_path / "WhoAteTheFatBall"
    real.mkdir()
    (real / ".fatball-e2e").write_text("")
    with pytest.raises(SystemExit):
        e2e_server.wipe(real)

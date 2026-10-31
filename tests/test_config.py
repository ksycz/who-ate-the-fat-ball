from pathlib import Path

from fatball.config import Settings


def test_default_data_dir_is_application_support(monkeypatch):
    monkeypatch.delenv("FATBALL_DATA_DIR", raising=False)
    s = Settings.load()
    assert s.data_dir == Path.home() / "Library/Application Support/WhoAteTheFatBall"


def test_env_overrides_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("FATBALL_DATA_DIR", str(tmp_path))
    s = Settings.load()
    assert s.data_dir == tmp_path
    assert s.db_path == tmp_path / "library.sqlite"
    assert s.media_dir == tmp_path / "media"

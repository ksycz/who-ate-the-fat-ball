import sqlite3
from importlib import resources

from fatball.library import repo
from fatball.library.db import SCHEMA_VERSION, connect
from fatball.recognition.catalog import DOG


def _version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_fresh_database_is_v3(tmp_path):
    conn = connect(tmp_path / "lib.db")
    assert SCHEMA_VERSION == 3
    assert _version(conn) == 3
    assert {"recognized_at", "best_frame_path", "recognition_error", "verdict_json"} <= _columns(conn, "clip")
    assert "recognition_wanted" in _columns(conn, "clip")
    assert "subject" in _columns(conn, "visit")
    assert {"cls", "feature", "label", "label_source"} <= _columns(conn, "detection")
    assert {"token", "visit_id", "before_json", "created_at"} == _columns(conn, "undo")
    conn.close()


def test_v1_database_upgrades_and_keeps_clips(tmp_path):
    path = tmp_path / "lib.db"
    raw = sqlite3.connect(path)
    schema = resources.files("fatball.library").joinpath("schema.sql").read_text(encoding="utf-8")
    raw.executescript(f"BEGIN;\n{schema}\nPRAGMA user_version = 1;\nCOMMIT;")
    raw.execute("INSERT INTO camera(id, name) VALUES (1, 'feeder')")
    raw.execute(
        "INSERT INTO clip(camera_id, sd_path, begin_at, end_at, kind) VALUES (1, '/a', 't0', 't1', 'motion')"
    )
    raw.commit()
    raw.close()

    conn = connect(path)
    assert _version(conn) == 3
    row = conn.execute("SELECT sd_path, recognized_at FROM clip").fetchone()
    assert row["sd_path"] == "/a"
    assert row["recognized_at"] is None
    conn.close()


def test_migration_is_idempotent(tmp_path):
    connect(tmp_path / "lib.db").close()
    conn = connect(tmp_path / "lib.db")
    assert _version(conn) == 3
    conn.close()


def test_ensure_catalog_twice_no_duplicates(tmp_path):
    conn = connect(tmp_path / "lib.db")
    repo.ensure_catalog(conn)
    first = conn.execute("SELECT COUNT(*) FROM species").fetchone()[0]
    repo.ensure_catalog(conn)
    assert conn.execute("SELECT COUNT(*) FROM species").fetchone()[0] == first == 48
    assert conn.execute("SELECT COUNT(*) FROM species_name").fetchone()[0] == first
    conn.close()


def test_category_rules(tmp_path):
    conn = connect(tmp_path / "lib.db")
    repo.ensure_catalog(conn)
    assert repo.category_for(conn, "Parus major") == "birds"
    assert repo.category_for(conn, DOG) == "other"
    assert repo.category_for(conn, "Vulpes vulpes") == "other_animals"
    assert repo.category_for(conn, None) == "other"
    assert repo.category_for(conn, "nothing") == "other"
    assert repo.category_for(conn, "Unknown unknown") == "other"
    conn.close()


def _v1_library(path):
    raw = sqlite3.connect(path)
    schema = resources.files("fatball.library").joinpath("schema.sql").read_text(encoding="utf-8")
    raw.executescript(f"BEGIN;\n{schema}\nPRAGMA user_version = 1;\nCOMMIT;")
    raw.execute("INSERT INTO camera(id, name) VALUES (1, 'feeder')")
    raw.execute(
        "INSERT INTO clip(camera_id, sd_path, begin_at, end_at, kind) VALUES (1, '/a', 't0', 't1', 'motion')"
    )
    raw.commit()
    raw.close()


def test_upgrading_a_v1_library_backs_it_up_first(tmp_path):
    path = tmp_path / "library.sqlite"
    _v1_library(path)
    connect(path).close()
    backup = tmp_path / "library.sqlite.v1.bak"
    assert backup.exists()
    raw = sqlite3.connect(backup)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
    assert raw.execute("SELECT sd_path FROM clip").fetchall() == [("/a",)]
    raw.close()
    connect(path).close()  # already current: the backup is kept as it was, no new one
    assert sorted(p.name for p in tmp_path.glob("*.bak")) == ["library.sqlite.v1.bak"]


def test_a_fresh_library_makes_no_backup(tmp_path):
    connect(tmp_path / "library.sqlite").close()
    connect(tmp_path / "library.sqlite").close()
    assert list(tmp_path.glob("*.bak")) == []


def test_v2_database_upgrades_to_v3_and_keeps_clips(tmp_path):
    path = tmp_path / "lib.db"
    _v1_library(path)
    raw = sqlite3.connect(path)
    for script in sorted(resources.files("fatball.library").joinpath("migrations").iterdir(), key=lambda e: e.name):
        if script.name.startswith("002"):
            raw.executescript(f"BEGIN;\n{script.read_text(encoding='utf-8')}\nPRAGMA user_version = 2;\nCOMMIT;")
    raw.close()

    conn = connect(path)
    assert _version(conn) == 3
    row = conn.execute("SELECT sd_path, recognition_wanted FROM clip").fetchone()
    assert (row["sd_path"], row["recognition_wanted"]) == ("/a", 0)
    conn.close()

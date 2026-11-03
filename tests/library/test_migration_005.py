import sqlite3
from importlib import resources

from fatball.library.db import SCHEMA_VERSION, connect


def test_migration_005_adds_columns_and_marks_old_visits_notified(tmp_path):
    path = tmp_path / "library.sqlite"
    raw = sqlite3.connect(path)
    schema = resources.files("fatball.library").joinpath("schema.sql").read_text(encoding="utf-8")
    raw.executescript(f"BEGIN;\n{schema}\nPRAGMA user_version = 1;\nCOMMIT;")
    for entry in sorted(resources.files("fatball.library").joinpath("migrations").iterdir(), key=lambda e: e.name):
        number = int(entry.name[:3])
        if number <= 4:
            raw.executescript(f"BEGIN;\n{entry.read_text(encoding='utf-8')}\nPRAGMA user_version = {number};\nCOMMIT;")
    raw.execute("INSERT INTO camera(id, name) VALUES (1, 'feeder')")
    raw.execute(
        "INSERT INTO clip(camera_id, sd_path, begin_at, end_at, kind) VALUES (1, '/a', 't0', 't1', 'motion')"
    )
    raw.execute(
        "INSERT INTO visit(started_at, ended_at, category) VALUES ('2026-11-01T08:00:00+01:00', 'e', 'birds')"
    )
    raw.commit()
    raw.close()

    conn = connect(path)
    assert SCHEMA_VERSION == 5
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    assert conn.execute("SELECT deleted_at FROM clip").fetchone()[0] is None
    row = conn.execute("SELECT started_at, notified_at FROM visit").fetchone()
    assert row["notified_at"] == row["started_at"] == "2026-11-01T08:00:00+01:00"
    conn.close()
    assert (tmp_path / "library.sqlite.v4.bak").exists()

import json
import sqlite3
from importlib import resources

from fatball.library.db import SCHEMA_VERSION, connect


def test_migration_006_moves_other_animals_into_other_and_keeps_species(tmp_path):
    path = tmp_path / "library.sqlite"
    raw = sqlite3.connect(path)
    schema = resources.files("fatball.library").joinpath("schema.sql").read_text(encoding="utf-8")
    raw.executescript(f"BEGIN;\n{schema}\nPRAGMA user_version = 1;\nCOMMIT;")
    for entry in sorted(resources.files("fatball.library").joinpath("migrations").iterdir(), key=lambda e: e.name):
        number = int(entry.name[:3])
        if number <= 5:
            raw.executescript(f"BEGIN;\n{entry.read_text(encoding='utf-8')}\nPRAGMA user_version = {number};\nCOMMIT;")
    raw.execute("INSERT INTO species(scientific_name, \"group\") VALUES ('Sciurus vulgaris', 'mammal')")
    squirrel = raw.execute("SELECT id FROM species").fetchone()[0]
    raw.execute(
        "INSERT INTO visit(started_at, ended_at, category, species_id) VALUES ('s1', 'e1', 'other_animals', ?)",
        (squirrel,),
    )
    raw.execute("INSERT INTO visit(started_at, ended_at, category) VALUES ('s2', 'e2', 'birds')")
    before = {"category": "other_animals", "species_id": squirrel}
    raw.execute(
        "INSERT INTO undo(token, visit_id, before_json, created_at) VALUES ('t', 1, ?, 'now')",
        (json.dumps({"bulk": [{"visit_id": 1, "before": before}]}),),
    )
    raw.commit()
    raw.close()

    conn = connect(path)
    assert SCHEMA_VERSION == 6
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    rows = conn.execute("SELECT category, species_id FROM visit ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("other", squirrel), ("birds", None)]
    undo = json.loads(conn.execute("SELECT before_json FROM undo").fetchone()[0])
    assert undo["bulk"][0]["before"]["category"] == "other"
    conn.close()
    assert (tmp_path / "library.sqlite.v5.bak").exists()

ALTER TABLE clip ADD COLUMN recognized_at TEXT;
ALTER TABLE clip ADD COLUMN best_frame_path TEXT;
ALTER TABLE clip ADD COLUMN recognition_error TEXT;
ALTER TABLE clip ADD COLUMN verdict_json TEXT;

ALTER TABLE visit ADD COLUMN subject TEXT;
CREATE INDEX visit_started ON visit(started_at);

CREATE TABLE detection (
    id INTEGER PRIMARY KEY,
    clip_id INTEGER NOT NULL REFERENCES clip(id),
    frame_index INTEGER NOT NULL,
    cls TEXT NOT NULL,
    conf REAL NOT NULL,
    x1 REAL NOT NULL,
    y1 REAL NOT NULL,
    x2 REAL NOT NULL,
    y2 REAL NOT NULL,
    feature BLOB,
    label TEXT,
    labelled_at TEXT,
    label_source TEXT CHECK (label_source IN ('import', 'correction'))
);
CREATE INDEX detection_clip ON detection(clip_id);
CREATE INDEX detection_label ON detection(label) WHERE label IS NOT NULL;

CREATE TABLE undo (
    token TEXT PRIMARY KEY,
    visit_id INTEGER NOT NULL,
    before_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

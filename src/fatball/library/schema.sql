CREATE TABLE camera (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    mac TEXT,
    last_ip TEXT,
    last_seen_at TEXT,
    last_error TEXT,
    clock_offset_s REAL
);

CREATE TABLE clip (
    id INTEGER PRIMARY KEY,
    camera_id INTEGER NOT NULL REFERENCES camera(id),
    sd_path TEXT NOT NULL,
    begin_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'downloading'
        CHECK (status IN ('downloading', 'downloaded', 'processing', 'ready', 'failed')),
    raw_path TEXT,
    original_path TEXT,
    web_path TEXT,
    poster_path TEXT,
    preview_path TEXT,
    duration_s REAL,
    size_bytes INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX clip_sd_path_begin ON clip(sd_path, begin_at);
CREATE INDEX clip_begin ON clip(begin_at);
CREATE INDEX clip_status ON clip(status);

CREATE TABLE species (
    id INTEGER PRIMARY KEY,
    scientific_name TEXT NOT NULL UNIQUE,
    "group" TEXT NOT NULL CHECK ("group" IN ('bird', 'mammal')),
    first_seen_at TEXT
);

CREATE TABLE species_name (
    species_id INTEGER NOT NULL REFERENCES species(id),
    lang TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (species_id, lang)
);

CREATE TABLE visit (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('birds', 'other_animals', 'other')),
    species_id INTEGER REFERENCES species(id),
    confidence REAL,
    best_clip_id INTEGER REFERENCES clip(id),
    best_frame_path TEXT,
    is_favourite INTEGER NOT NULL DEFAULT 0,
    moved_by_user INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE visit_clip (
    visit_id INTEGER NOT NULL REFERENCES visit(id),
    clip_id INTEGER NOT NULL REFERENCES clip(id),
    PRIMARY KEY (visit_id, clip_id)
);

CREATE TABLE guess (
    visit_id INTEGER NOT NULL REFERENCES visit(id),
    species_id INTEGER NOT NULL REFERENCES species(id),
    confidence REAL NOT NULL,
    rank INTEGER NOT NULL,
    PRIMARY KEY (visit_id, rank)
);

CREATE TABLE correction (
    id INTEGER PRIMARY KEY,
    visit_id INTEGER NOT NULL REFERENCES visit(id),
    from_species_id INTEGER REFERENCES species(id),
    to_species_id INTEGER REFERENCES species(id),
    from_category TEXT,
    to_category TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE setting (
    key TEXT PRIMARY KEY,
    value TEXT
);

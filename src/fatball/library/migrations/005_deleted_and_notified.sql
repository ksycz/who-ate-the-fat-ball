ALTER TABLE clip ADD COLUMN deleted_at TEXT;
ALTER TABLE visit ADD COLUMN notified_at TEXT;
UPDATE visit SET notified_at = started_at;

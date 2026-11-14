"""SQLite metadata responsibilities used by DedupStore.

The public storage API remains in ``storage.py``; this module documents the
relational model for contributors and provides the schema independently.
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mode INTEGER NOT NULL DEFAULT 420
);
CREATE TABLE IF NOT EXISTS file_chunks (
    path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    digest TEXT NOT NULL,
    PRIMARY KEY (path, position)
);
CREATE TABLE IF NOT EXISTS chunks (
    digest TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    ref_count INTEGER NOT NULL CHECK (ref_count > 0)
);
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    path TEXT,
    digest TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

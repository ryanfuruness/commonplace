"""SQLite schema and connection handling."""

from __future__ import annotations

import sqlite3
import threading

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS contributors (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    role        TEXT NOT NULL CHECK (role IN ('member', 'curator', 'admin')),
    token_hash  TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entries (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    summary       TEXT NOT NULL,
    task          TEXT NOT NULL,
    domain        TEXT,
    situation     TEXT,
    tags          TEXT NOT NULL DEFAULT '[]',
    body          TEXT NOT NULL,
    applies_when  TEXT,
    not_when      TEXT,
    tier          TEXT NOT NULL DEFAULT 'note' CHECK (tier IN ('note', 'pattern', 'canonical')),
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded', 'split', 'retired')),
    version       INTEGER NOT NULL DEFAULT 1,
    parents       TEXT NOT NULL DEFAULT '[]',
    successors    TEXT NOT NULL DEFAULT '[]',
    author        TEXT NOT NULL REFERENCES contributors(id),
    origin        TEXT NOT NULL DEFAULT '{}',
    approved_by       TEXT,
    approved_version  INTEGER,
    nominated_by      TEXT,
    nomination        TEXT,
    nominated_at      TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entry_versions (
    entry_id      TEXT NOT NULL REFERENCES entries(id),
    version       INTEGER NOT NULL,
    title         TEXT NOT NULL,
    summary       TEXT NOT NULL,
    body          TEXT NOT NULL,
    applies_when  TEXT,
    not_when      TEXT,
    change_note   TEXT NOT NULL,
    author        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (entry_id, version)
);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    id UNINDEXED, title, summary, task, domain, situation, tags, body, applies_when, not_when,
    tokenize = 'porter unicode61'
);

CREATE TABLE IF NOT EXISTS reports (
    id                   TEXT PRIMARY KEY,
    entry_id             TEXT NOT NULL REFERENCES entries(id),
    entry_version        INTEGER NOT NULL,
    reporter             TEXT NOT NULL REFERENCES contributors(id),
    task                 TEXT NOT NULL,
    domain               TEXT,
    situation            TEXT,
    outcome              TEXT NOT NULL CHECK (outcome IN ('success', 'partial', 'failure', 'not_applicable')),
    human_signal         TEXT NOT NULL CHECK (human_signal IN ('accepted', 'corrected', 'rejected', 'none')),
    what_helped          TEXT,
    what_changed         TEXT,
    suggested_amendment  TEXT,
    processed            INTEGER NOT NULL DEFAULT 0,
    stale                INTEGER NOT NULL DEFAULT 0,
    redacted             INTEGER NOT NULL DEFAULT 0,
    orig_entry_id        TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    updated_at           TEXT
);
CREATE INDEX IF NOT EXISTS reports_entry ON reports(entry_id);

CREATE TABLE IF NOT EXISTS questions (
    id          TEXT PRIMARY KEY,
    asker       TEXT NOT NULL REFERENCES contributors(id),
    question    TEXT NOT NULL,
    task        TEXT,
    domain      TEXT,
    situation   TEXT,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'closed')),
    demand      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS questions_fts USING fts5(
    id UNINDEXED, question, task, domain, situation,
    tokenize = 'porter unicode61'
);

CREATE TABLE IF NOT EXISTS answers (
    id           TEXT PRIMARY KEY,
    question_id  TEXT NOT NULL REFERENCES questions(id),
    answerer     TEXT NOT NULL REFERENCES contributors(id),
    body         TEXT NOT NULL,
    basis        TEXT NOT NULL CHECK (basis IN ('experience', 'reasoning')),
    entry_id     TEXT REFERENCES entries(id),
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS curation_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT NOT NULL,
    entry_ids   TEXT NOT NULL,
    rationale   TEXT NOT NULL,
    actor       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""

SCHEMA_VERSION = 1

# Columns added after the first tables were created. Databases created by an
# earlier build get them through ALTER TABLE; new databases get them from SCHEMA.
_ADDED_COLUMNS = {
    "entries": [
        ("approved_version", "INTEGER"),
        ("nominated_by", "TEXT"),
        ("nomination", "TEXT"),
        ("nominated_at", "TEXT"),
    ],
    "reports": [
        ("stale", "INTEGER NOT NULL DEFAULT 0"),
        ("redacted", "INTEGER NOT NULL DEFAULT 0"),
        ("orig_entry_id", "TEXT NOT NULL DEFAULT ''"),
        ("updated_at", "TEXT"),
    ],
}

_lock = threading.RLock()


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    for table, columns in _ADDED_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    conn.execute("UPDATE reports SET orig_entry_id = entry_id WHERE orig_entry_id = ''")
    conn.execute("UPDATE reports SET stale = 1 WHERE entry_version < "
                 "(SELECT version FROM entries WHERE entries.id = reports.entry_id)")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    with _lock:
        _migrate(conn)
    return conn


def write_lock() -> threading.RLock:
    """Serialize access to the shared connection. Tools run in worker threads so
    one slow request cannot stall the event loop; this lock keeps the single
    sqlite3 connection safe across those threads and multi-statement operations
    (split, merge) atomic."""
    return _lock

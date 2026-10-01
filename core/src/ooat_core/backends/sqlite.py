"""SQLite ledger backend (Solo profile)."""

import sqlite3
from pathlib import Path

from . import LedgerIntegrityError

# Spec §7 event table plus seq (portable append order) and the artifact table.
# task_id is nullable because ADAPTER_ACKNOWLEDGED has no task (ADR 0003).
_DDL = """
CREATE TABLE IF NOT EXISTS event (
  seq           INTEGER PRIMARY KEY AUTOINCREMENT,
  id            TEXT NOT NULL UNIQUE,
  ts            TEXT NOT NULL,
  task_id       TEXT,
  contract_id   TEXT,
  actor_kind    TEXT NOT NULL CHECK (actor_kind IN ('agent','hil','system')),
  actor_id      TEXT NOT NULL,
  role_ver      TEXT,
  type          TEXT NOT NULL,
  refs          TEXT NOT NULL DEFAULT '[]',
  lang          TEXT,
  body          TEXT NOT NULL,
  adapter       TEXT,
  tier          TEXT,
  tokens_in     INTEGER,
  tokens_cached INTEGER,
  tokens_out    INTEGER,
  quota_units   REAL,
  cost_usd      REAL,
  cost_basis    TEXT CHECK (cost_basis IN ('exact','estimated','shadow')),
  price_ver     TEXT
);
CREATE INDEX IF NOT EXISTS event_task_seq ON event (task_id, seq);
CREATE INDEX IF NOT EXISTS event_type_seq ON event (type, seq);
CREATE TABLE IF NOT EXISTS artifact (
  id                TEXT NOT NULL,
  version           INTEGER NOT NULL CHECK (version >= 1),
  type              TEXT NOT NULL,
  data_class        TEXT NOT NULL CHECK (data_class IN
                      ('public','internal','client_confidential','personal','special_category')),
  untrusted         INTEGER NOT NULL CHECK (untrusted IN (0, 1)),
  sha256            TEXT NOT NULL,
  uri               TEXT NOT NULL,
  produced_by_event TEXT NOT NULL REFERENCES event (id),
  PRIMARY KEY (id, version)
);
-- INSERT OR REPLACE deletes the old row without firing delete triggers, so inserts over an existing key abort too.
CREATE TRIGGER IF NOT EXISTS event_no_replace BEFORE INSERT ON event
  WHEN EXISTS (SELECT 1 FROM event WHERE id = NEW.id)
  BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS artifact_no_replace BEFORE INSERT ON artifact
  WHEN EXISTS (SELECT 1 FROM artifact WHERE id = NEW.id AND version = NEW.version)
  BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_no_update BEFORE UPDATE ON event
  BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_no_delete BEFORE DELETE ON event
  BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS artifact_no_update BEFORE UPDATE ON artifact
  BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS artifact_no_delete BEFORE DELETE ON artifact
  BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
"""


class SqliteBackend:
    def __init__(self, path: str | Path):
        self._db = sqlite3.connect(str(path))
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_DDL)

    def insert(self, event_row: dict, artifact_rows: list[dict]) -> None:
        try:
            with self._db:  # commits on success, rolls back on any error
                self._insert("event", event_row)
                for row in artifact_rows:
                    self._insert("artifact", row)
        except sqlite3.IntegrityError as error:
            raise LedgerIntegrityError(str(error)) from error

    def _insert(self, table: str, row: dict) -> None:
        columns = ",".join(row)
        self._db.execute(f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))

    def select_events(self, task: str | None, types: list[str]) -> list[dict]:
        where, args = [], []
        if task is not None:
            where.append("task_id = ?")
            args.append(task)
        if types:
            where.append(f"type IN ({','.join('?' * len(types))})")
            args.extend(types)
        sql = "SELECT * FROM event" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY seq"
        return [dict(row) for row in self._db.execute(sql, args)]

    def select_artifact(self, artifact_id: str, version: int) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM artifact WHERE id = ? AND version = ?", (artifact_id, version)
        ).fetchone()
        return dict(row) if row else None

    def max_artifact_version(self, artifact_id: str) -> int:
        (current,) = self._db.execute(
            "SELECT COALESCE(MAX(version), 0) FROM artifact WHERE id = ?", (artifact_id,)
        ).fetchone()
        return current

    def close(self) -> None:
        self._db.close()

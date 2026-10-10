"""SQLite ledger backend (Solo profile).

One connection per thread (`check_same_thread` stays on). WAL lets readers run while one writer appends; every
write is one `BEGIN IMMEDIATE` transaction, so the ledger's checks and its insert are serialised across threads and
processes (design 05 §7). WAL needs a local disk: it does not work on network shares.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path

from . import LedgerBusyError, LedgerIntegrityError

BUSY_TIMEOUT_MS = 5000  # a writer waits this long for the lock, then the write fails as LedgerBusyError
_BUSY = frozenset({"SQLITE_BUSY", "SQLITE_LOCKED"})

# Bumped with every DDL change; a ledger written by newer code is never opened by older code.
SCHEMA_VERSION = 2

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
  price_ver     TEXT,
  estimated_usd REAL
);
CREATE INDEX IF NOT EXISTS event_task_seq ON event (task_id, seq);
CREATE INDEX IF NOT EXISTS event_type_seq ON event (type, seq);
-- One answer per HIL request, also when two processes pass Ledger's check at the same time (spec §9).
CREATE UNIQUE INDEX IF NOT EXISTS event_one_response ON event (json_extract(body, '$.request'))
  WHERE type = 'HIL_RESPONSE';
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
-- INSERT OR REPLACE deletes the old row without firing delete triggers, so inserts over an existing key
-- (id or seq) abort too.
CREATE TRIGGER IF NOT EXISTS event_no_replace BEFORE INSERT ON event
  WHEN EXISTS (SELECT 1 FROM event WHERE id = NEW.id OR seq = NEW.seq)
  BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS artifact_no_replace BEFORE INSERT ON artifact
  WHEN EXISTS (SELECT 1 FROM artifact WHERE id = NEW.id AND version = NEW.version)
  BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
-- Provenance holds even on connections that did not enable foreign keys.
CREATE TRIGGER IF NOT EXISTS artifact_needs_event BEFORE INSERT ON artifact
  WHEN NOT EXISTS (SELECT 1 FROM event WHERE id = NEW.produced_by_event)
  BEGIN SELECT RAISE(ABORT, 'artifact needs its producing event'); END;
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
        # No implicit transactions: transaction() opens BEGIN IMMEDIATE itself.
        self._db = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._in_transaction = False
        try:
            self._prepare()
        except sqlite3.OperationalError as error:  # another writer held the file past the busy timeout
            self._db.close()
            if error.sqlite_errorname in _BUSY:
                raise LedgerBusyError("the ledger is busy; try again") from error
            raise

    def _prepare(self) -> None:
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")  # persistent in the file; ":memory:" stays "memory"
        (version,) = self._db.execute("PRAGMA user_version").fetchone()
        if version > SCHEMA_VERSION:
            self._db.close()
            raise ValueError(f"ledger schema version {version} is newer than this code ({SCHEMA_VERSION})")
        self._db.executescript(_DDL)
        # Version 2 records the gateway's estimate (ADR 0010). Check the column, not the number, so a crash
        # between ALTER and the version stamp, or a file from before versioning, still migrates cleanly.
        columns = [row[1] for row in self._db.execute("PRAGMA table_info(event)")]
        if "estimated_usd" not in columns:
            self._db.execute("ALTER TABLE event ADD COLUMN estimated_usd REAL")
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._in_transaction:
            raise RuntimeError("ledger transactions do not nest")
        try:
            self._db.execute("BEGIN IMMEDIATE")  # takes the write lock now, waiting up to the busy timeout
        except sqlite3.OperationalError as error:
            if error.sqlite_errorname in _BUSY:
                raise LedgerBusyError("the ledger is busy; try again") from error
            raise
        self._in_transaction = True
        try:
            yield
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        finally:
            self._in_transaction = False

    def insert(self, event_row: dict, artifact_rows: list[dict]) -> None:
        with nullcontext() if self._in_transaction else self.transaction():
            try:
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

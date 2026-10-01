# Core Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation of `ooat-core`: identifiers, spec validation, an append-only ledger with pluggable backends (SQLite first), content-addressed artifact storage and task/contract state derived from events.

**Architecture:** `Ledger` owns the spec rules (validate every event against `spec/schemas/event.schema.json`, write an event and the artifacts it produces atomically, map envelopes to rows) and delegates SQL to a `LedgerBackend` chosen by URL (ADR 0008). Artifact bodies live in a SHA-256 addressed `BlobStore`; an artifact becomes visible only when its producing event is appended. Task and contract state are pure functions over events.

**Tech Stack:** Python 3.12+, `jsonschema`, `referencing`, `sqlite3` (stdlib), pytest, hatchling.

**Spec:** `spec/ooat-specification.md` §2 (entities, outcomes), §3 (non-functional requirements), §7 (event envelope, ledger schema), §8 (task lifecycle); `spec/schemas/`; ADR 0003 and ADR 0008. Task definition: `task.md` next to this plan.

## Global Constraints

- Python `>=3.12`; runtime dependencies only `jsonschema>=4.23`, `referencing>=0.30` and `rfc3339-validator>=0.1.4`.
- Identifiers `tsk_`, `ctr_`, `agt_`, `evt_`, `art_` + 26-character ULID; artifact references `art_<ulid>@v<n>` (ADR 0003).
- Timestamps ISO 8601 UTC ending in `Z`.
- Ledger is append-only: no UPDATE, DELETE or INSERT OR REPLACE of events or artifact records, enforced in the database.
- The ledger does not authenticate actors: HIL identity is verified at intake/notifier (sub-projects 04/05), which are the only paths allowed to append `kind: hil` events.
- Only `ooat-core` writes the ledger; every event is validated against the OOA Spec before it is written.
- Code, comments, docs and commit messages in English; free-text test data may be Czech.
- No secrets in code, tests or fixtures.

## Review Focus

1. An event that fails the schema must leave the ledger unchanged and report every violation — `test_invalid_event_is_rejected_and_not_written` (Task 3), `test_every_violation_is_reported` (Task 2).
2. A failure while writing an event with artifacts must not leave half of it behind, and a duplicate key must not silently replace a row — `test_event_and_artifacts_are_written_atomically`, `test_artifact_needs_an_existing_event`, the `INSERT OR REPLACE` cases of `test_rows_cannot_be_changed_or_deleted` (Task 3).
3. A restarted runtime must see the same events in the same order — `test_reopened_ledger_keeps_events_in_order` (Task 3).
4. A blob changed on disk or a crafted digest must not be served — `test_tampered_blob_is_detected`, `test_path_traversal_digest_is_rejected` (Task 4).
5. An artifact must not be readable before the event that produces it exists — `test_artifact_is_readable_only_after_its_event` (Task 4).

---

## File Structure

```
core/
  pyproject.toml                  package ooat-core
  description.md                  As-is overview of the package (Task 5)
  src/ooat_core/
    __init__.py
    ids.py                        ULID ids, artifact reference parsing
    validation.py                 OOA Spec schema validation
    ledger.py                     Ledger: spec rules, envelope <-> row mapping, new_event()
    backends/__init__.py          LedgerBackend protocol, open_backend(url)
    backends/sqlite.py            SQLite dialect, DDL, append-only triggers
    blobs.py                      SHA-256 addressed file storage
    artifacts.py                  ArtifactStore: stage and read artifacts
    state.py                      task_state(), contract_state()
  tests/
    test_ids.py  test_validation.py  test_ledger.py  test_sqlite_backend.py  test_artifacts.py  test_state.py
pytest.ini                        add core/tests
.github/workflows/tests.yml       install core before pytest
```

Test file names are unique across the repository because pytest runs `spec/tests`, `catalog/tests` and `core/tests` in one session without packages.

---

### Task 1: Package skeleton and identifiers

**Files:**
- Create: `core/pyproject.toml`, `core/description.md`, `core/src/ooat_core/__init__.py`, `core/src/ooat_core/ids.py`
- Test: `core/tests/test_ids.py`
- Modify: `pytest.ini`, `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: `ulid(timestamp_ms: int | None = None) -> str`, `new_id(prefix: str) -> str` (prefixes `tsk ctr agt evt art`), `parse_artifact_ref(ref: str) -> tuple[str, int]`, constant `PREFIXES`.

- [ ] **Step 1: Create the package files**

`core/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "ooat-core"
version = "0.1.0.dev0"
description = "OOAT reference runtime: ledger, contracts and Topology Gate."
readme = "description.md"
requires-python = ">=3.12"
license = "Apache-2.0"
dependencies = ["jsonschema>=4.23", "referencing>=0.30", "rfc3339-validator>=0.1.4"]

[tool.hatch.build.targets.wheel]
packages = ["src/ooat_core"]
```

`core/description.md` (placeholder, completed in Task 5):

```markdown
# ooat-core

Reference runtime of OOAT. See Task 5 of the core ledger plan.
```

`core/src/ooat_core/__init__.py`:

```python
"""OOAT reference runtime (ooat-core)."""
```

Replace `pytest.ini` with:

```ini
[pytest]
testpaths = spec/tests catalog/tests core/tests
```

In `.github/workflows/tests.yml`, after the `pip install -r requirements-dev.txt` step add:

```yaml
      - run: python -m pip install -e core
```

Install locally: `python -m pip install -e core`

- [ ] **Step 2: Write the failing test** — `core/tests/test_ids.py`:

```python
import re

import pytest

from ooat_core.ids import new_id, parse_artifact_ref, ulid

ULID = r"[0-7][0-9A-HJKMNP-TV-Z]{25}"


@pytest.mark.parametrize("prefix", ["tsk", "ctr", "agt", "evt", "art"])
def test_new_id_matches_spec_pattern(prefix):
    assert re.fullmatch(f"{prefix}_{ULID}", new_id(prefix))


def test_new_ids_are_unique():
    assert len({new_id("evt") for _ in range(1000)}) == 1000


def test_ulid_sorts_by_time():
    assert ulid(1_000) < ulid(2_000) < ulid(2**48 - 1)
    assert ulid(0).startswith("0000000000")


def test_unknown_prefix_is_rejected():
    with pytest.raises(ValueError):
        new_id("usr")


def test_parse_artifact_ref():
    art = new_id("art")
    assert parse_artifact_ref(f"{art}@v12") == (art, 12)
    for bad in (art, f"{art}@v0", "art_short@v1"):
        with pytest.raises(ValueError):
            parse_artifact_ref(bad)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest core/tests/test_ids.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.ids'`

- [ ] **Step 4: Implement** — `core/src/ooat_core/ids.py`:

```python
"""Identifiers <prefix>_<ULID> (spec §2).

ULIDs start with a millisecond timestamp, so identifiers sort by creation time across installations.
"""

import os
import re
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIXES = frozenset({"tsk", "ctr", "agt", "evt", "art"})
_ARTIFACT_REF = re.compile(r"^(art_[0-7][0-9A-HJKMNP-TV-Z]{25})@v([1-9][0-9]*)$")


def ulid(timestamp_ms: int | None = None) -> str:
    """26-character Crockford base32 ULID: 48-bit millisecond timestamp + 80 random bits."""
    ms = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    value = (ms << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix: {prefix}")
    return f"{prefix}_{ulid()}"


def parse_artifact_ref(ref: str) -> tuple[str, int]:
    """Split art_<ulid>@v<n> into (artifact id, version)."""
    match = _ARTIFACT_REF.match(ref)
    if match is None:
        raise ValueError(f"not an artifact reference: {ref}")
    return match.group(1), int(match.group(2))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest -q`
Expected: all tests pass (schema, catalog and the 9 new id tests).

- [ ] **Step 6: Commit**

```bash
git add core/pyproject.toml core/description.md core/src/ooat_core/__init__.py core/src/ooat_core/ids.py core/tests/test_ids.py pytest.ini .github/workflows/tests.yml
git commit -m "core: package skeleton and ULID identifiers"
```

---

### Task 2: Spec validation

**Files:**
- Create: `core/src/ooat_core/validation.py`
- Test: `core/tests/test_validation.py`

**Interfaces:**
- Consumes: `spec/schemas/*.schema.json` (repository checkout layout).
- Produces: `validate(entity: str, document: dict) -> None`; `SpecValidationError(ValueError)` with `.entity: str` and `.messages: list[str]`; `KeyError` for an unknown entity.

- [ ] **Step 1: Write the failing test** — `core/tests/test_validation.py`:

```python
import json
from pathlib import Path

import pytest

from ooat_core.validation import SpecValidationError, validate

EXAMPLES = Path(__file__).resolve().parents[2] / "spec" / "examples" / "valid"


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_valid_documents_pass():
    validate("event", load("event.abstain.json"))
    validate("capability", load("capability.design_semantic_model.json"))


def test_every_violation_is_reported():
    event = load("event.abstain.json")
    del event["body"]["missing"]
    event["body"]["confidence"] = 2
    with pytest.raises(SpecValidationError) as info:
        validate("event", event)
    text = " ".join(info.value.messages)
    assert "missing" in text and "confidence" in text
    assert info.value.entity == "event"


def test_unknown_schema_is_an_error():
    with pytest.raises(KeyError):
        validate("nonsense", {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.validation'`

- [ ] **Step 3: Implement** — `core/src/ooat_core/validation.py`:

```python
"""Validation against the OOA Spec JSON Schemas in spec/schemas."""

import json
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

# F1 runs from a repository checkout; shipping the schemas inside the wheel is part of the release work.
SCHEMA_DIR = Path(__file__).resolve().parents[3] / "spec" / "schemas"


class SpecValidationError(ValueError):
    """A document does not match its OOA Spec schema. `messages` lists every violation."""

    def __init__(self, entity: str, messages: list[str]):
        super().__init__(f"{entity}: " + "; ".join(messages))
        self.entity = entity
        self.messages = messages


@cache
def _validators() -> dict[str, Draft202012Validator]:
    schemas = {
        path.name.removesuffix(".schema.json"): json.loads(path.read_text(encoding="utf-8"))
        for path in SCHEMA_DIR.glob("*.schema.json")
    }
    if not schemas:
        raise FileNotFoundError(f"no OOA Spec schemas in {SCHEMA_DIR}")
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas.values())
    return {
        name: Draft202012Validator(schema, registry=registry, format_checker=Draft202012Validator.FORMAT_CHECKER)
        for name, schema in schemas.items()
    }


def validate(entity: str, document: dict) -> None:
    """Raise SpecValidationError unless `document` matches spec/schemas/<entity>.schema.json."""
    validator = _validators().get(entity)
    if validator is None:
        raise KeyError(f"unknown OOA Spec schema: {entity}")
    errors = sorted(validator.iter_errors(document), key=lambda e: e.json_path)
    if errors:
        raise SpecValidationError(entity, [f"{e.json_path}: {e.message}" for e in errors])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/validation.py core/tests/test_validation.py
git commit -m "core: validate documents against the OOA Spec schemas"
```

---

### Task 3: Ledger with SQLite backend

**Files:**
- Create: `core/src/ooat_core/backends/__init__.py`, `core/src/ooat_core/backends/sqlite.py`, `core/src/ooat_core/ledger.py`
- Test: `core/tests/test_sqlite_backend.py`, `core/tests/test_ledger.py`

**Interfaces:**
- Consumes: `validate` (Task 2); `new_id`, `parse_artifact_ref` (Task 1).
- Produces:
  - `LedgerIntegrityError(Exception)` — raised by every backend's `insert` on a duplicate key or an artifact without its event; nothing is written.
  - `LedgerBackend` protocol: `insert(event_row: dict, artifact_rows: list[dict]) -> None`, `select_events(task: str | None, types: list[str]) -> list[dict]`, `select_artifact(artifact_id: str, version: int) -> dict | None`, `max_artifact_version(artifact_id: str) -> int`, `close() -> None`.
  - `open_backend(url: str) -> LedgerBackend` — `sqlite:///<path>`; `postgresql://` and `mssql://` raise `NotImplementedError`; anything else `ValueError`.
  - `SqliteBackend(path)`.
  - `Ledger(backend)`, `Ledger.open(url) -> Ledger`, `.append(event: dict, artifacts: Iterable[StagedArtifact] = ()) -> dict`, `.events(task: str | None = None, types: Iterable[str] = ()) -> list[dict]`, `.artifact(ref: str) -> dict | None` (keys `id version type data_class untrusted sha256 uri produced_by_event`, `untrusted` as bool), `.next_artifact_version(artifact_id: str) -> int`, `.close()`, attribute `.backend`.
  - `StagedArtifact(ref, type, data_class, untrusted, sha256, uri)` frozen dataclass.
  - `new_event(event_type, *, task, actor, body, refs=(), contract=None, lang=None, cost=None) -> dict`; `utc_now() -> str`.

- [ ] **Step 1: Write the failing backend test** — `core/tests/test_sqlite_backend.py`:

```python
import sqlite3

import pytest

from ooat_core.backends import LedgerIntegrityError
from ooat_core.backends.sqlite import SqliteBackend

EVENT = {"id": "evt_1", "ts": "2026-10-01T00:00:00Z", "task_id": "tsk_1", "actor_kind": "hil",
         "actor_id": "operator", "type": "TASK_SUBMITTED", "refs": "[]", "body": "{}"}
ARTIFACT = {"id": "art_1", "version": 1, "type": "summary", "data_class": "internal", "untrusted": 0,
            "sha256": "0" * 64, "uri": "blob:x", "produced_by_event": "evt_1"}


@pytest.fixture
def backend():
    b = SqliteBackend(":memory:")
    b.insert(EVENT, [ARTIFACT])
    yield b
    b.close()


@pytest.mark.parametrize("sql", [
    "UPDATE event SET type = 'CLAIM'",
    "DELETE FROM event",
    "UPDATE artifact SET data_class = 'public'",
    "DELETE FROM artifact",
    "INSERT OR REPLACE INTO event (id, ts, actor_kind, actor_id, type, body)"
    " VALUES ('evt_1', '2026-10-01T00:00:00Z', 'hil', 'x', 'CLAIM', '{}')",
    "INSERT OR REPLACE INTO artifact VALUES ('art_1', 1, 'summary', 'public', 0, 'x', 'blob:x', 'evt_1')",
])
def test_rows_cannot_be_changed_or_deleted(backend, sql):
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        backend._db.execute(sql)


def test_artifact_needs_an_existing_event(backend):
    orphan = {**ARTIFACT, "id": "art_2", "produced_by_event": "evt_missing"}
    with pytest.raises(LedgerIntegrityError):
        backend.insert({**EVENT, "id": "evt_2"}, [orphan])
    assert [row["id"] for row in backend.select_events(None, [])] == ["evt_1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_sqlite_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.backends'`

- [ ] **Step 3: Implement the backend** — `core/src/ooat_core/backends/__init__.py`:

```python
"""Storage backends for the ledger. A backend knows its database dialect; Ledger knows the spec.

Every backend implements the same small surface and must pass core/tests/test_ledger.py.
"""

from typing import Protocol


class LedgerIntegrityError(Exception):
    """A write would duplicate or orphan a ledger row. Backends translate their driver's integrity errors."""


class LedgerBackend(Protocol):
    def insert(self, event_row: dict, artifact_rows: list[dict]) -> None:
        """Insert one event row and its artifact rows in a single transaction.

        Raises LedgerIntegrityError, writing nothing, on a duplicate id or an artifact without its event.
        """

    def select_events(self, task: str | None, types: list[str]) -> list[dict]:
        """Event rows in append order (ascending seq), optionally filtered."""

    def select_artifact(self, artifact_id: str, version: int) -> dict | None: ...

    def max_artifact_version(self, artifact_id: str) -> int:
        """Highest stored version of an artifact, 0 if none."""

    def close(self) -> None: ...


def open_backend(url: str) -> LedgerBackend:
    """sqlite:///<path> or sqlite:///:memory:. PostgreSQL and SQL Server are planned (ADR 0008)."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        raise ValueError(f"not a ledger URL: {url}")
    if scheme == "sqlite":
        from .sqlite import SqliteBackend

        return SqliteBackend(rest.removeprefix("/"))
    if scheme in ("postgresql", "mssql"):
        raise NotImplementedError(f"the {scheme} ledger backend is not implemented yet (ADR 0008)")
    raise ValueError(f"unknown ledger backend: {scheme}")
```

`core/src/ooat_core/backends/sqlite.py`:

```python
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
```

- [ ] **Step 4: Run backend tests to verify they pass**

Run: `python -m pytest core/tests/test_sqlite_backend.py -v`
Expected: 7 passed

- [ ] **Step 5: Write the failing ledger test** — `core/tests/test_ledger.py`:

```python
import pytest

from ooat_core.backends import LedgerIntegrityError
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger, StagedArtifact, new_event
from ooat_core.validation import SpecValidationError

HIL = {"kind": "hil", "id": "operator"}


# Every ledger backend must pass this module. PostgreSQL and SQL Server URLs join this list (ADR 0008).
BACKEND_URLS = ["sqlite:///:memory:"]


@pytest.fixture(params=BACKEND_URLS)
def ledger(request):
    led = Ledger.open(request.param)
    yield led
    led.close()


def submitted(task):
    return new_event("TASK_SUBMITTED", task=task, actor=HIL, body={"goal": "Shrnout výroční zprávu."}, lang="cs")


def result(task, contract, refs):
    return new_event(
        "RESULT", task=task, contract=contract,
        actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
        body={"outcome": "DONE", "artifacts": list(refs)}, refs=refs,
        cost={"adapter": "prv.anthropic.subscription_cli", "tier": "workhorse", "quota_units": 1200,
              "usd": 0.05, "basis": "shadow"},
    )


def staged(ref):
    return StagedArtifact(ref=ref, type="summary", data_class="internal", untrusted=False,
                          sha256="0" * 64, uri="blob:" + "0" * 64)


def test_events_round_trip_in_append_order(ledger):
    task, ref = new_id("tsk"), new_id("art") + "@v1"
    appended = [ledger.append(submitted(task)), ledger.append(result(task, new_id("ctr"), [ref]), [staged(ref)])]
    ledger.append(submitted(new_id("tsk")))  # another task
    assert ledger.events(task=task) == appended
    assert ledger.events(types=["RESULT"]) == appended[1:]


def test_invalid_event_is_rejected_and_not_written(ledger):
    bad = submitted(new_id("tsk"))
    del bad["body"]["goal"]
    with pytest.raises(SpecValidationError, match="goal"):
        ledger.append(bad)
    assert ledger.events() == []


def test_artifact_is_recorded_with_its_event(ledger):
    ref = new_id("art") + "@v1"
    event = ledger.append(result(new_id("tsk"), new_id("ctr"), [ref]), [staged(ref)])
    record = ledger.artifact(ref)
    assert record["produced_by_event"] == event["id"]
    assert (record["version"], record["untrusted"], record["data_class"]) == (1, False, "internal")
    assert ledger.next_artifact_version(ref.split("@")[0]) == 2


def test_staged_artifact_must_be_referenced_by_its_event(ledger):
    ref, other = new_id("art") + "@v1", new_id("art") + "@v1"
    with pytest.raises(ValueError, match="referenced"):
        ledger.append(result(new_id("tsk"), new_id("ctr"), [other]), [staged(ref)])
    assert ledger.events() == []


def test_event_and_artifacts_are_written_atomically(ledger):
    task, contract, ref = new_id("tsk"), new_id("ctr"), new_id("art") + "@v1"
    first = ledger.append(result(task, contract, [ref]), [staged(ref)])
    with pytest.raises(LedgerIntegrityError):  # the same artifact version again
        ledger.append(result(task, contract, [ref]), [staged(ref)])
    assert [e["id"] for e in ledger.events()] == [first["id"]]


def test_reopened_ledger_keeps_events_in_order(tmp_path):
    path, task = tmp_path / "ledger.sqlite", new_id("tsk")
    led = Ledger.open(f"sqlite:///{path}")
    appended = [led.append(submitted(task)) for _ in range(3)]
    led.close()
    led = Ledger.open(f"sqlite:///{path}")
    assert led.events(task=task) == appended
    led.close()


def test_unknown_or_planned_backends():
    with pytest.raises(ValueError):
        Ledger.open("oracle://db")
    with pytest.raises(ValueError):
        Ledger.open("ledger.sqlite")
    for url in ("postgresql://host/ooat", "mssql://host/ooat"):
        with pytest.raises(NotImplementedError):
            Ledger.open(url)
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest core/tests/test_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.ledger'`

- [ ] **Step 7: Implement** — `core/src/ooat_core/ledger.py`:

```python
"""Append-only ledger of events and artifact records (spec §7).

This is the single write path of OOAT: agents and the orchestrator only propose events; ooat-core appends them.
Ledger owns the spec rules (validation, provenance, atomicity); the backend owns the database dialect.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from .backends import LedgerBackend, open_backend
from .ids import new_id, parse_artifact_ref
from .validation import validate

# The envelope's cost keys differ from the spec's column names for usd and basis.
_COST_COLUMNS = {
    "adapter": "adapter", "tier": "tier", "tokens_in": "tokens_in", "tokens_cached": "tokens_cached",
    "tokens_out": "tokens_out", "quota_units": "quota_units", "usd": "cost_usd", "basis": "cost_basis",
    "price_ver": "price_ver",
}


@dataclass(frozen=True)
class StagedArtifact:
    """An artifact body already in blob storage, waiting for the event that produces it."""

    ref: str
    type: str
    data_class: str
    untrusted: bool
    sha256: str
    uri: str


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_event(
    event_type: str,
    *,
    task: str | None,
    actor: dict,
    body: dict,
    refs: Iterable[str] = (),
    contract: str | None = None,
    lang: str | None = None,
    cost: dict | None = None,
) -> dict:
    """Build an event envelope with a fresh id and timestamp. Optional keys that are None are omitted."""
    event = {"id": new_id("evt"), "ts": utc_now(), "task": task, "actor": actor, "type": event_type,
             "refs": list(refs), "body": body}
    for key, value in (("contract", contract), ("lang", lang), ("cost", cost)):
        if value is not None:
            event[key] = value
    return event


def _event_row(event: dict) -> dict:
    actor, cost = event["actor"], event.get("cost", {})
    return {
        "id": event["id"], "ts": event["ts"], "task_id": event["task"], "contract_id": event.get("contract"),
        "actor_kind": actor["kind"], "actor_id": actor["id"], "role_ver": actor.get("role"),
        "type": event["type"], "refs": json.dumps(event["refs"]), "lang": event.get("lang"),
        "body": json.dumps(event["body"], ensure_ascii=False),
        **{column: cost.get(key) for key, column in _COST_COLUMNS.items()},
    }


def _row_event(row: dict) -> dict:
    event = {
        "id": row["id"], "ts": row["ts"], "task": row["task_id"],
        "actor": {"kind": row["actor_kind"], "id": row["actor_id"]},
        "type": row["type"], "refs": json.loads(row["refs"]), "body": json.loads(row["body"]),
    }
    if row["role_ver"] is not None:
        event["actor"]["role"] = row["role_ver"]
    if row["contract_id"] is not None:
        event["contract"] = row["contract_id"]
    if row["lang"] is not None:
        event["lang"] = row["lang"]
    cost = {key: row[column] for key, column in _COST_COLUMNS.items() if row[column] is not None}
    if cost:
        event["cost"] = cost
    return event


class Ledger:
    def __init__(self, backend: LedgerBackend):
        self.backend = backend

    @classmethod
    def open(cls, url: str) -> "Ledger":
        """Open a ledger by URL, e.g. sqlite:///ledger.sqlite or sqlite:///:memory:."""
        return cls(open_backend(url))

    def close(self) -> None:
        self.backend.close()

    def append(self, event: dict, artifacts: Iterable[StagedArtifact] = ()) -> dict:
        """Validate and append one event together with the artifacts it produces, atomically.

        Raises SpecValidationError without writing anything if the event does not match the spec.
        """
        validate("event", event)
        artifacts = list(artifacts)
        unreferenced = [a.ref for a in artifacts if a.ref not in event["refs"]]
        if unreferenced:
            raise ValueError(f"staged artifacts must be referenced by their event: {unreferenced}")
        artifact_rows = []
        for artifact in artifacts:
            artifact_id, version = parse_artifact_ref(artifact.ref)
            artifact_rows.append({
                "id": artifact_id, "version": version, "type": artifact.type, "data_class": artifact.data_class,
                "untrusted": int(artifact.untrusted), "sha256": artifact.sha256, "uri": artifact.uri,
                "produced_by_event": event["id"],
            })
        self.backend.insert(_event_row(event), artifact_rows)
        return event

    def events(self, task: str | None = None, types: Iterable[str] = ()) -> list[dict]:
        """Events in append order, optionally filtered by task and event types."""
        return [_row_event(row) for row in self.backend.select_events(task, list(types))]

    def artifact(self, ref: str) -> dict | None:
        """The artifact record for art_<ulid>@v<n>, or None if no appended event produced it."""
        record = self.backend.select_artifact(*parse_artifact_ref(ref))
        if record is not None:
            record["untrusted"] = bool(record["untrusted"])
        return record

    def next_artifact_version(self, artifact_id: str) -> int:
        return self.backend.max_artifact_version(artifact_id) + 1
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest core/tests -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add core/src/ooat_core/backends core/src/ooat_core/ledger.py core/tests/test_sqlite_backend.py core/tests/test_ledger.py
git commit -m "core: append-only ledger with pluggable backends, SQLite first"
```

---

### Task 4: Blob and artifact storage

**Files:**
- Create: `core/src/ooat_core/blobs.py`, `core/src/ooat_core/artifacts.py`
- Test: `core/tests/test_artifacts.py`

**Interfaces:**
- Consumes: `Ledger`, `StagedArtifact`, `new_event` (Task 3); `new_id` (Task 1).
- Produces: `BlobStore(root)` with `.put(content: bytes) -> str` (hex digest) and `.get(digest: str) -> bytes` (`ValueError` on tampering or a malformed digest); `ArtifactStore(ledger, blobs)` with `.stage(content: bytes, *, artifact_type: str, data_class: str, untrusted: bool = False, artifact_id: str | None = None) -> StagedArtifact` and `.read(ref: str) -> bytes` (`KeyError` until the producing event is appended); constant `DATA_CLASSES`.

- [ ] **Step 1: Write the failing test** — `core/tests/test_artifacts.py`:

```python
import pytest

from ooat_core.artifacts import ArtifactStore
from ooat_core.blobs import BlobStore
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger, new_event


@pytest.fixture
def ledger():
    led = Ledger.open("sqlite:///:memory:")
    yield led
    led.close()


@pytest.fixture
def store(ledger, tmp_path):
    return ArtifactStore(ledger, BlobStore(tmp_path / "blobs"))


def result(ref):
    return new_event(
        "RESULT", task=new_id("tsk"), contract=new_id("ctr"),
        actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
        body={"outcome": "DONE", "artifacts": [ref]}, refs=[ref],
    )


def test_artifact_is_readable_only_after_its_event(ledger, store):
    staged = store.stage("Shrnutí zprávy".encode(), artifact_type="summary", data_class="internal")
    with pytest.raises(KeyError):
        store.read(staged.ref)
    ledger.append(result(staged.ref), [staged])
    assert store.read(staged.ref).decode() == "Shrnutí zprávy"


def test_next_version_of_an_existing_artifact(ledger, store):
    first = store.stage(b"v1", artifact_type="summary", data_class="public")
    ledger.append(result(first.ref), [first])
    artifact_id = first.ref.split("@")[0]
    second = store.stage(b"v2", artifact_type="summary", data_class="public", artifact_id=artifact_id)
    assert second.ref == f"{artifact_id}@v2"


def test_unknown_data_class_is_rejected(store):
    with pytest.raises(ValueError, match="data class"):
        store.stage(b"x", artifact_type="summary", data_class="secret")


def test_identical_content_is_stored_once(tmp_path):
    blobs = BlobStore(tmp_path)
    assert blobs.put(b"same") == blobs.put(b"same")
    assert len([p for p in tmp_path.rglob("*") if p.is_file()]) == 1


def test_tampered_blob_is_detected(tmp_path):
    blobs = BlobStore(tmp_path)
    digest = blobs.put(b"original")
    (tmp_path / digest[:2] / digest).write_bytes(b"changed")
    with pytest.raises(ValueError, match="digest"):
        blobs.get(digest)


def test_path_traversal_digest_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        BlobStore(tmp_path).get("../" + "a" * 61)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_artifacts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.artifacts'`

- [ ] **Step 3: Implement** — `core/src/ooat_core/blobs.py`:

```python
"""Content-addressed storage of artifact bodies on the local filesystem (Solo profile)."""

import hashlib
from pathlib import Path

_HEX = frozenset("0123456789abcdef")


class BlobStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def put(self, content: bytes) -> str:
        """Store content once and return its SHA-256 hex digest."""
        digest = hashlib.sha256(content).hexdigest()
        path = self._path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_suffix(".partial")
            partial.write_bytes(content)
            partial.replace(path)  # readers never see a half-written blob
        return digest

    def get(self, digest: str) -> bytes:
        content = self._path(digest).read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError(f"blob {digest} does not match its digest")
        return content

    def _path(self, digest: str) -> Path:
        if len(digest) != 64 or not set(digest) <= _HEX:
            raise ValueError(f"not a SHA-256 hex digest: {digest}")
        return self.root / digest[:2] / digest
```

`core/src/ooat_core/artifacts.py`:

```python
"""Artifact staging and reading.

A staged artifact becomes visible only when the event that produces it is appended to the ledger,
so no artifact exists without provenance (spec §2).
"""

from .blobs import BlobStore
from .ids import new_id
from .ledger import Ledger, StagedArtifact

DATA_CLASSES = frozenset({"public", "internal", "client_confidential", "personal", "special_category"})


class ArtifactStore:
    def __init__(self, ledger: Ledger, blobs: BlobStore):
        self._ledger = ledger
        self._blobs = blobs

    def stage(
        self,
        content: bytes,
        *,
        artifact_type: str,
        data_class: str,
        untrusted: bool = False,
        artifact_id: str | None = None,
    ) -> StagedArtifact:
        """Store the body and return the staged record; pass artifact_id to create its next version."""
        if data_class not in DATA_CLASSES:
            raise ValueError(f"unknown data class: {data_class}")
        artifact_id = artifact_id or new_id("art")
        version = self._ledger.next_artifact_version(artifact_id)
        digest = self._blobs.put(content)
        return StagedArtifact(ref=f"{artifact_id}@v{version}", type=artifact_type, data_class=data_class,
                              untrusted=untrusted, sha256=digest, uri=f"blob:{digest}")

    def read(self, ref: str) -> bytes:
        record = self._ledger.artifact(ref)
        if record is None:
            raise KeyError(f"no appended event produced {ref}")
        return self._blobs.get(record["sha256"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/blobs.py core/src/ooat_core/artifacts.py core/tests/test_artifacts.py
git commit -m "core: content-addressed artifact storage with provenance"
```

---

### Task 5: State projections and documentation

**Files:**
- Create: `core/src/ooat_core/state.py`
- Test: `core/tests/test_state.py`
- Modify: `core/description.md`, `docs/description.md`, `tasks/f1-skeleton/task-01-core-ledger/task.md`

**Interfaces:**
- Consumes: event dicts as returned by `Ledger.events()` (Task 3); only `id`, `type`, `body`, `contract` are read.
- Produces: `task_state(events: Iterable[dict]) -> str | None` (`SUBMITTED`, `CLARIFYING`, `GATED`, `RUNNING`, `HIL_WAIT`, or the `TASK_CLOSED` state); `contract_state(events: Iterable[dict], contract_id: str) -> str | None` (`ISSUED`, `CLAIMED` or the last outcome).

- [ ] **Step 1: Write the failing test** — `core/tests/test_state.py`:

```python
import pytest

from ooat_core.state import contract_state, task_state


def ev(kind, body=None, id="evt_x", contract=None):
    event = {"id": id, "type": kind, "body": body or {}}
    if contract:
        event["contract"] = contract
    return event


SUBMITTED = ev("TASK_SUBMITTED", {"goal": "g"})
GATED_T2 = ev("TOPOLOGY_DECIDED", {"topology": "T2", "rules_applied": [], "candidates": []})
CLARIFY = ev("TOPOLOGY_DECIDED", {"topology": "T0", "rules_applied": ["A1"], "candidates": []})
ISSUED = ev("CONTRACT_ISSUED", {}, contract="ctr_1")


def request(id, blocking=True):
    return ev("HIL_REQUEST", {"blocking": blocking}, id=id)


def response(request_id):
    return ev("HIL_RESPONSE", {"request": request_id, "choice": "a"})


@pytest.mark.parametrize("events, expected", [
    ([], None),
    ([SUBMITTED], "SUBMITTED"),
    ([SUBMITTED, CLARIFY], "CLARIFYING"),
    ([SUBMITTED, CLARIFY, request("evt_q")], "CLARIFYING"),
    ([SUBMITTED, GATED_T2], "GATED"),
    ([SUBMITTED, GATED_T2, ISSUED], "RUNNING"),
    ([SUBMITTED, GATED_T2, ISSUED, request("evt_q")], "HIL_WAIT"),
    ([SUBMITTED, GATED_T2, ISSUED, request("evt_q"), response("evt_q")], "RUNNING"),
    ([SUBMITTED, GATED_T2, ISSUED, request("evt_q", blocking=False)], "RUNNING"),
    ([SUBMITTED, GATED_T2, ISSUED, request("evt_q"), ev("TASK_CLOSED", {"state": "CLOSED_ABSTAINED"})],
     "CLOSED_ABSTAINED"),
])
def test_task_state(events, expected):
    assert task_state(events) == expected


def test_contract_state_follows_its_own_events():
    events = [
        ev("CONTRACT_ISSUED", contract="ctr_1"),
        ev("CONTRACT_ISSUED", contract="ctr_2"),
        ev("CLAIM", contract="ctr_1"),
        ev("RESULT", {"outcome": "FAILED"}, contract="ctr_1"),
        ev("CLAIM", contract="ctr_1"),  # a crashed contract is restarted, not the task
        ev("ABSTAIN", {"outcome": "ABSTAIN_UNKNOWN"}, contract="ctr_2"),
    ]
    assert contract_state(events, "ctr_1") == "CLAIMED"
    assert contract_state(events, "ctr_2") == "ABSTAIN_UNKNOWN"
    assert contract_state(events + [ev("RESULT", {"outcome": "DONE"}, contract="ctr_1")], "ctr_1") == "DONE"
    assert contract_state(events, "ctr_3") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.state'`

- [ ] **Step 3: Implement** — `core/src/ooat_core/state.py`:

```python
"""Task and contract state as projections over ledger events (spec §8).

State is never stored: it is recomputed from events, so a restarted runtime sees exactly what the ledger holds.
F1 covers topologies T0–T2; PLANNED and REVIEW arrive with T3+.
"""

from collections.abc import Iterable


def task_state(events: Iterable[dict]) -> str | None:
    """Lifecycle state of one task from its events in ledger order; None before TASK_SUBMITTED."""
    state, open_requests = None, set()
    for event in events:
        kind, body = event["type"], event["body"]
        if kind == "TASK_SUBMITTED":
            state = "SUBMITTED"
        elif kind == "TOPOLOGY_DECIDED":
            clarifying = body["topology"] == "T0" and "A1" in body["rules_applied"]
            state = "CLARIFYING" if clarifying else "GATED"
        elif kind == "CONTRACT_ISSUED":
            state = "RUNNING"
        elif kind == "HIL_REQUEST" and body["blocking"]:
            open_requests.add(event["id"])
        elif kind == "HIL_RESPONSE":
            open_requests.discard(body["request"])
        elif kind == "TASK_CLOSED":
            return body["state"]
    if open_requests and state != "CLARIFYING":
        return "HIL_WAIT"
    return state


def contract_state(events: Iterable[dict], contract_id: str) -> str | None:
    """ISSUED, CLAIMED or the last outcome (DONE, PARTIAL, FAILED, ABSTAIN_*); None if never issued."""
    state = None
    for event in events:
        if event.get("contract") != contract_id:
            continue
        if event["type"] == "CONTRACT_ISSUED":
            state = "ISSUED"
        elif event["type"] == "CLAIM":
            state = "CLAIMED"
        elif event["type"] in ("RESULT", "ABSTAIN"):
            state = event["body"]["outcome"]
    return state
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Document the current state**

Replace `core/description.md` with:

```markdown
# ooat-core

## Purpose
Reference runtime of OOAT. Currently: identifiers, OOA Spec validation, the append-only ledger, artifact
storage and state projections. Gate, gateway, workers and API are not implemented yet.

## Key components
- `ids.py` — `new_id(prefix)`, ULIDs, `parse_artifact_ref()`
- `validation.py` — `validate(entity, document)` against `spec/schemas/`
- `ledger.py` — `Ledger`: the only write path; validates events, writes an event and its artifacts atomically
- `backends/` — `LedgerBackend` protocol and `open_backend(url)`; implemented: SQLite (ADR 0008)
- `blobs.py` — SHA-256 addressed bodies; tampering detected on read
- `artifacts.py` — `ArtifactStore.stage()` / `.read()`; artifacts exist only through their producing event
- `state.py` — `task_state()`, `contract_state()` computed from events

## Architectural patterns
Event sourcing: state is derived from the ledger, never stored. Ledger rules live in `Ledger`, SQL dialect
in a backend; every backend passes `tests/test_ledger.py`.

## Public API
`Ledger.open(url)`, `new_event()`, `ArtifactStore`, `BlobStore`, `task_state()`, `contract_state()`, `validate()`.
```

In `docs/description.md`, replace the line `- `core/`, `sdk/`, `adapters/`, `dashboard/`, `evals/` — empty` with:

```markdown
- `core/` — `ooat-core` package: ledger, artifact storage, state projections (see `core/description.md`)
- `sdk/`, `adapters/`, `dashboard/`, `evals/` — empty
```

In `tasks/f1-skeleton/task-01-core-ledger/task.md`, set `**Status:** done` and check all acceptance criteria.

- [ ] **Step 6: Commit**

```bash
git add core/src/ooat_core/state.py core/tests/test_state.py core/description.md docs/description.md tasks/f1-skeleton/task-01-core-ledger/task.md
git commit -m "core: task and contract state from events; document ooat-core"
```

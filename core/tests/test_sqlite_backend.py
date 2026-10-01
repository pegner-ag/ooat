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

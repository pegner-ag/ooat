import sqlite3
import threading

import pytest

from ooat_core.backends import LedgerBusyError, LedgerIntegrityError
from ooat_core.backends.sqlite import BUSY_TIMEOUT_MS, SCHEMA_VERSION, SqliteBackend

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


def test_replace_by_explicit_seq_is_rejected(backend):
    backend.insert({**EVENT, "id": "evt_2"}, [])  # no artifacts, so no foreign key protects it
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        backend._db.execute(
            "INSERT OR REPLACE INTO event (seq, id, ts, actor_kind, actor_id, type, body)"
            " VALUES (2, 'evt_forged', 't', 'hil', 'x', 'TASK_CLOSED', '{}')"
        )
    assert [row["id"] for row in backend.select_events(None, [])] == ["evt_1", "evt_2"]


def test_orphan_artifact_is_rejected_without_the_foreign_key_pragma(tmp_path):
    path = tmp_path / "ledger.sqlite"
    SqliteBackend(path).close()
    raw = sqlite3.connect(path)  # foreign keys are off by default on a new connection
    with pytest.raises(sqlite3.DatabaseError, match="producing event"):
        raw.execute("INSERT INTO artifact VALUES ('art_9', 1, 'summary', 'public', 0, 'x', 'blob:x', 'evt_missing')")
    raw.close()


def test_new_ledger_records_its_schema_version(tmp_path):
    path = tmp_path / "ledger.sqlite"
    SqliteBackend(path).close()
    raw = sqlite3.connect(path)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    raw.close()


def test_ledger_written_by_newer_code_is_refused(tmp_path):
    path = tmp_path / "ledger.sqlite"
    SqliteBackend(path).close()
    raw = sqlite3.connect(path)
    raw.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    raw.commit()
    raw.close()
    with pytest.raises(ValueError, match="newer"):
        SqliteBackend(path)


def test_version_1_ledger_is_migrated_to_record_estimates(tmp_path):
    from ooat_core.backends import sqlite as sqlite_backend

    path = tmp_path / "ledger.sqlite"
    raw = sqlite3.connect(path)
    version_1_ddl = sqlite_backend._DDL.replace("  price_ver     TEXT,\n  estimated_usd REAL\n", "  price_ver     TEXT\n")
    assert version_1_ddl != sqlite_backend._DDL
    raw.executescript(version_1_ddl)
    raw.execute("PRAGMA user_version = 1")
    raw.commit()
    assert "estimated_usd" not in [row[1] for row in raw.execute("PRAGMA table_info(event)")]
    raw.close()
    SqliteBackend(path).close()
    raw = sqlite3.connect(path)
    assert "estimated_usd" in [row[1] for row in raw.execute("PRAGMA table_info(event)")]
    assert raw.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 2
    raw.close()


def test_estimate_survives_the_round_trip():
    from ooat_core.ids import new_id
    from ooat_core.ledger import Ledger, new_event

    ledger = Ledger.open("sqlite:///:memory:")
    event = new_event("RESULT", task=new_id("tsk"), contract=new_id("ctr"),
                      actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
                      body={"outcome": "FAILED", "error": {"code": "UNAVAILABLE", "message": "x"}},
                      cost={"usd": 0.0, "basis": "estimated", "estimated_usd": 0.25})
    ledger.append(event)
    assert ledger.events()[0]["cost"]["estimated_usd"] == 0.25
    ledger.close()



def _version_1_file(tmp_path, with_column=False, version=1):
    from ooat_core.backends import sqlite as sqlite_backend

    path = tmp_path / "ledger.sqlite"
    raw = sqlite3.connect(path)
    ddl = sqlite_backend._DDL if with_column else sqlite_backend._DDL.replace(
        "  price_ver     TEXT,\n  estimated_usd REAL\n", "  price_ver     TEXT\n")
    raw.executescript(ddl)
    raw.execute(f"PRAGMA user_version = {version}")
    raw.commit()
    return path, raw


def test_migration_keeps_existing_events(tmp_path):
    from ooat_core.ids import new_id
    from ooat_core.ledger import Ledger, new_event

    path, raw = _version_1_file(tmp_path)
    raw.execute("INSERT INTO event (id, ts, task_id, contract_id, actor_kind, actor_id, role_ver, type, refs, body,"
                " cost_usd, cost_basis) VALUES ('evt_old', '2026-09-30T10:00:00Z', 'tsk_old', 'ctr_old', 'agent',"
                " 'agt_old', 'role.general.worker@0.1.0', 'RESULT', '[]', '{\"outcome\": \"DONE\"}', 0.5, 'exact')")
    raw.commit()
    raw.close()
    ledger = Ledger.open(f"sqlite:///{path}")
    (old,) = ledger.events()
    assert old["id"] == "evt_old" and old["cost"] == {"usd": 0.5, "basis": "exact"}
    event = new_event("RESULT", task=new_id("tsk"), contract=new_id("ctr"),
                      actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
                      body={"outcome": "FAILED", "error": {"code": "UNAVAILABLE", "message": "x"}},
                      cost={"usd": 0.0, "basis": "estimated", "estimated_usd": 0.25})
    ledger.append(event)
    assert ledger.events()[1]["cost"]["estimated_usd"] == 0.25
    ledger.close()


@pytest.mark.parametrize("with_column, version", [(True, 1), (False, 0)])
def test_migration_checks_the_column_not_the_version_number(tmp_path, with_column, version):
    path, raw = _version_1_file(tmp_path, with_column=with_column, version=version)
    raw.close()
    SqliteBackend(path).close()  # a crash after ALTER (column, still v1) or a pre-versioning file (v0)
    raw = sqlite3.connect(path)
    assert "estimated_usd" in [row[1] for row in raw.execute("PRAGMA table_info(event)")]
    assert raw.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    raw.close()


# Threads and processes (design 05 §7) ---------------------------------------------------------------------------

def test_a_file_ledger_uses_wal_and_a_five_second_busy_timeout(tmp_path):
    backend = SqliteBackend(tmp_path / "ledger.sqlite")
    assert backend._db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert backend._db.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS == 5000
    assert backend._db.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL, for an audit log
    backend.close()


def test_a_write_still_locked_out_after_the_timeout_is_busy_and_writes_nothing(tmp_path):
    path = tmp_path / "ledger.sqlite"
    backend = SqliteBackend(path)
    backend._db.execute("PRAGMA busy_timeout = 50")  # keep the test short
    other = sqlite3.connect(path, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")  # another process holds the write lock
    with pytest.raises(LedgerBusyError):
        backend.insert(EVENT, [ARTIFACT])
    other.execute("ROLLBACK")
    other.close()
    backend.insert(EVENT, [ARTIFACT])
    assert [row["id"] for row in backend.select_events(None, [])] == ["evt_1"]
    backend.close()


def test_opening_a_connection_while_another_writer_holds_the_lock_is_busy_too(tmp_path, monkeypatch):
    from ooat_core.backends import sqlite as sqlite_backend

    path = tmp_path / "ledger.sqlite"
    SqliteBackend(path).close()
    monkeypatch.setattr(sqlite_backend, "BUSY_TIMEOUT_MS", 50)
    other = sqlite3.connect(path, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(LedgerBusyError):  # opening runs the DDL, which needs the write lock
            SqliteBackend(path)
    finally:
        other.execute("ROLLBACK")
        other.close()


def test_readers_see_committed_rows_while_a_writer_holds_the_lock(tmp_path):
    path = tmp_path / "ledger.sqlite"
    backend = SqliteBackend(path)
    backend.insert(EVENT, [])
    reader = sqlite3.connect(path)
    with backend.transaction():
        backend.insert({**EVENT, "id": "evt_2"}, [])
        assert [row[0] for row in reader.execute("SELECT id FROM event")] == ["evt_1"]  # not blocked, not dirty
    assert [row[0] for row in reader.execute("SELECT id FROM event")] == ["evt_1", "evt_2"]
    reader.close()
    backend.close()


def test_a_failed_insert_inside_a_transaction_rolls_back_the_whole_transaction(tmp_path):
    backend = SqliteBackend(tmp_path / "ledger.sqlite")
    with pytest.raises(LedgerIntegrityError):
        with backend.transaction():
            backend.insert(EVENT, [])
            backend.insert(EVENT, [])  # duplicate id
    assert backend.select_events(None, []) == []
    with pytest.raises(RuntimeError, match="nest"):
        with backend.transaction():
            with backend.transaction():
                pass
    backend.close()


def _race(path, make_event, rounds=1, threads=2):
    """Append make_event() from `threads` threads at once, each on its own connection; the outcomes per round."""
    from ooat_core.ledger import Ledger

    outcomes = []
    for _ in range(rounds):
        events = [make_event() for _ in range(threads)]
        barrier, results = threading.Barrier(threads), [None] * threads

        def append(n):
            ledger = Ledger.open(f"sqlite:///{path.as_posix()}")
            barrier.wait()
            try:
                ledger.append(events[n])
                results[n] = "written"
            except Exception as error:  # noqa: BLE001 - the test inspects which error the loser got
                results[n] = error
            finally:
                ledger.close()

        workers = [threading.Thread(target=append, args=(n,)) for n in range(threads)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        outcomes.append(results)
    return outcomes


def test_two_threads_answering_one_request_write_one_answer_and_the_other_is_told(tmp_path):
    from ooat_core.ids import new_id
    from ooat_core.ledger import Ledger, new_event
    from ooat_core.validation import SpecValidationError

    path = tmp_path / "ledger.sqlite"
    ledger = Ledger.open(f"sqlite:///{path.as_posix()}")
    requests = []
    for _ in range(10):
        task = new_id("tsk")
        requests.append(ledger.append(new_event("HIL_REQUEST", task=task, actor={"kind": "system", "id": "x"}, body={
            "question": "Pokračovat?", "options": [{"id": "yes", "label": "Ano", "cost_usd": 0.0},
                                                    {"id": "no", "label": "Ne", "cost_usd": 0.0, "acts": False}],
            "recommended": "yes", "default_on_silence": "no", "deadline": "2026-10-12T10:00:00Z",
            "blocking": True, "evidence": []})))
    outcomes = []
    for request in requests:
        outcomes += _race(path, lambda r=request: new_event("HIL_RESPONSE", task=r["task"], actor={
            "kind": "hil", "id": "operator"}, body={"request": r["id"], "choice": "yes"}))
    for results in outcomes:
        assert results.count("written") == 1
        (loser,) = [r for r in results if r != "written"]
        # The check runs inside the write transaction, so the loser is told why, not hit by the unique index.
        assert isinstance(loser, SpecValidationError) and "already answered" in str(loser)
    assert len(ledger.events(types=["HIL_RESPONSE"])) == 10
    ledger.close()


def test_two_deliveries_of_one_chat_message_at_once_create_one_task(tmp_path):
    from ooat_core.ids import new_id
    from ooat_core.ledger import DuplicateIntake, Ledger, new_event

    path = tmp_path / "ledger.sqlite"
    Ledger.open(f"sqlite:///{path.as_posix()}").close()
    channel = "token:" + new_id("tok")
    for n in range(10):
        key = f"chat-1:msg-{n}"
        (results,) = _race(path, lambda k=key: new_event("TASK_SUBMITTED", task=new_id("tsk"), actor={
            "kind": "hil", "id": "operator"}, body={"goal": "Shrň smlouvu.", "channel": channel, "intake_key": k}))
        assert results.count("written") == 1
        (loser,) = [r for r in results if r != "written"]
        assert isinstance(loser, DuplicateIntake) and loser.task.startswith("tsk_")
    ledger = Ledger.open(f"sqlite:///{path.as_posix()}")
    assert len(ledger.events(types=["TASK_SUBMITTED"])) == 10
    ledger.close()

# Core ledger

**Epic:** f1-skeleton  **Status:** planned — see `plan.md`
**Origin:** spec §2, §3 (non-functional requirements), §7, §8

## Goal
The foundation of `ooat-core`: identifiers, validation against the OOA Spec schemas, the append-only
SQLite ledger with artifact records, content-addressed artifact storage and task/contract state derived
from events.

## Acceptance criteria
- [ ] `core/` is an installable package `ooat-core` (`python -m pip install -e core`), tested in CI.
- [ ] Every appended event is validated against `event.schema.json`; an invalid event is not written and
      the caller receives every validation message.
- [ ] The ledger backend is chosen by URL (ADR 0008); SQLite is implemented, `postgresql://` and `mssql://`
      are recognised but not implemented yet; every backend must pass `core/tests/test_ledger.py`.
- [ ] The ledger rejects UPDATE and DELETE on events and artifact records.
- [ ] An event and the artifacts it produces are written atomically; an artifact never exists without its
      producing event.
- [ ] Artifact bodies are stored by SHA-256; tampering is detected on read.
- [ ] Task and contract state are computed from events only and survive reopening the ledger file.

## Out of scope
Gateway, workers, Gate, REST API, dashboard (sub-projects 02–06).

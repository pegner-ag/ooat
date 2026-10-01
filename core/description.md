# ooat-core

## Purpose
Reference runtime of OOAT. Currently: identifiers, OOA Spec validation, the append-only ledger, artifact
storage and state projections. Gate, gateway, workers and API are not implemented yet.

## Key components
- `ids.py` — `new_id(prefix)`, ULIDs, `parse_artifact_ref()`
- `validation.py` — `validate(entity, document)` against `spec/schemas/`
- `ledger.py` — `Ledger`: the only write path; validates events (schema, finite numbers, 64-bit token counts, known artifact references, HIL options incl. R3 default "do not act", responses to existing requests) and staged artifact records, writes an event and its artifacts atomically
- `backends/` — `LedgerBackend` protocol and `open_backend(url)`; implemented: SQLite with schema version in `PRAGMA user_version` (ADR 0008)
- `blobs.py` — SHA-256 addressed bodies, fsynced before use, safe under concurrent writes; tampering detected on read, repaired on re-put
- `artifacts.py` — `ArtifactStore.stage()` / `.read()`; artifacts exist only through their producing event
- `state.py` — `task_state()`, `contract_state()` computed from events

## Architectural patterns
Event sourcing: state is derived from the ledger, never stored. Ledger rules live in `Ledger`, SQL dialect
in a backend; every backend passes `tests/test_ledger.py`.

## Public API
`Ledger.open(url)`, `new_event()`, `ArtifactStore`, `BlobStore`, `task_state()`, `contract_state()`, `validate()`.

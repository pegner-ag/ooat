# Ledger hardening (deferred review findings)

**Epic:** f1-skeleton  **Status:** done
**Origin:** final review of sub-project 01 (core ledger), findings graded Minor

## Goal
Close the smaller robustness gaps found in review before the ledger holds real data.

## Acceptance criteria
- [x] Oversized integers (e.g. `tokens_in = 2**70`) raise a ledger error, not a raw `OverflowError`.
- [x] `Ledger.append` validates `StagedArtifact` fields: SHA-256 digest format, `blob:<sha256>` URI, and
      `version == next_artifact_version` (no gaps).
- [x] `sqlite:///path?query` is rejected instead of treating the query as part of the file name.
- [x] `task_state` returns `None` until `TASK_SUBMITTED` and can filter by task id.
- [x] `Ledger.events(types="RESULT")` rejects a plain string.
- [x] `ulid(timestamp_ms)` rejects timestamps outside 0 … 2**48 − 1.
- [x] Blobs are fsynced before the rename; `BlobStore.put` repairs an existing blob whose digest no longer matches.
- [x] Round-trip fidelity documented (`Ledger.events` docstring): explicit `"contract": null` and integer `quota_units`.
- [x] A state test over a reopened file ledger with schema-valid events.
- [x] `PRAGMA user_version` (or equivalent) for future DDL migrations.

## Owner question
Answered: ADR 0009 (CLARIFYING returns to SUBMITTED once every clarifying question is answered).

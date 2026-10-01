# Ledger hardening (deferred review findings)

**Epic:** f1-skeleton  **Status:** open
**Origin:** final review of sub-project 01 (core ledger), findings graded Minor

## Goal
Close the smaller robustness gaps found in review before the ledger holds real data.

## Acceptance criteria
- [ ] Oversized integers (e.g. `tokens_in = 2**70`) raise a ledger error, not a raw `OverflowError`.
- [ ] `Ledger.append` validates `StagedArtifact` fields: SHA-256 digest format, `blob:<sha256>` URI, and
      `version == next_artifact_version` (no gaps).
- [ ] `sqlite:///path?query` is rejected instead of treating the query as part of the file name.
- [ ] `task_state` returns `None` until `TASK_SUBMITTED` and can filter by task id.
- [ ] `Ledger.events(types="RESULT")` rejects a plain string.
- [ ] `ulid(timestamp_ms)` rejects timestamps outside 0 … 2**48 − 1.
- [ ] Blobs are fsynced before the rename; `BlobStore.put` repairs an existing blob whose digest no longer matches.
- [ ] Round-trip fidelity documented or kept: explicit `"contract": null` and integer `quota_units`.
- [ ] A state test over a reopened file ledger with schema-valid events.
- [ ] `PRAGMA user_version` (or equivalent) for future DDL migrations.

## Owner question
- After `HIL_RESPONSE` to a clarification, does the task return to `SUBMITTED` for re-gating, or stay
  `CLARIFYING` until a new `TOPOLOGY_DECIDED`? (spec §8 does not say; current code: stays `CLARIFYING`)

# ADR 0003 — OOA Spec v0.1 schema interpretations

**Status:** accepted · **Date:** 2026-09-29 · **Context:** `spec/schemas/`, points where the spec text is silent or inconsistent

| # | Topic | Decision |
|---|---|---|
| 1 | Identifiers | `tsk_`, `ctr_`, `agt_`, `evt_`, `art_` use full 26-character ULIDs. IDs shortened in the spec text are illustrative only. |
| 2 | Technical failure | Contract outcome `FAILED` is recorded as a `RESULT` event with `outcome: FAILED` and a typed `error` (`TOOL_ERROR`, `TIMEOUT`, `API_ERROR`, `QUOTA_EXHAUSTED`, `INVALID_OUTPUT`). |
| 3 | Events without a task | `ADAPTER_ACKNOWLEDGED` has `task: null`; every other event type requires a task. |
| 4 | R3 default | `HIL_REQUEST` options may carry `acts`; an R3 request must include an option with `acts: false`, and the linter/runtime checks that `default_on_silence` points to it. |
| 5 | Objections | `severity` is `blocking` or `non_blocking`; `reason_code` is the closed list `SPEC_VIOLATION`, `FACT_UNSUPPORTED`, `GRAIN_MISMATCH`, `SECURITY_RISK`, `COST_RISK`, `INCONSISTENT_WITH_DECISION`, extended only by a spec version. |
| 6 | Role id | The middle segment of `role.<x>.<name>` is the capability domain (e.g. `bi`), not the family the role extends. The domain/family split itself is decided with the catalog taxonomy. |
| 7 | Schema `$id` | Host `ooat.invalid` is a placeholder until the project name and domain are settled (Q10). |

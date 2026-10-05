# ADR 0014 — Task runtime: provider failures, budget question, T2 critic

**Status:** accepted · **Date:** 2026-10-05 · **Context:** while designing and reviewing the task runtime (design 04
§5–§8, plan 04c) the owner decided four questions the spec does not answer or answers differently. They are
implemented in `core/src/ooat_core/runtime.py` and `acceptance.py`; this ADR records them so the spec v0.2
revision can carry them.

## Decision

1. **A provider failure never finishes a task** (owner, 2026-10-02). Quota, outage, timeout or API error pauses the
   task as `RUNNING` without using up an attempt. It resumes from the ledger with `ooat task run <id>` or
   `ooat task run --all`; 05 runs paused tasks automatically.
2. **A used-up contract budget asks the operator** (owner, 2026-10-03, choice B). Failed provider calls are charged
   their estimate. When the contract budget is used up, the task pauses with a blocking HIL question: raise the
   budget (recommended; `CONTRACT_ISSUED` is reissued with the raised `max_usd`) or stop. Silence until the
   deadline stops the task. Stopping keeps a usable document as `PARTIAL`.
3. **The contract budget is the task budget capped by the role's `max_usd_per_contract`.** The cap applies when the
   contract is issued; the operator's answer to the budget question may raise the budget above it.
4. **In T2 the critic runs on the same workhorse tier as the worker** (owner, 2026-10-03), although spec §7 rule 6
   says a critic never reviews output of the same role. Accepted as a T2 exception, revisited with T3+. The critic
   is called when Jev is unsure about a criterion, or when any input of the task is `untrusted`; an unsure critic
   counts the criterion as unmet, so an uncertain answer never produces `DONE`.

## Consequences

- Spec §7 rule 6, §8 (lifecycle: `RUNNING` may pause) and §9 (budget HIL question) are amended in the v0.2 revision
  (`tasks/spec/task-01-revision-v0-2/`).
- Decided by the owner on 2026-10-02 and 2026-10-03; recorded on 2026-10-05.

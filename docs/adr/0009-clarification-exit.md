# ADR 0009 — Leaving CLARIFYING

**Status:** accepted · **Date:** 2026-10-01 · **Context:** spec §8 says CLARIFYING leaves on `HIL_RESPONSE`
but does not name the next state

## Decision

When every clarifying question (each `HIL_REQUEST` raised while the task is `CLARIFYING`) has a
`HIL_RESPONSE`, the task returns to **`SUBMITTED`** and waits for the Topology Gate, which decides again.
While any clarifying question is still open, the task stays `CLARIFYING`.

## Why

- The dashboard stops showing the task as waiting for the human the moment they have answered.
- The 48-hour clarification timeout stops on the answer, so a slow or crashed Gate can never close a task
  as abstained although the human answered in time; after a restart the Gate simply picks it up again.
- If the answer is still not enough, the Gate asks again (rule A1, max. 3 clarifying questions).

Implemented in `core/src/ooat_core/state.py` (`task_state`).

## Consequences

- Spec §8 (`CLARIFYING` row of the task lifecycle) is amended by this ADR; the spec text is aligned in its next
  revision.
- Decided by the owner on 2026-10-01.

## Amendment — narrowing the scope (owner, 2026-10-02)

When the Gate's estimate exceeds the task budget, its question offers "raise the budget", "narrow the scope" or
"do not run". A `GATED` task whose budget question is answered by narrowing the scope (choice `narrow_scope` with
text) returns to the Topology Gate, which decides again on the task text plus the narrowed scope. The task state
stays `GATED` until the new `TOPOLOGY_DECIDED`; the Gate asks at most 3 budget questions per task, then closes it
as `CLOSED_ABSTAINED`. Each narrowing halves the output prior of the Gate's estimate, so narrowing can bring a
task under its budget. Implemented in `core/src/ooat_core/gate.py` (`task_facts().narrowed`). Spec §8 (`GATED`
row) is aligned in the v0.2 revision.

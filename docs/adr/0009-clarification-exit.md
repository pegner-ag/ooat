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

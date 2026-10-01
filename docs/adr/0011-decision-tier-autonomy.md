# ADR 0011 — Decision tier from the first task; projects on tasks

**Status:** accepted · **Date:** 2026-10-01 · **Context:** task runtime design
(`tasks/f1-skeleton/task-04-task-runtime/design.md`)

## Decision

1. **Jev decides from the first task** (amends spec §6 "θ = 1 until 20 rated cases" and §11). A decision point acts
   on an answer whose confidence reaches its threshold: 0.8 until 5 rated tasks exist for that point (the first
   5 tasks are the calibration set), then the spec §6 threshold computed on the rated history and recomputed after
   every rating. Below the threshold the safer outcome applies.
2. **Guardrails that do not slow Jev down:** a detected data class can only raise the declared class, never lower
   it; R2 and R3 actions are never decided by a model; every choice question is asked twice with reversed option
   order; every decision is recorded with engine, answer, confidence and threshold.
3. **Decision connectors** (`kind = "decision"`) are routed by the gateway like model connectors; when none can
   serve a request, the `economy` text tier answers the same typed questions.
4. **Schema:** `TASK_SUBMITTED.body.project`; `TOPOLOGY_DECIDED.body.decisions`; `TASK_RATED.body.decisions`
   (confirmed or corrected per decision), feeding the thresholds.

## Consequences

- Five rated tasks give a rough threshold; it sharpens with every further rating. The calibration view (F2) shows
  predicted vs. observed accuracy per decision point.
- Spec §6 and §11 text follows in the v0.2 revision (`tasks/spec/`).
- Decided by the owner on 2026-10-01.

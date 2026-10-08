# ADR 0011 — Decision tier from the first task; projects on tasks

**Status:** accepted · **Date:** 2026-10-01 · **Context:** task runtime design
(`tasks/f1-skeleton/task-04-task-runtime/design.md`)

## Decision

1. **Jev decides from the first task.** A decision acts when its confidence reaches the threshold θ of its key:
   decision point, engine and model version. Only R0 and R1 tasks act on decisions alone (spec §6).
   - Interim θ, while a key has fewer than 5 rated decisions: 0.8 for a decision connector; 1 for the text-model
     fallback, whose self-stated probability never acts alone before it is rated. The first 5 tasks are the
     calibration set.
   - θ_computed is the smallest θ on the grid 0.50–0.99 (step 0.01) for which at least 5 rated decisions have
     confidence ≥ θ and their error rate is at most ε (R0 5 %, R1 2 %). If no θ qualifies, θ_computed = 1.
   - From 5 to 19 ratings: θ = max(0.8, θ_computed). From 20 ratings: θ = θ_computed. It is recomputed after every
     rating. Ratings of another model version do not count.

   Below θ the safer outcome applies.
2. **Guardrails that do not slow Jev down:**
   - Detection can only raise the declared data class, never lower it.
   - A local deterministic pre-scan for personal data runs before anything is sent to a decision provider.
   - R2 and R3 actions are never decided by a model.
   - Every choice question is asked twice with the option order reversed.
   - An acceptance answer below θ goes to the LLM critic and never counts as a pass on its own.
   - When a task has untrusted inputs, a "met" answer is also confirmed by the critic.
   - Every decision is recorded with engine, model version, answer, confidence and threshold.
3. **Decision connectors** (`kind = "decision"`) are routed by the gateway like model connectors. When none can
   serve a request, the `economy` text tier answers the same typed questions; it is calibrated as its own engine.
4. **Schema:**
   - `TASK_SUBMITTED.body.project`;
   - decision records in `TOPOLOGY_DECIDED.body.decisions` and in `GATE_PASSED` / `GATE_FAILED`
     `body.criteria[].decision`;
   - `TASK_RATED.body.decisions`: a list of `{event, question, verdict, value}`, so that repeated questions are
     rated separately. These ratings feed the thresholds;
   - a fourth gate kind, `gate.decision.<name>`, for acceptance checks answered by the decision tier.

## Spec text this overrides

- §4 step A: "the calibrated probabilities become Gate inputs only after OOAT's own calibration". Decision
  connectors now act from the first task with the interim θ = 0.8. The text fallback keeps θ = 1 until it is rated.
- §6 "Introduced in F2; F1 uses deterministic rules and the fallback": the decision tier is introduced in F1.
- §6 and §11 "θ = 1 until 20 rated cases": replaced by the schedule in point 1.
- §2 "Gate — Checkpoint: deterministic, critic or HIL": a gate may also be of kind `decision`.

## Consequences

- Five rated tasks give a rough threshold. The 0.8 floor holds until 20 ratings, the minimum support of 5 keeps
  θ_computed away from noise, and every further rating sharpens it. The calibration view (F2) shows predicted vs.
  observed accuracy per decision point.
- Without Jev, the Gate asks the operator more often until the fallback has its own ratings.
- Personal data that the pre-scan cannot recognise is sent to the decision provider under the class the operator
  declared. This residual risk is stated to the operator.
- The spec v0.2 revision (`tasks/spec/`) will carry these changes into §2, §4, §6 and §11.
- Decided by the owner on 2026-10-01; the override of spec text was confirmed by the owner on 2026-10-02.

## Amendment (owner, 2026-10-08)

A key leaves its interim θ only when its ratings come from at least two tasks. In the seed calibration, the five
ratings of one client task alone unlocked the fallback's a1 threshold. One task's decisions are not independent
evidence: the same text and the same criteria rated five times.

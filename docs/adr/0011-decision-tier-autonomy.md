# ADR 0011 — Decision tier from the first task; projects on tasks

**Status:** accepted · **Date:** 2026-10-01 · **Context:** task runtime design
(`tasks/f1-skeleton/task-04-task-runtime/design.md`)

## Decision

1. **Jev decides from the first task.** A decision point acts on an answer whose confidence reaches its
   threshold θ. θ is kept per decision point, engine and model version:
   - θ = 0.8 until 5 rated tasks exist for that key (the first 5 tasks are the calibration set);
   - from 5 ratings, θ = max(0.8, θ_computed), where θ_computed is the spec §6 rule on the rated history,
     recomputed after every rating;
   - from 20 ratings, θ_computed alone.

   Below θ the safer outcome applies. Ratings of another model version do not count.
2. **Guardrails that do not slow Jev down:**
   - Detection can only raise the declared data class, never lower it.
   - A local deterministic pre-scan for personal data runs before anything is sent to a decision provider.
   - R2 and R3 actions are never decided by a model.
   - Every choice question is asked twice with the option order reversed.
   - An acceptance answer below θ goes to the LLM critic and never counts as a pass on its own.
   - Every decision is recorded with engine, model version, answer, confidence and threshold.
3. **Decision connectors** (`kind = "decision"`) are routed by the gateway like model connectors. When none can
   serve a request, the `economy` text tier answers the same typed questions; it is calibrated as its own engine.
4. **Schema:**
   - `TASK_SUBMITTED.body.project`;
   - `TOPOLOGY_DECIDED.body.decisions`;
   - `TASK_RATED.body.decisions`: confirmed, or corrected with the right value; these ratings feed the thresholds.

## Spec text this overrides

- §4 step A: "the calibrated probabilities become Gate inputs only after OOAT's own calibration". They now act
  from the first task with the interim θ = 0.8.
- §6 "Introduced in F2; F1 uses deterministic rules and the fallback": the decision tier is introduced in F1.
- §6 and §11 "θ = 1 until 20 rated cases": replaced by the schedule in point 1.

## Consequences

- Five rated tasks give a rough threshold. The 0.8 floor holds until 20 ratings, and every further rating sharpens
  the threshold. The calibration view (F2) shows predicted vs. observed accuracy per decision point.
- Personal data that the pre-scan cannot recognise is sent to the decision provider under the class the operator
  declared. This residual risk is stated to the operator.
- The spec v0.2 revision (`tasks/spec/`) will carry these changes into §4, §6 and §11.
- Decided by the owner on 2026-10-01.

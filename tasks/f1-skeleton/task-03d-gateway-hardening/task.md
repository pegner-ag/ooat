# Gateway hardening (deferred review findings)

**Epic:** f1-skeleton  **Status:** open
**Origin:** final review of plan 03a, findings graded Minor

## Acceptance criteria
- [ ] Budget comparison tolerates floating-point error: a call whose estimate equals the remaining budget is
      allowed after earlier spending too (`estimate.usd > remaining + 1e-9`), with a test where spent > 0.
- [ ] A pin that names a connector which is not installed or is broken adds a trace line saying so.
- [ ] The registry keeps a frozen copy of each validated manifest and the gateway routes on that copy, so a
      connector cannot change its data policy or jurisdiction after validation.
- [ ] Budget reservation: an in-flight call reserves its estimate against the contract budget until the caller
      appends the cost, so concurrent or back-to-back calls cannot overspend (with the 04 threading model).
- [ ] `GatewayError` documents the design §7 mapping to contract outcomes (`NOT_PERMITTED` and `BUDGET` are
      abstentions, not `RESULT.error.code` values).
- [x] Token accounting convention: `tokens_in` excludes cache reads and includes cache writes; `tokens_cached`
      is cache reads, billed at the cached price (documented in each connector's `description.md`, 03b).
- [ ] Cache writes are billed at the base input price; Anthropic charges 1.25x (5-minute) or 2x (1-hour).
- [ ] The consequences card shows both `jurisdiction.training_on_inputs` and `data_policy.training_on_inputs`
      (and `retention_days`) and flags a mismatch; today it shows only the enforced `data_policy` value.

### From the final review of plan 04a (decision layer)
- [ ] The fallback's budget check counts the cost of the failed decision-tier call, which the caller has not yet
      appended to the ledger (small overrun possible today).
- [ ] `estimate_decision()` reports the fallback's price when the state is too large for the decision connector
      (move Jev's 32k-token limit into the manifest or a gateway check).
- [ ] Measure Jev's tokens per character on Czech text; the characters / 3 estimate is unverified.
- [ ] Document that a noul `p_true` given as a percentage is refused while choice and score are normalised.
- [ ] Linter rule: a decision record's `answer` fits its question type (noul 0..1, score within the levels).
- [ ] `adapters/typesafe-jev/description.md`: a connect timeout is reported as `UNAVAILABLE`, not `TIMEOUT`.

### From the final review of plan 04b (Topology Gate)
- [ ] `task_facts()` raises `ValueError` (not `StopIteration`) for an unknown task.
- [ ] `TOPOLOGY_DECIDED.candidates[].eliminated_by` names the real reason when no route exists and the class was
      not raised (today it falls back to `A10` or `A3`).
- [ ] Compute `rated_decisions()` once per Gate batch instead of once per answer.
- [ ] The budget comparison counts the Gate cost already spent on the task.
- [ ] Document the pre-scan's residual gaps: lowercase IBANs, `00420…` numbers (seen as cards), phone numbers of
      other countries.

### From the review of PR #10
- [ ] Spec §4 rule A3 sends a task below `v_min` to T2 "without further calculation"; the Gate only records A3
      and may still close or clarify. Align the code or record the deviation in the spec v0.2 revision.
- [ ] Payment-card check: any 13–19 digit number passing Luhn (about 1 in 10, e.g. epoch-ms timestamps) raises a
      task to `personal`; require separators or an issuer prefix.
- [ ] An empty `narrow_scope` answer uses up a budget question without changing anything; ask again instead.

### From the final review of plan 03e (operator responsibility)
- [ ] `ooat connectors enable`: say when `--regions`, `--responsibility` or `--no-training` is ignored, and check
      the classes (e.g. `special_category`) before asking for responsibility.
- [ ] Define the region pattern once (config.py) and import it in operator_cli.py.

### From the review of PR #12
- [ ] `jurisdiction_stale(..., responsible=...)`: make the parameter required (or default False) so a caller that
      omits it stays fail-closed; the listing passes whether a responsibility is in force.
- [ ] The gateway says "not allowed by the manifest" when the real cause is an expired responsibility; name it.
- [ ] `checked_classes` tests `no_training` by truthiness; use `is True` like the gateway and `may_extend()`.
- [ ] Spec v0.2 revision (`tasks/spec/`) must carry ADR 0011 and ADR 0012 into spec §2, §4, §6, §8, §9 and §11.

### From the final review of plan 04c (task runtime)
- [ ] When the critic pauses, record the `RESULT FAILED` under the runtime actor, not the worker agent.
- [ ] A re-run acceptance check reuses a decision gate already recorded for the same document instead of paying
      for it again (rating then shows no duplicates).
- [ ] `ooat task rate`: validate each typed correction at once (a choice option must exist; a yes/no decision
      takes 0 or 1) instead of failing after the last prompt.
- [ ] Owner decision pending: repeated provider failures are charged against the contract budget and can end a
      paused task as `ABSTAIN_BUDGET`.

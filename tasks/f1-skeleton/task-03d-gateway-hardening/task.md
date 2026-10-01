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
- [ ] Token accounting convention defined and documented: `tokens_in` excludes cached input; `tokens_cached`
      is billed at the cached price (settled with the connectors in 03b).

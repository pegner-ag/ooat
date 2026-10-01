# Gateway hardening (deferred review findings)

**Epic:** f1-skeleton  **Status:** open
**Origin:** final review of plan 03a, findings graded Minor

## Acceptance criteria
- [ ] Budget comparison tolerates floating-point error: a call whose estimate equals the remaining budget is
      allowed after earlier spending too (`estimate.usd > remaining + 1e-9`), with a test where spent > 0.
- [ ] A pin that names a connector which is not installed or is broken adds a trace line saying so.

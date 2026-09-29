# ADR 0005 — First adapters for F1

**Status:** accepted · **Date:** 2026-09-29 · **Answers:** Q7, Q8

## Access (Q7)

- TypeSafe Jev: the operator has early access → the `decision` tier can exist in F1.
- Meta Model API: not available to the operator yet; the Muse Spark adapter waits until access is set up.

## Adapter order (Q8): subscriptions first, APIs as fallback

| Priority | Adapter | Tiers | Role in F1 |
|---|---|---|---|
| 1 | `prv.anthropic.subscription_cli` (Claude Code headless, USD 100/month plan) | `workhorse`, `frontier` | Default worker and orchestrator |
| 2 | `prv.openai.subscription_cli` (Codex CLI, USD 20/month plan) | `workhorse` | Second vendor, so T3 critics can run on a different vendor than the author |
| 3 | `prv.typesafe.api` (Jev) | `decision` | Gate step A, data-class guard, acceptance pre-checks |
| 4 | `prv.anthropic.api`, `prv.openai.api` | `economy` to `frontier` | Fallback when quota is exhausted or automation is not permitted; also satisfies the F1 requirement of one metered API adapter |

## Conditions

- Every subscription adapter starts with `automation_permitted: unknown`. It runs unattended only after the
  operator has checked that plan's terms and set `operator_confirmed`; until then it is limited to
  `subscription_manual` with HIL (spec §6). OOAT does not work around provider terms.
- Subscription quota is priced by its shadow price (spec §6); until `U_eff` is measured the API list price
  of an equivalent model is the prior.
- Every adapter is enabled only after the connection consequences card is acknowledged (spec §9).

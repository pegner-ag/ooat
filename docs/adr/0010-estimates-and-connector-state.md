# ADR 0010 — Cost estimates and connector state in the ledger

**Status:** accepted · **Date:** 2026-10-01 · **Context:** provider gateway design
(`tasks/f1-skeleton/task-03-provider-gateway/design.md`)

## Decision

1. **Estimate next to actual.** The event `cost` object gets an optional `estimated_usd`: the gateway's
   estimate made before the call. Predicted and actual cost are then comparable per connector and capability
   from the first call on; the Gate (04) uses the same estimates to stop tasks that would exceed their budget
   or value.
2. **Connector state is ledger state.** Enabling a connector is an `ADAPTER_ACKNOWLEDGED` event whose body
   gains `automation_confirmed` (boolean: the operator confirmed the plan's terms allow unattended use) and
   `jurisdiction_sha256` (fingerprint of the acknowledged `jurisdiction` block). A new event type
   `ADAPTER_DISABLED` (body: `adapter`, `operator`, `reason`; human actor only; no task) disables it. The
   configuration file holds preferences only and cannot enable a connector.
3. **Automation rule (amends spec §6 and ADR 0005).** The manifest field `automation_permitted` now states the
   provider's terms as published (`not_permitted` or `unknown`; `operator_confirmed` is no longer written into
   manifests). Unattended use requires `automation_permitted != not_permitted` **and** an acknowledgement with
   `automation_confirmed: true`; an acknowledgement never overrides `not_permitted`.
4. **Staleness (spec §9 rule 2).** A changed `jurisdiction` block (fingerprint mismatch) or a `verified_on` that
   is `null` or older than 12 months refuses `personal` and `special_category` until re-acknowledged; other
   classes stay available.
5. **Error codes.** `RESULT.error.code` gains `UNAVAILABLE` (connector not reachable, CLI missing or logged out);
   provider-side failures use the existing `API_ERROR`.
6. Connectors are discovered through the Python entry-point group `ooat.connectors`; one mechanism serves model
   connectors now and tool connectors later.

## Consequences

- `spec/schemas/event.schema.json` changes are made in plan 03a with valid and invalid examples: `cost.estimated_usd`;
  `ADAPTER_ACKNOWLEDGED` body fields; `ADAPTER_DISABLED` type, body, and its entries in the `task: null` and
  human-actor conditionals; `UNAVAILABLE` error code. Spec §6, §7 and §9 text follows in the v0.2 revision
  (`tasks/spec/`).
- Decided by the owner on 2026-10-01.

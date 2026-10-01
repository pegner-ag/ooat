# ADR 0010 — Cost estimates and connector state in the ledger

**Status:** accepted · **Date:** 2026-10-01 · **Context:** provider gateway design
(`tasks/f1-skeleton/task-03-provider-gateway/design.md`)

## Decision

1. **Estimate next to actual.** The event `cost` object gets an optional `estimated_usd`: the gateway's
   estimate made before the call. Predicted and actual cost are then comparable per connector and capability
   from the first call on; the Gate (04) uses the same estimates to stop tasks that would exceed their budget
   or value.
2. **Connector state is ledger state.** Enabling a connector is an `ADAPTER_ACKNOWLEDGED` event whose body
   gains `automation_confirmed` (boolean: the operator confirmed the plan's terms allow unattended use). A new
   event type `ADAPTER_DISABLED` (body: `adapter`, `operator`, `reason`) disables it. The configuration file
   holds preferences only and cannot enable a connector.
3. Connectors are discovered through the Python entry-point group `ooat.connectors`; one mechanism serves model
   connectors now and tool connectors later.

## Consequences

- `spec/schemas/event.schema.json` changes (cost key, acknowledgement field, new event type) are made in plan
  03a with valid and invalid examples; spec §7 and §9 text follows in the v0.2 revision (`tasks/spec/`).
- Decided by the owner on 2026-10-01.

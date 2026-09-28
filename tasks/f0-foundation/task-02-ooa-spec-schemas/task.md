# OOA Spec v0.1 — JSON Schemas

**Epic:** f0-foundation  **Status:** open
**Origin:** spec §12 F0, second checklist item

## Goal
Normative JSON Schemas (2020-12) for: capability, family, role, provider adapter, contract, event
(envelope + body per event type), routing.

## Context
- `spec/ooat-specification.md` §2 (entities, keys, outcomes), §5 (capability/role cards, inheritance),
  §6 (provider manifest, tiers), §7 (event envelope, event types, ledger SQL), §9 (HIL request, `jurisdiction` block).
- Schemas go to `spec/schemas/`; examples from the spec go to `spec/examples/` and must validate.

## Acceptance criteria
- [ ] One schema per entity in `spec/schemas/*.schema.json`, `$id` versioned (`v0.1`).
- [ ] Event `body` schemas for every event type in §7, including `ADAPTER_ACKNOWLEDGED` (§9).
- [ ] Abstention outcomes require `reason` (≤ 300 chars), `missing`, `confidence` 0–1 (§2).
- [ ] ID patterns enforced (`cap.<domain>.<verb>_<object>`, `role.<family>.<name>`, `family.<name>`,
      `prv.<vendor>.<access>`, `tsk_/ctr_/agt_/evt_<ulid>`, `art_<ulid>@v<n>`).
- [ ] All JSON examples from the spec stored in `spec/examples/` and validated by an automated test
      (a small pytest using `jsonschema`), plus at least one invalid example per schema that must fail.
- [ ] `spec/README.md` explaining each schema in one line.

## Out of scope
Runtime, linter for inheritance resolution (F1), `_resolved/` output.

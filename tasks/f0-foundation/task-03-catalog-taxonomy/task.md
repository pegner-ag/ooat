# Catalog taxonomy — domains, families, ~100 capability names

**Epic:** f0-foundation  **Status:** implemented — waiting for owner review of the capability list
**Origin:** spec §12 F0, third checklist item; structure per `docs/adr/0004-domains-and-families.md`

## Goal
13 capability domains with ~102 capability names and one-line summaries, plus the abstract role
families; no implementation.

## Context
- Spec §5 "Starter capability domains"; ADR 0004 (domains = namespaces, families = kind of work).

## Acceptance criteria
- [x] `catalog/families/*.json` — `family.base` + 5 kinds, valid against the family schema; kinds only
      narrow base permissions and budget (tested).
- [x] `catalog/taxonomy.json` listing every capability: id, one-line English summary, proposed `impl`.
- [x] Counts per domain match their `target` in `taxonomy.json` (±2); starter domains use spec §5 targets.
- [x] `general` domain with the T2 fallback capability `cap.general.complete_task` (103 in total).
- [x] No capability cards with prompts or cost cards yet.
- [ ] Owner review of capability names, summaries and proposed `impl`.

## Out of scope
The 15 implemented capabilities and 5 roles of F1.

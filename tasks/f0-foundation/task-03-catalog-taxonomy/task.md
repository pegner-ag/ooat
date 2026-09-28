# Catalog taxonomy — 13 families, ~100 capability names

**Epic:** f0-foundation  **Status:** open
**Origin:** spec §12 F0, third checklist item

## Goal
Taxonomy of the starter catalog: 13 family cards and ~102 capability names with one-line summaries, no implementation.

## Context
- Spec §5 "Starter capability domains" (families and target counts), naming `cap.<domain>.<verb>_<object>`.
- Depends on task-02 (family schema) for the family cards; the name list can start earlier.

## Acceptance criteria
- [ ] `catalog/families/*.json` — 13 families (+ `family.base`), valid against the family schema.
- [ ] `catalog/taxonomy.md` (or JSON) listing every capability: id, one-line English summary, proposed `impl`
      (`deterministic` / `decision` / `llm`, lowest kind that can do the job).
- [ ] Counts per family match spec §5 targets (±2).
- [ ] No capability cards with prompts or cost cards yet.

## Out of scope
The 15 implemented capabilities and 5 roles of F1.

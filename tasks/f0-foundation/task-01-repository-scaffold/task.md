# Repository scaffold completion

**Epic:** f0-foundation  **Status:** open
**Origin:** spec §12 F0, first checklist item

## Goal
Finish the public-repository basics that were not created during initial setup.

## Context
Folder skeleton, README, CLAUDE.md, AGENTS.md, `.gitignore`, `docs/adr/` already exist (see `docs/description.md`).

## Acceptance criteria
- [x] `LICENSE` — Apache 2.0 (ADR 0002).
- [ ] `CONTRIBUTING.md`: how to propose catalog packs, adapters, calibration tasks; evals mandatory; packs start in `shadow`.
- [ ] `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1 unless the owner prefers otherwise).
- [ ] Short `description.md` in each top-level code folder once it contains more than a stub.
- [ ] Public remote created — only after owner approval and Q10 (name) answered.

## Out of scope
Any runtime code (F1).

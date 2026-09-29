# ADR 0007 — Governance

**Status:** accepted · **Date:** 2026-09-29 · **Answers:** Q11

## Decision

- **Maintainer:** the project owner is the sole maintainer (single-maintainer model). Only a human
  maintainer merges pull requests, accepts catalog packs, publishes releases and enforces the code of conduct.
- **AI review:** Claude Opus 5.5 is the first-line reviewer of every pull request and catalog pack: schema
  validation, eval results, security, consistency with the spec and ADRs. Its review is advisory and is
  recorded on the pull request.
- **Catalog changes** follow spec §9: pull request → schema validation → evals → shadow run → human
  approval (R2). Agents may propose catalog changes, never apply them.

## Why not the model as maintainer

OOAT's own rules require a named human for R2 approvals (catalog and routing changes) and for publishing.
Merging to a public repository and releasing packages are exactly such actions. A model can prepare the
decision; the owner makes it.

## Revisit

When regular outside contributors appear, add co-maintainers and write `GOVERNANCE.md`.

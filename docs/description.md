# OOAT — overview (As-is)

## Purpose
OOAT is an open-source framework for multi-agent AI work in which a Topology Gate decides per task whether
a team is worth its cost. The repository currently contains the specification and the OOA Spec v0.1 JSON Schemas with tests;
the starter catalog holds role families and capability names only; no runtime exists yet.

## Technology
Chosen by decision (see `docs/adr/0001-initial-decisions.md`), not yet used in code:
- Core runtime: Python 3.12+, FastAPI, Pydantic v2
- Store: pluggable ledger backend by URL — SQLite (Solo), PostgreSQL (Team), SQL Server optional (ADR 0008)
- Dashboard and TS SDK: TypeScript
- Schemas: JSON Schema 2020-12

## Project structure
- `spec/ooat-specification.md` — normative design, draft v0.1 (sections 1–14)
- `spec/manifesto.md` — rationale for non-technical readers
- `spec/schemas/`, `spec/examples/`, `spec/tests/` — OOA Spec v0.1 JSON Schemas, examples, pytest (see `spec/README.md`)
- `catalog/families/` — `family.base` and 5 abstract families (analyst, builder, reviewer, communicator, orchestrator)
- `catalog/taxonomy.json` — 13 starter domains + `general` fallback; 103 capability names with summary, proposed `impl` and per-domain target
- `catalog/tests/` — schema, family-chain and taxonomy checks
- `core/`, `sdk/`, `adapters/`, `dashboard/`, `evals/` — empty
- `docs/adr/` — decision records; `docs/assets/` — images (social preview)
- `.github/` — CI (`tests.yml`: pytest on 3.12 and 3.13), Claude review workflows (`claude-review.yml` automatic on same-repo PRs, `claude.yml` on `@claude` mentions; Opus 5.5, comment-only, advisory per ADR 0007; auth via `CLAUDE_CODE_OAUTH_TOKEN`), issue and PR templates
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` — contribution rules, Contributor Covenant 2.1, private vulnerability reporting
- `tasks/` — open work (To-be), one folder per task

## Configuration
None yet. Dev dependencies: `requirements-dev.txt`; run `python -m pytest` (paths in `pytest.ini`).

## Security invariants
- No secrets in the repository.
- Ledger append-only; only `ooat-core` writes to it.
- R3 actions only with a named human approver.
- Data classes are enforced in the provider gateway, not in prompts.

## Related documentation
- `.claude/lessons.md` — gotchas
- `docs/adr/` — decisions

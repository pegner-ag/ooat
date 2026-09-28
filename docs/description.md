# OOAT — overview (As-is)

## Purpose
OOAT is an open-source framework for multi-agent AI work in which a Topology Gate decides per task whether
a team is worth its cost. The repository currently contains the specification and the OOA Spec v0.1 JSON Schemas with tests;
no runtime or catalog exists yet.

## Technology
Chosen by decision (see `docs/adr/0001-initial-decisions.md`), not yet used in code:
- Core runtime: Python 3.12+, FastAPI, Pydantic v2
- Store: SQLite (Solo profile), Postgres (Team profile)
- Dashboard and TS SDK: TypeScript
- Schemas: JSON Schema 2020-12

## Project structure
- `spec/ooat-specification.md` — normative design, draft v0.1 (sections 1–14)
- `spec/manifesto.md` — rationale for non-technical readers
- `spec/schemas/`, `spec/examples/`, `spec/tests/` — OOA Spec v0.1 JSON Schemas, examples, pytest (see `spec/README.md`)
- `catalog/`, `core/`, `sdk/`, `adapters/`, `dashboard/`, `evals/` — empty
- `docs/adr/` — decision records
- `tasks/` — open work (To-be), one folder per task

## Configuration
None yet. Dev dependencies: `requirements-dev.txt`; run `python -m pytest spec/tests`.

## Security invariants
- No secrets in the repository.
- Ledger append-only; only `ooat-core` writes to it.
- R3 actions only with a named human approver.
- Data classes are enforced in the provider gateway, not in prompts.

## Related documentation
- `.claude/lessons.md` — gotchas
- `docs/adr/` — decisions

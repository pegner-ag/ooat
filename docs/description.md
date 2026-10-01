# OOAT — overview (As-is)

## Purpose
OOAT is an open-source framework for multi-agent AI work in which a Topology Gate decides per task whether
a team is worth its cost. The repository currently contains the specification and the OOA Spec v0.1 JSON Schemas with tests;
the starter catalog holds role families and capability names only; `ooat-core` has the ledger foundation
and the provider gateway core (no concrete connectors, Gate, workers or API yet).

## Technology
In use:
- Core runtime: Python 3.12+ (`core/`), JSON Schema 2020-12 validation (`jsonschema`)
- Ledger backend: SQLite, selected by URL (ADR 0008)
- Model connectors as separate packages in `adapters/`: Claude Code CLI, Codex CLI, Anthropic Messages API

Chosen by decision (`docs/adr/`), not yet used in code:
- FastAPI and Pydantic v2 for the API
- PostgreSQL (Team) and optional SQL Server ledger backends (ADR 0008)
- Dashboard and TS SDK: TypeScript

## Project structure
- `spec/ooat-specification.md` — normative design, draft v0.1 (sections 1–14)
- `spec/manifesto.md` — rationale for non-technical readers
- `spec/schemas/`, `spec/examples/`, `spec/tests/` — OOA Spec v0.1 JSON Schemas, examples, pytest (see `spec/README.md`)
- `catalog/families/` — `family.base` and 5 abstract families (analyst, builder, reviewer, communicator, orchestrator)
- `catalog/taxonomy.json` — 13 starter domains + `general` fallback; 103 capability names with summary, proposed `impl` and per-domain target
- `catalog/tests/` — schema, family-chain and taxonomy checks
- `core/` — `ooat-core` package: ledger, artifact storage, state projections, provider gateway core (see `core/description.md`)
- `adapters/` — connector packages `ooat-adapter-claude-code`, `ooat-adapter-codex`, `ooat-adapter-anthropic-api`
  (each with `description.md`), `integration_tests/` (gateway with the real connectors, no network)
- `catalog/routing.json` — reference routing policy: Anthropic list prices with source and date, data-class policy
- `sdk/`, `dashboard/`, `evals/` — empty
- `docs/adr/` — decision records; `docs/assets/` — images (social preview)
- `.github/` — CI (`tests.yml`: pytest on 3.12 and 3.13), Claude review workflows (`claude-review.yml` automatic on same-repo PRs, `claude.yml` on `@claude` mentions; Opus 5.5, comment-only, advisory per ADR 0007; auth via `CLAUDE_CODE_OAUTH_TOKEN`), issue and PR templates
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` — contribution rules, Contributor Covenant 2.1, private vulnerability reporting
- `tasks/` — open work (To-be), one folder per task

## Configuration
`ooat.toml` (operator preferences: ledger URL, per-tier pins, connector settings; secrets only as environment
variable names). Connector enablement is ledger state (`ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`, ADR 0010),
written by `ooat connectors enable | disable` after the operator has read the connection consequences card.
Prices and the data-class policy: `catalog/routing.json`. Dev dependencies: `requirements-dev.txt`, then
`pip install -e core -e adapters/claude-code -e adapters/codex -e adapters/anthropic-api`; run `python -m pytest`
(paths in `pytest.ini`). Tests that spend quota or credit run only with `OOAT_LIVE=1`.

## Security invariants
- No secrets in the repository.
- Ledger append-only; only `ooat-core` writes to it.
- R3 actions only with a named human approver.
- Data classes are enforced in the provider gateway, not in prompts.

## Related documentation
- `.claude/lessons.md` — gotchas
- `docs/adr/` — decisions

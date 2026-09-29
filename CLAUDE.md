# OOAT — Object-Oriented Agent Team (open-source framework)

## What this is
Open-source, vendor-neutral framework that decides per task whether a team of AI agents is worth its cost
(Topology Gate T0–T5), then runs work as typed capability contracts with a ledger and human-in-the-loop gates.
As-is overview: `docs/description.md`. Normative design: `spec/ooat-specification.md` (draft v0.1).
Non-technical rationale: `spec/manifesto.md`.

## Documentation and task isolation
- `docs/` = As-is state, safe to read any time. Must match the code; fix docs immediately on mismatch.
- `docs/adr/` = decisions taken (D1–D11 and later). Read before changing architecture.
- `spec/` = normative specification. Changes to it are design decisions — ask the owner first.
- `tasks/` = To-be work. DO NOT read broadly. Open only the folder of the task you are working on.
- No changelog or plans in `docs/`; history lives in git.
- Global rules: `~/.claude/CLAUDE.md` (Karpathy guidelines, security, orchestration).

## Critical project rules
- Language (D3): spec, schemas, code, docs, commits in English. Tasks/free text may be in the user's language;
  event types, reason codes and schema keys always English.
- Current phase: **F0 Foundation**. Do not build F1+ runtime features before F0 deliverables exist.
- Simplicity over completeness: a measured small catalog beats a large untested one (spec §13).
- Only `ooat-core` writes to the ledger; ledger is append-only (no UPDATE/DELETE).
- Secrets (API keys, subscription sessions) live only in the provider gateway — never in catalog, artifacts,
  fixtures, evals or docs.
- Provider manifests: unknown values stay `null`, never guessed. Never work around provider terms.
- Irreversible (R3) actions always require a named human approver — no code path may bypass this.
- `cost_card.observed` is written only by the runtime from the ledger, never by hand.
- No public repo, remote, package publish (PyPI/npm) without the owner. Name OOAT (ADR 0006), licence Apache 2.0 (ADR 0002), governance ADR 0007.
- Stack: Python 3.12+ (FastAPI, Pydantic v2, SQLite→Postgres), TypeScript dashboard, JSON Schema 2020-12.

## Known Entities & Gotchas
See `.claude/lessons.md`.

## Team
| Role | Scope in this project |
|---|---|
| `lead-dev` | Spec changes, JSON Schema design, Topology Gate/economics, architecture decisions (ADR) |
| `python-dev` | `core/`, `sdk/` (Python), `adapters/`, `ooat-cli`, eval runner |
| `db-dev` | Ledger/event store schema, SQLite and Postgres views |
| `frontend-dev` | `dashboard/` and TypeScript SDK |
| `ux-designer` | Dashboard views (HIL queue, rating queue, exceptions), one-click HIL UX |
| `reviewer` | Code/security review, especially gateway, data-class enforcement, sandbox |
| `junior-dev` | Catalog stubs, template copying, simple doc edits |
| `translator` | Czech UI strings / `i18n` fields |

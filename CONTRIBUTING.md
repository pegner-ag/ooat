# Contributing to OOAT

Thank you for helping. OOAT is at specification stage, so the most valuable contributions right now are
critique of the specification, catalog proposals and adapters. Failure reports and counter-evidence are as
welcome as code.

## Before you start

- Read the [manifesto](spec/manifesto.md) and the relevant section of the [specification](spec/ooat-specification.md).
- Check the [decision records](docs/adr/). Proposals that reopen a decision should say which ADR and why.
- For anything larger than a small fix, open an issue first so we can agree on the approach.

## Ways to contribute

| Contribution | Where | Must include |
|---|---|---|
| Spec critique or correction | issue "Spec feedback" | section number, the problem, a proposed wording |
| Capability proposal | issue "Capability proposal", then a PR to `catalog/` | id `cap.<domain>.<verb>_<object>`, one-line summary, lowest `impl` that works (`deterministic` < `decision` < `llm`), acceptance criteria |
| Catalog pack | PR to `catalog/` | capability cards valid against `spec/schemas/`, an eval set of 10–20 cases with at least 3 where abstaining is correct; packs start in `shadow` |
| Provider adapter | issue "Adapter proposal", then a PR to `adapters/` | manifest with a `jurisdiction` block (unknown values `null`, never guessed), sources for every stated fact |
| Calibration task | PR to `evals/` | anonymised task with goal, checkable acceptance, value class, data class; no personal or client data |

## Development

```sh
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
python -m pip install -r requirements-dev.txt
python -m pytest
```

All tests must pass. Schema changes need a valid example and at least one invalid case in `spec/tests/`.

## Rules

- English for code, schemas, docs and commit messages; event types, reason codes and keys are always English.
- Never commit secrets, API keys, subscription sessions, personal data or client documents.
- `cost_card.observed` is written only by the runtime; pull requests that edit it by hand are rejected.
- Keep changes focused: one topic per pull request.

## Review and merging

Every pull request gets an automated first review by Claude (Opus 5.5). That review is advisory; a human
maintainer decides and merges (see [ADR 0007](docs/adr/0007-governance.md)). Catalog and routing changes also
go through evals and a shadow run before activation.

By contributing you agree that your contribution is licensed under the [Apache License 2.0](LICENSE) and that
you follow the [Code of Conduct](CODE_OF_CONDUCT.md).

# OOA Spec v0.1

Normative part of OOAT: JSON Schemas (draft 2020-12) plus the semantics in `ooat-specification.md`.

## Schemas (`schemas/`)

| Schema | Describes | Spec section |
|---|---|---|
| `common.schema.json` | Shared IDs (`tsk_`, `ctr_`, `agt_`, `evt_` + 26-char ULID, `art_<ulid>@v<n>`), tiers, data classes, outcomes, permissions, budget, gates | 2, 5, 6, 9 |
| `capability.schema.json` | Capability card: contract, acceptance, model policy, cost card | 5 |
| `family.schema.json` | Role family: shared rules, permissions, budget, gates | 5 |
| `role.schema.json` | Role card: capability bundle, artifact types, permissions, budget, gates, A2A fields | 5 |
| `provider.schema.json` | Provider adapter manifest incl. plan, data policy and `jurisdiction` block | 6, 9 |
| `routing.schema.json` | Tier → adapters, dated price list, data-class policy, display currency | 6, 9 |
| `contract.schema.json` | Contract instance for one task (body of `CONTRACT_ISSUED`) | 2, 8 |
| `event.schema.json` | Ledger event envelope and one body schema per event type | 7, 9 |

`$id` values use the placeholder host `ooat.invalid` until the project name and domain are settled (Q10).

## Rules the schemas enforce beyond types

- Deterministic capabilities have no model policy; `decision` capabilities run only on the `decision` tier and vice versa.
- Adapters allowing `client_confidential`, `personal` or `special_category` must declare `training_on_inputs: false`.
- Subscription adapters need a `plan`; manual relay cannot be `operator_confirmed` or metered.
- Abstentions require `reason` (≤ 300 chars), `missing` and `confidence`.
- `HIL_REQUEST`: 2–3 options, recommendation, default on silence, deadline; an R3 request must offer a do-not-act option (`acts: false`).
- Objections reference an artifact version and use a closed `reason_code` list.
- Only agents emit `CLAIM`/`RESULT`/`OBJECTION`; only humans emit `HIL_RESPONSE`, `TASK_RATED`, `DEFECT_FOUND`, `ADAPTER_ACKNOWLEDGED`.
- Timestamps are UTC (`Z`).

## Rules left to the catalog linter or runtime

JSON Schema cannot express these; they are checked in code:

- `recommended` and `default_on_silence` name an existing option; for R3 the default is the `acts: false` option.
- Inheritance: roles only narrow family permissions, gates accumulate, depth ≤ 3.
- `cost_card.observed` changes only through `ooat-core`.
- Referenced capabilities, roles, adapters and schema paths exist.

## Examples and tests

`examples/valid/<schema>.<name>.json` are valid documents, most taken from the specification text. Spec text
abbreviates IDs (`evt_01J9ZQ8M2K`); the examples use full 26-character ULIDs. Invalid cases are single
mutations of valid examples in `tests/test_schemas.py`.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
```

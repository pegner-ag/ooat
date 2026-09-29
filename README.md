# OOAT — Object-Oriented Agent Team

[![Tests](https://github.com/pegner-ag/ooat/actions/workflows/tests.yml/badge.svg)](https://github.com/pegner-ag/ooat/actions/workflows/tests.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

![OOAT: agent teams that earn their cost](docs/assets/social-preview.png)

Agent teams that earn their cost. OOAT asks, before any work starts, whether a team of AI agents is worth
its cost or whether one agent will do — and when a team is justified, builds it from specialists defined by
contracts, prices and tested success rates, with every step recorded in a ledger and every irreversible
action waiting for a named human.

- Why: [`spec/manifesto.md`](spec/manifesto.md)
- How: [`spec/ooat-specification.md`](spec/ooat-specification.md) (draft v0.1)
- Decisions: [`docs/adr/`](docs/adr/)

## Status

Specification stage (draft v0.1): JSON Schemas and the starter catalog taxonomy exist; no runnable runtime yet.
Decision records are in `docs/adr/`.

## Repository layout

| Folder | Content |
|---|---|
| `spec/` | Specification, manifesto; JSON Schemas of the OOA Spec |
| `catalog/` | Capability, role, family, routing and provider cards (JSON) |
| `core/` | `ooat-core` reference runtime (Python) |
| `sdk/` | Python and TypeScript SDKs |
| `adapters/` | Provider, store and notifier adapters |
| `dashboard/` | Web dashboard (TypeScript) |
| `evals/` | Capability eval sets and calibration tasks |
| `docs/` | Current-state documentation and decision records |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), the [Code of Conduct](CODE_OF_CONDUCT.md) and the [security policy](SECURITY.md).

## Licence

Apache License 2.0 — see [`LICENSE`](LICENSE).

# OOAT — Object-Oriented Agent Team

Agent teams that earn their cost. OOAT asks, before any work starts, whether a team of AI agents is worth
its cost or whether one agent will do — and when a team is justified, builds it from specialists defined by
contracts, prices and tested success rates, with every step recorded in a ledger and every irreversible
action waiting for a named human.

- Why: [`spec/manifesto.md`](spec/manifesto.md)
- How: [`spec/ooat-specification.md`](spec/ooat-specification.md) (draft v0.1)
- Decisions: [`docs/adr/`](docs/adr/)

## Status

Specification stage (draft v0.1). No runnable code yet.

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

## Licence

Apache License 2.0 — see [`LICENSE`](LICENSE).

# ooat-core

## Purpose
Reference runtime of OOAT. Currently: identifiers, OOA Spec validation, the append-only ledger, artifact
storage, state projections and the provider gateway core (connector contract, registry, routing, budgets,
metering). Concrete connectors, Gate, workers and API are not implemented yet.

## Key components
- `ids.py` — `new_id(prefix)`, ULIDs, `parse_artifact_ref()`
- `validation.py` — `validate(entity, document)` against `spec/schemas/`
- `ledger.py` — `Ledger`: the only write path; validates events (schema, finite numbers, 64-bit token counts, known artifact references, HIL options incl. R3 default "do not act", responses to existing requests) and staged artifact records, writes an event and its artifacts atomically
- `backends/` — `LedgerBackend` protocol and `open_backend(url)`; implemented: SQLite with schema version in `PRAGMA user_version` (ADR 0008)
- `blobs.py` — SHA-256 addressed bodies, fsynced before use, safe under concurrent writes; tampering detected on read, repaired on re-put
- `artifacts.py` — `ArtifactStore.stage()` / `.read()`; artifacts exist only through their producing event
- `state.py` — `task_state()`, `contract_state()` computed from events
- `connectors/` — connector contract (`ModelConnector`, `ModelRequest`, `ModelResponse`, `ConnectorError`),
  `jurisdiction_fingerprint()`; `registry.py` discovers installed connectors (entry points `ooat.connectors`)
  and lists broken ones without using them
- `config.py` — `load_config()` for `ooat.toml`: ledger URL, per-tier pins, connector settings; no secrets,
  no enablement
- `secrets.py` — `SecretResolver`: values from named environment variables, `redact()`
- `routing.py` — `RoutingPolicy` from `routing.json`: dated prices, optional tier allow-list, data-class policy
- `gateway.py` — `Gateway.estimate()` / `.call()`: data-class guard, acknowledgement and automation rules from
  the ledger, quota cool-down, pins, cheapest connector, contract budget, cost record with `estimated_usd`;
  passes the routed model to the connector in `ModelRequest.model`
- `connectors/cli.py` — `run_cli()`: vendor CLI with the prompt on stdin, in an empty temporary directory,
  typed `UNAVAILABLE` / `TIMEOUT` failures
- `connectors/conformance.py` — `check_connector()`: the contract every connector package tests

Schemas are read from `spec/schemas/` in the repository, so the package works from a checkout or an editable
install (`pip install -e core`); packaging the schemas into the wheel is release work.

## Architectural patterns
Event sourcing: state is derived from the ledger, never stored. Ledger rules live in `Ledger`, SQL dialect
in a backend; every backend passes `tests/test_ledger.py`.

## Public API
`Ledger.open(url)`, `new_event()`, `ArtifactStore`, `BlobStore`, `task_state()`, `contract_state()`, `validate()`,
`Gateway`, `Registry.discover()`, `load_config()`, `load_routing()`, `SecretResolver`.

# ooat-core

## Purpose
Reference runtime of OOAT. Currently: identifiers, OOA Spec validation, the append-only ledger, artifact
storage, state projections and the provider gateway core (connector contract, registry, routing, budgets,
metering, typed decisions with a text-model fallback), the connector contract used by the packages in
`adapters/`, the `ooat connectors` operator command, the Topology Gate for T0–T2, and the task runtime with
its `ooat task` / `ooat hil` commands (one worker, acceptance checks, closing, rating). The REST API and teams
(T3+) are not implemented yet.

## Key components
- `ids.py` — `new_id(prefix)`, ULIDs, `parse_artifact_ref()`
- `validation.py` — `validate(entity, document)` against `spec/schemas/`
- `ledger.py` — `Ledger`: the only write path; validates events (schema, finite numbers, 64-bit token counts, known artifact references, HIL options incl. R3 default "do not act", responses to existing requests) and staged artifact records, writes an event and its artifacts atomically
- `backends/` — `LedgerBackend` protocol and `open_backend(url)`; implemented: SQLite with schema version in `PRAGMA user_version` (ADR 0008)
- `blobs.py` — SHA-256 addressed bodies, fsynced before use, safe under concurrent writes; tampering detected on read, repaired on re-put
- `artifacts.py` — `ArtifactStore.stage()` / `.read()`; artifacts exist only through their producing event
- `state.py` — `task_state()`, `contract_state()` computed from events
- `connectors/` — connector contract: kind `model` (`ModelConnector`, `ModelRequest`, `ModelResponse`) and kind
  `decision` (`DecisionConnector`, `DecisionRequest`, `DecisionQuestion`, `DecisionAnswer`, `DecisionResponse`),
  `ConnectorError`, `jurisdiction_fingerprint()`; `registry.py` discovers installed connectors (entry points
  `ooat.connectors`), lists them by kind, and lists broken ones (bad manifest, unknown kind, a decision tier on
  the wrong kind) without using them
- `decisions.py` — `check_questions()`, `with_reversed_choices()` (order-swap check), `checked_answers()`,
  `merged_answers()`, and the text-model fallback `fallback_prompt()` / `parse_fallback()` (ADR 0011)
- `pii.py` — `scan()` / `raised_class()`: local pre-scan for e-mail, phone, IBAN, card and birth numbers; the
  gateway runs it before routing and raises the data class to `personal` on a hit, never lowering it
- `thresholds.py` — `threshold()`: θ per decision point, engine and model version from TASK_RATED verdicts on
  decision records (interim 0.8 for a decision connector, 1 for the text fallback; floor 0.8 until 20 ratings)
- `gate.py` — `Gate.run(task)`: step A as one decision batch (A1 per criterion, A4, A5, A7, A10), data class
  raised by pre-scan and by any A10 answer, estimate of worker plus acceptance checks, then T0 (closed: no permitted
  route, not worth its value, unclear after 3 clarifications, over budget after 3 budget questions, unanswered
  for 48 h, cancelled), a clarifying `HIL_REQUEST` (clarify / run as it is / do not run) or a budget one (raise /
  narrow the scope / do not run), or T2. `task_facts()` and `gated_data_class()` read the task and the
  operator's answers back for the runtime
- `config.py` — `load_config()` for `ooat.toml`: ledger URL, per-tier pins, connector settings, and the
  `[policy]` limits `blocked_countries` and `personal_data_regions` (ADR 0012); no secrets, no enablement
- `credentials_env.py` — `SecretResolver`: values from named environment variables, `redact()`
- `routing.py` — `RoutingPolicy` from `routing.json`: dated prices, optional tier allow-list, data-class policy
- `gateway.py` — `Gateway.estimate()` / `.call()`: data-class guard (the operator's responsibility stands in
  for a processing agreement, a region and no training; `[policy]` blocks countries and limits personal data to
  regions), acknowledgement and automation rules from the ledger, quota cool-down, pins, cheapest connector, contract budget, cost record with `estimated_usd`;
  passes the routed model to the connector in `ModelRequest.model`. `Gateway.estimate_decision()` /
  `.decide()`: the same rules for decision connectors; every choice is asked twice with reversed options,
  answers are checked before use, and when no decision connector can answer, the `economy` text tier answers the
  same questions (`DecisionResult.engine` and `.model` say which, `.fallback_from` why)
- `connectors/cli.py` — `run_cli()`: vendor CLI with the prompt on stdin, in an empty temporary directory,
  typed `UNAVAILABLE` / `TIMEOUT` failures
- `connectors/conformance.py` — `check_connector()`: the contract every connector package tests;
  `jurisdiction_stale()` in `connectors/__init__.py` is the spec §9 rule 2 check shared by gateway and CLI
- `connector_admin.py` — `connector_statuses()`, `consequences_card()`, `acknowledge()`, `disable()`: operator
  actions; state changes are `ADAPTER_ACKNOWLEDGED` / `ADAPTER_DISABLED` events by a named human;
  `acknowledgements()` is the connector state the gateway routes on. `acknowledge(..., responsibility, today)`
  records the operator's responsibility for client or personal data, which may carry those classes beyond the
  manifest when training is off; `responsibility_in_force()` (12 months) and `blocked_by_policy()` serve the
  gateway, the card and the listing
- `catalog.py` — `load_card()`, `routing_path()`: cards and `routing.json` read from the repository's
  `catalog/`
- `worker.py` — `run_worker()`: the T2 worker; one workhorse call with the family rules, the role, the task,
  untrusted attachments (whole up to 100,000 characters each, else a preview) and the feedback of a failed attempt; returns a Markdown
  document, an abstention in the fixed JSON form, or `invalid`
- `acceptance.py` — `check_output()`: deterministic checks, one decision per criterion (θ for point
  `acceptance`), the critic for unsure answers and for "met" on untrusted input; GATE_PASSED / GATE_FAILED events
- `runtime.py` — `Runtime.submit()` / `.run()` / `.expire()`: intake with untrusted attachments, the Gate, one
  contract (`cap.general.complete_task`, `role.general.worker`), two attempts, RESULT / ABSTAIN, TASK_CLOSED with
  the four cost parts; applies a declared default when a question's deadline has passed. A provider failure
  (quota, outage, timeout) pauses the task as RUNNING without using up an attempt; the next `run` resumes it from
  the ledger, and `runnable()` lists the tasks that can move without the operator. A used-up contract budget
  (capped by the role) asks the operator to raise it or stop; a usable earlier document is kept as PARTIAL
- `rating.py` — `task_decisions()`, `checked_verdict()`, `rate()`: TASK_RATED with the operator's verdict per
  decision; typing the answer the decision gave counts as confirmed, a choice correction must be one of its options
- `operator_cli.py` — the `ooat` command: `ooat connectors list | show | enable | disable`
- `task_cli.py` — `ooat task submit | run [--all] | show | rate` and `ooat hil list | answer`

Schemas are read from `spec/schemas/` in the repository, so the package works from a checkout or an editable
install (`pip install -e core`); packaging the schemas into the wheel is release work.

## Architectural patterns
Event sourcing: state is derived from the ledger, never stored. Ledger rules live in `Ledger`, SQL dialect
in a backend; every backend passes `tests/test_ledger.py`.

## Public API
`Ledger.open(url)`, `new_event()`, `ArtifactStore`, `BlobStore`, `task_state()`, `contract_state()`, `validate()`,
`Gateway`, `Gate`, `Runtime`, `rate()`, `task_facts()`, `threshold()`, `Registry.discover()`, `load_config()`,
`load_routing()`, `SecretResolver`, `connector_admin`, the `ooat` console script.

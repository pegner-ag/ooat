# Provider gateway — design

**Epic:** f1-skeleton · **Sub-project:** 03 · **Status:** design for owner review
**Spec:** `spec/ooat-specification.md` §6 (providers, routing, economics), §9 (data protection, connection
consequences); ADR 0005 (first adapters), ADR 0008 (pluggable backends), ADR 0010 (estimates, connector state)

## 1. Intent

What the owner asked for (2026-10-01):

- The installing operator chooses which connectors to use: one subscription or several tools.
- The mechanism is open: new connectors for new tools (API, MCP, CLI, …) are added without changing the core.
- One mechanism serves **models** now and **agent tools** (MCP servers, REST, CLI) later.
- When several connectors serve the same tier, the gateway picks automatically by expected cost; the operator
  can pin one connector per tier.
- Cost is predicted before work starts, recorded next to the actual cost, and can stop a task that is too
  expensive.

Success: a worker asks for a `workhorse` completion; the gateway picks a permitted connector, refuses what data
policy or budget forbids, calls it, and returns text plus a cost record that includes the estimate made before
the call. Adding a connector is `pip install <package>` plus an acknowledgement, never a core change.

## 2. Scope

In scope (sub-project 03, three plans):

| Plan | Content |
|---|---|
| 03a | Connector contract, registry, operator config, secrets, gateway (estimate, routing, budgets, quota, data-class guard, metering, typed errors), fake connector, ADR 0010 schema changes |
| 03b | Model connectors as separate packages: Claude Code CLI, Codex CLI, Anthropic API |
| 03c | `ooat connectors list / enable / disable` with the connection consequences card |

Out of scope: tool connectors (MCP, REST, CLI tools for agents), Jev/decision tier connector (F2 decision
points), the `ooat init` wizard (01c composes 03c), task-level pre-start estimate (04, see §9), calibration view (F2).

## 3. Architecture

```
ooat-core
  connectors/          contract (ModelConnector), Detection, registry (entry points "ooat.connectors")
  gateway/             Gateway: estimate(), call(); routing, budgets, quota, data-class guard, metering
  config.py            ooat.toml (operator preferences; no secrets, no enablement)
  secrets.py           SecretResolver: env var names from config -> values, redaction helper
adapters/              one distribution per connector; install only what you use
  claude-code/         ooat-adapter-claude-code   subscription_cli   claude -p --output-format json
  codex/               ooat-adapter-codex         subscription_cli   codex exec --json
  anthropic-api/       ooat-adapter-anthropic-api api                HTTPS Messages API
```

- `ooat-core` contains no vendor names (spec §6). Connectors register themselves through the Python entry-point
  group `ooat.connectors`; the registry discovers what is installed.
- The gateway is the only component that sees secrets and the only one that calls connectors.
- The gateway appends `QUOTA_WARNING` and `BUDGET_WARNING` events itself. For a model call it returns the
  cost record; the caller attaches it to the event it appends (`RESULT`, `ABSTAIN`, …), including after a
  failed call that consumed tokens.

## 4. Connector contract

```python
class ModelConnector(Protocol):
    kind: Literal["model"]          # "tool" connectors follow later with their own contract
    manifest: dict                  # valid against spec/schemas/provider.schema.json
    def detect(self) -> Detection: ...   # offline: CLI on PATH and its version, or key variable present
    def complete(self, request: ModelRequest, secrets: SecretResolver) -> ModelResponse: ...

@dataclass(frozen=True)
class Detection:
    available: bool
    detail: str                     # e.g. "claude 2.1.286 on PATH", "ANTHROPIC_API_KEY not set"

@dataclass(frozen=True)
class ModelRequest:
    tier: str                       # local | economy | workhorse | frontier
    prompt: str
    data_class: str                 # required: the gateway never guesses a class (spec §9)
    system: str = ""
    max_output_tokens: int = 4000
    expected_output_tokens: int | None = None   # from the capability cost card, for estimates
    task: str | None = None
    contract: str | None = None
    timeout_s: float = 600

@dataclass(frozen=True)
class ModelResponse:
    text: str
    model: str                      # concrete model id reported by the provider
    tokens_in: int | None
    tokens_cached: int | None
    tokens_out: int | None
    quota_units: float | None       # subscription units consumed, when reported
    metering: Literal["exact", "reported", "estimated"]
```

- A connector raises `ConnectorError(code, message)` with `code` in `QUOTA_EXHAUSTED`, `UNAVAILABLE`
  (CLI missing, not logged in, endpoint unreachable), `API_ERROR` (the provider answered with an error) or
  `TIMEOUT`; `QUOTA_EXHAUSTED` may carry `resets_at`. These are the `RESULT.error.code` values of the event
  schema; `UNAVAILABLE` is added to it in 03a (ADR 0010).
- In sub-project 03 CLI connectors run without tools (pure completion). Agent tools arrive with the runtime (04).
- The registry validates each manifest at discovery; an invalid or duplicate connector is listed as broken and
  never used, and does not stop the others from loading.

## 5. Connector state and operator config

**Enablement lives in the ledger** (ADR 0010), so it is audited and cannot be faked by editing a file:

- `ADAPTER_ACKNOWLEDGED` — operator, manifest version, allowed data classes, `automation_confirmed`
  (the operator checked that the plan's terms allow unattended use) and `jurisdiction_sha256` (fingerprint of
  the manifest's `jurisdiction` block at acknowledgement).
- `ADAPTER_DISABLED` — operator, reason. Written only by a human (`actor.kind = hil`), never by the gateway;
  a connector with a broken manifest is simply unusable and listed as broken.
- A connector is **enabled** when its latest state event is `ADAPTER_ACKNOWLEDGED`.
- Staleness, exactly as spec §9 rule 2: when the current `jurisdiction` block no longer matches the
  acknowledged fingerprint, or `jurisdiction.verified_on` is `null` or older than 12 months, the connector
  stays enabled but `personal` and `special_category` are refused until the operator acknowledges again.
  Other manifest changes need no new acknowledgement; the current manifest's own `allowed_data_classes`
  always applies.

**Preferences live in `ooat.toml`** (read with `tomllib`; no secrets, no enablement):

```toml
[ledger]
url = "sqlite:///C:/ooat/ledger.sqlite"

[routing.pin]                       # optional: always use this connector for the tier
workhorse = "prv.anthropic.subscription_cli"

[connectors."prv.anthropic.subscription_cli"]
plan_fee_usd_month = 100

[connectors."prv.anthropic.api"]
secret_env = "ANTHROPIC_API_KEY"    # the name of the variable, never its value
```

Prices come from `catalog/routing.json` (`prices`, with `valid_from` and `source`), as the spec requires.

## 6. Estimate, routing and metering

**Estimate** (`Gateway.estimate(request) -> Estimate`, no provider call; also used by routing and budgets):

- `tokens_in = ceil(len(system + prompt) / 4)`; `tokens_out = expected_output_tokens or max_output_tokens`.
- API connectors: tokens × the model's price from `routing.json`.
- Subscription connectors: shadow price `p_call = p_unit · u_call · (1 + [w > 0.8])` (spec §6). Until
  usable units per month are measured, the prior is the API list price of the same model, and `w` is
  unknown and treated as 0.
- `Estimate` = connector, tokens, `usd`, `basis` (`prior` until observed costs exist, then `observed`).

**Routing** for a request:

1. Candidates: discovered, enabled (ledger) connectors whose manifest maps the tier and that are not in a
   quota cool-down.
2. Data-class guard: `data_class` must be allowed by the manifest, by the acknowledgement and by the
   routing data-class policy; `special_category` is always refused in F1 (no verified redaction yet).
3. Automation: a connector is used only if its manifest's `automation_permitted` is not `not_permitted`
   **and** the acknowledgement has `automation_confirmed: true`. An acknowledgement never overrides a manifest
   that forbids automation (no way around provider terms). In F1 every gateway call is unattended, so
   `subscription_manual` connectors are never routed; human-relayed use comes with HIL in 05.
4. A pin for the tier selects that connector; if the pin fails steps 1–3, the call fails with the reason
   (no silent fallback).
5. Otherwise the lowest estimated cost wins; ties prefer `subscription_cli`, then `local`, then `api`
   (already-paid capacity first, ADR 0005).

Deferred steps of the spec §6 routing policy: keeping only connectors on which the capability passed its eval
for the tier (needs evals: 02 and 06), and running a T3+ critic on a different vendor than the author (T3, F2).

**Budget**: if the request names a contract, remaining budget = `max_usd` of its `CONTRACT_ISSUED` minus the
`usd` of its events. The call is refused with `BUDGET` when the estimate exceeds the remainder; a
`BUDGET_WARNING` (level `contract`) is appended once when spending passes 80 %. A failed call that reached the
provider (`API_ERROR`, `TIMEOUT`) is charged its estimate (basis `estimated`), so a contract that keeps failing
is stopped by its budget; a call that never ran (`UNAVAILABLE`, `QUOTA_EXHAUSTED`) costs nothing. The
budget counts the costs callers have appended to the ledger, so every caller appends the returned cost record.
The monthly system budget and the task budget (spec §6 budgets table) are enforced by the Gate in 04.

**Quota**: `QUOTA_EXHAUSTED` from a connector puts it in cool-down until `resets_at`, else
`plan.quota_window_hours`, else 1 hour, and appends `QUOTA_WARNING` (utilisation 1.0, `window_resets_at`).
After a restart the cool-down is rebuilt from the latest `QUOTA_WARNING`.

**Metering** — the cost record returned with every response or failure:

| Key | Source |
|---|---|
| `adapter`, `tier` | routing decision |
| `tokens_in`, `tokens_cached`, `tokens_out`, `quota_units` | connector response |
| `usd` | API: exact tokens × price; subscription: shadow price of the reported usage |
| `basis` | `exact` (API usage), `shadow` (subscription), `estimated` (no usage reported) |
| `price_ver` | `routing.json` version |
| `estimated_usd` | the estimate made before the call (ADR 0010) |

## 7. Errors

| Gateway error | Contract outcome |
|---|---|
| `NOT_PERMITTED` (data class, automation, no acknowledged connector for the tier) | `ABSTAIN_NOT_PERMITTED` |
| `BUDGET` | `ABSTAIN_BUDGET` |
| `QUOTA_EXHAUSTED`, `UNAVAILABLE`, `API_ERROR`, `TIMEOUT` | `FAILED` with that error code |

Every error carries the routing trace (candidates and why each was excluded), so the caller can explain it.

## 8. Secrets and data protection

- Config holds variable names only; `SecretResolver` reads values at call time and is passed to `complete`.
- Every message leaving the gateway (errors, warnings) is redacted of all resolved secret values; tests assert
  a secret never appears in responses, errors or ledger events.
- CLI connectors use the CLI's own login; the gateway passes no credentials to them.

## 9. Pre-start estimate for tasks (scope of sub-project 04, recorded here)

Before a task runs, the Gate sums contract estimates (from capability cost cards and `Gateway.estimate`) per
candidate topology and records them in `TOPOLOGY_DECIDED`. If the estimate exceeds the task budget, the task
does not start: a `HIL_REQUEST` offers "raise budget to X / narrow scope / do not run". If the estimate exceeds
the task value, the Gate chooses T0. After `TASK_CLOSED`, estimate and actual are compared; the calibration view
(F2) uses the `estimated_usd` series that the gateway records from the first call on.

## 10. Testing

- Unit tests run against a fake connector injected into the registry; no network.
- Connector parsing tests use recorded CLI and API outputs (fixtures without secrets).
- Live tests that spend quota run only with `OOAT_LIVE=1`; CI never sets it.
- Conformance: every connector package runs the shared connector tests (manifest valid, `detect` offline,
  errors typed, no secret in output).

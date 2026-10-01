# Gateway Core (03a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the provider gateway core: the connector contract and registry, operator config and secrets, the routing policy, cost estimates recorded next to actual cost, and `Gateway.estimate()` / `Gateway.call()` with data-class, acknowledgement, automation, quota and budget rules — tested against a fake connector, no network.

**Architecture:** Connectors are installed packages found through the entry-point group `ooat.connectors`; `ooat-core` holds only the contract. Connector enablement is ledger state (`ADAPTER_ACKNOWLEDGED` / `ADAPTER_DISABLED`), operator preferences live in `ooat.toml`, prices and data-class policy in `routing.json`. The gateway filters connectors, picks a pin or the cheapest (subscription first on ties), checks the contract budget, calls the connector, and returns a cost record with the pre-call estimate.

**Tech Stack:** Python 3.12+ (`tomllib`, `importlib.metadata`), `jsonschema`, `sqlite3`, pytest.

**Spec:** `tasks/f1-skeleton/task-03-provider-gateway/design.md` (sections 3–8, 10); ADR 0010; spec `spec/ooat-specification.md` §6, §9.

## Global Constraints

- Python `>=3.12`; no new runtime dependencies (`tomllib` and `importlib.metadata` are standard library).
- `ooat-core` contains no vendor names; test fakes use `prv.fake.*` and `prv.premium.*`.
- Connector error codes are the event schema's `RESULT.error.code` values: `QUOTA_EXHAUSTED`, `UNAVAILABLE`, `API_ERROR`, `TIMEOUT`.
- `ModelRequest.data_class` is required; the gateway never guesses a class. `special_category` is always refused in F1.
- A connector is used only if acknowledged in the ledger, its manifest's `automation_permitted` is not `not_permitted`, and the acknowledgement has `automation_confirmed: true`.
- Config never holds secrets or enablement; secrets come from environment variables named in config.
- No secret value may appear in a gateway response, error, trace or ledger event.
- Code, comments, docs and commit messages in English.

## Review Focus

1. A pinned connector in quota cool-down must report `QUOTA_EXHAUSTED` (retry later), not `NOT_PERMITTED`, and must not fall back silently — `test_pinned_connector_in_cool_down_reports_quota_not_permission` (Task 6).
2. A data class the routing policy marks `allowed: false` must be refused even when manifest and acknowledgement allow it — `test_data_class_forbidden_by_the_routing_policy_is_refused` (Task 6).
3. A new manifest version with an unchanged jurisdiction must keep working for personal data without a new acknowledgement (spec §9 rule 2 is about jurisdiction only) — `test_new_manifest_version_with_the_same_jurisdiction_needs_no_new_acknowledgement` (Task 6).
4. A contract budget exactly equal to the estimate must allow the call — `test_budget_exactly_equal_to_the_estimate_is_allowed` (Task 6).
5. A ledger created before this plan must gain the estimate column on open, without losing events — `test_version_1_ledger_is_migrated_to_record_estimates` (Task 5).

---

## File Structure

```
spec/schemas/event.schema.json, provider.schema.json, routing.schema.json   ADR 0010 changes (Task 1)
spec/examples/valid/event.adapter_disabled.json                               new example (Task 1)
core/src/ooat_core/
  connectors/__init__.py      contract: Detection, ModelRequest, ModelResponse, ConnectorError, ModelConnector,
                              jurisdiction_fingerprint (Task 2)
  connectors/registry.py      Registry, BrokenConnector, discovery via entry points (Task 2)
  config.py                   Config, parse_config, load_config (Task 3)
  secrets.py                  SecretResolver (Task 3)
  routing.py                  Price, RoutingPolicy, load_routing (Task 4)
  backends/sqlite.py          estimated_usd column, schema version 2 with migration (Task 5)
  ledger.py                   estimated_usd in the cost mapping (Task 5)
  gateway.py                  Gateway, GatewayError, Estimate, GatewayResult (Task 6)
core/tests/
  connector_fakes.py          FakeConnector, fake_manifest, quota_error (Task 2)
  test_connectors.py  test_config.py  test_routing.py  test_gateway.py
```

How to apply a "replace" step: the old text occurs exactly once in the file; replace it with the new text. Files may have CRLF line endings on Windows — match the text, not the line endings.

---

### Task 1: Schema changes of ADR 0010

**Files:**
- Modify: `spec/schemas/event.schema.json`, `spec/schemas/provider.schema.json`, `spec/schemas/routing.schema.json`
- Modify: `spec/examples/valid/provider.anthropic_subscription_cli.json`, `spec/examples/valid/provider.typesafe_api.json`, `spec/examples/valid/event.adapter_acknowledged.json`, `spec/examples/valid/event.result_partial.json`
- Create: `spec/examples/valid/event.adapter_disabled.json`
- Test: `spec/tests/test_schemas.py`

**Interfaces:**
- Consumes: nothing.
- Produces: event `cost.estimated_usd`; `ADAPTER_ACKNOWLEDGED` body with required `automation_confirmed` (bool) and `jurisdiction_sha256` (64 hex); event type `ADAPTER_DISABLED` (body `adapter`, `operator`, `reason`; `task: null`; human actor only); `RESULT.error.code` `UNAVAILABLE`; provider `automation_permitted` ∈ `permitted | not_permitted | unknown`; routing `tiers` optional.

- [ ] **Step 1: Write the failing tests (examples and invalid cases)**

Create `spec/examples/valid/event.adapter_disabled.json`:

```json
{
  "id": "evt_01J9ZQ61A1K3M5N7P9Q1R3S5T7",
  "ts": "2026-10-01T09:00:00Z",
  "task": null,
  "actor": {
    "kind": "hil",
    "id": "operator"
  },
  "type": "ADAPTER_DISABLED",
  "refs": [],
  "body": {
    "adapter": "prv.typesafe.api",
    "operator": "Operator",
    "reason": "Early access ended."
  }
}
```

In `spec/examples/valid/provider.anthropic_subscription_cli.json`, replace:

```json
"automation_permitted": "operator_confirmed"
```

with:

```json
"automation_permitted": "unknown"
```

In `spec/examples/valid/provider.typesafe_api.json`, replace:

```json
"automation_permitted": "operator_confirmed"
```

with:

```json
"automation_permitted": "unknown"
```

In `spec/examples/valid/event.adapter_acknowledged.json`, replace:

```json
    "operator": "Operator"
```

with:

```json
    "operator": "Operator",
    "automation_confirmed": true,
    "jurisdiction_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
```

In `spec/examples/valid/event.result_partial.json`, replace:

```json
"usd": 0.42, "basis": "shadow"}
```

with:

```json
"usd": 0.42, "basis": "shadow", "estimated_usd": 0.5}
```

In `spec/tests/test_schemas.py`, replace:

```python
    ("event_gate_rule_out_of_range", "event", "event.topology_decided.json",
     _set(["body", "rules_applied"], ["A11"])),
]
```

with:

```python
    ("event_gate_rule_out_of_range", "event", "event.topology_decided.json",
     _set(["body", "rules_applied"], ["A11"])),
    # ADR 0010
    ("provider_operator_confirmed_is_no_longer_a_term", "provider", "provider.typesafe_api.json",
     _set(["automation_permitted"], "operator_confirmed")),
    ("event_acknowledgement_without_automation_answer", "event", "event.adapter_acknowledged.json",
     _delete(["body", "automation_confirmed"])),
    ("event_acknowledgement_with_bad_fingerprint", "event", "event.adapter_acknowledged.json",
     _set(["body", "jurisdiction_sha256"], "not-a-digest")),
    ("event_adapter_disabled_by_system", "event", "event.adapter_disabled.json",
     _set(["actor"], {"kind": "system", "id": "ooat-gateway"})),
    ("event_adapter_disabled_without_reason", "event", "event.adapter_disabled.json",
     _delete(["body", "reason"])),
    ("event_negative_estimate", "event", "event.result_partial.json",
     _set(["cost", "estimated_usd"], -1)),
]
```


- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest spec/tests -q`
Expected: FAIL — `test_valid_example` for `event.adapter_acknowledged.json`, `event.adapter_disabled.json`, `event.result_partial.json`, and `test_invalid_example[provider_operator_confirmed_is_no_longer_a_term]` (still valid under the old schema).

- [ ] **Step 3: Change the schemas**

In `spec/schemas/event.schema.json`, replace:

```json
"description": "Task id. ADAPTER_ACKNOWLEDGED is not tied to a task and uses null.",
```

with:

```json
"description": "Task id. ADAPTER_ACKNOWLEDGED and ADAPTER_DISABLED are not tied to a task and use null.",
```

In `spec/schemas/event.schema.json`, replace:

```json
"if": {"properties": {"type": {"not": {"const": "ADAPTER_ACKNOWLEDGED"}}}},
```

with:

```json
"if": {"properties": {"type": {"not": {"enum": ["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"]}}}},
```

In `spec/schemas/event.schema.json`, replace:

```json
"description": "Only a human answers, rates, reports defects or acknowledges adapters.",
```

with:

```json
"description": "Only a human answers, rates, reports defects, acknowledges or disables adapters.",
```

In `spec/schemas/event.schema.json`, replace:

```json
"if": {"properties": {"type": {"enum": ["HIL_RESPONSE", "TASK_RATED", "DEFECT_FOUND", "ADAPTER_ACKNOWLEDGED"]}}},
```

with:

```json
"if": {"properties": {"type": {"enum": ["HIL_RESPONSE", "TASK_RATED", "DEFECT_FOUND", "ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"]}}},
```

In `spec/schemas/event.schema.json`, replace:

```json
{"if": {"properties": {"type": {"const": "ADAPTER_ACKNOWLEDGED"}}}, "then": {"properties": {"body": {"$ref": "#/$defs/body_adapter_acknowledged"}}}}
```

with:

```json
{"if": {"properties": {"type": {"const": "ADAPTER_ACKNOWLEDGED"}}}, "then": {"properties": {"body": {"$ref": "#/$defs/body_adapter_acknowledged"}}}},
    {"if": {"properties": {"type": {"const": "ADAPTER_DISABLED"}}}, "then": {"properties": {"body": {"$ref": "#/$defs/body_adapter_disabled"}}}}
```

In `spec/schemas/event.schema.json`, replace:

```json
"TASK_CLOSED", "TASK_RATED", "DEFECT_FOUND", "ADAPTER_ACKNOWLEDGED"
```

with:

```json
"TASK_CLOSED", "TASK_RATED", "DEFECT_FOUND", "ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"
```

In `spec/schemas/event.schema.json`, replace:

```json
"price_ver": {"type": "string", "minLength": 1}
```

with:

```json
"price_ver": {"type": "string", "minLength": 1},
        "estimated_usd": {"description": "Estimate made by the gateway before the call (ADR 0010).", "$ref": "common.schema.json#/$defs/usd"}
```

In `spec/schemas/event.schema.json`, replace:

```json
"code": {"enum": ["TOOL_ERROR", "TIMEOUT", "API_ERROR", "QUOTA_EXHAUSTED", "INVALID_OUTPUT"]},
```

with:

```json
"code": {"enum": ["TOOL_ERROR", "TIMEOUT", "API_ERROR", "QUOTA_EXHAUSTED", "INVALID_OUTPUT", "UNAVAILABLE"]},
```

In `spec/schemas/event.schema.json`, replace:

```json
"required": ["adapter", "manifest_version", "allowed_data_classes", "operator"],
```

with:

```json
"required": ["adapter", "manifest_version", "allowed_data_classes", "operator", "automation_confirmed", "jurisdiction_sha256"],
```

In `spec/schemas/event.schema.json`, replace:

```json
"operator": {"description": "Name of the acknowledging operator.", "$ref": "#/$defs/text"}
      }
    }
```

with:

```json
"operator": {"description": "Name of the acknowledging operator.", "$ref": "#/$defs/text"},
        "automation_confirmed": {"description": "The operator checked that the plan terms allow unattended use (ADR 0010).", "type": "boolean"},
        "jurisdiction_sha256": {"description": "Fingerprint of the acknowledged jurisdiction block (ADR 0010).", "type": "string", "pattern": "^[0-9a-f]{64}$"}
      }
    },
    "body_adapter_disabled": {
      "type": "object",
      "required": ["adapter", "operator", "reason"],
      "additionalProperties": false,
      "properties": {
        "adapter": {"$ref": "common.schema.json#/$defs/provider_id"},
        "operator": {"$ref": "#/$defs/text"},
        "reason": {"$ref": "#/$defs/text"}
      }
    }
```

In `spec/schemas/provider.schema.json`, replace:

```json
"automation_permitted": {"enum": ["operator_confirmed", "not_permitted", "unknown"]},
```

with:

```json
"automation_permitted": {"description": "Published provider terms for unattended use; the operator confirmation lives in ADAPTER_ACKNOWLEDGED (ADR 0010).", "enum": ["permitted", "not_permitted", "unknown"]},
```

In `spec/schemas/provider.schema.json`, replace:

```json
"automation_permitted": {"not": {"const": "operator_confirmed"}}
```

with:

```json
"automation_permitted": {"not": {"const": "permitted"}}
```

In `spec/schemas/routing.schema.json`, replace:

```json
"required": ["version", "tiers", "prices", "data_class_policy"],
```

with:

```json
"required": ["version", "prices", "data_class_policy"],
```

In `spec/schemas/routing.schema.json`, replace:

```json
"description": "Tier -> candidate adapters. The router filters and picks by expected cost; order is not a priority.",
```

with:

```json
"description": "Optional allow-list: tier -> adapters that may serve it. A tier without an entry accepts every acknowledged connector whose manifest maps it (ADR 0010). Order is not a priority.",
```


- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q`
Expected: PASS (all suites)

- [ ] **Step 5: Commit**

```bash
git add spec/schemas/event.schema.json spec/schemas/provider.schema.json spec/schemas/routing.schema.json spec/examples/valid spec/tests/test_schemas.py
git commit -m "spec: ADR 0010 schema changes (estimates, connector state, UNAVAILABLE, automation terms)"
```

---

### Task 2: Connector contract and registry

**Files:**
- Create: `core/src/ooat_core/connectors/__init__.py`, `core/src/ooat_core/connectors/registry.py`
- Create: `core/tests/connector_fakes.py`
- Test: `core/tests/test_connectors.py`

**Interfaces:**
- Consumes: `validate("provider", manifest)`, `SpecValidationError` (`ooat_core.validation`).
- Produces:
  - `ENTRY_POINT_GROUP = "ooat.connectors"`, `ERROR_CODES`.
  - `Detection(available: bool, detail: str)`.
  - `ModelRequest(tier: str, prompt: str, data_class: str, system: str = "", max_output_tokens: int = 4000, expected_output_tokens: int | None = None, task: str | None = None, contract: str | None = None, timeout_s: float = 600)`.
  - `ModelResponse(text, model, tokens_in, tokens_cached, tokens_out, quota_units, metering)`.
  - `ConnectorError(code, message, resets_at=None)` with `.code`, `.message`, `.resets_at`; `ValueError` for an unknown code.
  - `ModelConnector` protocol: `kind`, `manifest`, `detect()`, `complete(request, secrets)`; `SecretSource` protocol with `get(connector_id) -> str`.
  - `jurisdiction_fingerprint(manifest: dict) -> str` (SHA-256 hex of canonical JSON).
  - `Registry(connectors=(), broken=())` with `.ids() -> list[str]`, `.get(id)`, `.broken: list[BrokenConnector]`, `Registry.discover()`; `BrokenConnector(name, error)`.
  - Test helpers in `connector_fakes.py`: `FakeConnector(manifest=None, text=..., usage=(in, cached, out), error=None, secret_seen=None)` with `.calls`, `fake_manifest(connector_id="prv.fake.api", access="api", tiers=None, version="1.0.0", allowed=(...), automation="unknown", jurisdiction=None)`, `JURISDICTION`, `quota_error(resets_at=None)`.

- [ ] **Step 1: Write the failing test**

`core/tests/connector_fakes.py`:

```python
"""A configurable fake model connector for gateway tests (no network, no secrets)."""

from ooat_core.connectors import ConnectorError, Detection, ModelResponse

JURISDICTION = {
    "vendor_entity": "Fake Vendor Ltd", "vendor_country": "IE", "host_entity": "Fake Vendor Ltd",
    "processing_regions": ["eu"], "eu_region_available": True, "model_origin_country": "IE",
    "training_on_inputs": False, "retention": "30 days", "zero_retention_available": False,
    "transfer_notes": None, "source_urls": ["https://fake.invalid/privacy"], "verified_on": "2026-09-01",
}


def fake_manifest(connector_id="prv.fake.api", access="api", tiers=None, version="1.0.0",
                  allowed=("public", "internal", "client_confidential", "personal"),
                  automation="unknown", jurisdiction=None):
    manifest = {
        "id": connector_id, "version": version, "vendor": connector_id.split(".")[1], "access": access,
        "tiers": tiers or {"workhorse": "fake-model"}, "metering": "exact" if access == "api" else "reported",
        "automation_permitted": automation, "concurrency": 1,
        "data_policy": {"training_on_inputs": False, "retention_days": 30, "allowed_data_classes": list(allowed)},
        "jurisdiction": dict(jurisdiction or JURISDICTION),
    }
    if access.startswith("subscription"):
        manifest["plan"] = {"fee_usd_month": 100, "quota_window_hours": 5, "units": "token_equivalent"}
    if access == "subscription_cli":
        manifest["runner"] = "fake-cli"
    return manifest


class FakeConnector:
    kind = "model"

    def __init__(self, manifest=None, text="Hotovo.", usage=(1000, 0, 200), error=None, secret_seen=None):
        self.manifest = manifest or fake_manifest()
        self.text, self.usage, self.error = text, usage, error
        self.calls = []
        self.secret_seen = secret_seen  # connector id whose secret is requested on each call

    def detect(self):
        return Detection(True, "fake connector")

    def complete(self, request, secrets):
        self.calls.append(request)
        if self.secret_seen:
            secrets.get(self.secret_seen)
        if self.error:
            raise self.error
        tokens_in, tokens_cached, tokens_out = self.usage
        model = self.manifest["tiers"][request.tier]
        metering = "exact" if self.manifest["access"] == "api" else "reported"
        return ModelResponse(self.text, model, tokens_in, tokens_cached, tokens_out, None, metering)


def quota_error(resets_at=None):
    return ConnectorError("QUOTA_EXHAUSTED", "usage limit reached", resets_at=resets_at)
```

`core/tests/test_connectors.py`:

```python
import pytest
from connector_fakes import FakeConnector, fake_manifest

from ooat_core.connectors import ConnectorError, jurisdiction_fingerprint, registry
from ooat_core.connectors.registry import Registry


def test_valid_connector_is_registered():
    reg = Registry([FakeConnector()])
    assert reg.ids() == ["prv.fake.api"]
    assert reg.get("prv.fake.api").kind == "model"
    assert reg.broken == []


def test_invalid_manifest_is_listed_as_broken_and_not_used():
    manifest = fake_manifest()
    del manifest["jurisdiction"]
    reg = Registry([FakeConnector(manifest), FakeConnector(fake_manifest("prv.other.api"))])
    assert reg.ids() == ["prv.other.api"]
    assert reg.broken[0].name == "prv.fake.api" and "jurisdiction" in reg.broken[0].error


def test_unsupported_kind_is_broken():
    tool = FakeConnector()
    tool.kind = "tool"
    reg = Registry([tool])
    assert reg.ids() == [] and "kind" in reg.broken[0].error


def test_duplicate_ids_make_both_unusable():
    reg = Registry([FakeConnector(), FakeConnector()])
    assert reg.ids() == []
    assert reg.broken[0].name == "prv.fake.api"


class EntryPoint:
    def __init__(self, name, factory):
        self.name, self._factory = name, factory

    def load(self):
        return self._factory


def test_discover_loads_entry_points_and_survives_a_broken_plugin(monkeypatch):
    def failing():
        raise ImportError("missing dependency")

    monkeypatch.setattr(registry, "entry_points", lambda group: [
        EntryPoint("fake", FakeConnector), EntryPoint("bad", lambda: failing())])
    reg = Registry.discover()
    assert reg.ids() == ["prv.fake.api"]
    assert [b.name for b in reg.broken] == ["bad"]


def test_jurisdiction_fingerprint_ignores_key_order_and_detects_changes():
    manifest = fake_manifest()
    reordered = dict(manifest, jurisdiction=dict(reversed(list(manifest["jurisdiction"].items()))))
    changed = dict(manifest, jurisdiction=dict(manifest["jurisdiction"], processing_regions=["us"]))
    assert jurisdiction_fingerprint(manifest) == jurisdiction_fingerprint(reordered)
    assert jurisdiction_fingerprint(manifest) != jurisdiction_fingerprint(changed)


def test_connector_error_codes_are_the_schema_codes():
    assert ConnectorError("UNAVAILABLE", "claude not on PATH").code == "UNAVAILABLE"
    with pytest.raises(ValueError):
        ConnectorError("PROVIDER_ERROR", "x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_connectors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.connectors'`

- [ ] **Step 3: Implement** — `core/src/ooat_core/connectors/__init__.py`:

```python
"""Connector contract (gateway design §4).

Connectors are installed packages registered under the entry-point group "ooat.connectors"; ooat-core knows no
vendor names. Model connectors are served now; tool connectors (MCP, REST, CLI tools) follow with their own contract.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Protocol

ENTRY_POINT_GROUP = "ooat.connectors"
# The RESULT.error.code values a connector may raise (event schema, ADR 0010).
ERROR_CODES = frozenset({"QUOTA_EXHAUSTED", "UNAVAILABLE", "API_ERROR", "TIMEOUT"})


@dataclass(frozen=True)
class Detection:
    available: bool
    detail: str


@dataclass(frozen=True)
class ModelRequest:
    tier: str
    prompt: str
    data_class: str  # required: the gateway never guesses a class (spec §9)
    system: str = ""
    max_output_tokens: int = 4000
    expected_output_tokens: int | None = None
    task: str | None = None
    contract: str | None = None
    timeout_s: float = 600


@dataclass(frozen=True)
class ModelResponse:
    text: str
    model: str
    tokens_in: int | None
    tokens_cached: int | None
    tokens_out: int | None
    quota_units: float | None
    metering: Literal["exact", "reported", "estimated"]


class ConnectorError(Exception):
    def __init__(self, code: str, message: str, resets_at: str | None = None):
        if code not in ERROR_CODES:
            raise ValueError(f"unknown connector error code: {code}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.resets_at = resets_at  # ISO 8601 UTC, for QUOTA_EXHAUSTED when the provider says


class SecretSource(Protocol):
    def get(self, connector_id: str) -> str: ...


class ModelConnector(Protocol):
    kind: Literal["model"]
    manifest: dict  # valid against spec/schemas/provider.schema.json

    def detect(self) -> Detection: ...

    def complete(self, request: ModelRequest, secrets: SecretSource) -> ModelResponse: ...


def jurisdiction_fingerprint(manifest: dict) -> str:
    """SHA-256 of the canonical JSON of the manifest's jurisdiction block (ADR 0010)."""
    canonical = json.dumps(manifest["jurisdiction"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

`core/src/ooat_core/connectors/registry.py`:

```python
"""Discovery of installed connectors (entry-point group "ooat.connectors").

A connector that fails to load, has an invalid manifest, an unsupported kind or a duplicate id is listed as
broken and never used; it does not stop the other connectors from loading.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points

from ..validation import SpecValidationError, validate
from . import ENTRY_POINT_GROUP, ModelConnector


@dataclass(frozen=True)
class BrokenConnector:
    name: str
    error: str


class Registry:
    def __init__(self, connectors: Iterable[ModelConnector] = (), broken: Iterable[BrokenConnector] = ()):
        self.broken: list[BrokenConnector] = list(broken)
        found: dict[str, list[ModelConnector]] = {}
        for connector in connectors:
            connector_id = self._check(connector)
            if connector_id is not None:
                found.setdefault(connector_id, []).append(connector)
        self._connectors: dict[str, ModelConnector] = {}
        for connector_id, same_id in found.items():
            if len(same_id) > 1:  # which one is meant is unknowable, so neither is used
                self.broken.append(BrokenConnector(connector_id, f"{len(same_id)} connectors share this id"))
            else:
                self._connectors[connector_id] = same_id[0]

    def _check(self, connector) -> str | None:
        manifest = getattr(connector, "manifest", None)
        name = manifest.get("id", repr(connector)) if isinstance(manifest, dict) else repr(connector)
        if getattr(connector, "kind", None) != "model":
            self.broken.append(BrokenConnector(name, f"unsupported connector kind: {getattr(connector, 'kind', None)!r}"))
            return None
        try:
            validate("provider", manifest)
        except (SpecValidationError, TypeError) as error:
            self.broken.append(BrokenConnector(name, str(error)))
            return None
        return manifest["id"]

    @classmethod
    def discover(cls) -> "Registry":
        connectors, broken = [], []
        for entry_point in entry_points(group=ENTRY_POINT_GROUP):
            try:
                connectors.append(entry_point.load()())
            except Exception as error:  # a broken plugin must not take the gateway down
                broken.append(BrokenConnector(entry_point.name, f"{type(error).__name__}: {error}"))
        return cls(connectors, broken)

    def ids(self) -> list[str]:
        return sorted(self._connectors)

    def get(self, connector_id: str) -> ModelConnector | None:
        return self._connectors.get(connector_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/connectors core/tests/connector_fakes.py core/tests/test_connectors.py
git commit -m "core: connector contract and registry (entry points ooat.connectors)"
```

---

### Task 3: Operator config and secrets

**Files:**
- Create: `core/src/ooat_core/config.py`, `core/src/ooat_core/secrets.py`
- Test: `core/tests/test_config.py`

**Interfaces:**
- Consumes: `ConnectorError` (Task 2).
- Produces: `Config(ledger_url: str = "sqlite:///ooat-ledger.sqlite", pins: dict[str, str], connectors: dict[str, dict])`; `parse_config(data: dict) -> Config` (`ValueError` on unknown sections or settings, invalid pins, a `secret_env` that is not a variable name, `models` with unknown tiers); `load_config(path) -> Config`; `TIERS`. `SecretResolver(config, environ=os.environ)` with `.get(connector_id) -> str` (`ConnectorError("UNAVAILABLE")` when not configured or not set) and `.redact(text) -> str`; `REDACTED`. Connector settings keys: `secret_env`, `plan_fee_usd_month`, `models` (tier → model id).

- [ ] **Step 1: Write the failing test** — `core/tests/test_config.py`:

```python
import pytest

from ooat_core.config import Config, load_config, parse_config
from ooat_core.connectors import ConnectorError
from ooat_core.secrets import REDACTED, SecretResolver

EXAMPLE = """
[ledger]
url = "sqlite:///C:/ooat/ledger.sqlite"

[routing.pin]
workhorse = "prv.anthropic.subscription_cli"

[connectors."prv.anthropic.subscription_cli"]
plan_fee_usd_month = 100
models = { workhorse = "claude-sonnet-5-5" }

[connectors."prv.anthropic.api"]
secret_env = "ANTHROPIC_API_KEY"
"""


def test_example_config_loads(tmp_path):
    path = tmp_path / "ooat.toml"
    path.write_text(EXAMPLE, encoding="utf-8")
    config = load_config(path)
    assert config.ledger_url == "sqlite:///C:/ooat/ledger.sqlite"
    assert config.pins == {"workhorse": "prv.anthropic.subscription_cli"}
    assert config.connectors["prv.anthropic.api"] == {"secret_env": "ANTHROPIC_API_KEY"}
    assert config.connectors["prv.anthropic.subscription_cli"]["models"] == {"workhorse": "claude-sonnet-5-5"}


def test_empty_config_has_defaults():
    assert parse_config({}) == Config()


@pytest.mark.parametrize("data, message", [
    ({"secrets": {}}, "unknown config sections"),
    ({"routing": {"pin": {"turbo": "prv.a.api"}}}, "invalid pin"),
    ({"connectors": {"prv.a.api": {"api_key": "sk-123"}}}, "unknown settings"),
    ({"connectors": {"prv.a.api": {"secret_env": "sk-ant-abc123"}}}, "environment variable"),
    ({"connectors": {"prv.a.api": {"models": {"turbo": "m"}}}}, "models"),
    ({"connectors": {"anthropic": {}}}, "invalid connector id"),
])
def test_config_rejects_unknown_keys_and_pasted_secrets(data, message):
    with pytest.raises(ValueError, match=message):
        parse_config(data)


def test_secret_is_read_from_the_named_variable():
    secrets = SecretResolver(parse_config({"connectors": {"prv.a.api": {"secret_env": "A_KEY"}}}), {"A_KEY": "s3cr3t"})
    assert secrets.get("prv.a.api") == "s3cr3t"


@pytest.mark.parametrize("config, environ", [
    ({}, {}),
    ({"connectors": {"prv.a.api": {"secret_env": "A_KEY"}}}, {}),
])
def test_missing_secret_makes_the_connector_unavailable(config, environ):
    with pytest.raises(ConnectorError) as info:
        SecretResolver(parse_config(config), environ).get("prv.a.api")
    assert info.value.code == "UNAVAILABLE"


def test_redact_removes_every_configured_secret():
    config = parse_config({"connectors": {"prv.a.api": {"secret_env": "A_KEY"}, "prv.b.api": {"secret_env": "B_KEY"}}})
    secrets = SecretResolver(config, {"A_KEY": "sk-long-secret", "B_KEY": "sk-long"})
    assert secrets.redact("failed with sk-long-secret and sk-long") == f"failed with {REDACTED} and {REDACTED}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.config'`

- [ ] **Step 3: Implement** — `core/src/ooat_core/config.py`:

```python
"""Operator preferences from ooat.toml (gateway design §5).

The file never holds secrets or connector enablement: secrets are named by environment variable, enablement is
ledger state (ADR 0010). Unknown keys are rejected so a pasted API key cannot hide in the file.
"""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

TIERS = frozenset({"local", "economy", "workhorse", "frontier"})
_PROVIDER_ID = re.compile(r"^prv\.[a-z][a-z0-9_-]*\.[a-z][a-z0-9_]*$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_CONNECTOR_KEYS = frozenset({"secret_env", "plan_fee_usd_month", "models"})


@dataclass(frozen=True)
class Config:
    ledger_url: str = "sqlite:///ooat-ledger.sqlite"
    pins: dict[str, str] = field(default_factory=dict)  # tier -> connector id
    connectors: dict[str, dict] = field(default_factory=dict)  # connector id -> settings


def parse_config(data: dict) -> Config:
    unknown = set(data) - {"ledger", "routing", "connectors"}
    if unknown:
        raise ValueError(f"unknown config sections: {sorted(unknown)}")
    ledger_url = data.get("ledger", {}).get("url", Config.ledger_url)
    pins = data.get("routing", {}).get("pin", {})
    for tier, connector_id in pins.items():
        if tier not in TIERS or not _PROVIDER_ID.match(connector_id):
            raise ValueError(f"invalid pin {tier} = {connector_id}")
    connectors = data.get("connectors", {})
    for connector_id, settings in connectors.items():
        if not _PROVIDER_ID.match(connector_id):
            raise ValueError(f"invalid connector id: {connector_id}")
        extra = set(settings) - _CONNECTOR_KEYS
        if extra:
            raise ValueError(f"{connector_id}: unknown settings {sorted(extra)} (secrets belong in environment variables)")
        if "secret_env" in settings and not _ENV_NAME.match(settings["secret_env"]):
            raise ValueError(f"{connector_id}: secret_env must name an environment variable, not hold a value")
        if not set(settings.get("models", {})) <= TIERS:
            raise ValueError(f"{connector_id}: models must map tiers to model ids")
    return Config(ledger_url=ledger_url, pins=dict(pins), connectors={k: dict(v) for k, v in connectors.items()})


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as file:
        return parse_config(tomllib.load(file))
```

`core/src/ooat_core/secrets.py`:

```python
"""Secret resolution for connectors (gateway design §8).

Config names environment variables; values are read only when a connector asks, and every message leaving the
gateway is passed through redact().
"""

import os
from collections.abc import Mapping

from .config import Config
from .connectors import ConnectorError

REDACTED = "[REDACTED]"


class SecretResolver:
    def __init__(self, config: Config, environ: Mapping[str, str] = os.environ):
        self._config = config
        self._environ = environ

    def get(self, connector_id: str) -> str:
        name = self._config.connectors.get(connector_id, {}).get("secret_env")
        if not name:
            raise ConnectorError("UNAVAILABLE", f"{connector_id}: no secret_env configured")
        value = self._environ.get(name)
        if not value:
            raise ConnectorError("UNAVAILABLE", f"{connector_id}: environment variable {name} is not set")
        return value

    def redact(self, text: str) -> str:
        """Replace every configured secret value in text; longest first so overlapping values leave nothing."""
        values = {self._environ.get(s.get("secret_env", ""), "") for s in self._config.connectors.values()}
        for value in sorted((v for v in values if v), key=len, reverse=True):
            text = text.replace(value, REDACTED)
        return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/config.py core/src/ooat_core/secrets.py core/tests/test_config.py
git commit -m "core: operator config (ooat.toml) and secret resolution"
```

---

### Task 4: Routing policy

**Files:**
- Create: `core/src/ooat_core/routing.py`
- Test: `core/tests/test_routing.py`

**Interfaces:**
- Consumes: `validate("routing", document)` (routing `tiers` optional after Task 1).
- Produces: `Price(usd_per_mtok_in, usd_per_mtok_cached, usd_per_mtok_out)` with `.usd(tokens_in, tokens_cached, tokens_out) -> float`; `RoutingPolicy(document)` with `.version`, `.data_class_policy`, `.allows(tier, connector_id) -> bool`, `.price(connector_id, model, on: date) -> Price | None` (own price first, else any price of the same model; missing cached price = input price); `load_routing(path) -> RoutingPolicy`.

- [ ] **Step 1: Write the failing test** — `core/tests/test_routing.py`:

```python
from datetime import date

import pytest

from ooat_core.routing import Price, RoutingPolicy
from ooat_core.validation import SpecValidationError

POLICY = {
    "public": {"allowed": True}, "internal": {"allowed": True},
    "client_confidential": {"allowed": True, "require_no_training": True},
    "personal": {"allowed": True, "require_no_training": True, "require_known_region": True},
    "special_category": {"allowed": True, "require_verified_redaction": True},
}


def price(adapter, model, usd_in, usd_out, valid_from="2026-01-01", **extra):
    return {"adapter": adapter, "model": model, "usd_per_mtok_in": usd_in, "usd_per_mtok_out": usd_out,
            "valid_from": valid_from, "source": "https://fake.invalid/pricing", **extra}


def policy(prices=(), tiers=None):
    document = {"version": "0.1.0", "prices": list(prices), "data_class_policy": POLICY}
    if tiers is not None:
        document["tiers"] = tiers
    return RoutingPolicy(document)


def test_own_price_wins_over_another_adapters_price_for_the_same_model():
    routing = policy([price("prv.fake.api", "m", 3, 15), price("prv.other.api", "m", 1, 5)])
    assert routing.price("prv.fake.api", "m", date(2026, 10, 1)) == Price(3, 3, 15)


def test_subscription_prior_is_the_api_price_of_the_same_model():
    routing = policy([price("prv.fake.api", "m", 3, 15, usd_per_mtok_cached=0.3)])
    assert routing.price("prv.fake.subscription_cli", "m", date(2026, 10, 1)) == Price(3, 0.3, 15)


def test_prices_outside_their_validity_are_ignored():
    routing = policy([price("prv.fake.api", "m", 3, 15, valid_from="2026-11-01"),
                      price("prv.fake.api", "m", 9, 9, valid_until="2026-09-30")])
    assert routing.price("prv.fake.api", "m", date(2026, 10, 1)) is None


def test_price_usd():
    assert Price(3, 0.3, 15).usd(1_000_000, 1_000_000, 100_000) == pytest.approx(3 + 0.3 + 1.5)


def test_tier_allow_list_applies_only_to_listed_tiers():
    routing = policy(tiers={"frontier": ["prv.fake.api"]})
    assert routing.allows("frontier", "prv.fake.api")
    assert not routing.allows("frontier", "prv.other.api")
    assert routing.allows("workhorse", "prv.other.api")


def test_invalid_routing_document_is_rejected():
    with pytest.raises(SpecValidationError):
        RoutingPolicy({"version": "0.1.0", "prices": []})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_routing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.routing'`

- [ ] **Step 3: Implement** — `core/src/ooat_core/routing.py`:

```python
"""Routing policy from catalog/routing.json: dated prices, optional tier allow-list, data-class policy (spec §6, §9)."""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .validation import validate


@dataclass(frozen=True)
class Price:
    usd_per_mtok_in: float
    usd_per_mtok_cached: float
    usd_per_mtok_out: float

    def usd(self, tokens_in: int, tokens_cached: int, tokens_out: int) -> float:
        return (tokens_in * self.usd_per_mtok_in + tokens_cached * self.usd_per_mtok_cached
                + tokens_out * self.usd_per_mtok_out) / 1_000_000


class RoutingPolicy:
    def __init__(self, document: dict):
        validate("routing", document)
        self.version: str = document["version"]
        self._tiers: dict[str, list[str]] = document.get("tiers", {})
        self._prices: list[dict] = document["prices"]
        self.data_class_policy: dict[str, dict] = document["data_class_policy"]

    def allows(self, tier: str, connector_id: str) -> bool:
        """A tier listed in routing.json is an allow-list; an unlisted tier accepts any connector (ADR 0010)."""
        return tier not in self._tiers or connector_id in self._tiers[tier]

    def price(self, connector_id: str, model: str, on: date) -> Price | None:
        """The connector's own price for the model, else any listed price for the same model.

        The fallback is the spec §6 prior for subscriptions: the API list price of an equivalent model.
        """
        valid = [p for p in self._prices if p["model"] == model
                 and date.fromisoformat(p["valid_from"]) <= on
                 and ("valid_until" not in p or on <= date.fromisoformat(p["valid_until"]))]
        own = [p for p in valid if p["adapter"] == connector_id]
        chosen = (own or valid or [None])[0]
        if chosen is None:
            return None
        return Price(chosen["usd_per_mtok_in"], chosen.get("usd_per_mtok_cached", chosen["usd_per_mtok_in"]),
                     chosen["usd_per_mtok_out"])


def load_routing(path: str | Path) -> RoutingPolicy:
    return RoutingPolicy(json.loads(Path(path).read_text(encoding="utf-8")))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/routing.py core/tests/test_routing.py
git commit -m "core: routing policy with dated prices, tier allow-list and data-class policy"
```

---

### Task 5: Ledger records the estimate

**Files:**
- Modify: `core/src/ooat_core/backends/sqlite.py`, `core/src/ooat_core/ledger.py`
- Test: `core/tests/test_sqlite_backend.py`

**Interfaces:**
- Consumes: Task 1 schema (`cost.estimated_usd`).
- Produces: `SCHEMA_VERSION = 2`; event column `estimated_usd`; a version-1 SQLite ledger gains the column on open; `Ledger.events()` returns `cost.estimated_usd` when stored.

- [ ] **Step 1: Write the failing tests** — append to `core/tests/test_sqlite_backend.py`:

```python
def test_version_1_ledger_is_migrated_to_record_estimates(tmp_path):
    from ooat_core.backends import sqlite as sqlite_backend

    path = tmp_path / "ledger.sqlite"
    raw = sqlite3.connect(path)
    version_1_ddl = sqlite_backend._DDL.replace("  price_ver     TEXT,\n  estimated_usd REAL\n", "  price_ver     TEXT\n")
    assert version_1_ddl != sqlite_backend._DDL
    raw.executescript(version_1_ddl)
    raw.execute("PRAGMA user_version = 1")
    raw.commit()
    assert "estimated_usd" not in [row[1] for row in raw.execute("PRAGMA table_info(event)")]
    raw.close()
    SqliteBackend(path).close()
    raw = sqlite3.connect(path)
    assert "estimated_usd" in [row[1] for row in raw.execute("PRAGMA table_info(event)")]
    assert raw.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 2
    raw.close()


def test_estimate_survives_the_round_trip():
    from ooat_core.ids import new_id
    from ooat_core.ledger import Ledger, new_event

    ledger = Ledger.open("sqlite:///:memory:")
    event = new_event("RESULT", task=new_id("tsk"), contract=new_id("ctr"),
                      actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
                      body={"outcome": "FAILED", "error": {"code": "UNAVAILABLE", "message": "x"}},
                      cost={"usd": 0.0, "basis": "estimated", "estimated_usd": 0.25})
    ledger.append(event)
    assert ledger.events()[0]["cost"]["estimated_usd"] == 0.25
    ledger.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/test_sqlite_backend.py -v`
Expected: FAIL — `test_version_1_ledger_is_migrated_to_record_estimates` (`SCHEMA_VERSION == 2` is false) and `test_estimate_survives_the_round_trip` (`KeyError: 'estimated_usd'`).

- [ ] **Step 3: Implement**

In `core/src/ooat_core/backends/sqlite.py`, replace:

```python
SCHEMA_VERSION = 1
```

with:

```python
SCHEMA_VERSION = 2
```

In `core/src/ooat_core/backends/sqlite.py`, replace:

```python
  price_ver     TEXT
);
```

with:

```python
  price_ver     TEXT,
  estimated_usd REAL
);
```

In `core/src/ooat_core/backends/sqlite.py`, replace:

```python
        self._db.executescript(_DDL)
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
```

with:

```python
        self._db.executescript(_DDL)
        if version == 1:  # version 2 records the gateway's estimate next to the actual cost (ADR 0010)
            self._db.execute("ALTER TABLE event ADD COLUMN estimated_usd REAL")
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
```

In `core/src/ooat_core/ledger.py`, replace:

```python
    "price_ver": "price_ver",
}
```

with:

```python
    "price_ver": "price_ver", "estimated_usd": "estimated_usd",
}
```


- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/backends/sqlite.py core/src/ooat_core/ledger.py core/tests/test_sqlite_backend.py
git commit -m "core: record estimated_usd in the ledger (schema version 2 with migration)"
```

---

### Task 6: Gateway

**Files:**
- Create: `core/src/ooat_core/gateway.py`
- Test: `core/tests/test_gateway.py`

**Interfaces:**
- Consumes: `Registry`, `ModelConnector`, `ModelRequest`, `ModelResponse`, `ConnectorError`, `jurisdiction_fingerprint` (Task 2); `Config`, `parse_config`, `SecretResolver` (Task 3); `RoutingPolicy`, `Price` (Task 4); `Ledger`, `new_event`, `DATA_CLASSES` (`ooat_core.ledger`); cost round-trip (Task 5).
- Produces:
  - `Gateway(ledger, registry, routing, config=Config(), secrets=None, clock=...)` with `.estimate(request) -> Estimate` (no provider call) and `.call(request) -> GatewayResult` (`ValueError` without `request.task` or with an unknown data class).
  - `Estimate(connector, model, tokens_in, tokens_out, usd, basis)`; `GatewayResult(response, cost, estimate)`.
  - `GatewayError(code, message, trace=None, cost=None)`; codes `NOT_PERMITTED`, `BUDGET`, `QUOTA_EXHAUSTED`, `UNAVAILABLE`, `API_ERROR`, `TIMEOUT`.
  - Cost record keys: `adapter`, `tier`, `tokens_in`, `tokens_cached`, `tokens_out`, `quota_units` (when reported), `usd`, `basis` (`exact` | `shadow` | `estimated`), `price_ver`, `estimated_usd`. Failed calls: `usd: 0.0`, `basis: estimated`.
  - Ledger events written by the gateway (actor `system` / `ooat-gateway`): `QUOTA_WARNING` (utilisation 1.0, `window_resets_at`), `BUDGET_WARNING` (level `contract`, once per contract at 80 %).

- [ ] **Step 1: Write the failing test** — `core/tests/test_gateway.py`:

```python
import json
from datetime import datetime, timedelta, timezone

import pytest
from connector_fakes import JURISDICTION, FakeConnector, fake_manifest, quota_error

from ooat_core.config import parse_config
from ooat_core.connectors import ConnectorError, ModelRequest, jurisdiction_fingerprint
from ooat_core.connectors.registry import Registry
from ooat_core.gateway import Gateway, GatewayError
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger, new_event
from ooat_core.routing import RoutingPolicy
from ooat_core.secrets import SecretResolver

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
HIL = {"kind": "hil", "id": "operator"}
POLICY = {
    "public": {"allowed": True}, "internal": {"allowed": True},
    "client_confidential": {"allowed": True, "require_no_training": True},
    "personal": {"allowed": True, "require_no_training": True, "require_known_region": True},
    "special_category": {"allowed": True, "require_verified_redaction": True},
}
API = fake_manifest("prv.fake.api", "api")
SUBSCRIPTION = fake_manifest("prv.fake.subscription_cli", "subscription_cli")
EXPENSIVE = fake_manifest("prv.premium.api", "api", tiers={"workhorse": "premium-model"})


def prices():
    def price(adapter, model, usd_in, usd_out):
        return {"adapter": adapter, "model": model, "usd_per_mtok_in": usd_in, "usd_per_mtok_out": usd_out,
                "valid_from": "2026-01-01", "source": "https://fake.invalid/pricing"}
    return [price("prv.fake.api", "fake-model", 3, 15), price("prv.premium.api", "premium-model", 15, 75)]


class Setup:
    def __init__(self, *connectors, pins=None, settings=None, environ=None, tiers=None, now=NOW):
        self.now = now
        self.ledger = Ledger.open("sqlite:///:memory:")
        self.connectors = connectors
        self.config = parse_config({"routing": {"pin": pins or {}}, "connectors": settings or {}})
        routing = {"version": "0.1.0", "prices": prices(), "data_class_policy": POLICY}
        if tiers is not None:
            routing["tiers"] = tiers
        self.environ = environ or {}
        self.gateway = self.make_gateway()
        self.task = new_id("tsk")

    def make_gateway(self):  # a new gateway over the same ledger behaves like a restarted process
        return Gateway(self.ledger, Registry(self.connectors), RoutingPolicy(
            {"version": "0.1.0", "prices": prices(), "data_class_policy": POLICY}), self.config,
            SecretResolver(self.config, self.environ), clock=lambda: self.now)

    def acknowledge(self, connector, classes=("public", "internal", "client_confidential", "personal"),
                    automation=True, fingerprint=None):
        self.ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor=HIL, body={
            "adapter": connector.manifest["id"], "manifest_version": connector.manifest["version"],
            "allowed_data_classes": list(classes), "operator": "Operator", "automation_confirmed": automation,
            "jurisdiction_sha256": fingerprint or jurisdiction_fingerprint(connector.manifest)}))

    def request(self, data_class="internal", prompt="x" * 4000, **extra):
        return ModelRequest(tier="workhorse", prompt=prompt, data_class=data_class, max_output_tokens=1000,
                            task=self.task, **extra)

    def issue_contract(self, max_usd):
        contract = new_id("ctr")
        self.ledger.append(new_event("CONTRACT_ISSUED", task=self.task, contract=contract,
                                     actor={"kind": "system", "id": "ooat-core"}, body={"contract": {
            "id": contract, "task": self.task, "capability": "cap.general.complete_task",
            "capability_version": "0.1.0", "agent": new_id("agt"), "role": "role.general.worker@0.1.0",
            "goal": "Shrnout.", "inputs": [], "output_schema": "schemas/summary.v1.json",
            "budget": {"max_usd": max_usd}}}))
        return contract


def ready(*manifests, **options):
    connectors = [FakeConnector(m) for m in manifests]
    setup = Setup(*connectors, **options)
    for connector in connectors:
        setup.acknowledge(connector)
    return setup


# Routing --------------------------------------------------------------------------------------------------------

def test_cheapest_connector_wins():
    setup = ready(API, EXPENSIVE)
    assert setup.gateway.estimate(setup.request()).connector == "prv.fake.api"


def test_subscription_wins_a_tie_with_the_api_of_the_same_model():
    setup = ready(API, SUBSCRIPTION)
    assert setup.gateway.estimate(setup.request()).connector == "prv.fake.subscription_cli"


def test_pin_selects_a_more_expensive_connector():
    setup = ready(API, EXPENSIVE, pins={"workhorse": "prv.premium.api"})
    assert setup.gateway.estimate(setup.request()).connector == "prv.premium.api"


def test_pinned_connector_that_cannot_serve_fails_without_fallback():
    setup = ready(API, pins={"workhorse": "prv.premium.api"})
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request())
    assert info.value.code == "NOT_PERMITTED"


def test_unacknowledged_and_disabled_connectors_are_not_used():
    setup = Setup(FakeConnector(API))
    with pytest.raises(GatewayError, match="NOT_PERMITTED") as info:
        setup.gateway.estimate(setup.request())
    assert "not acknowledged" in info.value.trace[0]
    setup.acknowledge(setup.connectors[0])
    setup.ledger.append(new_event("ADAPTER_DISABLED", task=None, actor=HIL,
                                  body={"adapter": "prv.fake.api", "operator": "Operator", "reason": "test"}))
    with pytest.raises(GatewayError, match="NOT_PERMITTED"):
        setup.gateway.estimate(setup.request())


def test_routing_allow_list_restricts_a_listed_tier():
    setup = ready(API, EXPENSIVE)
    setup.gateway = Gateway(setup.ledger, Registry(setup.connectors), RoutingPolicy({
        "version": "0.1.0", "prices": prices(), "data_class_policy": POLICY,
        "tiers": {"workhorse": ["prv.premium.api"]}}), setup.config, clock=lambda: NOW)
    assert setup.gateway.estimate(setup.request()).connector == "prv.premium.api"


def test_connector_without_a_price_is_excluded():
    setup = ready(fake_manifest("prv.unpriced.api", "api", tiers={"workhorse": "unknown-model"}))
    with pytest.raises(GatewayError) as info:
        setup.gateway.estimate(setup.request())
    assert "no price" in info.value.trace[0]


def test_config_can_name_the_model_for_a_tier():
    manifest = fake_manifest("prv.cli.subscription_cli", "subscription_cli", tiers={"workhorse": None})
    setup = ready(manifest, settings={"prv.cli.subscription_cli": {"models": {"workhorse": "fake-model"}}})
    assert setup.gateway.estimate(setup.request()).model == "fake-model"


# Data protection and automation ----------------------------------------------------------------------------------

def test_special_category_is_always_refused():
    setup = ready(API)
    with pytest.raises(GatewayError, match="NOT_PERMITTED"):
        setup.gateway.estimate(setup.request("special_category"))


def test_data_class_must_be_acknowledged():
    setup = Setup(FakeConnector(API))
    setup.acknowledge(setup.connectors[0], classes=("public",))
    assert setup.gateway.estimate(setup.request("public")).connector == "prv.fake.api"
    with pytest.raises(GatewayError, match="NOT_PERMITTED"):
        setup.gateway.estimate(setup.request("internal"))


def test_changed_jurisdiction_blocks_personal_data_only():
    setup = Setup(FakeConnector(API))
    setup.acknowledge(setup.connectors[0], fingerprint="0" * 64)  # acknowledged a different jurisdiction
    assert setup.gateway.estimate(setup.request("client_confidential")).connector == "prv.fake.api"
    with pytest.raises(GatewayError) as info:
        setup.gateway.estimate(setup.request("personal"))
    assert "acknowledge again" in info.value.trace[0]


@pytest.mark.parametrize("verified_on", [None, "2025-09-01"])
def test_unverified_or_old_jurisdiction_blocks_personal_data(verified_on):
    manifest = fake_manifest(jurisdiction=dict(JURISDICTION, verified_on=verified_on))
    setup = ready(manifest)
    with pytest.raises(GatewayError, match="NOT_PERMITTED"):
        setup.gateway.estimate(setup.request("personal"))
    assert setup.gateway.estimate(setup.request("internal")).connector == "prv.fake.api"


def test_acknowledgement_never_overrides_provider_terms():
    setup = ready(fake_manifest(automation="not_permitted"))
    with pytest.raises(GatewayError) as info:
        setup.gateway.estimate(setup.request())
    assert "provider terms" in info.value.trace[0]


def test_unconfirmed_automation_is_not_used():
    setup = Setup(FakeConnector(API))
    setup.acknowledge(setup.connectors[0], automation=False)
    with pytest.raises(GatewayError) as info:
        setup.gateway.estimate(setup.request())
    assert "not confirmed" in info.value.trace[0]


def test_unknown_data_class_and_missing_task_are_programming_errors():
    setup = ready(API)
    with pytest.raises(ValueError):
        setup.gateway.estimate(setup.request("secret"))
    with pytest.raises(ValueError):
        setup.gateway.call(ModelRequest(tier="workhorse", prompt="x", data_class="internal"))


# Estimate and metering ----------------------------------------------------------------------------------------

def test_estimate_does_not_call_the_connector():
    setup = ready(API)
    estimate = setup.gateway.estimate(setup.request(system="y" * 400))
    assert (estimate.tokens_in, estimate.tokens_out, estimate.basis) == (1100, 1000, "prior")
    assert estimate.usd == pytest.approx((1100 * 3 + 1000 * 15) / 1_000_000)
    assert setup.connectors[0].calls == []


def test_call_returns_a_cost_record_with_the_estimate():
    setup = ready(API)
    result = setup.gateway.call(setup.request())
    assert result.response.text == "Hotovo."
    assert result.cost == {"adapter": "prv.fake.api", "tier": "workhorse", "tokens_in": 1000, "tokens_cached": 0,
                           "tokens_out": 200, "usd": pytest.approx((1000 * 3 + 200 * 15) / 1_000_000),
                           "basis": "exact", "price_ver": "0.1.0", "estimated_usd": result.estimate.usd}


def test_subscription_cost_is_a_shadow_price_and_fits_a_ledger_event():
    setup = ready(SUBSCRIPTION)
    result = setup.gateway.call(setup.request())
    assert result.cost["basis"] == "shadow"
    ref = new_id("art") + "@v1"
    event = new_event("RESULT", task=setup.task, contract=new_id("ctr"),
                      actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
                      body={"outcome": "FAILED", "error": {"code": "UNAVAILABLE", "message": "x"}},
                      refs=[], cost=result.cost)
    setup.ledger.append(event)  # validates against the event schema, including estimated_usd
    assert setup.ledger.events(types=["RESULT"])[0]["cost"]["estimated_usd"] == result.cost["estimated_usd"]
    del ref


def test_missing_usage_is_metered_as_estimated():
    connector = FakeConnector(API, usage=(None, None, None))
    setup = Setup(connector)
    setup.acknowledge(connector)
    result = setup.gateway.call(setup.request())
    assert result.cost["basis"] == "estimated"
    assert result.cost["tokens_in"] == result.estimate.tokens_in


# Budget ---------------------------------------------------------------------------------------------------------

def test_call_over_the_contract_budget_is_refused_before_the_connector_runs():
    setup = ready(API)
    contract = setup.issue_contract(max_usd=0.001)
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request(contract=contract))
    assert info.value.code == "BUDGET"
    assert setup.connectors[0].calls == []


def test_budget_warning_is_written_once_past_80_percent():
    setup = ready(API)
    contract = setup.issue_contract(max_usd=0.007)  # each call costs 0.006 USD; the estimate is tiny
    for _ in range(2):
        result = setup.gateway.call(setup.request(contract=contract, prompt="x" * 40, expected_output_tokens=1))
        setup.ledger.append(new_event("RESULT", task=setup.task, contract=contract,
                                      actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
                                      body={"outcome": "FAILED", "error": {"code": "API_ERROR", "message": "x"}},
                                      cost=result.cost))
    warnings = setup.ledger.events(types=["BUDGET_WARNING"])
    assert len(warnings) == 1 and warnings[0]["contract"] == contract


def test_unknown_contract_is_refused():
    setup = ready(API)
    with pytest.raises(GatewayError, match="NOT_PERMITTED"):
        setup.gateway.call(setup.request(contract=new_id("ctr")))


# Quota ----------------------------------------------------------------------------------------------------------

def test_exhausted_quota_cools_down_the_connector_and_routing_moves_on():
    subscription = FakeConnector(SUBSCRIPTION, error=quota_error())
    setup = Setup(subscription, FakeConnector(API))
    for connector in setup.connectors:
        setup.acknowledge(connector)
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request())
    assert info.value.code == "QUOTA_EXHAUSTED" and info.value.cost["usd"] == 0.0
    warning = setup.ledger.events(types=["QUOTA_WARNING"])[0]["body"]
    assert warning["window_resets_at"] == "2026-10-01T17:00:00Z"  # plan quota window of 5 hours
    assert setup.gateway.call(setup.request()).cost["adapter"] == "prv.fake.api"


def test_cool_down_survives_a_restart_and_ends_at_reset():
    setup = ready(SUBSCRIPTION)
    setup.connectors[0].error = quota_error(resets_at="2026-10-01T13:00:00Z")
    with pytest.raises(GatewayError):
        setup.gateway.call(setup.request())
    restarted = setup.make_gateway()
    with pytest.raises(GatewayError) as info:
        restarted.estimate(setup.request())
    assert info.value.code == "QUOTA_EXHAUSTED"
    setup.now = NOW + timedelta(hours=2)
    setup.connectors[0].error = None
    assert restarted.call(setup.request()).cost["adapter"] == "prv.fake.subscription_cli"


# Errors and secrets ---------------------------------------------------------------------------------------------

def test_connector_errors_are_typed_and_secrets_never_leave_the_gateway():
    settings = {"prv.fake.api": {"secret_env": "FAKE_KEY"}}
    environ = {"FAKE_KEY": "sk-fake-123456"}
    leaking = FakeConnector(API, error=ConnectorError("API_ERROR", "401 for key sk-fake-123456"),
                            secret_seen="prv.fake.api")
    setup = Setup(leaking, settings=settings, environ=environ)
    setup.acknowledge(leaking)
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request())
    assert info.value.code == "API_ERROR" and "sk-fake-123456" not in str(info.value)
    leaking.error = RuntimeError("crash while using sk-fake-123456")
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request())
    assert info.value.code == "API_ERROR" and "sk-fake-123456" not in str(info.value)
    assert "sk-fake-123456" not in json.dumps(setup.ledger.events())


# Review Focus -------------------------------------------------------------------------------------------------

def test_pinned_connector_in_cool_down_reports_quota_not_permission():
    setup = ready(SUBSCRIPTION, API, pins={"workhorse": "prv.fake.subscription_cli"})
    setup.connectors[0].error = quota_error()
    with pytest.raises(GatewayError):
        setup.gateway.call(setup.request())
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request())
    assert info.value.code == "QUOTA_EXHAUSTED"  # retry later; the pin is not silently bypassed


def test_data_class_forbidden_by_the_routing_policy_is_refused():
    setup = ready(API)
    setup.gateway = Gateway(setup.ledger, Registry(setup.connectors), RoutingPolicy({
        "version": "0.1.0", "prices": prices(),
        "data_class_policy": dict(POLICY, internal={"allowed": False})}), setup.config, clock=lambda: NOW)
    with pytest.raises(GatewayError) as info:
        setup.gateway.estimate(setup.request("internal"))
    assert "routing policy" in info.value.trace[0]


def test_new_manifest_version_with_the_same_jurisdiction_needs_no_new_acknowledgement():
    setup = ready(API)
    setup.connectors[0].manifest = dict(API, version="1.1.0")
    assert setup.gateway.estimate(setup.request("personal")).connector == "prv.fake.api"


def test_budget_exactly_equal_to_the_estimate_is_allowed():
    setup = ready(API)
    estimate = setup.gateway.estimate(setup.request())
    contract = setup.issue_contract(max_usd=estimate.usd)
    assert setup.gateway.call(setup.request(contract=contract)).cost["adapter"] == "prv.fake.api"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_gateway.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.gateway'`

- [ ] **Step 3: Implement** — `core/src/ooat_core/gateway.py`:

```python
"""Provider gateway: the only path from OOAT to a model (spec §6, §9; gateway design §6–§8).

Every call is estimated, routed (data class, acknowledgement, automation, quota, price), budget-checked, metered
and returned with a cost record for the caller's event. Connector state is read from the ledger (ADR 0010).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .config import Config
from .connectors import ConnectorError, ModelConnector, ModelRequest, ModelResponse, jurisdiction_fingerprint
from .connectors.registry import Registry
from .ledger import DATA_CLASSES, Ledger, new_event
from .routing import Price, RoutingPolicy
from .secrets import SecretResolver

ACTOR = {"kind": "system", "id": "ooat-gateway"}
# Already-paid capacity first when estimated costs tie (ADR 0005).
_ACCESS_RANK = {"subscription_cli": 0, "local": 1, "api": 2, "subscription_manual": 3}
_PERSONAL_OR_HIGHER = frozenset({"personal", "special_category"})
_STATE_EVENTS = ["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED", "QUOTA_WARNING"]


class GatewayError(Exception):
    """NOT_PERMITTED, BUDGET, QUOTA_EXHAUSTED, UNAVAILABLE, API_ERROR or TIMEOUT (design §7)."""

    def __init__(self, code: str, message: str, trace: list[str] | None = None, cost: dict | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.trace = trace or []  # why each connector was excluded
        self.cost = cost  # cost record for the caller's event when a connector was called


@dataclass(frozen=True)
class Estimate:
    connector: str
    model: str
    tokens_in: int
    tokens_out: int
    usd: float
    basis: str  # "prior" until calibration from observed costs exists (F2)


@dataclass(frozen=True)
class GatewayResult:
    response: ModelResponse
    cost: dict
    estimate: Estimate


@dataclass(frozen=True)
class _Candidate:
    estimate: Estimate
    connector: ModelConnector
    price: Price


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class Gateway:
    def __init__(self, ledger: Ledger, registry: Registry, routing: RoutingPolicy, config: Config = Config(),
                 secrets: SecretResolver | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._ledger = ledger
        self._registry = registry
        self._routing = routing
        self._config = config
        self._secrets = secrets or SecretResolver(config)
        self._clock = clock

    def estimate(self, request: ModelRequest) -> Estimate:
        """Expected cost of the request on the connector routing would pick; no provider call."""
        return self._route(request).estimate

    def call(self, request: ModelRequest) -> GatewayResult:
        if request.task is None:
            raise ValueError("every gateway call belongs to a task")
        candidate = self._route(request)
        self._check_budget(request, candidate.estimate)
        connector_id = candidate.connector.manifest["id"]
        try:
            response = candidate.connector.complete(request, self._secrets)
        except ConnectorError as error:
            if error.code == "QUOTA_EXHAUSTED":
                self._cool_down(request, candidate.connector, error.resets_at)
            raise GatewayError(error.code, self._secrets.redact(error.message),
                               cost=self._failure_cost(request, candidate)) from None
        except Exception as error:  # a connector bug must surface as a typed, redacted failure
            raise GatewayError("API_ERROR", self._secrets.redact(f"{connector_id}: {type(error).__name__}: {error}"),
                               cost=self._failure_cost(request, candidate)) from None
        cost = self._cost(request, candidate, response)
        self._warn_budget(request, cost["usd"])
        return GatewayResult(response, cost, candidate.estimate)

    # Routing ------------------------------------------------------------------------------------------------

    def _route(self, request: ModelRequest) -> _Candidate:
        if request.data_class not in DATA_CLASSES:
            raise ValueError(f"unknown data class: {request.data_class}")
        events = self._ledger.events(types=_STATE_EVENTS)
        acknowledgements, cooldowns = self._acknowledgements(events), self._cooldowns(events)
        candidates, trace, cooling = [], [], set()
        for connector_id in self._registry.ids():
            connector = self._registry.get(connector_id)
            reason = self._exclusion(connector, request, acknowledgements.get(connector_id), cooldowns)
            if reason is None:
                reason, candidate = self._priced(connector, request)
                if candidate is not None:
                    candidates.append(candidate)
                    continue
            if connector_id in cooldowns and reason.startswith("quota"):
                cooling.add(connector_id)
            trace.append(f"{connector_id}: {reason}")
        pin = self._config.pins.get(request.tier)
        if pin is not None:
            pinned = [c for c in candidates if c.connector.manifest["id"] == pin]
            if not pinned:
                code = "QUOTA_EXHAUSTED" if pin in cooling else "NOT_PERMITTED"
                raise GatewayError(code, f"pinned connector {pin} cannot serve this request", trace)
            return pinned[0]
        if not candidates:
            code = "QUOTA_EXHAUSTED" if cooling else "NOT_PERMITTED"
            raise GatewayError(code, f"no connector can serve tier {request.tier} for {request.data_class}", trace)
        return min(candidates, key=lambda c: (c.estimate.usd, _ACCESS_RANK[c.connector.manifest["access"]],
                                              c.connector.manifest["id"]))

    def _exclusion(self, connector, request, acknowledgement, cooldowns) -> str | None:
        manifest, connector_id, data_class = connector.manifest, connector.manifest["id"], request.data_class
        if request.tier not in manifest["tiers"] and request.tier not in self._models(connector_id):
            return f"does not serve tier {request.tier}"
        if not self._routing.allows(request.tier, connector_id):
            return f"not listed for tier {request.tier} in routing.json"
        if acknowledgement is None:
            return "not acknowledged by the operator (or disabled)"
        if data_class == "special_category":
            return "special_category needs verified redaction, not available yet"
        policy = self._routing.data_class_policy[data_class]
        if not policy["allowed"]:
            return f"{data_class} is not allowed by the routing policy"
        if data_class not in manifest["data_policy"]["allowed_data_classes"]:
            return f"{data_class} is not allowed by the manifest"
        if data_class not in acknowledgement["allowed_data_classes"]:
            return f"{data_class} was not acknowledged by the operator"
        if policy.get("require_no_training") and manifest["data_policy"]["training_on_inputs"] is not False:
            return f"{data_class} requires a connector that does not train on inputs"
        if policy.get("require_known_region") and not manifest["jurisdiction"]["processing_regions"]:
            return f"{data_class} requires a known processing region"
        if policy.get("require_verified_redaction"):
            return f"{data_class} requires verified redaction, not available yet"
        if data_class in _PERSONAL_OR_HIGHER and self._stale(manifest, acknowledgement):
            return "jurisdiction changed or not verified within 12 months; acknowledge again for personal data"
        if manifest["automation_permitted"] == "not_permitted":
            return "provider terms do not permit automated use"
        if not acknowledgement["automation_confirmed"]:
            return "automated use not confirmed by the operator"
        if connector_id in cooldowns:
            return f"quota cool-down until {cooldowns[connector_id]}"
        return None

    def _stale(self, manifest: dict, acknowledgement: dict) -> bool:
        verified_on = manifest["jurisdiction"]["verified_on"]
        if verified_on is None or (self._clock().date() - date.fromisoformat(verified_on)).days > 365:
            return True
        return jurisdiction_fingerprint(manifest) != acknowledgement["jurisdiction_sha256"]

    def _models(self, connector_id: str) -> dict:
        return self._config.connectors.get(connector_id, {}).get("models", {})

    def _priced(self, connector, request) -> tuple[str | None, _Candidate | None]:
        connector_id = connector.manifest["id"]
        model = self._models(connector_id).get(request.tier) or connector.manifest["tiers"].get(request.tier)
        if model is None:
            return f"no model configured for tier {request.tier}", None
        price = self._routing.price(connector_id, model, self._clock().date())
        if price is None:
            return f"no price for model {model} in routing.json", None
        tokens_in = math.ceil(len(request.system + request.prompt) / 4)
        tokens_out = request.expected_output_tokens or request.max_output_tokens
        estimate = Estimate(connector_id, model, tokens_in, tokens_out, price.usd(tokens_in, 0, tokens_out), "prior")
        return None, _Candidate(estimate, connector, price)

    @staticmethod
    def _acknowledgements(events: list[dict]) -> dict[str, dict]:
        state: dict[str, dict | None] = {}
        for event in events:
            if event["type"] == "ADAPTER_ACKNOWLEDGED":
                state[event["body"]["adapter"]] = event["body"]
            elif event["type"] == "ADAPTER_DISABLED":
                state[event["body"]["adapter"]] = None
        return {connector_id: body for connector_id, body in state.items() if body is not None}

    def _cooldowns(self, events: list[dict]) -> dict[str, str]:
        latest = {e["body"]["adapter"]: e["body"] for e in events if e["type"] == "QUOTA_WARNING"}
        now = self._clock()
        return {connector_id: body["window_resets_at"] for connector_id, body in latest.items()
                if body["utilisation"] >= 1 and "window_resets_at" in body and _utc(body["window_resets_at"]) > now}

    # Budget, quota, metering -------------------------------------------------------------------------------

    def _contract_budget(self, request: ModelRequest) -> tuple[float, float] | None:
        """(limit, spent) for the request's contract, from CONTRACT_ISSUED and the costs of its events."""
        if request.contract is None:
            return None
        events = self._ledger.events(task=request.task)
        issued = [e for e in events if e["type"] == "CONTRACT_ISSUED" and e.get("contract") == request.contract]
        if not issued:
            raise GatewayError("NOT_PERMITTED", f"contract {request.contract} was not issued in task {request.task}")
        spent = sum(e["cost"].get("usd", 0) for e in events if e.get("contract") == request.contract and "cost" in e)
        return issued[-1]["body"]["contract"]["budget"]["max_usd"], spent

    def _check_budget(self, request: ModelRequest, estimate: Estimate) -> None:
        budget = self._contract_budget(request)
        if budget is not None and estimate.usd > budget[0] - budget[1]:
            limit, spent = budget
            raise GatewayError("BUDGET", f"estimated {estimate.usd:.4f} USD exceeds the remaining "
                                         f"{limit - spent:.4f} USD of contract {request.contract}")

    def _warn_budget(self, request: ModelRequest, usd: float) -> None:
        budget = self._contract_budget(request)
        if budget is None:
            return
        limit, spent = budget
        warned = any(e.get("contract") == request.contract
                     for e in self._ledger.events(task=request.task, types=["BUDGET_WARNING"]))
        if not warned and spent + usd >= 0.8 * limit:
            self._ledger.append(new_event("BUDGET_WARNING", task=request.task, contract=request.contract, actor=ACTOR,
                                          body={"level": "contract", "used_usd": spent + usd, "limit_usd": limit}))

    def _cool_down(self, request: ModelRequest, connector: ModelConnector, resets_at: str | None) -> None:
        if resets_at is None:
            hours = (connector.manifest.get("plan") or {}).get("quota_window_hours") or 1
            resets_at = (self._clock() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._ledger.append(new_event("QUOTA_WARNING", task=request.task, actor=ACTOR, body={
            "adapter": connector.manifest["id"], "utilisation": 1.0, "window_resets_at": resets_at}))

    def _cost(self, request: ModelRequest, candidate: _Candidate, response: ModelResponse) -> dict:
        manifest, estimate = candidate.connector.manifest, candidate.estimate
        reported = response.tokens_in is not None and response.tokens_out is not None
        tokens_in = response.tokens_in if reported else estimate.tokens_in
        tokens_out = response.tokens_out if reported else estimate.tokens_out
        tokens_cached = response.tokens_cached or 0
        if not reported or response.metering == "estimated":
            basis = "estimated"
        else:
            basis = "exact" if manifest["access"] == "api" else "shadow"
        cost = {"adapter": manifest["id"], "tier": request.tier, "tokens_in": tokens_in,
                "tokens_cached": tokens_cached, "tokens_out": tokens_out, "quota_units": response.quota_units,
                "usd": candidate.price.usd(tokens_in, tokens_cached, tokens_out), "basis": basis,
                "price_ver": self._routing.version, "estimated_usd": estimate.usd}
        return {key: value for key, value in cost.items() if value is not None}

    def _failure_cost(self, request: ModelRequest, candidate: _Candidate) -> dict:
        """A failed call's usage is unknown: no charge is invented, the estimate is kept for calibration."""
        return {"adapter": candidate.connector.manifest["id"], "tier": request.tier, "usd": 0.0,
                "basis": "estimated", "price_ver": self._routing.version, "estimated_usd": candidate.estimate.usd}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q`
Expected: PASS (all suites)

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/gateway.py core/tests/test_gateway.py
git commit -m "core: provider gateway (estimate, routing, budgets, quota, metering, redaction)"
```

---

### Task 7: Documentation

**Files:**
- Modify: `core/description.md`, `docs/description.md`, `tasks/f1-skeleton/README.md`

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: As-is documentation of the gateway core.

- [ ] **Step 1: Update the documents**

In `core/description.md`, replace:

```markdown
storage and state projections. Gate, gateway, workers and API are not implemented yet.
```

with:

```markdown
storage, state projections and the provider gateway core (connector contract, registry, routing, budgets,
metering). Concrete connectors, Gate, workers and API are not implemented yet.
```

In `core/description.md`, replace:

```markdown
- `state.py` — `task_state()`, `contract_state()` computed from events
```

with:

```markdown
- `state.py` — `task_state()`, `contract_state()` computed from events
- `connectors/` — connector contract (`ModelConnector`, `ModelRequest`, `ModelResponse`, `ConnectorError`),
  `jurisdiction_fingerprint()`; `registry.py` discovers installed connectors (entry points `ooat.connectors`)
  and lists broken ones without using them
- `config.py` — `load_config()` for `ooat.toml`: ledger URL, per-tier pins, connector settings; no secrets,
  no enablement
- `secrets.py` — `SecretResolver`: values from named environment variables, `redact()`
- `routing.py` — `RoutingPolicy` from `routing.json`: dated prices, optional tier allow-list, data-class policy
- `gateway.py` — `Gateway.estimate()` / `.call()`: data-class guard, acknowledgement and automation rules from
  the ledger, quota cool-down, pins, cheapest connector, contract budget, cost record with `estimated_usd`
```

In `core/description.md`, replace:

```markdown
`Ledger.open(url)`, `new_event()`, `ArtifactStore`, `BlobStore`, `task_state()`, `contract_state()`, `validate()`.
```

with:

```markdown
`Ledger.open(url)`, `new_event()`, `ArtifactStore`, `BlobStore`, `task_state()`, `contract_state()`, `validate()`,
`Gateway`, `Registry.discover()`, `load_config()`, `load_routing()`, `SecretResolver`.
```

In `docs/description.md`, replace:

```markdown
the starter catalog holds role families and capability names only; `ooat-core` has the ledger foundation
(no Gate, gateway, workers or API yet).
```

with:

```markdown
the starter catalog holds role families and capability names only; `ooat-core` has the ledger foundation
and the provider gateway core (no concrete connectors, Gate, workers or API yet).
```

In `docs/description.md`, replace:

```markdown
- `core/` — `ooat-core` package: ledger, artifact storage, state projections (see `core/description.md`)
```

with:

```markdown
- `core/` — `ooat-core` package: ledger, artifact storage, state projections, provider gateway core (see `core/description.md`)
```

In `docs/description.md`, replace:

```markdown
None yet. Dev dependencies: `requirements-dev.txt`; run `python -m pytest` (paths in `pytest.ini`).
```

with:

```markdown
`ooat.toml` (operator preferences: ledger URL, per-tier pins, connector settings; secrets only as environment
variable names). Connector enablement is ledger state (`ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`, ADR 0010).
Dev dependencies: `requirements-dev.txt`; run `python -m pytest` (paths in `pytest.ini`).
```

In `tasks/f1-skeleton/README.md`, replace:

```markdown
Plans: 03a gateway core + connector contract, 03b connectors (Claude Code CLI, Codex CLI, Anthropic API), 03c `ooat connectors` + consequences card | 01 | 03a next |
```

with:

```markdown
Plans: 03a gateway core + connector contract (done), 03b connectors (Claude Code CLI, Codex CLI, Anthropic API), 03c `ooat connectors` + consequences card | 01 | 03b next |
```


- [ ] **Step 2: Run all tests**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add core/description.md docs/description.md tasks/f1-skeleton/README.md
git commit -m "docs: describe the provider gateway core"
```

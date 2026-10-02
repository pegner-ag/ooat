# Operator Data Responsibility (03e) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let tasks with personal details run without stopping: the operator takes responsibility for client and personal data once per connector (recorded, 12 months), may extend a subscription connector to those classes when training is off, and can block countries and keep personal data in chosen regions — all enforced by the gateway.

**Architecture:** The responsibility is a new optional object on `ADAPTER_ACKNOWLEDGED` (`confirmed_on`, `processing_regions`, `no_training`), written by `connector_admin.acknowledge()` and asked for by `ooat connectors enable`. The gateway's `_exclusion()` reads it through `responsibility_in_force()`: for `client_confidential` and `personal` it meets `require_contract`, supplies regions and "training off", and may exceed the manifest's classes. `ooat.toml` gains a `[policy]` table (`blocked_countries`, `personal_data_regions`) parsed into `Config`, checked by `blocked_by_policy()` and the gateway, and shown on the card and in the listing.

**Tech Stack:** Python 3.12+ standard library, JSON Schema 2020-12, pytest.

**Spec:** `tasks/f1-skeleton/task-03e-operator-data-responsibility/design.md`; ADR 0012 (new); ADR 0010 (connector state); spec §9.

## Global Constraints

- The ledger is append-only; the responsibility is recorded only on `ADAPTER_ACKNOWLEDGED` by a named human (`actor.kind = hil`).
- Responsibility covers `client_confidential` and `personal` only; `special_category` always needs verified redaction.
- A connector whose manifest says it trains on inputs (`training_on_inputs: true`) can never carry those classes beyond its manifest.
- Responsibility holds for 365 days from `confirmed_on`; the jurisdiction fingerprint rule (ADR 0010) still applies.
- `[policy]` values: `blocked_countries` = two-letter country codes (`^[A-Z]{2}$`) matched against `vendor_country` and `model_origin_country`; `personal_data_regions` = region codes (`^[a-z]{2}(-[a-z0-9-]+)?$`) matched by their first segment; unknown regions fail the limit; absent `personal_data_regions` means no limit.
- OOAT records the operator's statements and never claims to verify them; the card says so.
- `catalog/routing.json` is not changed.
- No secrets in config, fixtures or messages; code and docs in English; lines at most 120 characters.

## Review Focus

1. An operator who declines responsibility must leave nothing in the ledger — `test_declining_responsibility_changes_nothing` (Task 4).
2. A responsibility older than 12 months must stop personal data — `test_an_expired_responsibility_no_longer_counts` (Task 3), `test_responsibility_lasts_twelve_months_and_stands_in_for_the_verification_date` (Task 2).
3. A provider that trains on inputs must never be extended to client or personal data — `test_responsibility_has_limits` (Task 2).
4. `special_category` must never pass on a responsibility — `test_responsibility_never_covers_special_category_data` (Task 3).
5. A blocked country must exclude a connector even for public data — `test_blocked_countries_exclude_a_connector_for_every_class` (Task 3).

---

## File Structure

```
spec/schemas/event.schema.json, spec/examples/valid/event.adapter_acknowledged_responsibility.json,
spec/tests/test_schemas.py                                       responsibility on ADAPTER_ACKNOWLEDGED (Task 1)
core/src/ooat_core/config.py, core/tests/test_config.py          [policy] table (Task 1)
core/src/ooat_core/connectors/__init__.py                        jurisdiction_stale counts confirmed_on (Task 2)
core/src/ooat_core/connector_admin.py, core/tests/test_connector_admin.py   responsibility, policy, card (Task 2)
core/src/ooat_core/gateway.py, core/tests/test_gateway_responsibility.py    exclusions (Task 3)
core/src/ooat_core/operator_cli.py, core/tests/test_operator_cli.py         enable asks, list shows (Task 4)
core/description.md, docs/description.md, README.md, tasks/f1-skeleton/task-03d-gateway-hardening/task.md (Task 5)
```

How to apply a "replace" step: the old text occurs exactly once; replace it with the new text. Files may have CRLF line endings on Windows — match the text, not the line endings. Work on a branch `feat/data-responsibility` from `main`; run commands from the repository root with the project virtual environment active.

---

### Task 1: Schema and `[policy]` configuration

**Files:**
- Modify: `spec/schemas/event.schema.json`, `spec/tests/test_schemas.py`, `core/src/ooat_core/config.py`, `core/tests/test_config.py`
- Create: `spec/examples/valid/event.adapter_acknowledged_responsibility.json`

**Interfaces:**
- Produces: `ADAPTER_ACKNOWLEDGED.body.responsibility = {confirmed_on (date, required), processing_regions?, no_training? (const true)}`; `Config.blocked_countries: frozenset[str]` (default empty), `Config.personal_data_regions: frozenset[str] | None` (default None = no limit); `parse_config()` accepts a `[policy]` table with exactly these two keys; `load_config()` keeps the policy when it resolves a relative ledger path.

- [ ] **Step 1: Write the failing tests and example**

Create `spec/examples/valid/event.adapter_acknowledged_responsibility.json`:

````json
{
  "id": "evt_01J9ZQ61A1K3M5N7P9Q1R3S5T7",
  "ts": "2026-10-02T09:00:00Z",
  "task": null,
  "actor": {"kind": "hil", "id": "operator"},
  "type": "ADAPTER_ACKNOWLEDGED",
  "refs": [],
  "body": {
    "adapter": "prv.anthropic.subscription_cli",
    "manifest_version": "0.1.0",
    "allowed_data_classes": ["public", "internal", "client_confidential", "personal"],
    "operator": "Operator",
    "automation_confirmed": true,
    "jurisdiction_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    "responsibility": {"confirmed_on": "2026-10-02", "processing_regions": ["us"], "no_training": true}
  }
}
````

In `spec/tests/test_schemas.py`:

Replace:

````python
    ("event_rating_without_event", "event", "event.task_rated.json", _delete(["body", "decisions", 0, "event"])),
]
````

with:

````python
    ("event_rating_without_event", "event", "event.task_rated.json", _delete(["body", "decisions", 0, "event"])),
    # ADR 0012
    ("event_responsibility_without_date", "event", "event.adapter_acknowledged_responsibility.json",
     _delete(["body", "responsibility", "confirmed_on"])),
    ("event_responsibility_region_not_a_code", "event", "event.adapter_acknowledged_responsibility.json",
     _set(["body", "responsibility", "processing_regions"], ["Europe"])),
    ("event_responsibility_training_stated_false", "event", "event.adapter_acknowledged_responsibility.json",
     _set(["body", "responsibility", "no_training"], False)),
]
````

In `core/tests/test_config.py`:

Replace:

````python
    assert config.connectors["prv.anthropic.subscription_cli"]["models"] == {"workhorse": "claude-sonnet-5-5"}
````

with:

````python
    assert config.connectors["prv.anthropic.subscription_cli"]["models"] == {"workhorse": "claude-sonnet-5-5"}


def test_policy_limits_are_read():
    config = parse_config({"policy": {"blocked_countries": ["CN"], "personal_data_regions": ["eu"]}})
    assert config.blocked_countries == {"CN"} and config.personal_data_regions == {"eu"}
    assert parse_config({}).personal_data_regions is None  # no limit unless the operator sets one


@pytest.mark.parametrize("policy, message", [
    ({"blocked_countries": ["china"]}, "two-letter"),
    ({"blocked_countries": "CN"}, "two-letter"),
    ({"personal_data_regions": ["Europe"]}, "region codes"),
    ({"allow_everything": True}, "unknown settings"),
])
def test_policy_shapes_are_checked(policy, message):
    with pytest.raises(ValueError, match=message):
        parse_config({"policy": policy})


def test_a_relative_ledger_keeps_the_policy(tmp_path):
    (tmp_path / "ooat.toml").write_text('[ledger]\nurl = "sqlite:///l.sqlite"\n[policy]\nblocked_countries = ["CN"]\n',
                                        encoding="utf-8")
    assert load_config(tmp_path / "ooat.toml").blocked_countries == {"CN"}
````

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest spec core/tests/test_config.py -q`
Expected: `10 failed, 99 passed` — the new example and its invalid cases (the schema has no `responsibility` yet) and the policy tests (`unknown config sections: ['policy']`).

- [ ] **Step 3: Extend the schema and the config**

In `spec/schemas/event.schema.json`:

Replace:

````json
        "automation_confirmed": {"description": "The operator checked that the plan terms allow unattended use (ADR 0010).", "type": "boolean"},
        "jurisdiction_sha256": {"description": "Fingerprint of the acknowledged jurisdiction block (ADR 0010).", "type": "string", "pattern": "^[0-9a-f]{64}$"}
      }
````

with:

````json
        "automation_confirmed": {"description": "The operator checked that the plan terms allow unattended use (ADR 0010).", "type": "boolean"},
        "jurisdiction_sha256": {"description": "Fingerprint of the acknowledged jurisdiction block (ADR 0010).", "type": "string", "pattern": "^[0-9a-f]{64}$"},
        "responsibility": {
          "description": "The operator takes responsibility for client or personal data on this connector: legal basis, processing agreement, where it is processed (ADR 0012). In force for 12 months from confirmed_on.",
          "type": "object",
          "required": ["confirmed_on"],
          "additionalProperties": false,
          "properties": {
            "confirmed_on": {"type": "string", "format": "date"},
            "processing_regions": {"description": "Regions stated by the operator's agreement when the manifest does not know them.", "type": "array", "minItems": 1, "uniqueItems": true, "items": {"type": "string", "pattern": "^[a-z]{2}(-[a-z0-9-]+)?$"}},
            "no_training": {"description": "The operator states that training on inputs is switched off for this account.", "const": true}
          }
        }
      }
````

In `core/src/ooat_core/config.py`:

Replace:

````python
The file never holds secrets or connector enablement: secrets are named by environment variable, enablement is
ledger state (ADR 0010). Unknown keys are rejected so a pasted API key cannot hide in the file.
"""

import re
````

with:

````python
The file never holds secrets or connector enablement: secrets are named by environment variable, enablement is
ledger state (ADR 0010). Unknown keys are rejected so a pasted API key cannot hide in the file. The [policy] table
holds the operator's limits on where data may go, enforced by the gateway (ADR 0012).
"""

import dataclasses
import re
````

Replace:

````python
_CONNECTOR_KEYS = frozenset({"secret_env", "plan_fee_usd_month", "models"})
````

with:

````python
_CONNECTOR_KEYS = frozenset({"secret_env", "plan_fee_usd_month", "models"})
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_REGION = re.compile(r"^[a-z]{2}(-[a-z0-9-]+)?$")
````

Replace:

````python
    connectors: dict[str, dict] = field(default_factory=dict)  # connector id -> settings
````

with:

````python
    connectors: dict[str, dict] = field(default_factory=dict)  # connector id -> settings
    blocked_countries: frozenset[str] = frozenset()  # no connector whose vendor or model comes from these
    personal_data_regions: frozenset[str] | None = None  # personal data only processed here; None = no limit
````

Replace:

````python
def parse_config(data: dict) -> Config:
    unknown = set(data) - {"ledger", "routing", "connectors"}
    if unknown:
````

with:

````python
def parse_config(data: dict) -> Config:
    unknown = set(data) - {"ledger", "routing", "connectors", "policy"}
    if unknown:
````

Replace:

````python
            raise ValueError(f"{connector_id}: models must map tiers to model ids")
    return Config(ledger_url=ledger_url, pins=dict(pins), connectors={k: dict(v) for k, v in connectors.items()})
````

with:

````python
            raise ValueError(f"{connector_id}: models must map tiers to model ids")
    policy = _table(data, "policy", {"blocked_countries", "personal_data_regions"})
    blocked = policy.get("blocked_countries", [])
    if not isinstance(blocked, list) or not all(isinstance(c, str) and _COUNTRY.match(c) for c in blocked):
        raise ValueError("policy.blocked_countries must list two-letter country codes such as \"CN\"")
    regions = policy.get("personal_data_regions")
    if regions is not None and (not isinstance(regions, list)
                                or not all(isinstance(r, str) and _REGION.match(r) for r in regions)):
        raise ValueError("policy.personal_data_regions must list region codes such as \"eu\"")
    return Config(ledger_url=ledger_url, pins=dict(pins), connectors={k: dict(v) for k, v in connectors.items()},
                  blocked_countries=frozenset(blocked),
                  personal_data_regions=frozenset(regions) if regions is not None else None)
````

Replace:

````python
        resolved = (Path(path).resolve().parent / location).as_posix()
        config = Config(ledger_url=prefix + resolved, pins=config.pins, connectors=config.connectors)
    return config
````

with:

````python
        resolved = (Path(path).resolve().parent / location).as_posix()
        config = dataclasses.replace(config, ledger_url=prefix + resolved)
    return config
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest spec core/tests/test_config.py -q` → Expected: `109 passed`.
Run: `python -m pytest -q` → Expected: `575 passed, 4 skipped`.

- [ ] **Step 5: Commit**

```bash
git add spec/schemas/event.schema.json spec/examples/valid/event.adapter_acknowledged_responsibility.json spec/tests/test_schemas.py core/src/ooat_core/config.py core/tests/test_config.py
git commit -m "feat: responsibility on ADAPTER_ACKNOWLEDGED and a [policy] table in ooat.toml (ADR 0012)"
```

---

### Task 2: Responsibility and policy in connector administration

**Files:**
- Modify: `core/src/ooat_core/connectors/__init__.py`, `core/src/ooat_core/connector_admin.py`
- Test: `core/tests/test_connector_admin.py`

**Interfaces:**
- Consumes: `Config.blocked_countries`, `Config.personal_data_regions` (Task 1).
- Produces (in `ooat_core.connector_admin`): `RESPONSIBLE_CLASSES = ("client_confidential", "personal")`, `RESPONSIBILITY_DAYS = 365`; `responsibility_in_force(acknowledgement, today) -> dict | None`; `blocked_by_policy(manifest, config) -> str | None` ("blocked by your policy: model origin CN"); `checked_classes(manifest, classes, responsibility=None)`; `acknowledge(ledger, connector, operator, classes, automation_confirmed, responsibility=None, today=None)`; `consequences_card(manifest, today, config=None)` with a "Client or personal data" section and a "Your policy:" line; `connector_statuses(registry, ledger, today, config=None)` with `ConnectorStatus.responsibility_until` and `.blocked`. `jurisdiction_stale()` counts the later of `verified_on` and `responsibility.confirmed_on`.

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_connector_admin.py`:

Replace:

````python

from ooat_core.config import Config
from ooat_core.connector_admin import acknowledge, connector_statuses, consequences_card, disable
from ooat_core.connectors import ModelRequest
from ooat_core.connectors.registry import BrokenConnector, Registry
from ooat_core.gateway import Gateway
````

with:

````python

from ooat_core.config import Config
from ooat_core.connector_admin import (acknowledge, blocked_by_policy, connector_statuses, consequences_card, disable,
                                       responsibility_in_force)
from ooat_core.connectors import ModelRequest, jurisdiction_stale
from ooat_core.connectors.registry import BrokenConnector, Registry
from ooat_core.gateway import Gateway
````

Replace:

````python
        disable(ledger, "prv.fake.api", operator, "reason")
    assert ledger.events() == []
````

with:

````python
        disable(ledger, "prv.fake.api", operator, "reason")
    assert ledger.events() == []


# Operator responsibility for client and personal data (ADR 0012) -----------------------------------------------

def subscription(training=None, origin="US"):
    manifest = fake_manifest("prv.fake.subscription_cli", "subscription_cli", allowed=("public", "internal"),
                             jurisdiction=dict(JURISDICTION, model_origin_country=origin, verified_on=None))
    manifest["data_policy"]["training_on_inputs"] = training
    return FakeConnector(manifest)


def test_responsibility_extends_a_subscription_to_personal_data_when_training_is_off(ledger):
    event = acknowledge(ledger, subscription(), "Martin", ["public", "internal", "personal"], True,
                        {"no_training": True, "processing_regions": ["us"]}, TODAY)
    assert event["body"]["allowed_data_classes"] == ["public", "internal", "personal"]
    assert event["body"]["responsibility"] == {"confirmed_on": "2026-10-01", "no_training": True,
                                               "processing_regions": ["us"]}


@pytest.mark.parametrize("connector, classes, responsibility, message", [
    (subscription(), ["personal"], None, "need your responsibility"),
    (subscription(), ["personal"], {}, "training on your inputs is switched off"),
    (subscription(training=True), ["personal"], {"no_training": True}, "trains on inputs"),
    (subscription(), ["special_category"], {"no_training": True}, "verified redaction"),
    (FakeConnector(), ["public"], {}, "applies to client_confidential or personal"),
])
def test_responsibility_has_limits(ledger, connector, classes, responsibility, message):
    with pytest.raises(ValueError, match=message):
        acknowledge(ledger, connector, "Martin", classes, False, responsibility, TODAY)
    assert ledger.events() == []


def test_responsibility_lasts_twelve_months_and_stands_in_for_the_verification_date(ledger):
    connector = subscription()
    body = acknowledge(ledger, connector, "Martin", ["personal"], True, {"no_training": True}, TODAY)["body"]
    assert responsibility_in_force(body, date(2027, 10, 1)) is not None
    assert responsibility_in_force(body, date(2027, 10, 2)) is None
    assert not jurisdiction_stale(connector.manifest, body, TODAY)  # the manifest itself was never verified
    assert jurisdiction_stale(connector.manifest, body, date(2027, 10, 2))


def test_the_operator_policy_blocks_countries_and_is_shown_on_the_card_and_in_the_listing(ledger):
    connector = subscription(origin="CN")
    config = Config(blocked_countries=frozenset({"CN"}), personal_data_regions=frozenset({"eu"}))
    assert blocked_by_policy(connector.manifest, config) == "blocked by your policy: model origin CN"
    card = consequences_card(connector.manifest, TODAY, config)
    assert "blocked by your policy: model origin CN" in card and "Personal data only processed in: eu" in card
    assert "Only when you take responsibility" in consequences_card(connector.manifest, TODAY)
    acknowledge(ledger, connector, "Martin", ["personal"], True, {"no_training": True}, TODAY)
    (status,) = connector_statuses(Registry([connector]), ledger, TODAY, config)
    assert status.blocked == "blocked by your policy: model origin CN" and status.responsibility_until == "2027-10-01"
````

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest core/tests/test_connector_admin.py -q`
Expected: collection error — `ImportError: cannot import name 'blocked_by_policy' from 'ooat_core.connector_admin'`.

- [ ] **Step 3: Implement**

In `core/src/ooat_core/connectors/__init__.py`:

Replace:

````python
    A stale connector stays enabled but refuses personal and special-category data until acknowledged again.
    """
    verified_on = manifest["jurisdiction"]["verified_on"]
    if verified_on is None or (today - date.fromisoformat(verified_on)).days > 365:
        return True
````

with:

````python
    A stale connector stays enabled but refuses personal and special-category data until acknowledged again.
    An operator who takes responsibility (ADR 0012) checks the facts on the card that day, so the later of the
    manifest's verified_on and the responsibility's confirmed_on counts.
    """
    dates = [d for d in (manifest["jurisdiction"]["verified_on"],
                         (acknowledgement.get("responsibility") or {}).get("confirmed_on")) if d]
    if not dates or (today - max(date.fromisoformat(d) for d in dates)).days > 365:
        return True
````

In `core/src/ooat_core/connector_admin.py`:

Replace:

````python
by a named human. The card only shows what the manifest states; unknown facts are shown as unknown, never guessed.
"""
````

with:

````python
by a named human. The card only shows what the manifest states; unknown facts are shown as unknown, never guessed.
Client and personal data need the operator's responsibility (ADR 0012), which may extend a connector beyond the
classes its manifest accepts; the operator's [policy] in ooat.toml can block countries and limit personal data to
regions.
"""
````

Replace:

````python

from .connectors import ModelConnector, jurisdiction_fingerprint, jurisdiction_stale
````

with:

````python

from .config import Config
from .connectors import ModelConnector, jurisdiction_fingerprint, jurisdiction_stale
````

Replace:

````python
DEFAULT_CLASSES = ("public", "internal")
_STATE_EVENTS = ["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"]
````

with:

````python
DEFAULT_CLASSES = ("public", "internal")
RESPONSIBLE_CLASSES = ("client_confidential", "personal")  # need the operator's responsibility (ADR 0012)
RESPONSIBILITY_DAYS = 365
_STATE_EVENTS = ["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"]
````

Replace:

````python
    unattended: bool  # the gateway may route to it: enabled, terms allow it, operator confirmed
````

with:

````python
    unattended: bool  # the gateway may route to it: enabled, terms allow it, operator confirmed
    responsibility_until: str | None = None  # last day the operator's responsibility is in force
    blocked: str | None = None  # why the operator's policy blocks it
````

Replace:

````python

def unattended_forbidden(manifest: dict) -> str | None:
````

with:

````python

def responsibility_in_force(acknowledgement: dict | None, today: date) -> dict | None:
    """The operator's responsibility for client or personal data, if given within the last 12 months."""
    responsibility = (acknowledgement or {}).get("responsibility")
    if responsibility is None:
        return None
    if (today - date.fromisoformat(responsibility["confirmed_on"])).days > RESPONSIBILITY_DAYS:
        return None
    return responsibility


def blocked_by_policy(manifest: dict, config: Config | None) -> str | None:
    """Why the operator's policy excludes this connector for any data, or None."""
    if config is None:
        return None
    jurisdiction = manifest["jurisdiction"]
    for label, country in (("vendor country", jurisdiction["vendor_country"]),
                           ("model origin", jurisdiction["model_origin_country"])):
        if country in config.blocked_countries:
            return f"blocked by your policy: {label} {country}"
    return None


def unattended_forbidden(manifest: dict) -> str | None:
````

Replace:

````python

def connector_statuses(registry: Registry, ledger: Ledger, today: date) -> list[ConnectorStatus]:
    latest, statuses = latest_state_events(ledger.events(types=_STATE_EVENTS)), []
````

with:

````python

def connector_statuses(registry: Registry, ledger: Ledger, today: date,
                       config: Config | None = None) -> list[ConnectorStatus]:
    latest, statuses = latest_state_events(ledger.events(types=_STATE_EVENTS)), []
````

Replace:

````python
        event = latest.get(connector_id)
        state, stale, unattended = "not acknowledged", False, False
        if event is not None and event["type"] == "ADAPTER_DISABLED":
````

with:

````python
        event = latest.get(connector_id)
        state, stale, unattended, until = "not acknowledged", False, False, None
        if event is not None and event["type"] == "ADAPTER_DISABLED":
````

Replace:

````python
                          and unattended_forbidden(connector.manifest) is None)
        try:
````

with:

````python
                          and unattended_forbidden(connector.manifest) is None)
            responsibility = responsibility_in_force(event["body"], today)
            if responsibility is not None:
                confirmed = date.fromisoformat(responsibility["confirmed_on"])
                until = date.fromordinal(confirmed.toordinal() + RESPONSIBILITY_DAYS).isoformat()
        try:
````

Replace:

````python
        statuses.append(ConnectorStatus(connector_id, state, detail, dict(connector.manifest["tiers"]),
                                        connector.manifest["automation_permitted"], stale, unattended))
    for broken in registry.broken:
````

with:

````python
        statuses.append(ConnectorStatus(connector_id, state, detail, dict(connector.manifest["tiers"]),
                                        connector.manifest["automation_permitted"], stale, unattended, until,
                                        blocked_by_policy(connector.manifest, config)))
    for broken in registry.broken:
````

Replace:

````python

def consequences_card(manifest: dict, today: date) -> str:
    """Plain-text connection consequences card built from the manifest (spec §9 rule 1)."""
````

with:

````python

def consequences_card(manifest: dict, today: date, config: Config | None = None) -> str:
    """Plain-text connection consequences card built from the manifest (spec §9 rule 1)."""
````

Replace:

````python
        f"Classes this connector accepts: {_value(policy['allowed_data_classes'])}",
        "",
````

with:

````python
        f"Classes this connector accepts: {_value(policy['allowed_data_classes'])}",
        "Client or personal data (client_confidential, personal)",
        "  Only when you take responsibility: you have a legal basis, a processing agreement with the provider,",
        "  and you know where it processes. OOAT records your name and the date, and asks again after 12 months",
        "  or when these facts change. It may then also carry these classes beyond the list above, if training",
        "  on your inputs is off.",
    ]
    if config is not None:
        blocked = blocked_by_policy(manifest, config)
        lines.append(f"Your policy:            {blocked or 'does not block this connector'}")
        if config.personal_data_regions is not None:
            lines.append(f"  Personal data only processed in: {_value(sorted(config.personal_data_regions))}")
    lines += [
        "",
````

Replace:

````python

def checked_classes(manifest: dict, data_classes: Iterable[str]) -> list[str]:
    """Requested classes in canonical order, limited to what the connector accepts."""
    requested = set(data_classes)
````

with:

````python

def checked_classes(manifest: dict, data_classes: Iterable[str], responsibility: dict | None = None) -> list[str]:
    """Requested classes in canonical order, limited to what the connector accepts. With the operator's
    responsibility, client and personal data may go beyond the manifest unless the provider trains on inputs."""
    requested = set(data_classes)
````

Replace:

````python
    beyond = [c for c in classes if c not in manifest["data_policy"]["allowed_data_classes"]]
    if beyond:
        raise ValueError(f"{manifest['id']} does not accept {beyond}")
    return classes
````

with:

````python
    beyond = [c for c in classes if c not in manifest["data_policy"]["allowed_data_classes"]]
    if any(c not in RESPONSIBLE_CLASSES for c in beyond) or (beyond and responsibility is None):
        raise ValueError(f"{manifest['id']} does not accept {beyond} (client_confidential and personal need your "
                         f"responsibility; special_category needs verified redaction)")
    training = manifest["data_policy"]["training_on_inputs"]
    if beyond and training is True:
        raise ValueError(f"{manifest['id']} trains on inputs; it cannot carry {beyond}")
    if beyond and training is None and not responsibility.get("no_training"):
        raise ValueError(f"{manifest['id']}: state that training on your inputs is switched off to allow {beyond}")
    return classes
````

Replace:

````python
def acknowledge(ledger: Ledger, connector: ModelConnector, operator: str, data_classes: Iterable[str],
                automation_confirmed: bool) -> dict:
    """Enable a connector: a named operator allows data classes and states whether automation is confirmed."""
    manifest = connector.manifest
    operator = checked_operator(operator)
    classes = checked_classes(manifest, data_classes)
    forbidden = unattended_forbidden(manifest)
````

with:

````python
def acknowledge(ledger: Ledger, connector: ModelConnector, operator: str, data_classes: Iterable[str],
                automation_confirmed: bool, responsibility: dict | None = None, today: date | None = None) -> dict:
    """Enable a connector: a named operator allows data classes and states whether automation is confirmed.

    `responsibility` ({"processing_regions": [...], "no_training": True}, both optional) records that the operator
    takes responsibility for client or personal data on this connector, dated `today` (ADR 0012).
    """
    manifest = connector.manifest
    operator = checked_operator(operator)
    classes = checked_classes(manifest, data_classes, responsibility)
    forbidden = unattended_forbidden(manifest)
````

Replace:

````python
        raise ValueError(f"{manifest['id']}: {forbidden}; it cannot be confirmed")
    return ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor={"kind": "hil", "id": operator}, body={
        "adapter": manifest["id"], "manifest_version": manifest["version"], "allowed_data_classes": classes,
        "operator": operator, "automation_confirmed": automation_confirmed,
        "jurisdiction_sha256": jurisdiction_fingerprint(manifest)}))
````

with:

````python
        raise ValueError(f"{manifest['id']}: {forbidden}; it cannot be confirmed")
    body = {"adapter": manifest["id"], "manifest_version": manifest["version"], "allowed_data_classes": classes,
            "operator": operator, "automation_confirmed": automation_confirmed,
            "jurisdiction_sha256": jurisdiction_fingerprint(manifest)}
    if responsibility is not None:
        if not set(classes) & set(RESPONSIBLE_CLASSES):
            raise ValueError("responsibility applies to client_confidential or personal data")
        if today is None:
            raise ValueError("responsibility needs the date it is taken")
        body["responsibility"] = {"confirmed_on": today.isoformat(), **responsibility}
    return ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor={"kind": "hil", "id": operator},
                                   body=body))
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest core/tests/test_connector_admin.py -q` → Expected: `24 passed`.
Run: `python -m pytest -q` → Expected: `583 passed, 4 skipped`.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/connectors/__init__.py core/src/ooat_core/connector_admin.py core/tests/test_connector_admin.py
git commit -m "feat(core): the operator's responsibility and policy in connector administration"
```

---

### Task 3: The gateway honours responsibility and policy

**Files:**
- Modify: `core/src/ooat_core/gateway.py`
- Create: `core/tests/test_gateway_responsibility.py`

**Interfaces:**
- Consumes: `RESPONSIBLE_CLASSES`, `responsibility_in_force`, `blocked_by_policy` (Task 2); `Config` policy (Task 1).
- Produces: `Gateway._exclusion()` order: tier, routing allow-list, manual relay, acknowledgement, policy block, special category, routing policy, manifest classes (unless responsible), acknowledged classes, no training, known region, redaction, contract (met by responsibility), personal-data regions, staleness, automation, cool-down. The contract refusal reads "requires a provider contract: take responsibility for it when enabling the connector".

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_gateway_responsibility.py`:

````python
"""The gateway honours the operator's responsibility and [policy] for client and personal data (ADR 0012)."""

from datetime import date, datetime, timedelta, timezone

import pytest
from connector_fakes import JURISDICTION, FakeConnector, fake_manifest

from ooat_core.config import parse_config
from ooat_core.connector_admin import acknowledge
from ooat_core.connectors import ModelRequest
from ooat_core.connectors.registry import Registry
from ooat_core.credentials_env import SecretResolver
from ooat_core.gateway import Gateway, GatewayError
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger
from ooat_core.routing import RoutingPolicy

TODAY = date(2026, 10, 2)
# As catalog/routing.json: client and personal data need a contract, no training and a known region.
POLICY = {
    "public": {"allowed": True}, "internal": {"allowed": True},
    "client_confidential": {"allowed": True, "require_no_training": True, "require_known_region": True,
                            "require_contract": True},
    "personal": {"allowed": True, "require_no_training": True, "require_known_region": True, "require_contract": True},
    "special_category": {"allowed": True, "require_verified_redaction": True},
}
PRICES = [{"adapter": a, "model": "fake-model", "usd_per_mtok_in": 3, "usd_per_mtok_out": 15,
           "valid_from": "2026-01-01", "source": "https://fake.invalid/pricing"}
          for a in ("prv.fake.api", "prv.fake.subscription_cli", "prv.far.api")]


def api():
    return FakeConnector(fake_manifest("prv.fake.api", "api"))  # accepts personal, region eu, verified, no training


def subscription():
    manifest = fake_manifest("prv.fake.subscription_cli", "subscription_cli", allowed=("public", "internal"),
                             jurisdiction=dict(JURISDICTION, processing_regions=None, verified_on=None))
    manifest["data_policy"]["training_on_inputs"] = None
    return FakeConnector(manifest)


def far_away():
    return FakeConnector(fake_manifest("prv.far.api", "api",
                                       jurisdiction=dict(JURISDICTION, model_origin_country="CN")))


class Setup:
    def __init__(self, *connectors, policy=None, today=TODAY):
        self.ledger = Ledger.open("sqlite:///:memory:")
        self.connectors = connectors
        self.config = parse_config({"policy": policy or {}})
        self.now = datetime(today.year, today.month, today.day, 12, tzinfo=timezone.utc)
        self.gateway = Gateway(self.ledger, Registry(connectors),
                               RoutingPolicy({"version": "0.1.0", "prices": PRICES, "data_class_policy": POLICY}),
                               self.config, SecretResolver(self.config, {}), clock=lambda: self.now)

    def enable(self, connector, classes=("public", "internal", "personal"), responsibility=None):
        acknowledge(self.ledger, connector, "Martin", list(classes), True, responsibility, TODAY)

    def route(self, data_class):
        request = ModelRequest(tier="workhorse", prompt="Uprav stránku.", data_class=data_class, task=new_id("tsk"))
        return self.gateway.estimate(request).connector


def test_without_responsibility_personal_data_is_refused_with_a_way_out():
    connector = api()
    setup = Setup(connector)
    setup.enable(connector)
    with pytest.raises(GatewayError) as info:
        setup.route("personal")
    assert "take responsibility for it when enabling the connector" in info.value.trace[0]
    assert setup.route("internal") == "prv.fake.api"


def test_with_responsibility_personal_data_runs_on_the_api():
    connector = api()
    setup = Setup(connector)
    setup.enable(connector, responsibility={})
    assert setup.route("personal") == "prv.fake.api"


def test_responsibility_carries_personal_data_on_a_subscription_beyond_its_manifest():
    connector = subscription()
    setup = Setup(connector)
    setup.enable(connector, responsibility={"no_training": True, "processing_regions": ["us"]})
    assert setup.route("personal") == "prv.fake.subscription_cli"


def test_an_expired_responsibility_no_longer_counts():
    connector = api()
    setup = Setup(connector, today=TODAY + timedelta(days=366))
    setup.enable(connector, responsibility={})
    with pytest.raises(GatewayError):
        setup.route("personal")


def test_blocked_countries_exclude_a_connector_for_every_class():
    blocked, allowed = far_away(), api()
    setup = Setup(blocked, allowed, policy={"blocked_countries": ["CN"]})
    for connector in (blocked, allowed):
        setup.enable(connector)
    assert setup.route("internal") == "prv.fake.api"
    only_blocked = Setup(far_away(), policy={"blocked_countries": ["CN"]})
    only_blocked.enable(only_blocked.connectors[0])
    with pytest.raises(GatewayError) as info:
        only_blocked.route("public")
    assert "blocked by your policy: model origin CN" in info.value.trace[0]


def test_personal_data_stays_in_the_regions_the_operator_allows():
    us, eu = subscription(), api()
    setup = Setup(us, eu, policy={"personal_data_regions": ["eu"]})
    setup.enable(us, responsibility={"no_training": True, "processing_regions": ["us"]})
    setup.enable(eu, responsibility={})
    assert setup.route("personal") == "prv.fake.api"
    assert setup.route("internal") in ("prv.fake.subscription_cli", "prv.fake.api")
    only_us = Setup(subscription(), policy={"personal_data_regions": ["eu"]})
    only_us.enable(only_us.connectors[0], responsibility={"no_training": True, "processing_regions": ["us"]})
    with pytest.raises(GatewayError) as info:
        only_us.route("personal")
    assert "only in ['eu']" in info.value.trace[0]


def test_responsibility_never_covers_special_category_data():
    connector = api()
    setup = Setup(connector)
    setup.enable(connector, responsibility={})
    with pytest.raises(GatewayError):
        setup.route("special_category")
````

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest core/tests/test_gateway_responsibility.py -q`
Expected: `5 failed, 2 passed` — the two that pass already (`test_an_expired_responsibility_no_longer_counts`, `test_responsibility_never_covers_special_category_data`) guard refusals that must stay.

- [ ] **Step 3: Implement**

In `core/src/ooat_core/gateway.py`:

Replace:

````python
from .config import Config
from .connector_admin import acknowledgements
from .connectors import (ConnectorError, DecisionAnswer, DecisionRequest, ModelConnector, ModelRequest, ModelResponse,
````

with:

````python
from .config import Config
from .connector_admin import RESPONSIBLE_CLASSES, acknowledgements, blocked_by_policy, responsibility_in_force
from .connectors import (ConnectorError, DecisionAnswer, DecisionRequest, ModelConnector, ModelRequest, ModelResponse,
````

Replace:

````python
            return "not acknowledged by the operator (or disabled)"
        if data_class == "special_category":
````

with:

````python
            return "not acknowledged by the operator (or disabled)"
        blocked = blocked_by_policy(manifest, self._config)
        if blocked:
            return blocked
        if data_class == "special_category":
````

Replace:

````python
            return f"{data_class} is not allowed by the routing policy"
        if data_class not in manifest["data_policy"]["allowed_data_classes"]:
            return f"{data_class} is not allowed by the manifest"
````

with:

````python
            return f"{data_class} is not allowed by the routing policy"
        # The operator's responsibility (ADR 0012) stands in for what a manifest cannot state: the processing
        # agreement, the region under it, and that training is off for this account.
        responsibility = responsibility_in_force(acknowledgement, self._clock().date())
        responsible = responsibility is not None and data_class in RESPONSIBLE_CLASSES
        if data_class not in manifest["data_policy"]["allowed_data_classes"] and not responsible:
            return f"{data_class} is not allowed by the manifest"
````

Replace:

````python
            return f"{data_class} was not acknowledged by the operator"
        if policy.get("require_no_training") and manifest["data_policy"]["training_on_inputs"] is not False:
            return f"{data_class} requires a connector that does not train on inputs"
        if policy.get("require_known_region") and not manifest["jurisdiction"]["processing_regions"]:
            return f"{data_class} requires a known processing region"
````

with:

````python
            return f"{data_class} was not acknowledged by the operator"
        no_training = manifest["data_policy"]["training_on_inputs"] is False or (
            responsible and responsibility.get("no_training") is True
            and manifest["data_policy"]["training_on_inputs"] is not True)
        if policy.get("require_no_training") and not no_training:
            return f"{data_class} requires a connector that does not train on inputs"
        regions = manifest["jurisdiction"]["processing_regions"] or (
            responsibility.get("processing_regions") if responsible else None)
        if policy.get("require_known_region") and not regions:
            return f"{data_class} requires a known processing region"
````

Replace:

````python
            return f"{data_class} requires verified redaction, not available yet"
        if policy.get("require_contract"):  # manifests cannot state a processing agreement yet: fail closed
            return f"{data_class} requires a provider contract, which cannot be verified yet"
        if data_class in _PERSONAL_OR_HIGHER and jurisdiction_stale(manifest, acknowledgement, self._clock().date()):
````

with:

````python
            return f"{data_class} requires verified redaction, not available yet"
        if policy.get("require_contract") and not responsible:  # nothing else can vouch for an agreement
            return f"{data_class} requires a provider contract: take responsibility for it when enabling the connector"
        allowed_regions = self._config.personal_data_regions
        if data_class in _PERSONAL_OR_HIGHER and allowed_regions is not None and (
                not regions or any(r.split("-")[0] not in allowed_regions for r in regions)):
            return (f"your policy allows personal data only in {sorted(allowed_regions)}; "
                    f"this connector processes in {regions or 'unknown regions'}")
        if data_class in _PERSONAL_OR_HIGHER and jurisdiction_stale(manifest, acknowledgement, self._clock().date()):
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest core/tests/test_gateway_responsibility.py -q` → Expected: `7 passed`.
Run: `python -m pytest -q` → Expected: `590 passed, 4 skipped`.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/gateway.py core/tests/test_gateway_responsibility.py
git commit -m "feat(core): the gateway routes client and personal data on the operator's responsibility and policy"
```

---

### Task 4: `ooat connectors enable` asks, `list` and `show` tell

**Files:**
- Modify: `core/src/ooat_core/operator_cli.py`
- Test: `core/tests/test_operator_cli.py`

**Interfaces:**
- Consumes: Task 2 functions.
- Produces: `ooat connectors enable ... [--responsibility yes|no] [--regions eu,us] [--no-training yes|no]`. When the chosen classes include `client_confidential` or `personal`, the command prints the responsibility text and asks (in this order, each only when needed): responsibility; regions (manifest regions unknown); training off (manifest training unknown); then automation and confirmation as before. Declining changes nothing. `list` adds "blocked by your policy: …" and "your responsibility for client or personal data holds until YYYY-MM-DD"; `show` passes the config to the card.

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_operator_cli.py`:

Replace:

````python
import pytest
from connector_fakes import FakeConnector, fake_manifest
````

with:

````python
import pytest
from connector_fakes import JURISDICTION, FakeConnector, fake_manifest
````

Replace:

````python
        ledger.close()
````

with:

````python
        ledger.close()


# Operator responsibility for client and personal data (ADR 0012) -----------------------------------------------

def subscription(origin="US"):
    manifest = fake_manifest("prv.fake.subscription_cli", "subscription_cli", allowed=("public", "internal"),
                             jurisdiction=dict(JURISDICTION, processing_regions=None, verified_on=None,
                                               model_origin_country=origin))
    manifest["data_policy"]["training_on_inputs"] = None
    return FakeConnector(manifest)


def test_choosing_personal_data_asks_for_responsibility_and_records_it(config):
    code, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin",
                    answers="public,internal,personal\nyes\nyes\nprv.fake.api\n")
    assert code == 0 and "Do you take this responsibility?" in out and "You took responsibility" in out
    assert state_events(config)[0]["body"]["responsibility"] == {"confirmed_on": "2026-10-01"}


def test_declining_responsibility_changes_nothing(config):
    code, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin",
                    answers="personal\nno\n")
    assert code == 1 and "need your responsibility" in out and state_events(config) == []


def test_a_subscription_gets_personal_data_with_regions_and_training_stated(config):
    flags = ["--classes", "public,internal,personal", "--responsibility", "yes", "--regions", "us,eu",
             "--no-training", "yes", "--automation", "yes", "--confirm", "prv.fake.subscription_cli"]
    code, _ = run(config, "connectors", "enable", "prv.fake.subscription_cli", "--operator", "Martin", *flags,
                  connectors=[subscription()])
    assert code == 0
    assert state_events(config)[0]["body"]["responsibility"] == {
        "confirmed_on": "2026-10-01", "processing_regions": ["eu", "us"], "no_training": True}


@pytest.mark.parametrize("flags, message", [
    (["--regions", "us", "--no-training", "no"], "training on your inputs is switched off"),
    (["--regions", "Europe", "--no-training", "yes"], "regions are codes"),
])
def test_a_subscription_without_the_needed_statements_is_refused(config, flags, message):
    code, out = run(config, "connectors", "enable", "prv.fake.subscription_cli", "--operator", "Martin",
                    "--classes", "personal", "--responsibility", "yes", *flags, connectors=[subscription()])
    assert code == 1 and message in out and state_events(config) == []


def test_list_and_show_reflect_the_policy_and_the_responsibility(config):
    path, url = config
    path.write_text(f'[ledger]\nurl = "{url}"\n[policy]\nblocked_countries = ["CN"]\n', encoding="utf-8")
    connector = subscription(origin="CN")
    run(config, "connectors", "enable", "prv.fake.subscription_cli", "--operator", "Martin", "--classes", "personal",
        "--responsibility", "yes", "--regions", "us", "--no-training", "yes", "--automation", "yes",
        "--confirm", "prv.fake.subscription_cli", connectors=[connector])
    _, listing = run(config, "connectors", "list", connectors=[connector])
    assert "blocked by your policy: model origin CN" in listing and "holds until 2027-10-01" in listing
    _, card = run(config, "connectors", "show", "prv.fake.subscription_cli", connectors=[connector])
    assert "Your policy:            blocked by your policy: model origin CN" in card
````

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest core/tests/test_operator_cli.py -q`
Expected: `6 failed, 31 passed` — the six new tests.

- [ ] **Step 3: Implement**

In `core/src/ooat_core/operator_cli.py`:

Replace:

````python
import argparse
import sqlite3
````

with:

````python
import argparse
import re
import sqlite3
````

Replace:

````python
CANCELLED = 130
````

with:

````python
CANCELLED = 130
_REGION = re.compile(r"^[a-z]{2}(-[a-z0-9-]+)?$")
RESPONSIBILITY = """
Client or personal data on this connector (ADR 0012). By answering yes you state that you have a legal basis
for it, a processing agreement with the provider that covers it, and that you know where the provider processes
it. OOAT records your name and today's date; the statement holds for 12 months or until the facts on the card
change. OOAT does not check it: you answer for it.
"""
````

Replace:

````python
    enable.add_argument("--confirm", help="the connector id, typed again to confirm (asked when omitted)")
    disable = actions.add_parser("disable", help="disable a connector")
````

with:

````python
    enable.add_argument("--confirm", help="the connector id, typed again to confirm (asked when omitted)")
    enable.add_argument("--responsibility", choices=["yes", "no"],
                        help="take responsibility for client or personal data (asked when those classes are chosen)")
    enable.add_argument("--regions", help="comma-separated regions under your agreement, e.g. eu (asked when the "
                                          "manifest does not know them)")
    enable.add_argument("--no-training", dest="no_training", choices=["yes", "no"],
                        help="training on your inputs is switched off for this account (asked when unknown)")
    disable = actions.add_parser("disable", help="disable a connector")
````

Replace:

````python
            return REFUSED
        stdout.write(connector_admin.consequences_card(connector.manifest, today) + "\n")
        return 0
````

with:

````python
            return REFUSED
        stdout.write(connector_admin.consequences_card(connector.manifest, today, config) + "\n")
        return 0
````

Replace:

````python
        if args.action == "list":
            return _list(registry, ledger, today, stdout)
        if args.action == "disable":
            return _disable(args, ledger, url, stdout)
        return _enable(args, registry, ledger, url, today, stdin, stdout)
    finally:
````

with:

````python
        if args.action == "list":
            return _list(registry, ledger, today, config, stdout)
        if args.action == "disable":
            return _disable(args, ledger, url, stdout)
        return _enable(args, registry, ledger, url, today, config, stdin, stdout)
    finally:
````

Replace:

````python

def _list(registry, ledger, today, stdout) -> int:
    for status in connector_admin.connector_statuses(registry, ledger, today):
        state = status.state
````

with:

````python

def _list(registry, ledger, today, config, stdout) -> int:
    for status in connector_admin.connector_statuses(registry, ledger, today, config):
        state = status.state
````

Replace:

````python
            stdout.write(f"  tiers: {tiers}; unattended use per terms: {status.automation}\n")
    return 0
````

with:

````python
            stdout.write(f"  tiers: {tiers}; unattended use per terms: {status.automation}\n")
        if status.blocked:
            stdout.write(f"  {status.blocked}\n")
        if status.responsibility_until:
            stdout.write(f"  your responsibility for client or personal data holds until "
                         f"{status.responsibility_until}\n")
    return 0
````

Replace:

````python

def _enable(args, registry, ledger, url, today, stdin, stdout) -> int:
    connector = registry.get(args.connector)
````

with:

````python

def _responsibility(args, manifest, stdin, stdout) -> tuple[dict | None, str | None]:
    """Ask for the operator's responsibility for client or personal data: (responsibility, refusal)."""
    stdout.write(RESPONSIBILITY)
    taken = args.responsibility or _ask("Do you take this responsibility? (yes/no): ", stdin, stdout).lower()
    if taken not in ("yes", "no"):
        return None, "answer yes or no"
    if taken == "no":
        return None, "client_confidential and personal data need your responsibility"
    responsibility = {}
    if not manifest["jurisdiction"]["processing_regions"]:
        answer = args.regions if args.regions is not None else _ask(
            "Regions where the provider processes under your agreement (e.g. eu, us; empty if unknown): ",
            stdin, stdout)
        regions = [r.strip() for r in answer.split(",") if r.strip()]
        if not all(_REGION.match(r) for r in regions):
            return None, "regions are codes such as eu or us"
        if regions:
            responsibility["processing_regions"] = sorted(set(regions))
    if manifest["data_policy"]["training_on_inputs"] is None:
        off = args.no_training or _ask("Is training on your inputs switched off for this account? (yes/no): ",
                                       stdin, stdout).lower()
        if off not in ("yes", "no"):
            return None, "answer yes or no"
        if off == "yes":
            responsibility["no_training"] = True
    return responsibility, None


def _enable(args, registry, ledger, url, today, config, stdin, stdout) -> int:
    connector = registry.get(args.connector)
````

Replace:

````python
        return REFUSED
    stdout.write(connector_admin.consequences_card(manifest, today) + "\n")
    default = [c for c in connector_admin.DEFAULT_CLASSES if c in manifest["data_policy"]["allowed_data_classes"]]
````

with:

````python
        return REFUSED
    stdout.write(connector_admin.consequences_card(manifest, today, config) + "\n")
    default = [c for c in connector_admin.DEFAULT_CLASSES if c in manifest["data_policy"]["allowed_data_classes"]]
````

Replace:

````python
        answer = _ask(f"\nData classes to allow{hint}: ", stdin, stdout) or ",".join(default)
    try:
        classes = connector_admin.checked_classes(manifest, [c.strip() for c in answer.split(",") if c.strip()])
    except ValueError as error:
````

with:

````python
        answer = _ask(f"\nData classes to allow{hint}: ", stdin, stdout) or ",".join(default)
    requested = [c.strip() for c in answer.split(",") if c.strip()]
    responsibility = None
    if set(requested) & set(connector_admin.RESPONSIBLE_CLASSES):
        responsibility, refusal = _responsibility(args, manifest, stdin, stdout)
        if refusal:
            stdout.write(f"Refused: {refusal}; nothing was changed.\n")
            return REFUSED
    try:
        classes = connector_admin.checked_classes(manifest, requested, responsibility)
    except ValueError as error:
````

Replace:

````python
    try:
        connector_admin.acknowledge(ledger, connector, operator, classes, automation)
    except ValueError as error:
````

with:

````python
    try:
        connector_admin.acknowledge(ledger, connector, operator, classes, automation, responsibility, today)
    except ValueError as error:
````

Replace:

````python
    stdout.write(f"{manifest['id']} enabled for {', '.join(classes)}; {mode}. Recorded in {url}.\n")
    return 0
````

with:

````python
    stdout.write(f"{manifest['id']} enabled for {', '.join(classes)}; {mode}. Recorded in {url}.\n")
    if responsibility is not None:
        stdout.write(f"You took responsibility for client or personal data on it as {operator} on {today}.\n")
    return 0
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest core/tests/test_operator_cli.py -q` → Expected: `37 passed`.
Run: `python -m pytest -q` → Expected: `596 passed, 4 skipped`.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/operator_cli.py core/tests/test_operator_cli.py
git commit -m "feat(cli): enable asks for responsibility; list and show reflect it and the policy"
```

---

### Task 5: Documentation

**Files:**
- Modify: `core/description.md`, `docs/description.md`, `README.md`, `tasks/f1-skeleton/task-03d-gateway-hardening/task.md`

- [ ] **Step 1: Update the As-is docs and the hardening list**

In `core/description.md`:

Replace:

````markdown
- `gate.py` — `Gate.run(task)`: step A as one decision batch (A1 per criterion, A4, A5, A7, A10), data class
  raised by pre-scan and a confident A10, estimate of worker plus acceptance checks, then T0 (closed: no permitted
  route, not worth its value, unclear after 3 clarifications, over budget after 3 budget questions, unanswered
````

with:

````markdown
- `gate.py` — `Gate.run(task)`: step A as one decision batch (A1 per criterion, A4, A5, A7, A10), data class
  raised by pre-scan and by any A10 answer, estimate of worker plus acceptance checks, then T0 (closed: no permitted
  route, not worth its value, unclear after 3 clarifications, over budget after 3 budget questions, unanswered
````

Replace:

````markdown
  operator's answers back for the runtime
- `config.py` — `load_config()` for `ooat.toml`: ledger URL, per-tier pins, connector settings; no secrets,
  no enablement
- `credentials_env.py` — `SecretResolver`: values from named environment variables, `redact()`
- `routing.py` — `RoutingPolicy` from `routing.json`: dated prices, optional tier allow-list, data-class policy
- `gateway.py` — `Gateway.estimate()` / `.call()`: data-class guard, acknowledgement and automation rules from
  the ledger, quota cool-down, pins, cheapest connector, contract budget, cost record with `estimated_usd`;
  passes the routed model to the connector in `ModelRequest.model`. `Gateway.estimate_decision()` /
````

with:

````markdown
  operator's answers back for the runtime
- `config.py` — `load_config()` for `ooat.toml`: ledger URL, per-tier pins, connector settings, and the
  `[policy]` limits `blocked_countries` and `personal_data_regions` (ADR 0012); no secrets, no enablement
- `credentials_env.py` — `SecretResolver`: values from named environment variables, `redact()`
- `routing.py` — `RoutingPolicy` from `routing.json`: dated prices, optional tier allow-list, data-class policy
- `gateway.py` — `Gateway.estimate()` / `.call()`: data-class guard (the operator's responsibility stands in
  for a processing agreement, a region and no training; `[policy]` blocks countries and limits personal data to
  regions), acknowledgement and automation rules from the ledger, quota cool-down, pins, cheapest connector, contract budget, cost record with `estimated_usd`;
  passes the routed model to the connector in `ModelRequest.model`. `Gateway.estimate_decision()` /
````

Replace:

````markdown
  actions; state changes are `ADAPTER_ACKNOWLEDGED` / `ADAPTER_DISABLED` events by a named human;
  `acknowledgements()` is the connector state the gateway routes on
- `operator_cli.py` — the `ooat` command: `ooat connectors list | show | enable | disable`
````

with:

````markdown
  actions; state changes are `ADAPTER_ACKNOWLEDGED` / `ADAPTER_DISABLED` events by a named human;
  `acknowledgements()` is the connector state the gateway routes on. `acknowledge(..., responsibility, today)`
  records the operator's responsibility for client or personal data, which may carry those classes beyond the
  manifest when training is off; `responsibility_in_force()` (12 months) and `blocked_by_policy()` serve the
  gateway, the card and the listing
- `operator_cli.py` — the `ooat` command: `ooat connectors list | show | enable | disable`
````

In `docs/description.md`:

Replace:

````markdown
## Configuration
`ooat.toml` (operator preferences: ledger URL, per-tier pins, connector settings; secrets only as environment
variable names). Connector enablement is ledger state (`ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`, ADR 0010),
written by `ooat connectors enable | disable` after the operator has read the connection consequences card.
Prices and the data-class policy: `catalog/routing.json`. Dev dependencies: `requirements-dev.txt`, then
````

with:

````markdown
## Configuration
`ooat.toml` (operator preferences: ledger URL, per-tier pins, connector settings, `[policy]` limits on countries
and personal-data regions; secrets only as environment variable names). Connector enablement is ledger state
(`ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`, ADR 0010), written by `ooat connectors enable | disable` after the
operator has read the connection consequences card; for client or personal data the operator also takes
responsibility there (legal basis, processing agreement, region; ADR 0012), renewed every 12 months.
Prices and the data-class policy: `catalog/routing.json`. Dev dependencies: `requirements-dev.txt`, then
````

In `README.md`:

Replace:

````markdown
[ledger]
url = "sqlite:///ooat-ledger.sqlite"
```
````

with:

````markdown
[ledger]
url = "sqlite:///ooat-ledger.sqlite"

[policy]                          # optional limits, enforced by the gateway
blocked_countries = ["CN"]        # no connector whose vendor or model comes from these countries
personal_data_regions = ["eu"]    # personal data only to connectors processing in these regions
```
````

Replace:

````markdown
ooat connectors enable prv.anthropic.api --operator "Your Name"
```

`enable` and `disable` need an `ooat.toml`, so state always lands in the same ledger. Settings live in
````

with:

````markdown
ooat connectors enable prv.anthropic.api --operator "Your Name"
```

Choosing `client_confidential` or `personal` when enabling a connector asks you to take responsibility for that
data (legal basis, processing agreement, where it is processed). OOAT records it with your name and date and asks
again after 12 months. Text with an e-mail address, phone number or similar is treated as personal data, so allow
`personal` on at least one connector if your tasks contain such details.

`enable` and `disable` need an `ooat.toml`, so state always lands in the same ledger. Settings live in
````

In `tasks/f1-skeleton/task-03d-gateway-hardening/task.md`:

Replace:

````markdown
      other countries.
````

with:

````markdown
      other countries.

### From the review of PR #10
- [ ] Spec §4 rule A3 sends a task below `v_min` to T2 "without further calculation"; the Gate only records A3
      and may still close or clarify. Align the code or record the deviation in the spec v0.2 revision.
- [ ] Payment-card check: any 13–19 digit number passing Luhn (about 1 in 10, e.g. epoch-ms timestamps) raises a
      task to `personal`; require separators or an issuer prefix.
- [ ] An empty `narrow_scope` answer uses up a budget question without changing anything; ask again instead.
````

- [ ] **Step 2: Check**

Run: `python -m pytest -q` → Expected: `596 passed, 4 skipped`.
Run: `git grep -n "personal_data_regions" -- README.md core/description.md` → Expected: one line in each.

- [ ] **Step 3: Commit**

```bash
git add core/description.md docs/description.md README.md tasks/f1-skeleton/task-03d-gateway-hardening/task.md
git commit -m "docs: operator responsibility for client and personal data, [policy] limits"
```

---

## After the last task

- Owner, once: `ooat connectors enable prv.anthropic.subscription_cli --operator "<name>"` choosing `public,internal,personal` (and `client_confidential` if needed), answering the responsibility, regions and training questions; optionally add `[policy]` to `ooat.toml`.
- Next: plan 04c (task runtime and commands).

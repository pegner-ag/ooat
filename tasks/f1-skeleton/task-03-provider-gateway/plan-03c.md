# Connector Administration (03c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator see installed connectors, read each connection consequences card, and enable or disable a connector as a named human — `ooat connectors list | show | enable | disable` — so the gateway can route real calls.

**Architecture:** `connector_admin.py` holds the operator actions as plain functions over the registry and the ledger: statuses, the consequences card built only from manifest facts, `acknowledge()` (writes `ADAPTER_ACKNOWLEDGED` with allowed classes, `automation_confirmed` and the jurisdiction fingerprint) and `disable()` (`ADAPTER_DISABLED`). `operator_cli.py` is a thin argparse front end, installed as the `ooat` console script; it asks questions on stdin when flags are omitted and requires the connector id typed again as confirmation. The spec §9 staleness rule moves into `ooat_core.connectors` so gateway and CLI share it, and `connector_admin.acknowledgements()` becomes the connector state the gateway routes on, so `list` and routing cannot drift apart.

**Tech Stack:** Python 3.12+ standard library (`argparse`), pytest.

**Spec:** `tasks/f1-skeleton/task-03-provider-gateway/design.md` §5 (connector state, staleness) and §2 (plan 03c); spec `spec/ooat-specification.md` §9 (connection consequences card, rules 1–4); ADR 0010.

## Global Constraints

- Enabling and disabling are ledger events written with `actor.kind = hil` and a named operator; config never enables a connector.
- The card shows only manifest facts; unknown values are printed as `unknown`; the card says it is not legal advice (spec §9 rule 4).
- An acknowledgement allows only classes the manifest accepts; it never confirms automation for a manifest whose terms say `not_permitted`.
- Enabling requires the connector id typed again; a mismatch changes nothing.
- Manual relay and terms that forbid automation are never confirmed; an explicit `--automation yes` for them is refused, not ignored.
- An explicit `--config` that does not exist is refused; only an omitted flag falls back to defaults (a `disable` must never land in a stray ledger).
- `list` shows `[enabled, not usable unattended]` when the gateway would not route to an enabled connector; a failing `detect()` is reported, not raised.
- Code, comments, docs and messages in English.

## Review Focus

1. A connector whose terms forbid unattended use must never be confirmed, and the operator must not even be asked — `test_terms_that_forbid_automation_are_never_asked_and_never_confirmed` (Task 3), `test_acknowledge_refuses_what_the_connector_or_its_terms_do_not_allow` (Task 2).
2. A typo in the confirmation must leave the ledger unchanged — `test_wrong_confirmation_changes_nothing` (Task 3).
3. Pressing Enter at the class question must give the safe default (public, internal), not everything the connector accepts — `test_empty_class_answer_takes_the_safe_default` (Task 3).
4. A jurisdiction that changed after acknowledgement must show as stale in `list` — `test_status_reports_a_stale_jurisdiction` (Task 2).
5. A connector enabled through the CLI must be usable by the gateway without further steps — `test_acknowledged_connector_is_usable_by_the_gateway` (Task 2).

---

## File Structure

```
core/src/ooat_core/connectors/__init__.py   jurisdiction_stale() (Task 1)
core/src/ooat_core/gateway.py                uses jurisdiction_stale() (Task 1)
core/src/ooat_core/connector_admin.py        statuses, card, acknowledge, disable (Task 2)
core/src/ooat_core/operator_cli.py           `ooat` command (Task 3)
core/pyproject.toml                          console script (Task 3)
core/tests/test_connectors.py, test_connector_admin.py, test_operator_cli.py
```

How to apply a "replace" step: the old text occurs exactly once; replace it with the new text. Files may have CRLF line endings on Windows — match the text, not the line endings.

---

### Task 1: Shared jurisdiction staleness

**Files:**
- Modify: `core/src/ooat_core/connectors/__init__.py`, `core/src/ooat_core/gateway.py`
- Test: `core/tests/test_connectors.py`

**Interfaces:**
- Consumes: `jurisdiction_fingerprint` (03a).
- Produces: `jurisdiction_stale(manifest: dict, acknowledgement: dict, today: date) -> bool` in `ooat_core.connectors`; the gateway's private `_stale` is removed.

- [ ] **Step 1: Write the failing test**

In `core/tests/test_connectors.py`, replace:

```python
from ooat_core.connectors import ConnectorError, jurisdiction_fingerprint, registry
```

with:

```python
from datetime import date

from ooat_core.connectors import ConnectorError, jurisdiction_fingerprint, jurisdiction_stale, registry
```

In `core/tests/test_connectors.py`, replace:

```python
def test_connector_error_codes_are_the_schema_codes():
```

with:

```python
def test_jurisdiction_staleness_follows_spec_rule_2():
    manifest = fake_manifest()
    acknowledgement = {"jurisdiction_sha256": jurisdiction_fingerprint(manifest)}
    assert not jurisdiction_stale(manifest, acknowledgement, date(2026, 10, 1))
    assert jurisdiction_stale(manifest, acknowledgement, date(2027, 9, 2))  # verified_on older than 12 months
    assert jurisdiction_stale(manifest, {"jurisdiction_sha256": "0" * 64}, date(2026, 10, 1))
    assert jurisdiction_stale(manifest, {}, date(2026, 10, 1))  # acknowledgement from before ADR 0010
    unverified = fake_manifest(jurisdiction=dict(manifest["jurisdiction"], verified_on=None))
    assert jurisdiction_stale(unverified, {"jurisdiction_sha256": jurisdiction_fingerprint(unverified)},
                              date(2026, 10, 1))


def test_connector_error_codes_are_the_schema_codes():
```


- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_connectors.py -q`
Expected: FAIL — `ImportError: cannot import name 'jurisdiction_stale'`

- [ ] **Step 3: Implement**

In `core/src/ooat_core/connectors/__init__.py`, replace:

```python
import hashlib
import json
from dataclasses import dataclass
```

with:

```python
import hashlib
import json
from dataclasses import dataclass
from datetime import date
```

In `core/src/ooat_core/connectors/__init__.py`, replace:

```python
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

with:

```python
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def jurisdiction_stale(manifest: dict, acknowledgement: dict, today: date) -> bool:
    """Spec §9 rule 2: the jurisdiction changed since acknowledgement, or was not verified within 12 months.

    A stale connector stays enabled but refuses personal and special-category data until acknowledged again.
    """
    verified_on = manifest["jurisdiction"]["verified_on"]
    if verified_on is None or (today - date.fromisoformat(verified_on)).days > 365:
        return True
    return jurisdiction_fingerprint(manifest) != acknowledgement.get("jurisdiction_sha256")
```

In `core/src/ooat_core/gateway.py`, replace:

```python
from .connectors import ConnectorError, ModelConnector, ModelRequest, ModelResponse, jurisdiction_fingerprint
```

with:

```python
from .connectors import ConnectorError, ModelConnector, ModelRequest, ModelResponse, jurisdiction_stale
```

In `core/src/ooat_core/gateway.py`, replace:

```python
        if data_class in _PERSONAL_OR_HIGHER and self._stale(manifest, acknowledgement):
```

with:

```python
        if data_class in _PERSONAL_OR_HIGHER and jurisdiction_stale(manifest, acknowledgement, self._clock().date()):
```

In `core/src/ooat_core/gateway.py`, replace:

```python
    def _stale(self, manifest: dict, acknowledgement: dict) -> bool:
        verified_on = manifest["jurisdiction"]["verified_on"]
        if verified_on is None or (self._clock().date() - date.fromisoformat(verified_on)).days > 365:
            return True
        return jurisdiction_fingerprint(manifest) != acknowledgement.get("jurisdiction_sha256")
```

with:

```python

```

In `core/src/ooat_core/gateway.py`, replace:

```python
from datetime import date, datetime, timedelta, timezone
```

with:

```python
from datetime import datetime, timedelta, timezone
```


- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/connectors/__init__.py core/src/ooat_core/gateway.py core/tests/test_connectors.py
git commit -m "core: share the jurisdiction staleness rule between gateway and operator tools"
```

---

### Task 2: Operator actions on connectors

**Files:**
- Create: `core/src/ooat_core/connector_admin.py`
- Modify: `core/src/ooat_core/gateway.py` (routes on `acknowledgements()`)
- Test: `core/tests/test_connector_admin.py`

**Interfaces:**
- Consumes: `Registry`, `BrokenConnector`, `ModelConnector`, `jurisdiction_fingerprint`, `jurisdiction_stale`; `Ledger`, `new_event`, `DATA_CLASSES`; `Gateway`, `RoutingPolicy`, `Config` (test only).
- Produces: `ConnectorStatus(id, state, detail, tiers, automation, stale, unattended)`; `latest_state_events(events) -> dict`; `acknowledgements(events) -> dict[str, dict]` (used by the gateway); `unattended_forbidden(manifest) -> str | None`; with `state` ∈ `enabled | disabled | not acknowledged | broken`; `connector_statuses(registry, ledger, today) -> list[ConnectorStatus]`; `consequences_card(manifest, today) -> str`; `acknowledge(ledger, connector, operator, data_classes, automation_confirmed) -> dict` (`ValueError` for an empty operator, no or unknown classes, classes the manifest does not accept, or automation for `not_permitted` terms or manual relay); `disable(ledger, connector_id, operator, reason) -> dict`; constants `DATA_CLASS_ORDER`, `DEFAULT_CLASSES = ("public", "internal")`.

- [ ] **Step 1: Write the failing test** — `core/tests/test_connector_admin.py`:

```python
from datetime import date

import pytest
from connector_fakes import JURISDICTION, FakeConnector, fake_manifest

from ooat_core.config import Config
from ooat_core.connector_admin import acknowledge, connector_statuses, consequences_card, disable
from ooat_core.connectors import ModelRequest
from ooat_core.connectors.registry import BrokenConnector, Registry
from ooat_core.gateway import Gateway
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger
from ooat_core.routing import RoutingPolicy

TODAY = date(2026, 10, 1)
POLICY = {"public": {"allowed": True}, "internal": {"allowed": True}, "client_confidential": {"allowed": True},
          "personal": {"allowed": True}, "special_category": {"allowed": True, "require_verified_redaction": True}}


@pytest.fixture
def ledger():
    led = Ledger.open("sqlite:///:memory:")
    yield led
    led.close()


def test_card_shows_unknown_facts_as_unknown_and_is_not_legal_advice():
    unknown = {key: None for key in JURISDICTION} | {"source_urls": []}
    card = consequences_card(fake_manifest(jurisdiction=unknown), TODAY)
    assert "Vendor entity:        unknown" in card
    assert "never - personal and special-category data stay refused" in card
    assert "not legal advice" in card and "unknown - check your plan's terms" in card


def test_card_shows_verified_facts_and_warns_when_they_are_old():
    card = consequences_card(fake_manifest(), TODAY)
    assert "Fake Vendor Ltd" in card and "Facts verified on:      2026-09-01" in card
    assert "Training on inputs:   no" in card
    assert "older than 12 months" in consequences_card(fake_manifest(), date(2027, 10, 1))


def test_acknowledge_then_disable_changes_the_state(ledger):
    connector = FakeConnector()
    registry = Registry([connector], broken=[BrokenConnector("prv.bad.api", "ImportError: x")])
    states = {s.id: s.state for s in connector_statuses(registry, ledger, TODAY)}
    assert states == {"prv.fake.api": "not acknowledged", "prv.bad.api": "broken"}
    event = acknowledge(ledger, connector, " Martin ", ["internal", "public"], automation_confirmed=True)
    assert event["actor"] == {"kind": "hil", "id": "Martin"}
    assert event["body"]["allowed_data_classes"] == ["public", "internal"]
    assert connector_statuses(registry, ledger, TODAY)[0].state == "enabled"
    disable(ledger, "prv.fake.api", "Martin", "trial ended")
    assert connector_statuses(registry, ledger, TODAY)[0].state == "disabled"


def test_status_reports_a_stale_jurisdiction(ledger):
    connector = FakeConnector()
    acknowledge(ledger, connector, "Martin", ["public"], automation_confirmed=True)
    connector.manifest = fake_manifest(jurisdiction=dict(JURISDICTION, processing_regions=["us"]))
    assert connector_statuses(Registry([connector]), ledger, TODAY)[0].stale


@pytest.mark.parametrize("classes, automation, manifest, message", [
    (["public"], True, fake_manifest(automation="not_permitted"), "do not permit"),
    (["special_category"], False, fake_manifest(), "does not accept"),
    (["secret"], False, fake_manifest(), "unknown data classes"),
    ([], False, fake_manifest(), "at least one"),
])
def test_acknowledge_refuses_what_the_connector_or_its_terms_do_not_allow(ledger, classes, automation, manifest, message):
    with pytest.raises(ValueError, match=message):
        acknowledge(ledger, FakeConnector(manifest), "Martin", classes, automation)
    assert ledger.events() == []


def test_acknowledge_and_disable_need_a_named_operator(ledger):
    with pytest.raises(ValueError):
        acknowledge(ledger, FakeConnector(), "  ", ["public"], True)
    with pytest.raises(ValueError):
        disable(ledger, "prv.fake.api", "Martin", " ")


def test_acknowledged_connector_is_usable_by_the_gateway(ledger):
    connector = FakeConnector()
    acknowledge(ledger, connector, "Martin", ["public", "internal"], automation_confirmed=True)
    routing = RoutingPolicy({"version": "0.1.0", "data_class_policy": POLICY, "prices": [
        {"adapter": "prv.fake.api", "model": "fake-model", "usd_per_mtok_in": 1, "usd_per_mtok_out": 5,
         "valid_from": "2026-01-01", "source": "https://fake.invalid/pricing"}]})
    gateway = Gateway(ledger, Registry([connector]), routing, Config())
    request = ModelRequest(tier="workhorse", prompt="x", data_class="internal", task=new_id("tsk"))
    assert gateway.call(request).cost["adapter"] == "prv.fake.api"


def test_manual_relay_can_never_be_confirmed_for_unattended_use(ledger):
    manual = fake_manifest("prv.fake.subscription_manual", "subscription_manual")
    manual["metering"] = "none"
    with pytest.raises(ValueError, match="manual relay"):
        acknowledge(ledger, FakeConnector(manual), "Martin", ["public"], automation_confirmed=True)


def test_one_faulty_detect_does_not_break_the_listing(ledger):
    faulty = FakeConnector(fake_manifest("prv.faulty.api"))
    faulty.detect = lambda: (_ for _ in ()).throw(OSError("probe crashed"))
    details = {s.id: s.detail for s in connector_statuses(Registry([faulty, FakeConnector()]), ledger, TODAY)}
    assert details["prv.faulty.api"].startswith("detect failed: OSError")
    assert details["prv.fake.api"] == "fake connector"


def test_unconfirmed_acknowledgement_is_enabled_but_not_unattended(ledger):
    connector = FakeConnector()
    acknowledge(ledger, connector, "Martin", ["public"], automation_confirmed=False)
    (status,) = connector_statuses(Registry([connector]), ledger, TODAY)
    assert status.state == "enabled" and not status.unattended
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_connector_admin.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.connector_admin'`

- [ ] **Step 3: Implement** — `core/src/ooat_core/connector_admin.py`:

```python
"""Operator actions on connectors: status, the connection consequences card, acknowledge, disable (spec §9, ADR 0010).

Connector state is ledger state: acknowledging writes ADAPTER_ACKNOWLEDGED, disabling writes ADAPTER_DISABLED, both
by a named human. The card only shows what the manifest states; unknown facts are shown as unknown, never guessed.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from .connectors import ModelConnector, jurisdiction_fingerprint, jurisdiction_stale
from .connectors.registry import Registry
from .ledger import DATA_CLASSES, Ledger, new_event

DATA_CLASS_ORDER = ["public", "internal", "client_confidential", "personal", "special_category"]
DEFAULT_CLASSES = ("public", "internal")
_STATE_EVENTS = ["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"]


@dataclass(frozen=True)
class ConnectorStatus:
    id: str
    state: str  # enabled | disabled | not acknowledged | broken
    detail: str
    tiers: dict
    automation: str
    stale: bool
    unattended: bool  # the gateway may route to it: enabled, terms allow it, operator confirmed


def latest_state_events(events: Iterable[dict]) -> dict[str, dict]:
    """The latest ADAPTER_ACKNOWLEDGED or ADAPTER_DISABLED event per connector."""
    latest = {}
    for event in events:
        if event["type"] in _STATE_EVENTS:
            latest[event["body"]["adapter"]] = event
    return latest


def acknowledgements(events: Iterable[dict]) -> dict[str, dict]:
    """Bodies of the acknowledgements in force: the connectors whose latest state event enables them."""
    return {connector_id: event["body"] for connector_id, event in latest_state_events(events).items()
            if event["type"] == "ADAPTER_ACKNOWLEDGED"}


def unattended_forbidden(manifest: dict) -> str | None:
    """Why this connector can never be confirmed for unattended use, or None (ADR 0010 §3)."""
    if manifest["automation_permitted"] == "not_permitted":
        return "the provider's terms do not permit unattended use"
    if manifest["access"] == "subscription_manual":
        return "manual relay is never used unattended"
    return None


def connector_statuses(registry: Registry, ledger: Ledger, today: date) -> list[ConnectorStatus]:
    latest, statuses = latest_state_events(ledger.events(types=_STATE_EVENTS)), []
    for connector_id in registry.ids():
        connector = registry.get(connector_id)
        event = latest.get(connector_id)
        state, stale, unattended = "not acknowledged", False, False
        if event is not None and event["type"] == "ADAPTER_DISABLED":
            state = "disabled"
        elif event is not None:
            state, stale = "enabled", jurisdiction_stale(connector.manifest, event["body"], today)
            unattended = (event["body"].get("automation_confirmed") is True
                          and unattended_forbidden(connector.manifest) is None)
        try:
            detail = connector.detect().detail
        except Exception as error:  # plugin code: one faulty connector must not break the listing
            detail = f"detect failed: {type(error).__name__}: {error}"
        statuses.append(ConnectorStatus(connector_id, state, detail, dict(connector.manifest["tiers"]),
                                        connector.manifest["automation_permitted"], stale, unattended))
    for broken in registry.broken:
        statuses.append(ConnectorStatus(broken.name, "broken", broken.error, {}, "unknown", False, False))
    return statuses


def _value(value, unknown: str = "unknown") -> str:
    if value is None:
        return unknown
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(value) if value else "none"
    return str(value)


def consequences_card(manifest: dict, today: date) -> str:
    """Plain-text connection consequences card built from the manifest (spec §9 rule 1)."""
    jurisdiction, policy = manifest["jurisdiction"], manifest["data_policy"]
    verified_on = jurisdiction["verified_on"]
    if verified_on is None:
        verified = "never - personal and special-category data stay refused until the facts are verified"
    elif (today - date.fromisoformat(verified_on)).days > 365:
        verified = f"{verified_on} - older than 12 months; personal data stays refused until verified again"
    else:
        verified = verified_on
    terms = {"permitted": "the provider's terms permit unattended use",
             "not_permitted": "the provider's terms do NOT permit unattended use; OOAT will not run it unattended",
             "unknown": "unknown - check your plan's terms before confirming"}[manifest["automation_permitted"]]
    lines = [
        f"Connection consequences: {manifest['id']} ({manifest['vendor']}, {manifest['access']}), "
        f"manifest {manifest['version']}",
        "",
        "Who processes the data",
        f"  Vendor entity:        {_value(jurisdiction['vendor_entity'])}",
        f"  Vendor country:       {_value(jurisdiction['vendor_country'])}",
        f"  Host entity:          {_value(jurisdiction['host_entity'])}",
        f"  Processing regions:   {_value(jurisdiction['processing_regions'])}",
        f"  EU region available:  {_value(jurisdiction['eu_region_available'])}",
        f"  Model origin:         {_value(jurisdiction['model_origin_country'])}",
        "What happens to inputs",
        f"  Training on inputs:   {_value(policy['training_on_inputs'])}",
        f"  Retention:            {_value(jurisdiction['retention'])}",
        f"  Zero retention:       {_value(jurisdiction['zero_retention_available'])}",
        f"  Transfer notes:       {_value(jurisdiction['transfer_notes'], 'none')}",
        f"Sources:                {_value(jurisdiction['source_urls'])}",
        f"Facts verified on:      {verified}",
        f"Unattended use:         {terms}",
        f"Classes this connector accepts: {_value(policy['allowed_data_classes'])}",
        "",
        "This card repeats the facts in the connector manifest. It is not legal advice: you decide, and answer for,",
        "which data may go to this connection.",
    ]
    return "\n".join(lines)


def acknowledge(ledger: Ledger, connector: ModelConnector, operator: str, data_classes: Iterable[str],
                automation_confirmed: bool) -> dict:
    """Enable a connector: a named operator allows data classes and states whether automation is confirmed."""
    manifest = connector.manifest
    operator = operator.strip()
    if not operator:
        raise ValueError("a named operator is required")
    requested = set(data_classes)
    if not requested:
        raise ValueError("allow at least one data class")
    unknown = sorted(requested - DATA_CLASSES)
    if unknown:
        raise ValueError(f"unknown data classes: {unknown}")
    classes = [c for c in DATA_CLASS_ORDER if c in requested]
    beyond = [c for c in classes if c not in manifest["data_policy"]["allowed_data_classes"]]
    if beyond:
        raise ValueError(f"{manifest['id']} does not accept {beyond}")
    forbidden = unattended_forbidden(manifest)
    if automation_confirmed and forbidden:
        raise ValueError(f"{manifest['id']}: {forbidden}; it cannot be confirmed")
    return ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor={"kind": "hil", "id": operator}, body={
        "adapter": manifest["id"], "manifest_version": manifest["version"], "allowed_data_classes": classes,
        "operator": operator, "automation_confirmed": automation_confirmed,
        "jurisdiction_sha256": jurisdiction_fingerprint(manifest)}))


def disable(ledger: Ledger, connector_id: str, operator: str, reason: str) -> dict:
    operator, reason = operator.strip(), reason.strip()
    if not operator or not reason:
        raise ValueError("a named operator and a reason are required")
    return ledger.append(new_event("ADAPTER_DISABLED", task=None, actor={"kind": "hil", "id": operator},
                                   body={"adapter": connector_id, "operator": operator, "reason": reason}))
```

The gateway routes on the same state:

In `core/src/ooat_core/gateway.py`, replace:

```python
from .config import Config
```

with:

```python
from .config import Config
from .connector_admin import acknowledgements
```

In `core/src/ooat_core/gateway.py`, replace:

```python
        acknowledgements, cooldowns = self._acknowledgements(events), self._cooldowns(events)
```

with:

```python
        acknowledged, cooldowns = acknowledgements(events), self._cooldowns(events)
```

In `core/src/ooat_core/gateway.py`, replace:

```python
            reason = self._exclusion(connector, request, acknowledgements.get(connector_id), cooldowns)
```

with:

```python
            reason = self._exclusion(connector, request, acknowledged.get(connector_id), cooldowns)
```

In `core/src/ooat_core/gateway.py`, replace:

```python
    @staticmethod
    def _acknowledgements(events: list[dict]) -> dict[str, dict]:
        state: dict[str, dict | None] = {}
        for event in events:
            if event["type"] == "ADAPTER_ACKNOWLEDGED":
                state[event["body"]["adapter"]] = event["body"]
            elif event["type"] == "ADAPTER_DISABLED":
                state[event["body"]["adapter"]] = None
        return {connector_id: body for connector_id, body in state.items() if body is not None}
```

with:

```python

```


- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/connector_admin.py core/src/ooat_core/gateway.py core/tests/test_connector_admin.py
git commit -m "core: connector statuses, consequences card, acknowledge and disable; gateway routes on the same state"
```

---

### Task 3: The `ooat connectors` command

**Files:**
- Create: `core/src/ooat_core/operator_cli.py`
- Modify: `core/pyproject.toml`
- Test: `core/tests/test_operator_cli.py`

**Interfaces:**
- Consumes: `connector_admin` (Task 2); `load_config`, `Config`; `Registry.discover()`; `Ledger`.
- Produces: `main(argv=None, stdin=None, stdout=None, registry=None, today=None) -> int` (0 done, 1 refused, argparse exits 2 on usage errors); console script `ooat`. Commands: `ooat [--config PATH] connectors list`, `show ID`, `enable ID --operator NAME [--classes a,b] [--automation yes|no] [--confirm ID]`, `disable ID --operator NAME --reason TEXT`.

- [ ] **Step 1: Write the failing test** — `core/tests/test_operator_cli.py`:

```python
import io
from datetime import date

import pytest
from connector_fakes import FakeConnector, fake_manifest

from ooat_core.operator_cli import main
from ooat_core.connectors.registry import Registry
from ooat_core.ledger import Ledger

TODAY = date(2026, 10, 1)


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "ooat.toml"
    url = f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}"
    path.write_text(f'[ledger]\nurl = "{url}"\n', encoding="utf-8")
    return path, url


def run(config, *argv, answers="", connectors=None):
    stdout = io.StringIO()
    registry = Registry(connectors if connectors is not None else [FakeConnector()])
    code = main(["--config", str(config[0]), *argv], stdin=io.StringIO(answers), stdout=stdout,
                registry=registry, today=TODAY)
    return code, stdout.getvalue()


def state_events(config):
    ledger = Ledger.open(config[1])
    events = ledger.events(types=["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"])
    ledger.close()
    return events


def test_list_shows_installed_connectors_and_their_state(config):
    code, out = run(config, "connectors", "list")
    assert code == 0 and "prv.fake.api  [not acknowledged]" in out and "tiers: workhorse=fake-model" in out


def test_show_prints_the_card_without_changing_anything(config):
    code, out = run(config, "connectors", "show", "prv.fake.api")
    assert code == 0 and "Connection consequences: prv.fake.api" in out
    assert state_events(config) == []


def test_interactive_enable_records_the_answers(config):
    code, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin",
                    answers="public, internal\nyes\nprv.fake.api\n")
    assert code == 0 and "enabled for public, internal; unattended use confirmed" in out
    (event,) = state_events(config)
    assert event["body"]["allowed_data_classes"] == ["public", "internal"]
    assert event["body"]["automation_confirmed"] is True and event["actor"]["id"] == "Martin"


def test_empty_class_answer_takes_the_safe_default(config):
    code, _ = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin",
                  answers="\nno\nprv.fake.api\n")
    assert code == 0 and state_events(config)[0]["body"]["allowed_data_classes"] == ["public", "internal"]
    assert state_events(config)[0]["body"]["automation_confirmed"] is False


def test_wrong_confirmation_changes_nothing(config):
    code, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin",
                    answers="public\nyes\nprv.fake\n")
    assert code == 1 and "did not match" in out and state_events(config) == []


def test_non_interactive_enable_with_flags(config):
    code, _ = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin", "--classes", "public",
                  "--automation", "no", "--confirm", "prv.fake.api")
    assert code == 0 and state_events(config)[0]["body"]["allowed_data_classes"] == ["public"]


def test_terms_that_forbid_automation_are_never_asked_and_never_confirmed(config):
    connector = FakeConnector(fake_manifest(automation="not_permitted"))
    code, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin",
                    answers="public\nprv.fake.api\n", connectors=[connector])
    assert code == 0 and "Do the terms of your plan allow" not in out
    assert state_events(config)[0]["body"]["automation_confirmed"] is False


def test_refused_classes_report_and_change_nothing(config):
    code, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin",
                    "--classes", "special_category", "--automation", "no", "--confirm", "prv.fake.api")
    assert code == 1 and "Refused" in out and state_events(config) == []


def test_unknown_connector_is_reported(config):
    code, out = run(config, "connectors", "show", "prv.missing.api")
    assert code == 1 and "not installed" in out


def test_disable_records_operator_and_reason(config):
    code, _ = run(config, "connectors", "disable", "prv.fake.api", "--operator", "Martin", "--reason", "trial ended")
    assert code == 0 and state_events(config)[0]["body"] == {
        "adapter": "prv.fake.api", "operator": "Martin", "reason": "trial ended"}


def test_disable_with_a_malformed_id_is_refused(config):
    code, out = run(config, "connectors", "disable", "anthropic", "--operator", "Martin", "--reason", "x")
    assert code == 1 and "Refused" in out


def test_console_script_is_installed():
    from importlib.metadata import entry_points

    (script,) = [e for e in entry_points(group="console_scripts") if e.name == "ooat"]
    assert script.value == "ooat_core.operator_cli:main"


def test_missing_explicit_config_is_refused_and_writes_no_ledger(tmp_path):
    stdout = io.StringIO()
    code = main(["--config", str(tmp_path / "typo.toml"), "connectors", "disable", "prv.fake.api", "--operator", "M",
                 "--reason", "x"], stdin=io.StringIO(), stdout=stdout, registry=Registry([FakeConnector()]),
                today=TODAY)
    assert code == 1 and "not found" in stdout.getvalue()
    assert list(tmp_path.iterdir()) == []


def test_list_tells_when_an_enabled_connector_is_not_usable_unattended(config):
    run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin", "--classes", "public",
        "--automation", "no", "--confirm", "prv.fake.api")
    _, out = run(config, "connectors", "list")
    assert "[enabled, not usable unattended]" in out


def test_explicit_yes_for_forbidding_terms_is_refused(config):
    connector = FakeConnector(fake_manifest(automation="not_permitted"))
    code, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin", "--classes", "public",
                    "--automation", "yes", "--confirm", "prv.fake.api", connectors=[connector])
    assert code == 1 and "do not permit" in out and state_events(config) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest core/tests/test_operator_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.operator_cli'`

- [ ] **Step 3: Implement** — `core/src/ooat_core/operator_cli.py`:

```python
"""`ooat` command line: operator commands. Currently `ooat connectors list | show | enable | disable`."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import connector_admin
from .config import Config, load_config
from .connectors.registry import Registry
from .ledger import Ledger

REFUSED = 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ooat", description="OOAT operator commands.")
    parser.add_argument("--config", help="operator config (default: ./ooat.toml if present)")
    commands = parser.add_subparsers(dest="command", required=True)
    connectors = commands.add_parser("connectors", help="list, inspect, enable or disable model connectors")
    actions = connectors.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="installed connectors and their state")
    show = actions.add_parser("show", help="print the connection consequences card")
    show.add_argument("connector")
    enable = actions.add_parser("enable", help="acknowledge the consequences card and enable a connector")
    enable.add_argument("connector")
    enable.add_argument("--operator", required=True, help="your name; recorded as the approver")
    enable.add_argument("--classes", help="comma-separated data classes to allow (asked when omitted)")
    enable.add_argument("--automation", choices=["yes", "no"],
                        help="whether your plan's terms allow unattended use (asked when omitted)")
    enable.add_argument("--confirm", help="the connector id, typed again to confirm (asked when omitted)")
    disable = actions.add_parser("disable", help="disable a connector")
    disable.add_argument("connector")
    disable.add_argument("--operator", required=True)
    disable.add_argument("--reason", required=True)
    return parser


def _ask(prompt: str, stdin, stdout) -> str:
    stdout.write(prompt)
    stdout.flush()
    return stdin.readline().strip()


def main(argv=None, stdin=None, stdout=None, registry: Registry | None = None, today=None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    args = _parser().parse_args(argv)
    if args.config is not None and not Path(args.config).exists():
        # An explicit config that is missing must not fall back to a default ledger: a disable would land elsewhere.
        stdout.write(f"Config file not found: {args.config}\n")
        return REFUSED
    path = args.config or "ooat.toml"
    config = load_config(path) if Path(path).exists() else Config()
    registry = registry or Registry.discover()
    today = today or datetime.now(timezone.utc).date()
    ledger = Ledger.open(config.ledger_url)
    try:
        return _connectors(args, ledger, registry, today, stdin, stdout)
    finally:
        ledger.close()


def _connectors(args, ledger, registry, today, stdin, stdout) -> int:
    if args.action == "list":
        for status in connector_admin.connector_statuses(registry, ledger, today):
            state = status.state
            if state == "enabled" and not status.unattended:
                state += ", not usable unattended"
            stale = " (jurisdiction stale: personal data refused)" if status.stale else ""
            tiers = ", ".join(f"{tier}={model or 'set in ooat.toml'}" for tier, model in status.tiers.items())
            stdout.write(f"{status.id}  [{state}]{stale}\n  {status.detail}\n")
            if tiers:
                stdout.write(f"  tiers: {tiers}; unattended use per terms: {status.automation}\n")
        return 0
    if args.action == "disable":  # also allowed for a connector that is no longer installed
        try:
            connector_admin.disable(ledger, args.connector, args.operator, args.reason)
        except ValueError as error:  # includes SpecValidationError, e.g. a malformed connector id
            stdout.write(f"Refused: {error}\n")
            return REFUSED
        stdout.write(f"{args.connector} disabled.\n")
        return 0
    connector = registry.get(args.connector)
    if connector is None:
        stdout.write(f"{args.connector} is not installed (see `ooat connectors list`).\n")
        return REFUSED
    stdout.write(connector_admin.consequences_card(connector.manifest, today) + "\n")
    if args.action == "show":
        return 0
    return _enable(args, ledger, connector, stdin, stdout)


def _enable(args, ledger, connector, stdin, stdout) -> int:
    accepted = connector.manifest["data_policy"]["allowed_data_classes"]
    default = [c for c in connector_admin.DEFAULT_CLASSES if c in accepted]
    answer = args.classes if args.classes is not None else _ask(
        f"\nData classes to allow [{','.join(default)}]: ", stdin, stdout)
    classes = [c.strip() for c in answer.split(",") if c.strip()] or default
    forbidden = connector_admin.unattended_forbidden(connector.manifest)
    if forbidden and args.automation == "yes":
        stdout.write(f"Refused: {forbidden}; nothing was changed.\n")
        return REFUSED
    if forbidden:
        automation = False
    else:
        automation_answer = args.automation or _ask(
            "Do the terms of your plan allow unattended automated use? (yes/no): ", stdin, stdout).lower()
        if automation_answer not in ("yes", "no"):
            stdout.write("Answer yes or no; nothing was changed.\n")
            return REFUSED
        automation = automation_answer == "yes"
    confirmation = args.confirm if args.confirm is not None else _ask(
        f"Type {connector.manifest['id']} to confirm: ", stdin, stdout)
    if confirmation != connector.manifest["id"]:
        stdout.write("Confirmation did not match; nothing was changed.\n")
        return REFUSED
    try:
        connector_admin.acknowledge(ledger, connector, args.operator, classes, automation)
    except ValueError as error:
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    if forbidden:
        mode = f"{forbidden}"
    else:
        mode = "unattended use confirmed" if automation else "not used unattended until automation is confirmed"
    stdout.write(f"{connector.manifest['id']} enabled for {', '.join(classes)}; {mode}.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

In `core/pyproject.toml`, replace:

```
[tool.hatch.build.targets.wheel]
```

with:

```
[project.scripts]
ooat = "ooat_core.operator_cli:main"

[tool.hatch.build.targets.wheel]
```


Reinstall so the console script exists: `python -m pip install -e core`

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q`
Expected: PASS. Smoke check: `ooat connectors list` prints the installed connectors with `[not acknowledged]`.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/operator_cli.py core/pyproject.toml core/tests/test_operator_cli.py
git commit -m "core: ooat connectors list | show | enable | disable"
```

---

### Task 4: Documentation

**Files:**
- Modify: `core/description.md`, `docs/description.md`, `tasks/f1-skeleton/README.md`, `README.md`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: As-is documentation and a first-steps section in the README.

- [ ] **Step 1: Update the documents**

In `core/description.md`, replace:

```markdown
- `connectors/conformance.py` — `check_connector()`: the contract every connector package tests
```

with:

```markdown
- `connectors/conformance.py` — `check_connector()`: the contract every connector package tests;
  `jurisdiction_stale()` in `connectors/__init__.py` is the spec §9 rule 2 check shared by gateway and CLI
- `connector_admin.py` — `connector_statuses()`, `consequences_card()`, `acknowledge()`, `disable()`: operator
  actions; state changes are `ADAPTER_ACKNOWLEDGED` / `ADAPTER_DISABLED` events by a named human;
  `acknowledgements()` is the connector state the gateway routes on
- `operator_cli.py` — the `ooat` command: `ooat connectors list | show | enable | disable`
```

In `core/description.md`, replace:

```markdown
`Gateway`, `Registry.discover()`, `load_config()`, `load_routing()`, `SecretResolver`.
```

with:

```markdown
`Gateway`, `Registry.discover()`, `load_config()`, `load_routing()`, `SecretResolver`, `connector_admin`, the `ooat`
console script.
```

In `docs/description.md`, replace:

```markdown
variable names). Connector enablement is ledger state (`ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`, ADR 0010).
```

with:

```markdown
variable names). Connector enablement is ledger state (`ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`, ADR 0010),
written by `ooat connectors enable | disable` after the operator has read the connection consequences card.
```

In `tasks/f1-skeleton/README.md`, replace:

```markdown
03c `ooat connectors` + consequences card | 01 | 03c next |
```

with:

```markdown
03c `ooat connectors` + consequences card (done) | 01 | done |
```

In `README.md`, replace:

```markdown
## Repository layout
```

with:

```markdown
## First steps

```sh
python -m pip install -e core -e adapters/claude-code -e adapters/codex -e adapters/anthropic-api
ooat connectors list                      # installed connectors and their state
ooat connectors show prv.anthropic.api    # connection consequences card
ooat connectors enable prv.anthropic.api --operator "Your Name"
```

Settings live in `ooat.toml` (ledger URL, per-tier pins, connector settings; secrets only as environment
variable names); prices and the data-class policy in `catalog/routing.json`.

## Repository layout
```


- [ ] **Step 2: Run all tests**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add core/description.md docs/description.md tasks/f1-skeleton/README.md README.md
git commit -m "docs: connector administration and first steps"
```

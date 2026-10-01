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

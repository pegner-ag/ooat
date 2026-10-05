"""Operator actions on connectors: status, the connection consequences card, acknowledge, disable (spec §9, ADR 0010).

Connector state is ledger state: acknowledging writes ADAPTER_ACKNOWLEDGED, disabling writes ADAPTER_DISABLED, both
by a named human. The card only shows what the manifest states; unknown facts are shown as unknown, never guessed.
Client and personal data need the operator's responsibility (ADR 0012), which may extend a connector beyond the
classes its manifest accepts; the operator's [policy] in ooat.toml can block countries and limit personal data to
regions.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from .config import Config
from .connectors import ModelConnector, jurisdiction_fingerprint, jurisdiction_stale
from .connectors.registry import Registry
from .ledger import DATA_CLASSES, Ledger, new_event

DATA_CLASS_ORDER = ["public", "internal", "client_confidential", "personal", "special_category"]
DEFAULT_CLASSES = ("public", "internal")
RESPONSIBLE_CLASSES = ("client_confidential", "personal")  # need the operator's responsibility (ADR 0012)
RESPONSIBILITY_DAYS = 365
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
    responsibility_until: str | None = None  # last day the operator's responsibility is in force
    blocked: str | None = None  # why the operator's policy blocks it


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


def responsibility_in_force(acknowledgement: dict | None, today: date) -> dict | None:
    """The operator's responsibility for client or personal data, if given within the last 12 months."""
    responsibility = (acknowledgement or {}).get("responsibility")
    if responsibility is None:
        return None
    age = (today - date.fromisoformat(responsibility["confirmed_on"])).days
    if not 0 <= age <= RESPONSIBILITY_DAYS:  # a date in the future is not a confirmation
        return None
    return responsibility


def provider_trains(manifest: dict) -> bool | None:
    """True if either manifest block says the provider trains on inputs, False if the data policy says it does
    not (and nothing says it does), None when unknown."""
    stated = (manifest["data_policy"]["training_on_inputs"], manifest["jurisdiction"]["training_on_inputs"])
    if True in stated:
        return True
    return False if stated[0] is False else None


def may_extend(manifest: dict, responsibility: dict | None) -> bool:
    """Whether a responsibility may carry client or personal data beyond the manifest (ADR 0012 point 3)."""
    trains = provider_trains(manifest)
    return responsibility is not None and trains is not True and (
        trains is False or responsibility.get("no_training") is True)


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
    """Why this connector can never be confirmed for unattended use, or None (ADR 0010 §3)."""
    if manifest["automation_permitted"] == "not_permitted":
        return "the provider's terms do not permit unattended use"
    if manifest["access"] == "subscription_manual":
        return "manual relay is never used unattended"
    return None


def connector_statuses(registry: Registry, ledger: Ledger, today: date,
                       config: Config | None = None) -> list[ConnectorStatus]:
    latest, statuses = latest_state_events(ledger.events(types=_STATE_EVENTS)), []
    for connector_id in registry.ids():
        connector = registry.get(connector_id)
        event = latest.get(connector_id)
        state, stale, unattended, until = "not acknowledged", False, False, None
        if event is not None and event["type"] == "ADAPTER_DISABLED":
            state = "disabled"
        elif event is not None:
            responsibility = responsibility_in_force(event["body"], today)
            state = "enabled"
            stale = jurisdiction_stale(connector.manifest, event["body"], today, responsibility is not None)
            unattended = (event["body"].get("automation_confirmed") is True
                          and unattended_forbidden(connector.manifest) is None)
            if responsibility is not None:
                confirmed = date.fromisoformat(responsibility["confirmed_on"])
                until = date.fromordinal(confirmed.toordinal() + RESPONSIBILITY_DAYS).isoformat()
        try:
            detail = connector.detect().detail
        except Exception as error:  # plugin code: one faulty connector must not break the listing
            detail = f"detect failed: {type(error).__name__}: {error}"
        statuses.append(ConnectorStatus(connector_id, state, detail, dict(connector.manifest["tiers"]),
                                        connector.manifest["automation_permitted"], stale, unattended, until,
                                        blocked_by_policy(connector.manifest, config)))
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


def consequences_card(manifest: dict, today: date, config: Config | None = None) -> str:
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
        "Client or personal data (client_confidential, personal)",
        "  Only when you take responsibility: you have a legal basis, a processing agreement with the provider,",
        "  and you know where it processes. OOAT records your name and the date, and asks again after 12 months",
        "  or when these facts change. It may then also carry these classes beyond the list above, if training",
        "  on your inputs is off.",
    ]
    if config is not None:
        blocked = blocked_by_policy(manifest, config)
        lines.append(f"Your policy:            {blocked or 'does not block this connector'}")
        unknown = [label for label, key in (("vendor country", "vendor_country"),
                                            ("model origin", "model_origin_country"))
                   if jurisdiction[key] is None]
        if config.blocked_countries and unknown and not blocked:
            lines.append(f"  Note: {' and '.join(unknown)} unknown - your country block cannot check them")
        if config.personal_data_regions is not None:
            lines.append(f"  Personal data only processed in: {_value(sorted(config.personal_data_regions))}")
    lines += [
        "",
        "This card repeats the facts in the connector manifest. It is not legal advice: you decide, and answer for,",
        "which data may go to this connection.",
    ]
    return "\n".join(lines)


RESERVED_NAMES = frozenset({"default-on-silence"})  # the runtime applying a declared default (design 04 §5)


def checked_operator(name: str) -> str:
    """The approver's name as recorded: required, one line, no control characters, not a reserved name."""
    name = name.strip()
    if not name:
        raise ValueError("a named operator is required")
    if name.lower() in RESERVED_NAMES:
        raise ValueError(f"{name!r} is reserved for answers OOAT applies on silence")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValueError("the operator name may not contain line breaks or control characters")
    return name


def checked_classes(manifest: dict, data_classes: Iterable[str], responsibility: dict | None = None) -> list[str]:
    """Requested classes in canonical order, limited to what the connector accepts. With the operator's
    responsibility, client and personal data may go beyond the manifest unless the provider trains on inputs."""
    requested = set(data_classes)
    if not requested:
        raise ValueError("allow at least one data class")
    unknown = sorted(requested - DATA_CLASSES)
    if unknown:
        raise ValueError(f"unknown data classes: {unknown}")
    classes = [c for c in DATA_CLASS_ORDER if c in requested]
    beyond = [c for c in classes if c not in manifest["data_policy"]["allowed_data_classes"]]
    if any(c not in RESPONSIBLE_CLASSES for c in beyond) or (beyond and responsibility is None):
        raise ValueError(f"{manifest['id']} does not accept {beyond} (client_confidential and personal need your "
                         f"responsibility; special_category needs verified redaction)")
    training = provider_trains(manifest)
    if beyond and training is True:
        raise ValueError(f"{manifest['id']} trains on inputs; it cannot carry {beyond}")
    if beyond and training is None and responsibility.get("no_training") is not True:
        raise ValueError(f"{manifest['id']}: state that training on your inputs is switched off to allow {beyond}")
    return classes


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
    if automation_confirmed and forbidden:
        raise ValueError(f"{manifest['id']}: {forbidden}; it cannot be confirmed")
    body = {"adapter": manifest["id"], "manifest_version": manifest["version"], "allowed_data_classes": classes,
            "operator": operator, "automation_confirmed": automation_confirmed,
            "jurisdiction_sha256": jurisdiction_fingerprint(manifest)}
    if responsibility is not None:
        if not set(classes) & set(RESPONSIBLE_CLASSES):
            raise ValueError("responsibility applies to client_confidential or personal data")
        if today is None:
            raise ValueError("responsibility needs the date it is taken")
        unknown = set(responsibility) - {"processing_regions", "no_training"}
        if unknown:
            raise ValueError(f"unknown responsibility settings: {sorted(unknown)} (the date is always today)")
        body["responsibility"] = {**responsibility, "confirmed_on": today.isoformat()}
    return ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor={"kind": "hil", "id": operator},
                                   body=body))


def disable(ledger: Ledger, connector_id: str, operator: str, reason: str) -> dict:
    operator, reason = checked_operator(operator), reason.strip()
    if not reason:
        raise ValueError("a reason is required")
    return ledger.append(new_event("ADAPTER_DISABLED", task=None, actor={"kind": "hil", "id": operator},
                                   body={"adapter": connector_id, "operator": operator, "reason": reason}))

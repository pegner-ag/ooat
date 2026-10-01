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


def _table(data: dict, key: str, allowed: set[str]) -> dict:
    """A config table with only the allowed keys; values are never echoed in errors (they may be pasted secrets)."""
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a table (secrets belong in environment variables)")
    extra = set(value) - allowed if allowed else set()
    if extra:
        raise ValueError(f"{key}: unknown settings {sorted(extra)} (secrets belong in environment variables)")
    return value


def parse_config(data: dict) -> Config:
    unknown = set(data) - {"ledger", "routing", "connectors"}
    if unknown:
        raise ValueError(f"unknown config sections: {sorted(unknown)}")
    ledger_url = _table(data, "ledger", {"url"}).get("url", Config.ledger_url)
    if not isinstance(ledger_url, str):
        raise ValueError("ledger.url must be a string")
    pins = _table(_table(data, "routing", {"pin"}), "pin", set())
    for tier, connector_id in pins.items():
        if tier not in TIERS or not isinstance(connector_id, str) or not _PROVIDER_ID.match(connector_id):
            raise ValueError(f"invalid pin for tier {tier}")
    connectors = _table(data, "connectors", set())
    for connector_id in connectors:
        if not _PROVIDER_ID.match(connector_id):
            raise ValueError(f"invalid connector id: {connector_id}")
        settings = _table(connectors, connector_id, set(_CONNECTOR_KEYS))
        secret_env = settings.get("secret_env")
        if secret_env is not None and (not isinstance(secret_env, str) or not _ENV_NAME.match(secret_env)):
            raise ValueError(f"{connector_id}: secret_env must name an environment variable, not hold a value")
        models = _table(settings, "models", set(TIERS))
        if not all(isinstance(model, str) for model in models.values()):
            raise ValueError(f"{connector_id}: models must map tiers to model ids")
    return Config(ledger_url=ledger_url, pins=dict(pins), connectors={k: dict(v) for k, v in connectors.items()})


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as file:
        return parse_config(tomllib.load(file))

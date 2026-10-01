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

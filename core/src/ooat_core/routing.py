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

    def price(self, connector_id: str, model: str, on: date, fallback: bool = True) -> Price | None:
        """The connector's newest valid price for the model, else (with fallback) the newest of any adapter.

        The fallback is the spec §6 prior for subscriptions: the API list price of an equivalent model.
        """
        valid = [p for p in self._prices if p["model"] == model
                 and date.fromisoformat(p["valid_from"]) <= on
                 and ("valid_until" not in p or on <= date.fromisoformat(p["valid_until"]))]
        valid.sort(key=lambda p: p["valid_from"], reverse=True)  # a newer price supersedes an open-ended older one
        own = [p for p in valid if p["adapter"] == connector_id]
        chosen = (own or (valid if fallback else []) or [None])[0]
        if chosen is None:
            return None
        return Price(chosen["usd_per_mtok_in"], chosen.get("usd_per_mtok_cached", chosen["usd_per_mtok_in"]),
                     chosen["usd_per_mtok_out"])


def load_routing(path: str | Path) -> RoutingPolicy:
    return RoutingPolicy(json.loads(Path(path).read_text(encoding="utf-8")))

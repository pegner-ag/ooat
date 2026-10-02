import json
from datetime import date
from pathlib import Path

from ooat_core.routing import RoutingPolicy

ROUTING = Path(__file__).resolve().parents[1] / "routing.json"


def test_reference_routing_is_valid_and_sourced():
    document = json.loads(ROUTING.read_text(encoding="utf-8"))
    RoutingPolicy(document)  # validates against spec/schemas/routing.schema.json
    for price in document["prices"]:
        assert price["source"].startswith("https://")
        date.fromisoformat(price["valid_from"])


def test_the_jev_alias_and_the_version_it_resolves_to_carry_the_same_price():
    policy = RoutingPolicy(json.loads(ROUTING.read_text(encoding="utf-8")))
    alias = policy.price("prv.typesafe.api", "jev-latest", date(2026, 10, 1), fallback=False)
    assert alias is not None and alias == policy.price("prv.typesafe.api", "jev-1.13.0", date(2026, 10, 1), False)
    assert alias.usd_per_mtok_out == 0


def test_reference_policy_keeps_client_and_personal_data_off_unverified_routes():
    policy = json.loads(ROUTING.read_text(encoding="utf-8"))["data_class_policy"]
    for data_class in ("client_confidential", "personal"):
        assert policy[data_class].get("require_no_training") and policy[data_class].get("require_contract")
    assert policy["special_category"].get("require_verified_redaction")

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



def test_newest_valid_price_wins():
    routing = policy([price("prv.fake.api", "m", 3, 15), price("prv.fake.api", "m", 2, 10, valid_from="2026-09-01")])
    assert routing.price("prv.fake.api", "m", date(2026, 10, 1)) == Price(2, 2, 10)


def test_fallback_to_another_adapters_price_can_be_disabled():
    routing = policy([price("prv.other.api", "m", 1, 5)])
    assert routing.price("prv.fake.api", "m", date(2026, 10, 1), fallback=False) is None

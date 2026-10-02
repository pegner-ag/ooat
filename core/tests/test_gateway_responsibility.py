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


# Final review of plan 03e ---------------------------------------------------------------------------------------

def lax(setup):
    """The same setup under a routing policy without the no-training requirement."""
    policy = {k: {key: v for key, v in rules.items() if key != "require_no_training"} for k, rules in POLICY.items()}
    return Gateway(setup.ledger, Registry(setup.connectors),
                   RoutingPolicy({"version": "0.1.0", "prices": PRICES, "data_class_policy": policy}),
                   setup.config, SecretResolver(setup.config, {}), clock=lambda: setup.now)


def test_a_provider_that_trains_is_never_extended_whatever_the_routing_policy():
    connector = subscription()
    setup = Setup(connector)
    setup.enable(connector, classes=("client_confidential",), responsibility={"no_training": True,
                                                                              "processing_regions": ["us"]})
    connector.manifest["data_policy"]["training_on_inputs"] = True  # the provider's terms changed later
    request = ModelRequest(tier="workhorse", prompt="x", data_class="client_confidential", task=new_id("tsk"))
    with pytest.raises(GatewayError) as info:
        lax(setup).estimate(request)
    assert "trains on inputs" in info.value.trace[0]


def test_training_stated_in_the_jurisdiction_block_counts_too():
    connector = subscription()
    setup = Setup(connector)
    setup.enable(connector, responsibility={"no_training": True, "processing_regions": ["us"]})
    connector.manifest["jurisdiction"]["training_on_inputs"] = True
    with pytest.raises(GatewayError):
        setup.route("personal")


def test_an_expired_responsibility_stops_a_subscription_carrying_personal_data_beyond_its_manifest():
    connector = subscription()
    setup = Setup(connector, today=TODAY + timedelta(days=366))
    setup.enable(connector, responsibility={"no_training": True, "processing_regions": ["us"]})
    with pytest.raises(GatewayError) as info:
        setup.route("personal")
    assert "not allowed by the manifest" in info.value.trace[0]


def test_changed_facts_stop_client_data_on_an_existing_responsibility():
    connector = subscription()
    setup = Setup(connector)
    setup.enable(connector, classes=("client_confidential",),
                 responsibility={"no_training": True, "processing_regions": ["us"]})
    assert setup.route("client_confidential") == "prv.fake.subscription_cli"
    connector.manifest["jurisdiction"]["host_entity"] = "Another Host Inc."
    with pytest.raises(GatewayError) as info:
        setup.route("client_confidential")
    assert "jurisdiction changed" in info.value.trace[0]


def test_a_sub_region_in_the_policy_matches_that_sub_region():
    connector = subscription()
    setup = Setup(connector, policy={"personal_data_regions": ["eu-west"]})
    setup.enable(connector, responsibility={"no_training": True, "processing_regions": ["eu-west"]})
    assert setup.route("personal") == "prv.fake.subscription_cli"

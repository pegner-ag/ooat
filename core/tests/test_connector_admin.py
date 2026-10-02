from datetime import date

import pytest
from connector_fakes import JURISDICTION, FakeConnector, fake_manifest

from ooat_core.config import Config
from ooat_core.connector_admin import (acknowledge, blocked_by_policy, connector_statuses, consequences_card, disable,
                                       responsibility_in_force)
from ooat_core.connectors import ModelRequest, jurisdiction_stale
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


@pytest.mark.parametrize("operator", ["M\x00", "Martin\nEvil", "\t"])
def test_operator_names_with_control_characters_are_refused(ledger, operator):
    with pytest.raises(ValueError):
        acknowledge(ledger, FakeConnector(), operator, ["public"], True)
    with pytest.raises(ValueError):
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
    assert jurisdiction_stale(connector.manifest, body, TODAY, responsible=False)  # special-category data


def test_the_operator_policy_blocks_countries_and_is_shown_on_the_card_and_in_the_listing(ledger):
    connector = subscription(origin="CN")
    config = Config(blocked_countries=frozenset({"CN"}), personal_data_regions=frozenset({"eu"}))
    assert blocked_by_policy(connector.manifest, config) == "blocked by your policy: model origin CN"
    card = consequences_card(connector.manifest, TODAY, config)
    assert "blocked by your policy: model origin CN" in card and "Personal data only processed in: eu" in card
    assert "Only when you take responsibility" in consequences_card(connector.manifest, TODAY)
    unknown = subscription(origin=None)
    assert "model origin unknown - your country block cannot check them" in consequences_card(
        unknown.manifest, TODAY, config)
    acknowledge(ledger, connector, "Martin", ["personal"], True, {"no_training": True}, TODAY)
    (status,) = connector_statuses(Registry([connector]), ledger, TODAY, config)
    assert status.blocked == "blocked by your policy: model origin CN" and status.responsibility_until == "2027-10-01"

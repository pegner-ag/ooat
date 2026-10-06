import json
from datetime import datetime, timedelta, timezone

import pytest
from connector_fakes import JURISDICTION, FakeConnector, fake_manifest, quota_error

from ooat_core.config import parse_config
from ooat_core.connectors import ConnectorError, ModelRequest, jurisdiction_fingerprint
from ooat_core.connectors.registry import Registry
from ooat_core.gateway import Gateway, GatewayError
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger, new_event
from ooat_core.routing import RoutingPolicy
from ooat_core.credentials_env import SecretResolver

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
HIL = {"kind": "hil", "id": "operator"}
POLICY = {
    "public": {"allowed": True}, "internal": {"allowed": True},
    "client_confidential": {"allowed": True, "require_no_training": True},
    "personal": {"allowed": True, "require_no_training": True, "require_known_region": True},
    "special_category": {"allowed": True, "require_verified_redaction": True},
}
API = fake_manifest("prv.fake.api", "api")
SUBSCRIPTION = fake_manifest("prv.fake.subscription_cli", "subscription_cli")
EXPENSIVE = fake_manifest("prv.premium.api", "api", tiers={"workhorse": "premium-model"})


def prices():
    def price(adapter, model, usd_in, usd_out):
        return {"adapter": adapter, "model": model, "usd_per_mtok_in": usd_in, "usd_per_mtok_out": usd_out,
                "valid_from": "2026-01-01", "source": "https://fake.invalid/pricing"}
    return [price("prv.fake.api", "fake-model", 3, 15), price("prv.premium.api", "premium-model", 15, 75)]


class Setup:
    def __init__(self, *connectors, pins=None, settings=None, environ=None, tiers=None, now=NOW):
        self.now = now
        self.ledger = Ledger.open("sqlite:///:memory:")
        self.connectors = connectors
        self.config = parse_config({"routing": {"pin": pins or {}}, "connectors": settings or {}})
        routing = {"version": "0.1.0", "prices": prices(), "data_class_policy": POLICY}
        if tiers is not None:
            routing["tiers"] = tiers
        self.environ = environ or {}
        self.gateway = self.make_gateway()
        self.task = new_id("tsk")

    def make_gateway(self):  # a new gateway over the same ledger behaves like a restarted process
        return Gateway(self.ledger, Registry(self.connectors), RoutingPolicy(
            {"version": "0.1.0", "prices": prices(), "data_class_policy": POLICY}), self.config,
            SecretResolver(self.config, self.environ), clock=lambda: self.now)

    def acknowledge(self, connector, classes=("public", "internal", "client_confidential", "personal"),
                    automation=True, fingerprint=None):
        self.ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor=HIL, body={
            "adapter": connector.manifest["id"], "manifest_version": connector.manifest["version"],
            "allowed_data_classes": list(classes), "operator": "Operator", "automation_confirmed": automation,
            "jurisdiction_sha256": fingerprint or jurisdiction_fingerprint(connector.manifest)}))

    def request(self, data_class="internal", prompt="x" * 4000, **extra):
        return ModelRequest(tier="workhorse", prompt=prompt, data_class=data_class, max_output_tokens=1000,
                            task=self.task, **extra)

    def issue_contract(self, max_usd):
        contract = new_id("ctr")
        self.ledger.append(new_event("CONTRACT_ISSUED", task=self.task, contract=contract,
                                     actor={"kind": "system", "id": "ooat-core"}, body={"contract": {
            "id": contract, "task": self.task, "capability": "cap.general.complete_task",
            "capability_version": "0.1.0", "agent": new_id("agt"), "role": "role.general.worker@0.1.0",
            "goal": "Shrnout.", "inputs": [], "output_schema": "schemas/summary.v1.json",
            "budget": {"max_usd": max_usd}}}))
        return contract


def ready(*manifests, **options):
    connectors = [FakeConnector(m) for m in manifests]
    setup = Setup(*connectors, **options)
    for connector in connectors:
        setup.acknowledge(connector)
    return setup


# Routing --------------------------------------------------------------------------------------------------------

def test_cheapest_connector_wins():
    setup = ready(API, EXPENSIVE)
    assert setup.gateway.estimate(setup.request()).connector == "prv.fake.api"


def test_subscription_wins_a_tie_with_the_api_of_the_same_model():
    setup = ready(API, SUBSCRIPTION)
    assert setup.gateway.estimate(setup.request()).connector == "prv.fake.subscription_cli"


def test_pin_selects_a_more_expensive_connector():
    setup = ready(API, EXPENSIVE, pins={"workhorse": "prv.premium.api"})
    assert setup.gateway.estimate(setup.request()).connector == "prv.premium.api"


def test_pinned_connector_that_cannot_serve_fails_without_fallback():
    setup = ready(API, pins={"workhorse": "prv.premium.api"})
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request())
    assert info.value.code == "NOT_PERMITTED"


def test_unacknowledged_and_disabled_connectors_are_not_used():
    setup = Setup(FakeConnector(API))
    with pytest.raises(GatewayError, match="NOT_PERMITTED") as info:
        setup.gateway.estimate(setup.request())
    assert "not acknowledged" in info.value.trace[0]
    setup.acknowledge(setup.connectors[0])
    setup.ledger.append(new_event("ADAPTER_DISABLED", task=None, actor=HIL,
                                  body={"adapter": "prv.fake.api", "operator": "Operator", "reason": "test"}))
    with pytest.raises(GatewayError, match="NOT_PERMITTED"):
        setup.gateway.estimate(setup.request())


def test_routing_allow_list_restricts_a_listed_tier():
    setup = ready(API, EXPENSIVE)
    setup.gateway = Gateway(setup.ledger, Registry(setup.connectors), RoutingPolicy({
        "version": "0.1.0", "prices": prices(), "data_class_policy": POLICY,
        "tiers": {"workhorse": ["prv.premium.api"]}}), setup.config, clock=lambda: NOW)
    assert setup.gateway.estimate(setup.request()).connector == "prv.premium.api"


def test_connector_without_a_price_is_excluded():
    setup = ready(fake_manifest("prv.unpriced.api", "api", tiers={"workhorse": "unknown-model"}))
    with pytest.raises(GatewayError) as info:
        setup.gateway.estimate(setup.request())
    assert "no price" in info.value.trace[0]


def test_config_can_name_the_model_for_a_tier():
    manifest = fake_manifest("prv.cli.subscription_cli", "subscription_cli", tiers={"workhorse": None})
    setup = ready(manifest, settings={"prv.cli.subscription_cli": {"models": {"workhorse": "fake-model"}}})
    assert setup.gateway.estimate(setup.request()).model == "fake-model"


# Data protection and automation ----------------------------------------------------------------------------------

def test_special_category_is_always_refused():
    setup = ready(API)
    with pytest.raises(GatewayError, match="NOT_PERMITTED"):
        setup.gateway.estimate(setup.request("special_category"))


def test_data_class_must_be_acknowledged():
    setup = Setup(FakeConnector(API))
    setup.acknowledge(setup.connectors[0], classes=("public",))
    assert setup.gateway.estimate(setup.request("public")).connector == "prv.fake.api"
    with pytest.raises(GatewayError, match="NOT_PERMITTED"):
        setup.gateway.estimate(setup.request("internal"))


def test_changed_jurisdiction_blocks_personal_data_only():
    setup = Setup(FakeConnector(API))
    setup.acknowledge(setup.connectors[0], fingerprint="0" * 64)  # acknowledged a different jurisdiction
    assert setup.gateway.estimate(setup.request("client_confidential")).connector == "prv.fake.api"
    with pytest.raises(GatewayError) as info:
        setup.gateway.estimate(setup.request("personal"))
    assert "acknowledge again" in info.value.trace[0]


@pytest.mark.parametrize("verified_on", [None, "2025-09-01"])
def test_unverified_or_old_jurisdiction_blocks_personal_data(verified_on):
    manifest = fake_manifest(jurisdiction=dict(JURISDICTION, verified_on=verified_on))
    setup = ready(manifest)
    with pytest.raises(GatewayError, match="NOT_PERMITTED"):
        setup.gateway.estimate(setup.request("personal"))
    assert setup.gateway.estimate(setup.request("internal")).connector == "prv.fake.api"


def test_acknowledgement_never_overrides_provider_terms():
    setup = ready(fake_manifest(automation="not_permitted"))
    with pytest.raises(GatewayError) as info:
        setup.gateway.estimate(setup.request())
    assert "provider terms" in info.value.trace[0]


def test_unconfirmed_automation_is_not_used():
    setup = Setup(FakeConnector(API))
    setup.acknowledge(setup.connectors[0], automation=False)
    with pytest.raises(GatewayError) as info:
        setup.gateway.estimate(setup.request())
    assert "not confirmed" in info.value.trace[0]


def test_unknown_data_class_and_missing_task_are_programming_errors():
    setup = ready(API)
    with pytest.raises(ValueError):
        setup.gateway.estimate(setup.request("secret"))
    with pytest.raises(ValueError):
        setup.gateway.call(ModelRequest(tier="workhorse", prompt="x", data_class="internal"))


# Estimate and metering ----------------------------------------------------------------------------------------

def test_estimate_does_not_call_the_connector():
    setup = ready(API)
    estimate = setup.gateway.estimate(setup.request(system="y" * 400))
    assert (estimate.tokens_in, estimate.tokens_out, estimate.basis) == (1100, 1000, "prior")
    assert estimate.usd == pytest.approx((1100 * 3 + 1000 * 15) / 1_000_000)
    assert setup.connectors[0].calls == []


def test_call_returns_a_cost_record_with_the_estimate():
    setup = ready(API)
    result = setup.gateway.call(setup.request())
    assert result.response.text == "Hotovo."
    assert result.cost == {"adapter": "prv.fake.api", "tier": "workhorse", "tokens_in": 1000, "tokens_cached": 0,
                           "tokens_out": 200, "usd": pytest.approx((1000 * 3 + 200 * 15) / 1_000_000),
                           "basis": "exact", "price_ver": "0.1.0", "estimated_usd": result.estimate.usd}


def test_subscription_cost_is_a_shadow_price_and_fits_a_ledger_event():
    setup = ready(SUBSCRIPTION)
    result = setup.gateway.call(setup.request())
    assert result.cost["basis"] == "shadow"
    ref = new_id("art") + "@v1"
    event = new_event("RESULT", task=setup.task, contract=new_id("ctr"),
                      actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
                      body={"outcome": "FAILED", "error": {"code": "UNAVAILABLE", "message": "x"}},
                      refs=[], cost=result.cost)
    setup.ledger.append(event)  # validates against the event schema, including estimated_usd
    assert setup.ledger.events(types=["RESULT"])[0]["cost"]["estimated_usd"] == result.cost["estimated_usd"]
    del ref


def test_missing_usage_is_metered_as_estimated():
    connector = FakeConnector(API, usage=(None, None, None))
    setup = Setup(connector)
    setup.acknowledge(connector)
    result = setup.gateway.call(setup.request())
    assert result.cost["basis"] == "estimated"
    assert result.cost["tokens_in"] == result.estimate.tokens_in


# Budget ---------------------------------------------------------------------------------------------------------

def test_call_over_the_contract_budget_is_refused_before_the_connector_runs():
    setup = ready(API)
    contract = setup.issue_contract(max_usd=0.001)
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request(contract=contract))
    assert info.value.code == "BUDGET"
    assert setup.connectors[0].calls == []


def test_budget_warning_is_written_once_past_80_percent():
    setup = ready(API)
    contract = setup.issue_contract(max_usd=0.007)  # each call costs 0.006 USD; the estimate is tiny
    for _ in range(2):
        result = setup.gateway.call(setup.request(contract=contract, prompt="x" * 40, expected_output_tokens=1))
        setup.ledger.append(new_event("RESULT", task=setup.task, contract=contract,
                                      actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
                                      body={"outcome": "FAILED", "error": {"code": "API_ERROR", "message": "x"}},
                                      cost=result.cost))
    warnings = setup.ledger.events(types=["BUDGET_WARNING"])
    assert len(warnings) == 1 and warnings[0]["contract"] == contract


def test_unknown_contract_is_refused():
    setup = ready(API)
    with pytest.raises(GatewayError, match="NOT_PERMITTED"):
        setup.gateway.call(setup.request(contract=new_id("ctr")))


# Quota ----------------------------------------------------------------------------------------------------------

def test_exhausted_quota_cools_down_the_connector_and_routing_moves_on():
    subscription = FakeConnector(SUBSCRIPTION, error=quota_error())
    setup = Setup(subscription, FakeConnector(API))
    for connector in setup.connectors:
        setup.acknowledge(connector)
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request())
    assert info.value.code == "QUOTA_EXHAUSTED" and info.value.cost["usd"] == 0.0
    warning = setup.ledger.events(types=["QUOTA_WARNING"])[0]["body"]
    assert warning["window_resets_at"] == "2026-10-01T17:00:00Z"  # plan quota window of 5 hours
    assert setup.gateway.call(setup.request()).cost["adapter"] == "prv.fake.api"


def test_cool_down_survives_a_restart_and_ends_at_reset():
    setup = ready(SUBSCRIPTION)
    setup.connectors[0].error = quota_error(resets_at="2026-10-01T13:00:00Z")
    with pytest.raises(GatewayError):
        setup.gateway.call(setup.request())
    restarted = setup.make_gateway()
    with pytest.raises(GatewayError) as info:
        restarted.estimate(setup.request())
    assert info.value.code == "QUOTA_EXHAUSTED"
    setup.now = NOW + timedelta(hours=2)
    setup.connectors[0].error = None
    assert restarted.call(setup.request()).cost["adapter"] == "prv.fake.subscription_cli"


# Errors and secrets ---------------------------------------------------------------------------------------------

def test_connector_errors_are_typed_and_secrets_never_leave_the_gateway():
    settings = {"prv.fake.api": {"secret_env": "FAKE_KEY"}}
    environ = {"FAKE_KEY": "sk-fake-123456"}
    leaking = FakeConnector(API, error=ConnectorError("API_ERROR", "401 for key sk-fake-123456"),
                            secret_seen="prv.fake.api")
    setup = Setup(leaking, settings=settings, environ=environ)
    setup.acknowledge(leaking)
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request())
    assert info.value.code == "API_ERROR" and "sk-fake-123456" not in str(info.value)
    leaking.error = RuntimeError("crash while using sk-fake-123456")
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request())
    assert info.value.code == "API_ERROR" and "sk-fake-123456" not in str(info.value)
    assert "sk-fake-123456" not in json.dumps(setup.ledger.events())


# Routed model ------------------------------------------------------------------------------------------------

def test_connector_receives_the_routed_model():
    manifest = fake_manifest("prv.cli.subscription_cli", "subscription_cli", tiers={"workhorse": None})
    setup = ready(manifest, settings={"prv.cli.subscription_cli": {"models": {"workhorse": "fake-model"}}})
    setup.gateway.call(setup.request())
    assert setup.connectors[0].calls[0].model == "fake-model"


def test_cost_follows_the_model_that_actually_ran():
    connector = FakeConnector(SUBSCRIPTION, reported_model="premium-model")
    setup = Setup(connector)
    setup.acknowledge(connector)
    result = setup.gateway.call(setup.request())
    assert result.cost["usd"] == pytest.approx((1000 * 15 + 200 * 75) / 1_000_000)
    assert result.cost["basis"] == "shadow"


def test_unpriced_model_that_actually_ran_is_marked_estimated():
    connector = FakeConnector(API, reported_model="mystery-model")
    setup = Setup(connector)
    setup.acknowledge(connector)
    assert setup.gateway.call(setup.request()).cost["basis"] == "estimated"


# Review Focus -------------------------------------------------------------------------------------------------

def test_pinned_connector_in_cool_down_reports_quota_not_permission():
    setup = ready(SUBSCRIPTION, API, pins={"workhorse": "prv.fake.subscription_cli"})
    setup.connectors[0].error = quota_error()
    with pytest.raises(GatewayError):
        setup.gateway.call(setup.request())
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request())
    assert info.value.code == "QUOTA_EXHAUSTED"  # retry later; the pin is not silently bypassed


def test_data_class_forbidden_by_the_routing_policy_is_refused():
    setup = ready(API)
    setup.gateway = Gateway(setup.ledger, Registry(setup.connectors), RoutingPolicy({
        "version": "0.1.0", "prices": prices(),
        "data_class_policy": dict(POLICY, internal={"allowed": False})}), setup.config, clock=lambda: NOW)
    with pytest.raises(GatewayError) as info:
        setup.gateway.estimate(setup.request("internal"))
    assert "routing policy" in info.value.trace[0]


def test_new_manifest_version_with_the_same_jurisdiction_needs_no_new_acknowledgement():
    setup = ready(API)
    setup.connectors[0].manifest = dict(API, version="1.1.0")
    assert setup.gateway.estimate(setup.request("personal")).connector == "prv.fake.api"


def test_budget_exactly_equal_to_the_estimate_is_allowed():
    setup = ready(API)
    estimate = setup.gateway.estimate(setup.request())
    contract = setup.issue_contract(max_usd=estimate.usd)
    assert setup.gateway.call(setup.request(contract=contract)).cost["adapter"] == "prv.fake.api"



def test_manual_relay_is_never_used_unattended():
    manual = fake_manifest("prv.fake.subscription_manual", "subscription_manual")
    manual["metering"] = "none"
    setup = ready(manual)
    with pytest.raises(GatewayError) as info:
        setup.gateway.estimate(setup.request())
    assert "manual relay" in info.value.trace[0]


def test_failed_calls_count_against_the_budget():
    setup = ready(API)
    setup.connectors[0].error = ConnectorError("API_ERROR", "500 from provider")
    estimate = setup.gateway.estimate(setup.request())
    contract = setup.issue_contract(max_usd=estimate.usd * 2.5)
    for _ in range(2):
        with pytest.raises(GatewayError) as info:
            setup.gateway.call(setup.request(contract=contract))
        assert info.value.cost["usd"] == estimate.usd and info.value.cost["basis"] == "estimated"
        setup.ledger.append(new_event("RESULT", task=setup.task, contract=contract,
                                      actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
                                      body={"outcome": "FAILED", "error": {"code": "API_ERROR", "message": "500"}},
                                      cost=info.value.cost))
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request(contract=contract))
    assert info.value.code == "BUDGET"



# Final review fixes --------------------------------------------------------------------------------------------

def test_contract_requirement_fails_closed():
    setup = ready(API)
    setup.gateway = Gateway(setup.ledger, Registry(setup.connectors), RoutingPolicy({
        "version": "0.1.0", "prices": prices(),
        "data_class_policy": dict(POLICY, internal={"allowed": True, "require_contract": True})}),
        setup.config, clock=lambda: NOW)
    with pytest.raises(GatewayError) as info:
        setup.gateway.estimate(setup.request("internal"))
    assert "contract" in info.value.trace[0]


def test_legacy_acknowledgement_does_not_break_routing():
    from ooat_core.ledger import _event_row

    setup = ready(API)
    legacy = FakeConnector(EXPENSIVE)
    setup.connectors = (setup.connectors[0], legacy)
    setup.gateway = setup.make_gateway()
    old = new_event("ADAPTER_ACKNOWLEDGED", task=None, actor=HIL, body={
        "adapter": "prv.premium.api", "manifest_version": "1.0.0",
        "allowed_data_classes": ["internal"], "operator": "Operator"})  # written before ADR 0010
    setup.ledger.backend.insert(_event_row(old), [])
    estimate = setup.gateway.estimate(setup.request())
    assert estimate.connector == "prv.fake.api"
    with pytest.raises(GatewayError) as info:
        Gateway(setup.ledger, Registry([legacy]), setup.gateway._routing, setup.config,
                clock=lambda: NOW).estimate(setup.request())
    assert "acknowledge again" in info.value.trace[0]


@pytest.mark.parametrize("resets_at, expected", [
    ("soon", "2026-10-01T17:00:00Z"),
    ("2026-10-01T13:00:00", "2026-10-01T17:00:00Z"),
    ("2026-10-01T15:00:00+02:00", "2026-10-01T13:00:00Z"),
])
def test_connector_reset_time_is_normalised_or_replaced(resets_at, expected):
    setup = ready(SUBSCRIPTION)
    setup.connectors[0].error = quota_error(resets_at=resets_at)
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request())
    assert info.value.code == "QUOTA_EXHAUSTED"
    assert setup.ledger.events(types=["QUOTA_WARNING"])[0]["body"]["window_resets_at"] == expected


def test_response_text_is_redacted():
    settings = {"prv.fake.api": {"secret_env": "FAKE_KEY"}}
    connector = FakeConnector(API, text="the key is sk-fake-123456")
    setup = Setup(connector, settings=settings, environ={"FAKE_KEY": "sk-fake-123456"})
    setup.acknowledge(connector)
    result = setup.gateway.call(setup.request())
    assert "sk-fake-123456" not in result.response.text


def test_connector_cannot_read_another_connectors_secret():
    settings = {"prv.fake.api": {"secret_env": "FAKE_KEY"}, "prv.other.api": {"secret_env": "OTHER_KEY"}}
    snooping = FakeConnector(API, secret_seen="prv.other.api")
    setup = Setup(snooping, settings=settings, environ={"FAKE_KEY": "a", "OTHER_KEY": "b"})
    setup.acknowledge(snooping)
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(setup.request())
    assert info.value.code == "UNAVAILABLE" and "own secret" in info.value.message


@pytest.mark.parametrize("usage", [(-5, 0, 10), (1.5, 0, 10), ("100", 0, 10)])
def test_invalid_usage_from_a_connector_is_metered_as_estimated(usage):
    connector = FakeConnector(API, usage=usage)
    setup = Setup(connector)
    setup.acknowledge(connector)
    result = setup.gateway.call(setup.request())
    assert result.cost["basis"] == "estimated" and result.cost["tokens_in"] == result.estimate.tokens_in
    setup.ledger.append(new_event("RESULT", task=setup.task, contract=new_id("ctr"),
                                  actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
                                  body={"outcome": "FAILED", "error": {"code": "API_ERROR", "message": "x"}},
                                  cost=result.cost))


def test_api_connector_never_borrows_another_vendors_price():
    setup = ready(fake_manifest("prv.copycat.api", "api", tiers={"workhorse": "fake-model"}))
    with pytest.raises(GatewayError) as info:
        setup.gateway.estimate(setup.request())
    assert "no price" in info.value.trace[0]


# Hardening (03d) -----------------------------------------------------------------------------------------------

def test_budget_equal_to_the_estimate_after_earlier_spending_is_allowed():
    setup = ready(API)
    estimate = setup.gateway.estimate(setup.request()).usd
    # an earlier spend whose float sum loses the last bit: (spent + estimate) - spent < estimate
    spent = next(s / 10 for s in range(1, 10) if (s / 10 + estimate) - s / 10 < estimate)
    contract = setup.issue_contract(max_usd=spent + estimate)
    cost = dict(setup.gateway.call(setup.request(contract=contract)).cost, usd=spent)
    setup.ledger.append(new_event("RESULT", task=setup.task, contract=contract,
                                  actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
                                  body={"outcome": "FAILED", "error": {"code": "API_ERROR", "message": "500"}},
                                  cost=cost))
    assert setup.gateway.call(setup.request(contract=contract)).cost["adapter"] == "prv.fake.api"

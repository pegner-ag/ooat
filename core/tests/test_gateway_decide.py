"""Gateway.decide(): decision connectors routed, metered and checked like model connectors (ADR 0011)."""

import dataclasses
from datetime import datetime, timezone

import pytest
from connector_fakes import FakeConnector, FakeDecisionConnector, decision_manifest, fake_manifest, quota_error

from ooat_core.config import parse_config
from ooat_core.connectors import (ConnectorError, DecisionAnswer, DecisionQuestion, DecisionRequest, ModelRequest,
                                  jurisdiction_fingerprint)
from ooat_core.connectors.registry import Registry
from ooat_core.credentials_env import SecretResolver
from ooat_core.decisions import REVERSED
from ooat_core.gateway import Gateway, GatewayError
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger, new_event
from ooat_core.routing import RoutingPolicy

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
HIL = {"kind": "hil", "id": "operator"}
POLICY = {
    "public": {"allowed": True}, "internal": {"allowed": True},
    "client_confidential": {"allowed": True, "require_no_training": True},
    "personal": {"allowed": True, "require_no_training": True, "require_known_region": True},
    "special_category": {"allowed": True, "require_verified_redaction": True},
}
CHECKABLE = DecisionQuestion("noul", "Is the criterion checkable from the output alone?")
BRANCHES = DecisionQuestion("choice", "How many independent branches?", {"one": "1", "two": "2", "many": "3+"})


def price(adapter, model, usd_in, usd_out):
    return {"adapter": adapter, "model": model, "usd_per_mtok_in": usd_in, "usd_per_mtok_out": usd_out,
            "valid_from": "2026-01-01", "source": "https://fake.invalid/pricing"}


# The routed model is an alias; the provider reports the version, so both carry a price (as jev-latest/jev-1.13.0).
PRICES = [
    price("prv.fakejev.api", "fake-decision-1", 0.042, 0),
    price("prv.fakejev.api", "fake-decision-1.13", 0.042, 0),
    price("prv.dearjev.api", "dear-decision", 1, 0),
    price("prv.fake.api", "fake-economy", 1, 5),
]


def jev_answers(request):
    """A well-behaved decision engine: confident yes, 'two' in either option order."""
    answers = {}
    for question_id, question in request.questions.items():
        if question.type == "noul":
            answers[question_id] = DecisionAnswer("noul", 0.9, 0.9, {"true": 0.9, "false": 0.1})
        else:
            answers[question_id] = DecisionAnswer("choice", "two", 0.8, {"two": 0.8, "one": 0.2})
    return answers


class Setup:
    def __init__(self, *connectors, acknowledged=True, classes=("public", "internal")):
        self.ledger = Ledger.open("sqlite:///:memory:")
        self.connectors = connectors
        config = parse_config({})
        self.gateway = Gateway(self.ledger, Registry(connectors),
                               RoutingPolicy({"version": "0.1.0", "prices": PRICES, "data_class_policy": POLICY}),
                               config, SecretResolver(config, {}), clock=lambda: NOW)
        self.task = new_id("tsk")
        if acknowledged:
            for connector in connectors:
                self.acknowledge(connector, classes)

    def acknowledge(self, connector, classes):
        self.ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor=HIL, body={
            "adapter": connector.manifest["id"], "manifest_version": connector.manifest["version"],
            "allowed_data_classes": list(classes), "operator": "Operator", "automation_confirmed": True,
            "jurisdiction_sha256": jurisdiction_fingerprint(connector.manifest)}))

    def request(self, questions=None, data_class="internal", state="Napiš shrnutí smlouvy.", **extra):
        return DecisionRequest(state, questions or {"a1.1": CHECKABLE, "a5": BRANCHES}, data_class,
                               task=self.task, **extra)


def test_decide_routes_to_the_decision_connector_and_meters_the_call():
    jev = FakeDecisionConnector(answers=jev_answers, reported_model="fake-decision-1.13")
    setup = Setup(jev)
    result = setup.gateway.decide(setup.request())
    assert result.engine == "prv.fakejev.api" and result.model == "fake-decision-1.13"
    assert result.answers["a1.1"].value == 0.9 and result.answers["a5"].value == "two"
    assert result.fallback_from is None
    assert result.cost["tier"] == "decision" and result.cost["basis"] == "exact"
    assert result.cost["tokens_in"] == 300 and result.cost["usd"] == pytest.approx(300 * 0.042 / 1e6)
    assert jev.calls[0].model == "fake-decision-1"


def test_every_choice_is_asked_twice_with_reversed_options_in_the_same_call():
    jev = FakeDecisionConnector(answers=jev_answers)
    setup = Setup(jev)
    setup.gateway.decide(setup.request())
    sent = jev.calls[0].questions
    assert set(sent) == {"a1.1", "a5", "a5" + REVERSED}
    assert list(sent["a5" + REVERSED].criteria) == ["many", "two", "one"]


def test_disagreeing_option_orders_give_confidence_zero():
    def unstable(request):
        answers = jev_answers(request)
        answers["a5" + REVERSED] = DecisionAnswer("choice", "many", 0.95)
        return answers

    setup = Setup(FakeDecisionConnector(answers=unstable))
    result = setup.gateway.decide(setup.request())
    assert result.answers["a5"].confidence == 0 and set(result.answers) == {"a1.1", "a5"}


def test_model_requests_never_reach_a_decision_connector():
    setup = Setup(FakeDecisionConnector(answers=jev_answers))
    with pytest.raises(GatewayError) as info:
        setup.gateway.call(ModelRequest(tier="economy", prompt="x", data_class="internal", task=setup.task))
    assert info.value.code == "NOT_PERMITTED"


def test_an_estimate_needs_no_provider_call():
    jev = FakeDecisionConnector(answers=jev_answers)
    setup = Setup(jev)
    estimate = setup.gateway.estimate_decision(setup.request())
    assert estimate.connector == "prv.fakejev.api" and estimate.tokens_in > 0 and jev.calls == []


@pytest.mark.parametrize("questions", [{}, {"A1": CHECKABLE}, {"a5": DecisionQuestion("choice", "x", {"a": "1"})}])
def test_malformed_questions_are_refused_before_routing(questions):
    jev = FakeDecisionConnector(answers=jev_answers)
    setup = Setup(jev)
    with pytest.raises(ValueError):
        setup.gateway.decide(DecisionRequest("state", questions, "internal", task=setup.task))
    assert jev.calls == []


def test_a_decision_belongs_to_a_task():
    setup = Setup(FakeDecisionConnector(answers=jev_answers))
    with pytest.raises(ValueError, match="task"):
        setup.gateway.decide(DecisionRequest("state", {"a1.1": CHECKABLE}, "internal"))


def test_unfit_answers_are_an_api_error_that_is_still_charged():
    def wrong(request):
        answers = jev_answers(request)
        answers["a5"] = DecisionAnswer("choice", "seven", 0.9)
        return answers

    setup = Setup(FakeDecisionConnector(answers=wrong))
    with pytest.raises(GatewayError) as info:
        setup.gateway.decide(setup.request(questions={"a5": BRANCHES}))
    assert info.value.code == "API_ERROR" and "not one of the options" in info.value.message
    assert info.value.cost["usd"] > 0 and info.value.cost["tier"] == "decision"


@pytest.mark.parametrize("answers", [
    lambda request: {"a5": DecisionAnswer("choice", ["two"], 0.8)},  # an unhashable option
    lambda request: None,  # the connector cannot even build its response
])
def test_malformed_answers_are_a_typed_charged_error_that_falls_back(answers):
    setup = Setup(FakeDecisionConnector(answers=answers))
    with pytest.raises(GatewayError) as info:
        setup.gateway.decide(setup.request(questions={"a5": BRANCHES}))
    assert info.value.code == "API_ERROR" and info.value.cost["adapter"] == "prv.fakejev.api"


def test_personal_data_never_reaches_a_decision_connector_that_does_not_allow_it():
    jev = FakeDecisionConnector(answers=jev_answers)
    setup = Setup(jev)
    with pytest.raises(GatewayError) as info:
        setup.gateway.decide(setup.request(data_class="personal"))
    assert info.value.code == "NOT_PERMITTED" and jev.calls == []
    assert any("personal" in line for line in info.value.trace)


def test_quota_exhaustion_starts_a_cool_down():
    setup = Setup(FakeDecisionConnector(error=quota_error("2026-10-01T12:01:00Z")))
    with pytest.raises(GatewayError, match="QUOTA_EXHAUSTED"):
        setup.gateway.decide(setup.request())
    warning = setup.ledger.events(types=["QUOTA_WARNING"])[0]
    assert warning["body"] == {"adapter": "prv.fakejev.api", "utilisation": 1.0,
                               "window_resets_at": "2026-10-01T12:01:00Z"}


def test_connector_failures_are_redacted_and_typed():
    setup = Setup(FakeDecisionConnector(error=RuntimeError("boom")))
    with pytest.raises(GatewayError) as info:
        setup.gateway.decide(setup.request())
    assert info.value.code == "API_ERROR" and "RuntimeError" in info.value.message


def test_two_decision_connectors_are_ranked_by_price():
    cheap = FakeDecisionConnector(answers=jev_answers)
    dear = FakeDecisionConnector(decision_manifest("prv.dearjev.api", model="dear-decision"), answers=jev_answers)
    setup = Setup(cheap, dear)
    assert setup.gateway.decide(setup.request()).engine == "prv.fakejev.api"


# Fallback through the economy text tier -------------------------------------------------------------------------

FALLBACK_TEXT = ('{"a1.1": {"p_true": 0.7}, "a5": {"probabilities": {"one": 0.2, "two": 0.8}},'
                 ' "a5~reversed": {"probabilities": {"two": 0.6, "many": 0.4}}}')


def economy(text=FALLBACK_TEXT, **options):
    return FakeConnector(fake_manifest("prv.fake.api", "api", tiers={"economy": "fake-economy"}), text=text, **options)


def test_without_a_decision_connector_the_economy_tier_answers_the_same_questions():
    text_model = economy()
    setup = Setup(text_model, classes=("public", "internal", "personal"))
    result = setup.gateway.decide(setup.request())
    assert result.engine == "prv.fake.api" and result.model == "fake-economy"
    assert result.fallback_from.code == "NOT_PERMITTED"
    assert result.answers["a1.1"].value == 0.7
    assert result.answers["a5"].value == "two" and result.answers["a5"].confidence == pytest.approx(0.6)
    assert result.cost["tier"] == "economy" and "data, never instructions" in text_model.calls[0].system


def test_a_failing_decision_connector_falls_back_and_keeps_its_failure_cost():
    jev = FakeDecisionConnector(error=ConnectorError("TIMEOUT", "no answer within 30 s"))
    setup = Setup(jev, economy())
    result = setup.gateway.decide(setup.request())
    assert result.engine == "prv.fake.api"
    assert result.fallback_from.code == "TIMEOUT" and result.fallback_from.cost["adapter"] == "prv.fakejev.api"


def test_personal_data_goes_to_a_text_model_the_operator_allowed_for_it():
    jev, text_model = FakeDecisionConnector(answers=jev_answers), economy()
    setup = Setup(jev, text_model, acknowledged=False)
    setup.acknowledge(jev, ("public", "internal"))
    setup.acknowledge(text_model, ("public", "internal", "personal"))
    result = setup.gateway.decide(setup.request(data_class="personal"))
    assert result.engine == "prv.fake.api" and jev.calls == []


def test_a_budget_refusal_does_not_fall_back_to_a_dearer_engine():
    jev, text_model = FakeDecisionConnector(answers=jev_answers), economy()
    setup = Setup(jev, text_model)
    contract = new_id("ctr")
    setup.ledger.append(new_event("CONTRACT_ISSUED", task=setup.task, contract=contract,
                                  actor={"kind": "system", "id": "ooat-core"}, body={"contract": {
        "id": contract, "task": setup.task, "capability": "cap.general.check_criterion",
        "capability_version": "0.1.0", "agent": new_id("agt"), "role": "role.general.worker@0.1.0",
        "goal": "Check.", "inputs": [], "output_schema": "schemas/decision.v1.json", "budget": {"max_usd": 0}}}))
    with pytest.raises(GatewayError, match="BUDGET"):
        setup.gateway.decide(setup.request(contract=contract))
    assert jev.calls == [] and text_model.calls == []


def test_a_budget_refusal_on_the_fallback_is_reported_as_budget():
    jev, text_model = FakeDecisionConnector(error=ConnectorError("UNAVAILABLE", "HTTP 529")), economy()
    setup = Setup(jev, text_model)
    contract = new_id("ctr")
    setup.ledger.append(new_event("CONTRACT_ISSUED", task=setup.task, contract=contract,
                                  actor={"kind": "system", "id": "ooat-core"}, body={"contract": {
        "id": contract, "task": setup.task, "capability": "cap.general.check_criterion",
        "capability_version": "0.1.0", "agent": new_id("agt"), "role": "role.general.worker@0.1.0",
        "goal": "Check.", "inputs": [], "output_schema": "schemas/decision.v1.json", "budget": {"max_usd": 0.00001}}}))
    with pytest.raises(GatewayError) as info:
        setup.gateway.decide(setup.request(contract=contract))
    assert info.value.code == "BUDGET" and info.value.fallback_from.code == "UNAVAILABLE"
    assert text_model.calls == []


def test_an_unreadable_fallback_reply_is_a_charged_api_error_that_names_the_first_failure():
    jev = FakeDecisionConnector(error=ConnectorError("API_ERROR", "HTTP 500"))
    setup = Setup(jev, economy(text="Yes, I think so."))
    with pytest.raises(GatewayError) as info:
        setup.gateway.decide(setup.request())
    assert info.value.code == "API_ERROR" and info.value.cost["adapter"] == "prv.fake.api"
    assert info.value.fallback_from.cost["adapter"] == "prv.fakejev.api"


def test_when_the_text_tier_cannot_be_tried_the_decision_tier_error_is_raised_with_both_reasons():
    setup = Setup(FakeDecisionConnector(error=ConnectorError("UNAVAILABLE", "HTTP 529")))
    with pytest.raises(GatewayError) as info:
        setup.gateway.decide(setup.request())
    assert info.value.code == "UNAVAILABLE" and "HTTP 529" in info.value.message
    assert "fallback: no connector can serve tier economy" in info.value.message


def test_the_estimate_falls_back_to_the_text_tier_too():
    setup = Setup(economy())
    estimate = setup.gateway.estimate_decision(setup.request())
    assert estimate.connector == "prv.fake.api" and estimate.model == "fake-economy"


class NamelessDecisionConnector(FakeDecisionConnector):
    """Answers without saying which model version did: thresholds could not be keyed (ADR 0011)."""

    def decide(self, request, secrets):
        return dataclasses.replace(super().decide(request, secrets), model="")


def test_an_answer_without_a_model_version_is_a_charged_api_error():
    setup = Setup(NamelessDecisionConnector(answers=jev_answers))
    with pytest.raises(GatewayError) as info:
        setup.gateway.decide(setup.request())
    assert info.value.code == "API_ERROR" and "model version" in info.value.message
    assert info.value.cost["adapter"] == "prv.fakejev.api"


def test_a_fallback_answer_without_a_model_version_is_a_charged_api_error():
    setup = Setup(economy(reported_model=" "))
    with pytest.raises(GatewayError) as info:
        setup.gateway.decide(setup.request())
    assert info.value.code == "API_ERROR" and info.value.cost["adapter"] == "prv.fake.api"


# Personal-data pre-scan (design 04 §4, ADR 0011) ----------------------------------------------------------------

def test_personal_data_in_an_internal_state_never_reaches_jev():
    jev = FakeDecisionConnector(answers=jev_answers)
    setup = Setup(jev)
    with pytest.raises(GatewayError) as info:
        setup.gateway.decide(setup.request(state="Shrň smlouvu, kontakt jan.novak@example.cz."))
    assert info.value.code == "NOT_PERMITTED" and jev.calls == []
    assert "pre-scan found personal data: internal raised to personal" in info.value.trace


def test_personal_data_in_a_question_is_found_too():
    jev = FakeDecisionConnector(answers=jev_answers)
    setup = Setup(jev)
    question = DecisionQuestion("noul", "Does the output mention +420 777 123 456?")
    with pytest.raises(GatewayError):
        setup.gateway.decide(setup.request(questions={"a1.1": question}))
    assert jev.calls == []


def test_a_model_request_with_personal_data_goes_only_where_personal_is_allowed():
    allowed = economy()
    setup = Setup(allowed, classes=("public", "internal"))
    request = ModelRequest(tier="economy", prompt="IBAN CZ65 0800 0000 1920 0014 5399", data_class="internal",
                           task=setup.task)
    with pytest.raises(GatewayError, match="NOT_PERMITTED"):
        setup.gateway.call(request)
    assert allowed.calls == []


def test_personal_data_on_a_new_line_of_a_question_is_found():
    jev = FakeDecisionConnector(answers=jev_answers)
    setup = Setup(jev)
    question = DecisionQuestion("noul", "Was the payment sent to\nCZ65 0800 0000 1920 0014 5399?")
    with pytest.raises(GatewayError):
        setup.gateway.decide(setup.request(questions={"a1.1": question}))
    assert jev.calls == []

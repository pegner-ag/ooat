"""Topology Gate for T0–T2 with fake connectors (design 04 §4, ADR 0011)."""

import json
from datetime import datetime, timezone

import pytest
from connector_fakes import FakeConnector, FakeDecisionConnector, fake_manifest

from ooat_core.config import parse_config
from ooat_core.connectors import ConnectorError, DecisionAnswer, jurisdiction_fingerprint
from ooat_core.connectors.registry import Registry
from ooat_core.credentials_env import SecretResolver
from ooat_core.gate import Gate, GateSettings
from ooat_core.gateway import Gateway
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger, new_event
from ooat_core.routing import RoutingPolicy
from ooat_core.state import task_state

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
HIL = {"kind": "hil", "id": "operator"}
GATE = {"kind": "system", "id": "ooat-gate"}
POLICY = {
    "public": {"allowed": True}, "internal": {"allowed": True},
    "client_confidential": {"allowed": True, "require_no_training": True},
    "personal": {"allowed": True, "require_no_training": True, "require_known_region": True},
    "special_category": {"allowed": True, "require_verified_redaction": True},
}
ALL_BUT_SPECIAL = ("public", "internal", "client_confidential", "personal")


def price(adapter, model, usd_in, usd_out):
    return {"adapter": adapter, "model": model, "usd_per_mtok_in": usd_in, "usd_per_mtok_out": usd_out,
            "valid_from": "2026-01-01", "source": "https://fake.invalid/pricing"}


PRICES = [price("prv.fakejev.api", "fake-decision-1", 0.042, 0), price("prv.fake.api", "fake-model", 3, 15),
          price("prv.fake.api", "fake-economy", 1, 5)]


def confident(**overrides):
    """A decision engine that is sure every criterion is checkable, the task is one part, and the data internal."""
    def answers(request):
        given = {}
        for question_id, question in request.questions.items():
            if question.type == "noul":
                given[question_id] = DecisionAnswer("noul", 0.95, 0.95)
            elif question_id.startswith("a5"):
                given[question_id] = DecisionAnswer("choice", "one", 0.9)
            else:
                given[question_id] = DecisionAnswer("choice", "internal", 0.9)
        for question_id, answer in overrides.items():
            for key in (question_id, question_id + "~reversed"):
                if key in given:
                    given[key] = answer
        return given
    return answers


def fallback_reply(criteria=1):
    """What the economy text tier answers when it stands in for the decision tier."""
    reply = {f"a1.{n}": {"p_true": 0.9} for n in range(1, criteria + 1)}
    reply.update({"a4": {"p_true": 0.2}, "a7": {"p_true": 0.2},
                  "a5": {"probabilities": {"one": 1}}, "a5~reversed": {"probabilities": {"one": 1}},
                  "a10": {"probabilities": {"internal": 1}}, "a10~reversed": {"probabilities": {"internal": 1}}})
    return json.dumps(reply)


class GateSetup:
    def __init__(self, answers=None, jev_error=None, worker_text=None, settings=GateSettings()):
        self.ledger = Ledger.open("sqlite:///:memory:")
        self.jev = FakeDecisionConnector(answers=answers or confident(), error=jev_error)
        self.worker = FakeConnector(fake_manifest("prv.fake.api", "api",
                                                  tiers={"workhorse": "fake-model", "economy": "fake-economy"}),
                                    text=worker_text or fallback_reply())
        for connector, classes in ((self.jev, ("public", "internal")), (self.worker, ALL_BUT_SPECIAL)):
            self.ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor=HIL, body={
                "adapter": connector.manifest["id"], "manifest_version": connector.manifest["version"],
                "allowed_data_classes": list(classes), "operator": "Operator", "automation_confirmed": True,
                "jurisdiction_sha256": jurisdiction_fingerprint(connector.manifest)}))
        config = parse_config({})
        self.gateway = Gateway(self.ledger, Registry([self.jev, self.worker]),
                               RoutingPolicy({"version": "0.1.0", "prices": PRICES, "data_class_policy": POLICY}),
                               config, SecretResolver(config, {}), clock=lambda: NOW)
        self.gate = Gate(self.ledger, self.gateway, settings, clock=lambda: NOW)

    def submit(self, goal="Napiš shrnutí smlouvy pro jednatele.", acceptance=("Shrnutí má nejvýše 300 slov.",),
               **extra):
        task = new_id("tsk")
        body = {"goal": goal, "acceptance": list(acceptance), **extra}
        self.ledger.append(new_event("TASK_SUBMITTED", task=task, actor=HIL, body=body))
        return task

    def events(self, task, kind):
        return [e for e in self.ledger.events(task=task) if e["type"] == kind]


def test_a_clear_task_runs_as_t2_and_every_decision_is_recorded():
    setup = GateSetup()
    task = setup.submit()
    outcome = setup.gate.run(task)
    assert (outcome.action, outcome.topology, outcome.data_class, outcome.budget_usd) == ("run", "T2", "internal", 2.0)
    decided = setup.events(task, "TOPOLOGY_DECIDED")[0]
    assert decided["body"]["topology"] == "T2" and decided["body"]["rules_applied"] == []
    assert decided["body"]["candidates"] == [{"topology": "T2", "model_usd": outcome.estimate_usd}]
    assert decided["body"]["parameters"] == {"budget_usd": 2.0}
    records = {r["question"]: r for r in decided["body"]["decisions"]}
    assert set(records) == {"a1.1", "a4", "a5", "a7", "a10"}
    assert records["a1.1"] == {"question": "a1.1", "engine": "prv.fakejev.api", "model": "fake-decision-1",
                               "answer": 0.95, "confidence": 0.95, "threshold": 0.8}
    assert decided["cost"]["tier"] == "decision" and decided["refs"] == [setup.events(task, "TASK_SUBMITTED")[0]["id"]]
    assert task_state(setup.ledger.events(task=task)) == "GATED"


def test_the_estimate_covers_the_worker_and_the_acceptance_checks():
    setup = GateSetup()
    outcome = setup.gate.run(setup.submit())
    assert 2000 * 15 / 1e6 < outcome.estimate_usd < 0.04  # 2,000 workhorse output tokens dominate


def test_a_confident_a10_raises_the_class_and_never_lowers_it():
    raise_ = GateSetup(answers=confident(a10=DecisionAnswer("choice", "client_confidential", 0.95)))
    task = raise_.submit()
    outcome = raise_.gate.run(task)
    assert outcome.data_class == "client_confidential"
    assert raise_.events(task, "TOPOLOGY_DECIDED")[0]["body"]["rules_applied"] == ["A10"]
    lower = GateSetup(answers=confident(a10=DecisionAnswer("choice", "public", 0.99)))
    assert lower.gate.run(lower.submit()).data_class == "internal"


def test_an_unsure_a10_keeps_the_declared_class():
    setup = GateSetup(answers=confident(a10=DecisionAnswer("choice", "personal", 0.7)))
    assert setup.gate.run(setup.submit()).data_class == "internal"


def test_personal_data_found_by_the_pre_scan_raises_the_class_and_keeps_the_task_off_jev():
    setup = GateSetup()
    task = setup.submit(goal="Napiš odpověď panu Novákovi na jan.novak@example.cz.")
    outcome = setup.gate.run(task)
    assert outcome.data_class == "personal" and setup.jev.calls == []
    decided = setup.events(task, "TOPOLOGY_DECIDED")[0]["body"]
    assert decided["rules_applied"] == ["A10"]
    assert {r["engine"] for r in decided["decisions"]} == {"prv.fake.api"}
    assert {r["threshold"] for r in decided["decisions"]} == {1.0}  # the fallback is not rated yet


def test_a_task_without_a_permitted_route_is_closed_without_running():
    setup = GateSetup()
    task = setup.submit(data_class="special_category")
    outcome = setup.gate.run(task)
    assert (outcome.action, outcome.topology, outcome.closed) == ("closed", "T0", "CLOSED_ABSTAINED")
    closed = setup.events(task, "TASK_CLOSED")[0]["body"]
    assert "special_category" in closed["missing"] and closed["cost"]["contracts_usd"] == 0
    assert setup.events(task, "TOPOLOGY_DECIDED")[0]["body"]["topology"] == "T0"
    assert setup.worker.calls == [] and task_state(setup.ledger.events(task=task)) == "CLOSED_ABSTAINED"


def test_a_task_that_costs_more_than_it_is_worth_is_closed_as_t0():
    setup = GateSetup()
    task = setup.submit(value={"usd": 0.01})
    outcome = setup.gate.run(task)
    assert outcome.closed == "CLOSED_ABSTAINED" and outcome.estimate_usd > 0.01
    decided = setup.events(task, "TOPOLOGY_DECIDED")[0]["body"]
    assert decided["topology"] == "T0" and "A3" in decided["rules_applied"]
    assert decided["parameters"]["v_usd"] == 0.01
    assert "exceeds the task value" in setup.events(task, "TASK_CLOSED")[0]["body"]["missing"]


def test_value_classes_map_to_usd():
    setup = GateSetup(settings=GateSettings(value_usd={"A": 1000.0, "B": 300.0, "C": 0.001}))
    assert setup.gate.run(setup.submit(value={"class": "C"})).closed == "CLOSED_ABSTAINED"
    assert setup.gate.run(setup.submit(value={"class": "A"})).action == "run"


def test_charged_decision_failures_are_recorded_with_their_cost():
    setup = GateSetup(jev_error=ConnectorError("API_ERROR", "HTTP 500"), worker_text="Not JSON.")
    task = setup.submit()
    setup.gate.run(task)
    failures = setup.events(task, "DECISION")
    assert [f["cost"]["adapter"] for f in failures] == ["prv.fake.api", "prv.fakejev.api"]
    assert all(f["actor"] == GATE for f in failures)


def test_the_gate_runs_only_on_a_submitted_task():
    setup = GateSetup()
    task = setup.submit()
    setup.gate.run(task)
    with pytest.raises(ValueError, match="not SUBMITTED"):
        setup.gate.run(task)


def rate_history(setup, question, outcomes):
    """Append rated decisions of the fake decision engine: outcomes is a list of (confidence, correct)."""
    for confidence, correct in outcomes:
        task = new_id("tsk")
        record = {"question": question, "engine": "prv.fakejev.api", "model": "fake-decision-1", "answer": 0.9,
                  "confidence": confidence, "threshold": 0.8}
        decided = setup.ledger.append(new_event("TOPOLOGY_DECIDED", task=task, actor=GATE, body={
            "topology": "T2", "candidates": [{"topology": "T2"}], "rules_applied": [], "decisions": [record]}))
        verdict = {"event": decided["id"], "question": question, "verdict": "confirmed" if correct else "corrected"}
        if not correct:
            verdict["value"] = 0
        setup.ledger.append(new_event("TASK_RATED", task=task, actor=HIL, body={
            "accepted": True, "value_class": "C", "decisions": [verdict]}))


def test_a_task_without_a_risk_class_is_judged_as_r1_the_safer_default():
    setup = GateSetup()
    rate_history(setup, "a4", [(0.9, True)] * 19 + [(0.9, False)])  # 5 % errors: enough for R0, not for R1
    unspecified, r0 = setup.submit(), setup.submit(risk_class="R0")
    setup.gate.run(unspecified)
    setup.gate.run(r0)
    thresholds = [{r["question"]: r["threshold"] for r in setup.events(t, "TOPOLOGY_DECIDED")[0]["body"]["decisions"]}
                  for t in (unspecified, r0)]
    assert thresholds[0]["a4"] == 1.0 and thresholds[1]["a4"] == 0.5

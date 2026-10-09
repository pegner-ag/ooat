"""Topology Gate for T0–T2 with fake connectors (design 04 §4, ADR 0011)."""

import json
from pathlib import Path
import math
from datetime import datetime, timezone

import pytest
from connector_fakes import FakeConnector, FakeDecisionConnector, fake_manifest

from ooat_core.config import parse_config
from ooat_core.connectors import ConnectorError, DecisionAnswer, jurisdiction_fingerprint
from ooat_core.connectors.registry import Registry
from ooat_core.credentials_env import SecretResolver
from ooat_core.gate import Gate, GateSettings, gated_data_class, task_facts
from ooat_core.gateway import Gateway, GatewayError
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
    def __init__(self, answers=None, jev_error=None, worker_text=None, settings=GateSettings(), attachment_chars=None):
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
        self.gate = Gate(self.ledger, self.gateway, settings, clock=lambda: NOW, attachment_chars=attachment_chars)

    def submit(self, goal="Napiš shrnutí smlouvy pro jednatele.", acceptance=("Shrnutí má nejvýše 300 slov.",),
               **extra):
        task = new_id("tsk")
        body = {"goal": goal, "acceptance": list(acceptance), **extra}
        self.ledger.append(new_event("TASK_SUBMITTED", task=task, actor=HIL, body=body))
        return task

    def events(self, task, kind):
        return [e for e in self.ledger.events(task=task) if e["type"] == kind]

    def submit_with_attachment(self, **extra):
        import tempfile

        from ooat_core.artifacts import ArtifactStore
        from ooat_core.blobs import BlobStore
        staged = ArtifactStore(self.ledger, BlobStore(Path(tempfile.mkdtemp(prefix="ooat-gate-")))).stage(
            "Smlouva o dílo.".encode(), artifact_type="attachment", untrusted=True, data_class="internal")
        task = new_id("tsk")
        body = {"goal": "Shrň přiloženou smlouvu.", "acceptance": ["Shrnutí má nejvýše 300 slov."], **extra}
        self.ledger.append(new_event("TASK_SUBMITTED", task=task, actor=HIL, body=body, refs=[staged.ref]), [staged])
        return task

    def closed_run(self, usd, adapter="prv.fake.api"):
        """A closed contract of `usd` on the worker's adapter, as the runtime would leave it in the ledger."""
        task, ctr = new_id("tsk"), new_id("ctr")
        self.ledger.append(new_event("TASK_SUBMITTED", task=task, actor=HIL, body={"goal": "x"}))
        self.ledger.append(new_event("CONTRACT_ISSUED", task=task, contract=ctr, actor=GATE, body={"contract": {
            "id": ctr, "task": task, "capability": "cap.general.complete_task", "capability_version": "0.1.0",
            "agent": new_id("agt"), "role": "role.general.worker@0.1.0", "goal": "x", "inputs": [],
            "output_schema": "schemas/markdown_document.v1.json", "budget": {"max_usd": 5.0}}}))
        import tempfile

        from ooat_core.artifacts import ArtifactStore
        from ooat_core.blobs import BlobStore
        doc = ArtifactStore(self.ledger, BlobStore(Path(tempfile.mkdtemp(prefix="ooat-gate-")))).stage(
            b"# Doc", artifact_type="markdown_document", data_class="internal")
        self.ledger.append(new_event("RESULT", task=task, contract=ctr, refs=[doc.ref],
                                     actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
                                     body={"outcome": "DONE", "artifacts": [doc.ref]},
                                     cost={"adapter": adapter, "tier": "workhorse", "tokens_in": 1, "tokens_cached": 0,
                                           "tokens_out": 1, "usd": usd, "basis": "exact", "price_ver": "0.1.0",
                                           "estimated_usd": usd}), [doc])
        self.ledger.append(new_event("TASK_CLOSED", task=task, actor=GATE, body={
            "state": "CLOSED_DONE", "summary": "x", "cost": {"contracts_usd": usd, "gate_usd": 0.0,
                                                             "orchestrator_usd": 0.0, "critic_usd": 0.0}}))


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
    # worker at 2,000 output tokens, plus the critic at its prior share 0.5, times 1.25 attempts (plan 04d)
    assert 2000 * 15 / 1e6 * 1.25 < outcome.estimate_usd < 0.08


def test_a_confident_a10_raises_the_class_and_never_lowers_it():
    raise_ = GateSetup(answers=confident(a10=DecisionAnswer("choice", "client_confidential", 0.95)))
    task = raise_.submit()
    outcome = raise_.gate.run(task)
    assert outcome.data_class == "client_confidential"
    assert raise_.events(task, "TOPOLOGY_DECIDED")[0]["body"]["rules_applied"] == ["A10"]
    lower = GateSetup(answers=confident(a10=DecisionAnswer("choice", "public", 0.99)))
    assert lower.gate.run(lower.submit()).data_class == "internal"


def test_personal_data_found_by_the_pre_scan_raises_the_class_and_keeps_the_task_off_jev():
    setup = GateSetup()
    task = setup.submit(goal="Napiš odpověď panu Novákovi na jan.novak@example.cz.")
    outcome = setup.gate.run(task)
    assert outcome.data_class == "personal" and setup.jev.calls == []
    decided = setup.events(task, "TOPOLOGY_DECIDED")[0]["body"]
    assert {r["engine"] for r in decided["decisions"]} == {"prv.fake.api"}
    assert {r["threshold"] for r in decided["decisions"]} == {1.0}  # the fallback is not rated yet
    # nothing the fallback says acts alone, so the operator confirms the criteria
    assert outcome.action == "ask" and decided["rules_applied"] == ["A1", "A10"]


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


# Asking the operator: clarification (A1, ADR 0009) and budget ----------------------------------------------------

def answer(setup, task, request, **body):
    setup.ledger.append(new_event("HIL_RESPONSE", task=task, actor=HIL, body={"request": request, **body}))


def test_a_task_without_criteria_asks_the_operator_before_any_model_is_called():
    setup = GateSetup()
    task = setup.submit(acceptance=())
    outcome = setup.gate.run(task)
    assert (outcome.action, outcome.topology) == ("ask", "T0") and setup.jev.calls == []
    decided = setup.events(task, "TOPOLOGY_DECIDED")[0]["body"]
    assert decided["rules_applied"] == ["A1"] and decided["candidates"][0]["eliminated_by"] == ["A1"]
    assert outcome.estimate_usd == decided["candidates"][0]["model_usd"]
    request = setup.events(task, "HIL_REQUEST")[0]
    assert request["id"] == outcome.request and "no acceptance criteria" in request["body"]["question"]
    assert [o["id"] for o in request["body"]["options"]] == ["clarify", "run_as_is", "do_not_run"]
    assert request["body"]["default_on_silence"] == "do_not_run" and request["body"]["blocking"] is True
    assert request["body"]["deadline"] == "2026-10-04T12:00:00Z"  # 48 h (spec §8)
    assert task_state(setup.ledger.events(task=task)) == "CLARIFYING"


@pytest.mark.parametrize("a1", [DecisionAnswer("noul", 0.2, 0.8), DecisionAnswer("noul", 0.9, 0.7)])
def test_a_criterion_that_is_not_confidently_checkable_is_sent_back_to_the_operator(a1):
    setup = GateSetup(answers=confident(**{"a1.1": a1}))
    task = setup.submit(acceptance=("Shrnutí je srozumitelné.",))
    outcome = setup.gate.run(task)
    assert outcome.action == "ask" and setup.worker.calls == []
    assert "Shrnutí je srozumitelné." in setup.events(task, "HIL_REQUEST")[0]["body"]["question"]


def test_a_clarification_goes_back_to_the_gate_with_the_answer_in_the_task_text():
    def answers(request):
        checkable = "Clarification 1:" in request.state
        return confident(**{"a1.1": DecisionAnswer("noul", 0.95 if checkable else 0.2, 0.95)})(request)

    setup = GateSetup(answers=answers)
    task = setup.submit(acceptance=("Shrnutí je srozumitelné.",))
    first = setup.gate.run(task)
    answer(setup, task, first.request, text="Srozumitelné = bez právních termínů, nejvýše 300 slov.")
    assert task_state(setup.ledger.events(task=task)) == "SUBMITTED"
    second = setup.gate.run(task)
    assert second.action == "run"
    assert "Clarification 1: Srozumitelné = bez právních termínů" in setup.jev.calls[1].state


def test_without_criteria_the_clarifications_become_the_criteria():
    setup = GateSetup()
    task = setup.submit(acceptance=())
    first = setup.gate.run(task)
    answer(setup, task, first.request, choice="clarify", text="Výstup je tabulka s 10 řádky.")
    assert setup.gate.run(task).action == "run"
    assert "a1.1" in setup.jev.calls[0].questions


def test_run_as_is_skips_the_criteria_questions():
    setup = GateSetup(answers=confident(**{"a1.1": DecisionAnswer("noul", 0.1, 0.9)}))
    task = setup.submit()
    first = setup.gate.run(task)
    answer(setup, task, first.request, choice="run_as_is")
    assert setup.gate.run(task).action == "run"
    assert not any(q.startswith("a1.") for q in setup.jev.calls[1].questions)


@pytest.mark.parametrize("response, closed", [
    ({"choice": "do_not_run"}, "CANCELLED"),
    ({"choice": "do_not_run", "default_applied": True}, "CLOSED_ABSTAINED"),  # silence until the deadline
])
def test_do_not_run_cancels_the_task_and_silence_closes_it_as_abstained(response, closed):
    setup = GateSetup()
    task = setup.submit(acceptance=())
    first = setup.gate.run(task)
    answer(setup, task, first.request, **response)
    outcome = setup.gate.run(task)
    assert outcome.closed == closed and task_state(setup.ledger.events(task=task)) == closed
    assert setup.jev.calls == []


def test_after_three_clarifications_an_unclear_task_is_closed():
    setup = GateSetup(answers=confident(**{"a1.1": DecisionAnswer("noul", 0.1, 0.9)}))
    task = setup.submit(acceptance=("Je to dobré.",))
    for round_ in range(3):
        outcome = setup.gate.run(task)
        assert outcome.action == "ask"
        answer(setup, task, outcome.request, text=f"Pokus {round_ + 1}.")
    outcome = setup.gate.run(task)
    assert outcome.closed == "CLOSED_ABSTAINED"
    missing = setup.events(task, "TASK_CLOSED")[0]["body"]["missing"]
    assert "after 3 clarifications" in missing and "Je to dobré." in missing
    assert len(setup.events(task, "HIL_REQUEST")) == 3


def test_a_failed_decision_tier_makes_the_gate_ask_instead_of_guessing():
    setup = GateSetup(jev_error=ConnectorError("UNAVAILABLE", "HTTP 529"), worker_text="Not JSON.")
    task = setup.submit()
    assert setup.gate.run(task).action == "ask"


def test_an_estimate_above_the_budget_asks_to_raise_it():
    setup = GateSetup()
    task = setup.submit(budget_usd=0.001)
    outcome = setup.gate.run(task)
    assert (outcome.action, outcome.topology) == ("ask", "T2") and outcome.estimate_usd > 0.001
    request = setup.events(task, "HIL_REQUEST")[0]["body"]
    raise_option = request["options"][0]
    assert raise_option["id"] == "raise_budget"
    assert raise_option["cost_usd"] == math.ceil(outcome.estimate_usd * 120) / 100  # whole cents, rounded up
    assert request["default_on_silence"] == "do_not_run"
    assert task_state(setup.ledger.events(task=task)) == "HIL_WAIT"
    answer(setup, task, outcome.request, choice="raise_budget")
    events = setup.ledger.events(task=task)
    assert task_state(events) == "GATED" and task_facts(events).budget_usd == raise_option["cost_usd"]


def test_the_runtime_sees_the_safer_default_risk_class():
    setup = GateSetup()
    task = setup.submit()
    assert task_facts(setup.ledger.events(task=task)).risk_class == "R1"


def test_refusing_the_budget_is_visible_to_the_runtime():
    setup = GateSetup()
    task = setup.submit(budget_usd=0.001)
    outcome = setup.gate.run(task)
    answer(setup, task, outcome.request, choice="do_not_run")
    assert task_facts(setup.ledger.events(task=task)).refused


def test_the_runtime_recomputes_the_class_the_gate_decided():
    setup = GateSetup(answers=confident(a10=DecisionAnswer("choice", "client_confidential", 0.95)))
    task = setup.submit()
    outcome = setup.gate.run(task)
    assert gated_data_class(setup.ledger.events(task=task)) == outcome.data_class == "client_confidential"


def test_narrowing_the_scope_sends_a_gated_task_back_to_the_gate():
    setup = GateSetup()
    task = setup.submit(budget_usd=0.001)
    first = setup.gate.run(task)
    assert [o["id"] for o in setup.events(task, "HIL_REQUEST")[0]["body"]["options"]] == \
        ["raise_budget", "narrow_scope", "do_not_run"]
    answer(setup, task, first.request, choice="narrow_scope", text="Jen první kapitola smlouvy.")
    assert task_state(setup.ledger.events(task=task)) == "GATED"
    second = setup.gate.run(task)
    assert "Narrowed scope 1: Jen první kapitola smlouvy." in setup.jev.calls[1].state
    assert second.estimate_usd < first.estimate_usd * 0.6  # the output prior is halved
    assert second.action == "ask" and len(setup.events(task, "HIL_REQUEST")) == 2  # still above 0.001 USD
    assert task_facts(setup.ledger.events(task=task)).criteria == ["Shrnutí má nejvýše 300 slov."]


def test_a_gated_task_without_a_narrowed_scope_is_not_gated_again():
    setup = GateSetup()
    task = setup.submit(budget_usd=0.001)
    first = setup.gate.run(task)
    answer(setup, task, first.request, choice="raise_budget")
    with pytest.raises(ValueError, match="not SUBMITTED"):
        setup.gate.run(task)


def test_after_three_budget_questions_a_task_still_over_budget_is_closed():
    setup = GateSetup()
    task = setup.submit(budget_usd=0.001)
    for round_ in range(3):
        outcome = setup.gate.run(task)
        assert outcome.action == "ask"
        answer(setup, task, outcome.request, choice="narrow_scope", text=f"Ještě méně, kolo {round_ + 1}.")
    outcome = setup.gate.run(task)
    assert outcome.closed == "CLOSED_ABSTAINED"
    assert "after 3 budget questions" in setup.events(task, "TASK_CLOSED")[0]["body"]["missing"]


# Final review of plan 04b ---------------------------------------------------------------------------------------

def test_a_self_stated_certainty_of_the_fallback_never_acts_alone():
    sure = json.loads(fallback_reply())
    sure["a1.1"] = {"p_true": 1.0}
    setup = GateSetup(jev_error=ConnectorError("UNAVAILABLE", "HTTP 529"), worker_text=json.dumps(sure))
    assert setup.gate.run(setup.submit()).action == "ask"


def test_an_r2_task_never_runs_on_a_decision_alone_even_at_certainty():
    setup = GateSetup(answers=confident(**{"a1.1": DecisionAnswer("noul", 1.0, 1.0)}))
    assert setup.gate.run(setup.submit(risk_class="R2")).action == "ask"


def test_a_quota_cool_down_leaves_the_task_submitted_instead_of_closing_it():
    setup = GateSetup()
    task = setup.submit()
    setup.ledger.append(new_event("QUOTA_WARNING", task=task, actor=GATE, body={
        "adapter": "prv.fake.api", "utilisation": 1.0, "window_resets_at": "2026-10-02T13:00:00Z"}))
    with pytest.raises(GatewayError) as info:
        setup.gate.run(task)
    assert info.value.code == "QUOTA_EXHAUSTED"
    assert task_state(setup.ledger.events(task=task)) == "SUBMITTED" and setup.events(task, "TASK_CLOSED") == []
    assert [e["cost"]["adapter"] for e in setup.events(task, "DECISION")] == ["prv.fakejev.api"]  # cost kept


def test_a_class_raised_in_an_earlier_round_is_kept_and_used_for_the_next_one():
    setup = GateSetup(answers=confident(**{"a1.1": DecisionAnswer("noul", 0.2, 0.8),
                                           "a10": DecisionAnswer("choice", "client_confidential", 0.95)}))
    task = setup.submit()
    first = setup.gate.run(task)
    assert (first.action, first.data_class) == ("ask", "client_confidential")
    answer(setup, task, first.request, text="Stačí 300 slov.")
    second = setup.gate.run(task)
    assert second.data_class == "client_confidential" and len(setup.jev.calls) == 1  # round 2 never reached Jev
    assert gated_data_class(setup.ledger.events(task=task)) == "client_confidential"


def test_a_text_only_answer_to_the_budget_question_narrows_the_scope():
    setup = GateSetup()
    task = setup.submit(budget_usd=0.001)
    first = setup.gate.run(task)
    answer(setup, task, first.request, text="Jen první kapitola.")
    facts = task_facts(setup.ledger.events(task=task))
    assert facts.narrowed and facts.criteria == ["Shrnutí má nejvýše 300 slov."]
    setup.gate.run(task)  # a GATED task with a narrowed scope goes back to the Gate


def test_when_the_decision_tier_fails_the_operator_is_told_so():
    setup = GateSetup(jev_error=ConnectorError("UNAVAILABLE", "HTTP 529"), worker_text="Not JSON.")
    task = setup.submit()
    setup.gate.run(task)
    assert "could not be checked automatically" in setup.events(task, "HIL_REQUEST")[0]["body"]["question"]


def test_an_unsure_a10_that_names_a_higher_class_still_raises_it():
    setup = GateSetup(answers=confident(a10=DecisionAnswer("choice", "client_confidential", 0.6)))
    assert setup.gate.run(setup.submit()).data_class == "client_confidential"


def test_a_refusal_stays_final_whatever_comes_later():
    events = [
        {"id": "evt_1", "type": "TASK_SUBMITTED", "actor": HIL, "body": {"goal": "x"}},
        {"id": "evt_2", "type": "HIL_REQUEST", "actor": GATE, "body": {"options": [{"id": "clarify"}]}},
        {"id": "evt_3", "type": "HIL_RESPONSE", "actor": HIL, "body": {"request": "evt_2", "choice": "do_not_run"}},
        {"id": "evt_4", "type": "HIL_REQUEST", "actor": GATE, "body": {"options": [{"id": "clarify"}]}},
        {"id": "evt_5", "type": "HIL_RESPONSE", "actor": HIL, "body": {"request": "evt_4", "text": "Later text."}},
    ]
    assert task_facts(events).refused


# Hardening (03d) -----------------------------------------------------------------------------------------------

def test_facts_of_an_unknown_task_are_a_clear_error():
    with pytest.raises(ValueError, match="no TASK_SUBMITTED"):
        task_facts([])


# Estimate from observed runs (plan 04d) ----------------------------------------------------------------------

from ooat_core.connectors import ModelRequest as _ModelRequest


def candidate_usd(setup, task):
    setup.gate.run(task)
    decided = setup.events(task, "TOPOLOGY_DECIDED")[-1]
    return next(c["model_usd"] for c in decided["body"]["candidates"] if "model_usd" in c)


def old_formula(setup, task, routed=True):
    """Today's estimate without the new code: the worker at 2,000 output tokens, plus the decision checks (about
    nothing on the fake engine), or plus the worker again when no decision route exists."""
    state = task_facts(setup.ledger.events(task=task)).state
    worker = setup.gateway.estimate(_ModelRequest(tier="workhorse", prompt=state, data_class="internal",
                                                  expected_output_tokens=2000, task=task)).usd
    return worker + (0.0 if routed else worker)


def test_without_observations_the_estimate_is_never_below_the_old_one():
    setup = GateSetup()
    task = setup.submit()
    assert candidate_usd(setup, task) >= old_formula(setup, task)


def test_without_a_decision_route_the_critic_is_certain(monkeypatch):
    routed, unrouted = GateSetup(), GateSetup()

    def no_route(*args, **kwargs):
        raise GatewayError("NOT_PERMITTED", "no decision route in this test")
    monkeypatch.setattr(unrouted.gateway, "estimate_decision", no_route)
    assert candidate_usd(unrouted, unrouted.submit()) > candidate_usd(routed, routed.submit())


def test_narrowing_scales_the_observed_estimate():
    setup = GateSetup()
    for usd in (0.10, 0.20, 0.30, 0.40, 0.50):
        setup.closed_run(usd)
    task = setup.submit(budget_usd=0.01)
    first = setup.gate.run(task)
    answer(setup, task, first.request, choice="narrow_scope", text="Jen první kapitola smlouvy.")
    second = setup.gate.run(task)
    assert second.estimate_usd == pytest.approx(first.estimate_usd / 2)


def test_narrowing_still_lowers_the_prior_estimate():
    setup = GateSetup()
    task = setup.submit(budget_usd=0.001)
    first = setup.gate.run(task)
    answer(setup, task, first.request, choice="narrow_scope", text="Jen první kapitola smlouvy.")
    second = setup.gate.run(task)
    assert second.estimate_usd < first.estimate_usd * 0.75


def test_an_untrusted_attachment_always_counts_the_critic():
    plain = GateSetup()
    attached = GateSetup(attachment_chars=lambda refs: 4_000 if refs else 0)
    assert candidate_usd(attached, attached.submit_with_attachment()) > candidate_usd(plain, plain.submit())


def test_an_attachment_counts_only_what_the_worker_receives():
    capped = GateSetup(attachment_chars=lambda refs: 100_000)
    huge = GateSetup(attachment_chars=lambda refs: 5_000_000)
    assert candidate_usd(huge, huge.submit_with_attachment()) == \
        pytest.approx(candidate_usd(capped, capped.submit_with_attachment()))


def test_four_runs_keep_the_prior_and_the_fifth_switches_to_observation():
    setup = GateSetup()
    for usd in (0.10, 0.20, 0.30, 0.40):
        setup.closed_run(usd)
    prior = candidate_usd(setup, setup.submit())
    setup.closed_run(0.50)
    assert prior != pytest.approx(0.30) and candidate_usd(setup, setup.submit()) == pytest.approx(0.30)


def test_from_five_runs_the_estimate_is_the_observed_p50():
    setup = GateSetup()
    for usd in (0.003, 0.058, 0.086, 0.238, 0.469, 0.507):
        setup.closed_run(usd)
    assert candidate_usd(setup, setup.submit()) == pytest.approx(0.086)


def test_the_budget_check_uses_p90():
    setup = GateSetup()
    for usd in (0.003, 0.058, 0.086, 0.238, 0.469, 0.507):
        setup.closed_run(usd)
    task = setup.submit(budget_usd=0.30)  # above p50, below p90
    outcome = setup.gate.run(task)
    assert outcome.action == "ask" and outcome.estimate_p90_usd == pytest.approx(0.507)
    raise_to = next(o for o in setup.events(task, "HIL_REQUEST")[0]["body"]["options"] if o["id"] == "raise_budget")
    assert raise_to["cost_usd"] >= 0.507


def test_without_a_decision_route_the_prior_is_never_below_the_old_formula(monkeypatch):
    setup = GateSetup()

    def no_route(*args, **kwargs):
        raise GatewayError("NOT_PERMITTED", "no decision route in this test")
    monkeypatch.setattr(setup.gateway, "estimate_decision", no_route)
    task = setup.submit()
    assert candidate_usd(setup, task) >= old_formula(setup, task, routed=False)

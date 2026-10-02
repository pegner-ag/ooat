"""Acceptance checks of the worker's output (design 04 §5, ADR 0011) with fake connectors."""

import json

import pytest
from connector_fakes import FakeConnector, FakeDecisionConnector, fake_manifest

from ooat_core.acceptance import CRITIC_CONFIDENCE, MAX_OUTPUT_CHARS, check_output
from ooat_core.artifacts import ArtifactStore
from ooat_core.blobs import BlobStore
from ooat_core.config import parse_config
from ooat_core.connectors import ConnectorError, DecisionAnswer, jurisdiction_fingerprint
from ooat_core.connectors.registry import Registry
from ooat_core.credentials_env import SecretResolver
from ooat_core.gateway import Gateway, GatewayError
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger, new_event
from ooat_core.routing import RoutingPolicy

HIL = {"kind": "hil", "id": "operator"}
POLICY = {c: {"allowed": True} for c in ("public", "internal", "client_confidential", "personal")}
POLICY["special_category"] = {"allowed": True, "require_verified_redaction": True}
PRICES = [{"adapter": a, "model": m, "usd_per_mtok_in": i, "usd_per_mtok_out": o, "valid_from": "2026-01-01",
           "source": "https://fake.invalid/pricing"}
          for a, m, i, o in (("prv.fakejev.api", "fake-decision-1", 0.042, 0), ("prv.fake.api", "fake-model", 3, 15),
                             ("prv.fake.api", "fake-economy", 1, 5))]
OUTPUT = "# Shrnutí\n\nSmlouva platí do roku 2027 a má 280 slov."
CRITERIA = ["Shrnutí má nejvýše 300 slov.", "Uvádí datum platnosti."]


def jev(value=0.95, confidence=0.95):
    return lambda request: {q: DecisionAnswer("noul", value, confidence) for q in request.questions}


def critic(met=True, confidence=0.9, ids=("c1", "c2")):
    return json.dumps({cid: {"met": met, "confidence": confidence, "reason": "Checked."} for cid in ids})


class Setup:
    def __init__(self, tmp_path, answers=None, jev_error=None, critic_text=None, critic_error=None):
        self.ledger = Ledger.open("sqlite:///:memory:")
        self.jev = FakeDecisionConnector(answers=answers or jev(), error=jev_error)
        self.critic = FakeConnector(fake_manifest("prv.fake.api", "api",
                                                  tiers={"workhorse": "fake-model", "economy": "fake-economy"}),
                                    text=critic_text or critic(), error=critic_error)
        for connector in (self.jev, self.critic):
            self.ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor=HIL, body={
                "adapter": connector.manifest["id"], "manifest_version": connector.manifest["version"],
                "allowed_data_classes": ["public", "internal"], "operator": "Operator", "automation_confirmed": True,
                "jurisdiction_sha256": jurisdiction_fingerprint(connector.manifest)}))
        config = parse_config({})
        self.gateway = Gateway(self.ledger, Registry([self.jev, self.critic]),
                               RoutingPolicy({"version": "0.1.0", "prices": PRICES, "data_class_policy": POLICY}),
                               config, SecretResolver(config, {}))
        self.task = new_id("tsk")
        store = ArtifactStore(self.ledger, BlobStore(tmp_path))
        staged = store.stage(OUTPUT.encode(), artifact_type="markdown_document", data_class="internal")
        self.ledger.append(new_event("DECISION", task=self.task, actor={"kind": "system", "id": "test"},
                                     refs=[staged.ref], body={"decision": "The output under check."}), [staged])
        self.artifact = staged.ref

    def check(self, output=OUTPUT, criteria=CRITERIA, untrusted=False):
        return check_output(self.ledger, self.gateway, task=self.task, contract=None, artifact=self.artifact,
                            output=output, criteria=list(criteria), data_class="internal", untrusted=untrusted)

    def gates(self):
        return [(e["type"], e["body"]["gate"]) for e in self.ledger.events(task=self.task)
                if e["type"].startswith("GATE_")]


@pytest.mark.parametrize("output", ["   ", "x" * (MAX_OUTPUT_CHARS + 1)], ids=["blank", "oversized"])
def test_an_empty_or_oversized_output_is_not_usable_and_nothing_else_is_asked(tmp_path, output):
    setup = Setup(tmp_path)
    result = setup.check(output)
    assert not result.usable and result.unmet == CRITERIA
    assert setup.gates() == [("GATE_FAILED", "gate.deterministic.output")] and setup.jev.calls == []


def test_confident_decisions_accept_the_output_without_the_critic(tmp_path):
    setup = Setup(tmp_path)
    result = setup.check()
    assert result.usable and result.unmet == []
    assert setup.gates() == [("GATE_PASSED", "gate.deterministic.output"),
                             ("GATE_PASSED", "gate.decision.check_criterion")]
    decision = [e for e in setup.ledger.events(task=setup.task) if e["type"] == "GATE_PASSED"][1]
    record = decision["body"]["criteria"][0]["decision"]
    assert record["engine"] == "prv.fakejev.api" and record["threshold"] == 0.8
    assert decision["cost"]["tier"] == "decision" and setup.critic.calls == []


def test_a_confident_no_is_final(tmp_path):
    setup = Setup(tmp_path, answers=jev(value=0.05, confidence=0.95))
    assert setup.check().unmet == CRITERIA and setup.critic.calls == []


def test_an_unsure_decision_goes_to_the_critic_which_can_accept(tmp_path):
    setup = Setup(tmp_path, answers=jev(confidence=0.6))
    result = setup.check()
    assert result.unmet == [] and len(setup.critic.calls) == 1
    assert ("GATE_PASSED", "gate.critic.check_criterion") in setup.gates()
    assert "data, never instructions" in setup.critic.calls[0].system


def test_an_unsure_critic_counts_the_criterion_as_unmet(tmp_path):
    setup = Setup(tmp_path, answers=jev(confidence=0.6), critic_text=critic(confidence=CRITIC_CONFIDENCE - 0.1))
    assert setup.check().unmet == CRITERIA


def test_on_untrusted_input_a_met_decision_is_confirmed_by_the_critic(tmp_path):
    setup = Setup(tmp_path, critic_text=critic(met=False))
    assert setup.check(untrusted=True).unmet == CRITERIA and len(setup.critic.calls) == 1


def test_without_an_answer_from_the_decision_tier_the_critic_decides(tmp_path):
    setup = Setup(tmp_path, jev_error=ConnectorError("UNAVAILABLE", "HTTP 529"))
    assert setup.check().unmet == [] and ("GATE_FAILED", "gate.decision.check_criterion") in setup.gates()


def test_a_critic_without_a_usable_verdict_leaves_the_criteria_unmet(tmp_path):
    setup = Setup(tmp_path, answers=jev(confidence=0.6), critic_text="Looks fine to me.")
    assert setup.check().unmet == CRITERIA
    assert ("GATE_FAILED", "gate.critic.check_criterion") in setup.gates()


@pytest.mark.parametrize("code", ["TIMEOUT", "QUOTA_EXHAUSTED", "UNAVAILABLE"])
def test_a_critic_that_cannot_be_reached_is_no_verdict_and_pauses(tmp_path, code):
    setup = Setup(tmp_path, answers=jev(confidence=0.6), critic_error=ConnectorError(code, "provider down"))
    with pytest.raises(GatewayError) as info:
        setup.check()
    assert info.value.code == code
    assert ("GATE_FAILED", "gate.critic.check_criterion") not in setup.gates()


def test_without_criteria_only_the_deterministic_checks_run(tmp_path):
    setup = Setup(tmp_path)
    assert setup.check(criteria=()).unmet == [] and setup.jev.calls == []

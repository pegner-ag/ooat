"""Scripted connectors for task-runtime tests: a decision engine and one text model that plays worker and critic."""

import json

from connector_fakes import FakeConnector, FakeDecisionConnector, fake_manifest

from ooat_core.acceptance import CRITIC_SYSTEM
from ooat_core.connectors import DecisionAnswer, ModelResponse, jurisdiction_fingerprint
from ooat_core.ledger import new_event

HIL = {"kind": "hil", "id": "operator"}
POLICY = {c: {"allowed": True} for c in ("public", "internal", "client_confidential", "personal")}
POLICY["special_category"] = {"allowed": True, "require_verified_redaction": True}
PRICES = [{"adapter": a, "model": m, "usd_per_mtok_in": i, "usd_per_mtok_out": o, "valid_from": "2026-01-01",
           "source": "https://fake.invalid/pricing"}
          for a, m, i, o in (("prv.fakejev.api", "fake-decision-1", 0.042, 0), ("prv.fake.api", "fake-model", 3, 15),
                             ("prv.fake.api", "fake-economy", 1, 5))]
DOCUMENT = "# Shrnutí\n\nSmlouva platí do roku 2027."


def routing_document() -> dict:
    return {"version": "0.1.0", "prices": PRICES, "data_class_policy": POLICY}


class ScriptedModel(FakeConnector):
    """Answers as the worker from `documents` (the last one repeats) and as the critic with `critic`.

    A provider that is down for a while: `outages` maps the role ("worker" or "critic") and the number of the
    call in that role (1, 2 …) to the ConnectorError raised instead of an answer. Only answered worker calls are
    kept in `worker_prompts`.
    """

    def __init__(self, documents=(DOCUMENT,), critic=None, outages=None):
        super().__init__(fake_manifest("prv.fake.api", "api", tiers={"workhorse": "fake-model",
                                                                     "economy": "fake-economy"}))
        self.documents, self.critic, self.outages = list(documents), critic, dict(outages or {})
        self.worker_prompts, self.attempts = [], {"worker": 0, "critic": 0}

    def complete(self, request, secrets):
        self.calls.append(request)
        role = "critic" if request.system == CRITIC_SYSTEM else "worker"
        self.attempts[role] += 1
        if (role, self.attempts[role]) in self.outages:
            raise self.outages[(role, self.attempts[role])]
        if role == "critic":
            text = self.critic or json.dumps({f"c{n}": {"met": True, "confidence": 0.9, "reason": "ok"}
                                              for n in range(1, 10)})
        else:
            self.worker_prompts.append(request.prompt)
            text = self.documents[min(len(self.worker_prompts), len(self.documents)) - 1]
        return ModelResponse(text, request.model, 1000, 0, 200, None, "exact")


def decisions(checkable=True, met=True, confidence=0.95):
    """A decision engine: Gate questions per `checkable`, acceptance questions (c1, c2 …) per `met`.

    `met` may be a list: one value per acceptance call, the last one repeating.
    """
    calls = []

    def answers(request):
        given, acceptance = {}, any(q.startswith("c") for q in request.questions)
        if acceptance:
            calls.append(1)
        for question_id, question in request.questions.items():
            if question.type == "choice":
                given[question_id] = DecisionAnswer("choice", "one" if question_id.startswith("a5") else "internal",
                                                    0.9)
            elif acceptance:
                wanted = met[min(len(calls), len(met)) - 1] if isinstance(met, list) else met
                given[question_id] = DecisionAnswer("noul", 0.95 if wanted else 0.05, confidence)
            elif question_id.startswith("a1"):
                given[question_id] = DecisionAnswer("noul", 0.95 if checkable else 0.1, 0.95)
            else:
                given[question_id] = DecisionAnswer("noul", 0.1, 0.9)
        return given
    return FakeDecisionConnector(answers=answers)


def acknowledge(ledger, connector, classes=("public", "internal")):
    ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor=HIL, body={
        "adapter": connector.manifest["id"], "manifest_version": connector.manifest["version"],
        "allowed_data_classes": list(classes), "operator": "Operator", "automation_confirmed": True,
        "jurisdiction_sha256": jurisdiction_fingerprint(connector.manifest)}))

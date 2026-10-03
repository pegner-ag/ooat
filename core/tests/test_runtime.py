"""Task runtime T0–T2 end to end on fake connectors (design 04 §5)."""

from datetime import datetime, timedelta, timezone

import pytest
from runtime_fakes import HIL, ScriptedModel, acknowledge, decisions, routing_document

from ooat_core.artifacts import ArtifactStore
from ooat_core.blobs import BlobStore
from ooat_core.config import parse_config
from ooat_core.connectors import ConnectorError
from ooat_core.connectors.registry import Registry
from ooat_core.credentials_env import SecretResolver
from ooat_core.gateway import Gateway
from ooat_core.ledger import Ledger, new_event
from ooat_core.routing import RoutingPolicy
from ooat_core.runtime import Runtime
from ooat_core.state import contract_state, task_state

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
CRITERIA = ["Shrnutí má nejvýše 300 slov."]


class Setup:
    def __init__(self, tmp_path, model=None, jev=None, classes=("public", "internal")):
        self.now = NOW
        self.ledger = Ledger.open("sqlite:///:memory:")
        self.model, self.jev = model or ScriptedModel(), jev or decisions()
        for connector in (self.model, self.jev):
            acknowledge(self.ledger, connector, classes if connector is self.model else ("public", "internal"))
        config = parse_config({})
        clock = lambda: self.now  # noqa: E731
        gateway = Gateway(self.ledger, Registry([self.model, self.jev]), RoutingPolicy(routing_document()), config,
                          SecretResolver(config, {}), clock=clock)
        self.artifacts = ArtifactStore(self.ledger, BlobStore(tmp_path))
        self.runtime = Runtime(self.ledger, gateway, self.artifacts, clock=clock)

    def submit(self, acceptance=CRITERIA, **extra):
        return self.runtime.submit(operator="Martin", goal="Shrň smlouvu pro jednatele.", acceptance=acceptance,
                                   **extra)

    def types(self, task):
        return [e["type"] for e in self.ledger.events(task=task)]

    def last(self, task, kind):
        return [e for e in self.ledger.events(task=task) if e["type"] == kind][-1]

    def answer(self, task, request, **body):
        self.ledger.append(new_event("HIL_RESPONSE", task=task, actor=HIL, body={"request": request, **body}))


def test_a_clear_task_runs_to_a_delivered_document(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit(project="sme-ai")
    outcome = setup.runtime.run(task)
    assert outcome.state == "CLOSED_DONE" and outcome.artifact
    assert setup.types(task) == ["TASK_SUBMITTED", "TOPOLOGY_DECIDED", "CONTRACT_ISSUED", "CLAIM", "RESULT",
                                 "GATE_PASSED", "GATE_PASSED", "TASK_CLOSED"]
    assert setup.artifacts.read(outcome.artifact).decode() == setup.model.documents[0]
    closed = setup.last(task, "TASK_CLOSED")["body"]
    assert closed["artifacts"] == [outcome.artifact]
    assert closed["cost"]["gate_usd"] > 0 and closed["cost"]["contracts_usd"] > 0 and closed["cost"]["critic_usd"] > 0
    contract = setup.last(task, "CONTRACT_ISSUED")["body"]["contract"]
    assert contract["capability"] == "cap.general.complete_task" and contract["budget"]["max_usd"] == 2.0
    assert setup.last(task, "TASK_SUBMITTED")["body"]["project"] == "sme-ai"


def test_an_unmet_criterion_gets_one_retry_with_feedback(tmp_path):
    model = ScriptedModel(["Příliš dlouhé.", "# Krátké shrnutí"])
    setup = Setup(tmp_path, model=model, jev=decisions(met=[False, True]))
    task = setup.submit()
    assert setup.runtime.run(task).state == "CLOSED_DONE"
    assert len(setup.model.worker_prompts) == 2 and CRITERIA[0] in setup.model.worker_prompts[1]
    assert "did not meet" in setup.model.worker_prompts[1]


def test_still_unmet_after_the_retry_closes_as_partial(tmp_path):
    setup = Setup(tmp_path, jev=decisions(met=False))
    task = setup.submit()
    outcome = setup.runtime.run(task)
    assert outcome.state == "CLOSED_PARTIAL" and outcome.artifact
    result = setup.last(task, "RESULT")["body"]
    assert result["outcome"] == "PARTIAL" and CRITERIA[0] in result["remaining"]
    contract = setup.last(task, "CONTRACT_ISSUED")["contract"]
    assert contract_state(setup.ledger.events(task=task), contract) == "PARTIAL"


def test_an_abstaining_worker_closes_the_task_with_what_is_missing(tmp_path):
    reply = '{"abstain": "UNKNOWN", "reason": "Chybí text smlouvy.", "missing": "Text smlouvy.", "confidence": 0.9}'
    setup = Setup(tmp_path, model=ScriptedModel([reply]))
    task = setup.submit()
    assert setup.runtime.run(task).state == "CLOSED_ABSTAINED"
    assert setup.last(task, "ABSTAIN")["body"]["outcome"] == "ABSTAIN_UNKNOWN"
    assert setup.last(task, "TASK_CLOSED")["body"]["missing"] == "Text smlouvy."


def test_two_malformed_replies_are_failed_results_and_the_task_closes(tmp_path):
    setup = Setup(tmp_path, model=ScriptedModel(['{"abstain": "UNKNOWN"}']))
    task = setup.submit()
    assert setup.runtime.run(task).state == "CLOSED_ABSTAINED"
    failed = [e for e in setup.ledger.events(task=task) if e["type"] == "RESULT"]
    assert [r["body"]["error"]["code"] for r in failed] == ["INVALID_OUTPUT", "INVALID_OUTPUT"]
    assert setup.last(task, "ABSTAIN")["body"]["outcome"] == "ABSTAIN_UNABLE"


def test_a_clarification_answered_by_the_operator_lets_the_task_run(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit(acceptance=())
    first = setup.runtime.run(task)
    assert first.state == "CLARIFYING" and first.request
    setup.answer(task, first.request, text="Shrnutí má nejvýše 300 slov.")
    assert setup.runtime.run(task).state == "CLOSED_DONE"


def test_refusing_the_budget_cancels_and_raising_it_runs(tmp_path):
    for choice, closed in (("do_not_run", "CANCELLED"), ("raise_budget", "CLOSED_DONE")):
        setup = Setup(tmp_path)
        task = setup.submit(budget_usd=0.001)
        first = setup.runtime.run(task)
        assert first.state == "HIL_WAIT"
        setup.answer(task, first.request, choice=choice)
        assert setup.runtime.run(task).state == closed


def test_an_unanswered_question_expires_after_its_deadline(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit(acceptance=())
    first = setup.runtime.run(task)
    setup.now = NOW + timedelta(hours=49)
    assert setup.runtime.run(task).state == "CLOSED_ABSTAINED"
    response = setup.last(task, "HIL_RESPONSE")
    assert response["actor"] == {"kind": "hil", "id": "default-on-silence"}
    assert response["body"] == {"request": first.request, "choice": "do_not_run", "default_applied": True}


def test_attachments_are_untrusted_reach_the_worker_and_bring_in_the_critic(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit(files=[b"Smlouva o dilu c. 12/2026, platnost do roku 2027."])
    assert setup.runtime.run(task).state == "CLOSED_DONE"
    ref = setup.last(task, "TASK_SUBMITTED")["refs"][0]
    assert setup.ledger.artifact(ref)["untrusted"] is True
    assert "Smlouva o dilu" in setup.model.worker_prompts[0]
    assert any(e["body"]["gate"] == "gate.critic.check_criterion" for e in setup.ledger.events(task=task)
               if e["type"].startswith("GATE_"))


def test_personal_data_in_an_attachment_without_a_permitted_route_is_an_abstention(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit(files=["Kontakt: jan.novak@example.cz".encode()])
    assert setup.runtime.run(task).state == "CLOSED_ABSTAINED"
    assert setup.last(task, "ABSTAIN")["body"]["outcome"] == "ABSTAIN_NOT_PERMITTED"
    assert setup.model.worker_prompts == []


# Provider failures pause the task; it is not done (owner, 2026-10-02) -----------------------------------------

def test_a_provider_outage_pauses_the_task_and_the_next_run_finishes_it(tmp_path):
    setup = Setup(tmp_path, model=ScriptedModel(outages={("worker", 1): ConnectorError("UNAVAILABLE", "HTTP 529")}))
    task = setup.submit()
    paused = setup.runtime.run(task)
    assert paused.state == "RUNNING" and "Paused" in paused.summary and "ooat task run" in paused.summary
    assert setup.last(task, "RESULT")["body"]["error"]["code"] == "UNAVAILABLE"
    assert "TASK_CLOSED" not in setup.types(task) and task in setup.runtime.runnable()
    assert setup.runtime.run(task).state == "CLOSED_DONE"
    assert len(setup.ledger.events(task=task, types=["CONTRACT_ISSUED"])) == 1  # the same contract goes on


def test_an_outage_never_uses_up_an_attempt_and_the_feedback_survives_it(tmp_path):
    model = ScriptedModel(["Příliš dlouhé.", "# Krátké shrnutí"],
                          outages={("worker", 2): ConnectorError("TIMEOUT", "no answer")})
    setup = Setup(tmp_path, model=model, jev=decisions(met=[False, True]))
    task = setup.submit()
    assert setup.runtime.run(task).state == "RUNNING"
    assert setup.runtime.run(task).state == "CLOSED_DONE"
    assert len(model.worker_prompts) == 2 and CRITERIA[0] in model.worker_prompts[1]


def test_a_quota_cool_down_keeps_the_task_paused_until_the_window_resets(tmp_path):
    model = ScriptedModel(outages={("worker", 1): ConnectorError("QUOTA_EXHAUSTED", "limit reached")})
    setup = Setup(tmp_path, model=model)
    task = setup.submit()
    assert setup.runtime.run(task).state == "RUNNING"
    assert setup.runtime.run(task).state == "RUNNING"  # still cooling down: nothing is called
    setup.now = NOW + timedelta(hours=2)
    assert setup.runtime.run(task).state == "CLOSED_DONE"


def test_a_paused_acceptance_check_reruns_on_the_same_document(tmp_path):
    model = ScriptedModel(outages={("critic", 1): ConnectorError("TIMEOUT", "no answer")})
    setup = Setup(tmp_path, model=model)
    task = setup.submit(files=[b"Smlouva o dilu."])  # untrusted input: the critic must confirm
    assert setup.runtime.run(task).state == "RUNNING"
    paused = setup.last(task, "RESULT")
    assert paused["body"]["outcome"] == "FAILED" and paused["refs"]
    assert setup.runtime.run(task).state == "CLOSED_DONE"
    assert len(model.worker_prompts) == 1  # no new document was written


def test_a_rechecked_document_that_fails_gets_a_new_attempt_not_an_endless_loop(tmp_path):
    model = ScriptedModel(outages={("critic", 1): ConnectorError("TIMEOUT", "no answer")})
    setup = Setup(tmp_path, model=model, jev=decisions(met=[True, False]))
    task = setup.submit(files=[b"Smlouva o dilu."])  # untrusted: the first "met" goes to the critic, which is down
    assert setup.runtime.run(task).state == "RUNNING"
    assert setup.runtime.run(task).state == "CLOSED_PARTIAL"  # re-check unmet, one new attempt, still unmet
    assert len(model.worker_prompts) == 2 and len(setup.jev.calls) <= 5


def test_personal_data_in_an_attachment_raises_the_class_of_the_attachment_and_the_document(tmp_path):
    setup = Setup(tmp_path, classes=("public", "internal", "personal"))
    task = setup.submit(files=["Kontakt: jan.novak@example.cz".encode()])
    outcome = setup.runtime.run(task)
    assert outcome.state == "CLOSED_DONE"
    attachment = setup.last(task, "TASK_SUBMITTED")["refs"][0]
    assert setup.ledger.artifact(attachment)["data_class"] == "personal"
    assert setup.ledger.artifact(outcome.artifact)["data_class"] == "personal"


def test_no_operator_may_answer_as_the_silence_default(tmp_path):
    setup = Setup(tmp_path)
    with pytest.raises(ValueError, match="reserved"):
        setup.runtime.submit(operator="Default-On-Silence", goal="x")


def test_a_closed_task_stays_closed_and_an_unknown_one_is_refused(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit()
    setup.runtime.run(task)
    assert setup.runtime.run(task).summary == "The task is closed."
    with pytest.raises(ValueError, match="unknown task"):
        setup.runtime.run("tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7")
    assert task_state(setup.ledger.events(task=task)) == "CLOSED_DONE"


# Final review of plan 04c ---------------------------------------------------------------------------------------

def test_a_utf16_attachment_is_read_as_text_and_its_personal_data_is_found(tmp_path):
    setup = Setup(tmp_path, classes=("public", "internal", "personal"))
    task = setup.submit(files=["Kontakt: jan.novak@example.cz".encode("utf-16")])  # PowerShell 5 writes this
    ref = setup.last(task, "TASK_SUBMITTED")["refs"][0]
    assert setup.ledger.artifact(ref)["data_class"] == "personal"
    assert setup.artifacts.read(ref).decode("utf-8") == "Kontakt: jan.novak@example.cz"


@pytest.mark.parametrize("content", [b"\xff\xfe\x00\xd8", b"PK\x03\x04\x00\x00binary", b"\xe9t\xe9"])
def test_an_attachment_that_is_not_text_is_refused(tmp_path, content):
    setup = Setup(tmp_path)
    with pytest.raises(ValueError, match="text"):
        setup.submit(files=[content])


def interrupted_once(monkeypatch, when):
    """Make the n-th acceptance check raise KeyboardInterrupt, as Ctrl+C would."""
    import ooat_core.runtime as runtime_module
    real, calls = runtime_module.check_output, []

    def check(*args, **kwargs):
        calls.append(1)
        if len(calls) == when:
            raise KeyboardInterrupt
        return real(*args, **kwargs)
    monkeypatch.setattr(runtime_module, "check_output", check)


def test_an_interruption_after_delivery_rechecks_the_document_instead_of_writing_a_new_one(tmp_path, monkeypatch):
    setup = Setup(tmp_path)
    task = setup.submit()
    interrupted_once(monkeypatch, 1)
    with pytest.raises(KeyboardInterrupt):
        setup.runtime.run(task)
    assert setup.runtime.run(task).state == "CLOSED_DONE"
    assert len(setup.model.worker_prompts) == 1


def test_an_interruption_in_the_second_check_never_leads_to_a_third_attempt(tmp_path, monkeypatch):
    setup = Setup(tmp_path, jev=decisions(met=False))
    task = setup.submit()
    interrupted_once(monkeypatch, 2)
    with pytest.raises(KeyboardInterrupt):
        setup.runtime.run(task)
    assert setup.runtime.run(task).state == "CLOSED_PARTIAL"
    assert len(setup.model.worker_prompts) == 2


def test_a_contract_issued_before_a_crash_gets_its_claim_when_the_task_resumes(tmp_path, monkeypatch):
    setup = Setup(tmp_path)
    task = setup.submit()
    real_append = setup.ledger.append

    def crash_at_the_claim(event, artifacts=()):
        if event["type"] == "CLAIM":
            raise KeyboardInterrupt
        return real_append(event, artifacts)
    monkeypatch.setattr(setup.ledger, "append", crash_at_the_claim)
    with pytest.raises(KeyboardInterrupt):
        setup.runtime.run(task)
    monkeypatch.setattr(setup.ledger, "append", real_append)
    assert setup.runtime.run(task).state == "CLOSED_DONE"
    assert setup.types(task).count("CLAIM") == 1 and setup.types(task).count("CONTRACT_ISSUED") == 1


def test_personal_data_the_model_writes_into_the_document_raises_its_class(tmp_path):
    model = ScriptedModel(["# Odpověď\n\nNapište na jan.novak@example.cz."])
    setup = Setup(tmp_path, model=model, classes=("public", "internal", "personal"))
    task = setup.submit()
    setup.runtime.run(task)
    document = setup.last(task, "RESULT")["body"]["artifacts"][0]
    assert setup.ledger.artifact(document)["data_class"] == "personal"


# Owner decisions of 2026-10-03 and the third review of plan 04c --------------------------------------------------

def test_a_usable_first_document_is_kept_when_the_retry_brings_nothing_usable(tmp_path):
    for second in ('{"abstain": "UNKNOWN"}',
                   '{"abstain": "UNKNOWN", "reason": "Nevím.", "missing": "Víc času.", "confidence": 0.5}'):
        model = ScriptedModel(["# Shrnutí\n\nPrvní verze.", second])
        setup = Setup(tmp_path, model=model, jev=decisions(met=False))
        task = setup.submit()
        outcome = setup.runtime.run(task)
        first = [e for e in setup.ledger.events(task=task, types=["RESULT"]) if e["body"]["outcome"] == "DONE"][0]
        assert outcome.state == "CLOSED_PARTIAL" and outcome.artifact == first["body"]["artifacts"][0]
        assert setup.last(task, "RESULT")["body"]["outcome"] == "PARTIAL"


def test_the_contract_budget_never_exceeds_the_role_cap(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit(budget_usd=50.0)
    setup.runtime.run(task)
    assert setup.last(task, "CONTRACT_ISSUED")["body"]["contract"]["budget"]["max_usd"] == 5.0


def budget_setup(tmp_path):
    model = ScriptedModel(outages={("worker", 1): ConnectorError("TIMEOUT", "no answer")})
    setup = Setup(tmp_path, model=model)
    task = setup.submit(budget_usd=0.05)  # enough for one call: the failed one is charged its estimate
    assert setup.runtime.run(task).state == "RUNNING"
    asked = setup.runtime.run(task)
    return setup, task, asked


def test_a_budget_used_up_by_failed_calls_pauses_and_asks_to_raise_it(tmp_path):
    setup, task, asked = budget_setup(tmp_path)
    assert asked.state == "HIL_WAIT" and asked.request
    request = setup.last(task, "HIL_REQUEST")["body"]
    assert [o["id"] for o in request["options"]] == ["raise_budget", "do_not_run"]
    assert "failed provider calls" in request["question"] and request["default_on_silence"] == "do_not_run"
    setup.answer(task, asked.request, choice="raise_budget")
    assert setup.runtime.run(task).state == "CLOSED_DONE"
    budgets = [e["body"]["contract"]["budget"]["max_usd"] for e in setup.ledger.events(task=task)
               if e["type"] == "CONTRACT_ISSUED"]
    assert len(budgets) == 2 and budgets[1] > budgets[0]


def test_stopping_at_the_budget_question_cancels_the_task(tmp_path):
    setup, task, asked = budget_setup(tmp_path)
    setup.answer(task, asked.request, choice="do_not_run")
    assert setup.runtime.run(task).state == "CANCELLED"


def test_the_runtime_constants_match_the_catalog_cards():
    from ooat_core.catalog import load_card
    from ooat_core.runtime import CAPABILITY, CAPABILITY_VERSION, MAX_ATTEMPTS, ROLE
    from ooat_core.worker import WORKER_TIER

    capability, role = load_card("capabilities", CAPABILITY), load_card("roles", "role.general.worker")
    assert (CAPABILITY_VERSION, MAX_ATTEMPTS, WORKER_TIER) == (
        capability["version"], capability["model_policy"]["max_attempts"], capability["model_policy"]["tier"])
    assert ROLE == f"{role['id']}@{role['version']}" and CAPABILITY in role["capabilities"]

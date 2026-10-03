"""Rating a closed task and its decisions (design 04 §5, ADR 0011)."""

import pytest
from test_runtime import Setup

from ooat_core.rating import rate, task_decisions
from ooat_core.thresholds import rated_decisions


def closed_task(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit()
    setup.runtime.run(task)
    return setup, task


def test_the_decisions_of_a_task_are_listed_gate_first_then_acceptance(tmp_path):
    setup, task = closed_task(tmp_path)
    decisions = task_decisions(setup.ledger.events(task=task))
    assert [d.kind for d in decisions] == ["gate"] * 5 + ["acceptance"]
    assert [d.question for d in decisions] == ["a1.1", "a4", "a5", "a7", "a10", "c1"]
    assert decisions[2].answer == "one" and decisions[5].answer == 0.95


def test_rating_records_confirmations_and_corrections_that_feed_the_thresholds(tmp_path):
    setup, task = closed_task(tmp_path)
    decisions = task_decisions(setup.ledger.events(task=task))
    gate, acceptance = decisions[0], decisions[5]
    event = rate(setup.ledger, task, operator="Martin", accepted=True, value_class="B", note="Dobré.",
                 verdicts={(gate.event, "a1.1"): "confirmed", (gate.event, "a5"): "two",
                           (acceptance.event, "c1"): 0})
    assert event["body"]["decisions"] == [
        {"event": gate.event, "question": "a1.1", "verdict": "confirmed"},
        {"event": gate.event, "question": "a5", "verdict": "corrected", "value": "two"},
        {"event": acceptance.event, "question": "c1", "verdict": "corrected", "value": 0}]
    assert event["actor"] == {"kind": "hil", "id": "Martin"} and event["body"]["note"] == "Dobré."
    rated = rated_decisions(setup.ledger.events())
    assert sorted((r.point, r.correct) for r in rated) == [("a1", True), ("a5", False), ("acceptance", False)]


@pytest.mark.parametrize("verdicts, message", [
    ("unknown_event", "no decision"),
    ("a5_as_number", "one of its options"),
    ("c1_as_word", "correct a yes/no decision"),
    ("c1_as_two", "correct a yes/no decision"),
    ("c1_as_true", "correct a yes/no decision"),
])
def test_wrong_verdicts_are_refused(tmp_path, verdicts, message):
    setup, task = closed_task(tmp_path)
    decisions = {d.question: d for d in task_decisions(setup.ledger.events(task=task))}
    verdicts = {"unknown_event": {("evt_01J9ZQ70A0K3M5N7P9Q1R3S5T7", "a1.1"): "confirmed"},
                "a5_as_number": {(decisions["a5"].event, "a5"): 1},
                "c1_as_word": {(decisions["c1"].event, "c1"): "yes"},
                "c1_as_two": {(decisions["c1"].event, "c1"): 2},
                "c1_as_true": {(decisions["c1"].event, "c1"): True}}[verdicts]
    with pytest.raises(ValueError, match=message):
        rate(setup.ledger, task, operator="Martin", accepted=True, value_class="B", verdicts=verdicts)


def test_only_a_closed_task_can_be_rated(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit(acceptance=())
    setup.runtime.run(task)  # waits for a clarification
    with pytest.raises(ValueError, match="once it is closed"):
        rate(setup.ledger, task, operator="Martin", accepted=False, value_class="C")


def test_typing_the_answer_the_decision_already_gave_counts_as_confirmed(tmp_path):
    setup, task = closed_task(tmp_path)
    decisions = {d.question: d for d in task_decisions(setup.ledger.events(task=task))}
    event = rate(setup.ledger, task, operator="Martin", accepted=True, value_class="B", verdicts={
        (decisions["c1"].event, "c1"): 1, (decisions["a5"].event, "a5"): "one"})
    assert {d["verdict"] for d in event["body"]["decisions"]} == {"confirmed"}


def test_a_choice_correction_must_be_one_of_the_question_options(tmp_path):
    setup, task = closed_task(tmp_path)
    decision = {d.question: d for d in task_decisions(setup.ledger.events(task=task))}["a10"]
    with pytest.raises(ValueError, match="one of"):
        rate(setup.ledger, task, operator="Martin", accepted=True, value_class="B",
             verdicts={(decision.event, "a10"): "pubic"})

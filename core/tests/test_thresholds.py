"""θ per decision point, engine and model version from ratings in the ledger (ADR 0011)."""

import pytest

from ooat_core.ids import new_id
from ooat_core.thresholds import (RatedDecision, computed_threshold, rated_decisions, reception_threshold,
                                 reception_verdicts, threshold)

JEV, VERSION = "prv.typesafe.api", "jev-1.13.0"


def record(question, confidence, engine=JEV, model=VERSION):
    return {"question": question, "engine": engine, "model": model, "answer": 0.9, "confidence": confidence,
            "threshold": 0.8}


def gate_event(*records, task=None):
    return {"id": new_id("evt"), "type": "TOPOLOGY_DECIDED", "task": task or new_id("tsk"),
            "body": {"decisions": list(records)}}


def acceptance_event(*records, task=None):
    criteria = [{"id": r["question"].replace(".", "_"), "passed": True, "decision": r} for r in records]
    return {"id": new_id("evt"), "type": "GATE_PASSED", "task": task or new_id("tsk"), "body": {"criteria": criteria}}


def rating(event, question, verdict):
    item = {"event": event["id"], "question": question, "verdict": verdict}
    if verdict == "corrected":
        item["value"] = 0
    return {"id": new_id("evt"), "type": "TASK_RATED", "body": {"decisions": [item]}}


def history(point_question, outcomes, engine=JEV, model=VERSION, maker=gate_event):
    """Events for rated decisions: outcomes is a list of (confidence, correct)."""
    events = []
    for confidence, correct in outcomes:
        decided = maker(record(point_question, confidence, engine, model))
        events += [decided, rating(decided, point_question, "confirmed" if correct else "corrected")]
    return events


def test_before_five_ratings_jev_uses_the_interim_threshold_and_the_fallback_never_acts_alone():
    events = history("a1.1", [(0.95, True)] * 4)
    assert threshold(events, "a1", JEV, VERSION) == 0.8
    assert threshold(events, "a1", "prv.anthropic.api", "claude-haiku", decision_engine=False) == 1.0


def test_from_five_ratings_the_floor_of_0_8_holds_and_a_computed_value_can_raise_it():
    good = history("a1.1", [(0.6, True)] * 5)
    assert threshold(good, "a1", JEV, VERSION) == 0.8  # computed 0.5, floored
    risky = history("a1.1", [(0.85, False)] * 2 + [(0.95, True)] * 5)
    assert threshold(risky, "a1", JEV, VERSION) == 0.86


def test_from_twenty_ratings_the_computed_value_alone_applies():
    events = history("a5", [(0.6, True)] * 20)
    assert threshold(events, "a5", JEV, VERSION) == 0.5


def test_without_a_qualifying_threshold_nothing_acts_alone():
    events = history("a1.1", [(0.95, False)] * 6)
    assert threshold(events, "a1", JEV, VERSION) == 1.0


def test_keys_are_separate_by_point_engine_and_model_version():
    events = history("a1.1", [(0.6, True)] * 20) + history("a1.2", [(0.95, False)] * 20, model="jev-1.14.0")
    assert threshold(events, "a1", JEV, VERSION) == 0.5
    assert threshold(events, "a1", JEV, "jev-1.14.0") == 1.0
    assert threshold(events, "a4", JEV, VERSION) == 0.8  # not rated yet
    assert threshold(events, "acceptance", JEV, VERSION) == 0.8


def test_acceptance_decisions_are_rated_from_gate_events():
    events = history("c1", [(0.6, True)] * 20, maker=acceptance_event)
    assert threshold(events, "acceptance", JEV, VERSION) == 0.5
    assert {r.point for r in rated_decisions(events)} == {"acceptance"}


def test_r1_tolerates_fewer_errors_and_r2_never_acts_alone():
    events = history("a1.1", [(0.9, True)] * 19 + [(0.9, False)])  # 5 % errors
    assert threshold(events, "a1", JEV, VERSION, "R0") == 0.5
    assert threshold(events, "a1", JEV, VERSION, "R1") == 1.0
    assert threshold(events, "a1", JEV, VERSION, "R2") == 1.0


def test_a_later_rating_of_the_same_decision_replaces_the_earlier_one():
    decided = gate_event(record("a1.1", 0.9))
    events = [decided, rating(decided, "a1.1", "corrected"), rating(decided, "a1.1", "confirmed")]
    assert [r.correct for r in rated_decisions(events)] == [True]


def test_ratings_of_unknown_decisions_are_ignored():
    stray = {"id": new_id("evt"), "type": "TOPOLOGY_DECIDED", "body": {}}
    assert rated_decisions([rating(stray, "a1.1", "confirmed")]) == []


@pytest.mark.parametrize("outcomes, expected", [
    ([(0.7, True)] * 4, 1.0),  # support below 5
    ([(0.55, False)] + [(0.7, True)] * 5, 0.56),
])
def test_computed_threshold_needs_support_and_a_low_error_rate(outcomes, expected):
    rated = [RatedDecision("a1", JEV, VERSION, c, ok) for c, ok in outcomes]
    assert computed_threshold(rated, 0.05) == expected


def test_the_default_risk_class_is_the_stricter_r1():
    events = history("a1.1", [(0.9, True)] * 19 + [(0.9, False)])  # 5 % errors: enough for R0 only
    assert threshold(events, "a1", JEV, VERSION) == 1.0


def test_ratings_from_a_single_task_never_leave_the_interim_threshold():
    task = new_id("tsk")
    events = []
    for _ in range(6):
        decided = gate_event(record("a1.1", 0.95, "prv.anthropic.api", "claude-haiku"), task=task)
        events += [decided, rating(decided, "a1.1", "confirmed")]
    assert threshold(events, "a1", "prv.anthropic.api", "claude-haiku", decision_engine=False) == 1.0
    assert threshold(events, "a1", "prv.anthropic.api", "claude-haiku", decision_engine=True) == 0.8
    other = gate_event(record("a1.1", 0.95, "prv.anthropic.api", "claude-haiku"))  # a second task
    events += [other, rating(other, "a1.1", "confirmed")]
    assert threshold(events, "a1", "prv.anthropic.api", "claude-haiku", decision_engine=False) == 0.8


# The reception's threshold (plan 08a task 8) ------------------------------------------------------------------



def _decided(conversation, kind, confidence=0.75, engine="prv.fake.api", model="fake-economy", task=None):
    body = {"conversation": conversation, "decision": kind, "messages": [new_id("evt")],
            "record": {"engine": engine, "model": model, "confidence": confidence, "threshold": 0.7}}
    if task:
        body["task"] = task
    return {"id": new_id("evt"), "ts": "2026-10-16T12:00:00.000000Z", "task": None, "type": "RECEPTION_DECIDED",
            "actor": {"kind": "system", "id": "ooat-reception"}, "body": body}


def _tap(conversation, tap):
    return {"id": new_id("evt"), "ts": "2026-10-16T12:00:01.000000Z", "task": None, "type": "CONVERSATION_MESSAGE",
            "actor": {"kind": "hil", "id": "operator"}, "body": {"conversation": conversation, "tap": tap}}


def _confirmed(n, yes=True, confidence=0.75, **options):
    events = []
    for _ in range(n):
        conversation = new_id("cnv")
        events += [_decided(conversation, "confirm", confidence, **options),
                   _tap(conversation, "yes" if yes else "differently")]
    return events


def test_yes_confirms_and_differently_corrects():
    conversation = new_id("cnv")
    verdicts = reception_verdicts([_decided(conversation, "confirm"), _tap(conversation, "differently")])
    assert [(v.point, v.correct, v.task) for v in verdicts] == [("reception", False, conversation)]
    assert reception_verdicts(_confirmed(1))[0].correct is True


def test_interim_theta_until_five_verdicts():
    assert reception_threshold(_confirmed(4, confidence=0.9), "prv.fake.api", "fake-economy", 0.7) == 0.7


def test_the_interim_is_the_floor_until_twenty():
    assert reception_threshold(_confirmed(6, confidence=0.6), "prv.fake.api", "fake-economy", 0.7) == 0.7


def test_twenty_verdicts_compute_theta():
    events = _confirmed(20, confidence=0.6)
    assert reception_threshold(events, "prv.fake.api", "fake-economy", 0.7) == 0.5  # all correct: the grid's lowest


def test_wrong_decisions_raise_theta():
    events = _confirmed(20, confidence=0.6, yes=False) + _confirmed(20, confidence=0.95)
    assert reception_threshold(events, "prv.fake.api", "fake-economy", 0.7) == 0.61


def test_a_quick_cancel_corrects_the_decision_and_an_accepted_rating_confirms_it():
    conversation, quick, kept = new_id("cnv"), new_id("tsk"), new_id("tsk")
    events = [_decided(conversation, "task", task=quick), _decided(conversation, "task", task=kept)]
    for task in (quick, kept):
        events.append({"id": new_id("evt"), "ts": "2026-10-16T12:00:00.000000Z", "task": task,
                       "type": "TASK_SUBMITTED", "actor": {"kind": "hil", "id": "operator"}, "body": {"goal": "x"}})
    events.append({"id": new_id("evt"), "ts": "2026-10-16T12:01:00.000000Z", "task": quick, "type": "DECISION",
                   "actor": {"kind": "hil", "id": "operator"}, "body": {"decision": "cancel the task"}})
    events.append({"id": new_id("evt"), "ts": "2026-10-16T13:00:00.000000Z", "task": kept, "type": "TASK_RATED",
                   "actor": {"kind": "hil", "id": "operator"}, "body": {"accepted": True, "value_class": "B"}})
    assert sorted(v.correct for v in reception_verdicts(events)) == [False, True]


def test_a_late_cancel_is_no_verdict():
    conversation, task = new_id("cnv"), new_id("tsk")
    events = [_decided(conversation, "task", task=task),
              {"id": new_id("evt"), "ts": "2026-10-16T12:00:00.000000Z", "task": task, "type": "TASK_SUBMITTED",
               "actor": {"kind": "hil", "id": "operator"}, "body": {"goal": "x"}},
              {"id": new_id("evt"), "ts": "2026-10-16T12:10:00.000000Z", "task": task, "type": "DECISION",
               "actor": {"kind": "hil", "id": "operator"}, "body": {"decision": "cancel the task"}}]
    assert reception_verdicts(events) == []


def test_reception_thresholds_are_per_engine_and_model():
    events = _confirmed(20, confidence=0.6)
    assert reception_threshold(events, "prv.fake.api", "fake-model", 0.7) == 0.7
    assert reception_threshold(events, "prv.other.api", "fake-economy", 0.7) == 0.7

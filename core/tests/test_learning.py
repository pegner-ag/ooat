"""The learning price list from the ledger (spec §11 Price-list calibration; plan 09 decisions 1-3)."""

import pytest

from ooat_core.ids import new_id
from ooat_core.learning import GENERAL, card_prior, observed, p_accept

CAP = "cap.general.complete_task"


def run(state="CLOSED_DONE", accepted=None, task_type=None):
    """A task that ran one contract and closed; rated when `accepted` is given."""
    task, ctr = new_id("tsk"), new_id("ctr")
    body = {"goal": "x", **({"task_type": task_type} if task_type else {})}
    events = [{"id": new_id("evt"), "type": "TASK_SUBMITTED", "task": task, "ts": "2026-10-19T10:00:00Z",
               "body": body},
              {"id": new_id("evt"), "type": "CONTRACT_ISSUED", "task": task, "contract": ctr,
               "body": {"contract": {"id": ctr, "capability": CAP}}},
              {"id": new_id("evt"), "type": "TASK_CLOSED", "task": task, "body": {"state": state}}]
    if accepted is not None:
        events.append({"id": new_id("evt"), "type": "TASK_RATED", "task": task,
                       "body": {"accepted": accepted, "value_class": "B"}})
    return events


def test_without_ratings_p_accept_is_the_cards_prior():
    assert p_accept([], CAP, None, 0.7) == pytest.approx(0.7)


def test_each_rating_moves_the_beta_mean_weighted_against_five_prior_observations():
    events = run(accepted=True) + run(accepted=False) + run(accepted=False)
    # (0.7 * 5 + 1) / (5 + 3)
    assert p_accept(events, CAP, None, 0.7) == pytest.approx(4.5 / 8)


def test_a_justified_abstention_is_not_a_failure_and_a_lazy_one_is():
    justified = run("CLOSED_ABSTAINED", accepted=True)
    lazy = run("CLOSED_ABSTAINED", accepted=False)
    assert p_accept(justified, CAP, None, 0.7) == pytest.approx(0.7)
    assert p_accept(lazy, CAP, None, 0.7) == pytest.approx(3.5 / 6)


def test_unrated_runs_and_gate_closures_without_a_contract_count_only_where_they_belong():
    gate_closed = [e for e in run("CLOSED_ABSTAINED", accepted=False) if e["type"] != "CONTRACT_ISSUED"]
    events = run() + run("CLOSED_ABSTAINED") + gate_closed
    [row] = observed(events, {CAP: 0.7})
    assert (row.n, row.runs, row.p_abstain, row.p_accept) == (0, 2, 0.5, pytest.approx(0.7))


def test_task_types_are_separate_rows_and_a_task_without_one_is_general():
    events = run(accepted=True, task_type="copy") + run(accepted=False)
    rows = {r.task_type: r for r in observed(events, {CAP: 0.7})}
    assert set(rows) == {"copy", GENERAL} and rows["copy"].accepted == 1 and rows[GENERAL].accepted == 0
    assert p_accept(events, CAP, "copy", 0.7) == pytest.approx(4.5 / 6)


def test_the_cards_prior_is_read_from_the_catalog():
    assert card_prior(CAP) == pytest.approx(0.7)


from ooat_core.learning import summary


def conversation(*steps):
    """Reception events of one conversation: ("decided", kind, extra) or ("tap", tap)."""
    cnv, events = new_id("cnv"), []
    for step in steps:
        if step[0] == "decided":
            events.append({"id": new_id("evt"), "type": "RECEPTION_DECIDED", "task": None, "ts": "2026-10-19T10:00:00Z",
                           "actor": {"kind": "system", "id": "ooat-reception"},
                           "body": {"conversation": cnv, "decision": step[1], **step[2]}})
        else:
            events.append({"id": new_id("evt"), "type": "CONVERSATION_MESSAGE", "task": None,
                           "ts": "2026-10-19T10:00:05Z", "actor": {"kind": "hil", "id": "operator"},
                           "body": {"conversation": cnv, "tap": step[1]}})
    return events


def test_reception_decisions_are_counted_with_the_differently_that_followed_them():
    events = conversation(("decided", "confirm", {}), ("tap", "differently"), ("decided", "task", {}),
                          ("decided", "escalated", {}),
                          ("decided", "answer", {"lesson": {"kind": "fact", "text": "x"}}),
                          ("tap", "remember"))
    events.append({"id": new_id("evt"), "type": "MEMORY_NOTED", "task": None, "ts": "2026-10-19T10:00:06Z",
                   "actor": {"kind": "hil", "id": "operator"}, "body": {"source": events[-1]["id"]}})
    found = summary(events, visible=lambda task: True, reception_interim=0.8)
    rows = {r["decision"]: r for r in found["reception"]}
    assert rows["confirm"] == {"decision": "confirm", "count": 1, "differently": 1, "cancelled": 0}
    assert "escalated" not in rows  # a replaced call is not a decision the person saw
    assert found["memory"]["lessons_offered"] == 1 and found["memory"]["lessons_kept"] == 1


def test_a_rejected_task_needs_a_look_only_within_the_cap():
    shown, hidden = run(accepted=False), run(accepted=False)
    found = summary(shown + hidden, visible=lambda task: task == shown[0]["task"], reception_interim=0.8)
    assert [a["task"] for a in found["attention"]] == [shown[0]["task"]]
    assert found["price_list"][0]["n"] == 2  # counts include the task above the cap


def test_a_justified_abstention_does_not_need_a_look():
    found = summary(run("CLOSED_ABSTAINED", accepted=True), visible=lambda task: True, reception_interim=0.8)
    assert found["attention"] == []


def test_a_refused_remember_tap_is_not_counted_as_kept():
    events = conversation(("decided", "task", {"lesson": {"kind": "fact", "text": "x"}}), ("tap", "remember"),
                          ("tap", "remember"))
    tap = events[1]
    events.insert(2, {"id": new_id("evt"), "type": "MEMORY_NOTED", "task": None, "ts": "2026-10-19T10:00:06Z",
                      "actor": {"kind": "hil", "id": "operator"},
                      "body": {"memory": new_id("mem"), "scope": "docs", "kind": "fact", "source": tap["id"]}})
    assert summary(events, visible=lambda task: True, reception_interim=0.8)["memory"]["lessons_kept"] == 1


def test_a_rating_note_with_personal_data_is_not_shown():
    events = run(accepted=False)
    events[-1]["body"]["note"] = "Volal Jan Novák, jan.novak@example.cz"
    assert summary(events, visible=lambda task: True, reception_interim=0.8)["attention"][0]["note"] is None

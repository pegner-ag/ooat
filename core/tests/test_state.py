import pytest

from ooat_core.ids import new_id
from ooat_core.ledger import Ledger, new_event
from ooat_core.state import contract_state, task_state


def ev(kind, body=None, id="evt_x", contract=None):
    event = {"id": id, "type": kind, "body": body or {}}
    if contract:
        event["contract"] = contract
    return event


SUBMITTED = ev("TASK_SUBMITTED", {"goal": "g"})
GATED_T2 = ev("TOPOLOGY_DECIDED", {"topology": "T2", "rules_applied": [], "candidates": []})
CLARIFY = ev("TOPOLOGY_DECIDED", {"topology": "T0", "rules_applied": ["A1"], "candidates": []})
ISSUED = ev("CONTRACT_ISSUED", {}, contract="ctr_1")


def request(id, blocking=True):
    return ev("HIL_REQUEST", {"blocking": blocking}, id=id)


def response(request_id):
    return ev("HIL_RESPONSE", {"request": request_id, "choice": "a"})


@pytest.mark.parametrize("events, expected", [
    ([], None),
    ([request("evt_q")], None),  # nothing submitted yet
    ([SUBMITTED], "SUBMITTED"),
    ([SUBMITTED, CLARIFY], "CLARIFYING"),
    ([SUBMITTED, CLARIFY, request("evt_q")], "CLARIFYING"),
    # ADR 0009: once every clarifying question is answered, the task is back in SUBMITTED for re-gating
    ([SUBMITTED, CLARIFY, request("evt_q"), response("evt_q")], "SUBMITTED"),
    ([SUBMITTED, CLARIFY, request("evt_q"), request("evt_r"), response("evt_q")], "CLARIFYING"),
    ([SUBMITTED, CLARIFY, request("evt_q"), request("evt_r"), response("evt_q"), response("evt_r")], "SUBMITTED"),
    ([SUBMITTED, CLARIFY, request("evt_q"), response("evt_q"), GATED_T2], "GATED"),
    ([SUBMITTED, GATED_T2], "GATED"),
    ([SUBMITTED, GATED_T2, ISSUED], "RUNNING"),
    ([SUBMITTED, GATED_T2, ISSUED, request("evt_q")], "HIL_WAIT"),
    ([SUBMITTED, GATED_T2, ISSUED, request("evt_q"), response("evt_q")], "RUNNING"),
    ([SUBMITTED, GATED_T2, ISSUED, request("evt_q", blocking=False)], "RUNNING"),
    ([SUBMITTED, GATED_T2, ISSUED, request("evt_q"), ev("TASK_CLOSED", {"state": "CLOSED_ABSTAINED"})],
     "CLOSED_ABSTAINED"),
])
def test_task_state(events, expected):
    assert task_state(events) == expected


def test_contract_state_follows_its_own_events():
    events = [
        ev("CONTRACT_ISSUED", contract="ctr_1"),
        ev("CONTRACT_ISSUED", contract="ctr_2"),
        ev("CLAIM", contract="ctr_1"),
        ev("RESULT", {"outcome": "FAILED"}, contract="ctr_1"),
        ev("CLAIM", contract="ctr_1"),  # a crashed contract is restarted, not the task
        ev("ABSTAIN", {"outcome": "ABSTAIN_UNKNOWN"}, contract="ctr_2"),
    ]
    assert contract_state(events, "ctr_1") == "CLAIMED"
    assert contract_state(events, "ctr_2") == "ABSTAIN_UNKNOWN"
    assert contract_state(events + [ev("RESULT", {"outcome": "DONE"}, contract="ctr_1")], "ctr_1") == "DONE"
    assert contract_state(events, "ctr_3") is None


def test_task_state_can_select_one_task():
    events = [{**SUBMITTED, "task": "tsk_a"}, {**SUBMITTED, "task": "tsk_b"}, {**GATED_T2, "task": "tsk_b"}]
    assert task_state(events, task="tsk_a") == "SUBMITTED"
    assert task_state(events, task="tsk_b") == "GATED"


def test_state_survives_reopening_a_file_ledger(tmp_path):
    url, task, contract = f"sqlite:///{tmp_path / 'ledger.sqlite'}", new_id("tsk"), new_id("ctr")
    system = {"kind": "system", "id": "ooat-core"}
    events = [
        new_event("TASK_SUBMITTED", task=task, actor={"kind": "hil", "id": "operator"}, body={"goal": "Shrnout."}),
        new_event("TOPOLOGY_DECIDED", task=task, actor=system,
                  body={"topology": "T2", "rules_applied": [], "candidates": [{"topology": "T2"}]}),
        new_event("CONTRACT_ISSUED", task=task, contract=contract, actor=system, body={"contract": {
            "id": contract, "task": task, "capability": "cap.general.complete_task", "capability_version": "0.1.0",
            "agent": new_id("agt"), "role": "role.general.worker@0.1.0", "goal": "Shrnout.", "inputs": [],
            "output_schema": "schemas/summary.v1.json", "budget": {"max_usd": 1.0}}}),
        new_event("HIL_REQUEST", task=task, actor=system, body={
            "question": "Pokračovat?", "options": [{"id": "a", "label": "Ano", "cost_usd": 0.1},
                                                   {"id": "b", "label": "Ne", "cost_usd": 0.0}],
            "recommended": "a", "default_on_silence": "b", "deadline": "2026-10-02T10:00:00Z",
            "blocking": True, "evidence": []}),
    ]
    ledger = Ledger.open(url)
    for event in events:
        ledger.append(event)
    ledger.close()
    ledger = Ledger.open(url)
    stored = ledger.events(task=task)
    ledger.close()
    assert task_state(stored, task=task) == "HIL_WAIT"
    assert contract_state(stored, contract) == "ISSUED"

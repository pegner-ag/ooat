import pytest

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
    ([SUBMITTED], "SUBMITTED"),
    ([SUBMITTED, CLARIFY], "CLARIFYING"),
    ([SUBMITTED, CLARIFY, request("evt_q")], "CLARIFYING"),
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

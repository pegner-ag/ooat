"""Task and contract state as projections over ledger events (spec §8).

State is never stored: it is recomputed from events, so a restarted runtime sees exactly what the ledger holds.
F1 covers topologies T0–T2; PLANNED and REVIEW arrive with T3+.
"""

from collections.abc import Iterable


def task_state(events: Iterable[dict], task: str | None = None) -> str | None:
    """Lifecycle state of one task from its events in ledger order; None before TASK_SUBMITTED.

    Pass `task` when `events` may contain other tasks' events.
    """
    state, open_requests = None, set()
    for event in events:
        if task is not None and event.get("task") != task:
            continue
        kind, body = event["type"], event["body"]
        if kind == "TASK_SUBMITTED":
            state = "SUBMITTED"
        elif kind == "TOPOLOGY_DECIDED":
            clarifying = body["topology"] == "T0" and "A1" in body["rules_applied"]
            state = "CLARIFYING" if clarifying else "GATED"
        elif kind == "CONTRACT_ISSUED":
            state = "RUNNING"
        elif kind == "HIL_REQUEST" and body["blocking"]:
            open_requests.add(event["id"])
        elif kind == "HIL_RESPONSE":
            open_requests.discard(body["request"])
        elif kind == "TASK_CLOSED":
            return body["state"]
    if state is None:
        return None
    if open_requests and state != "CLARIFYING":
        return "HIL_WAIT"
    return state


def contract_state(events: Iterable[dict], contract_id: str) -> str | None:
    """ISSUED, CLAIMED or the last outcome (DONE, PARTIAL, FAILED, ABSTAIN_*); None if never issued."""
    state = None
    for event in events:
        if event.get("contract") != contract_id:
            continue
        if event["type"] == "CONTRACT_ISSUED":
            state = "ISSUED"
        elif event["type"] == "CLAIM":
            state = "CLAIMED"
        elif event["type"] in ("RESULT", "ABSTAIN"):
            state = event["body"]["outcome"]
    return state

"""Rating a closed task and confirming or correcting its decisions (design 04 §5; ADR 0011).

TASK_RATED carries the operator's verdict on every decision they look at: the Gate's (TOPOLOGY_DECIDED, every Gate
run) and the acceptance checks' (GATE_* events, every attempt). These verdicts are what thresholds.py calibrates on.
"""

from dataclasses import dataclass

from .connector_admin import checked_operator
from .ledger import Ledger, new_event
from .runtime import CLOSED
from .state import task_state
from .thresholds import GATE_EVENTS


@dataclass(frozen=True)
class TaskDecision:
    event: str  # the event that holds the decision record
    question: str
    kind: str  # "gate" or "acceptance"
    answer: float | str  # noul: probability of yes; choice: the option
    confidence: float


def task_decisions(events: list[dict]) -> list[TaskDecision]:
    """Every decision record of the task, in ledger order."""
    found = []
    for event in events:
        if event["type"] == "TOPOLOGY_DECIDED":
            records = [("gate", r) for r in event["body"].get("decisions", [])]
        elif event["type"] in GATE_EVENTS:
            records = [("acceptance", c["decision"]) for c in event["body"].get("criteria", []) if "decision" in c]
        else:
            continue
        found += [TaskDecision(event["id"], r["question"], kind, r["answer"], r["confidence"]) for kind, r in records]
    return found


def rate(ledger: Ledger, task: str, *, operator: str, accepted: bool, value_class: str,
         verdicts: dict[tuple[str, str], object] = None, note: str | None = None) -> dict:
    """Append TASK_RATED. `verdicts` maps (event id, question) to "confirmed" or to the correct answer: 0 or 1
    for a yes/no decision, the right option for a choice. Decisions left out stay unrated."""
    events = ledger.events(task=task)
    state = task_state(events)
    if state not in CLOSED:
        raise ValueError(f"task {task} is {state}; rate it once it is closed")
    operator = checked_operator(operator)
    decisions = {(d.event, d.question): d for d in task_decisions(events)}
    rated = []
    for key, verdict in (verdicts or {}).items():
        decision = decisions.get(key)
        if decision is None:
            raise ValueError(f"no decision {key[1]} in event {key[0]} of task {task}")
        if verdict == "confirmed":
            rated.append({"event": key[0], "question": key[1], "verdict": "confirmed"})
            continue
        if isinstance(decision.answer, str) != isinstance(verdict, str) or (
                not isinstance(verdict, str) and (type(verdict) is not int or verdict not in (0, 1))):
            raise ValueError(f"{key[1]}: correct a yes/no decision with 0 or 1, a choice with the right option")
        rated.append({"event": key[0], "question": key[1], "verdict": "corrected", "value": verdict})
    body = {"accepted": accepted, "value_class": value_class, "decisions": rated}
    if note and note.strip():
        body["note"] = note.strip()
    closed = [e["id"] for e in events if e["type"] == "TASK_CLOSED"]
    return ledger.append(new_event("TASK_RATED", task=task, actor={"kind": "hil", "id": operator}, refs=closed,
                                   body=body))

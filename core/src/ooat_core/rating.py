"""Rating a closed task and confirming or correcting its decisions (design 04 §5; ADR 0011).

TASK_RATED carries the operator's verdict on every decision they look at: the Gate's (TOPOLOGY_DECIDED, every Gate
run) and the acceptance checks' (GATE_* events, every attempt). These verdicts are what thresholds.py calibrates on.
"""

from dataclasses import dataclass

from .acceptance import CRITIC_CONFIDENCE, GATE_CRITIC as CRITIC_GATE
from .connector_admin import checked_operator
from .gate import BRANCHES, DATA_CLASSES
from .ledger import Ledger, new_event
from .runtime import CLOSED
from .state import task_state
from .thresholds import GATE_EVENTS


CHOICE_OPTIONS = {"a5": set(BRANCHES), "a10": set(DATA_CLASSES)}  # the Gate's choice questions


class NotClosed(ValueError):
    """Only a closed task is rated."""


class AlreadyRated(ValueError):
    """A task is rated once."""


@dataclass(frozen=True)
class TaskDecision:
    event: str  # the event that holds the decision record
    question: str
    kind: str  # "gate" or "acceptance"
    answer: float | str  # noul: probability of yes; choice: the option
    confidence: float
    disputed: bool = False  # the critic later judged the same criterion of the same document the other way


def task_decisions(events: list[dict]) -> list[TaskDecision]:
    """Every decision record of the task, in ledger order."""
    found, critic = [], {}
    for event in events:  # the critic's sure verdicts, by document and criterion; no answer or an unsure one is none
        if event["type"] in GATE_EVENTS and event["body"].get("gate") == CRITIC_GATE:
            critic |= {(tuple(event["refs"]), c["id"]): c["passed"] for c in event["body"].get("criteria", [])
                       if c.get("score", 0) >= CRITIC_CONFIDENCE}
    for event in events:
        if event["type"] == "TOPOLOGY_DECIDED":
            records = [("gate", r) for r in event["body"].get("decisions", [])]
        elif event["type"] in GATE_EVENTS:
            records = [("acceptance", c["decision"]) for c in event["body"].get("criteria", []) if "decision" in c]
        else:
            continue
        for kind, r in records:
            judged = critic.get((tuple(event["refs"]), r["question"])) if kind == "acceptance" else None
            disputed = judged is not None and judged != (r["answer"] >= 0.5)
            found.append(TaskDecision(event["id"], r["question"], kind, r["answer"], r["confidence"], disputed))
    return found


def checked_verdict(decision: TaskDecision, verdict) -> object:
    """"confirmed", or the corrected value. Typing the answer the decision already gave is a confirmation, so it
    is never counted as an error of the engine; a correction must fit the question."""
    if verdict == "confirmed":
        return verdict
    if isinstance(decision.answer, str):
        options = CHOICE_OPTIONS.get(decision.question)
        if not isinstance(verdict, str) or (options is not None and verdict not in options):
            listed = f": {', '.join(sorted(options))}" if options else ""
            raise ValueError(f"{decision.question}: correct a choice with one of its options{listed}")
        return "confirmed" if verdict == decision.answer else verdict
    if type(verdict) is not int or verdict not in (0, 1):
        raise ValueError(f"{decision.question}: correct a yes/no decision with 0 or 1, a choice with one of its "
                         "options")
    return "confirmed" if verdict == (1 if decision.answer >= 0.5 else 0) else verdict


def rate(ledger: Ledger, task: str, *, operator: str, accepted: bool, value_class: str,
         verdicts: dict[tuple[str, str], object] = None, note: str | None = None, channel: str | None = None) -> dict:
    """Append TASK_RATED. `verdicts` maps (event id, question) to "confirmed" or to the correct answer: 0 or 1
    for a yes/no decision, the right option for a choice. Decisions left out stay unrated."""
    events = ledger.events(task=task)
    state = task_state(events)
    if state not in CLOSED:
        raise NotClosed(f"task {task} is {state}; rate it once it is closed")
    if any(e["type"] == "TASK_RATED" for e in events):  # a second rating would count its verdicts twice in θ
        raise AlreadyRated(f"task {task} is already rated")
    operator = checked_operator(operator)
    decisions = {(d.event, d.question): d for d in task_decisions(events)}
    rated = []
    for key, verdict in (verdicts or {}).items():
        decision = decisions.get(key)
        if decision is None:
            raise ValueError(f"no decision {key[1]} in event {key[0]} of task {task}")
        verdict = checked_verdict(decision, verdict)
        if verdict == "confirmed":
            rated.append({"event": key[0], "question": key[1], "verdict": "confirmed"})
        else:
            rated.append({"event": key[0], "question": key[1], "verdict": "corrected", "value": verdict})
    body = {"accepted": accepted, "value_class": value_class, "decisions": rated}
    if note and note.strip():
        body["note"] = note.strip()
    if channel is not None:
        body["channel"] = channel
    closed = [e["id"] for e in events if e["type"] == "TASK_CLOSED"]
    return ledger.append(new_event("TASK_RATED", task=task, actor={"kind": "hil", "id": operator}, refs=closed,
                                   body=body))

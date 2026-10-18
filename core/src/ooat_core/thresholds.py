"""Confidence thresholds θ per decision point, engine and model version (ADR 0011, spec §6).

A decision acts alone only when its confidence reaches θ. θ is computed from the operator's ratings in the ledger:
decision records live in TOPOLOGY_DECIDED (Gate) and GATE_PASSED / GATE_FAILED (acceptance), verdicts in
TASK_RATED. Nothing is stored; θ is recomputed from the events every time, so every new rating counts at once.
"""

from collections.abc import Iterable
from dataclasses import dataclass

INTERIM_DECISION_ENGINE = 0.8  # a decision connector (Jev) before 5 ratings
INTERIM_FALLBACK_ENGINE = 1.0  # a text model's self-stated probability never acts alone before it is rated
FLOOR = 0.8  # holds from 5 to 19 ratings
MIN_RATED = 5
MIN_TASKS = 2  # ratings from one task alone never leave the interim threshold (owner, 2026-10-08)
FULL_HISTORY = 20
MIN_SUPPORT = 5  # rated decisions at or above a candidate θ
EPSILON = {"R0": 0.05, "R1": 0.02}  # tolerated error rate; R2 and R3 never act on a decision alone
GRID = [round(0.50 + step / 100, 2) for step in range(50)]  # 0.50 .. 0.99
GATE_EVENTS = ("GATE_PASSED", "GATE_FAILED")


@dataclass(frozen=True)
class RatedDecision:
    point: str  # "a1", "a4", "a5", "a7", "a10" or "acceptance"
    engine: str
    model: str
    confidence: float
    correct: bool
    task: str | None = None  # the task whose event holds the decision


def acts_alone(confidence: float, theta: float) -> bool:
    """θ = 1 means a decision never acts alone (fallback before rating, R2/R3, no qualifying θ): a self-stated
    confidence of 1.0 must not pass it."""
    return theta < 1.0 and confidence >= theta


def decision_point(event_type: str, question: str) -> str:
    """Gate questions "a1.2", "a10" belong to their rule; every acceptance criterion to "acceptance"."""
    return "acceptance" if event_type in GATE_EVENTS else question.split(".")[0]


def _records(events: list[dict]) -> dict[tuple[str, str], tuple[str, dict, str | None]]:
    records = {}
    for event in events:
        if event["type"] == "TOPOLOGY_DECIDED":
            for record in event["body"].get("decisions", []):
                records[(event["id"], record["question"])] = (decision_point(event["type"], record["question"]), record,
                                                              event.get("task"))
        elif event["type"] in GATE_EVENTS:
            for criterion in event["body"].get("criteria", []):
                record = criterion.get("decision")
                if record is not None:
                    records[(event["id"], record["question"])] = ("acceptance", record, event.get("task"))
    return records


def rated_decisions(events: Iterable[dict]) -> list[RatedDecision]:
    """Every decision record the operator rated; a later rating of the same record replaces an earlier one."""
    events = list(events)
    records = _records(events)
    verdicts = {}
    for event in events:
        if event["type"] == "TASK_RATED":
            for verdict in event["body"].get("decisions", []):
                verdicts[(verdict["event"], verdict["question"])] = verdict["verdict"]
    rated = []
    for key, verdict in verdicts.items():
        if key in records:
            point, record, task = records[key]
            rated.append(RatedDecision(point, record["engine"], record["model"], record["confidence"],
                                       verdict == "confirmed", task))
    return rated


def computed_threshold(rated: list[RatedDecision], epsilon: float) -> float:
    """The smallest θ on the grid with at least MIN_SUPPORT rated decisions at or above it and an error rate
    of at most ε among them; 1 when none qualifies."""
    for theta in GRID:
        above = [r for r in rated if r.confidence >= theta]
        if len(above) >= MIN_SUPPORT and sum(not r.correct for r in above) / len(above) <= epsilon:
            return theta
    return 1.0


def threshold(events: Iterable[dict], point: str, engine: str, model: str, risk_class: str = "R1",
              decision_engine: bool = True) -> float:
    """θ for one key. `decision_engine` is False for the text-model fallback (ADR 0011). Without a stated risk
    class the stricter R1 tolerance applies, as in the Gate."""
    if risk_class not in EPSILON:
        return 1.0
    rated = [r for r in rated_decisions(events) if (r.point, r.engine, r.model) == (point, engine, model)]
    if len(rated) < MIN_RATED or len({r.task for r in rated}) < MIN_TASKS:
        return INTERIM_DECISION_ENGINE if decision_engine else INTERIM_FALLBACK_ENGINE
    computed = computed_threshold(rated, EPSILON[risk_class])
    return computed if len(rated) >= FULL_HISTORY else max(FLOOR, computed)


RECEPTION_POINT = "reception"
QUICK_CANCEL_S = 120  # a task cancelled this soon after the reception started it was not what the person meant


def _utc(text: str):
    from datetime import datetime
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def quick_cancels(events: Iterable[dict]) -> set[str]:
    """Ids of the reception's task decisions whose task the operator cancelled within QUICK_CANCEL_S of its
    submission: the task was not what the person meant."""
    started, submitted, found = {}, {}, set()
    for event in events:
        body = event["body"]
        if (event["type"] == "RECEPTION_DECIDED" and body["decision"] in ("task", "continue_task")
                and body.get("task")):
            started[body["task"]] = event["id"]
        elif event["type"] == "TASK_SUBMITTED":
            submitted[event["task"]] = event["ts"]
        elif (event["type"] == "DECISION" and event["actor"]["kind"] == "hil" and event["task"] in started
              and body["decision"] == "cancel the task" and event["task"] in submitted
              and (_utc(event["ts"]) - _utc(submitted[event["task"]])).total_seconds() <= QUICK_CANCEL_S):
            found.add(started[event["task"]])
    return found


def reception_verdicts(events: Iterable[dict]) -> list[RatedDecision]:
    """The operator's verdicts on reception decisions, read from the conversation (plan 08a decision 3): Yes after
    a confirm confirms it and Differently corrects it; a task the reception started is corrected by a cancel within
    two minutes and confirmed by an accepted rating. `task` holds the conversation, so one conversation alone never
    leaves the interim threshold."""
    events = list(events)
    awaiting: dict[str, dict] = {}  # conversation -> the confirm waiting for its tap
    started: dict[str, dict] = {}  # task -> the decision that started it
    verdicts = {}
    for event in events:
        body = event["body"]
        if event["type"] == "RECEPTION_DECIDED" and "record" in body:
            if body["decision"] == "confirm":
                awaiting[body["conversation"]] = event
            elif body["decision"] in ("task", "continue_task") and body.get("task"):
                started[body["task"]] = event
        elif event["type"] == "CONVERSATION_MESSAGE" and body.get("tap") in ("yes", "differently"):
            confirm = awaiting.pop(body["conversation"], None)
            if confirm is not None:
                verdicts[confirm["id"]] = (confirm, body["tap"] == "yes")
        elif event["type"] == "TASK_RATED" and event["task"] in started and body["accepted"]:
            decision = started[event["task"]]
            verdicts.setdefault(decision["id"], (decision, True))
    recorded = {d["id"]: d for d in started.values()}  # only decisions with a record can be verdicts
    for decision_id in quick_cancels(events):
        if decision_id in recorded:
            verdicts[decision_id] = (recorded[decision_id], False)  # a quick cancel outweighs an accepted rating
    return [RatedDecision(RECEPTION_POINT, d["body"]["record"]["engine"], d["body"]["record"]["model"],
                          d["body"]["record"]["confidence"], correct, d["body"]["conversation"])
            for d, correct in verdicts.values()]


def reception_threshold(events: Iterable[dict], engine: str, model: str, interim: float) -> float:
    """θ of the reception's decisions for one engine and model version (plan 08a decision 2): `interim` until 5
    verdicts from at least 2 conversations, then at least `interim` until 20, then the computed θ at ε of R1."""
    rated = [r for r in reception_verdicts(events) if (r.engine, r.model) == (engine, model)]
    if len(rated) < MIN_RATED or len({r.task for r in rated}) < MIN_TASKS:
        return interim
    computed = computed_threshold(rated, EPSILON["R1"])
    return computed if len(rated) >= FULL_HISTORY else max(interim, computed)

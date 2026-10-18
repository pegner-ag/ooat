"""What OOAT learns from the ledger (plan 09): the learning price list of spec §11 and the What it learns figures.

Nothing is stored. Like θ (thresholds.py), every figure is recomputed from the events on each read, so the card in
the repository keeps `"observed": {"n": 0}` and `cost_card.observed` changes only through ooat-core (plan 09
decision 1).
"""

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass

from .catalog import load_card
from .pii import scan
from .thresholds import (RECEPTION_POINT, quick_cancels, rated_decisions, reception_threshold, reception_verdicts,
                         threshold)

EVENTS = ("TASK_SUBMITTED", "CONTRACT_ISSUED", "TASK_CLOSED", "TASK_RATED")
GENERAL = "general"  # the task type of a task submitted without one
PRIOR_WEIGHT = 5  # the card's prior counts as five observations (spec §11)
ABSTAINED = "CLOSED_ABSTAINED"
REPLACED = ("escalated", "retried")  # calls whose decision the next call replaced: the person never saw them
ATTENTION = 10  # tasks listed as needing a look


@dataclass(frozen=True)
class Observed:
    capability: str
    task_type: str
    n: int  # rated runs counted in p_accept
    accepted: int
    prior: float
    p_accept: float  # the Beta mean
    runs: int  # closed runs, rated or not
    p_abstain: float | None

    def as_dict(self) -> dict:
        return asdict(self) | {"p_silent": None}  # needs DEFECT_FOUND (spec §11), not recorded yet


def card_prior(capability: str) -> float:
    """The card's prior.p_accept; 0.5 when the card states none."""
    return load_card("capabilities", capability).get("cost_card", {}).get("prior", {}).get("p_accept", 0.5)


def _runs(events: Iterable[dict]) -> list[tuple[str, str, str, bool | None]]:
    """(capability, task type, closing state, accepted or None) of every closed task that ran a contract."""
    types, capability, closed, rated = {}, {}, {}, {}
    for event in events:
        task, body = event.get("task"), event["body"]
        if event["type"] == "TASK_SUBMITTED":
            types[task] = body.get("task_type") or GENERAL
        elif event["type"] == "CONTRACT_ISSUED":
            capability.setdefault(task, body["contract"]["capability"])
        elif event["type"] == "TASK_CLOSED":
            closed[task] = body["state"]
        elif event["type"] == "TASK_RATED":
            rated[task] = body["accepted"]
    return [(capability[t], types.get(t, GENERAL), state, rated.get(t)) for t, state in closed.items()
            if t in capability]


def _counted(state: str, accepted: bool | None) -> bool | None:
    """A success, a failure, or None when the run does not count (plan 09 decision 2): unrated, or an abstention the
    operator accepted as justified."""
    if accepted is None or (state == ABSTAINED and accepted):
        return None
    return accepted


def _beta_mean(successes: int, n: int, prior: float) -> float:
    return (prior * PRIOR_WEIGHT + successes) / (PRIOR_WEIGHT + n)


def p_accept(events: Iterable[dict], capability: str, task_type: str | None, prior: float) -> float:
    """The Beta mean of acceptance for one capability and task type."""
    wanted = task_type or GENERAL
    counted = [_counted(state, accepted) for cap, kind, state, accepted in _runs(events)
               if (cap, kind) == (capability, wanted)]
    counted = [c for c in counted if c is not None]
    return _beta_mean(sum(counted), len(counted), prior)


def observed(events: Iterable[dict], priors: dict[str, float]) -> list[Observed]:
    """One row per capability and task type that has closed runs, sorted by both."""
    groups: dict[tuple[str, str], list[tuple[str, bool | None]]] = {}
    for cap, kind, state, accepted in _runs(events):
        groups.setdefault((cap, kind), []).append((state, accepted))
    rows = []
    for (cap, kind), runs in sorted(groups.items()):
        counted = [c for c in (_counted(s, a) for s, a in runs) if c is not None]
        prior = priors.get(cap, 0.5)
        mean = _beta_mean(sum(counted), len(counted), prior)
        rows.append(Observed(cap, kind, len(counted), sum(counted), prior, mean, len(runs),
                             sum(s == ABSTAINED for s, _ in runs) / len(runs)))
    return rows



# What it learns (plan 09 decision 7) ------------------------------------------------------------------------------

def _thresholds(events: list[dict], reception_interim: float) -> list[dict]:
    rows: dict[tuple[str, str, str], list[bool]] = {}
    for rated in [*rated_decisions(events), *reception_verdicts(events)]:
        rows.setdefault((rated.point, rated.engine, rated.model), []).append(rated.correct)
    found = []
    for (point, engine, model), correct in sorted(rows.items()):
        theta = (reception_threshold(events, engine, model, reception_interim) if point == RECEPTION_POINT
                 else threshold(events, point, engine, model))
        found.append({"point": point, "engine": engine, "model": model, "rated": len(correct),
                      "confirmed": sum(correct), "theta": theta})
    return found


def _reception(events: list[dict]) -> tuple[list[dict], dict]:
    rows: dict[str, dict] = {}
    last: dict[str, dict] = {}  # conversation -> the row of its newest decision the person saw
    cancelled = quick_cancels(events)
    offered = 0
    taps = set()  # the remember taps; one counts as kept when its item was stored
    for event in events:
        body = event["body"]
        if event["type"] == "RECEPTION_DECIDED" and body["decision"] not in REPLACED:
            row = rows.setdefault(body["decision"], {"decision": body["decision"], "count": 0, "differently": 0,
                                                     "cancelled": 0})
            row["count"] += 1
            row["cancelled"] += event["id"] in cancelled
            last[body["conversation"]] = row
            offered += "lesson" in body
        elif event["type"] == "CONVERSATION_MESSAGE" and body.get("tap") in ("differently", "remember"):
            if body["tap"] == "differently" and body["conversation"] in last:
                last.pop(body["conversation"])["differently"] += 1
            if body["tap"] == "remember":
                taps.add(event["id"])
    kept = sum(1 for e in events if e["type"] == "MEMORY_NOTED" and e["body"].get("source") in taps)
    return (sorted(rows.values(), key=lambda r: (-r["count"], r["decision"])),
            {"lessons_offered": offered, "lessons_kept": kept})


def _memory(events: list[dict]) -> dict:
    """Notes the reception stored on its own, and how many of them the operator forgot later."""
    noted = {e["body"]["memory"] for e in events if e["type"] == "MEMORY_NOTED" and e["actor"]["kind"] == "system"}
    forgotten = {e["body"]["memory"] for e in events if e["type"] == "MEMORY_FORGOTTEN"} & noted
    return {"noted": len(noted), "forgotten": len(forgotten)}


def _plain(note: str | None) -> str | None:
    """A rating note is the operator's free text with no class of its own: shown only when it holds no personal
    data the scan recognises."""
    return note if note is None or not scan(note) else None


def _attention(events: list[dict], visible: Callable[[str], bool]) -> list[dict]:
    """The latest rejected tasks within the reader's cap, newest first; a justified abstention needs no look."""
    closed = {e["task"]: e["body"]["state"] for e in events if e["type"] == "TASK_CLOSED"}
    found = []
    for event in events:
        if event["type"] != "TASK_RATED" or event["body"]["accepted"] or not visible(event["task"]):
            continue
        state = closed.get(event["task"], "")
        found.append({"task": event["task"], "state": state,
                      "why": "lazy_abstention" if state == ABSTAINED else "rejected",
                      "note": _plain(event["body"].get("note"))})
    return found[-ATTENTION:][::-1]


def summary(events: list[dict], *, visible: Callable[[str], bool], reception_interim: float) -> dict:
    """The What it learns figures. Counts cover every task; task ids and rating notes only `visible` ones."""
    caps = {e["body"]["contract"]["capability"] for e in events if e["type"] == "CONTRACT_ISSUED"}
    reception, lessons = _reception(events)
    return {"price_list": [r.as_dict() for r in observed(events, {c: card_prior(c) for c in caps})],
            "thresholds": _thresholds(events, reception_interim), "reception": reception,
            "memory": _memory(events) | lessons, "attention": _attention(events, visible)}

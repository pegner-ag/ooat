"""What OOAT learns from the ledger (plan 09): the learning price list of spec §11 and the What it learns figures.

Nothing is stored. Like θ (thresholds.py), every figure is recomputed from the events on each read, so the card in
the repository keeps `"observed": {"n": 0}` and `cost_card.observed` changes only through ooat-core (plan 09
decision 1).
"""

from collections.abc import Iterable
from dataclasses import asdict, dataclass

from .catalog import load_card

EVENTS = ("TASK_SUBMITTED", "CONTRACT_ISSUED", "TASK_CLOSED", "TASK_RATED")
GENERAL = "general"  # the task type of a task submitted without one
PRIOR_WEIGHT = 5  # the card's prior counts as five observations (spec §11)
ABSTAINED = "CLOSED_ABSTAINED"


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

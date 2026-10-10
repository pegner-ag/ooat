"""Usage figures from the ledger (design 05 §8): what ran, what it used, what it cost, how long questions waited.

Pure projections over events, like state.py: nothing is stored. Calls, tokens and cost are grouped by role,
connector, tier or project; cost is split into metered (`exact`, `estimated`) and the subscription shadow value
(`shadow`). Until T3 and the catalog the roles are few: the worker's role, the Gate, the acceptance checks and the
critic. HIL time is waiting time from request to answer; the ledger does not know how long a person worked on it.
"""

from datetime import datetime, timedelta
from statistics import median

from .acceptance import GATE_CRITIC
from .gate import ACTOR as GATE_ACTOR

PERIODS = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "all": None}
GROUPS = ("role", "connector", "tier", "project")
OTHER = "(other)"  # projects the reader may not see by name, and tasks without a project
COST_PARTS = ("contracts_usd", "gate_usd", "orchestrator_usd", "critic_usd")  # TASK_CLOSED.cost in USD


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def role_of(event: dict) -> str:
    """Who spent: the worker's role id, the Gate, the critic, or the runtime's acceptance decisions."""
    actor = event["actor"]
    if actor["kind"] == "agent":
        return actor["role"].split("@", 1)[0]
    if actor == GATE_ACTOR:
        return "gate"
    return "critic" if event["body"].get("gate") == GATE_CRITIC else "acceptance"


def usage(events: list[dict], *, now: datetime, period: str = "7d", project: str | None = None,
          group: str = "role", above_cap: frozenset[str] = frozenset()) -> dict:
    """The Usage figures for events in the period. `above_cap` holds the tasks above the reader's data class:
    their costs count, but their project is named only when another task of it is within the cap."""
    if period not in PERIODS:
        raise ValueError(f"period is one of {', '.join(PERIODS)}")
    if group not in GROUPS:
        raise ValueError(f"group is one of {', '.join(GROUPS)}")
    days = PERIODS[period]
    since = now - timedelta(days=days) if days else None
    projects = {e["task"]: e["body"].get("project") for e in events if e["type"] == "TASK_SUBMITTED"}
    named = {p for task, p in projects.items() if p and task not in above_cap}
    selected = [e for e in events if (since is None or _utc(e["ts"]) >= since)
                and (project is None or projects.get(e["task"]) == project)]

    def key(event: dict) -> str:
        if group == "role":
            return role_of(event)
        if group in ("connector", "tier"):
            return event["cost"].get("adapter" if group == "connector" else "tier") or OTHER
        name = projects.get(event["task"])
        return name if name in named else OTHER

    groups: dict[str, dict] = {}
    for event in selected:
        cost = event.get("cost")
        if not cost:
            continue
        row = groups.setdefault(key(event), {"calls": 0, "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0,
                                             "metered_usd": 0.0, "shadow_usd": 0.0})
        row["calls"] += 1
        for tokens in ("tokens_in", "tokens_cached", "tokens_out"):
            row[tokens] += cost.get(tokens, 0)
        row["shadow_usd" if cost["basis"] == "shadow" else "metered_usd"] += cost.get("usd", 0.0)
    rows = sorted(({"key": k, **v} for k, v in groups.items()),
                  key=lambda r: (-(r["metered_usd"] + r["shadow_usd"]), r["key"]))
    return {"period": period, "project": project, "group": group,
            "spend": {"metered_usd": sum(r["metered_usd"] for r in rows),
                      "shadow_usd": sum(r["shadow_usd"] for r in rows)},
            "groups": rows, "tasks": _tasks(selected, events), "hil": _hil(selected, events)}


def _tasks(selected: list[dict], events: list[dict]) -> dict:
    """Tasks closed in the period: by outcome, accepted, cost per accepted task, the Gate's estimate vs actual."""
    closed = {e["task"]: e for e in selected if e["type"] == "TASK_CLOSED"}
    rated = {e["task"]: e["body"]["accepted"] for e in events if e["type"] == "TASK_RATED" and e["task"] in closed}
    by_state: dict[str, int] = {}
    for event in closed.values():
        by_state[event["body"]["state"]] = by_state.get(event["body"]["state"], 0) + 1
    actual = {task: sum(e["body"]["cost"][part] for part in COST_PARTS) for task, e in closed.items()}
    estimates = {}
    for event in events:
        if event["type"] == "TOPOLOGY_DECIDED" and event["task"] in closed:
            estimate = [c["model_usd"] for c in event["body"]["candidates"] if "model_usd" in c]
            if estimate:
                estimates[event["task"]] = estimate[0]  # the last decision stands
    accepted = sum(1 for ok in rated.values() if ok)
    estimated = sum(estimates.values())
    return {"closed": len(closed), "by_state": by_state, "rated": len(rated), "accepted": accepted,
            "cost_usd": sum(actual.values()),
            "cost_per_accepted_usd": sum(actual.values()) / accepted if accepted else None,
            "estimate_vs_actual": (sum(actual[t] for t in estimates) - estimated) / estimated if estimated else None}


def _hil(selected: list[dict], events: list[dict]) -> dict:
    """Questions asked in the period, answers, defaults applied on silence, median wait for a human answer."""
    asked = {e["id"]: e for e in selected if e["type"] == "HIL_REQUEST"}
    responses = [e for e in events if e["type"] == "HIL_RESPONSE" and e["body"]["request"] in asked]
    defaults = [r for r in responses if r["body"].get("default_applied")]
    waits = [(_utc(r["ts"]) - _utc(asked[r["body"]["request"]]["ts"])).total_seconds() / 60
             for r in responses if not r["body"].get("default_applied")]
    return {"questions": len(asked), "answered": len(responses) - len(defaults), "defaults_applied": len(defaults),
            "median_wait_minutes": median(waits) if waits else None}

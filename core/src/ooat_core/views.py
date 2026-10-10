"""What a reader of the API sees (design 05 §5, §6): tasks, timelines, questions and the rating queue, with the
reader's data-class cap applied. Pure projections over events, like state.py.

A token caps every read, not only what it submits (ADR 0016): content of a task or artifact above the cap comes back
as a stub, while ids, states, costs and deadlines stay visible. A task's class is the class it runs under: the
declared one, raised by the pre-scan and the Gate's A10, and by its attachments. An artifact has its own class.
A web session on loopback has no cap (`cap=None`).
"""

from collections.abc import Callable

from .gate import GateSettings, gated_data_class
from .pii import ORDER, higher_class
from .rating import task_decisions
from .runtime import CLOSED
from .state import task_state

STUB_TEXT = "above this token's data class; open in the web app"


def within(data_class: str, cap: str | None) -> bool:
    return cap is None or ORDER.index(data_class) <= ORDER.index(cap)


def stub(task: str) -> dict:
    return {"redacted": STUB_TEXT, "link": f"/tasks/{task}"}


def by_task(events: list[dict]) -> dict[str, list[dict]]:
    """Events of every task, in submission order."""
    tasks: dict[str, list[dict]] = {}
    for event in events:
        if event["task"] is not None:
            tasks.setdefault(event["task"], []).append(event)
    return tasks


def task_class(events: list[dict], artifact_class: Callable[[str], str],
               settings: GateSettings = GateSettings()) -> str:
    """The class the task runs under: gated (declared, pre-scan, A10), raised by its attachments."""
    submitted = next(e for e in events if e["type"] == "TASK_SUBMITTED")
    data_class = gated_data_class(events, settings)
    for ref in submitted["refs"]:
        data_class = higher_class(data_class, artifact_class(ref))
    return data_class


def _latest(events: list[dict], kind: str) -> dict | None:
    return next((e for e in reversed(events) if e["type"] == kind), None)


def task_summary(task: str, events: list[dict], data_class: str, cap: str | None) -> dict:
    submitted = next(e for e in events if e["type"] == "TASK_SUBMITTED")
    decided, closed = _latest(events, "TOPOLOGY_DECIDED"), _latest(events, "TASK_CLOSED")
    visible = within(data_class, cap)
    estimates = [c["model_usd"] for c in decided["body"]["candidates"] if "model_usd" in c] if decided else []
    return {
        "task": task, "state": task_state(events), "data_class": data_class,
        "project": submitted["body"].get("project") if visible else None,
        "goal": submitted["body"]["goal"] if visible else stub(task),
        "topology": decided["body"]["topology"] if decided else None,
        "cost_usd": sum(e.get("cost", {}).get("usd", 0.0) for e in events),
        "budget_usd": submitted["body"].get("budget_usd"),
        "estimate_usd": estimates[0] if estimates else None,
        "submitted": submitted["ts"], "updated": events[-1]["ts"],
        "closed": closed["body"]["state"] if closed else None,
    }


def task_detail(task: str, events: list[dict], data_class: str, cap: str | None,
                artifact_record: Callable[[str], dict], open_requests: list[dict]) -> dict:
    visible = within(data_class, cap)
    submitted, closed = next(e for e in events if e["type"] == "TASK_SUBMITTED"), _latest(events, "TASK_CLOSED")
    refs = list(dict.fromkeys(ref for e in events for ref in e["refs"] if ref.startswith("art_")))
    artifacts = []
    for ref in refs:
        record = artifact_record(ref)
        artifacts.append({"ref": ref, "type": record["type"], "data_class": record["data_class"],
                          "untrusted": record["untrusted"], "readable": within(record["data_class"], cap)})
    detail = task_summary(task, events, data_class, cap)
    detail |= {
        "expected_output": submitted["body"].get("expected_output") if visible else None,
        "acceptance": submitted["body"].get("acceptance", []) if visible else stub(task),
        "result": None, "artifacts": artifacts,
        "questions": [hil_view(r, data_class, cap) for r in open_requests if r["task"] == task],
    }
    if closed is not None:
        body = closed["body"]
        detail["result"] = {"state": body["state"], "cost": body["cost"], "artifacts": body.get("artifacts", []),
                            "summary": body["summary"] if visible else stub(task),
                            "missing": body.get("missing") if visible else None}
    return detail


def timeline(events: list[dict], data_class: str, cap: str | None, after: str | None = None) -> list[dict]:
    """The task's events after the event `after` (a cursor), bodies stubbed above the cap."""
    if after is not None:
        ids = [e["id"] for e in events]
        if after not in ids:
            raise KeyError(after)
        events = events[ids.index(after) + 1:]
    visible = within(data_class, cap)
    return [{"id": e["id"], "ts": e["ts"], "type": e["type"], "actor": {"kind": e["actor"]["kind"],
                                                                        "id": e["actor"]["id"]},
             "refs": e["refs"], "cost": e.get("cost"), "body": e["body"] if visible else stub(e["task"])}
            for e in events]


def hil_view(request: dict, data_class: str, cap: str | None) -> dict:
    body, visible, task = request["body"], within(data_class, cap), request["task"]
    return {"request": request["id"], "task": task, "asked": request["ts"], "deadline": body["deadline"],
            "risk_class": body.get("risk_class"), "blocking": body["blocking"],
            "recommended": body["recommended"], "default_on_silence": body["default_on_silence"],
            "question": body["question"] if visible else stub(task),
            "options": [{"id": o["id"], "cost_usd": o["cost_usd"], "acts": o.get("acts", True),
                         "label": o["label"] if visible else stub(task)} for o in body["options"]]}


def rating_queue(tasks: dict[str, list[dict]], classes: dict[str, str], cap: str | None) -> list[dict]:
    """Closed tasks without a rating, with the decisions OOAT made alone."""
    queue = []
    for task, events in tasks.items():
        if task_state(events) not in CLOSED or any(e["type"] == "TASK_RATED" for e in events):
            continue
        entry = task_summary(task, events, classes[task], cap)
        entry["decisions"] = [{"event": d.event, "question": d.question, "kind": d.kind, "answer": d.answer,
                               "confidence": d.confidence, "disputed": d.disputed} for d in task_decisions(events)]
        queue.append(entry)
    return queue

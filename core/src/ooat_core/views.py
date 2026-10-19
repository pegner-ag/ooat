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
from .rating import CHOICE_OPTIONS, task_decisions
from .runner import last_failure, resume_after
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
    paused = resume_after(events) if task_state(events) not in CLOSED else None  # the inbox's "stuck" list
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
        "resume_after": paused.isoformat().replace("+00:00", "Z") if paused else None,
        "paused_by": last_failure(events) if paused and visible else None,
    }


def workspace_view(events: list[dict], visible: bool) -> dict | None:
    """What a task on a project's folders did there, for the web app and the chat bridge (design 07 §7). Above the
    reader's class every task gets the stub, so the reader cannot even tell whether it worked on files; otherwise
    None for a text-only task."""
    submitted = next(e for e in events if e["type"] == "TASK_SUBMITTED")
    if not visible:
        return stub(submitted["task"])
    workspace = submitted["body"].get("workspace")
    if workspace is None:
        return None
    used = [e["body"] for e in events if e["type"] == "WORKSPACE_USED" and e["body"]["by"] == "worker"]
    files: dict[str, dict] = {}
    for body in used:
        for item in body["created"]:
            entry = files.setdefault(item["path"], {"path": item["path"], "kind": "created", "added": 0, "removed": 0})
            entry["added"] += item["added"]
        for item in body["changed"]:
            entry = files.setdefault(item["path"], {"path": item["path"], "kind": "changed", "added": 0, "removed": 0})
            entry["added"], entry["removed"] = entry["added"] + item["added"], entry["removed"] + item["removed"]
    diffs = [body["diff"] for body in used if body.get("diff")]
    reverted = _latest(events, "WORKSPACE_REVERTED")
    return {"write": workspace["write"], "folders": workspace["folders"], "files": list(files.values()),
            "refused": sum(len(body["refused"]) for body in used),
            "limit": any(body["limit"] is not None for body in used), "diff": diffs[-1] if diffs else None,
            "reverted": None if reverted is None else {
                "restored": [i["path"] for i in reverted["body"]["restored"]],
                "skipped": reverted["body"]["skipped"], "kept": reverted["body"]["kept"],
                "by": reverted["actor"]["id"], "ts": reverted["ts"]},
            "revertable": task_state(events) in CLOSED and bool(files) and reverted is None}


def task_detail(task: str, events: list[dict], data_class: str, cap: str | None,
                artifact_record: Callable[[str], dict], open_requests: list[dict]) -> dict:
    visible = within(data_class, cap)
    submitted, closed = next(e for e in events if e["type"] == "TASK_SUBMITTED"), _latest(events, "TASK_CLOSED")
    refs = list(dict.fromkeys(ref for e in events for ref in e["refs"] if ref.startswith("art_")))
    names = dict(zip(submitted["refs"], submitted["body"].get("attachment_names", []))) if visible else {}
    artifacts = []
    for ref in refs:
        record = artifact_record(ref)
        artifacts.append({"ref": ref, "type": record["type"], "data_class": record["data_class"],
                          "untrusted": record["untrusted"], "readable": within(record["data_class"], cap),
                          "name": names.get(ref)})
    detail = task_summary(task, events, data_class, cap)
    detail |= {
        "expected_output": submitted["body"].get("expected_output") if visible else None,
        "acceptance": submitted["body"].get("acceptance", []) if visible else stub(task),
        "result": None, "artifacts": artifacts,
        "questions": [hil_view(r, data_class, cap) for r in open_requests if r["task"] == task],
        "workspace": workspace_view(events, visible),
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
                               "confidence": d.confidence, "disputed": d.disputed,
                               "options": sorted(CHOICE_OPTIONS[d.question])
                               if isinstance(d.answer, str) and d.question in CHOICE_OPTIONS else None}
                              for d in task_decisions(events)]
        queue.append(entry)
    return queue


# Conversations and memory (ADR 0018) ------------------------------------------------------------------------------

_SAID = ("text", "tap_text", "reply", "interpretation", "options", "pending", "attachment_names", "lesson")


def conversation_stub(conversation: str) -> dict:
    return {"redacted": STUB_TEXT, "link": f"/conversations/{conversation}"}


def conversation_event(event: dict, cap: str | None) -> dict:
    """A conversation event for a reader: what was said is stubbed above the reader's cap; ids, decisions, buttons,
    tasks and costs stay visible."""
    body = dict(event["body"])
    if not within(body.get("data_class", "internal"), cap):
        stub_body = conversation_stub(body["conversation"])
        for key in _SAID:
            if key in body:
                body[key] = stub_body
    return {"id": event["id"], "ts": event["ts"], "type": event["type"],
            "actor": {"kind": event["actor"]["kind"], "id": event["actor"]["id"]}, "refs": event["refs"],
            "cost": event.get("cost"), "body": body}


def conversation_view(conversation, own: list[dict], tasks: list[str], cap: str | None) -> dict:
    return {"conversation": conversation.id, "project": conversation.project, "channel": conversation.channel,
            "operator": conversation.operator, "started": conversation.started,
            "last_message": conversation.last_message, "closed": conversation.closed, "tasks": tasks,
            "events": [conversation_event(e, cap) for e in own]}


def memory_view(item) -> dict:
    """A memory item the reader may see (the caller has applied the cap)."""
    return {"memory": item.id, "scope": item.scope, "kind": item.kind, "data_class": item.data_class,
            "text": item.text, "pinned": item.pinned, "done": item.done, "noted": item.noted, "source": item.source,
            "conversation": item.conversation}

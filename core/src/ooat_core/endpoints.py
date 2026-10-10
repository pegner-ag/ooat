"""The resources of the REST API (design 05 §5): tasks, timelines, artifacts, questions, ratings, connectors, usage.

Handlers call the same functions as the CLI (`Runtime.submit`, `Runtime.cancel`, `hil.answer`, `rate`,
`connector_admin.*`) with the operator and the channel of the principal, never a name from the request body; they
build no actor themselves. Every read applies the reader's data-class cap through views.py, and a write on content
above it is refused with DATA_CLASS_ABOVE_TOKEN. Whatever changes a task queues it for the runner.
"""

import base64
import binascii
import difflib
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from . import connector_admin, hil, stats, views
from .api import ApiError, Principal, Server, principal, require_within, scope, server_of
from .gate import settings_from_config
from .ids import parse_artifact_ref
from .rating import rate
from .runtime import CLOSED
from .state import task_state

INTAKE_KEY = re.compile(r"^[!-~]{1,128}$")  # printable ASCII without spaces, as the schema's intake_key
SSE_POLL_S, SSE_MAX_S = 1.0, 900.0  # a stream ends after 15 minutes; the client reconnects with Last-Event-ID
DataClass = Literal["public", "internal", "client_confidential", "personal", "special_category"]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttachmentIn(_Body):
    name: str = Field(min_length=1, max_length=255)
    content_base64: str


class TaskIn(_Body):
    project: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=64)
    goal: str = Field(min_length=1, max_length=20000)
    expected_output: str | None = Field(default=None, min_length=1, max_length=5000)
    acceptance: list[str] = Field(default=[], max_length=20)
    value: Literal["A", "B", "C"] | None = None
    value_usd: float | None = Field(default=None, ge=0)
    budget_usd: float | None = Field(default=None, gt=0)
    data_class: DataClass = "internal"
    attachments: list[AttachmentIn] = Field(default=[], max_length=20)


class AnswerIn(_Body):
    choice: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")
    text: str | None = Field(default=None, max_length=20000)


class VerdictIn(_Body):
    event: str
    question: str
    verdict: Literal["confirmed", "corrected"]
    value: StrictInt | StrictStr | None = None


class RatingIn(_Body):
    accepted: bool
    value_class: Literal["A", "B", "C"]
    note: str | None = Field(default=None, max_length=5000)
    decisions: list[VerdictIn] = []


class ResponsibilityIn(_Body):
    processing_regions: list[str] | None = None
    no_training: Literal[True] | None = None


class EnableIn(_Body):
    classes: list[DataClass] = Field(min_length=1)
    automation: bool
    confirm: str  # the connector id, typed again (spec §9 rule 1)
    responsibility: ResponsibilityIn | None = None  # stated for client_confidential or personal (ADR 0012)


class DisableIn(_Body):
    reason: str = Field(min_length=1, max_length=500)


class HookIn(_Body):
    path: str
    sha256: str


class HooksIn(_Body):
    confirm: str
    hooks: list[HookIn]  # exactly as GET .../hooks listed them: the operator approves what they saw


def task_classes(server: Server, tasks: dict[str, list[dict]]) -> dict[str, str]:
    ledger, settings = server.runtime().ledger, settings_from_config(server.config)
    return {task: views.task_class(events, lambda ref: ledger.artifact(ref)["data_class"], settings)
            for task, events in tasks.items()}


def submitted_tasks(server: Server) -> dict[str, list[dict]]:
    tasks = views.by_task(server.runtime().ledger.events())
    return {t: e for t, e in tasks.items() if any(x["type"] == "TASK_SUBMITTED" for x in e)}


def one_task(server: Server, task: str) -> tuple[list[dict], str]:
    """The task's events and class; 404 when there is no such task."""
    events = server.runtime().ledger.events(task=task)
    if not any(e["type"] == "TASK_SUBMITTED" for e in events):
        raise ApiError(404, "NOT_FOUND", f"no task {task}")
    return events, task_classes(server, {task: events})[task]


def resource_routes() -> APIRouter:
    api = APIRouter()

    # Tasks -----------------------------------------------------------------------------------------------------

    @api.post("/tasks", status_code=202)
    def submit(body: TaskIn, request: Request, who: Principal = Depends(scope("submit")),
               idempotency_key: str | None = Header(default=None)) -> dict:
        require_within(who, body.data_class)
        if idempotency_key is not None and not INTAKE_KEY.match(idempotency_key):
            raise ApiError(400, "INVALID", "Idempotency-Key is 1 to 128 printable ASCII characters without spaces")
        if body.value is not None and body.value_usd is not None:
            raise ApiError(400, "INVALID", "give value or value_usd, not both")
        try:
            contents = [base64.b64decode(a.content_base64, validate=True) for a in body.attachments]
        except (binascii.Error, ValueError):
            raise ApiError(400, "INVALID", "an attachment's content_base64 is not base64") from None
        server = server_of(request)
        runtime = server.runtime()
        value = {"class": body.value} if body.value else {"usd": body.value_usd} if body.value_usd is not None else None
        task = runtime.submit(operator=who.operator, goal=body.goal, acceptance=body.acceptance, project=body.project,
                              expected_output=body.expected_output, value=value, budget_usd=body.budget_usd,
                              data_class=body.data_class, files=contents,
                              file_names=[a.name for a in body.attachments], channel=who.channel,
                              intake_key=idempotency_key)
        server.runner.enqueue(task)
        return {"task": task, "state": task_state(runtime.ledger.events(task=task))}

    @api.get("/tasks")
    def list_tasks(request: Request, state: str | None = None, project: str | None = None, after: str | None = None,
                   limit: int = 50, who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        tasks = submitted_tasks(server)
        classes = task_classes(server, tasks)
        found = []
        for task in sorted(tasks, reverse=True):  # ULIDs sort by creation: newest first; `after` pages on
            if after is not None and task >= after:
                continue
            summary = views.task_summary(task, tasks[task], classes[task], who.max_data_class)
            if (state is None or summary["state"] == state) and (project is None or summary["project"] == project):
                found.append(summary)
        limit = max(1, min(limit, 200))
        return {"tasks": found[:limit], "next": found[limit - 1]["task"] if len(found) > limit else None}

    @api.get("/tasks/{task}")
    def show_task(task: str, request: Request, who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        events, data_class = one_task(server, task)
        return views.task_detail(task, events, data_class, who.max_data_class, server.runtime().ledger.artifact,
                                 hil.open_requests(server.runtime().ledger))

    @api.get("/tasks/{task}/events", response_model=None)
    def task_events(task: str, request: Request, after: str | None = None, who: Principal = Depends(scope("read")),
                    last_event_id: str | None = Header(default=None)) -> dict | StreamingResponse:
        server = server_of(request)
        events, data_class = one_task(server, task)
        cursor = last_event_id or after
        try:
            found = views.timeline(events, data_class, who.max_data_class, cursor)
        except KeyError:
            raise ApiError(400, "INVALID", f"{cursor} is not an event of {task}") from None
        if "text/event-stream" not in request.headers.get("accept", ""):
            return {"events": found, "next": found[-1]["id"] if found else cursor}
        return StreamingResponse(_stream(server, task, cursor, lambda: scope("read")(principal(request))),
                                 media_type="text/event-stream")

    @api.post("/tasks/{task}/cancel", status_code=202)
    def cancel(task: str, request: Request, who: Principal = Depends(scope("submit"))) -> dict:
        server = server_of(request)
        require_within(who, one_task(server, task)[1])
        asked = server.runtime().cancel(task, operator=who.operator, channel=who.channel)
        server.runner.enqueue(task)
        return {"task": task, "cancel": "requested" if asked else "already requested"}

    # Artifacts -------------------------------------------------------------------------------------------------

    def readable(server: Server, ref: str, who: Principal) -> tuple[dict, bytes | None]:
        """The artifact's record, and its content when it is within the reader's cap (else None)."""
        parse_artifact_ref(ref)  # 400 on a malformed reference
        record = server.runtime().ledger.artifact(ref)
        if record is None:
            raise ApiError(404, "NOT_FOUND", f"no artifact {ref}")
        if not views.within(record["data_class"], who.max_data_class):
            return record, None
        return record, server.runtime().artifacts.read(ref)

    def producing_task(server: Server, record: dict) -> str:
        """Attachments come with TASK_SUBMITTED, documents with RESULT; 404 for an artifact of any other event."""
        task = next((e["task"] for e in server.runtime().ledger.events(types=["TASK_SUBMITTED", "RESULT"])
                     if e["id"] == record["produced_by_event"]), None)
        if task is None:
            raise ApiError(404, "NOT_FOUND", "no task produced this artifact")
        return task

    @api.get("/artifacts/{ref}", response_model=None)
    def artifact(ref: str, request: Request, who: Principal = Depends(scope("read"))) -> Response:
        server = server_of(request)
        record, content = readable(server, ref, who)
        if content is None:
            return JSONResponse(views.stub(producing_task(server, record)))
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return Response(content, media_type="application/octet-stream",
                            headers={"Content-Disposition": f'attachment; filename="{ref}"'})
        return Response(content, media_type="text/plain; charset=utf-8")  # never text/html: untrusted content

    @api.get("/artifacts/{ref}/diff", response_model=None)
    def diff(ref: str, against: str, request: Request, who: Principal = Depends(scope("read"))) -> Response:
        """A unified diff of two text artifacts of one task, e.g. the documents of two attempts."""
        server = server_of(request)
        (old, before), (new, now) = readable(server, against, who), readable(server, ref, who)
        task = producing_task(server, new)
        if producing_task(server, old) != task:
            raise ApiError(400, "INVALID", "a diff compares two artifacts of one task")
        if before is None or now is None:
            return JSONResponse(views.stub(task))
        try:
            lines = difflib.unified_diff(before.decode("utf-8").splitlines(keepends=True),
                                         now.decode("utf-8").splitlines(keepends=True), fromfile=against, tofile=ref)
        except UnicodeDecodeError:
            raise ApiError(400, "INVALID", "only text artifacts have a diff") from None
        return Response("".join(lines), media_type="text/plain; charset=utf-8")

    # Questions and ratings -------------------------------------------------------------------------------------

    @api.get("/hil")
    def questions(request: Request, who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        found = hil.open_requests(server.runtime().ledger)
        tasks = views.by_task(server.runtime().ledger.events())
        classes = task_classes(server, {r["task"]: tasks[r["task"]] for r in found})
        return {"requests": [views.hil_view(r, classes[r["task"]], who.max_data_class) for r in found]}

    @api.post("/hil/{request_id}/answer", status_code=202)
    def answer(request_id: str, body: AnswerIn, request: Request, who: Principal = Depends(scope("answer"))) -> dict:
        server = server_of(request)
        found = hil.find_request(server.runtime().ledger, request_id)
        if found is None:
            raise ApiError(404, "NOT_FOUND", f"no question {request_id}")
        require_within(who, one_task(server, found["task"])[1])
        response = hil.answer(server.runtime().ledger, server.runtime(), request_id, operator=who.operator,
                              choice=body.choice, text=body.text, channel=who.channel)
        server.runner.enqueue(response["task"])
        return {"task": response["task"], "response": response["id"]}

    @api.get("/ratings/queue")
    def rating_queue(request: Request, who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        closed = {t: e for t, e in submitted_tasks(server).items() if task_state(e) in CLOSED}
        return {"tasks": views.rating_queue(closed, task_classes(server, closed), who.max_data_class)}

    @api.post("/tasks/{task}/rating", status_code=201)
    def rate_task(task: str, body: RatingIn, request: Request, who: Principal = Depends(scope("rate"))) -> dict:
        server = server_of(request)
        require_within(who, one_task(server, task)[1])
        verdicts = {}
        for decision in body.decisions:
            if decision.verdict == "corrected" and decision.value is None:
                raise ApiError(400, "INVALID", f"{decision.question}: a correction needs its value")
            verdicts[(decision.event, decision.question)] = \
                "confirmed" if decision.verdict == "confirmed" else decision.value
        event = rate(server.runtime().ledger, task, operator=who.operator, accepted=body.accepted,
                     value_class=body.value_class, verdicts=verdicts, note=body.note, channel=who.channel)
        return {"task": task, "rating": event["id"], "decisions": len(event["body"]["decisions"])}

    # Connectors ------------------------------------------------------------------------------------------------

    def installed(server: Server, connector_id: str):
        found = server.registry.get(connector_id)
        if found is None:
            raise ApiError(404, "NOT_FOUND", f"{connector_id} is not installed")
        return found

    @api.get("/connectors")
    def connectors(request: Request, who: Principal = Depends(scope("connectors"))) -> dict:
        server = server_of(request)
        statuses = connector_admin.connector_statuses(server.registry, server.runtime().ledger,
                                                      server.clock().date(), server.config)
        return {"connectors": [asdict(s) for s in statuses]}

    @api.get("/connectors/{connector_id}/card")
    def card(connector_id: str, request: Request, who: Principal = Depends(scope("connectors"))) -> dict:
        server = server_of(request)
        manifest = installed(server, connector_id).manifest
        return {"connector": connector_id,
                "card": connector_admin.consequences_card(manifest, server.clock().date(), server.config)}

    @api.post("/connectors/{connector_id}/enable", status_code=201)
    def enable(connector_id: str, body: EnableIn, request: Request,
               who: Principal = Depends(scope("connectors"))) -> dict:
        server = server_of(request)
        connector = installed(server, connector_id)
        if body.confirm != connector_id:
            raise ApiError(400, "INVALID", "type the connector id to confirm")
        for data_class in body.classes:
            require_within(who, data_class)
        responsibility = body.responsibility.model_dump(exclude_none=True) if body.responsibility else None
        event = connector_admin.acknowledge(server.runtime().ledger, connector, who.operator, body.classes,
                                            body.automation, responsibility, server.clock().date(),
                                            channel=who.channel)
        return {"connector": connector_id, "event": event["id"]}

    @api.post("/connectors/{connector_id}/disable", status_code=201)
    def disable(connector_id: str, body: DisableIn, request: Request,
                who: Principal = Depends(scope("connectors"))) -> dict:
        event = connector_admin.disable(server_of(request).runtime().ledger, connector_id, who.operator, body.reason,
                                        channel=who.channel)
        return {"connector": connector_id, "event": event["id"]}

    @api.get("/connectors/{connector_id}/hooks")
    def hooks(connector_id: str, request: Request, who: Principal = Depends(scope("connectors"))) -> dict:
        connector = installed(server_of(request), connector_id)
        listed = connector.hooks() if hasattr(connector, "hooks") else []
        return {"hooks": [{"path": path, "sha256": sha, "text": text} for path, sha, text in listed]}

    @api.post("/connectors/{connector_id}/approve-hooks", status_code=201)
    def approve_hooks(connector_id: str, body: HooksIn, request: Request,
                      who: Principal = Depends(scope("connectors"))) -> dict:
        # Approving a hook approves code that runs on this machine (ADR 0015): the CLI or a web session, never a token.
        if who.channel != "web":
            raise ApiError(403, "SCOPE", "hooks are approved in the web app or with `ooat connectors approve-hooks`, "
                                         "never with an API token")
        server = server_of(request)
        connector = installed(server, connector_id)
        if body.confirm != connector_id:
            raise ApiError(400, "INVALID", "type the connector id to confirm")
        current =[(path, sha) for path, sha, _ in (connector.hooks() if hasattr(connector, "hooks") else [])]
        if not current or any(not sha for _, sha in current):
            raise ApiError(400, "INVALID", "there are no hooks that can be approved")
        if [(h.path, h.sha256) for h in body.hooks] != current:
            raise ApiError(409, "HOOKS_CHANGED", "the hooks changed since they were listed; review them again")
        event = connector_admin.approve_hooks(server.runtime().ledger, connector, who.operator, current,
                                              channel=who.channel)
        return {"connector": connector_id, "event": event["id"]}

    # Usage -----------------------------------------------------------------------------------------------------

    @api.get("/stats")
    def usage(request: Request, period: str = "7d", project: str | None = None, group: str = "role",
              who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        tasks = submitted_tasks(server)
        above = frozenset(t for t, c in task_classes(server, tasks).items() if not views.within(c, who.max_data_class))
        events = server.runtime().ledger.events()
        if project is not None and not any(e[0]["body"].get("project") == project for t, e in tasks.items()
                                           if t not in above):
            events = []  # a project only above the cap reads like an unknown one: no spend, no sign it exists
        return stats.usage(events, now=server.clock(), period=period, project=project, group=group, above_cap=above)

    return api


def _stream(server: Server, task: str, cursor: str | None, recheck: Callable[[], Principal]):
    """Server-Sent Events: the timeline after the cursor, then each new event, until the task is closed. Each step
    reads the ledger through the thread it runs on (Starlette iterates a sync generator in its thread pool).

    Every poll authenticates the reader again (session still open, token not revoked or expired, `read` scope) and
    applies its cap afresh, so a revoked token's stream ends at the next poll with an UNAUTHENTICATED event."""
    started = time.monotonic()
    while True:
        try:
            who = recheck()
        except ApiError as error:
            body = {"error": {"code": "UNAUTHENTICATED", "message": error.message, "details": None}}
            yield f"event: UNAUTHENTICATED\ndata: {json.dumps(body)}\n\n"
            return
        events, data_class = one_task(server, task)
        for event in views.timeline(events, data_class, who.max_data_class, cursor):
            yield f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            cursor = event["id"]
        if task_state(events) in CLOSED or time.monotonic() - started > SSE_MAX_S:
            return
        time.sleep(SSE_POLL_S)

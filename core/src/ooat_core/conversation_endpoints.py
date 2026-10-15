"""Conversations and memory in the REST API (design 08 §8, ADR 0018; plan 08a task 9).

A message is recorded at once and decided by the desk after its quiet window; the decision comes on the
conversation's events, as a task's progress does. A tap is decided at once. Handlers call `Reception` and the memory
module with the operator and channel of the principal, never a name from the body. A conversation is the operator's
own: another operator's reads like an unknown one. Every read applies the reader's cap (views.conversation_event);
a write on a project or an item above the cap is refused.
"""

import base64
import binascii
import json
import re
import time

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from . import conversations, memory, views
from .api import ApiError, Principal, Server, principal, require_within, scope, server_of
from .endpoints import AttachmentIn

INTAKE_KEY = re.compile(r"^[!-~]{1,128}$")
SSE_POLL_S, SSE_MAX_S = 1.0, 900.0
CONVERSATION = r"^cnv_[0-7][0-9A-HJKMNP-TV-Z]{25}$"
MEMORY = r"^mem_[0-7][0-9A-HJKMNP-TV-Z]{25}$"
TAP = r"^(yes|differently|new_thing|make_task|todo|forget:mem_[0-7][0-9A-HJKMNP-TV-Z]{25}|done:mem_[0-7][0-9A-HJKMNP-TV-Z]{25})$"


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MessageIn(_Body):
    project: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=64)
    text: str = Field(min_length=1, max_length=20000)
    conversation: str | None = Field(default=None, pattern=CONVERSATION)
    reply_to: str | None = Field(default=None, pattern=r"^evt_[0-7][0-9A-HJKMNP-TV-Z]{25}$")
    attachments: list[AttachmentIn] = Field(default=[], max_length=20)


class TapIn(_Body):
    tap: str = Field(pattern=TAP)
    text: str | None = Field(default=None, max_length=20000)


class MemoryEditIn(_Body):
    text: str | None = Field(default=None, min_length=1, max_length=memory.MAX_TEXT)
    pinned: bool | None = None
    done: bool | None = None


def project_class(server: Server, project: str) -> str:
    mapped = server.config.projects.get(project)
    return mapped.data_class if mapped is not None else "internal"


def own_conversation(server: Server, who: Principal, conversation: str):
    """The principal's conversation and its events; 404 for an unknown one or another operator's."""
    events = server.runtime().ledger.events()
    found = conversations.conversations(events).get(conversation)
    if found is None or found.operator != who.operator:
        raise ApiError(404, "NOT_FOUND", f"no conversation {conversation}")
    return found, events


def own_item(server: Server, who: Principal, scope_name: str, mem_id: str) -> dict:
    """The item's MEMORY_NOTED, when it is in this scope and within the reader's cap."""
    events = server.runtime().ledger.events(types=memory.EVENTS)
    noted = memory.find(events, mem_id)
    if noted is None or noted["body"]["scope"] != scope_name:
        raise ApiError(404, "NOT_FOUND", f"no memory item {mem_id} in {scope_name}")
    require_within(who, memory.item_class(events, mem_id))
    return noted


def conversation_routes() -> APIRouter:
    api = APIRouter()

    @api.post("/conversations/messages", status_code=202)
    def send(body: MessageIn, request: Request, who: Principal = Depends(scope("submit")),
             idempotency_key: str | None = Header(default=None)) -> dict:
        server = server_of(request)
        require_within(who, project_class(server, body.project))
        if idempotency_key is not None and not INTAKE_KEY.match(idempotency_key):
            raise ApiError(400, "INVALID", "Idempotency-Key is 1 to 128 printable ASCII characters without spaces")
        try:
            contents = [base64.b64decode(a.content_base64, validate=True) for a in body.attachments]
        except (binascii.Error, ValueError):
            raise ApiError(400, "INVALID", "an attachment's content_base64 is not base64") from None
        message = server.reception().receive(operator=who.operator, project=body.project, channel=who.channel,
                                             text=body.text, conversation=body.conversation, reply_to=body.reply_to,
                                             files=contents, file_names=[a.name for a in body.attachments],
                                             intake_key=idempotency_key)
        conversation = message["body"]["conversation"]
        server.desk.enqueue(conversation)
        return {"conversation": conversation, "message": message["id"]}

    @api.post("/conversations/{conversation}/taps")
    def tap(conversation: str, body: TapIn, request: Request, who: Principal = Depends(scope("answer"))) -> dict:
        server = server_of(request)
        found, _ = own_conversation(server, who, conversation)
        require_within(who, project_class(server, found.project))
        if body.tap.startswith(("forget:", "done:")):
            mem_id = body.tap.split(":", 1)[1]
            events = server.runtime().ledger.events(types=memory.EVENTS)
            data_class = memory.item_class(events, mem_id)
            if data_class is not None:
                require_within(who, data_class)
        result = server.reception().tap(conversation, body.tap, operator=who.operator, channel=who.channel,
                                        text=body.text)
        if result["decision"] is None:
            server.desk.enqueue(conversation)
        return {"conversation": conversation, "message": result["message"]["id"],
                "decision": views.conversation_event(result["decision"], who.max_data_class)
                if result["decision"] is not None else None}

    @api.get("/conversations")
    def list_conversations(request: Request, project: str | None = None, limit: int = 50,
                           who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        found = [c for c in conversations.conversations(server.runtime().ledger.events(
            types=list(conversations.TYPES))).values() if c.operator == who.operator
            and (project is None or c.project == project)
            and views.within(project_class(server, c.project), who.max_data_class)]
        found.sort(key=lambda c: c.last_message, reverse=True)
        return {"conversations": [{"conversation": c.id, "project": c.project, "channel": c.channel,
                                   "started": c.started, "last_message": c.last_message, "closed": c.closed}
                                  for c in found[:max(1, min(limit, 200))]]}

    @api.get("/conversations/{conversation}")
    def show(conversation: str, request: Request, who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        found, events = own_conversation(server, who, conversation)
        return views.conversation_view(found, conversations.events_of(events, conversation),
                                       conversations.tasks_of(events, conversation), who.max_data_class)

    @api.get("/conversations/{conversation}/events", response_model=None)
    def events(conversation: str, request: Request, after: str | None = None,
               who: Principal = Depends(scope("read")),
               last_event_id: str | None = Header(default=None)) -> dict | StreamingResponse:
        server = server_of(request)
        found, ledger_events = own_conversation(server, who, conversation)
        cursor = last_event_id or after
        try:
            listed = _after(conversations.events_of(ledger_events, conversation), cursor)
        except KeyError:
            raise ApiError(400, "INVALID", f"{cursor} is not an event of {conversation}") from None
        if "text/event-stream" not in request.headers.get("accept", ""):
            shown = [views.conversation_event(e, who.max_data_class) for e in listed]
            return {"events": shown, "next": shown[-1]["id"] if shown else cursor}
        return StreamingResponse(_stream(server, conversation, cursor, lambda: scope("read")(principal(request))),
                                 media_type="text/event-stream")

    @api.get("/memory/{scope_name}")
    def list_memory(scope_name: str, request: Request, kind: str | None = None, done: bool = False,
                    who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        if kind is not None and kind not in memory.KINDS:
            raise ApiError(400, "INVALID", f"kind is one of {', '.join(memory.KINDS)}")
        items = memory.items(server.runtime().ledger.events(types=memory.EVENTS), server.memory, scope=scope_name,
                             cap=who.max_data_class, kinds=(kind,) if kind else memory.KINDS, include_done=done)
        return {"scope": scope_name, "items": [views.memory_view(i) for i in items]}

    @api.patch("/memory/{scope_name}/{mem_id}")
    def edit_memory(scope_name: str, mem_id: str, body: MemoryEditIn, request: Request,
                    who: Principal = Depends(scope("answer"))) -> dict:
        server = server_of(request)
        if (body.text is not None or body.pinned is not None) and who.channel != "web":
            # Pinned memory steers every later task: a named operator's session, never a token (design 08 §8).
            raise ApiError(403, "SCOPE", "editing or pinning memory needs the web app; a token may forget or "
                                         "mark an open point done")
        own_item(server, who, scope_name, mem_id)
        if server.memory is None:
            raise ApiError(404, "NOT_FOUND", f"no memory item {mem_id}")
        event = memory.edit(server.runtime().ledger, server.memory, mem_id, operator=who.operator,
                            channel=who.channel, text=body.text, pinned=body.pinned, done=body.done)
        return {"memory": mem_id, "event": event["id"]}

    @api.delete("/memory/{scope_name}/{mem_id}")
    def forget_memory(scope_name: str, mem_id: str, request: Request, reason: str | None = None,
                      who: Principal = Depends(scope("answer"))) -> dict:
        server = server_of(request)
        own_item(server, who, scope_name, mem_id)
        if server.memory is None:
            raise ApiError(404, "NOT_FOUND", f"no memory item {mem_id}")
        event = memory.forget(server.runtime().ledger, server.memory, mem_id, operator=who.operator,
                              channel=who.channel, reason=reason)
        return {"memory": mem_id, "forgotten": True, "event": event["id"]}

    return api


def _after(own: list[dict], cursor: str | None) -> list[dict]:
    if cursor is None:
        return own
    ids = [e["id"] for e in own]
    if cursor not in ids:
        raise KeyError(cursor)
    return own[ids.index(cursor) + 1:]


def _stream(server: Server, conversation: str, cursor: str | None, recheck):
    """Server-Sent Events of the conversation until it is closed or 15 minutes pass; every poll authenticates the
    reader again and applies its cap afresh, as the task stream does."""
    started = time.monotonic()
    while True:
        try:
            who = recheck()
        except ApiError as error:
            body = {"error": {"code": "UNAUTHENTICATED", "message": error.message, "details": None}}
            yield f"event: UNAUTHENTICATED\ndata: {json.dumps(body)}\n\n"
            return
        own = conversations.events_of(server.runtime().ledger.events(types=list(conversations.TYPES)), conversation)
        for event in _after(own, cursor):
            shown = views.conversation_event(event, who.max_data_class)
            yield f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(shown, ensure_ascii=False)}\n\n"
            cursor = event["id"]
        if any(e["type"] == "CONVERSATION_CLOSED" for e in own) or time.monotonic() - started > SSE_MAX_S:
            return
        time.sleep(SSE_POLL_S)
        yield ": keepalive\n\n"

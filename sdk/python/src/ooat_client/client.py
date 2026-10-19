"""A client for the REST API of `ooat serve` (design 05 §5, §9), standard library only.

It holds one API token (`ooat tokens create`), which the bot keeps in its own secret store, never in code. The token
goes to the OOAT server only: plain HTTP to this machine alone, no redirects followed, no proxy from the environment.
"""

import base64
import http.client
import ipaddress
import json
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from urllib.parse import quote, urlencode, urlsplit

API = "/api/v1"
DONE_WHEN = ("done when:", "hotovo když:")  # the line after which a chat message lists its acceptance criteria
CLOSED = frozenset({"CLOSED_DONE", "CLOSED_PARTIAL", "CLOSED_ABSTAINED", "CANCELLED"})
RECONNECT_S, MAX_RECONNECT_S = 1.0, 30.0  # the first wait after a dropped stream; waits double up to the cap


class OoatError(Exception):
    """A refusal: the HTTP status, the API's code (INVALID, SCOPE, ALREADY_ANSWERED …) and its message."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class Artifact:
    ref: str
    content: bytes | None  # None when the artifact is above the token's data class
    redacted: dict | None = None  # then the server's notice: {"redacted": "…", "link": "/tasks/…"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # the API never redirects; following one would carry the token elsewhere


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _error(status: int, body: bytes) -> OoatError:
    try:
        error = json.loads(body)["error"]
        return OoatError(status, str(error["code"]), str(error["message"]))
    except (ValueError, KeyError, TypeError):  # not the API's error, e.g. a proxy's page
        return OoatError(status, "HTTP", f"HTTP {status}")


def parse_message(text: str) -> tuple[str, list[str]]:
    """A chat message as a goal and acceptance criteria: the text before a "Done when:" line is the goal, each line
    after it (and any text on that line) a criterion, with a leading "-" or "*" dropped."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        marker = next((m for m in DONE_WHEN if line.strip().lower().startswith(m)), None)
        if marker is not None:
            criteria = (c.strip().lstrip("-*").strip() for c in [line.strip()[len(marker):], *lines[i + 1:]])
            return "\n".join(lines[:i]).strip(), [c for c in criteria if c]
    return text.strip(), []


class OoatClient:
    """The REST API as a bot uses it. A refusal raises OoatError; a server that cannot be reached raises OSError.
    `sleep` is how `follow` waits before it reconnects (tests pass their own)."""

    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0,
                 sleep: Callable[[float], None] = time.sleep):
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("base_url is http(s)://host:port of `ooat serve`")
        if parts.scheme == "http" and not _loopback(parts.hostname):
            raise ValueError("plain http only to this machine (127.0.0.1, ::1, localhost); use https beyond it")
        if not token:
            raise ValueError("an API token is needed: `ooat tokens create`")
        self.base_url, self.timeout, self._token, self._sleep = base_url.rstrip("/"), timeout, token, sleep
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)

    def __repr__(self) -> str:
        return f"OoatClient({self.base_url!r})"  # never the token

    # HTTP -------------------------------------------------------------------------------------------------------

    def _open(self, method: str, path: str, *, body: dict | None = None, headers: dict[str, str] | None = None):
        """The open response; any HTTP error status raises OoatError."""
        data = json.dumps(body).encode("utf-8") if body is not None else (b"" if method == "POST" else None)
        request = urllib.request.Request(self.base_url + API + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self._token}", "Accept": "application/json", "User-Agent": "ooat-client",
            **({"Content-Type": "application/json"} if body is not None else {}), **(headers or {})})
        try:
            return self._opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            with error:
                raise _error(error.code, error.read()) from None

    def _json(self, method: str, path: str, *, body: dict | None = None,
              headers: dict[str, str] | None = None) -> dict:
        with self._open(method, path, body=body, headers=headers) as response:
            return json.loads(response.read())

    # The API ----------------------------------------------------------------------------------------------------

    def me(self) -> dict:
        return self._json("GET", "/me")

    def submit(self, *, project: str, goal: str, acceptance: Sequence[str] = (),
               attachments: Sequence[tuple[str, bytes]] = (), key: str | None = None,
               expected_output: str | None = None, value: str | None = None, budget_usd: float | None = None,
               data_class: str | None = None) -> str:
        """Submit a task; returns its id. A repeated `key` (the chat's and the message's id) returns the first task
        instead of a second one, also after a restart of either side."""
        optional = {"expected_output": expected_output, "value": value, "budget_usd": budget_usd,
                    "data_class": data_class}
        body = {"project": project, "goal": goal, "acceptance": list(acceptance),
                "attachments": [{"name": name, "content_base64": base64.b64encode(content).decode("ascii")}
                                for name, content in attachments],
                **{k: v for k, v in optional.items() if v is not None}}
        return self._json("POST", "/tasks", body=body, headers={"Idempotency-Key": key} if key else None)["task"]

    def task(self, task: str) -> dict:
        return self._json("GET", f"/tasks/{quote(task)}")

    def events(self, task: str, after: str | None = None) -> list[dict]:
        query = f"?{urlencode({'after': after})}" if after else ""
        return self._json("GET", f"/tasks/{quote(task)}/events{query}")["events"]

    def follow(self, task: str, after: str | None = None, stop: threading.Event | None = None) -> Iterator[dict]:
        """The task's timeline events after `after`, as they happen, until TASK_CLOSED (yielded too).

        After a dropped connection or a busy server (5xx) it reconnects from the last event it yielded, waiting
        1 s, doubling to 30 s; a refusal (4xx), a token revoked while it reads and a certificate that fails
        verification raise. A stream the server ends (after 15 minutes) is opened again; for a task that is
        already closed the iteration ends. Setting `stop` ends it too, within a second, also while it waits."""
        cursor, wait = after, RECONNECT_S
        while not (stop and stop.is_set()):
            try:
                headers = {"Accept": "text/event-stream", **({"Last-Event-ID": cursor} if cursor else {})}
                with self._open("GET", f"/tasks/{quote(task)}/events", headers=headers) as response:
                    for message in _sse(response, stop):
                        if message.get("event") == "UNAUTHENTICATED":
                            raise _error(401, message["data"].encode("utf-8"))
                        event = json.loads(message["data"])
                        cursor, wait = event["id"], RECONNECT_S
                        yield event
                        if event["type"] == "TASK_CLOSED":
                            return
                if stop and stop.is_set():
                    return
                if self.task(task)["state"] in CLOSED:
                    # It may have closed as the stream ended: what came after the cursor (its close) is still due.
                    yield from self.events(task, cursor)
                    return
                self.pause(RECONNECT_S, stop)
                continue
            except (OoatError, OSError, http.client.HTTPException) as error:
                if not retryable(error):
                    raise
            self.pause(wait, stop)
            wait = min(wait * 2, MAX_RECONNECT_S)

    def pause(self, seconds: float, stop: threading.Event | None = None) -> None:
        """Wait before trying again: until `stop` is set when there is one, else with the client's `sleep`."""
        if stop is None:
            self._sleep(seconds)
        else:
            stop.wait(seconds)

    def questions(self) -> list[dict]:
        return self._json("GET", "/hil")["requests"]

    def answer(self, request: str, *, choice: str | None = None, text: str | None = None) -> dict:
        body = {name: value for name, value in (("choice", choice), ("text", text)) if value is not None}
        return self._json("POST", f"/hil/{quote(request)}/answer", body=body)

    def rate(self, task: str, *, accepted: bool, value_class: str, note: str | None = None) -> dict:
        body = {"accepted": accepted, "value_class": value_class, **({"note": note} if note else {})}
        return self._json("POST", f"/tasks/{quote(task)}/rating", body=body)

    def cancel(self, task: str) -> dict:
        return self._json("POST", f"/tasks/{quote(task)}/cancel")

    def revert(self, task: str) -> dict:
        """Write back the originals of the project files a closed task changed. Ask the operator to confirm
        first (design 07: revert takes a second confirmation)."""
        return self._json("POST", f"/tasks/{quote(task)}/revert")

    def artifact(self, ref: str) -> Artifact:
        """The artifact's bytes, or the server's notice when it is above the token's data class."""
        with self._open("GET", f"/artifacts/{quote(ref)}", headers={"Accept": "*/*"}) as response:
            content = response.read()
            if response.headers.get_content_type() == "application/json":  # content is text/plain or bytes
                return Artifact(ref, None, json.loads(content))
            return Artifact(ref, content)

    def stats(self, *, period: str = "7d", project: str | None = None, group: str = "role") -> dict:
        query = urlencode({"period": period, "group": group, **({"project": project} if project else {})})
        return self._json("GET", f"/stats?{query}")

    # Conversations and memory (ADR 0018) ------------------------------------------------------------------------

    def send_message(self, *, project: str, text: str, conversation: str | None = None, reply_to: str | None = None,
                     attachments: Sequence[tuple[str, bytes]] = (), key: str | None = None) -> dict:
        """A message to the reception: {conversation, message} at once; the decision comes on the conversation's
        events (`follow_conversation`). A repeated `key` returns the first message."""
        body = {"project": project, "text": text,
                "attachments": [{"name": name, "content_base64": base64.b64encode(content).decode("ascii")}
                                for name, content in attachments],
                **{k: v for k, v in (("conversation", conversation), ("reply_to", reply_to)) if v is not None}}
        return self._json("POST", "/conversations/messages", body=body,
                          headers={"Idempotency-Key": key} if key else None)

    def tap(self, conversation: str, tap: str, text: str | None = None) -> dict:
        """A button of a reception reply: yes, differently, new_thing, make_task, todo, remember,
        forget:<mem>, done:<mem>. Returns {conversation, message, decision}; a Differently with a text is decided
        later, like a message."""
        body = {"tap": tap, **({"text": text} if text is not None else {})}
        return self._json("POST", f"/conversations/{quote(conversation)}/taps", body=body)

    def conversation(self, conversation: str) -> dict:
        return self._json("GET", f"/conversations/{quote(conversation)}")

    def conversation_events(self, conversation: str, after: str | None = None) -> list[dict]:
        query = f"?{urlencode({'after': after})}" if after else ""
        return self._json("GET", f"/conversations/{quote(conversation)}/events{query}")["events"]

    def follow_conversation(self, conversation: str, after: str | None = None,
                            stop: threading.Event | None = None) -> Iterator[dict]:
        """The conversation's events after `after`, as they happen, until CONVERSATION_CLOSED (yielded too), with
        the reconnect rules of `follow`."""
        cursor, wait = after, RECONNECT_S
        path = f"/conversations/{quote(conversation)}/events"
        while not (stop and stop.is_set()):
            try:
                headers = {"Accept": "text/event-stream", **({"Last-Event-ID": cursor} if cursor else {})}
                with self._open("GET", path, headers=headers) as response:
                    for message in _sse(response, stop):
                        if message.get("event") == "UNAUTHENTICATED":
                            raise _error(401, message["data"].encode("utf-8"))
                        event = json.loads(message["data"])
                        cursor, wait = event["id"], RECONNECT_S
                        yield event
                        if event["type"] == "CONVERSATION_CLOSED":
                            return
                if stop and stop.is_set():
                    return
                if self.conversation(conversation)["closed"] is not None:
                    yield from self.conversation_events(conversation, cursor)
                    return
                self.pause(RECONNECT_S, stop)
                continue
            except (OoatError, OSError, http.client.HTTPException) as error:
                if not retryable(error):
                    raise
            self.pause(wait, stop)
            wait = min(wait * 2, MAX_RECONNECT_S)

    def memory(self, scope: str, kind: str | None = None, done: bool = False) -> list[dict]:
        """A project's memory items (or the operator's preferences, scope "operator") within the token's cap."""
        query = urlencode({**({"kind": kind} if kind else {}), **({"done": "true"} if done else {})})
        return self._json("GET", f"/memory/{quote(scope)}" + (f"?{query}" if query else ""))["items"]

    def forget(self, scope: str, memory: str) -> dict:
        return self._json("DELETE", f"/memory/{quote(scope)}/{quote(memory)}")

    def done(self, scope: str, memory: str) -> dict:
        """Mark an open point (todo) done."""
        return self._json("PATCH", f"/memory/{quote(scope)}/{quote(memory)}", body={"done": True})


def retryable(error: Exception) -> bool:
    """Worth trying again: a busy server (5xx), a dropped or refused connection; never a refusal (4xx) or a
    certificate that fails verification."""
    if isinstance(error, OoatError):
        return error.status >= 500
    reason = getattr(error, "reason", error)  # urllib wraps TLS errors in URLError
    return not isinstance(reason, ssl.SSLCertVerificationError)


def _sse(lines, stop: threading.Event | None = None) -> Iterator[dict[str, str]]:
    """Server-Sent Events messages from a response's lines, until `stop` is set (the server's keepalive comes
    every second); a message cut off by a dropped connection is never returned, so the cursor only moves past
    events that arrived whole."""
    fields: dict[str, str] = {}
    for raw in lines:
        if stop and stop.is_set():
            return
        # A whole line holds whole characters; only the last, cut-off line may end inside one, and it is dropped.
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            if "data" in fields:
                yield fields
            fields = {}
        elif not line.startswith(":"):  # ":" starts the server's keepalive comment
            name, _, value = line.partition(":")
            value = value.removeprefix(" ")
            fields[name] = f"{fields[name]}\n{value}" if name == "data" and name in fields else value

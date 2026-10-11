# The Python Client and the Chat Bridge (05c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A bot that today calls an AI CLI can send its chat messages to OOAT instead: a small Python client for the REST API of `ooat serve` and a reference chat bridge in `sdk/python`, the bridge contract in `docs/`, and a test that plays a whole chat against the real server.

**Architecture:** One new distribution, `ooat-client` (import `ooat_client`), in `sdk/python/`, standard library only and independent of `ooat-core`: it speaks HTTP. `client.py` holds `OoatClient` (one bearer token, typed errors, the timeline as Server-Sent Events with reconnect); `bridge.py` holds `Bridge`, the contract's chat actions on top of the client for any chat platform, through a two-method `Chat` protocol; `texts.py` holds what the bridge writes, in English and Czech. The client's own tests run against a standard-library stub server; the client and the bridge are tested end to end in `core/tests/` against the real app served by uvicorn on a loopback port with its runner thread.

**Tech Stack:** Python 3.12+ standard library (`urllib.request`, `http.client`, `json`, `base64`), hatchling for the package, pytest; on the server side the existing FastAPI app and uvicorn 0.54 (tests only).

**Spec:** `tasks/f1-skeleton/task-05-operator-ux/design.md` (approved 2026-10-09; §5, §6, §9, §11, §13); ADR 0016.

## Global Constraints

- `ooat-client` depends on nothing but the standard library and never imports `ooat_core` (design §9: "standard library only"). Python 3.12+.
- No change to the server: no endpoint, schema, event type or ledger change. The only server-side edits are test helpers in `core/tests/api_fakes.py`.
- The token is the bot's secret: never in code, logs, fixtures, docs or `repr`; the client sends it only to its `base_url`: plain `http` only to loopback (`127.0.0.1`, `::1`, `localhost`), redirects never followed, proxies from the environment never used.
- The bridge is platform-neutral: no Telegram or other platform code, no network access except through `OoatClient`. The private bot is changed in its own repository, not here; do not read its `.env`, `projects.json` or tokens.
- OOAT trusts the token; the bot vouches for the person: the docs say the bot checks the allowed chat or user before it calls the bridge (design §9).
- The bridge token's data-class cap is `internal` (owner decision, design §13): content above it reaches the chat only as a notice to open the web app.
- R3 stays refused: the bridge shows an R3 question without buttons; the server's refusal is unchanged.
- Chat texts in `en` and `cs` with the same keys (spec §10); event types, states and API error codes stay English.
- No publish: `ooat-client` is installed from the checkout (`pip install -e sdk/python`); PyPI only on the owner's go.
- Tests stay offline: loopback only (a stub server, uvicorn on `127.0.0.1` port 0).
- Code, comments, docs and commits in English; lines at most 120 characters. Where a line of this plan's code exceeds 120 characters, wrap it; that needs no ruling.

**Decisions this plan takes where the design is silent** (for the owner's review of this plan):
1. **Synchronous client.** `urllib` only, so the client has no dependency; `follow()` is a plain generator. An async bot runs `bridge.watch` (or `follow`) with `asyncio.to_thread`. Design §9's sketch (`async for update in ooat.follow(task)`) is amended to the synchronous form in Task 4.
2. **Package:** `ooat-client` `0.1.0.dev0` in `sdk/python/` (src layout, hatchling), Apache-2.0, not published. Installed in CI and by developers with `pip install -e sdk/python`.
3. **Where the token may go:** plain HTTP only to loopback (`ooat serve --host` beyond loopback needs TLS anyway, design §6), no redirects (urllib would carry the `Authorization` header to the new host), no proxy from `HTTP_PROXY` and the like (OOAT is reached directly).
4. **`follow()` reconnects** as the web app does (plan 05b): after a dropped connection or a 5xx (`LEDGER_BUSY`) it waits 1 s, doubling to 30 s, and goes on from the last event it yielded (`Last-Event-ID`); a 4xx and the stream's `UNAUTHENTICATED` event raise `OoatError`; it ends after `TASK_CLOSED`, and at once for a task that is already closed (a bot restarted after the close) instead of reconnecting forever.
5. **The reference bridge ships in the package** (`ooat_client.Bridge`) rather than only in a test, so a bot can use it as it is or copy it. A bot gives it a `Chat` (`id`, `send(text, buttons) -> message id`, `send_file(name, content, caption) -> message id`). Methods called on a person's action (`on_message`, `on_button`, `on_reply`, `cancel`, `stats`) return the text to show them; `watch(task)` posts on its own and blocks until the task is closed.
6. **Questions in chat:** one button per option on its own row (★ the recommended one, the cost when it has one), the default on silence and the deadline (UTC) in the text. The options answered with text (`clarify`, `narrow_scope`) do not call the API: their button asks for a reply, and a reply to the question message answers with its text (design §9). The bridge keeps question messages in memory only: after a restart buttons still work (they carry the ids), replies to older questions are not recognised.
7. **Rating in chat:** two rows, `Accepted A/B/C` and `Not accepted A/B/C`. The API needs a value class with every rating, so "Not accepted" is one button per value (design §9 lists "Accepted A / B / C and Not accepted"); decisions stay for the web rating card.
8. **Result in chat:** the final document as text in at most 3 messages of `limit` characters (default 4096, Telegram's), else (or when it is not UTF-8) as a file `<task>.md`; content above the cap as the notice. Then a footer `state · topology · cost · tokens in/out · time` with the rating buttons. Tokens are summed from the task's events, so a restarted watch reports them complete.
9. **Progress lines:** one line for the Gate's topology (`TOPOLOGY_DECIDED`), one per attempt (`CONTRACT_ISSUED`), one per answer (`HIL_RESPONSE`, including a default applied on silence). Events whose body is above the cap post nothing except the question and the result.
10. **Idempotency key** `<chat id>:<message id>`: unique per token across chats, so a platform's repeated delivery never creates a second task.
11. **"Done when:"** is also recognised in Czech (`Hotovo když:`), case-insensitively; text on the marker line is the first criterion; a leading `-` or `*` is dropped. A message with nothing before the marker is refused by the bridge (no goal).
12. **`/stats`** shows the chat's project, by role and by connector, for `7d` unless the bot passes another period.
13. **Button data** is at most 64 bytes (Telegram's callback-data limit, the smallest of the common platforms): `a:<request>:<option>` and `r:<task>:<A|B|C>:<y|n>`; a test checks every button the bridge sent.
14. **Tests:** the client's behaviour on the wire (headers, errors, redirects, reconnects) against a standard-library stub server in `sdk/python/tests/`; the client and the bridge end to end in `core/tests/` against the real app on uvicorn, because FastAPI's test client buffers a whole streamed body (`.claude/lessons.md`).

## Review Focus

1. The chat platform delivers one message twice (a webhook retry, a bot restart) → one task (Task 3 test `test_a_chat_message_becomes_a_task_with_a_question_a_result_a_rating_and_stats`, second `on_message`).
2. The stream drops mid-message, the ledger is busy (503) or the server ends the stream after 15 minutes → the bot goes on from the last event, without gaps or duplicates (Task 2 tests `test_follow_reconnects_after_a_drop_from_the_last_event`, `test_follow_waits_out_a_busy_server_and_stops_on_a_refusal`).
3. A chat message with personal data (the pre-scan raises the class above the token's cap) → nothing of it reaches the chat, and answering or cancelling it from the chat is refused with a readable reason (Task 3 test `test_content_above_the_tokens_data_class_never_reaches_the_chat`).
4. The bot restarts after a task closed and follows it again → the iteration ends at once, no reconnect loop (Task 2 tests `test_follow_ends_for_a_closed_task_and_on_a_revoked_token` and `test_follow_yields_the_timeline_to_its_end_and_a_closed_task_ends_it_at_once`).
5. A base URL with plain `http` to another machine, a redirect from the server, or a proxy variable in the bot's environment → the token goes to the OOAT server only (Task 1 tests `test_plain_http_only_to_this_machine`, `test_a_redirect_is_not_followed`, `test_proxies_from_the_environment_are_not_used`).

---

## File Structure

```
sdk/python/pyproject.toml, sdk/python/README.md, sdk/python/src/ooat_client/{__init__,client}.py,
sdk/python/tests/{stub_http,test_ooat_client}.py, pytest.ini, .github/workflows/tests.yml        (Task 1)
sdk/python/src/ooat_client/client.py, sdk/python/tests/test_ooat_client.py,
core/tests/api_fakes.py, core/tests/test_client.py                                                (Task 2)
sdk/python/src/ooat_client/{__init__,bridge,texts}.py, sdk/python/tests/test_ooat_bridge.py,
core/tests/test_bridge.py                                                                          (Task 3)
docs/chat-bridge.md, docs/description.md, README.md, .claude/lessons.md,
tasks/f1-skeleton/task-05-operator-ux/design.md                                                    (Task 4)
```

How to apply a "replace" step: the old text occurs exactly once in the file; replace it with the new text. Files may
have CRLF line endings on Windows — match the text, not the line endings. Work on a branch `feat/05c-client` from
`main`; run every command from the repository root with the project virtual environment active.

---

### Task 1: The package and the client's calls

**Files:**
- Create: `sdk/python/pyproject.toml`, `sdk/python/README.md`
- Create: `sdk/python/src/ooat_client/__init__.py`, `sdk/python/src/ooat_client/client.py`
- Create: `sdk/python/tests/stub_http.py`, `sdk/python/tests/test_ooat_client.py`
- Modify: `pytest.ini`, `.github/workflows/tests.yml`

**Interfaces:**
- Produces (used by Tasks 2 and 3):
  - `OoatClient(base_url: str, token: str, *, timeout: float = 30.0, sleep: Callable[[float], None] = time.sleep)`; `ValueError` for plain `http` beyond loopback or an empty token.
  - `me() -> dict`; `submit(*, project, goal, acceptance=(), attachments: Sequence[tuple[str, bytes]] = (), key=None, expected_output=None, value=None, budget_usd=None, data_class=None) -> str` (the task id); `task(task) -> dict`; `events(task, after=None) -> list[dict]`; `questions() -> list[dict]`; `answer(request, *, choice=None, text=None) -> dict`; `rate(task, *, accepted: bool, value_class: str, note=None) -> dict`; `cancel(task) -> dict`; `artifact(ref) -> Artifact`; `stats(*, period="7d", project=None, group="role") -> dict`.
  - `OoatError(status: int, code: str, message: str)` with attributes `status`, `code`, `message`; code `"HTTP"` when the body is not the API's error.
  - `Artifact(ref: str, content: bytes | None, redacted: dict | None = None)`.
  - `parse_message(text: str) -> tuple[str, list[str]]` (goal, acceptance criteria).
  - `client._open(method, path, *, body=None, headers=None)` returns the open `http.client.HTTPResponse` and raises `OoatError` for any HTTP error status (Task 2 builds `follow` on it).
- Produces (tests, used by Task 2): `stub_http.Stub(*replies)` (context manager; `.url`, `.requests`: list of `{"method", "path", "headers", "body"}`), a reply being `(status, body)`, `(status, body, content_type)` or a callable taking the request handler.

- [ ] **Step 1: Create the package files and install it**

Create `sdk/python/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "ooat-client"
version = "0.1.0.dev0"
description = "A client for the REST API of ooat serve and a reference chat bridge, standard library only."
readme = "README.md"
requires-python = ">=3.12"
license = "Apache-2.0"
dependencies = []

[tool.hatch.build.targets.wheel]
packages = ["src/ooat_client"]
```

Create `sdk/python/README.md`:

````markdown
# ooat-client

A client for the REST API of `ooat serve` and a reference chat bridge, for bots and scripts. Standard library only,
Python 3.12+. Not on PyPI yet: install it from a checkout with `pip install -e sdk/python`.

```python
from ooat_client import OoatClient

client = OoatClient("http://127.0.0.1:8765", token)  # from `ooat tokens create`; keep it in your secret store
task = client.submit(project="docs", goal="Summarise the contract.", acceptance=["At most 300 words."])
for event in client.follow(task):                     # the task's timeline, until TASK_CLOSED
    print(event["type"])
```

The chat bridge contract and `ooat_client.Bridge`: [`docs/chat-bridge.md`](../../docs/chat-bridge.md).
````

Create `sdk/python/src/ooat_client/__init__.py`:

```python
"""ooat-client: the REST API of `ooat serve` for bots and scripts, and a reference chat bridge (design 05 §9)."""

from .client import Artifact, OoatClient, OoatError, parse_message

__all__ = ["Artifact", "OoatClient", "OoatError", "parse_message"]
```

Create `sdk/python/src/ooat_client/client.py` with only the module docstring for now:

```python
"""A client for the REST API of `ooat serve` (design 05 §5, §9), standard library only."""
```

Run: `python -m pip install -e sdk/python`
Expected: `Successfully installed ooat-client-0.1.0.dev0`

In `pytest.ini`, replace:

```
testpaths = spec/tests catalog/tests core/tests adapters
```

with:

```
testpaths = spec/tests catalog/tests core/tests adapters sdk/python/tests
```

In `.github/workflows/tests.yml`, replace:

```yaml
      - run: python -m pip install -e core
```

with:

```yaml
      - run: python -m pip install -e core
      - run: python -m pip install -e sdk/python
```

- [ ] **Step 2: Write the stub server and the failing tests**

Create `sdk/python/tests/stub_http.py`:

```python
"""A scripted HTTP server on a loopback port for the client's tests: each request gets the next reply."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Stub:
    """Replies are (status, body), (status, body, content type) or a callable that writes the reply itself; a dict
    body is sent as JSON. Every request is kept in `requests` with its method, path, headers and body."""

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                stub.requests.append({"method": self.command, "path": self.path, "headers": self.headers,
                                      "body": self.rfile.read(length)})
                reply = stub.replies.pop(0)
                if callable(reply):
                    reply(self)
                    return
                status, body, *rest = reply
                data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", rest[0] if rest else "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = serve

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
```

Create `sdk/python/tests/test_ooat_client.py`:

```python
"""The client on the wire, against a stub server (design 05 §9): what it sends, what it refuses, how it fails."""

import base64
import json

import pytest
from stub_http import Stub

from ooat_client import OoatClient, OoatError, parse_message

BUSY = {"error": {"code": "LEDGER_BUSY", "message": "the ledger is busy", "details": None}}


def sent(request) -> dict:
    return json.loads(request["body"]) if request["body"] else {}


def test_plain_http_only_to_this_machine():
    for url in ("http://127.0.0.1:8765", "http://localhost:8765", "http://[::1]:8765", "https://ooat.example"):
        OoatClient(url, "secret")
    for url in ("http://192.168.1.5:8765", "http://ooat.example", "ftp://127.0.0.1", "127.0.0.1:8765"):
        with pytest.raises(ValueError):
            OoatClient(url, "secret")
    with pytest.raises(ValueError):
        OoatClient("http://127.0.0.1:8765", "")
    assert "secret" not in repr(OoatClient("http://127.0.0.1:8765", "secret"))


def test_submit_sends_the_token_the_key_and_the_attachments():
    with Stub((202, {"task": "tsk_1", "state": "SUBMITTED"})) as stub:
        task = OoatClient(stub.url + "/", "secret").submit(
            project="docs", goal="Shrň smlouvu.", acceptance=["Nejvýše 300 slov."], attachments=[("a.txt", b"hi")],
            key="chat-1:7", data_class="internal")
    assert task == "tsk_1"
    (request,) = stub.requests
    assert request["method"] == "POST" and request["path"] == "/api/v1/tasks"
    assert request["headers"]["Authorization"] == "Bearer secret"
    assert request["headers"]["Idempotency-Key"] == "chat-1:7"
    assert sent(request) == {"project": "docs", "goal": "Shrň smlouvu.", "acceptance": ["Nejvýše 300 slov."],
                             "attachments": [{"name": "a.txt", "content_base64": base64.b64encode(b"hi").decode()}],
                             "data_class": "internal"}


def test_each_call_reaches_its_endpoint():
    with Stub((200, {"task": "tsk_1"}), (200, {"events": [{"id": "evt_1"}], "next": "evt_1"}),
              (200, {"requests": []}), (202, {"task": "tsk_1", "response": "evt_2"}), (201, {"rating": "evt_3"}),
              (202, {"cancel": "requested"}), (200, {"groups": []}), (200, {"operator": "operator"})) as stub:
        client = OoatClient(stub.url, "secret")
        assert client.task("tsk_1") == {"task": "tsk_1"}
        assert client.events("tsk_1", after="evt_0") == [{"id": "evt_1"}]
        assert client.questions() == []
        client.answer("evt_2", choice="run_as_is")
        client.rate("tsk_1", accepted=False, value_class="C", note="too long")
        assert client.cancel("tsk_1") == {"cancel": "requested"}
        client.stats(period="30d", project="docs", group="connector")
        assert client.me() == {"operator": "operator"}
    assert [(r["method"], r["path"], sent(r)) for r in stub.requests] == [
        ("GET", "/api/v1/tasks/tsk_1", {}), ("GET", "/api/v1/tasks/tsk_1/events?after=evt_0", {}),
        ("GET", "/api/v1/hil", {}), ("POST", "/api/v1/hil/evt_2/answer", {"choice": "run_as_is"}),
        ("POST", "/api/v1/tasks/tsk_1/rating", {"accepted": False, "value_class": "C", "note": "too long"}),
        ("POST", "/api/v1/tasks/tsk_1/cancel", {}),
        ("GET", "/api/v1/stats?period=30d&group=connector&project=docs", {}),
        ("GET", "/api/v1/me", {})]
    assert stub.requests[5]["headers"]["Content-Length"] == "0"  # the server wants a length on every POST


def test_a_refusal_is_a_typed_error_and_so_is_a_foreign_error_page():
    conflict = {"error": {"code": "ALREADY_ANSWERED", "message": "evt_2 is already answered", "details": None}}
    with Stub((409, conflict), (502, b"<html>Bad gateway</html>", "text/html")) as stub:
        client = OoatClient(stub.url, "secret")
        with pytest.raises(OoatError) as first:
            client.answer("evt_2", choice="run_as_is")
        with pytest.raises(OoatError) as second:
            client.me()
    assert (first.value.status, first.value.code, first.value.message) == (409, "ALREADY_ANSWERED",
                                                                            "evt_2 is already answered")
    assert (second.value.status, second.value.code) == (502, "HTTP")


def test_a_redirect_is_not_followed():
    def redirect(handler):
        handler.send_response(302)
        handler.send_header("Location", "/elsewhere")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    with Stub(redirect, (200, {"operator": "operator"})) as stub:
        with pytest.raises(OoatError) as refused:
            OoatClient(stub.url, "secret").me()
    assert refused.value.status == 302 and len(stub.requests) == 1  # the token went nowhere else


def test_proxies_from_the_environment_are_not_used(monkeypatch):
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")  # nothing listens there: a proxied call would fail
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    with Stub((200, {"operator": "operator"})) as stub:
        assert OoatClient(stub.url, "secret").me() == {"operator": "operator"}


def test_an_artifact_is_its_bytes_or_the_servers_notice():
    notice = {"redacted": "above this token's data class; open in the web app", "link": "/tasks/tsk_1"}
    with Stub((200, b"# Doc\n", "text/plain; charset=utf-8"), (200, notice)) as stub:
        client = OoatClient(stub.url, "secret")
        document, above = client.artifact("art_1@v1"), client.artifact("art_2@v1")
    assert document.content == b"# Doc\n" and document.redacted is None
    assert above.content is None and above.redacted == notice
    assert stub.requests[0]["path"] == "/api/v1/artifacts/art_1%40v1"


def test_a_message_becomes_a_goal_and_its_criteria():
    assert parse_message("Shrň smlouvu.") == ("Shrň smlouvu.", [])
    assert parse_message("Shrň smlouvu.\nPro jednatele.\n\nDone when:\n- Nejvýše 300 slov.\n* Česky.\n\n") == (
        "Shrň smlouvu.\nPro jednatele.", ["Nejvýše 300 slov.", "Česky."])
    assert parse_message("Shrň smlouvu.\nHOTOVO KDYŽ: nejvýše 300 slov") == ("Shrň smlouvu.",
                                                                        ["nejvýše 300 slov"])
    assert parse_message("Done when: x") == ("", ["x"])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest sdk/python/tests -q`
Expected: FAIL with `ImportError: cannot import name 'OoatClient' from 'ooat_client.client'`

- [ ] **Step 4: Write the client's calls**

Replace the whole content of `sdk/python/src/ooat_client/client.py` with:

```python
"""A client for the REST API of `ooat serve` (design 05 §5, §9), standard library only.

It holds one API token (`ooat tokens create`), which the bot keeps in its own secret store, never in code. The token
goes to the OOAT server only: plain HTTP to this machine alone, no redirects followed, no proxy from the environment.
"""

import base64
import ipaddress
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import quote, urlencode, urlsplit

API = "/api/v1"
DONE_WHEN = ("done when:", "hotovo když:")  # the line after which a chat message lists its acceptance criteria


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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest sdk/python/tests -q`
Expected: `8 passed`

- [ ] **Step 6: Commit**

```bash
git add sdk/python/pyproject.toml sdk/python/README.md sdk/python/src/ooat_client/__init__.py sdk/python/src/ooat_client/client.py sdk/python/tests/stub_http.py sdk/python/tests/test_ooat_client.py pytest.ini .github/workflows/tests.yml
git commit -m "feat(sdk): ooat-client, the REST API's calls with the token kept to the server (plan 05c)"
```

---

### Task 2: Following a task's timeline

**Files:**
- Modify: `sdk/python/src/ooat_client/client.py`
- Modify: `sdk/python/tests/test_ooat_client.py`
- Modify: `core/tests/api_fakes.py` (`Served(runner=…)`, `listening`, `wait_for`, `secret`)
- Create: `core/tests/test_client.py`

**Interfaces:**
- Consumes: `OoatClient._open`, `OoatClient.task`, `OoatError` (Task 1).
- Produces (used by Task 3):
  - `OoatClient.follow(task: str, after: str | None = None) -> Iterator[dict]`: timeline events (`{"id", "ts", "type", "actor", "refs", "cost", "body"}`; `body` is the server's notice above the cap) until `TASK_CLOSED`, which it yields too.
  - `ooat_client.client.CLOSED`: the closed states.
- Produces (tests, used by Task 3): in `core/tests/api_fakes.py`
  - `Served(tmp_path, …, runner=False, **settings)`: `runner=True` starts the runner thread with the app's lifespan;
  - `listening(served)`: context manager, the app on uvicorn on `127.0.0.1` port 0, yields its base URL;
  - `wait_for(found, timeout=20.0)`: the first truthy value of `found()`;
  - `secret(headers) -> str`: the token from `Served.token()`'s headers.

- [ ] **Step 1: Write the failing tests**

Append to `sdk/python/tests/test_ooat_client.py`:

```python
def event(id, kind="RESULT"):
    return {"id": id, "ts": "2026-10-11T10:00:00Z", "type": kind, "actor": {"kind": "runtime", "id": "ooat"},
            "refs": [], "cost": None, "body": {}}


def stream(*events, cut=False, unauthenticated=False):
    """A Server-Sent Events reply that ends when the server closes the connection."""
    def reply(handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Connection", "close")
        handler.end_headers()
        for item in events:
            handler.wfile.write(f"id: {item['id']}\nevent: {item['type']}\ndata: {json.dumps(item)}\n\n".encode())
        if unauthenticated:
            body = {"error": {"code": "UNAUTHENTICATED", "message": "unknown, expired or revoked token",
                              "details": None}}
            handler.wfile.write(f"event: UNAUTHENTICATED\ndata: {json.dumps(body)}\n\n".encode())
        if cut:  # the connection drops in the middle of a message
            handler.wfile.write(b'id: evt_9\nevent: RESULT\ndata: {"id": "evt_9"')
        handler.close_connection = True
    return reply


def follower(stub):
    waits = []
    return OoatClient(stub.url, "secret", sleep=waits.append), waits


def test_follow_reconnects_after_a_drop_from_the_last_event():
    with Stub(stream(event("evt_1"), cut=True), (200, {"state": "RUNNING"}),
              stream(event("evt_2", "TASK_CLOSED"))) as stub:
        client, waits = follower(stub)
        seen = [e["id"] for e in client.follow("tsk_1")]
    assert seen == ["evt_1", "evt_2"]  # the cut-off evt_9 never arrived, so it is not yielded
    assert [r["path"] for r in stub.requests] == ["/api/v1/tasks/tsk_1/events", "/api/v1/tasks/tsk_1",
                                                  "/api/v1/tasks/tsk_1/events"]
    assert stub.requests[0]["headers"]["Accept"] == "text/event-stream"
    assert stub.requests[0]["headers"]["Last-Event-ID"] is None
    assert stub.requests[2]["headers"]["Last-Event-ID"] == "evt_1"
    assert waits == [1.0]


def test_follow_waits_out_a_busy_server_and_stops_on_a_refusal():
    with Stub((503, BUSY), (503, BUSY), stream(event("evt_1", "TASK_CLOSED"))) as stub:
        client, waits = follower(stub)
        assert [e["id"] for e in client.follow("tsk_1", after="evt_0")] == ["evt_1"]
    assert waits == [1.0, 2.0] and stub.requests[0]["headers"]["Last-Event-ID"] == "evt_0"
    missing = {"error": {"code": "NOT_FOUND", "message": "no task tsk_1", "details": None}}
    with Stub((404, missing)) as stub:
        client, waits = follower(stub)
        with pytest.raises(OoatError) as refused:
            list(client.follow("tsk_1"))
    assert refused.value.code == "NOT_FOUND" and waits == []


def test_follow_ends_for_a_closed_task_and_on_a_revoked_token():
    with Stub(stream(), (200, {"state": "CLOSED_DONE"})) as stub:  # the cursor was the task's last event
        client, waits = follower(stub)
        assert list(client.follow("tsk_1", after="evt_7")) == []
    assert waits == []
    with Stub(stream(event("evt_1"), unauthenticated=True)) as stub:
        client, waits = follower(stub)
        timeline = client.follow("tsk_1")
        assert next(timeline)["id"] == "evt_1"
        with pytest.raises(OoatError) as refused:
            next(timeline)
    assert (refused.value.status, refused.value.code) == (401, "UNAUTHENTICATED") and waits == []


def test_follow_retries_a_server_it_cannot_reach():
    class Stop(Exception):
        pass

    waits = []

    def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 2:  # Windows takes about 2 s to refuse a connection: two attempts are enough
            raise Stop

    with Stub() as stub:
        url = stub.url  # the port is free again once the stub is closed
    with pytest.raises(Stop):
        list(OoatClient(url, "secret", sleep=sleep).follow("tsk_1"))
    assert waits == [1.0, 2.0]
```

In `core/tests/api_fakes.py`, replace:

```python
from datetime import datetime, timezone

from fastapi.testclient import TestClient
```

with:

```python
import socket
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi.testclient import TestClient
```

replace:

```python
    def __init__(self, tmp_path, model=None, jev=None, classes=("public", "internal"), **settings):
```

with:

```python
    def __init__(self, tmp_path, model=None, jev=None, classes=("public", "internal"), runner=False, **settings):
```

replace:

```python
                              routing=RoutingPolicy(routing_document()), clock=now, start_runner=False)
```

with:

```python
                              routing=RoutingPolicy(routing_document()), clock=now, start_runner=runner)
```

and append to the same file:

```python
def secret(headers: dict) -> str:
    """The token in `Served.token()`'s headers, as a bot keeps it."""
    return headers["Authorization"].removeprefix("Bearer ")


def wait_for(found, timeout: float = 20.0):
    """The first truthy value of `found()`, polled while other threads (the runner, a stream) work."""
    deadline = time.monotonic() + timeout
    while not (value := found()):
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)
    return value


@contextmanager
def listening(served: Served):
    """The app on uvicorn on a free loopback port, as `ooat serve` runs it (with `Served(runner=True)` its runner
    thread too), for clients that speak HTTP. Yields the base URL."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    # A stream still open when a test fails must not hold the shutdown for its 15 minutes.
    server = uvicorn.Server(uvicorn.Config(served.app, log_level="warning", lifespan="on", timeout_graceful_shutdown=5))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        wait_for(lambda: server.started, timeout=10.0)
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(30)
        sock.close()
```

Create `core/tests/test_client.py`:

```python
"""The Python client (sdk/python) against `ooat serve` on a loopback port, with its runner thread (design 05 §9)."""

import pytest
from api_fakes import CRITERIA, Served, listening, secret

from ooat_client import OoatClient, OoatError
from ooat_core import endpoints, tokens

GOAL = "Shrň smlouvu pro jednatele."


@pytest.fixture(autouse=True)
def fast_stream(monkeypatch):
    monkeypatch.setattr(endpoints, "SSE_POLL_S", 0.05)


def test_follow_yields_the_timeline_to_its_end_and_a_closed_task_ends_it_at_once(tmp_path):
    served = Served(tmp_path, runner=True)
    with listening(served) as url:
        client = OoatClient(url, secret(served.token()), sleep=lambda seconds: pytest.fail("no reconnect"))
        task = client.submit(project="docs", goal=GOAL, acceptance=CRITERIA)
        events = list(client.follow(task))
        assert events[0]["type"] == "TASK_SUBMITTED" and events[-1]["type"] == "TASK_CLOSED"
        assert len({e["id"] for e in events}) == len(events)
        assert list(client.follow(task, after=events[-1]["id"])) == []  # a bot restarted after the close
        detail = client.task(task)
        assert detail["state"] == "CLOSED_DONE"
        (document,) = detail["result"]["artifacts"]
        assert client.artifact(document).content.decode("utf-8") == served.model.documents[0]


def test_a_token_revoked_while_it_follows_a_task_gets_an_error(tmp_path):
    served = Served(tmp_path, runner=True)
    with listening(served) as url:
        client = OoatClient(url, secret(served.token()))
        task = client.submit(project="docs", goal=GOAL)  # no criteria: the Gate asks, the task waits
        timeline = client.follow(task)
        while next(timeline)["type"] != "HIL_REQUEST":
            pass
        with served.ledger() as ledger:
            (token,) = tokens.tokens(ledger.events(types=tokens.EVENTS))
            tokens.revoke(ledger, operator="operator", token_id=token, reason="leaked")
        with pytest.raises(OoatError) as refused:
            next(timeline)
    assert (refused.value.status, refused.value.code) == (401, "UNAUTHENTICATED")


def test_refusals_reach_the_bot_as_typed_errors(tmp_path):
    served = Served(tmp_path, runner=True)
    with listening(served) as url:
        reader = OoatClient(url, secret(served.token(scopes=("submit", "read"))))
        task = reader.submit(project="docs", goal=GOAL, key="chat-1:7")
        assert reader.submit(project="docs", goal=GOAL, key="chat-1:7") == task
        refusals = []
        for call in (lambda: reader.answer("evt_01J9ZQ70A0K3M5N7P9Q1R3S5T7", choice="run_as_is"),
                     lambda: reader.submit(project="docs", goal="x", data_class="personal"),
                     lambda: reader.task("tsk_01J9ZQ70A0K3M5N7P9Q1R3S5T7")):
            with pytest.raises(OoatError) as refused:
                call()
            refusals.append((refused.value.status, refused.value.code))
    assert refusals == [(403, "SCOPE"), (403, "DATA_CLASS_ABOVE_TOKEN"), (404, "NOT_FOUND")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest sdk/python/tests core/tests/test_client.py -q`
Expected: FAIL with `AttributeError: 'OoatClient' object has no attribute 'follow'`

- [ ] **Step 3: Write `follow`**

In `sdk/python/src/ooat_client/client.py`, replace:

```python
import base64
import ipaddress
```

with:

```python
import base64
import http.client
import ipaddress
```

replace:

```python
from collections.abc import Callable, Sequence
```

with:

```python
from collections.abc import Callable, Iterator, Sequence
```

replace:

```python
DONE_WHEN = ("done when:", "hotovo když:")  # the line after which a chat message lists its acceptance criteria
```

with:

```python
DONE_WHEN = ("done when:", "hotovo když:")  # the line after which a chat message lists its acceptance criteria
CLOSED = frozenset({"CLOSED_DONE", "CLOSED_PARTIAL", "CLOSED_ABSTAINED", "CANCELLED"})
RECONNECT_S, MAX_RECONNECT_S = 1.0, 30.0  # the first wait after a dropped stream; waits double up to the cap
```

replace:

```python
    def questions(self) -> list[dict]:
```

with:

```python
    def follow(self, task: str, after: str | None = None) -> Iterator[dict]:
        """The task's timeline events after `after`, as they happen, until TASK_CLOSED (yielded too).

        After a dropped connection or a busy server (5xx) it reconnects from the last event it yielded, waiting
        1 s, doubling to 30 s; a refusal (4xx) and a token revoked while it reads raise OoatError. A stream the
        server ends (after 15 minutes) is opened again; for a task that is already closed the iteration ends."""
        cursor, wait = after, RECONNECT_S
        while True:
            try:
                headers = {"Accept": "text/event-stream", **({"Last-Event-ID": cursor} if cursor else {})}
                with self._open("GET", f"/tasks/{quote(task)}/events", headers=headers) as response:
                    for message in _sse(response):
                        if message.get("event") == "UNAUTHENTICATED":
                            raise _error(401, message["data"].encode("utf-8"))
                        event = json.loads(message["data"])
                        cursor, wait = event["id"], RECONNECT_S
                        yield event
                        if event["type"] == "TASK_CLOSED":
                            return
                if self.task(task)["state"] in CLOSED:
                    return  # closed at or before the cursor: nothing more will come
                self._sleep(RECONNECT_S)
                continue
            except OoatError as error:
                if error.status < 500:
                    raise
            except (OSError, http.client.HTTPException):  # refused, timed out, dropped
                pass
            self._sleep(wait)
            wait = min(wait * 2, MAX_RECONNECT_S)

    def questions(self) -> list[dict]:
```

and append to the same file:

```python
def _sse(lines) -> Iterator[dict[str, str]]:
    """Server-Sent Events messages from a response's lines; a message cut off by a dropped connection is never
    returned, so the cursor only moves past events that arrived whole."""
    fields: dict[str, str] = {}
    for raw in lines:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if "data" in fields:
                yield fields
            fields = {}
        elif not line.startswith(":"):  # ":" starts the server's keepalive comment
            name, _, value = line.partition(":")
            value = value.removeprefix(" ")
            fields[name] = f"{fields[name]}\n{value}" if name == "data" and name in fields else value
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest sdk/python/tests core/tests/test_client.py -q`
Expected: `15 passed`

Run: `python -m pytest core/tests -q`
Expected: every test passes (the `Served` change keeps `runner=False` as before).

- [ ] **Step 5: Commit**

```bash
git add sdk/python/src/ooat_client/client.py sdk/python/tests/test_ooat_client.py core/tests/api_fakes.py core/tests/test_client.py
git commit -m "feat(sdk): follow a task's timeline with reconnects, tested against ooat serve on a loopback port (plan 05c)"
```

---

### Task 3: The reference chat bridge

**Files:**
- Create: `sdk/python/src/ooat_client/texts.py`, `sdk/python/src/ooat_client/bridge.py`
- Modify: `sdk/python/src/ooat_client/__init__.py`
- Create: `sdk/python/tests/test_ooat_bridge.py`, `core/tests/test_bridge.py`

**Interfaces:**
- Consumes: `OoatClient.submit`, `follow`, `task`, `events`, `questions`, `answer`, `rate`, `cancel`, `artifact`, `stats`, `OoatError`, `parse_message` (Tasks 1, 2); `Served(runner=True)`, `listening`, `wait_for`, `secret` (Task 2).
- Produces (documented in Task 4):
  - `Button(label: str, data: str)`; `Chat` protocol: `id: str`, `send(text: str, buttons: Sequence[Sequence[Button]] = ()) -> str`, `send_file(name: str, content: bytes, caption: str) -> str` (each returns the sent message's id).
  - `Bridge(client: OoatClient, chat: Chat, project: str, *, language: str = "en", limit: int = 4096, max_parts: int = 3)` with `on_message(text, message_id, files=()) -> str` (task id; `ValueError` without a goal), `watch(task, after=None) -> None`, `on_button(data) -> str`, `on_reply(replied_to, text) -> str | None`, `cancel(task) -> str`, `stats(period="7d") -> str`.
  - `ooat_client.bridge.split_text(text, limit) -> list[str]`, `money(usd) -> str`, `count(n) -> str`; `ooat_client.texts.TEXTS: dict[str, dict[str, str]]`.

- [ ] **Step 1: Write the failing tests**

Create `sdk/python/tests/test_ooat_bridge.py`:

```python
"""The bridge's parts that need no server: texts, splitting, numbers, and buttons that call nothing."""

import pytest

from ooat_client import Bridge, OoatClient
from ooat_client.bridge import count, money, split_text
from ooat_client.texts import TEXTS


class Silent:
    """A chat the bridge must not write to."""
    id = "chat-1"

    def send(self, text, buttons=()):
        raise AssertionError(text)

    def send_file(self, name, content, caption):
        raise AssertionError(name)


def offline_bridge(language="en"):
    # Nothing listens on port 9: a call to the API would raise, so these tests prove none is made.
    return Bridge(OoatClient("http://127.0.0.1:9", "secret"), Silent(), "docs", language=language)


def test_both_languages_have_the_same_texts():
    assert TEXTS["en"].keys() == TEXTS["cs"].keys()


def test_long_text_is_split_at_line_breaks_within_the_limit():
    assert split_text("a\nbb\nccc", 4) == ["a\nbb", "ccc"]
    assert split_text("abcdefgh", 3) == ["abc", "def", "gh"]
    assert split_text("short", 4096) == ["short"]
    assert split_text("", 10) == []


def test_money_and_counts_read_as_in_the_web_app():
    assert [money(v) for v in (None, 0, 0.42, 2.6, 0.002, 0.00001)] == ["—", "$0.00", "$0.42", "$2.60", "$0.002",
                                                                        "<$0.0001"]
    assert [count(n) for n in (999, 410_000, 1_500_000)] == ["999", "410k", "1.5M"]


def test_buttons_that_are_not_ours_or_ask_for_text_call_nothing():
    bridge = offline_bridge()
    for data in ("x", "r:tsk_1", "r:tsk_1:D:y", "r:tsk_1:A:maybe"):
        assert bridge.on_button(data) == "This button is not one of OOAT's."
    assert bridge.on_button("a:evt_1:clarify") == "Reply to the question with your text."
    assert offline_bridge("cs").on_button("a:evt_1:narrow_scope") == "Odpovězte na otázku svým textem."
    assert bridge.on_reply("m1", "Nejvýše 300 slov.") is None  # m1 is no question this bridge sent


def test_a_message_needs_a_goal_before_its_criteria():
    with pytest.raises(ValueError):
        offline_bridge().on_message("Done when: at most 300 words", "1")
```

Create `core/tests/test_bridge.py`:

```python
"""The reference chat bridge (sdk/python, design 05 §9) on `ooat serve` with its runner, as a chat sees it."""

import threading

import pytest
from api_fakes import CRITERIA, PERSONAL_GOAL, Served, listening, secret, wait_for

from ooat_client import Bridge, OoatClient
from ooat_core import endpoints

GOAL = "Shrň smlouvu pro jednatele."
PERSONAL_ROUTE = ("public", "internal", "personal")  # the operator enabled the fake model for personal data


class FakeChat:
    """A chat that keeps what the bridge sent; the watch thread writes while the test reads."""

    def __init__(self, id="chat-1"):
        self.id, self.sent, self._lock = id, [], threading.Lock()

    def send(self, text, buttons=()):
        return self._keep({"text": text, "buttons": [list(row) for row in buttons]})

    def send_file(self, name, content, caption):
        return self._keep({"text": caption, "file": name, "content": content, "buttons": []})

    def _keep(self, message):
        with self._lock:
            message["id"] = f"m{len(self.sent) + 1}"
            self.sent.append(message)
            return message["id"]

    def find(self, prefix):
        """The first message with a button whose data starts with `prefix`: "a:" a question, "r:" a result."""
        with self._lock:
            return next((m for m in self.sent if any(b.data.startswith(prefix) for row in m["buttons"]
                                                     for b in row)), None)


def button(message, label):
    return next(b for row in message["buttons"] for b in row if b.label.startswith(label))


def watching(bridge, task):
    watcher = threading.Thread(target=bridge.watch, args=(task,), daemon=True)
    watcher.start()
    return watcher


def finished(watcher):
    watcher.join(30)
    return not watcher.is_alive()


@pytest.fixture(autouse=True)
def fast_stream(monkeypatch):
    monkeypatch.setattr(endpoints, "SSE_POLL_S", 0.05)


def test_a_chat_message_becomes_a_task_with_a_question_a_result_a_rating_and_stats(tmp_path):
    served, chat = Served(tmp_path, runner=True), FakeChat()
    with listening(served) as url:
        bridge = Bridge(OoatClient(url, secret(served.token())), chat, "docs")
        task = bridge.on_message(GOAL, "7")  # no "Done when:" line: the Gate asks (rule A1)
        assert bridge.on_message(GOAL, "7") == task  # the platform delivered the message twice
        watcher = watching(bridge, task)
        question = wait_for(lambda: chat.find("a:"))
        assert question["text"].startswith("? The task has no acceptance criteria")
        assert "UTC: Do not run." in question["text"]  # the deadline and the default on silence
        assert button(question, "Clarify").label.endswith("★")  # the recommended option
        assert bridge.on_button(button(question, "Clarify").data) == "Reply to the question with your text."
        # The watch thread records the question just after the chat returned its id.
        assert wait_for(lambda: bridge.on_reply(question["id"], CRITERIA[0])) == "Answer recorded."
        assert "already answered" in bridge.on_button(button(question, "Run as it is").data)
        assert finished(watcher)
        texts = [m["text"] for m in chat.sent]
        assert "Gate: T0" in texts and f"Answered: {CRITERIA[0]}" in texts and "Working on it (attempt 1)." in texts
        assert served.model.documents[0] in texts
        footer = chat.find("r:")
        assert footer["text"].startswith("CLOSED_DONE · T") and " tokens · " in footer["text"]
        assert bridge.on_button(button(footer, "Accepted B").data) == "Rating saved."
        usage = bridge.stats()
        assert "1 accepted" in usage and "gate" in usage and "prv.fake.api" in usage
    assert all(len(b.data.encode("utf-8")) <= 64 for m in chat.sent for row in m["buttons"] for b in row)
    with served.ledger() as ledger:
        assert len(ledger.events(types=["TASK_SUBMITTED"])) == 1
        (rated,) = ledger.events(types=["TASK_RATED"])
    assert rated["body"]["accepted"] is True and rated["body"]["value_class"] == "B"
    assert rated["body"]["channel"].startswith("token:")


def test_content_above_the_tokens_data_class_never_reaches_the_chat(tmp_path):
    served, chat = Served(tmp_path, classes=PERSONAL_ROUTE, runner=True), FakeChat()
    with listening(served) as url:
        bridge = Bridge(OoatClient(url, secret(served.token(cap="internal"))), chat, "docs")
        task = bridge.on_message(f"{PERSONAL_GOAL}\nDone when:\n- {CRITERIA[0]}", "8")  # the pre-scan finds personal
        watcher = watching(bridge, task)
        question = wait_for(lambda: chat.find("a:"))
        assert question["text"].startswith("? Above this token's data class: open it in the web app.")
        assert [b.label for row in question["buttons"] for b in row] == ["clarify ★", "run_as_is", "do_not_run"]
        assert "above internal" in bridge.on_button(button(question, "run_as_is").data)
        assert "above internal" in bridge.cancel(task)
        web = served.login()
        assert served.client.post(f"/api/v1/tasks/{task}/cancel", headers=web).status_code == 202
        assert finished(watcher)
        assert chat.find("r:")["text"].startswith("CANCELLED")
    shown = " ".join(m["text"] + m.get("content", b"").decode("utf-8", "replace") for m in chat.sent).lower()
    assert "novak" not in shown and "novák" not in shown


def test_cancel_from_the_chat_closes_a_waiting_task_in_czech(tmp_path):
    served, chat = Served(tmp_path, runner=True), FakeChat()
    with listening(served) as url:
        bridge = Bridge(OoatClient(url, secret(served.token())), chat, "docs", language="cs")
        task = bridge.on_message(GOAL, "9")
        watcher = watching(bridge, task)
        question = wait_for(lambda: chat.find("a:"))
        assert "UTC: Do not run." in question["text"] and question["text"].count("Když nikdo neodpoví do ") == 1
        assert bridge.cancel(task) == "Zrušení vyžádáno."
        assert finished(watcher)
        assert chat.find("r:")["text"].startswith("CANCELLED")
        assert button(chat.find("r:"), "Přijato A").data == f"r:{task}:A:y"
        assert bridge.cancel(task) not in ("Zrušení vyžádáno.", "Zrušení už bylo vyžádáno.")  # closed now
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest sdk/python/tests/test_ooat_bridge.py core/tests/test_bridge.py -q`
Expected: FAIL with `ImportError: cannot import name 'Bridge' from 'ooat_client'`

- [ ] **Step 3: Write the texts and the bridge**

Create `sdk/python/src/ooat_client/texts.py`:

```python
"""What the reference bridge writes in a chat, in English and Czech (spec §10). Placeholders in braces; states,
topologies and the server's error messages stay as the API gives them."""

TEXTS = {
    "en": {
        "gate": "Gate: {topology}",
        "working": "Working on it (attempt {n}).",
        "answered": "Answered: {answer}",
        "defaulted": "No answer in time: {answer} applies.",
        "default": "If nobody answers by {deadline}: {option}.",
        "r3": "This needs a named approver: answer it in the web app.",
        "redacted": "Above this token's data class: open it in the web app.",
        "reply_with_text": "Reply to the question with your text.",
        "recorded": "Answer recorded.",
        "rated": "Rating saved.",
        "accepted": "Accepted {value}",
        "rejected": "Not accepted {value}",
        "cancel_requested": "Cancel requested.",
        "cancel_already": "A cancel was already requested.",
        "footer": "{state} · {topology} · {cost} · {tokens_in}/{tokens_out} tokens · {time}",
        "attached": "The result is long, so it is attached.",
        "unknown_button": "This button is not one of OOAT's.",
        "no_goal": "Write what should be done before the \"Done when:\" line.",
        "usage": "Usage, {period}: metered {metered} · subscription shadow {shadow}",
        "by_role": "By role:",
        "by_connector": "By connector:",
        "row": "  {key}: {calls} calls · {tokens_in}/{tokens_out} tokens · {cost}",
        "tasks": "Tasks: {closed} closed · {accepted} accepted · per accepted task {per}",
        "hil": "Questions: {questions} · median wait {wait} · defaults applied {defaults}",
        "minutes": "{n} min",
        "under_a_minute": "under 1 min",
    },
    "cs": {
        "gate": "Gate: {topology}",
        "working": "Pracuji na tom (pokus {n}).",
        "answered": "Odpověď: {answer}",
        "defaulted": "Bez odpovědi včas: platí {answer}.",
        "default": "Když nikdo neodpoví do {deadline}: {option}.",
        "r3": "Tohle potřebuje jmenovitého schvalovatele: odpovězte ve webové aplikaci.",
        "redacted": "Nad datovou třídou tohoto tokenu: otevřete to ve webové aplikaci.",
        "reply_with_text": "Odpovězte na otázku svým textem.",
        "recorded": "Odpověď zaznamenána.",
        "rated": "Hodnocení uloženo.",
        "accepted": "Přijato {value}",
        "rejected": "Nepřijato {value}",
        "cancel_requested": "Zrušení vyžádáno.",
        "cancel_already": "Zrušení už bylo vyžádáno.",
        "footer": "{state} · {topology} · {cost} · {tokens_in}/{tokens_out} tokenů · {time}",
        "attached": "Výsledek je dlouhý, proto je v příloze.",
        "unknown_button": "Tohle tlačítko nepatří OOAT.",
        "no_goal": "Před řádek „Hotovo když:“ napište, co se má udělat.",
        "usage": "Využití, {period}: placené {metered} · stínová hodnota předplatného {shadow}",
        "by_role": "Podle role:",
        "by_connector": "Podle konektoru:",
        "row": "  {key}: {calls} volání · {tokens_in}/{tokens_out} tokenů · {cost}",
        "tasks": "Úlohy: {closed} uzavřeno · {accepted} přijato · na přijatou úlohu {per}",
        "hil": "Otázky: {questions} · medián čekání {wait} · použitých výchozích {defaults}",
        "minutes": "{n} min",
        "under_a_minute": "méně než 1 min",
    },
}
```

Note the Czech test above: `"UTC: Do not run."` is in the Czech question because the option labels come from the
server, in English; only the bridge's own sentence is translated.

Create `sdk/python/src/ooat_client/bridge.py`:

```python
"""A reference chat bridge (design 05 §9): the contract's chat actions on top of OoatClient, for any chat platform.

The bot keeps its own platform code: it receives messages and button presses, sends messages, and checks that a
message comes from its allowed chat or user before it calls the bridge (OOAT trusts the token; the bot vouches for
the person). It gives the bridge a Chat that sends a text with rows of buttons, or a file, and returns the sent
message's id. Methods called on a person's action return the text to show them; `watch` posts on its own.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .client import OoatClient, OoatError, parse_message
from .texts import TEXTS

TEXT_OPTIONS = frozenset({"clarify", "narrow_scope"})  # answered with text: their button asks for a reply
VALUES = ("A", "B", "C")


@dataclass(frozen=True)
class Button:
    label: str
    data: str  # at most 64 bytes (Telegram's callback data); the platform hands it back: pass it to on_button


class Chat(Protocol):
    id: str  # unique per chat on the platform: with a message id it makes the task's idempotency key

    def send(self, text: str, buttons: Sequence[Sequence[Button]] = ()) -> str: ...

    def send_file(self, name: str, content: bytes, caption: str) -> str: ...


def money(usd: float | None) -> str:
    """Dollars as the web app shows them: cents, or the digits that matter below a cent."""
    if usd is None:
        return "—"
    if usd == 0 or abs(usd) >= 0.01:
        return f"${usd:.2f}"
    small = f"{usd:.4f}".rstrip("0")
    return "<$0.0001" if small.endswith(".") else f"${small}"


def count(n: int) -> str:
    """410000 → "410k"."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{round(n / 1000)}k"
    return f"{n / 1_000_000:.1f}M"


def split_text(text: str, limit: int) -> list[str]:
    """Text in parts of at most `limit` characters, cut at the last line break inside the limit when there is one."""
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit + 1)
        cut = cut if cut > 0 else limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts + ([text] if text else [])


def _utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class Bridge:
    """One project's chat. `limit` is the platform's message length, `max_parts` how many messages a result may
    take before it is sent as a file."""

    def __init__(self, client: OoatClient, chat: Chat, project: str, *, language: str = "en", limit: int = 4096,
                 max_parts: int = 3):
        self.client, self.chat, self.project, self.limit, self.max_parts = client, chat, project, limit, max_parts
        self.texts = TEXTS[language]
        self._questions: dict[str, str] = {}  # a question message's id → its request, for answers by reply

    def _t(self, key: str, **values) -> str:
        return self.texts[key].format(**values)

    def _shown(self, value) -> str:
        """A text, or the notice in place of the server's stub for content above the token's data class."""
        return value if isinstance(value, str) else self._t("redacted")

    # A person's actions -------------------------------------------------------------------------------------------

    def on_message(self, text: str, message_id: str, files: Sequence[tuple[str, bytes]] = ()) -> str:
        """A message (with files) becomes a task of the chat's project; the same message delivered again returns the
        same task. Returns the task id: pass it to `watch`."""
        goal, acceptance = parse_message(text)
        if not goal:
            raise ValueError(self._t("no_goal"))
        return self.client.submit(project=self.project, goal=goal, acceptance=acceptance, attachments=files,
                                  key=f"{self.chat.id}:{message_id}")

    def on_button(self, data: str) -> str:
        kind, _, rest = data.partition(":")
        try:
            if kind == "a":
                request, _, choice = rest.partition(":")
                if choice in TEXT_OPTIONS:
                    return self._t("reply_with_text")
                self.client.answer(request, choice=choice)
                return self._t("recorded")
            if kind == "r":
                task, value, accepted = rest.split(":")
                if value in VALUES and accepted in ("y", "n"):
                    self.client.rate(task, accepted=accepted == "y", value_class=value)
                    return self._t("rated")
        except OoatError as error:
            return error.message
        except ValueError:  # data that is not a button of ours
            pass
        return self._t("unknown_button")

    def on_reply(self, replied_to: str, text: str) -> str | None:
        """A reply to a question message answers it with the text; None when the replied message is no question."""
        request = self._questions.get(replied_to)
        if request is None:
            return None
        try:
            self.client.answer(request, text=text)
        except OoatError as error:
            return error.message
        return self._t("recorded")

    def cancel(self, task: str) -> str:
        try:
            asked = self.client.cancel(task)["cancel"]
        except OoatError as error:
            return error.message
        return self._t("cancel_requested" if asked == "requested" else "cancel_already")

    def stats(self, period: str = "7d") -> str:
        """`/stats`: the chat's project, by role and by connector."""
        try:
            by_role = self.client.stats(period=period, project=self.project, group="role")
            by_connector = self.client.stats(period=period, project=self.project, group="connector")
        except OoatError as error:
            return error.message
        spend, tasks, hil = by_role["spend"], by_role["tasks"], by_role["hil"]
        lines = [self._t("usage", period=period, metered=money(spend["metered_usd"]),
                         shadow=money(spend["shadow_usd"]))]
        for heading, usage in (("by_role", by_role), ("by_connector", by_connector)):
            lines.append(self._t(heading))
            lines += [self._t("row", key=g["key"], calls=g["calls"], tokens_in=count(g["tokens_in"]),
                              tokens_out=count(g["tokens_out"]), cost=money(g["metered_usd"] + g["shadow_usd"]))
                      for g in usage["groups"]]
        wait = hil["median_wait_minutes"]
        lines.append(self._t("tasks", closed=tasks["closed"], accepted=tasks["accepted"],
                             per=money(tasks["cost_per_accepted_usd"])))
        lines.append(self._t("hil", questions=hil["questions"], defaults=hil["defaults_applied"],
                             wait="—" if wait is None else self._t("minutes", n=round(wait))))
        return "\n".join(lines)

    # What OOAT does -----------------------------------------------------------------------------------------------

    def watch(self, task: str, after: str | None = None) -> None:
        """Post the task's progress until it is closed: a line per state change, each question with its buttons, then
        the result with its footer and the rating buttons. It blocks: a bot runs it in a thread (`asyncio.to_thread`).
        After a restart, pass the last event it had seen as `after`."""
        attempts = 0
        for event in self.client.follow(task, after):
            kind, body = event["type"], event["body"]
            if "redacted" in body and kind not in ("HIL_REQUEST", "TASK_CLOSED"):
                continue  # above the token's data class: only the question and the result are posted
            if kind == "TOPOLOGY_DECIDED":
                self.chat.send(self._t("gate", topology=body["topology"]))
            elif kind == "CONTRACT_ISSUED":
                attempts += 1
                self.chat.send(self._t("working", n=attempts))
            elif kind == "HIL_REQUEST":
                self._question(event["id"])
            elif kind == "HIL_RESPONSE":
                answer = body.get("choice") or body.get("text", "")
                self.chat.send(self._t("defaulted" if body.get("default_applied") else "answered", answer=answer))
            elif kind == "TASK_CLOSED":
                self._result(task, event)

    def _question(self, request_id: str) -> None:
        request = next((r for r in self.client.questions() if r["request"] == request_id), None)
        if request is None:
            return  # answered meanwhile, or its default applied
        labels = {o["id"]: o["label"] if isinstance(o["label"], str) else o["id"] for o in request["options"]}
        default = labels.get(request["default_on_silence"], request["default_on_silence"])
        deadline = _utc(request["deadline"]).strftime("%Y-%m-%d %H:%M UTC")
        asked, footer = f"? {self._shown(request['question'])}", self._t("default", deadline=deadline, option=default)
        if request["risk_class"] == "R3":  # never answered by a token (ADR 0016): no buttons
            self.chat.send("\n".join([asked, self._t("r3"), footer]))
            return
        buttons = [[Button(labels[o["id"]] + (" ★" if o["id"] == request["recommended"] else "")
                           + (f" · {money(o['cost_usd'])}" if o["cost_usd"] else ""), f"a:{request_id}:{o['id']}")]
                   for o in request["options"]]
        self._questions[self.chat.send(f"{asked}\n{footer}", buttons)] = request_id

    def _result(self, task: str, closed: dict) -> None:
        detail, events = self.client.task(task), self.client.events(task)
        result = detail["result"]
        minutes = (_utc(closed["ts"]) - _utc(detail["submitted"])).total_seconds() / 60
        tokens_in = sum((e["cost"] or {}).get("tokens_in", 0) for e in events)
        tokens_out = sum((e["cost"] or {}).get("tokens_out", 0) for e in events)
        footer = self._t("footer", state=result["state"], topology=detail["topology"] or "—",
                         cost=money(detail["cost_usd"]), tokens_in=count(tokens_in), tokens_out=count(tokens_out),
                         time=self._t("minutes", n=round(minutes)) if minutes >= 1 else self._t("under_a_minute"))
        document = self.client.artifact(result["artifacts"][0]) if result["artifacts"] else None
        if document is None:
            self.chat.send(self._shown(result["summary"]))
        elif document.content is None:
            self.chat.send(self._t("redacted"))
        else:
            self._document(task, document.content)
        self.chat.send(footer, [[Button(self._t("accepted", value=v), f"r:{task}:{v}:y") for v in VALUES],
                                [Button(self._t("rejected", value=v), f"r:{task}:{v}:n") for v in VALUES]])

    def _document(self, task: str, content: bytes) -> None:
        try:
            parts = split_text(content.decode("utf-8"), self.limit)
        except UnicodeDecodeError:
            parts = None
        if parts is None or len(parts) > self.max_parts:
            self.chat.send_file(f"{task}.md" if parts is not None else task, content, self._t("attached"))
            return
        for part in parts:
            self.chat.send(part)
```

In `sdk/python/src/ooat_client/__init__.py`, replace:

```python
from .client import Artifact, OoatClient, OoatError, parse_message

__all__ = ["Artifact", "OoatClient", "OoatError", "parse_message"]
```

with:

```python
from .bridge import Bridge, Button, Chat
from .client import Artifact, OoatClient, OoatError, parse_message

__all__ = ["Artifact", "Bridge", "Button", "Chat", "OoatClient", "OoatError", "parse_message"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest sdk/python/tests core/tests/test_client.py core/tests/test_bridge.py -q`
Expected: `23 passed`

Run: `python -m pytest -q`
Expected: every test passes.

- [ ] **Step 5: Commit**

```bash
git add sdk/python/src/ooat_client/__init__.py sdk/python/src/ooat_client/bridge.py sdk/python/src/ooat_client/texts.py sdk/python/tests/test_ooat_bridge.py core/tests/test_bridge.py
git commit -m "feat(sdk): the reference chat bridge - questions with buttons, results, rating, cancel and /stats in English or Czech (plan 05c)"
```

---

### Task 4: The bridge contract and the docs

**Files:**
- Create: `docs/chat-bridge.md`
- Modify: `docs/description.md`, `README.md`, `.claude/lessons.md`
- Modify: `tasks/f1-skeleton/task-05-operator-ux/design.md` (§9 sketch, Decision 1)

**Interfaces:**
- Consumes: everything of Tasks 1–3, as built.

- [ ] **Step 1: Write the contract**

Create `docs/chat-bridge.md`:

````markdown
# Chat bridge (As-is)

A chat bridge is a bot that holds one OOAT API token and turns chat actions into calls of the REST API of
`ooat serve` (design 05 §9). OOAT ships the Python client `ooat-client` (`sdk/python`, standard library only) with a
reference bridge, `ooat_client.Bridge`, that implements the contract below for any chat platform. The bot stays the
operator's own program: it receives messages and button presses, sends messages, and **checks that a message comes
from its allowed chat or user before it calls the bridge**. OOAT trusts the token; the bot vouches for the person.

## The token

`ooat tokens create --operator NAME --name telegram --scopes submit,read,answer,rate` prints the token once; keep
it in the bot's own secret store, never in code. Its data-class cap is `internal` by default, and stays so for a
chat bridge (owner decision): a chat service stores messages on its own servers. Content of a task above the cap
(client or personal data, also when the pre-scan raises the class) reaches the chat only as a notice to open the
web app, and answering, rating or cancelling such a task from the chat is refused. `ooat tokens revoke` ends the
token at once, also for a timeline the bot is following.

## Contract

| Chat action | `Bridge` | API |
|---|---|---|
| A message (with files) in a project's chat | `on_message(text, message_id, files)` → task id | `POST /tasks` with the chat's project; the text before a `Done when:` (or `Hotovo když:`) line is the `goal`, each line after it a criterion; files as attachments; `Idempotency-Key: <chat id>:<message id>`, so a repeated delivery returns the first task |
| Progress | `watch(task)` | follows `GET /tasks/{id}/events` (Server-Sent Events) and posts one line for the Gate's topology, each attempt and each answer |
| A question | posted by `watch`; `on_button(data)`, `on_reply(message_id, text)` | `GET /hil`: one button per option (★ the recommended one, its cost when it has one), the default on silence and the deadline (UTC) in the text; a button calls `POST /hil/{evt}/answer`; the options answered with text (clarify, narrow the scope) ask for a reply, and a reply to the question answers with its text; an R3 question has no buttons |
| Result | posted by `watch` | the final document as text in up to 3 messages (`limit`, default 4096 characters), else as a file `<task>.md`; a footer: state, topology, cost, tokens in/out, time |
| Rate | the footer's buttons, `on_button(data)` | `POST /tasks/{id}/rating`: `Accepted A/B/C` or `Not accepted A/B/C`; the decisions stay for the web app's rating card |
| `/cancel` | `cancel(task)` | `POST /tasks/{id}/cancel` |
| `/stats` | `stats(period="7d")` | `GET /stats?period=…&project=…`, by role and by connector |

Methods called on a person's action return the text to show them; `watch` posts on its own and returns when the
task is closed. Button data is at most 64 bytes (Telegram's callback-data limit): `a:<request>:<option>` and
`r:<task>:<A|B|C>:<y|n>`. The bridge writes English or Czech (`language="cs"`); option labels, states and the
server's error messages come as the API gives them.

## Minimal use

```python
from ooat_client import Bridge, OoatClient

client = OoatClient("http://127.0.0.1:8765", token)           # token from the bot's secret store
bridge = Bridge(client, chat, project="docs", language="cs")  # chat: id, send(text, buttons), send_file(...)

task = bridge.on_message(text, message_id, files)             # a message from the allowed chat or user
await asyncio.to_thread(bridge.watch, task)                   # progress, questions, the result (it blocks)
await show(bridge.on_button(data))                            # a button press
```

The client is synchronous (standard library only); an async bot runs `watch` in a thread as above. Without the
bridge, `OoatClient` alone has `submit`, `follow` (the timeline until `TASK_CLOSED`), `task`, `events`,
`questions`, `answer`, `rate`, `cancel`, `artifact` and `stats`; a refusal raises `OoatError` with the API's code.

## Network

Plain HTTP only to this machine (`127.0.0.1`, `::1`, `localhost`); beyond it HTTPS (`ooat serve --host` needs TLS).
The client follows no redirects and uses no proxy from the environment, so the token goes to the OOAT server only.
`follow` reconnects after a dropped connection or a busy server (1 s, doubling to 30 s) from the last event it
yielded, and opens the stream again when the server ends it after 15 minutes.

## Restarts

Tasks live in the ledger, not in the bot. After a restart a bot calls `watch(task, after=<last event id it saw>)`
for the tasks it was watching; a task already closed returns at once. Buttons keep working, since they carry the
ids. Replies to questions sent before the restart are not recognised (the bridge keeps question messages in memory):
answer those with the buttons or in the web app.

## What changes for a bot that ran a coding CLI

An OOAT task in F1 turns text into a document. It has no tools (no file edits, no commands) and no conversation
memory (each message is its own task, with clarifications inside the task), and every task pays for the Gate and
the acceptance checks. Add the bridge as one more engine a chat can switch to (`/engine ooat`), next to the direct
CLI, until tool capabilities and sessions exist (owner decision).
````

- [ ] **Step 2: Update the overview, the README and the lessons**

In `docs/description.md`, replace:

```
JavaScript served from the `ooat-core` wheel; the operator needs no Node.
```

with:

```
JavaScript served from the `ooat-core` wheel; the operator needs no Node.

Bots use the Python client `ooat-client` (`sdk/python`, standard library only) and its reference chat bridge: a
chat message becomes a task, questions come with buttons, the result with a rating, and `/stats` shows usage. The
contract is in `docs/chat-bridge.md`.
```

replace:

```
  `node --test` (Node 22, developers and CI only); markdown-it 15.0.2 vendored (plan 05b, ADR 0016)
```

with:

```
  `node --test` (Node 22, developers and CI only); markdown-it 15.0.2 vendored (plan 05b, ADR 0016)
- Python client and reference chat bridge: `ooat-client` in `sdk/python`, standard library only (plan 05c)
```

replace:

```
- `sdk/`, `dashboard/`, `evals/` — empty
```

with:

```
- `sdk/python/` — `ooat-client`: the REST API client and the reference chat bridge (`docs/chat-bridge.md`)
- `dashboard/`, `evals/` — empty
```

replace:

```
`pip install -e core -e adapters/claude-code -e adapters/codex -e adapters/anthropic-api -e adapters/typesafe-jev -e adapters/antigravity-cli`;
```

with:

```
`pip install -e core -e adapters/claude-code -e adapters/codex -e adapters/anthropic-api -e adapters/typesafe-jev -e adapters/antigravity-cli -e sdk/python`;
```

and replace:

```
- `.claude/lessons.md` — gotchas
```

with:

```
- `.claude/lessons.md` — gotchas
- `docs/chat-bridge.md` — the chat bridge contract
```

In `README.md`, replace:

```
| `sdk/` | Python and TypeScript SDKs |
```

with:

```
| `sdk/` | Python client and reference chat bridge (`sdk/python`); TypeScript SDK later |
```

Append to `.claude/lessons.md`:

```
- `urllib` carries an `Authorization` header across a redirect, also to another host, and takes proxies from
  `HTTP_PROXY`/`HTTPS_PROXY`: `ooat_client` builds its opener with `ProxyHandler({})` and a redirect handler that
  refuses, and allows plain `http` only to loopback.
- Tests that need a real HTTP stream (the Python client's `follow`) run the app on uvicorn with a pre-bound socket
  on `127.0.0.1` port 0 (`api_fakes.listening`): `uvicorn.Server.run(sockets=[sock])` in a thread, stopped with
  `should_exit`. `Served(runner=True)` lets the app's lifespan start the runner thread.
```

- [ ] **Step 3: Amend design §9's sketch (Decision 1)**

In `tasks/f1-skeleton/task-05-operator-ux/design.md`, replace:

```python
ooat = OoatClient(base_url, token)              # token from the bot's own secret store, never in code
task = ooat.submit(project=chat_project, goal=text, attachments=files, key=message_id)
async for update in ooat.follow(task):           # state lines, questions, the result
    await reply(render(update))                  # the bot keeps its own message format
```

with:

```python
ooat = OoatClient(base_url, token)              # token from the bot's own secret store, never in code
task = ooat.submit(project=chat_project, goal=text, attachments=files, key=f"{chat_id}:{message_id}")
for update in ooat.follow(task):                 # synchronous (plan 05c): an async bot runs it in a thread
    reply(render(update))                        # the bot keeps its own message format, or uses ooat_client.Bridge
```

- [ ] **Step 4: Run every test**

Run: `python -m pytest -q`
Expected: every test passes, the earlier ones and the 23 new ones.

- [ ] **Step 5: Commit**

```bash
git add docs/chat-bridge.md docs/description.md README.md .claude/lessons.md tasks/f1-skeleton/task-05-operator-ux/design.md
git commit -m "docs: the chat bridge contract and ooat-client (plan 05c)"
```

---

## Self-review against the design

- §9 contract, row by row: message with files, project, "Done when:", idempotency key (Task 1 `submit`,
  `parse_message`; Task 3 `on_message`); progress by following the events as SSE (Task 2 `follow`, Task 3 `watch`);
  questions with buttons, recommended marked, default and deadline, button answers, reply answers with text (Task 3
  `_question`, `on_button`, `on_reply`); result as text split at the limit or as a file, footer with topology, cost,
  tokens, time (Task 3 `_result`, `_document`); rating buttons, decisions left to the web (Task 3); `/stats` (Task 3
  `stats`). `/cancel` from design §13 (Task 3 `cancel`).
- §9 "standard library only", "the bot stays the operator's own program", "the bot must still check …": Global
  Constraints, `bridge.py` docstring, `docs/chat-bridge.md`.
- §9 "what changes for a bot that ran a coding CLI" and §13 "/engine ooat": `docs/chat-bridge.md`.
- §11 05c: client in `sdk/python` (Tasks 1–2), contract in `docs/` (Task 4), reference bridge test (Task 3
  `core/tests/test_bridge.py`); the private bot is not changed here.
- §6 token cap and stubs reach the chat as a notice; writes above the cap refused (Task 3 personal test); R3 without
  buttons (Task 3 `_question`; the server's refusal is tested since 05a).
- §5 error codes reach the bot as `OoatError` (Task 1, Task 2 `test_refusals_reach_the_bot_as_typed_errors`).
- Not in 05c: the private bot's change (its own repository), a TypeScript SDK, push notifications (design §6: the
  bridge pulls), 01c and the R3 binding.
````

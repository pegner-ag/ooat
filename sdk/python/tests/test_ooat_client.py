"""The client on the wire, against a stub server (design 05 §9): what it sends, what it refuses, how it fails."""

import base64
import json
import ssl
import threading
import time
import urllib.error

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
        if cut:  # the connection drops in the middle of a message, inside a two-byte character ("ř")
            handler.wfile.write(b'id: evt_9\nevent: RESULT\ndata: {"id": "evt_9", "goal": "\xc5')
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


def endless(handler):
    """A stream that sends one event, then only keepalives for five seconds."""
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Connection", "close")
    handler.end_headers()
    try:
        handler.wfile.write(f"id: evt_1\nevent: RESULT\ndata: {json.dumps(event('evt_1'))}\n\n".encode())
        for _ in range(100):
            handler.wfile.write(b": keepalive\n\n")
            handler.wfile.flush()
            time.sleep(0.05)
    except OSError:  # the client went away
        pass
    handler.close_connection = True


def test_follow_stops_when_asked_also_while_the_stream_is_idle():
    stop = threading.Event()
    with Stub(endless) as stub:
        client, waits = follower(stub)
        timeline = client.follow("tsk_1", stop=stop)
        assert next(timeline)["id"] == "evt_1"
        stop.set()
        started = time.monotonic()
        assert list(timeline) == []
    assert time.monotonic() - started < 2 and waits == []


def test_a_certificate_that_fails_verification_is_raised_not_retried():
    client = OoatClient("https://ooat.example", "secret", sleep=lambda seconds: pytest.fail("retried"))

    def refuse(request, timeout):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed"))

    client._opener.open = refuse
    with pytest.raises(urllib.error.URLError):
        list(client.follow("tsk_1"))

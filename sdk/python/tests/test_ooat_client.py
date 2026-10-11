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

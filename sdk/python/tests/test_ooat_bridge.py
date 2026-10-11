"""The bridge's parts that need no server, and its watch against a stub server."""

import json
import threading

import pytest
from stub_http import Stub

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
    assert [count(n) for n in (999, 410_000, 999_499, 999_500, 1_500_000)] == ["999", "410k", "999k", "1.0M",
                                                                               "1.5M"]


def test_buttons_that_are_not_ours_or_ask_for_text_call_nothing():
    bridge = offline_bridge()
    for data in ("x", "r:tsk_1", "r:tsk_1:D:y", "r:tsk_1:A:maybe"):
        assert bridge.on_button(data) == "This button is not one of OOAT's."
    assert bridge.on_button("a:evt_1:clarify") == "Reply to the question with your text."
    assert offline_bridge("cs").on_button("a:evt_1:narrow_scope") == "Odpovězte na otázku svým textem."
    assert bridge.on_reply("m1", "Nejvýše 300 slov.") is None  # m1 is no question this bridge sent


def test_a_refusal_while_watching_is_told_in_the_chat():
    class Kept:
        id, sent = "chat-1", []

        def send(self, text, buttons=()):
            self.sent.append(text)
            return f"m{len(self.sent)}"

    missing = {"error": {"code": "NOT_FOUND", "message": "no task tsk_1", "details": None}}
    with Stub((404, missing)) as stub:
        chat = Kept()
        Bridge(OoatClient(stub.url, "secret"), chat, "docs").watch("tsk_1")
    assert chat.sent == ["no task tsk_1"]


def test_a_message_needs_a_goal_before_its_criteria():
    with pytest.raises(ValueError):
        offline_bridge().on_message("Done when: at most 300 words", "1")


QUESTION = {"request": "evt_q", "task": "tsk_1", "asked": "2026-10-11T10:00:00Z", "deadline": "2026-10-13T10:00:00Z",
            "risk_class": None, "blocking": True, "recommended": "run_as_is", "default_on_silence": "do_not_run",
            "question": "Run it?", "options": [{"id": "run_as_is", "cost_usd": 0.0, "acts": True, "label": "Run"},
                                               {"id": "do_not_run", "cost_usd": 0.0, "acts": False, "label": "Stop"}]}


def asked():
    """A stream with the question's HIL_REQUEST, then the server closes it."""
    def reply(handler):
        item = {"id": "evt_q", "ts": "2026-10-11T10:00:00Z", "type": "HIL_REQUEST",
                "actor": {"kind": "runtime", "id": "ooat"}, "refs": [], "cost": None, "body": {}}
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.write(f"id: evt_q\nevent: HIL_REQUEST\ndata: {json.dumps(item)}\n\n".encode())
        handler.close_connection = True
    return reply


def reset(handler):
    handler.close_connection = True  # no reply at all: the client sees the connection reset


class Kept:
    def __init__(self):
        self.id, self.sent = "chat-1", []

    def send(self, text, buttons=()):
        self.sent.append((text, buttons))
        return f"m{len(self.sent)}"


def test_watch_waits_out_a_busy_or_vanished_server_and_still_posts_the_question():
    busy = {"error": {"code": "LEDGER_BUSY", "message": "the ledger is busy", "details": None}}
    waits, chat = [], Kept()
    with Stub(asked(), reset, asked(), (503, busy), asked(), (200, {"requests": [QUESTION]}),
              (200, {"state": "CANCELLED"})) as stub:
        Bridge(OoatClient(stub.url, "secret", sleep=waits.append), chat, "docs").watch("tsk_1")
    assert waits == [1.0, 2.0]
    ((text, buttons),) = chat.sent  # the question once, no "the ledger is busy"
    assert text.startswith("? Run it?") and [b.label for (b,) in buttons] == ["Run ★", "Stop"]


def test_watch_returns_at_once_when_it_is_stopped():
    stop = threading.Event()
    stop.set()
    with Stub() as stub:  # no replies: any request would fail the test
        Bridge(OoatClient(stub.url, "secret"), Silent(), "docs").watch("tsk_1", stop=stop)
    assert stub.requests == []

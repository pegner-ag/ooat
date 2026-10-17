"""The bridge's parts that need no server, and its watch against a stub server."""

import json
import threading

import pytest
from stub_http import Stub

from ooat_client import Bridge, ChatFailed, OoatClient
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
              (200, {"state": "CANCELLED"}), (200, {"events": [], "next": "evt_q"})) as stub:
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


def test_a_chat_that_fails_to_send_is_the_bots_error_not_retried():
    class Broken(Kept):
        def send(self, text, buttons=()):
            raise OSError("the chat platform is down")

    waits = []
    with Stub(asked(), (200, {"requests": [QUESTION]})) as stub:
        with pytest.raises(ChatFailed):
            Bridge(OoatClient(stub.url, "secret", sleep=waits.append), Broken(), "docs").watch("tsk_1")
    assert waits == []


# The reception (plan 08c) --------------------------------------------------------------------------------------

CNV = "cnv_01JZ0000000000000000000001"
MSG1, MSG2, MSG9, TAP1 = (f"evt_01JZ00000000000000000000M{n}" for n in (1, 2, 9, "T"))
EVT3, EVT4, EVT5, EVT6 = (f"evt_01JZ00000000000000000000E{n}" for n in (3, 4, 5, 6))
TSK1, TSK9 = "tsk_01JZ0000000000000000000001", "tsk_01JZ0000000000000000000009"
MEM1, MEM2, MEM3, MEM4 = (f"mem_01JZ000000000000000000000{n}" for n in (1, 2, 3, 4))


class Talk:
    """A chat that keeps each text and its buttons as (label, data) rows."""

    def __init__(self):
        self.id, self.sent, self.buttons = "chat-1", [], []

    def send(self, text, buttons=()):
        self.sent.append(text)
        self.buttons.append([[(b.label, b.data) for b in row] for row in buttons])
        return f"m{len(self.sent)}"


def event(evt, kind, **body):
    return {"id": evt, "ts": "2026-10-16T10:00:00Z", "type": kind,
            "actor": {"kind": "system", "id": "ooat-reception"},
            "refs": [], "cost": None,
            "body": {"conversation": CNV, "project": "docs", "data_class": "internal", **body}}


def decided(evt, messages, decision="answer", reply="Ahoj.", **body):
    return event(evt, "RECEPTION_DECIDED", **{"messages": messages, "decision": decision, "reply": reply,
                                              "options": [], "buttons": [], "context": [], **body})


def report(evt, task, reply="Hotovo.", options=()):
    return event(evt, "CONVERSATION_REPORTED", task=task, reply=reply, options=list(options))


def closed(evt):
    return event(evt, "CONVERSATION_CLOSED", reason="operator")


def sse(*events):
    def reply(handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Connection", "close")
        handler.end_headers()
        for e in events:
            handler.wfile.write(f"id: {e['id']}\nevent: {e['type']}\ndata: {json.dumps(e)}\n\n".encode())
        handler.close_connection = True
    return reply


def bridge_of(stub, chat, language="en", own=()):
    bridge = Bridge(OoatClient(stub.url, "secret"), chat, "docs", language=language)
    bridge.restore({"own_messages": list(own)})
    return bridge


def test_a_message_goes_to_the_reception_with_the_chat_key():
    with Stub((202, {"conversation": CNV, "message": MSG1})) as stub:
        bridge = bridge_of(stub, Talk())
        assert bridge.converse("Změň titulek.", "41") == CNV
    assert stub.requests[0]["path"] == "/api/v1/conversations/messages"
    assert json.loads(stub.requests[0]["body"]) == {"project": "docs", "text": "Změň titulek.", "attachments": []}
    assert stub.requests[0]["headers"]["Idempotency-Key"] == "chat-1:41"
    assert bridge.own_messages == [MSG1] and bridge.last_conversation_event == {CNV: MSG1}


def test_an_empty_message_is_refused_before_any_call():
    with pytest.raises(ValueError):
        offline_bridge().converse("  ", "1")


def test_a_burst_decided_once_is_posted_once_with_numbered_options_and_buttons():
    reply = decided(EVT3, [MSG1, MSG2], "confirm", "Rozumím: změnit titulek. Mám začít?",
                    options=["Jen titulek", "Titulek i podtitulek"], buttons=["yes", "differently"])
    with Stub((202, {"conversation": CNV, "message": MSG1}), (202, {"conversation": CNV, "message": MSG2}),
              sse(reply, closed(EVT4))) as stub:
        chat = Talk()
        bridge = bridge_of(stub, chat, "cs")
        bridge.converse("Změň", "41")
        bridge.converse("titulek", "42")
        bridge.follow(CNV)
    assert stub.requests[2]["headers"]["Last-Event-ID"] == MSG1
    assert chat.sent == ["Rozumím: změnit titulek. Mám začít?\n\n1. Jen titulek\n2. Titulek i podtitulek"]
    assert chat.buttons == [[[("Ano", f"y:{CNV}")], [("Jinak", f"d:{CNV}")]]]
    assert bridge.last_conversation_event == {}  # closed: no cursor kept


def test_another_bots_decision_and_report_and_replaced_calls_are_not_posted():
    with Stub(sse(decided(EVT3, [MSG9], "task", "Dělám na tom.", task=TSK9), report(EVT4, TSK9),
                  decided(EVT5, [MSG1], "escalated"), closed(EVT6))) as stub:
        chat = Talk()
        bridge_of(stub, chat, own=[MSG1]).follow(CNV)
    assert chat.sent == []


def test_a_started_task_goes_to_on_task_and_its_report_is_posted():
    started = []
    with Stub(sse(decided(EVT3, [MSG1], "task", "Dělám na tom.", task=TSK1),
                  report(EVT4, TSK1, "Hotovo: titulek změněn.", ["Zkontrolovat web"]), closed(EVT5))) as stub:
        chat = Talk()
        bridge = bridge_of(stub, chat, own=[MSG1])
        bridge.on_task = started.append
        bridge.follow(CNV)
    assert started == [TSK1] and chat.sent == ["Dělám na tom.", "Hotovo: titulek změněn.\n\n1. Zkontrolovat web"]


def test_a_decision_above_the_cap_is_a_notice_without_buttons():
    stub_reply = {"redacted": "…", "link": f"/conversations/{CNV}"}
    above = decided(EVT3, [MSG1], "confirm", stub_reply, options=stub_reply, buttons=["yes", "differently"])
    with Stub(sse(above, closed(EVT4))) as stub:
        chat = Talk()
        bridge_of(stub, chat, own=[MSG1]).follow(CNV)
    assert chat.sent == [TEXTS["en"]["redacted"]] and chat.buttons == [[]]


def test_a_switch_calls_on_switch_and_posts_why_it_could_not():
    switched = []
    with Stub(sse(decided(EVT3, [MSG1], "switch", "Přepínám na eshop.", switch_to="eshop"), closed(EVT4))) as stub:
        chat = Talk()
        bridge = bridge_of(stub, chat, own=[MSG1])
        bridge.on_switch = lambda slug: switched.append(slug) or "Projekt eshop nemám v seznamu."
        bridge.follow(CNV)
    assert switched == ["eshop"] and chat.sent == ["Přepínám na eshop.", "Projekt eshop nemám v seznamu."]


def test_a_reply_to_a_reception_post_continues_its_conversation():
    with Stub(sse(decided(EVT3, [MSG1], reply="Který web?"), closed(EVT4)),
              (202, {"conversation": CNV, "message": MSG2})) as stub:
        bridge = bridge_of(stub, Talk(), own=[MSG1])
        bridge.follow(CNV)
        bridge.converse("Ten ruský.", "43", replied_to="m1")
    sent = json.loads(stub.requests[1]["body"])
    assert sent["conversation"] == CNV and sent["reply_to"] == EVT3


def test_after_a_restart_the_follow_resumes_at_the_cursor_and_posts_only_what_is_new():
    saved = {"own_messages": [MSG1], "own_tasks": [], "posted": [EVT3], "scopes": {MEM1: "eshop"},
             "last_conversation_event": {CNV: EVT4}}
    with Stub(sse(decided(EVT5, [MSG1], reply="Ještě něco?"), closed(EVT6))) as stub:
        chat = Talk()
        bridge = Bridge(OoatClient(stub.url, "secret"), chat, "docs")
        bridge.restore(json.loads(json.dumps(saved)))
        assert bridge.state() == saved
        bridge.follow(CNV)
    assert stub.requests[0]["headers"]["Last-Event-ID"] == EVT4 and chat.sent == ["Ještě něco?"]


def test_a_yes_tap_posts_its_decision_once_and_starts_the_watch():
    started = decided(EVT5, [TAP1], "task", "Spouštím: změnit titulek", task=TSK1)
    with Stub((200, {"conversation": CNV, "message": TAP1, "decision": started}),
              sse(started, closed(EVT6))) as stub:
        chat, tasks = Talk(), []
        bridge = bridge_of(stub, chat, "cs")
        bridge.on_task = tasks.append
        assert bridge.on_button(f"y:{CNV}") == "Odpověď zaznamenána."
        bridge.follow(CNV)
    assert stub.requests[0]["path"] == f"/api/v1/conversations/{CNV}/taps"
    assert json.loads(stub.requests[0]["body"]) == {"tap": "yes"}
    assert chat.sent == ["Spouštím: změnit titulek"] and tasks == [TSK1]


def test_forget_uses_the_scope_of_the_post_that_showed_the_button():
    noted = decided(EVT3, [MSG1], reply="Hotovo.\n\n🧠 Zapamatováno: titulky bez tečky.", project="eshop",
                    buttons=[f"forget:{MEM1}"], memory=[MEM1])
    with Stub(sse(noted, closed(EVT4)), (200, {"memory": MEM1, "forgotten": True, "event": EVT5}),
              (200, {"memory": MEM2, "event": EVT6})) as stub:
        chat = Talk()
        bridge = bridge_of(stub, chat, own=[MSG1])
        bridge.follow(CNV)
        assert chat.buttons == [[[("Forget", f"f:{MEM1}")]]]
        assert bridge.on_button(f"f:{MEM1}") == "Forgotten."
        assert bridge.on_button(f"x:{MEM2}") == "Marked done."  # unknown item: the chat's own project
    assert (stub.requests[1]["method"], stub.requests[1]["path"]) == ("DELETE", f"/api/v1/memory/eshop/{MEM1}")
    assert (stub.requests[2]["method"], stub.requests[2]["path"]) == ("PATCH", f"/api/v1/memory/docs/{MEM2}")


def test_several_notes_get_numbered_forget_buttons():
    noted = decided(EVT3, [MSG1], buttons=[f"forget:{MEM1}", f"forget:{MEM2}"])
    with Stub(sse(noted, closed(EVT4))) as stub:
        chat = Talk()
        bridge_of(stub, chat, own=[MSG1]).follow(CNV)
    assert chat.buttons == [[[("Forget 1", f"f:{MEM1}")], [("Forget 2", f"f:{MEM2}")]]]


def test_a_command_offers_the_handoff_and_passes_the_own_text_once():
    handed = []
    with Stub((202, {"conversation": CNV, "message": MSG1}),
              sse(decided(EVT3, [MSG1], "command", "Tohle OOAT nespustí.", buttons=["todo"]), closed(EVT4))) as stub:
        chat = Talk()
        bridge = bridge_of(stub, chat, "cs")
        bridge.handoff = handed.append
        bridge.converse("Commitni a pushni to.", "41")
        bridge.follow(CNV)
    assert chat.buttons == [[[("Nechat jako otevřený bod", f"o:{CNV}")], [("Předat: Claude Code", f"k:{EVT3}")]]]
    assert bridge.on_button(f"k:{EVT3}") == "Předáno: Claude Code."
    assert handed == ["Commitni a pushni to."]
    assert bridge.on_button(f"k:{EVT3}") == TEXTS["cs"]["handoff_gone"]


def test_without_a_handoff_a_command_has_no_handoff_button():
    with Stub(sse(decided(EVT3, [MSG1], "command", "Tohle OOAT nespustí.", buttons=["todo"]), closed(EVT4))) as stub:
        chat = Talk()
        bridge_of(stub, chat, own=[MSG1]).follow(CNV)
    assert chat.buttons == [[[("Keep as an open point", f"o:{CNV}")]]]


def test_reception_button_data_fits_telegram():
    for data in (f"y:{CNV}", f"f:{MEM1}", f"k:{EVT3}"):
        assert len(data.encode()) <= 64


def item(mem, kind, text, pinned=False, noted="2026-10-15T10:00:00Z"):
    return {"memory": mem, "scope": "docs", "kind": kind, "data_class": "internal", "text": text, "pinned": pinned,
            "done": False, "noted": noted, "source": None, "conversation": None}


def test_memory_shows_pinned_items_open_points_with_buttons_and_the_last_summary():
    items = [item(MEM1, "fact", "Web běží na IIS.", pinned=True),
             item(MEM2, "todo", "Na konci projektu připomenout zálohu."),
             item(MEM3, "summary", "Starší.", noted="2026-10-14T09:00:00Z"),
             item(MEM4, "summary", "Měnili jsme titulky.")]
    with Stub((200, {"scope": "docs", "items": items})) as stub:
        chat = Talk()
        assert bridge_of(stub, chat, "cs").show_memory() is None
    assert chat.sent == ["📌 Připnuté:\n• Web běží na IIS.\n\nOtevřené body:\n1. Na konci projektu připomenout "
                         "zálohu.\n\nMinule: Měnili jsme titulky."]
    assert chat.buttons == [[[("Hotovo ✓ 1", f"x:{MEM2}"), ("Zapomenout 1", f"f:{MEM2}")]]]


def test_empty_memory_says_so():
    with Stub((200, {"scope": "docs", "items": []})) as stub:
        chat = Talk()
        bridge_of(stub, chat).show_memory()
    assert chat.sent == ["Project docs has nothing in its memory yet."]


def test_a_tapped_decision_is_not_posted_again_after_a_restart():
    started = decided(EVT5, [TAP1], "task", "Spouštím.", task=TSK1)
    with Stub((200, {"conversation": CNV, "message": TAP1, "decision": started})) as stub:
        chat = Talk()
        bridge = bridge_of(stub, chat)
        bridge.on_button(f"y:{CNV}")
        saved = json.loads(json.dumps(bridge.state()))  # the bot stops before the stream brought the decision
    with Stub(sse(started, closed(EVT6))) as stub:
        again = Bridge(OoatClient(stub.url, "secret"), Talk(), "docs")
        again.restore(saved)
        again.follow(CNV)
    assert chat.sent == ["Spouštím."] and again.chat.sent == []


def test_a_memory_button_keeps_its_scope_across_a_restart():
    with Stub((200, {"memory": MEM1, "event": EVT5})) as stub:
        bridge = bridge_of(stub, Talk())
        bridge.restore({"scopes": {MEM1: "eshop"}})
        bridge.on_button(f"x:{MEM1}")
    assert stub.requests[0]["path"] == f"/api/v1/memory/eshop/{MEM1}"


def test_many_conversations_at_once_share_the_bridge_safely():
    bridge = offline_bridge()
    bridge.chat = Talk()

    def post(n):
        for i in range(300):
            evt = f"evt_{n}_{i}"
            bridge._reply(decided(evt, [MSG1], buttons=[f"forget:mem_{n}_{i}"]))
            bridge._claim(evt)

    threads = [threading.Thread(target=post, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(bridge._sent) <= 500 and len(bridge._posted) <= 500 and len(bridge._scope) <= 500

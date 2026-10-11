"""The bridge's parts that need no server: texts, splitting, numbers, and buttons that call nothing."""

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

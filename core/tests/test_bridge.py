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
        # A restarted bot goes on from the last event the bridge handled: nothing is posted twice.
        posted, last = len(chat.sent), bridge.last_event[task]
        Bridge(OoatClient(url, secret(served.token())), chat, "docs").watch(task, after=last)
        assert len(chat.sent) == posted
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


# The project workspace in the chat (plan 07c) --------------------------------------------------------------------

from runtime_fakes import WorkspaceModel  # noqa: E402

from ooat_core.config import parse_config  # noqa: E402

ORIGINAL = b"def main():\n    return 1\n"
EDIT = [("read_file", {"path": "Bots/src/bot.py"}),
        ("edit_file", {"path": "Bots/src/bot.py", "old": "return 1", "new": "return 2"})]
TASK_TEXT = f"Oprav bot.\nDone when:\n{CRITERIA[0]}"


def project(tmp_path, tools, classes=("public", "internal"), **settings):
    root = tmp_path / "Bots"
    (root / "src").mkdir(parents=True)
    (root / "src" / "bot.py").write_bytes(ORIGINAL)
    config = parse_config({"projects": {"bots": {"folders": [str(root)], "write": True, **settings}}})
    return root, Served(tmp_path, model=WorkspaceModel(tools), config=config, runner=True, classes=classes)


def test_a_result_brings_the_diff_and_a_revert_that_needs_a_second_tap(tmp_path):
    root, served = project(tmp_path, [EDIT])
    chat = FakeChat()
    with listening(served) as url:
        bridge = Bridge(OoatClient(url, secret(served.token())), chat, "bots")
        task = bridge.on_message(TASK_TEXT, "1")
        assert finished(watching(bridge, task))
        (diff,) = [m for m in chat.sent if m.get("file") == f"{task}.diff"]
        assert b"+    return 2" in diff["content"]
        footer = chat.find("v:")
        assert bridge.on_button(button(footer, "Revert").data) == "Confirm below."
        assert root.joinpath("src", "bot.py").read_bytes() != ORIGINAL  # one tap writes nothing
        confirm = chat.find("V:")
        assert bridge.on_button(button(confirm, "Yes, revert").data) == "Reverted: the details are below."
        assert chat.sent[-1]["text"].startswith("Restored 1, skipped 0")
        assert root.joinpath("src", "bot.py").read_bytes() == ORIGINAL


def test_the_limit_question_comes_with_the_document_and_its_revert_asks_again(tmp_path):
    root, served = project(tmp_path, [EDIT + [("read_file", {"path": "Bots/src/bot.py"})]], max_operations=2)
    chat = FakeChat()
    with listening(served) as url:
        bridge = Bridge(OoatClient(url, secret(served.token())), chat, "bots")
        task = bridge.on_message(TASK_TEXT, "1")
        watcher = watching(bridge, task)
        question = wait_for(lambda: chat.find("a:"))
        assert any("Files changed (recorded by OOAT)" in m["text"] for m in chat.sent)  # the limited document first
        assert [m for m in chat.sent if m.get("file") == f"{task}.diff"]
        assert len(question["buttons"]) == 4
        assert bridge.on_button(button(question, "Revert").data) == "Confirm below."
        assert root.joinpath("src", "bot.py").read_bytes() != ORIGINAL
        assert bridge.on_button(button(chat.find("c:"), "Yes, revert").data) == "Answer recorded."
        assert finished(watcher)
        assert root.joinpath("src", "bot.py").read_bytes() == ORIGINAL


def test_a_project_without_folders_is_told_once(tmp_path):
    served, chat = Served(tmp_path, runner=True), FakeChat()
    with listening(served) as url:
        bridge = Bridge(OoatClient(url, secret(served.token())), chat, "docs")
        bridge.on_message(f"{GOAL}\nDone when:\n{CRITERIA[0]}", "1")
        bridge.on_message(f"{GOAL}\nDone when:\n{CRITERIA[0]}", "2")
    assert len([m for m in chat.sent if "no folders in OOAT" in m["text"]]) == 1


def test_a_workspace_above_the_tokens_class_posts_no_diff_and_no_revert(tmp_path):
    root, served = project(tmp_path, [EDIT])  # an internal project, watched with a token capped at public
    chat = FakeChat()
    with listening(served) as url:
        session = served.login()  # the web session submits it; the chat only watches
        task = served.submit(session, project="bots", acceptance=CRITERIA)["task"]
        bridge = Bridge(OoatClient(url, secret(served.token(cap="public"))), chat, "bots")
        assert finished(watching(bridge, task))
    assert not [m for m in chat.sent if m.get("file", "").endswith(".diff")] and not chat.find("v:")


def test_a_revert_that_skips_a_file_shows_it_in_the_chat(tmp_path):
    root, served = project(tmp_path, [EDIT])
    chat = FakeChat()
    with listening(served) as url:
        bridge = Bridge(OoatClient(url, secret(served.token())), chat, "bots")
        task = bridge.on_message(TASK_TEXT, "1")
        assert finished(watching(bridge, task))
        bridge.on_button(button(chat.find("v:"), "Revert").data)
        root.joinpath("src", "bot.py").write_bytes(b"changed by hand\n")
        answer = bridge.on_button(button(chat.find("V:"), "Yes, revert").data)
        assert len(answer) <= 200  # a callback answer (toast) on Telegram
        assert any("Skipped Bots/src/bot.py: changed since the task" in m["text"] for m in chat.sent)


def test_a_limit_question_answered_revert_shows_what_was_skipped_and_no_second_diff(tmp_path):
    root, served = project(tmp_path, [EDIT + [("read_file", {"path": "Bots/src/bot.py"})]], max_operations=2)
    chat = FakeChat()
    with listening(served) as url:
        bridge = Bridge(OoatClient(url, secret(served.token())), chat, "bots")
        task = bridge.on_message(TASK_TEXT, "1")
        watcher = watching(bridge, task)
        question = wait_for(lambda: chat.find("a:"))
        root.joinpath("src", "bot.py").write_bytes(b"changed by hand\n")
        bridge.on_button(button(question, "Revert").data)
        bridge.on_button(button(chat.find("c:"), "Yes, revert").data)
        assert finished(watcher)
    assert any("Skipped Bots/src/bot.py: changed since the task" in m["text"] for m in chat.sent)
    assert len([m for m in chat.sent if m.get("file") == f"{task}.diff"]) == 1  # only before the question


def test_a_chat_that_fails_on_the_notice_still_gets_the_task(tmp_path):
    class Failing(FakeChat):
        def send(self, text, buttons=()):
            if "no folders" in text:
                raise OSError("the platform is down")
            return super().send(text, buttons)

    served = Served(tmp_path, runner=True)
    with listening(served) as url:
        bridge = Bridge(OoatClient(url, secret(served.token())), Failing(), "docs")
        assert bridge.on_message(f"{GOAL}\nDone when:\n{CRITERIA[0]}", "1").startswith("tsk_")

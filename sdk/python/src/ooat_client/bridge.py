"""A reference chat bridge (design 05 §9): the contract's chat actions on top of OoatClient, for any chat platform.

The bot keeps its own platform code: it receives messages and button presses, sends messages, and checks that a
message comes from its allowed chat or user before it calls the bridge (OOAT trusts the token; the bot vouches for
the person). It gives the bridge a Chat that sends a text with rows of buttons, or a file, and returns the sent
message's id. Methods called on a person's action return the text to show them; `watch` posts on its own.
"""

import http.client
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .client import MAX_RECONNECT_S, RECONNECT_S, OoatClient, OoatError, parse_message, retryable
from .texts import TEXTS

TEXT_OPTIONS = frozenset({"clarify", "narrow_scope"})  # answered with text: their button asks for a reply
VALUES = ("A", "B", "C")
TAPS = {"y": "yes", "d": "differently", "n": "new_thing", "t": "make_task", "o": "todo"}  # button data → tap
CODES = {tap: code for code, tap in TAPS.items()}
REPLACED = frozenset({"escalated", "retried"})  # decisions the next call replaced: never posted
OWN_KEPT = 500  # how many own message and task ids a bridge keeps (and a bot stores across restarts)


@dataclass(frozen=True)
class Button:
    label: str
    data: str  # at most 64 bytes (Telegram's callback data); the platform hands it back: pass it to on_button


class ChatFailed(Exception):
    """The chat platform failed to send: the bot's own error, which `watch` raises instead of retrying it."""


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
    if n < 999_500:  # rounds to 1000k and above: millions
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


def _trim(kept: dict) -> None:
    """The newest OWN_KEPT entries of a dict that grows in insertion order."""
    for key in list(kept)[:-OWN_KEPT]:
        del kept[key]


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
        self.last_event: dict[str, str] = {}  # task → the last event `watch` handled: keep it for a restart
        self._told_text_only = False  # the notice for a project without folders goes out once
        # The reception (design 08 §9): the bot's callbacks are attributes; see docs/chat-bridge.md.
        self.on_task: Callable[[str], None] | None = None  # a task a decision started: watch it
        self.on_switch: Callable[[str], str | None] | None = None  # a project to switch to; a text when it cannot
        self.handoff: Callable[[str], None] | None = None  # a command's text, handed to the bot's other engine
        self.handoff_name = "Claude Code"
        self.own_messages: list[str] = []  # message and tap ids this bridge sent, newest last
        self.own_tasks: list[str] = []  # tasks the decisions on them started
        self.last_conversation_event: dict[str, str] = {}  # conversation → the last event `follow` handled
        self._posted: dict[str, None] = {}  # decisions and reports posted, oldest first (a tap's comes twice)
        self._guard = threading.RLock()  # the state above and below: one follow thread per conversation shares it
        self._sent: dict[str, tuple[str, str]] = {}  # a posted message's id → (conversation, event), for replies
        self._texts: dict[str, str] = {}  # own message id → its text, for a handoff
        self._said: dict[str, str] = {}  # a command decision → the text a handoff passes on
        self._scope: dict[str, str] = {}  # memory item → its scope, from the post that showed its button

    def _t(self, name: str, **values) -> str:
        return self.texts[name].format(**values)

    def _send(self, text: str, buttons: Sequence[Sequence[Button]] = ()) -> str:
        try:
            return self.chat.send(text, buttons)
        except Exception as error:  # an OSError here is the platform's, not the OOAT server's: never retried
            raise ChatFailed(str(error)) from error

    def _send_file(self, name: str, content: bytes, caption: str) -> str:
        try:
            return self.chat.send_file(name, content, caption)
        except Exception as error:
            raise ChatFailed(str(error)) from error

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
        task = self.client.submit(project=self.project, goal=goal, acceptance=acceptance, attachments=files,
                                  key=f"{self.chat.id}:{message_id}")
        if not self._told_text_only:  # the project is the bridge's own: one look tells for every task
            try:
                plain = self.client.task(task).get("workspace") is None
                self._told_text_only = True
                if plain:
                    self._send(self._t("no_folders", project=self.project))
            except (OoatError, ChatFailed):
                pass  # the task exists: never lose its id for a notice
        return task

    def converse(self, text: str, message_id: str, files: Sequence[tuple[str, bytes]] = (),
                 replied_to: str | None = None) -> str:
        """A message (with files) to the reception of the chat's project; a reply to one of the reception's posts
        continues its conversation. The same message delivered again is the same message. Returns the
        conversation id: pass it to `follow`."""
        if not text.strip():
            raise ValueError(self._t("no_text"))
        conversation, reply_to = self._sent.get(replied_to, (None, None)) if replied_to else (None, None)
        sent = self.client.send_message(project=self.project, text=text, conversation=conversation,
                                        reply_to=reply_to, attachments=files, key=f"{self.chat.id}:{message_id}")
        conversation, message = sent["conversation"], sent["message"]
        with self._guard:
            self._own(self.own_messages, message)
            self._texts[message] = text
            fresh = conversation not in self.last_conversation_event
        if fresh:  # replies come after it; earlier ones were posted
            self.last_conversation_event[conversation] = message
        return conversation

    def on_button(self, data: str) -> str:
        kind, _, rest = data.partition(":")
        try:
            if kind in TAPS and rest:
                result = self.client.tap(rest, TAPS[kind])
                with self._guard:
                    self._own(self.own_messages, result["message"])
                if result.get("decision") is not None:
                    self._decided(result["decision"])
                return self._t("recorded")
            if kind == "f" and rest:
                self.client.forget(self._scope.get(rest, self.project), rest)
                return self._t("forgotten")
            if kind == "x" and rest:
                self.client.done(self._scope.get(rest, self.project), rest)
                return self._t("marked_done")
            if kind == "k" and rest:
                said = self._said.pop(rest, None)
                if self.handoff is None or said is None:
                    return self._t("handoff_gone")
                self.handoff(said)
                return self._t("handed", engine=self.handoff_name)
            if kind == "a" and rest.endswith(":revert"):  # writing files back takes a second tap (design 07 §12)
                self._send(self._t("revert_confirm"), [[Button(self._t("revert_yes"), f"c:{rest[:-len(':revert')]}")]])
                return self._t("confirm_below")
            if kind == "c":
                self.client.answer(rest, choice="revert")
                return self._t("recorded")
            if kind == "v":
                self._send(self._t("revert_confirm"), [[Button(self._t("revert_yes"), f"V:{rest}")]])
                return self._t("confirm_below")
            if kind == "V":
                result = self.client.revert(rest)
                # The report goes out as a message: a button's answer may be shown as a short toast (200 characters).
                self._send(self._revert_report(len(result["restored"]), result["skipped"], len(result["kept"])))
                return self._t("revert_done")
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

    def show_memory(self) -> str | None:
        """`/pamet`: the project's pinned items, its open points with Done and Forget, and the last summary, posted;
        returns the server's refusal as text, else None."""
        try:
            items = self.client.memory(self.project)
        except OoatError as error:
            return error.message
        said = lambda item: item["text"] if isinstance(item["text"], str) else self._t("redacted")  # noqa: E731
        pinned = [i for i in items if i["pinned"] and i["kind"] != "todo"]
        todos = sorted((i for i in items if i["kind"] == "todo" and not i["done"]), key=lambda i: i["noted"])
        summaries = sorted((i for i in items if i["kind"] == "summary"), key=lambda i: i["noted"])
        parts, rows = [], []
        if pinned:
            parts.append("\n".join([self._t("mem_pinned"), *(f"• {said(i)}" for i in pinned)]))
        if todos:
            shown = todos[:10]
            lines = [self._t("mem_todos"), *(f"{n}. {said(i)}" for n, i in enumerate(shown, 1))]
            if len(todos) > len(shown):
                lines.append(self._t("mem_more", n=len(todos) - len(shown)))
            parts.append("\n".join(lines))
            for n, i in enumerate(shown, 1):
                with self._guard:
                    self._scope[i["memory"]] = i["scope"]
                    _trim(self._scope)
                rows.append([Button(self._t("b_done_n", n=n), f"x:{i['memory']}"),
                             Button(self._t("b_forget_n", n=n), f"f:{i['memory']}")])
        if summaries:
            parts.append(self._t("mem_summary", text=said(summaries[-1])))
        self._post_parts("\n\n".join(parts) or self._t("mem_empty", project=self.project), rows)
        return None

    def state(self) -> dict:
        """What a bot keeps across a restart for `follow` and the memory buttons: its own ids, what it posted, each
        conversation's cursor and each memory button's scope."""
        with self._guard:
            return {"own_messages": list(self.own_messages), "own_tasks": list(self.own_tasks),
                    "posted": list(self._posted), "scopes": dict(self._scope),
                    "last_conversation_event": dict(self.last_conversation_event)}

    def restore(self, state: dict) -> None:
        with self._guard:
            for name in ("own_messages", "own_tasks"):
                getattr(self, name)[:] = [i for i in state.get(name, []) if isinstance(i, str)][-OWN_KEPT:]
            self._posted.update(dict.fromkeys(i for i in state.get("posted", []) if isinstance(i, str)))
            self._scope.update({m: s for m, s in state.get("scopes", {}).items() if isinstance(s, str)})
            _trim(self._posted)
            _trim(self._scope)
            cursors = state.get("last_conversation_event", {})
        self.last_conversation_event.update({c: e for c, e in cursors.items() if isinstance(e, str)})

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

    def watch(self, task: str, after: str | None = None, stop: threading.Event | None = None) -> None:
        """Post the task's progress until it is closed: a line per state change, each question with its buttons, then
        the result with its footer and the rating buttons. It blocks: a bot runs it in a thread (`asyncio.to_thread`).
        After a restart, pass the task's `last_event` as `after`. A refusal (a revoked token, say) is told in the
        chat and ends the watch; a busy or vanished server is waited out. Set `stop` to end it on shutdown."""
        attempts, wait = 0, RECONNECT_S
        while not (stop and stop.is_set()):
            try:
                for event in self.client.follow(task, self.last_event.get(task, after), stop):
                    counted = attempts + (event["type"] == "CONTRACT_ISSUED")
                    self._post(task, event, counted)
                    attempts, wait, self.last_event[task] = counted, RECONNECT_S, event["id"]
                return
            except (OoatError, OSError, http.client.HTTPException) as error:
                if not retryable(error):
                    self._send(error.message if isinstance(error, OoatError) else str(error))
                    return
            # The server went busy or away while an event was posted: post it again once it is back.
            self.client.pause(wait, stop)
            wait = min(wait * 2, MAX_RECONNECT_S)

    def follow(self, conversation: str, stop: threading.Event | None = None) -> None:
        """Post the reception's replies to this bridge's messages until the conversation is closed: each decision
        with its numbered options and buttons, and the report of each task they started. A started task goes to
        `on_task`, a project switch to `on_switch`. It blocks: a bot runs it in a thread. Retries as `watch` does."""
        wait = RECONNECT_S
        while not (stop and stop.is_set()):
            try:
                cursor = self.last_conversation_event.get(conversation)
                for event in self.client.follow_conversation(conversation, cursor, stop):
                    self._converse_post(event)
                    wait, self.last_conversation_event[conversation] = RECONNECT_S, event["id"]
                if not (stop and stop.is_set()):
                    self.last_conversation_event.pop(conversation, None)  # closed: nothing more comes
                return
            except (OoatError, OSError, http.client.HTTPException) as error:
                if not retryable(error):
                    self._send(error.message if isinstance(error, OoatError) else str(error))
                    return
            self.client.pause(wait, stop)
            wait = min(wait * 2, MAX_RECONNECT_S)

    def _converse_post(self, event: dict) -> None:
        kind, body = event["type"], event["body"]
        if kind == "RECEPTION_DECIDED":
            if body["decision"] not in REPLACED and set(body["messages"]) & set(self.own_messages):
                self._decided(event)
        elif kind == "CONVERSATION_REPORTED" and body.get("task") in self.own_tasks and self._claim(event["id"]):
            self._reply(event)

    def _claim(self, event_id: str) -> bool:
        """True for the first caller only: a tap's decision comes in its response and on the stream."""
        with self._guard:
            if event_id in self._posted:
                return False
            self._posted[event_id] = None
            _trim(self._posted)
            return True

    def _decided(self, event: dict) -> None:
        if not self._claim(event["id"]):
            return
        body = event["body"]
        self._reply(event)
        if body.get("task") and body["decision"] in ("task", "continue_task"):
            with self._guard:
                self._own(self.own_tasks, body["task"])
            if self.on_task is not None:
                self.on_task(body["task"])
        if body.get("switch_to") and self.on_switch is not None:
            said = self.on_switch(body["switch_to"])
            if said:
                self._send(said)

    def _reply(self, event: dict) -> None:
        """A decision or a report: its reply, its numbered options and its buttons; the notice above the cap."""
        body, evt = event["body"], event["id"]
        reply, options = body.get("reply"), body.get("options")
        if not isinstance(reply, str):
            text, rows = self._t("redacted"), []
        else:
            numbered = [f"{n}. {o}" for n, o in enumerate(options, 1)] if isinstance(options, list) else []
            text = "\n\n".join([reply, "\n".join(numbered)]) if numbered else reply
            rows = self._buttons(body, evt)
        sent = self._post_parts(text, rows)
        with self._guard:
            self._sent.update(dict.fromkeys(sent, (body["conversation"], evt)))
            _trim(self._sent)

    def _buttons(self, body: dict, evt: str) -> list[list[Button]]:
        with self._guard:
            return self._buttons_of(body, evt)

    def _buttons_of(self, body: dict, evt: str) -> list[list[Button]]:
        cnv, taps = body["conversation"], body.get("buttons", [])
        forgets = [b for b in taps if b.startswith("forget:")]
        rows = []
        for tap in taps:
            kind, _, mem = tap.partition(":")
            if mem:
                self._scope[mem] = body["project"]
                _trim(self._scope)
                several = len(forgets) > 1 and kind == "forget"
                label = self._t("b_forget_n", n=forgets.index(tap) + 1) if several else self._t(f"b_{kind}")
                rows.append([Button(label, f"{'f' if kind == 'forget' else 'x'}:{mem}")])
            elif tap in CODES:
                rows.append([Button(self._t(f"b_{tap}"), f"{CODES[tap]}:{cnv}")])
        if body.get("decision") == "command" and self.handoff is not None:
            said = [self._texts[m] for m in body["messages"] if m in self._texts]
            if said:
                self._said[evt] = "\n\n".join(said)
                rows.append([Button(self._t("b_handoff", engine=self.handoff_name), f"k:{evt}")])
        return rows

    def _post_parts(self, text: str, rows: Sequence[Sequence[Button]]) -> list[str]:
        """The text in parts of the chat's limit, the buttons on the last; the ids of the messages sent."""
        parts = split_text(text, self.limit) or [text]
        return [self._send(part, rows if n == len(parts) - 1 else ()) for n, part in enumerate(parts)]

    def _own(self, kept: list[str], item: str) -> None:
        """Keep an own id (with self._guard held)."""
        if item not in kept:
            kept.append(item)
        for dropped in kept[:-OWN_KEPT]:
            self._texts.pop(dropped, None)
        del kept[:-OWN_KEPT]

    def _post(self, task: str, event: dict, attempts: int) -> None:
        kind, body = event["type"], event["body"]
        if "redacted" in body and kind not in ("HIL_REQUEST", "TASK_CLOSED"):
            return  # above the token's data class: only the question and the result are posted
        if kind == "TOPOLOGY_DECIDED":
            self._send(self._t("gate", topology=body["topology"]))
        elif kind == "CONTRACT_ISSUED":
            self._send(self._t("working", n=attempts))
        elif kind == "HIL_REQUEST":
            self._question(event["id"])
        elif kind == "HIL_RESPONSE":
            answer = body.get("choice") or body.get("text", "")
            self._send(self._t("defaulted" if body.get("default_applied") else "answered", answer=answer))
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
        if any(o["id"] == "raise_limit" for o in request["options"]):  # the question quotes none of the work
            self._limited_work(request["task"])
        if request["risk_class"] == "R3":  # never answered by a token (ADR 0016): no buttons
            self._send("\n".join([asked, self._t("r3"), footer]))
            return
        buttons = [[Button(labels[o["id"]] + (" ★" if o["id"] == request["recommended"] else "")
                           + (f" · {money(o['cost_usd'])}" if o["cost_usd"] else ""), f"a:{request_id}:{o['id']}")]
                   for o in request["options"]]
        self._questions[self._send(f"{asked}\n{footer}", buttons)] = request_id

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
            self._send(self._shown(result["summary"]))
        elif document.content is None:
            self._send(self._t("redacted"))
        else:
            self._document(task, document.content)
        workspace = detail.get("workspace")
        if isinstance(workspace, dict) and isinstance(workspace.get("reverted"), dict):  # what came back, not the diff
            reverted = workspace["reverted"]
            self._send(self._revert_report(len(reverted["restored"]), reverted["skipped"], len(reverted["kept"])))
        else:
            self._diff(task, detail)
        rows = [[Button(self._t("accepted", value=v), f"r:{task}:{v}:y") for v in VALUES],
                [Button(self._t("rejected", value=v), f"r:{task}:{v}:n") for v in VALUES]]
        if isinstance(workspace, dict) and workspace.get("revertable"):  # next to "not accepted" (design 07 §7)
            rows.append([Button(self._t("revert"), f"v:{task}")])
        self._send(footer, rows)

    def _revert_report(self, restored: int, skipped: list[dict], kept: int) -> str:
        return "\n".join([self._t("reverted", restored=restored, skipped=len(skipped), kept=kept)]
                         + [self._t("skipped", path=s["path"], reason=s["reason"]) for s in skipped])

    def _limited_work(self, task: str) -> None:
        """What the agent did before its limit, as OOAT recorded it: the document and the diff, each only within the
        token's data class."""
        detail = self.client.task(task)
        docs = [a for a in detail["artifacts"] if a["type"] == "markdown_document"]
        if docs:
            document = self.client.artifact(docs[-1]["ref"])
            if document.content is None:
                self._send(self._t("redacted"))
            else:
                self._document(task, document.content)
        self._diff(task, detail)

    def _diff(self, task: str, detail: dict) -> None:
        workspace = detail.get("workspace")
        if not isinstance(workspace, dict) or "redacted" in workspace or not workspace.get("diff"):
            return
        diff = self.client.artifact(workspace["diff"])
        if diff.content is not None:
            self._send_file(f"{task}.diff", diff.content, self._t("diff"))

    def _document(self, task: str, content: bytes) -> None:
        try:
            parts = split_text(content.decode("utf-8"), self.limit)
        except UnicodeDecodeError:
            parts = None
        if parts is None or len(parts) > self.max_parts:
            self._send_file(f"{task}.md" if parts is not None else task, content, self._t("attached"))
            return
        for part in parts:
            self._send(part)

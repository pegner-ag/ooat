"""A reference chat bridge (design 05 §9): the contract's chat actions on top of OoatClient, for any chat platform.

The bot keeps its own platform code: it receives messages and button presses, sends messages, and checks that a
message comes from its allowed chat or user before it calls the bridge (OOAT trusts the token; the bot vouches for
the person). It gives the bridge a Chat that sends a text with rows of buttons, or a file, and returns the sent
message's id. Methods called on a person's action return the text to show them; `watch` posts on its own.
"""

import http.client
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .client import MAX_RECONNECT_S, RECONNECT_S, OoatClient, OoatError, parse_message, retryable
from .texts import TEXTS

TEXT_OPTIONS = frozenset({"clarify", "narrow_scope"})  # answered with text: their button asks for a reply
VALUES = ("A", "B", "C")


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

    def on_button(self, data: str) -> str:
        kind, _, rest = data.partition(":")
        try:
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

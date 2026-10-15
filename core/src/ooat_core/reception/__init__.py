"""The reception: a person's messages become answers, questions or tasks (design 08 §4, ADR 0018).

`receive` records a message, `decide` decides every undecided message of a conversation with one model call and
acts on it, `tap` applies a button at once. The model proposes; the rules here decide what happens: a `Done when:`
line wins, R2 and R3 are always confirmed and never lowered, below θ a decision is tried once more on the workhorse
tier and then confirmed, after two questions in a row the reception starts on its best reading, a `command` never
becomes a task, and a failed reception sends the message as a task. Tasks go through `Runtime.submit` and then the
Gate as before; answers to a task's question go through `hil.answer`.
"""

import threading
from collections.abc import Callable
from datetime import datetime, timezone

from .. import conversations, hil, memory
from ..config import Project, ReceptionSettings
from ..connector_admin import checked_operator
from ..gateway import GatewayError
from ..ids import new_id
from ..ledger import DuplicateIntake, new_event
from ..pii import higher_class, raised_class
from ..runtime import CLOSED, Runtime, TaskClosed, attachment_text
from ..state import task_state
from . import context as reception_context
from . import model

ACTOR = {"kind": "system", "id": "ooat-reception"}
_SLUG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-")
DONE_WHEN = ("done when:", "hotovo když:", "hotovo kdyz:")
TEXT_OPTIONS = ("clarify", "narrow_scope")  # a task's question answered with the person's words (ADR 0009)
CZECH = frozenset("áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ")
PREVIEW_CHARS = 1000


class UnknownConversation(ValueError):
    """No such conversation of this operator."""


def split_done_when(text: str) -> tuple[str, list[str]]:
    """The text before a `Done when:` (or `Hotovo když:`) line is the goal, each line after it a criterion."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        marker = next((m for m in DONE_WHEN if line.strip().lower().startswith(m)), None)
        if marker is not None:
            criteria = (c.strip().lstrip("-*").strip() for c in [line.strip()[len(marker):], *lines[i + 1:]])
            return "\n".join(lines[:i]).strip(), [c for c in criteria if c]
    return text.strip(), []


def czech(text: str) -> bool:
    return any(c in CZECH for c in text)


def say(text: str, cs: str, en: str) -> str:
    """One of OOAT's own lines in the person's language."""
    return cs if czech(text) else en


class Reception:
    def __init__(self, runtime: Runtime, store: memory.MemoryStore | None, settings: ReceptionSettings = ReceptionSettings(),
                 projects: dict[str, Project] | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 on_task: Callable[[str], None] = lambda task: None):
        self.runtime, self.ledger, self.gateway = runtime, runtime.ledger, runtime.gateway
        self.store, self.settings, self.clock, self.on_task = store, settings, clock, on_task
        self.projects = projects if projects is not None else (
            runtime.workspaces.config.projects if runtime.workspaces is not None else {})
        self._deciding = threading.Lock()

    # Messages and taps ------------------------------------------------------------------------------------------

    def receive(self, *, operator: str, project: str, channel: str, text: str, conversation: str | None = None,
                reply_to: str | None = None, files: list[bytes] = (), file_names: list[str] = (),
                intake_key: str | None = None) -> dict:
        """Record a message (CONVERSATION_MESSAGE) in the open conversation of the operator, project and channel, or
        in a new one; returns the event. A repeated intake key returns the first message."""
        operator = checked_operator(operator)
        text = text.strip()
        if not text:
            raise ValueError("a message needs a text")
        if not project or not set(project) <= _SLUG_CHARS or len(project) > 64:
            raise ValueError("a project is lower-case letters, digits, - and _")
        events = self.ledger.events(types=list(conversations.TYPES))
        known = conversations.conversations(events)
        if conversation is not None:
            found = known.get(conversation)
            if found is None or found.operator != operator:
                raise UnknownConversation(f"no conversation {conversation}")
            if found.closed is not None or found.project != project or found.channel != channel:
                conversation = None  # a reply to a closed conversation, or from elsewhere, starts a new one
        if conversation is None:
            found = conversations.open_for(events, operator=operator, project=project, channel=channel,
                                           now=self.clock(), silence_hours=self.settings.silence_hours)
            conversation = found.id if found is not None else new_id("cnv")
        if file_names and len(file_names) != len(files):
            raise ValueError("give one file name per attachment")
        texts = [attachment_text(content) for content in files]
        settings = self.projects.get(project)
        declared = settings.data_class if settings is not None else "internal"
        names = list(file_names) or [f"attachment-{n}.txt" for n in range(1, len(texts) + 1)]
        data_class = raised_class(declared, "\n".join([text, *names, *texts]))
        staged = [self.runtime.artifacts.stage(t.encode("utf-8"), artifact_type="attachment", untrusted=True,
                                               data_class=raised_class(declared, f"{n}\n{t}"))
                  for n, t in zip(names, texts)]
        body = {"conversation": conversation, "project": project, "channel": channel, "text": text,
                "data_class": data_class}
        if reply_to is not None:
            body["reply_to"] = reply_to
        if intake_key is not None:
            body["intake_key"] = intake_key
        if files:
            body["attachment_names"] = names
        try:
            return self.ledger.append(new_event("CONVERSATION_MESSAGE", task=None, actor={"kind": "hil", "id": operator},
                                                refs=[s.ref for s in staged], body=body), staged)
        except DuplicateIntake as repeated:
            return repeated.earlier

    def tap(self, conversation: str, tap: str, *, operator: str, channel: str, text: str | None = None) -> dict:
        """A button pressed in the conversation; returns the tap's CONVERSATION_MESSAGE and the decision it caused
        ({"message": …, "decision": … or None}). A Differently with a correction is decided like a message, later."""
        operator = checked_operator(operator)
        events = self.ledger.events()
        found = conversations.conversations(events).get(conversation)
        if found is None or found.operator != operator:
            raise UnknownConversation(f"no conversation {conversation}")
        if found.closed is not None:
            raise ValueError("this conversation is closed; write a new message")
        own = conversations.events_of(events, conversation)
        text = (text or "").strip() or None
        body = {"conversation": conversation, "project": found.project, "channel": channel, "tap": tap,
                "data_class": raised_class(self._class(found.project), text or "")}
        if text is not None:
            body["tap_text"] = text
        message = self.ledger.append(new_event("CONVERSATION_MESSAGE", task=None,
                                               actor={"kind": "hil", "id": operator}, body=body))
        if tap == "differently" and text is not None:
            return {"message": message, "decision": None}
        return {"message": message, "decision": self._apply_tap(found, own, message, tap, operator, channel)}

    def _apply_tap(self, found, own, message, tap, operator, channel) -> dict:
        last = conversations.last_decision(own)
        said = " ".join(conversations.message_text(e) or "" for e in own if e["type"] == "CONVERSATION_MESSAGE")
        reply = lambda cs, en: say(said, cs, en)  # noqa: E731
        decided = {"conversation": found.id, "project": found.project, "messages": [message["id"]], "options": [],
                   "buttons": [], "context": [], "data_class": message["body"]["data_class"]}
        if tap in ("yes", "new_thing"):
            pending = conversations.pending(own) if tap == "yes" else self._new_thing(own)
            if pending is None:
                raise ValueError("there is nothing to start")
            if tap == "new_thing":
                pending = {k: v for k, v in pending.items() if k != "follows"}
            task = self._start(found, pending, operator, channel, f"tap:{message['id']}", last)
            decided |= {"decision": "task", "task": task, "reply": reply(f"Spouštím: {pending['goal'][:300]}",
                                                                       f"Starting: {pending['goal'][:300]}")}
        elif tap == "differently":
            decided |= {"decision": "ask", "reply": reply("Napište, jak to myslíte.", "Write how you mean it.")}
        elif tap == "make_task":
            if last is None:
                raise ValueError("there is nothing to make a task of")
            asked = [e for e in own if e["id"] in last["body"]["messages"]]
            goal, acceptance = split_done_when("\n\n".join(conversations.message_text(e) or "" for e in asked))
            task = self._start(found, {"goal": goal, "acceptance": acceptance}, operator, channel,
                               f"tap:{message['id']}", last)
            decided |= {"decision": "task", "task": task, "reply": reply(f"Spouštím jako úkol: {goal[:300]}",
                                                                       f"Starting it as a task: {goal[:300]}")}
        elif tap == "todo":
            if last is None or self.store is None:
                raise ValueError("there is nothing to keep")
            text = last["body"].get("interpretation") or " ".join(
                conversations.message_text(e) or "" for e in own if e["id"] in last["body"]["messages"])
            item = memory.note(self.ledger, self.store, scope=found.project, kind="todo", text=text,
                               data_class=message["body"]["data_class"], source=message["id"],
                               actor={"kind": "hil", "id": operator}, conversation=found.id, channel=channel)
            decided |= {"decision": "answer", "memory": [item.id], "buttons": [f"done:{item.id}", f"forget:{item.id}"],
                        "reply": reply(f"🧠 Otevřený bod: {item.text}", f"🧠 Open point: {item.text}")}
        elif tap.startswith(("forget:", "done:")):
            kind, mem_id = tap.split(":", 1)
            self._own_item(found.project, mem_id)
            if self.store is None:
                raise memory.UnknownMemory(f"no memory item {mem_id}")
            if kind == "forget":
                memory.forget(self.ledger, self.store, mem_id, operator=operator, channel=channel)
                decided |= {"decision": "forget", "reply": reply("Zapomenuto.", "Forgotten.")}
            else:
                memory.edit(self.ledger, self.store, mem_id, operator=operator, channel=channel, done=True)
                decided |= {"decision": "answer", "reply": reply("Odškrtnuto.", "Marked done.")}
        else:
            raise ValueError(f"unknown tap {tap}")
        return self.ledger.append(new_event("RECEPTION_DECIDED", task=None, actor=ACTOR, body=decided))

    def _new_thing(self, own: list[dict]) -> dict | None:
        pending = conversations.pending(own)
        if pending is not None:
            return pending
        last = conversations.last_decision(own)
        if last is not None and last["body"].get("interpretation"):
            return {"goal": last["body"]["interpretation"]}
        return None

    def _own_item(self, project: str, mem_id: str) -> dict:
        noted = memory.find(self.ledger.events(types=memory.EVENTS), mem_id)
        if noted is None or noted["body"]["scope"] not in (project, memory.OPERATOR_SCOPE):
            raise memory.UnknownMemory(f"no memory item {mem_id}")
        return noted

    # Deciding ---------------------------------------------------------------------------------------------------

    def theta(self, engine: str, model_version: str) -> float:
        from ..thresholds import reception_threshold
        return reception_threshold(self.ledger.events(), engine, model_version, self.settings.theta)

    def decide(self, conversation: str) -> dict | None:
        """Decide every undecided message of the conversation as one request and act on it; returns the final
        RECEPTION_DECIDED, or None when nothing waits. One decision at a time per process."""
        with self._deciding:
            events = self.ledger.events()
            own = conversations.events_of(events, conversation)
            waiting = conversations.undecided(own)
            if not waiting:
                return None
            found = conversations.conversations(events)[conversation]
            data_class = self._class(found.project)
            for message in waiting:
                data_class = higher_class(data_class, message["body"]["data_class"])
                for ref in message["refs"]:
                    data_class = higher_class(data_class, self.ledger.artifact(ref)["data_class"])
            said = self._messages(waiting)
            context = reception_context.gather(
                events=events, store=self.store, workspaces=self.runtime.workspaces, operator=found.operator,
                project=found.project, conversation=conversation, data_class=data_class,
                projects=sorted(self.projects), budget_tokens=self.settings.context_tokens)
            base = {"conversation": conversation, "project": found.project, "messages": [m["id"] for m in waiting],
                    "context": context.ids, "data_class": data_class}
            called = self._ask(base, context.text, said, data_class)
            if called is None:
                return self._fallback(found, waiting, base, said)
            decision = called.data
            theta = self.theta(called.engine, called.model)
            if decision["decision"] in ("task", "continue_task") and decision["confidence"] < theta:
                self._record(base | {"decision": "escalated", "options": [], "buttons": []},
                             called, theta)
                stronger = self._ask(base, context.text, said, data_class, tier=model.ESCALATION_TIER)
                if stronger is not None:
                    called, decision = stronger, stronger.data
                    theta = self.theta(called.engine, called.model)
            final = self._act(found, own, waiting, said, decision, theta, data_class)
            event = self._record(base | final, called, theta)
            for task in final.get("cancelled", []):  # a started or answered task was queued when it was
                self.on_task(task)
            if final["decision"] == "switch":
                self.ledger.append(new_event("CONVERSATION_CLOSED", task=None, actor=ACTOR, body={
                    "conversation": conversation, "project": found.project, "reason": "switched"}))
            return event

    def _ask(self, base: dict, context: str, said: str, data_class: str, tier: str = model.DECISION_TIER):
        """The decision call, once more after an unusable reply; None when the reception cannot decide. Every call
        that was charged and not used is recorded with its cost."""
        for attempt in (1, 2):
            try:
                return model.decide_call(self.gateway, tier=tier, context=context, messages=said,
                                         conversation=base["conversation"], data_class=data_class)
            except model.Unusable as unusable:
                self._record(base | {"decision": "retried", "options": [], "buttons": []}, None, None,
                             cost=unusable.cost)
            except GatewayError as error:
                if error.cost is not None and error.cost.get("usd"):
                    self._record(base | {"decision": "retried", "options": [], "buttons": []}, None, None,
                                 cost=error.cost)
                return None
        return None

    def _record(self, body: dict, called, theta, cost: dict | None = None) -> dict:
        body = {k: v for k, v in body.items() if v is not None}
        if called is not None and theta is not None:
            body["record"] = {"engine": called.engine, "model": called.model,
                              "confidence": float(called.data["confidence"]), "threshold": theta}
        return self.ledger.append(new_event("RECEPTION_DECIDED", task=None, actor=ACTOR, body=body,
                                            cost=cost if called is None else called.cost))

    def _messages(self, waiting: list[dict]) -> str:
        parts = []
        for message in waiting:
            parts.append(conversations.message_text(message))
            names = message["body"].get("attachment_names", [])
            for ref, name in zip(message["refs"], names):
                preview = self.runtime.artifacts.read(ref).decode("utf-8", "replace")
                parts.append(f"[attachment {name}, first {PREVIEW_CHARS} characters]\n{preview[:PREVIEW_CHARS]}")
        return "\n\n".join(parts)

    def _class(self, project: str) -> str:
        settings = self.projects.get(project)
        return settings.data_class if settings is not None else "internal"

    def _fallback(self, found, waiting, base, said) -> dict:
        """The reception could not decide: the message goes as a task, as the chat bridge sent it before 08."""
        goal, acceptance = split_done_when(said)
        operator = waiting[-1]["actor"]["id"]
        task = self._start(found, {"goal": goal or said, "acceptance": acceptance}, operator,
                           waiting[-1]["body"]["channel"], f"reception:{waiting[0]['id']}", None,
                           files_from=waiting)
        return self._record(base | {
            "decision": "task", "task": task, "fallback": True, "options": [], "buttons": [],
            "reply": say(said, "Recepce teď není dostupná, poslal jsem zprávu jako úkol.",
                         "The reception is not available now; I sent the message as a task.")}, None, None)

    def _act(self, found, own, waiting, said, decision, theta, data_class) -> dict:
        """The design's rules on the model's decision, then the action; returns the body of the final decision."""
        kind = decision["decision"]
        reply = decision["reply"].strip()
        options = [o.strip() for o in decision.get("options", []) if o.strip()]
        goal, written = split_done_when(said)
        acceptance = written or decision.get("acceptance", [])  # a Done when: line wins (rule 3)
        goal = decision.get("goal") or goal or said
        risk = decision.get("risk_hint")
        raises = risk if risk in ("R2", "R3") else None  # passed on only to raise; never to lower (rule 2)
        operator, channel = waiting[-1]["actor"]["id"], waiting[-1]["body"]["channel"]
        key = f"reception:{waiting[0]['id']}"
        result = {"decision": kind, "reply": reply, "options": options, "buttons": []}
        if decision.get("interpretation"):
            result["interpretation"] = decision["interpretation"].strip()

        if kind == "switch":
            if decision["project"] not in self.projects or decision["project"] == found.project:
                names = [p for p in sorted(self.projects) if p != found.project][:9]
                return result | {"decision": "ask", "options": names, "reply": say(
                    said, "Na který projekt mám přepnout?", "Which project shall I switch to?")}
            return result | {"switch_to": decision["project"]}
        target = decision.get("task")
        if kind == "continue_task" and not self._task_of(found, target):
            kind = "task" if decision.get("goal") else "ask"
            result["decision"] = kind
        if kind in ("task", "continue_task") and (raises or decision["confidence"] < theta):
            pending = {"goal": goal, "acceptance": acceptance} | ({"risk_class": raises} if raises else {})
            if kind == "continue_task":
                pending["follows"] = target
            interpretation = result.get("interpretation") or goal
            question = say(said, f"Rozumím tomu jako: {interpretation[:500]}\nMám začít?",
                           f"I understand it as: {interpretation[:500]}\nShall I start?")
            buttons = ["yes", "differently"] + (["new_thing"] if kind == "continue_task" else [])
            return result | {"decision": "confirm", "pending": pending, "buttons": buttons,
                             "reply": reply if reply.endswith("?") else question}
        if kind in ("ask", "confirm") and conversations.questions_in_a_row(own) >= 2 and not raises:
            # Rule 1: after two questions in a row the reception starts on its best reading.
            interpretation = result.get("interpretation") or goal
            task = self._start(found, {"goal": goal, "acceptance": acceptance}, operator, channel, key, None,
                               files_from=waiting)
            return result | {"decision": "task", "task": task, "options": [], "reply": say(
                said, f"Začínám podle toho, jak tomu rozumím: {interpretation[:500]}",
                f"Starting on how I understand it: {interpretation[:500]}")}
        if kind == "confirm":
            pending = {"goal": goal, "acceptance": acceptance} | ({"risk_class": raises} if raises else {})
            return result | {"pending": pending, "buttons": ["yes", "differently"]}
        if kind == "task":
            task = self._start(found, {"goal": goal, "acceptance": acceptance}, operator, channel, key, None,
                               files_from=waiting)
            result |= {"task": task}
        elif kind == "continue_task":
            result |= self._continue(found, target, said, goal, acceptance, operator, channel, key, waiting)
        elif kind == "cancel":
            cancelled = []
            for task in conversations.tasks_of(self.ledger.events(types=["TASK_SUBMITTED"]), found.id):
                try:
                    if self.runtime.cancel(task, operator=operator, channel=channel):
                        cancelled.append(task)
                except TaskClosed:
                    continue
            result |= {"cancelled": cancelled} if cancelled else {
                "reply": say(said, "Nic neběží, není co zastavit.", "Nothing is running; there is nothing to stop.")}
        elif kind == "command":
            result["buttons"] = ["todo"]
        elif kind == "forget":
            try:
                self._own_item(found.project, decision["memory"])
                result["buttons"] = [f"forget:{decision['memory']}"]
            except memory.UnknownMemory:
                result |= {"decision": "answer", "reply": say(said, "Takovou položku paměti nemám.",
                                                              "I have no such memory item.")}
        notes = self._notes(found, waiting, decision.get("memory_notes", []), data_class)
        if notes:
            lines, kept = notes
            result["reply"] = "\n\n".join([result["reply"], *lines])
            if kept:
                result["memory"] = kept
                result["buttons"] = [*result["buttons"], *(f"forget:{m}" for m in kept)][:12]
        return result

    def _notes(self, found, waiting, notes, data_class) -> tuple[list[str], list[str]] | None:
        if not notes or self.store is None:
            return None
        lines, kept = [], []
        for item in notes[:3]:
            scope = memory.OPERATOR_SCOPE if item.get("scope") == "operator" and item["kind"] == "preference" \
                else found.project
            try:
                noted = memory.note(self.ledger, self.store, scope=scope, kind=item["kind"], text=item["text"],
                                    data_class=data_class, source=waiting[0]["id"], actor=ACTOR,
                                    conversation=found.id)
            except memory.SecretRefused as refused:
                lines.append(f"🧠 {refused}")
                continue
            except ValueError:  # e.g. twenty preferences already: the decision stands without the note
                continue
            kept.append(noted.id)
            lines.append(f"🧠 {noted.text}")
        return lines, kept

    def _task_of(self, found, task: str | None) -> bool:
        if not task:
            return False
        submitted = self.ledger.events(task=task, types=["TASK_SUBMITTED"])
        return bool(submitted) and (submitted[0]["body"].get("conversation") == found.id
                                    or submitted[0]["body"].get("project") == found.project)

    def _continue(self, found, target, said, goal, acceptance, operator, channel, key, waiting) -> dict:
        """An answer to the task's open question when it takes text; else a follow-up task (plan 08a decision 6)."""
        events = self.ledger.events(task=target)
        if task_state(events) not in CLOSED:
            answered = {e["body"]["request"] for e in events if e["type"] == "HIL_RESPONSE"}
            for request in reversed([e for e in events if e["type"] == "HIL_REQUEST" and e["id"] not in answered]):
                choice = next((o["id"] for o in request["body"]["options"] if o["id"] in TEXT_OPTIONS), None)
                if choice is not None and request["body"].get("risk_class") != "R3":
                    hil.answer(self.ledger, self.runtime, request["id"], operator=operator, choice=choice, text=said,
                               channel=channel)
                    self.on_task(target)
                    return {"task": target}
        task = self._start(found, {"goal": goal, "acceptance": acceptance, "follows": target}, operator, channel,
                           key, None, files_from=waiting)
        return {"task": task}

    def _start(self, found, pending: dict, operator: str, channel: str, key: str, last, files_from=()) -> str:
        """Submit a task for the conversation; the intake key makes a repeated decision return the same task."""
        files, names = [], []
        for message in files_from:
            for ref, name in zip(message["refs"], message["body"].get("attachment_names", [])):
                files.append(self.runtime.artifacts.read(ref))
                names.append(name)
        follows = pending.get("follows")
        if follows is not None:
            closed = self.ledger.events(task=follows, types=["TASK_CLOSED"])
            documents = closed[-1]["body"].get("artifacts", []) if closed else []
            if documents:
                files.append(self.runtime.artifacts.read(documents[0]))
                names.append("previous-task.md")
        if last is not None and last["body"].get("messages"):
            for message in self.ledger.events(types=["CONVERSATION_MESSAGE"]):
                if message["id"] in last["body"]["messages"]:
                    for ref, name in zip(message["refs"], message["body"].get("attachment_names", [])):
                        files.append(self.runtime.artifacts.read(ref))
                        names.append(name)
        task = self.runtime.submit(operator=operator, goal=pending["goal"], acceptance=pending.get("acceptance", []),
                                   project=found.project, risk_class=pending.get("risk_class"), files=files,
                                   file_names=names, channel=channel, intake_key=key, follows=follows,
                                   conversation=found.id)
        self.on_task(task)
        return task

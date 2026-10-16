# The Chat Bridge Talks to the Reception (08c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The reference chat bridge `ooat_client.Bridge` sends a chat message to the reception, not as a task, and
posts what comes back. That covers the reply with its numbered options and buttons, the progress of the task it
started, and the report when that task closes. The new buttons work, and `/pamet` shows the project's memory. The
Telegram bot's side is its own task-04 (`TelegramBOTs/tasks/telegrambots/task-04-ooat-reception/plan.md`).

**Architecture:** Changes are confined to `sdk/python/src/ooat_client/bridge.py` and `texts.py`.
- `Bridge.converse` sends a message.
- `Bridge.follow` posts one conversation's replies until it closes. It hands each started task to `on_task`, so the
  bot watches it as today with `watch`.
- `on_button` learns the reception's buttons.
- `show_memory` posts pinned items, open points and the last summary.

The REST API of 08a is used as it is: no server change.

**Tech Stack:** Python 3.12+ standard library (the client has no dependency), pytest with the stub HTTP server of
`sdk/python/tests/stub_http.py`.

**Spec:** `tasks/f1-skeleton/task-08-reception/design.md` §8, §9 (chat bridge), §14; `docs/chat-bridge.md` (the
contract this plan extends); ADR 0016 (tokens, caps), ADR 0018.

## Global Constraints

- The bridge only calls the REST API with its token. It never builds an event, and never calls a model.
- Button data is at most 64 bytes (Telegram's callback-data limit). Existing codes (`a:`, `r:`, `v:`, `V:`, `c:`)
  keep their meaning.
- Content above the token's data class reaches the chat only as the notice `redacted`. Such a reply gets no buttons,
  and a decision, report or memory item above the cap is never quoted.
- A person's action returns the text to show. Only `converse` raises (`OoatError`, `ValueError` for an empty
  message), as `on_message` does. `follow` posts on its own and raises `ChatFailed` when the chat fails.
- The bridge never runs anything itself. Handing a `command` to another engine is the bot's callback, started only
  by a person's tap.
- English and Czech texts have the same keys (`test_both_languages_have_the_same_texts`).
- `on_message` (one task per message) stays for bots without the reception. `docs/chat-bridge.md` says which to use.
- No new dependency. Lines are at most 120 characters. Code, comments, docs and commits are in English.
- Explicit git paths in every commit, never `git add -A`.

**Decisions this plan takes where the design is silent** (for the owner's review):

1. **A bridge posts only its own conversation events.** The owner's three bots share one token and one private chat
   id, so two bots in the same project write into one conversation, since a conversation is per operator, project
   and channel. Each bridge keeps:
   - the ids of the messages and taps it sent (`own_messages`);
   - the tasks their decisions started (`own_tasks`).

   It posts a `RECEPTION_DECIDED` only when one of its `messages` is its own. It posts a `CONVERSATION_REPORTED`
   only for its own task. The bot keeps both sets across restarts, together with the cursor.
2. **Forget and Done use the memory endpoints, not taps.** They are `f:<mem>` and `x:<mem>`, as the design names
   them. The scope comes from the reply that showed the button (the decision's `project`), or from the chat's
   current project after a restart. A button then keeps working after its conversation has closed, which a tap
   would not.
3. **A `command` decision gets a "Hand to <engine>" button** (`k:<evt>`), but only when the bot gives the bridge a
   handoff. The tap passes the text of the bridge's own messages behind that decision to the bot's callback. The
   texts are kept in memory only. After a restart the button says to send the message again.
4. **Numbered options are text**, appended to the reply as `1. …`. The person answers with "2" or "1/ yes 2/ no".
   No buttons per option: the reception understands the number (rule 8), and a typed answer can carry more.
5. **A reply to a reception message continues it.** The bridge maps each message it posted to its conversation
   and event, and sends a reply with `conversation` and `reply_to`. The map lives in memory. After a restart a reply
   is an ordinary message, which goes into the open conversation anyway.
6. **Progress of a started task is posted as today** (Gate line, attempts, questions, result, diff, rating). The
   reception's report follows as its own message with numbered options. Wishlist item 1 (one message edited in
   place) stays out.
7. **The bridge starts following after the message it sent.** A new follow passes the sent message's id as the
   cursor, so earlier replies in a conversation the bridge joins are not posted again.

## Review Focus

- A burst within the quiet window (two messages, one decision whose `messages` holds both) is posted once.
- A tap's decision comes back in the tap's response and also on the stream. It is posted once, whichever comes
  first.
- A restart in the middle of a conversation posts nothing twice: the cursor and both "own" sets are restored.
- A decision above the token's cap posts the notice, without buttons, numbered options or memory lines.
- A `switch` decision posts the reply, calls `on_switch`, and the follow ends with `CONVERSATION_CLOSED`. The next
  message goes to the new project's conversation.

Each line has its test in the task that owns the code: lines 1, 4 and 5 in task 1, line 2 in task 2, and line 3 in
task 1 (`state`/`restore`).

---

## File Structure

| File | Responsibility |
| --- | --- |
| `sdk/python/src/ooat_client/bridge.py` (modify) | `converse`, `follow`, `_reply`, the new buttons, `show_memory`, `state`/`restore` |
| `sdk/python/src/ooat_client/texts.py` (modify) | button labels, memory headings, handoff texts (en, cs) |
| `sdk/python/tests/test_ooat_bridge.py` (modify) | the tests below, against `Stub` |
| `docs/chat-bridge.md` (modify) | the contract: conversation rows, new button data, `/pamet`, restart |
| `sdk/python/README.md` (modify) | one paragraph on `converse`/`follow` |

### Task 1: Messages to the reception and their replies

**Files:**
- Modify: `sdk/python/src/ooat_client/bridge.py`, `sdk/python/src/ooat_client/texts.py`
- Test: `sdk/python/tests/test_ooat_bridge.py`

**Interfaces:**
- Consumes: `OoatClient.send_message(project, text, conversation, reply_to, attachments, key) -> {conversation,
  message}` and `OoatClient.follow_conversation(conversation, after, stop) -> Iterator[event]`. Both are in
  `client.py` already.
- Produces:
  - `Bridge.converse(text, message_id, files=(), replied_to=None) -> str`, which returns the conversation id.
  - `Bridge.follow(conversation, stop=None) -> None`.
  - Attributes:
    - `on_task: Callable[[str], None] | None`;
    - `on_switch: Callable[[str], str | None] | None`, which returns a text to post when the switch could not be
      applied;
    - `handoff: Callable[[str], None] | None`, with `handoff_name: str` (default `"Claude Code"`).
  - `Bridge.last_conversation_event: dict[str, str]`, which is the cursor per conversation.
  - `Bridge.state() -> dict` and `Bridge.restore(state: dict) -> None`, for `own_messages`, `own_tasks` and
    `last_conversation_event`, with the own sets capped at the last 500 ids.

What `follow` posts, per event of the stream:

| Event | Posted when | What |
| --- | --- | --- |
| `CONVERSATION_MESSAGE` | never | the person's own words |
| `RECEPTION_DECIDED` with decision `escalated` or `retried` | never | replaced by the next call |
| `RECEPTION_DECIDED` | one of `body.messages` is in `own_messages`, and its id is not in `_posted` | `_reply(event)`; then, if `body.task` and the decision is `task` or `continue_task`: `own_tasks.add`, `on_task(task)`; if `switch_to`: `on_switch(switch_to)`, posting its text when not None |
| `CONVERSATION_REPORTED` | `body.task` in `own_tasks` | `_reply(event)` |
| `CONVERSATION_CLOSED` | never | `follow` returns |

`_reply(event)` builds the post:
- The text is `body.reply`, followed by a blank line and `1. …` per option.
- `body.reply` may be the server's stub (a dict). Then the text is `texts.redacted`, with no options and no buttons.
- The text is split with `split_text(text, self.limit)`, and the buttons go on the last part.
- Each button gets its own row, in the order of `body.buttons`:

  | Tap | Label key | Data |
  | --- | --- | --- |
  | `yes` | `b_yes` | `y:<cnv>` |
  | `differently` | `b_differently` | `d:<cnv>` |
  | `new_thing` | `b_new_thing` | `n:<cnv>` |
  | `make_task` | `b_make_task` | `t:<cnv>` |
  | `todo` | `b_todo` | `o:<cnv>` |
  | `forget:<mem>` | `b_forget` (`b_forget_n` with its number when there are several) | `f:<mem>` |
  | `done:<mem>` | `b_done` | `x:<mem>` |

  A `command` decision gets one more row, `b_handoff` with `k:<evt>`, when `self.handoff` is set.
- `_reply` records several things:
  - each sent message's id in `_sent[message_id] = (cnv, evt)`;
  - each `forget:`/`done:` item's scope in `_scope[mem] = body.project`;
  - for a `command` decision, `_said[evt]`: the texts of its own messages, from `_texts[message_evt]`, which
    `converse` fills;
  - the event's id in `_posted`.
- `follow` retries like `watch`: a 5xx or a dropped connection is waited out, `RECONNECT_S` doubling to
  `MAX_RECONNECT_S`. A refusal is told in the chat and ends the follow. Each handled event moves
  `last_conversation_event[cnv]`.

- [ ] **Step 1: Write the failing tests**

```python
def decided(evt, messages, decision="answer", reply="Ahoj.", **body):
    return {"id": evt, "ts": "2026-10-16T10:00:00Z", "type": "RECEPTION_DECIDED", "actor": {"kind": "system",
            "id": "ooat-reception"}, "refs": [], "cost": None,
            "body": {"conversation": CNV, "project": "docs", "messages": messages, "decision": decision,
                     "reply": reply, "options": [], "buttons": [], "context": [], "data_class": "internal", **body}}


def closed(evt):
    return {"id": evt, "ts": "2026-10-16T10:05:00Z", "type": "CONVERSATION_CLOSED", "actor": {"kind": "system",
            "id": "ooat-reception"}, "refs": [], "cost": None,
            "body": {"conversation": CNV, "project": "docs", "reason": "operator"}}


def sse(*events):
    return (200, "".join(f"id: {e['id']}\nevent: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode(),
            "text/event-stream")


def test_a_message_goes_to_the_reception_with_the_chat_key():
    with Stub((202, {"conversation": CNV, "message": MSG1})) as stub:
        bridge = Bridge(OoatClient(stub.url, "secret"), Kept(), "docs")
        assert bridge.converse("Změň titulek.", "41") == CNV
    sent = json.loads(stub.requests[0]["body"])
    assert stub.requests[0]["path"] == "/api/v1/conversations/messages"
    assert sent == {"project": "docs", "text": "Změň titulek.", "attachments": []}
    assert stub.requests[0]["headers"]["Idempotency-Key"] == "chat-1:41"


def test_a_burst_decided_once_is_posted_once_with_numbered_options_and_buttons():
    reply = decided(EVT3, [MSG1, MSG2], "confirm", "Rozumím: změnit titulek. Mám začít?",
                    options=["Jen titulek", "Titulek i podtitulek"], buttons=["yes", "differently"])
    with Stub((202, {"conversation": CNV, "message": MSG1}), (202, {"conversation": CNV, "message": MSG2}),
              sse(reply, closed(EVT4))) as stub:
        chat = Kept()
        bridge = Bridge(OoatClient(stub.url, "secret"), chat, "docs", language="cs")
        bridge.converse("Změň", "41")
        bridge.converse("titulek", "42")
        bridge.follow(CNV)
    assert chat.sent == ["Rozumím: změnit titulek. Mám začít?\n\n1. Jen titulek\n2. Titulek i podtitulek"]
    assert chat.buttons[0] == [[("Ano", f"y:{CNV}")], [("Jinak", f"d:{CNV}")]]


def test_another_bots_decision_and_report_are_not_posted():
    theirs = decided(EVT3, [MSG9], "task", "Dělám na tom.", task=TSK9)
    with Stub(sse(theirs, report(EVT4, TSK9), closed(EVT5))) as stub:
        chat = Kept()
        Bridge(OoatClient(stub.url, "secret"), chat, "docs").follow(CNV)
    assert chat.sent == []


def test_a_started_task_goes_to_on_task_and_its_report_is_posted():
    started = []
    with Stub(sse(decided(EVT3, [MSG1], "task", "Dělám na tom.", task=TSK1),
                  report(EVT4, TSK1, "Hotovo: titulek změněn.", ["Zkontrolovat web"]), closed(EVT5))) as stub:
        chat = Kept()
        bridge = Bridge(OoatClient(stub.url, "secret"), chat, "docs")
        bridge.restore({"own_messages": [MSG1]})
        bridge.on_task = started.append
        bridge.follow(CNV)
    assert started == [TSK1] and chat.sent == ["Dělám na tom.", "Hotovo: titulek změněn.\n\n1. Zkontrolovat web"]


def test_a_decision_above_the_cap_is_a_notice_without_buttons():
    stub_reply = {"redacted": "…", "link": f"/conversations/{CNV}"}
    above = decided(EVT3, [MSG1], "confirm", stub_reply, options=stub_reply, buttons=["yes", "differently"])
    with Stub(sse(above, closed(EVT4))) as stub:
        chat = Kept()
        bridge = Bridge(OoatClient(stub.url, "secret"), chat, "docs")
        bridge.restore({"own_messages": [MSG1]})
        bridge.follow(CNV)
    assert chat.sent == [TEXTS["en"]["redacted"]] and chat.buttons == [[]]


def test_a_switch_calls_on_switch_and_the_follow_ends():
    switched = []
    with Stub(sse(decided(EVT3, [MSG1], "switch", "Přepínám na eshop.", switch_to="eshop"), closed(EVT4))) as stub:
        chat = Kept()
        bridge = Bridge(OoatClient(stub.url, "secret"), chat, "docs")
        bridge.restore({"own_messages": [MSG1]})
        bridge.on_switch = lambda slug: switched.append(slug) or "Projekt eshop nemám v seznamu."
        bridge.follow(CNV)
    assert switched == ["eshop"] and chat.sent == ["Přepínám na eshop.", "Projekt eshop nemám v seznamu."]


def test_state_survives_a_restart_and_nothing_is_posted_twice():
    with Stub(sse(decided(EVT3, [MSG1]), closed(EVT4))) as stub:
        bridge = Bridge(OoatClient(stub.url, "secret"), Kept(), "docs")
        bridge.restore({"own_messages": [MSG1]})
        bridge.follow(CNV)
        saved = bridge.state()
    assert saved["last_conversation_event"] == {CNV: EVT4}
    with Stub(sse()) as stub:  # the server has nothing after the cursor
        chat = Kept()
        again = Bridge(OoatClient(stub.url, "secret"), chat, "docs")
        again.restore(json.loads(json.dumps(saved)))
        again.follow(CNV, stop=stopped_after_first_poll())
    assert stub.requests[0]["headers"]["Last-Event-ID"] == EVT4 and chat.sent == []
```

The test module also needs these helpers:
- constants `CNV`, `MSG1`, `MSG2`, `MSG9`, `EVT3` to `EVT5`, `TSK1`, `TSK9`, as valid-looking ids;
- `report(evt, task, reply="…", options=())`, which builds a `CONVERSATION_REPORTED` event with
  `body = {conversation, project, task, reply, options, data_class}`;
- `Kept`, the existing recording chat, extended with `buttons`, a list of each send's rows as `(label, data)`
  tuples;
- `stopped_after_first_poll()`, a `threading.Event` that a timer sets after 0.3 s.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider sdk/python/tests/test_ooat_bridge.py`
Expected: FAIL with `AttributeError: 'Bridge' object has no attribute 'converse'`.

- [ ] **Step 3: Implement**

In `Bridge.__init__`, add:

```python
        self.on_task = self.on_switch = self.handoff = None  # the bot's callbacks; see docs/chat-bridge.md
        self.handoff_name = "Claude Code"
        self.own_messages: list[str] = []  # message and tap ids this bridge sent, newest last (at most OWN_KEPT)
        self.own_tasks: list[str] = []  # tasks the decisions on them started
        self.last_conversation_event: dict[str, str] = {}  # conversation → the last event `follow` handled
        self._posted: set[str] = set()  # decisions already posted (a tap's comes back twice)
        self._sent: dict[str, tuple[str, str]] = {}  # a posted message's id → (conversation, event), for replies
        self._texts: dict[str, str] = {}  # own message id → its text, for a handoff
        self._said: dict[str, str] = {}  # a command decision → the text a handoff passes on
        self._scope: dict[str, str] = {}  # memory item → its scope, from the reply that showed its button
```

Then:
- `converse` checks the text first: `text.strip()` empty raises `ValueError(self._t("no_text"))`.
- It looks up `replied_to` in `_sent`, to get `conversation` and `reply_to`.
- It calls `send_message(..., key=f"{self.chat.id}:{message_id}")`.
- It appends the message id to `own_messages` (via `_own`, which trims to `OWN_KEPT = 500`) and stores `_texts`.
- It sets `last_conversation_event.setdefault(cnv, message)` (decision 7) and returns the conversation id.

`follow` mirrors `watch`. The cursor for each call is `self.last_conversation_event.get(cnv)`.

- [ ] **Step 4: Run the tests to verify they pass.** The same command; expected: PASS. Then run the whole SDK suite:
  `.venv/Scripts/python -m pytest -q -p no:cacheprovider sdk/python/tests`.

- [ ] **Step 5: Commit**

```bash
git add sdk/python/src/ooat_client/bridge.py sdk/python/src/ooat_client/texts.py sdk/python/tests/test_ooat_bridge.py
git commit -m "feat: the chat bridge sends messages to the reception and posts its replies (08c task 1)"
```

### Task 2: The reception's buttons

**Files:**
- Modify: `sdk/python/src/ooat_client/bridge.py`, `sdk/python/src/ooat_client/texts.py`
- Test: `sdk/python/tests/test_ooat_bridge.py`

**Interfaces:**
- Consumes:
  - `OoatClient.tap(conversation, tap, text=None) -> {conversation, message, decision}`;
  - `OoatClient.forget(scope, memory)` and `OoatClient.done(scope, memory)`;
  - from task 1: `_reply`, `_own`, `_posted`, `_scope`, `_said`, `on_task`.
- Produces `on_button(data)` for these codes:
  - `y`, `d`, `n`, `t`, `o` with `<cnv>`;
  - `f` and `x` with `<mem>`;
  - `k` with `<evt>`.

The codes behave as follows:
- `y:` → `tap(cnv, "yes")`; `d:` → `differently`; `n:` → `new_thing`; `t:` → `make_task`; `o:` → `todo`. For each:
  - the response's message id is recorded with `_own`;
  - its decision is posted with `_reply`, which adds it to `_posted`, so the stream skips it;
  - a started task goes to `on_task`;
  - the person sees `recorded`.

  A Differently tap needs no text: the reception asks "Write how you mean it", and the next message is the
  correction.
- `f:<mem>` → `client.forget(self._scope.get(mem, self.project), mem)`, which returns `forgotten`. `x:<mem>` →
  `client.done(...)`, which returns `marked_done`.
- `k:<evt>`:
  - with no `handoff`, or no `_said[evt]`, it returns `handoff_gone`;
  - otherwise it calls `self.handoff(self._said.pop(evt))` and returns `handed`, built with `engine=handoff_name`.
- A refusal returns the server's message, as the existing buttons do.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_yes_tap_posts_its_decision_once_and_starts_the_watch():
    started = decided(EVT5, [TAP1], "task", "Spouštím: změnit titulek", task=TSK1)
    with Stub((200, {"conversation": CNV, "message": TAP1, "decision": started}),
              sse(started, closed(EVT6))) as stub:
        chat, tasks = Kept(), []
        bridge = Bridge(OoatClient(stub.url, "secret"), chat, "docs", language="cs")
        bridge.on_task = tasks.append
        assert bridge.on_button(f"y:{CNV}") == "Odpověď zaznamenána."
        bridge.follow(CNV)
    assert json.loads(stub.requests[0]["body"]) == {"tap": "yes"}
    assert chat.sent == ["Spouštím: změnit titulek"] and tasks == [TSK1]


def test_forget_uses_the_scope_of_the_reply_that_showed_the_button():
    noted = decided(EVT3, [MSG1], reply="Hotovo.\n\n🧠 Zapamatováno: titulky píšeme bez tečky.",
                    project="eshop", buttons=[f"forget:{MEM1}"], memory=[MEM1])
    with Stub(sse(noted, closed(EVT4)), (200, {"memory": MEM1, "forgotten": True, "event": EVT5})) as stub:
        chat = Kept()
        bridge = Bridge(OoatClient(stub.url, "secret"), chat, "docs")
        bridge.restore({"own_messages": [MSG1]})
        bridge.follow(CNV)
        assert bridge.on_button(f"f:{MEM1}") == "Forgotten."
    assert stub.requests[1]["method"] == "DELETE" and stub.requests[1]["path"] == f"/api/v1/memory/eshop/{MEM1}"


def test_a_command_offers_the_handoff_and_passes_the_own_text_once():
    handed = []
    with Stub((202, {"conversation": CNV, "message": MSG1}),
              sse(decided(EVT3, [MSG1], "command", "Tohle OOAT nespustí.", buttons=["todo"]),
                  closed(EVT4))) as stub:
        chat = Kept()
        bridge = Bridge(OoatClient(stub.url, "secret"), chat, "docs", language="cs")
        bridge.handoff = handed.append
        bridge.converse("Commitni a pushni to.", "41")
        bridge.follow(CNV)
    assert chat.buttons[0][-1] == [("Předat: Claude Code", f"k:{EVT3}")]
    assert bridge.on_button(f"k:{EVT3}") == "Předáno: Claude Code."
    assert handed == ["Commitni a pushni to."]
    assert bridge.on_button(f"k:{EVT3}") == TEXTS["cs"]["handoff_gone"]


def test_reception_button_data_fits_telegram():
    for data in (f"y:{CNV}", f"f:{MEM1}", f"k:{EVT3}"):
        assert len(data.encode()) <= 64
```

- [ ] **Step 2: Run the tests to verify they fail.** Expected: FAIL with `This button is not one of OOAT's.`

- [ ] **Step 3: Implement** the branches in `on_button`, before the existing `a:` branch. Add the text keys to `en`
  and `cs`:

  | Key | en | cs |
  | --- | --- | --- |
  | `b_yes` | Yes | Ano |
  | `b_differently` | Differently | Jinak |
  | `b_new_thing` | New thing | Nová věc |
  | `b_make_task` | Make it a task | Udělat z toho úkol |
  | `b_todo` | Keep as an open point | Nechat jako otevřený bod |
  | `b_forget` | Forget | Zapomenout |
  | `b_forget_n` | Forget {n} | Zapomenout {n} |
  | `b_done` | Done ✓ | Hotovo ✓ |
  | `b_handoff` | Hand to: {engine} | Předat: {engine} |
  | `forgotten` | Forgotten. | Zapomenuto. |
  | `marked_done` | Marked done. | Odškrtnuto. |
  | `handed` | Handed to: {engine}. | Předáno: {engine}. |
  | `handoff_gone` | I no longer have that message: send it again. | Tu zprávu už nemám: pošlete ji znovu. |
  | `no_text` | Write a message. | Napište zprávu. |

- [ ] **Step 4: Run the SDK suite to verify it passes.**

- [ ] **Step 5: Commit**
  `git add sdk/python/src/ooat_client/bridge.py sdk/python/src/ooat_client/texts.py sdk/python/tests/test_ooat_bridge.py`
  and `git commit -m "feat: the reception's buttons in the chat bridge - yes, differently, task, open point, forget,
  handoff (08c task 2)"`.

### Task 3: `/pamet` — the project's memory in the chat

**Files:**
- Modify: `sdk/python/src/ooat_client/bridge.py`, `sdk/python/src/ooat_client/texts.py`
- Test: `sdk/python/tests/test_ooat_bridge.py`

**Interfaces:**
- Consumes: `OoatClient.memory(scope, kind=None, done=False) -> list[item]`, where an item is `{memory, scope, kind,
  data_class, text, pinned, done, noted, ...}`; `_scope` from task 1.
- Produces: `Bridge.show_memory() -> str | None`. It posts the memory and returns None, or returns the server's
  refusal as text.

The post has these parts:
- `mem_pinned` with the pinned items, one line each;
- `mem_todos` with the open points (kind `todo`, not done), numbered, each with a row `[b_done n] [b_forget_n n]`
  (`x:<mem>`, `f:<mem>`);
- `mem_summary` with the text of the newest `summary` item.

Each part is left out when it is empty. When all three are empty, the post is `mem_empty`, which names the project.
An item whose `text` is the stub (a dict) is shown as `redacted`. At most 10 open points are shown, the oldest
first, with `mem_more` (`and {n} more on the web`) after them. Each listed item's scope is recorded in `_scope`.

- [ ] **Step 1: Write the failing tests**

```python
def item(mem, kind, text, pinned=False, noted="2026-10-15T10:00:00Z"):
    return {"memory": mem, "scope": "docs", "kind": kind, "data_class": "internal", "text": text,
            "pinned": pinned, "done": False, "noted": noted, "source": None, "conversation": None}


def test_memory_shows_pinned_items_open_points_with_buttons_and_the_last_summary():
    items = [item(MEM1, "fact", "Web běží na IIS.", pinned=True), item(MEM2, "todo", "Na konci projektu připomenout "
             "zálohu."), item(MEM3, "summary", "Starší.", noted="2026-10-14T09:00:00Z"),
             item(MEM4, "summary", "Měnili jsme titulky.")]
    with Stub((200, {"scope": "docs", "items": items})) as stub:
        chat = Kept()
        assert Bridge(OoatClient(stub.url, "secret"), chat, "docs", language="cs").show_memory() is None
    assert chat.sent == ["📌 Připnuté:\n• Web běží na IIS.\n\nOtevřené body:\n1. Na konci projektu připomenout "
                         "zálohu.\n\nMinule: Měnili jsme titulky."]
    assert chat.buttons[0] == [[("Hotovo ✓ 1", f"x:{MEM2}"), ("Zapomenout 1", f"f:{MEM2}")]]


def test_empty_memory_says_so():
    with Stub((200, {"scope": "docs", "items": []})) as stub:
        chat = Kept()
        Bridge(OoatClient(stub.url, "secret"), chat, "docs").show_memory()
    assert chat.sent == ["Project docs has nothing in its memory yet."]
```

- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement**:
  - `show_memory`;
  - the keys `mem_pinned` ("📌 Pinned:"/"📌 Připnuté:"), `mem_todos` ("Open points:"/"Otevřené body:"),
    `mem_summary` ("Last time: {text}"/"Minule: {text}"), `mem_empty` ("Project {project} has nothing in its memory
    yet."/"Projekt {project} zatím nemá nic v paměti."), `mem_more` ("and {n} more on the web"/"a dalších {n} na
    webu");
  - `b_done_n` ("Done ✓ {n}"/"Hotovo ✓ {n}").
- [ ] **Step 4: Run the SDK suite to verify it passes.**
- [ ] **Step 5: Commit** `feat: /pamet - pinned items, open points and the last summary in the chat (08c task 3)`.

### Task 4: The contract as built

**Files:**
- Modify: `docs/chat-bridge.md`, `sdk/python/README.md`

- [ ] **Step 1:** In `docs/chat-bridge.md`, replace the section "Conversations (the reception)" with rows in the
  contract table:
  - a message → `converse` → `POST /conversations/messages`;
  - replies → `follow` (own events only, decision 1);
  - the new button data and what each calls;
  - `/pamet` → `show_memory`;
  - the callbacks `on_task`, `on_switch`, `handoff`.

  Also:
  - say that `on_message` remains for a bot without the reception;
  - extend "Restarts" with `state()`/`restore()`;
  - extend "What changes for a bot that ran a coding CLI": the reception answers and remembers, and a command can
    be handed to the CLI by a tap.
- [ ] **Step 2:** In `sdk/python/README.md`, add one paragraph with the three lines of minimal use (`converse`,
  `follow` in a thread, `on_task = watch in a thread`).
- [ ] **Step 3:** Run the whole suite, `.venv/Scripts/python -m pytest -q -p no:cacheprovider`. Expected: PASS.
- [ ] **Step 4: Commit**
  `git add docs/chat-bridge.md sdk/python/README.md` and `git commit -m "docs: the chat bridge talks to the reception
  (08c task 4)"`.

## After the plan

The bot's task-04 uses these methods. It is deployed only after this plan, 08a and the 60 s window (PR #51) are on
`main` and pulled into the production clone `C:\scripts\OOAT`. Restarting `OoatServe` and the bot needs the owner's
confirmation, as always.

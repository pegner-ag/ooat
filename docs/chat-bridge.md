# Chat bridge (As-is)

A chat bridge is a bot that holds one OOAT API token and turns chat actions into calls of the REST API of
`ooat serve` (design 05 §9). OOAT ships the Python client `ooat-client` (`sdk/python`, standard library only) with a
reference bridge, `ooat_client.Bridge`, that implements the contract below for any chat platform. The bot stays the
operator's own program: it receives messages and button presses, sends messages, and **checks that a message comes
from its allowed chat or user before it calls the bridge**. OOAT trusts the token; the bot vouches for the person.

## The token

`ooat tokens create --operator NAME --name telegram --scopes submit,read,answer,rate` prints the token once; keep
it in the bot's own secret store, never in code. Its data-class cap is `internal` by default, and stays so for a
chat bridge (owner decision): a chat service stores messages on its own servers. Content of a task above the cap
(client or personal data, also when the pre-scan raises the class) reaches the chat only as a notice to open the
web app, and answering, rating or cancelling such a task from the chat is refused. `ooat tokens revoke` ends the
token at once, also for a timeline the bot is following.

## Contract

| Chat action | `Bridge` | API |
|---|---|---|
| A message (with files) in a project's chat | `on_message(text, message_id, files)` → task id | `POST /tasks` with the chat's project; the text before a `Done when:` (or `Hotovo když:`) line is the `goal`, each line after it a criterion; files as attachments; `Idempotency-Key: <chat id>:<message id>`, so a repeated delivery returns the first task |
| Progress | `watch(task)` | follows `GET /tasks/{id}/events` (Server-Sent Events) and posts one line for the Gate's topology, each attempt and each answer |
| A question | posted by `watch`; `on_button(data)`, `on_reply(message_id, text)` | `GET /hil`: one button per option (★ the recommended one, its cost when it has one), the default on silence and the deadline (UTC) in the text; a button calls `POST /hil/{evt}/answer`; the options answered with text (clarify, narrow the scope) ask for a reply, and a reply to the question answers with its text; an R3 question has no buttons |
| Result | posted by `watch` | the final document as text in up to 3 messages (`limit`, default 4096 characters), else as a file `<task>.md` (`<task>` when it is not text); a footer: state, topology, cost, tokens in/out, time |
| Project files | posted by `watch` | for a task on a project's folders (ADR 0017): the diff as `<task>.diff` after the document; a "Revert the changes" row in the footer while a revert is possible; a tap asks "Yes, revert", and only that second tap calls `POST /tasks/{id}/revert`; skipped files are listed with their reason. A limit question is preceded by the task's latest document and its diff, and its `revert` button asks for a second tap too. Nothing of this is posted above the token's data class |
| Rate | the footer's buttons, `on_button(data)` | `POST /tasks/{id}/rating`: `Accepted A/B/C` or `Not accepted A/B/C`; the decisions stay for the web app's rating card |
| `/cancel` | `cancel(task)` | `POST /tasks/{id}/cancel` |
| `/stats` | `stats(period="7d")` | `GET /stats?period=…&project=…`, by role and by connector |

Methods called on a person's action return the text to show them, the server's reason included when it refuses;
only `on_message` raises (`OoatError` when the server refuses the task, `ValueError` when the message has no goal),
so the bot replies with the error's text. `watch` posts on its own and returns when the task is closed, after
posting the reason when the server refuses (a revoked token, say), or when its `stop` event is set; a busy or
vanished server is waited out, and the event it was posting is posted once the server is back; when the
chat itself fails to send, `watch` raises `ChatFailed` (the bot's error, never retried). Button data is at
most 64 bytes (Telegram's callback-data limit): `a:<request>:<option>`, `r:<task>:<A|B|C>:<y|n>`, and for
revert `v:<task>` (asks), `V:<task>` (confirmed) and `c:<request>` (a confirmed `revert` answer). A project
without folders in OOAT gets a notice once, after its first task.
The bridge writes English or Czech (`language="cs"`); option labels, states and the server's error messages come as
the API gives them.

## Minimal use

```python
from ooat_client import Bridge, OoatClient

client = OoatClient("http://127.0.0.1:8765", token)           # token from the bot's secret store
bridge = Bridge(client, chat, project="docs", language="cs")  # chat: id, send(text, buttons), send_file(...)

stop = threading.Event()                                      # set it when the bot shuts down

task = bridge.on_message(text, message_id, files)             # a message from the allowed chat or user
await asyncio.to_thread(bridge.watch, task, stop=stop)        # progress, questions, the result (it blocks)
await show(bridge.on_button(data))                            # a button press
```

The client is synchronous (standard library only); an async bot runs `watch` in a thread as above. Without the
bridge, `OoatClient` alone has `submit`, `follow` (the timeline until `TASK_CLOSED`), `task`, `events`,
`questions`, `answer`, `rate`, `cancel`, `revert`, `artifact` and `stats`; a refusal raises `OoatError` with the API's code.

## Network

Plain HTTP only to this machine (`127.0.0.1`, `::1`, `localhost`); beyond it HTTPS (`ooat serve --host` needs TLS).
The client follows no redirects and uses no proxy from the environment, so the token goes to the OOAT server only.
`follow` reconnects after a dropped connection or a busy server (1 s, doubling to 30 s) from the last event it
yielded, and opens the stream again when the server ends it after 15 minutes; a certificate that fails
verification is raised, not retried. `follow(task, stop=event)` ends within a second once the event is set.

## Restarts

Tasks live in the ledger, not in the bot. `bridge.last_event` maps each watched task to the last event `watch`
handled; a bot that keeps it calls `watch(task, after=last_event)` after a restart, and nothing is posted twice. For
conversations a bot keeps `bridge.state()` (its own message and task ids, what it posted, each conversation's
cursor and each memory button's scope), saved after every button too, gives it
back with `bridge.restore(state)` and calls `follow` again. A reply to a reception post sent before the restart is
an ordinary message, which goes into the open conversation anyway; a Hand-over button from before it asks to send
the message again. A
task already closed returns at once. Buttons keep working, since they carry the
ids. Replies to questions sent before the restart are not recognised (the bridge keeps question messages in memory):
answer those with the buttons or in the web app.

## Conversations (the reception)

A bot with the reception (design 08, ADR 0018) sends each message with `converse` instead of `on_message`. The
reception answers it, asks one question, asks to confirm, or starts a task with criteria it writes itself, and keeps
project memory. `on_message`, one task per message, stays for a bot without the reception.

| Chat action | `Bridge` | API |
|---|---|---|
| A message (with files) | `converse(text, message_id, files, replied_to)` → conversation id | `POST /conversations/messages` with the chat's project; `Idempotency-Key: <chat id>:<message id>`; a reply to one of the reception's posts sends its `conversation` and `reply_to` |
| Replies | `follow(conversation, stop)` | follows `GET /conversations/{id}/events` until `CONVERSATION_CLOSED`. It posts each `RECEPTION_DECIDED` on the bridge's own messages, with its numbered options (`1. …`) and buttons, and the `CONVERSATION_REPORTED` of each task those decisions started. A task started goes to `on_task` (the bot watches it with `watch`), a project switch to `on_switch` |
| Yes, Differently, New thing, Make it a task, Keep as an open point | `on_button` with `y:`, `d:`, `n:`, `t:`, `o:` + `<conversation>` | `POST /conversations/{id}/taps`; the decision in the response is posted at once, and not again from the stream |
| Forget, Done | `on_button` with `f:` / `x:` + `<memory>` | `DELETE` / `PATCH /memory/{scope}/{memory}`, the scope from the post that showed the button (else the chat's project); they keep working after the conversation closes |
| Hand a command to another engine | `on_button` with `k:<event>`, only when the bot set `handoff` | none: the bot's `handoff(text)` gets the text of the bridge's own messages behind that `command` decision, once |
| `/pamet` | `show_memory()` | `GET /memory/{project}`: pinned items, open points (each with Done and Forget), the last summary |

A bridge posts only the replies to its own messages and the reports of its own tasks, so several bots that share a
token and a chat id never post one reply twice. A reply above the token's data class is the notice to open the web
app, without buttons. The reception waits for a quiet window after the last message (60 s by default) before it
decides, so a bot should show that the message arrived (the Telegram bot reacts with 👀).

The callbacks are attributes the bot sets: `on_task(task)`, `on_switch(project) -> text or None` (a text is posted
when the switch could not be applied), `handoff(text)` with `handoff_name` for the button's label.

## What changes for a bot that ran a coding CLI

An OOAT task in F1 turns text into a document; for a project mapped in `ooat.toml` it also reads and edits the
project's files through OOAT's own tools (ADR 0017), but it runs no commands. With the reception a question is
answered without a task, the conversation and project memory carry over between messages, and a command (commit,
push, restart) is said to be out of reach, with a button that hands it to the chat's coding CLI when the bot offers
one. Every task still pays for the Gate and the acceptance checks. Add the bridge as one more engine a chat can
switch to (`/engine ooat`), next to the direct CLI, until tool capabilities and sessions exist (owner decision).

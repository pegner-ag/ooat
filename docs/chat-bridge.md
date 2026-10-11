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
| Rate | the footer's buttons, `on_button(data)` | `POST /tasks/{id}/rating`: `Accepted A/B/C` or `Not accepted A/B/C`; the decisions stay for the web app's rating card |
| `/cancel` | `cancel(task)` | `POST /tasks/{id}/cancel` |
| `/stats` | `stats(period="7d")` | `GET /stats?period=…&project=…`, by role and by connector |

Methods called on a person's action return the text to show them, the server's reason included when it refuses;
only `on_message` raises (`OoatError` when the server refuses the task, `ValueError` when the message has no goal),
so the bot replies with the error's text. `watch` posts on its own and returns when the task is closed, after
posting the reason when the server refuses (a revoked token, say), or when its `stop` event is set; a busy or
vanished server is waited out, and the event it was posting is posted once the server is back. Button data is at
most 64 bytes (Telegram's callback-data limit): `a:<request>:<option>` and `r:<task>:<A|B|C>:<y|n>`.
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
`questions`, `answer`, `rate`, `cancel`, `artifact` and `stats`; a refusal raises `OoatError` with the API's code.

## Network

Plain HTTP only to this machine (`127.0.0.1`, `::1`, `localhost`); beyond it HTTPS (`ooat serve --host` needs TLS).
The client follows no redirects and uses no proxy from the environment, so the token goes to the OOAT server only.
`follow` reconnects after a dropped connection or a busy server (1 s, doubling to 30 s) from the last event it
yielded, and opens the stream again when the server ends it after 15 minutes; a certificate that fails
verification is raised, not retried. `follow(task, stop=event)` ends within a second once the event is set.

## Restarts

Tasks live in the ledger, not in the bot. `bridge.last_event` maps each watched task to the last event `watch`
handled; a bot that keeps it calls `watch(task, after=last_event)` after a restart, and nothing is posted twice. A
task already closed returns at once. Buttons keep working, since they carry the
ids. Replies to questions sent before the restart are not recognised (the bridge keeps question messages in memory):
answer those with the buttons or in the web app.

## What changes for a bot that ran a coding CLI

An OOAT task in F1 turns text into a document. It has no tools (no file edits, no commands) and no conversation
memory (each message is its own task, with clarifications inside the task), and every task pays for the Gate and
the acceptance checks. Add the bridge as one more engine a chat can switch to (`/engine ooat`), next to the direct
CLI, until tool capabilities and sessions exist (owner decision).

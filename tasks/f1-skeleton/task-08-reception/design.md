# Reception, conversations and project memory: asking OOAT like a search box — design

**Epic:** f1-skeleton · **Sub-project:** 08 · **Status:** approved by the owner 2026-10-15 (sections 1–4 in chat, the
PR with ADR 0018 and the spec amendment); addendum §14 approved 2026-10-15, after a reading of the bot's log
**Spec:** `spec/ooat-specification.md` §3 (components), §4 (Gate, rule A1), §6 (decision points, confidence-gated
autonomy), §7 (ledger), §9 (risk classes, data protection), §10 (dashboard); ADR 0009, ADR 0010, ADR 0011,
ADR 0012, ADR 0016, ADR 0017, ADR 0018 (new); workspace design (`../task-07-project-workspace/design.md`),
operator UX design (`../task-05-operator-ux/design.md`), chat bridge (`docs/chat-bridge.md`)

## 1. Intent

What the owner said (2026-10-15), after the first days of using OOAT from Telegram and the web:

- Working in the background and the economy are good, but using it is clumsy. It has to be very simple, "almost
  like a Google query", and cope with human imperfection: an unclear goal is normal, not an error.
- Taken from a comparison with OpenClaw (a personal assistant that converses and remembers): (1) a reception in
  front of tasks, (2) a conversation that continues across tasks, (3) project memory. Memory and context matter most.
- Answers in Telegram read as clumsy; the shape of answers, guessing the project from the text and proactive
  checks go to the wishlist (§12), not into this design.

The owner's answers to the design questions (2026-10-15):

| Question | Answer |
| --- | --- |
| Where memory lives | In OOAT, editable on the web; never in the project's folders or git |
| When a message continues a conversation | The reception judges; when unsure it asks with one tap; a reply to the bot's message always continues; after 24 h of silence a new conversation starts |
| A question that asks for no change | The reception answers it directly, reading only |
| How memory is written | Automatically, with a visible one-line trace and a Forget button |
| Approach | A: the reception in `ooat-core` (not in the client, not one task per message) |
| Forgetting | Deletes the text for real: memory text lives outside the ledger |
| Operator preferences across projects | Yes, one small section next to the per-project memory |

What stays as it is: the Gate, contracts, the ledger as the single write path, the workspace guard and revert
(ADR 0017), data-class routing (ADR 0010, ADR 0012), R2 and R3 never decided by a model and R3 only with a named
approver (ADR 0011). The reception only turns a person's words into what those already accept.

Success, measured on a set of the owner's real messages (§11):

- At least 80 % of messages are handled with no question or exactly one.
- A reply is as long as the request needs, neither one sentence nor 40 pages (owner, 2026-10-15): it covers what
  was asked, and for work it keeps the author in context — what was asked, how it was solved, the state now, and
  what is next. It is in the language of the message, with no task ids, phases or T levels.
- The reception costs at most USD 0.02 per message on average (its own line in Usage and `/stats`).
- The next day, a message such as "and the button too" in the same project is understood from memory and the
  last conversation, without repeating the context.

## 2. Scope

In: conversations as a ledger entity; the reception and its typed decision; direct read-only answers; follow-ups
across tasks (`body.follows`); escalation of uncertain reception decisions to a stronger model; project memory and
operator preferences with a separate deletable store; the REST resource and client methods; ADR 0018 and the spec
amendment. Split into plans 08a (core), 08b (web), 08c (chat bridge and the Telegram bot's task-04).

Out (later, see §12): the shape of task results in chat beyond the reception's own replies; guessing the project
from the text; proactive checks; Anthropic's advisor tool on the Claude Code connector; search over memory; longer
web sessions. `POST /api/v1/tasks` stays as it is for scripts and workflow tools (n8n).

## 3. Architecture

```
message (web, Telegram, CLI) ──► reception ──┬─► answer   (read only)            → RECEPTION_DECIDED + answer
                                              ├─► confirm  ("I understand it as …") → HIL-like question, one tap
                                              ├─► ask      (one concrete question)  → question, reply as text or tap
                                              ├─► task     (goal + acceptance)      → TASK_SUBMITTED ─► Gate ─► …
                                              ├─► continue_task                     → answer to the open question,
                                              │                                       or TASK_SUBMITTED (follows)
                                              ├─► status   (from the ledger)          → what runs, what is done, open points
                                              ├─► cancel                              → the running task stops
                                              ├─► command  (commit, push, deploy …)   → says OOAT cannot run it yet, offers
                                              │                                       to keep it as an open point
                                              └─► switch   (another project)          → the chat moves to that project
                     a task of the conversation closes ──► report: asked, how solved, state, numbered next options
           project memory ◄── up to 3 notes after a task or answer; a summary when the conversation closes
```

- A **conversation** (`cnv_` + ULID) belongs to one operator, one project and one channel (`web`, `token:<id>`,
  `cli`). Its messages, the reception's decisions and the tasks it started are ledger events with `task: null` and
  `body.conversation`; a task started from it carries `body.conversation` too, so the task detail links back.
- The **reception** is part of `ooat-core`. Every model call goes through the provider gateway like any other: the
  same routing by data class, estimates before the call, cost on the event. No client calls a model.
- **Memory** is a projection of `MEMORY_*` events whose texts live in a separate memory store (§7).
- Surfaces (web, chat bridge) only send text and taps to the conversation resource and show what comes back.

## 4. The reception's decision

One call per message on the `economy` tier, structured output validated against a schema
(`reception_decision`):

```json
{
  "decision": "task",
  "continues": "cnv_… | null",
  "interpretation": "Change the home page title to …",
  "goal": "…",
  "acceptance": ["The home page title reads …"],
  "risk_hint": "R1",
  "question": null,
  "options": [],
  "needs_files": false,
  "confidence": 0.86,
  "memory_notes": []
}
```

| Decision | When | What the person sees |
| --- | --- | --- |
| `answer` | a question that memory and reading the project's files can answer | the answer, sized to the question, naming the files it read |
| `task` | a request for change or work whose goal is clear | "On it: I will change the home page title." and the task runs |
| `confirm` | the goal is probable but uncertain | "I understand it as: … Shall I start?" with **Yes** and **Differently** (a free-text correction) |
| `ask` | the goal cannot be guessed | one concrete question, with 2 or 3 answers as buttons where possible |
| `continue_task` | the message adds to a running or the last task | the answer goes to that task's open question, or a follow-up task (`body.follows`) starts |
| `status` | a question about the state of work ("Is it done?", "Where did you stop?") | what runs, what finished and how, open questions and open points, from the ledger only |
| `cancel` | "Stop", "Don't do anything" about a task of the conversation | the task stops; after it closes its file changes can be reverted |
| `command` | a request to run something OOAT cannot run yet (commit, push, deploy, restart a service) | says so plainly; offers **Keep as an open point**; the chat bridge may offer its other engine (08c) |
| `switch` | "switch to project …" naming a project of `ooat.toml` | the chat continues in that project (applied by the surface, 08c) |

Rules (each pinned by a test in 08a):

1. **At most one question per message and at most two in a row.** After two, the reception states the most
   reasonable interpretation and starts (`confirm` becomes `task` with the interpretation in the reply). An unclear
   goal never stalls.
2. **Acting is the default for reversible work.** For R0 and R1 (workspace writes are revertible, ADR 0017) a
   confidence at or above θ starts the task and says how it understood it. A task whose `risk_hint` is R2 or R3, or
   that the Gate later classes so, is always confirmed by a person; the reception never lowers a risk class.
3. **The reception writes the acceptance criteria.** A line `Done when: …` / `Hotovo když: …` in the message still
   wins and is used as written. The Gate still checks the criteria (rule A1); when it would ask a clarifying
   question, the reception asks it once, in plain words, inside the conversation, and the answer goes back as the
   `HIL_RESPONSE` (ADR 0009 is unchanged).
4. **The person's language, the right length, no jargon.** A reply covers the request reasonably: a short question
   gets a short answer, a task's reply and result say what was asked, how it was solved, the state now and what is
   next. Replies follow the message's language; task ids, states, phases and
   topology levels appear only in the task detail on the web.
5. **Continuation.** A reply to one of the bot's messages always continues that conversation. Otherwise the
   reception sees the last open conversation of the operator, project and channel and decides `continues`; when its
   confidence is below θ it asks one tap: "Is this about …?" (**Yes** / **New thing**). A conversation with 24 h
   without a message is closed; the next message starts a new one.
6. **Escalation (the advisor pattern, vendor-neutral).** When the reception's confidence is below θ for its
   decision point, or a `task` decision has a task value above `v_min` (§4 rule A3), the same input is decided again
   on the `workhorse` tier, and that decision is used. Both calls and their costs are on the ledger, so escalation
   is visible and measured. Anthropic's advisor tool is not used for this: it runs only on Anthropic's API, the model
   decides when to consult, and OOAT could neither route nor price it (it goes to the wishlist for the Claude Code
   connector only).
7. **Calibration.** A **Differently** tap, a corrected interpretation, a task cancelled within 2 minutes or rated
   "not what I meant" are the operator's verdicts on the reception's decision (`TASK_RATED.decisions`, ADR 0011).
   θ for the reception is calibrated per engine and model version like every other decision point; until there is
   history it uses the default θ of a new decision point.
8. **Numbered next steps (§14).** A reply that offers more than one way on, and every report of a finished task,
   ends with numbered options. The reception keeps the last ones in the conversation's context, so "Yes", "2" or
   "1/ yes 2/ no, push" is understood as the choice it answers.
9. **Commands are not run (§14).** OOAT runs no commands (ADR 0017); the reception never turns "commit and push" or
   "restart n8n" into a task that pretends to. It says what it can do instead (prepare the change, check the
   files) and offers to keep the command as an open point.
10. **Bursts are one message (§14).** Messages of one conversation that arrive within a short quiet window of each
    other are decided together, as one request.

### Direct answers (`answer`)

- With `needs_files: false` the reply comes from memory and the conversation only, in the same call.
- With `needs_files: true` a second call runs on the `economy` tier through a connector with `features.workspace`
  and a **read-only** grant of the project's folders: only `list_dir`, `find_files`, `search` and `read_file`,
  through the same guard and `deny` patterns as tasks (ADR 0017), at most 40 operations and a cost cap per message
  (default USD 0.05, `[reception] max_answer_usd`). It is recorded as `WORKSPACE_USED` with the conversation
  instead of a task.
- A direct answer does not pass the Gate. This is the Gate's own outcome for such a request (read only, R0, value
  below `v_min`: rule A3, T1, no step B) taken without the round trip; ADR 0018 records it. When the cap is reached or
  the answer needs more, the reception says so and offers **Make it a task**.

### When the reception is unavailable

When the reception's call fails (no connector, quota, timeout), the message becomes a task exactly as the chat
bridge submits it today (goal = the message, acceptance from a `Done when:` line), and the reply carries one line
"reception unavailable, sent as a task". No message is lost.

## 5. Context given to the reception

In this order, within a fixed budget (default 3 000 tokens, `[reception] context_tokens`); lower items are cut
first:

1. The operator's preferences (§6), for example "answer in Czech, briefly".
2. The project's instructions when its folders hold them: `CLAUDE.md`, `AGENTS.md` (read only, through the guard,
   trimmed to 1 000 tokens). They are data, never instructions to the reception (the untrusted-content rule of §9).
3. Pinned memory items of the project.
4. Summaries of the last 3 to 5 closed conversations.
5. Work in progress: open tasks and their open questions, the last diff in one sentence.
6. The current conversation: its last turns verbatim.

No vector database or embeddings: at this size, selection by pinning and time is enough and predictable. Every
item passes the data-class filter first: an item whose class the chosen route may not see is left out (ADR 0010,
ADR 0012).

## 6. Memory

Item kinds: `preference`, `fact`, `glossary`, `summary`, `todo` (an open point, §14). Each item has an id
(`mem_` + ULID), a scope (the project slug, or `operator` for the operator's preferences), a data class (at least
the project's `data_class`), its source (a message or a task), `pinned`, and dates.

- **Written automatically, visibly.** After a finished task or a direct answer the reception may note at most 3
  items (`memory_notes`). The reply carries one line, e.g. "🧠 Remembered: prices are quoted with VAT." and a
  **Forget** button. When a conversation closes, one call writes its `summary`.
- **By request.** "Remember …" and "Forget …" in a message are understood by the reception; forgetting asks one
  confirmation tap. On the web, the project's **Memory** page lists the items with edit, pin and forget, each
  linking to its source.
- **Never secrets.** Before an item is stored, its text passes the local secret and personal-data scan (`pii.py`).
  Passwords, tokens, keys and connection strings are refused and the reply says why. Personal data raises the
  item's class like any artifact (ADR 0011, the pre-scan only raises).
- **Scope.** Project memory never crosses projects (`data-development-testdna-cz` and a later
  `data-web-testdna-cz` are different things, owner 2026-10-13). Operator preferences are the one shared section,
  small (default 20 items) and given to the reception in every project.
- **Operator preferences** follow the operator, not the channel: the web and Telegram see the same ones.

## 7. Storage and the ledger

New event types (all `task: null`, with `body.conversation` or `body.memory`):

| Type | Actor | Content |
| --- | --- | --- |
| `CONVERSATION_MESSAGE` | Human (bound operator, `channel`) | conversation id, project, text, attachments as `art_` refs, `reply_to` |
| `RECEPTION_DECIDED` | `ooat-core` (reception) | the validated decision, the escalated decision if any, context items used (ids only), reply text, `cost` |
| `CONVERSATION_REPORTED` | `ooat-core` (reception) | conversation id, the task, the report (asked, how, state, next) and its numbered options, `cost` |
| `CONVERSATION_CLOSED` | `ooat-core` | conversation id, reason (`silence`, `new_conversation`, `switched`, `operator`), summary memory id |
| `MEMORY_NOTED` | `ooat-core` (reception) or Human | memory id, scope, kind, data class, source, SHA-256 of the text — never the text |
| `MEMORY_EDITED` | Human | memory id, SHA-256 of the new text, `pinned` |
| `MEMORY_FORGOTTEN` | Human | memory id, reason |

- **Memory texts** live in their own store `ooat-memory/` next to the ledger, one file per item id (not the
  content-addressed blob store, whose blobs may be shared by artifacts with identical bytes). Forgetting deletes the
  file; the ledger keeps only the id, the hash and that it was forgotten. An item whose file is missing is treated
  as forgotten.
- **Conversation messages** are stored like task requests today (`TASK_SUBMITTED.body`): in the ledger, permanent.
  Forgetting a memory item does not remove the message it came from; the Memory page says so. A message the operator
  wants gone is a separate question for the spec (§13).
- The reception's prompts are not stored; `RECEPTION_DECIDED` stores the decision, the reply and the ids of the
  context items, so a decision can be explained without keeping the context itself.

## 8. API and client

- `POST /api/v1/conversations/messages` — `{project, text, reply_to?, conversation?, attachments?, intake_key}`;
  returns `{conversation, message}` at once. The decision follows after the quiet window of §4 rule 10 and comes as
  `RECEPTION_DECIDED` on `GET /api/v1/conversations/{id}/events` (JSON, or Server-Sent Events as for tasks), with
  the reply, its buttons and the task it started. `intake_key` makes a resent message idempotent, as for tasks
  (ADR 0016). Scope `submit`.
- `POST /api/v1/conversations/{id}/taps` — `{tap: "yes" | "differently" | "new_thing" | "make_task" | "forget:<mem>",
  text?}`. Scope `answer`.
- `GET /api/v1/conversations/{id}` — messages, decisions, linked tasks. Scope `read`.
- `GET|PATCH|DELETE /api/v1/memory/{scope}[/{id}]` — list, edit, pin, forget. Reading needs `read`; forgetting
  needs `answer`, so the chat's Forget button works; editing a text or pinning needs a web session (a named
  operator), not a token, because pinned memory steers every later task. Items noted from a message are written by
  the reception, under the token's data-class cap.
- Token caps apply: a token capped at `internal` never sees an item above `internal`, and its messages cannot raise
  a project's memory above its cap.
- The Python client and the TypeScript SDK gain `send_message`, `tap`, `conversation`, `memory`.

## 9. Surfaces

- **Web (08b).** The home page gets one input field like a search box, with a project picker next to it that
  remembers the last project and lists the projects of `ooat.toml` (nobody types a slug). The conversation runs
  below the field; the task detail (Gate, cost, diff, revert) is one click away, as today. The project's **Memory**
  page and an **Operator preferences** page.
- **Chat bridge and Telegram (08c).** The bridge sends each message to the conversation resource instead of
  creating a task; the reply, its buttons and the task's later progress come back as today. New button data:
  `y:<cnv>` (yes), `d:<cnv>` (differently), `n:<cnv>` (new thing), `t:<cnv>` (make it a task), `f:<mem>` (forget),
  `o:<cnv>` (keep as an open point), `x:<mem>` (an open point is done). A `switch` decision changes the chat's
  project as `/setdir` would; a `command` decision may offer to hand the message to the chat's other engine.
  `/setdir` and `/engine ooat` stay; `/pamet` shows pinned items, open points and the last summary. The bot's own
  changes are its task-04, planned after 08a.

## 10. Errors and limits

| Situation | Behaviour |
| --- | --- |
| Reception call fails | the message becomes a task as today, with one line saying so (§4) |
| Reception output fails its schema | one retry on the same tier, then escalation; then as above |
| Read-only answer hits 40 operations or its cost cap | partial answer, says so, offers **Make it a task** |
| Memory text refused by the secret scan | not stored; the reply says why |
| Memory file missing | treated as forgotten; the Memory page shows it as such |
| Context above budget | lower items of §5 are cut; the decision records which ids were used |
| Two messages at once in one conversation | handled in order of arrival; the second sees the first's decision |

## 11. Testing and measurement

- Unit tests with a fake gateway for every decision and rule of §4: at most two questions in a row; R2 and R3 always
  confirmed; a `Done when:` line wins; continuation by reply; 24 h silence closes; escalation below θ; fallback when
  the reception fails; the read-only grant refuses every write tool.
- Memory: the secret scan refuses a token-like text; forgetting deletes the file and the item disappears from the
  next context; data-class filtering leaves out an item above the route's class; a token capped at `internal` never
  reads a `client_confidential` item.
- **The owner's message set.** 20 to 30 real messages from the owner's Telegram, vague ones included, each with
  the expected decision (`answer`, `task`, `confirm`, `ask`, `continue_task`). The reception is measured against it
  in the eval runner (§11 of the spec) on each change of prompt or model, against the success criteria of §1. The
  messages are the owner's data: they live in the eval fixtures only after the owner has picked them and removed
  anything sensitive.

## 12. Wishlist (not in this design)

1. Progress in chat as one message edited in place; the diff behind a button. (The report of a finished task in the
   shape of §4 rule 4 is in this design since §14.)
2. The project guessed from the text without naming it ("the price on the Russian site"); naming it is `switch`
   (§14).
3. A proactive, read-only heartbeat (for example a morning summary of errors in logs).
4. The Claude Code connector started with Anthropic's `--advisor` for its own tasks.
5. Search over memory once it grows (SQLite FTS5, as the role index).
6. A longer web session that renews while it is used.

## 13. Open questions for the owner

- Should a conversation message itself be deletable (today task requests are permanent in the ledger)? Not needed
  for this design; a spec question if the owner wants it.
- The default caps (USD 0.02 average target, USD 0.05 per read-only answer, 40 operations, 3 000 tokens of context)
  are first guesses to be checked against the owner's message set before 08a ships.

## 14. Addendum after the bot's log (owner, 2026-10-15)

The owner's 293 messages to the Telegram bot (07–10/2026, three bots, cut at about 90 characters in the log) and the
first three OOAT tasks from Telegram (2026-10-13) were read before planning. What they show, and what the owner
approved in reply:

| Pattern in the log | Share | What the design does |
| --- | --- | --- |
| A reaction to the bot's last proposal ("Yes", "Option 1", "Subagent driven") | about 31 % | rule 8: the last options are in context |
| Answers to numbered questions ("1/ commit 2/ ok, push", "6-A, 7-…, 8-yes") | about 16 % | rule 8 |
| Questions about the state of work ("Is n8n running?", "Where did you stop?") | about 14 % | decision `status` |
| Commands (commit, push, deploy, restart a service) | about 9 % | decision `command`, rule 9 |
| Preferences about how to work ("save tokens", "use subagents") | about 7 % | operator preferences (§6) |
| Bursts (codes sent one by one, an article then a question) | several | rule 10 |
| Stop and correct ("Sorry. Do nothing.", "No. I mean this one…") | several | decision `cancel`; `continue_task` for a correction |
| Reminders ("Remind me at the end of the project", "Add it to unfinished tasks") | several | memory kind `todo` |
| Switching the project by text | 5 | decision `switch`, from the wishlist |

The three OOAT tasks of 2026-10-13 each stopped at rule A1's question that the task had no acceptance criteria; the
answer, sent as a new message, became a separate task, and the next message ("pick only the goals not met yet")
became a third task without the previous result. Their documents were good; the interaction was not. §4 rule 3 (the
reception writes the criteria) and `continue_task` cover this; the three messages are cases of the message set
(§11).

Approved (owner, 2026-10-15, points 1–6):

1. Decisions `status` and `cancel`. `status` answers from the ledger only: the conversation's tasks, open tasks of
   the project with their questions, and open points; no model reads files for it. `cancel` stops the running
   task of the conversation through the existing cancel (a DECISION by the operator) and says that its file changes
   can be reverted once it closes.
2. Numbered next steps (rule 8). When a task started from a conversation closes, the reception writes its report
   (`CONVERSATION_REPORTED`): what was asked, how it was solved, the state now, and numbered options for what next,
   in the message's language and sized to the work (§4 rule 4).
3. Commands (rule 9): decision `command` with **Keep as an open point**; handing the message to another engine of
   the chat is the bridge's (08c). Running commands comes with containers (part 2).
4. Bursts (rule 10): a quiet window per conversation, default 60 s after the last message (`[reception] batch_seconds`;
   the owner, 2026-10-16: 8 s is too short to write the next message). Every reply waits for the window; a message
   that arrives later is still understood through `continue_task`.
5. Memory kind `todo`: an open point noted from a request ("remind me", "add it to unfinished") or from a
   `command`; it stays in the project's status and on the Memory page until it is marked done.
6. Switching the project by text (`switch`), moved from the wishlist: the reception sees the slugs of
   `ooat.toml`'s projects and decides `switch` only for one of them; the surface applies it (08c).

The reply comes asynchronously (§8): a decision may read files for a minute, and a burst must be waited for, so the
API records a message at once and the decision follows on the conversation's event stream, as a task's progress
does.

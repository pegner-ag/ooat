# The Web App Talks to the Reception (08b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The web app's home page gets one input field, like a search box. Next to it is a project picker that
remembers the last project. The conversation with the reception runs below the field: replies, numbered options,
buttons, the tasks it started and their reports. A project's **Memory** page and the **Operator preferences** page
list memory items with edit, pin, done and forget.

**Architecture:**
- The web app uses the 08a REST API as it is. The server gains one read endpoint, `GET /api/v1/projects`, because
  nothing lists the projects of `ooat.toml` today. It also serves the app's shell at the new addresses.
- One new pure module, `conversation.js`, turns a conversation's events into what the page shows. It is tested in
  Node like `timeline.js`.
- Two new views:
  - `views/home.js`: the box and the conversation. The inbox's lists stay below them.
  - `views/memory.js`: the Memory page and the Operator preferences page.
- `views/conversation.js` shows one conversation by its id. The server's redaction notice already links there
  (`views.conversation_stub`).

**Tech Stack:** Plain JavaScript ES modules with JSDoc types, checked by `npm run check` (tsc, `checkJs`, strict) and
tested by `npm test` (`node --test`), both from `core/`, no build step (ADR 0016). FastAPI and pytest for the
endpoint.

**Spec:** `tasks/f1-skeleton/task-08-reception/design.md` §6, §8, §9 (web), §14; operator UX design
(`../task-05-operator-ux/design.md` §4, §6); ADR 0016, ADR 0018.

## Global Constraints

- The page builds elements only through `dom.js` `h`. It never builds HTML from data, and only `markdown.js` writes
  HTML (`core/tests/test_web.py` holds this rule).
- Every request carries the session key (`api.js`). The page reads Server-Sent Events through `fetch`, never through
  `EventSource`.
- English and Czech strings have the same keys (`i18n/cs.js` is type-checked against `i18n/en.js`).
- A stubbed reply (`{redacted, link}` above the session's cap) shows `common.redacted`, with no buttons and no
  options.
- Editing a memory text and pinning go through the web session (the server refuses tokens). Forgetting asks for one
  confirmation.
- Typed text is never wiped by a refresh or a stream redraw. This is the inbox's rule: wait while the focus is
  inside.
- No new dependency. Lines are at most 120 characters. Code, comments, docs and commits are in English.
- Explicit git paths in every commit, never `git add -A`.

**Decisions this plan takes where the design is silent** (for the owner's review):

1. **New endpoint `GET /api/v1/projects` (scope `read`).** It returns `{projects: [{project, data_class, write,
   folders: n}]}`, sorted by slug. It lists the projects of `ooat.toml` within the reader's cap, followed by the
   projects of the reader's conversations and tasks that `ooat.toml` lacks (with `folders: 0`). Folder paths are not
   returned: the picker needs names only. The picker lists exactly these projects, so nobody types a slug. With no
   project at all, the box says to add one to `ooat.toml`.
2. **The detailed task form stays, folded.** It sits under the box as "A task with exact criteria" (a closed
   `<details>`): acceptance, data class, budget. Scripts and the owner keep a way to submit a task as before. The
   `?sample` link from Setup opens it filled in.
3. **The home page shows the open web conversation of the chosen project.** A conversation is per channel, so a
   Telegram conversation is never continued from the web. Below the conversation, the page lists the project's last
   five conversations from every channel (channel, time, first words). Each links to its read-only page.
4. **Forget and Done use the memory endpoints, as in the chat (08c).** A button keeps working after its conversation
   closes. **Make it a task**, **Yes**, **New thing** and **Keep as an open point** are taps. **Differently** opens
   a one-line field under the reply and sends the tap with that text.
5. **Replies and reports are rendered as Markdown** through `markdown.js`, with raw HTML off. Numbered options
   follow as an ordered list. Typing "2" or "1/ yes 2/ no" in the box answers them (rule 8); there is no button
   per option.
6. **Enter sends, Shift+Enter makes a new line.** After sending, the message shows at once with a status line:
   "Received. The reception replies once you stop writing for a moment." The status line never names a number of
   seconds, which is `[reception] batch_seconds` on the server.
7. **Memory items are not added by hand on the web.** No create endpoint exists, and "Remember …" in the box does it
   through the reception, with the secret scan. The Memory page lists, edits, pins, marks done and forgets. It shows
   done open points behind a toggle.
8. **The header's navigation gains "Memory".** It links to the Memory page of the project last chosen in the picker.
   From there, one link leads to the Operator preferences page. The nav does not grow by two entries.

## Review Focus

- A tap's decision comes back in the tap's response and on the stream: it is shown once (dedup by event id).
- The stream ends after 15 minutes or drops. The next stream starts after the last event shown, so nothing is shown
  twice and nothing is missed.
- A double Enter or a retry after a network error sends one message: one `Idempotency-Key` per typed message.
- Switching the project in the picker while a conversation is followed stops the old stream. Replies of the old
  project never appear under the new one.
- A half-typed message, or a half-typed "Differently" correction, survives the 15-second refresh of the lists and
  any new reply on the stream.

Line 1 has its test in task 2 (`conversation.js` `shown`), line 2 in task 2 (`api.js` `follow`), and lines 3 to 5
are checked by hand in task 3's step "check in the browser", since the views have no DOM tests (as for the inbox
today).

---

## File Structure

| File | Responsibility |
| --- | --- |
| `core/src/ooat_core/endpoints.py` or `conversation_endpoints.py` (modify) | `GET /projects` |
| `core/src/ooat_core/api.py` (modify) | the shell for `/conversations/{id}`, `/memory/{scope}` |
| `core/tests/test_conversation_api.py`, `core/tests/test_web.py` (modify) | the endpoint, the shell paths |
| `core/src/ooat_core/web/app/api.js` (modify) | `follow` for a task or a conversation |
| `core/src/ooat_core/web/app/conversation.js` (create) | events → shown turns; tap labels; open conversation |
| `core/src/ooat_core/web/app/views/home.js` (create) | the box, the picker, the live conversation, the lists |
| `core/src/ooat_core/web/app/views/inbox.js` (modify) | exports the lists and the folded task form for home |
| `core/src/ooat_core/web/app/views/conversation.js` (create) | one conversation by id |
| `core/src/ooat_core/web/app/views/memory.js` (create) | Memory and Operator preferences |
| `core/src/ooat_core/web/app/app.js`, `app.css`, `i18n/en.js`, `i18n/cs.js` (modify) | routes, nav, look, strings |
| `core/web-tests/conversation.test.mjs` (create), `core/web-tests/api.test.mjs` (modify) | Node tests |
| `docs/description.md` (modify) | the web app as built |

### Task 1: The project list and the new addresses

**Files:**
- Modify: `core/src/ooat_core/conversation_endpoints.py` (the route sits with the conversations, which need it),
  `core/src/ooat_core/api.py`
- Test: `core/tests/test_conversation_api.py`, `core/tests/test_web.py`

**Interfaces:**
- Produces: `GET /api/v1/projects -> {"projects": [{"project": str, "data_class": str, "write": bool,
  "folders": int}]}`, plus the app shell at `/conversations/{conversation}`, `/memory/{scope}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_projects_lists_the_configured_ones_within_the_cap_and_those_seen(tmp_path):
    served = Served(tmp_path, projects={"docs": {"folders": [str(tmp_path)], "data_class": "internal"},
                                        "hr": {"folders": [str(tmp_path / "hr")], "data_class": "personal"}})
    served.message("eshop", "Ahoj")  # a project only seen in a conversation
    listed = served.client.get("/api/v1/projects", headers=served.token(max_data_class="internal")).json()
    assert listed == {"projects": [{"project": "docs", "data_class": "internal", "write": False, "folders": 1},
                                   {"project": "eshop", "data_class": "internal", "write": False, "folders": 0}]}


def test_projects_never_returns_a_folder_path(tmp_path):
    served = Served(tmp_path, projects={"docs": {"folders": [str(tmp_path)]}})
    assert str(tmp_path) not in served.client.get("/api/v1/projects", headers=served.web()).text
```

Add `"/conversations/cnv_01ABC"`, `"/memory/docs"` and `"/memory/operator"` to the paths of
`test_the_app_shell_is_served_for_each_screen_without_a_session`. Use the fixtures the file already has; the names
above (`Served(projects=…)`, `message`, `token`, `web`) are to be matched to them.

- [ ] **Step 2: Run them and see them fail** — `.venv/Scripts/python -m pytest -q -p no:cacheprovider
  core/tests/test_conversation_api.py core/tests/test_web.py`. Expected: 404 for `/api/v1/projects` and the new
  shell paths.

- [ ] **Step 3: Implement**

```python
    @api.get("/projects")
    def list_projects(request: Request, who: Principal = Depends(scope("read"))) -> dict:
        """The projects a picker offers (design 08 §9): ooat.toml's within the reader's cap, then the projects of the
        reader's conversations and tasks it lacks. Names only, never a folder path."""
        server = server_of(request)
        listed = {slug: {"project": slug, "data_class": p.data_class, "write": p.write, "folders": len(p.folders)}
                  for slug, p in server.config.projects.items() if views.within(p.data_class, who.max_data_class)}
        events = server.runtime().ledger.events(types=["TASK_SUBMITTED", "CONVERSATION_MESSAGE"])
        for event in events:
            slug = event["body"].get("project")
            if slug and slug not in listed and slug not in server.config.projects \
                    and event["actor"]["id"] == who.operator:
                listed[slug] = {"project": slug, "data_class": "internal", "write": False, "folders": 0}
        return {"projects": [listed[slug] for slug in sorted(listed)]}
```

Check the actor field of `TASK_SUBMITTED` against `views.task_summary` (a task's submitter) before relying on
`actor.id`. In `app_routes`, add `/conversations/{conversation}` and `/memory/{scope}` like `/tasks/{task}`.

- [ ] **Step 4: Run the tests and see them pass**, then the whole core suite.

- [ ] **Step 5: Commit** — `git add core/src/ooat_core/conversation_endpoints.py core/src/ooat_core/api.py
  core/tests/test_conversation_api.py core/tests/test_web.py`, then
  `git commit -m "feat: GET /projects for the picker, the shell for the new pages (08b task 1)"`.

### Task 2: What a conversation shows, and following it

**Files:**
- Create: `core/src/ooat_core/web/app/conversation.js`, `core/web-tests/conversation.test.mjs`
- Modify: `core/src/ooat_core/web/app/api.js`, `core/web-tests/api.test.mjs`

**Interfaces:**
- Produces:
  - `api.follow(task, after, onEvent, signal)` stays as it is.
  - `api.followConversation(conversation, after, onEvent, signal)` does the same for
    `/conversations/{id}/events` and ends at `CONVERSATION_CLOSED`. Both use one inner `stream(path, end, …)`.
  - `conversation.js`:
    - `REPLACED = ["escalated", "retried"]`;
    - `shown(events: any[]): Turn[]`. A `Turn` is
      `{id, ts, who: "you" | "reception" | "report" | "closed", text: string | null, redacted: boolean,
      options: string[], buttons: string[], task: string | null, project: string}`. It is in event order, one turn
      per event id, without replaced decisions. A tap message's text is its label (`tapLabel`), plus its
      `tap_text` after a colon.
    - `tapLabel(tap: string): Key`, the i18n key of a button (`conv.yes`, `conv.differently`, `conv.newThing`,
      `conv.makeTask`, `conv.todo`, `conv.forget`, `conv.done`).
    - `openOf(list: any[], project: string): string | null`, the newest conversation of `GET /conversations` that
      is not closed and whose channel is `web`.

- [ ] **Step 1: Write the failing tests**

```js
import assert from "node:assert/strict";
import { test } from "node:test";
import { openOf, shown } from "../src/ooat_core/web/app/conversation.js";

const ev = (id, type, body) => ({id, ts: "2026-10-17T10:00:00Z", type, actor: {kind: "system", id: "x"}, refs: [],
  cost: null, body: {conversation: "cnv_1", project: "docs", data_class: "internal", ...body}});

test("a message, its decision and a report become three turns; a replaced decision is left out", () => {
  const turns = shown([ev("e1", "CONVERSATION_MESSAGE", {text: "Změň titulek"}),
    ev("e2", "RECEPTION_DECIDED", {decision: "escalated", reply: "x", options: [], buttons: []}),
    ev("e3", "RECEPTION_DECIDED", {decision: "confirm", reply: "Mám začít?", options: ["A", "B"],
      buttons: ["yes", "differently"]}),
    ev("e4", "CONVERSATION_REPORTED", {task: "tsk_1", reply: "Hotovo.", options: ["Push"]})]);
  assert.deepEqual(turns.map((turn) => [turn.who, turn.text]),
    [["you", "Změň titulek"], ["reception", "Mám začít?"], ["report", "Hotovo."]]);
  assert.deepEqual(turns[1].options, ["A", "B"]);
});

test("the same event twice (a tap's response and the stream) is one turn", () => {
  const decided = ev("e3", "RECEPTION_DECIDED", {decision: "task", reply: "Spouštím.", task: "tsk_1", options: [],
    buttons: []});
  assert.equal(shown([decided, decided]).length, 1);
});

test("a stubbed reply is redacted, without buttons or options", () => {
  const [turn] = shown([ev("e3", "RECEPTION_DECIDED", {decision: "ask", reply: {redacted: "…", link: "/x"},
    options: {redacted: "…"}, buttons: ["yes"]})]);
  assert.deepEqual([turn.redacted, turn.text, turn.options, turn.buttons], [true, null, [], []]);
});

test("the open web conversation of the project, never a Telegram one or a closed one", () => {
  const list = [{conversation: "cnv_3", project: "docs", channel: "token:t1", closed: null},
    {conversation: "cnv_2", project: "docs", channel: "web", closed: "2026-10-16T10:00:00Z"},
    {conversation: "cnv_1", project: "docs", channel: "web", closed: null}];
  assert.equal(openOf(list, "docs"), "cnv_1");
  assert.equal(openOf(list, "eshop"), null);
});
```

In `api.test.mjs`, the test of the task stream gets a twin. `followConversation` reconnects after a dropped stream
with `Last-Event-ID` of the last event, and ends at `CONVERSATION_CLOSED`.

- [ ] **Step 2: Run them and see them fail** — `npm test` in `core/`.

- [ ] **Step 3: Implement.** Move the body of `follow` into `stream(path, end, after, onEvent, signal)`. `follow`
  calls it with `/tasks/{id}/events` and `"TASK_CLOSED"`, and `followConversation` calls it with
  `/conversations/{id}/events` and `"CONVERSATION_CLOSED"`. `shown` keeps a `Set` of seen ids, and maps the event
  types as in the table:

  | Event | Turn |
  | --- | --- |
  | `CONVERSATION_MESSAGE` with `text` | `you`, the text |
  | `CONVERSATION_MESSAGE` with `tap` | `you`, the tap's label (`: tap_text` when there is one) |
  | `RECEPTION_DECIDED`, decision in `REPLACED` | none |
  | `RECEPTION_DECIDED` | `reception`, `reply`, `options`, `buttons`, `task` |
  | `CONVERSATION_REPORTED` | `report`, `reply`, `options`, `task` |
  | `CONVERSATION_CLOSED` | `closed`, the reason |

  A string field is shown text; anything else in `reply` (the server's stub) sets `redacted` and empties `options`
  and `buttons`.

- [ ] **Step 4: Run `npm test` and `npm run check`; both pass.**

- [ ] **Step 5: Commit** — `git add core/src/ooat_core/web/app/conversation.js core/src/ooat_core/web/app/api.js
  core/web-tests/conversation.test.mjs core/web-tests/api.test.mjs`, then
  `git commit -m "feat: the web app reads and follows a conversation (08b task 2)"`.

### Task 3: The home page: the box, the picker and the conversation

**Files:**
- Create: `core/src/ooat_core/web/app/views/home.js`, `core/src/ooat_core/web/app/views/conversation.js`
- Modify: `core/src/ooat_core/web/app/views/inbox.js`, `app.js`, `app.css`, `i18n/en.js`, `i18n/cs.js`

**Interfaces:**
- Consumes: task 1's `/projects`, task 2's `followConversation`, `shown`, `openOf`, `tapLabel`.
- Produces:
  - `home(root, ctx)` is the `/` route. It replaces `inbox` there.
  - `inbox.js` exports `lists(ctx)` (`{element, draw}`: waiting, stuck, tasks, as today) and `taskForm(ctx)` (the
    form of today, inside a closed `<details>`).
  - `conversationPage(root, ctx, id)` is the `/conversations/{id}` route.
  - `turnElement(turn, ctx, actions)` is shared by both pages. `actions` is null on a read-only page.
  - `PROJECT_STORAGE = "ooat.project"`, in `localStorage`, read with a fallback.

The home page from top to bottom:

1. The box: a `textarea` (rows 2, grows to 8), the picker (`select` of `/projects`; the stored project if listed,
   else the first), a file input and **Send**. Enter sends and Shift+Enter makes a new line. Sending posts
   `/conversations/messages` with `{project, text, conversation?}` and `Idempotency-Key` (a new `crypto.randomUUID()`
   only after a success). Attachments are encoded with `base64` and capped at 14 MB, as in the task form. The box is
   cleared only after the server accepted the message.
2. The conversation. The list `GET /conversations?project=<p>&limit=20` gives `openOf`, and its events are fetched
   from `GET /conversations/{id}/events`. Each turn is drawn with `turnElement`, and `followConversation` adds new
   ones after the last id. A new message without a conversation starts one: the response's `conversation` is
   followed from its `message`. The status line from decision 6 shows until the next reception turn.
3. `turnElement`:
   - `you` turns are right-aligned plain text.
   - `reception` and `report` turns are Markdown (`showMarkdown`), then an `<ol>` of options, then one button per
     tap.
   - A turn with a `task` gets a line linking to `/tasks/<task>`.
   - Taps post `/conversations/{id}/taps`, and the decision in the response is drawn through `shown`, deduplicated
     by id.
   - `forget:<mem>` is a `DELETE /memory/<project>/<mem>` after `confirm(t("conv.forgetConfirm"))`.
     `done:<mem>` is `PATCH {done: true}`.
   - **Differently** shows a one-line field with **Send**. The field's text goes as the tap's `text`.
   - A redacted turn shows `common.redacted` and a link to the page.
4. "Earlier conversations": the last five of the list (any channel), each a link with its channel and start time.
5. The folded task form, then `lists(ctx)` as on the inbox today, refreshed every 15 s while the focus is outside.

Changing the picker stores the project, aborts the conversation's stream (its own `AbortController`, linked to
`ctx.signal`) and draws the conversation of the new project.

`conversationPage` fetches `GET /conversations/{id}` and draws its events with `turnElement`. It passes `actions`
only when the conversation is open and its channel is `web`; otherwise the page is read only.

- [ ] **Step 1: Write the strings first** (en and cs, same keys): `home.placeholder`, `home.project`, `home.send`,
  `home.received`, `home.noProjects`, `home.earlier`, `home.exactTask`, `conv.yes`, `conv.differently`,
  `conv.newThing`, `conv.makeTask`, `conv.todo`, `conv.forget`, `conv.done`, `conv.forgetConfirm`, `conv.correction`,
  `conv.task`, `conv.closed`, `conv.readOnly`, `conv.title`, `nav.memory`. `npm run check` fails until both files
  have them.
- [ ] **Step 2: Split `inbox.js`** into `lists` and `taskForm` without changing what they do, and route `/` to
  `home`. Run `npm run check`.
- [ ] **Step 3: Write `views/home.js` and `views/conversation.js`** as described, and the CSS (`.turn`, `.turn.you`,
  `.box`). The layout stays one column on a phone (720 px).
- [ ] **Step 4: Run `npm run check` and `npm test`**, then the core suite (the shell test and
  `test_only_the_markdown_view_writes_html_and_nothing_evaluates_code`).
- [ ] **Step 5: Check in the browser** with `ooat serve`, run from a short folder (lessons: the 260-character path
  limit), with a fake or a real connector. Check:
  - a burst of two messages gets one reply;
  - Yes, Differently with a correction, and Forget each work;
  - a task started from the conversation links to its page, and its report arrives;
  - each line of the Review Focus.
- [ ] **Step 6: Commit** — `git add` the files above by name, then
  `git commit -m "feat: the home page talks to the reception (08b task 3)"`.

### Task 4: Memory and Operator preferences

**Files:**
- Create: `core/src/ooat_core/web/app/views/memory.js`
- Modify: `app.js`, `app.css`, `i18n/en.js`, `i18n/cs.js`

**Interfaces:**
- Consumes: `GET /memory/{scope}?done=…`, `PATCH /memory/{scope}/{mem}` (`text`, `pinned`, `done`), and
  `DELETE /memory/{scope}/{mem}`.
- Produces: `memoryPage(root, ctx, scope)` for `/memory/{scope}`. The scope `operator` is the Operator preferences
  page.

The page:
- The heading is the project, or "Operator preferences" for the scope `operator`.
- A link switches between the project's page and the preferences.
- Items are grouped by kind (pinned first, then fact, glossary, preference, todo, summary), newest first. Each item
  shows its text, data class, date and a source link (`/conversations/<id>`, or the task).
- Each item has four actions:
  - **Edit** turns the text into a textarea with **Save**/**Cancel** and sends `PATCH {text}`. A refusal (the
    secret scan, 400) is shown under the item.
  - **Pin**/**Unpin** sends `PATCH {pinned}`.
  - **Done** (todo only) sends `PATCH {done: true}`.
  - **Forget** asks `confirm(t("memory.forgetConfirm"))`, then sends `DELETE`.
- A checkbox "show done open points" reloads with `done=true`.
- One muted line says that forgetting deletes the text, and that the message it came from stays in the conversation
  (design §7).
- The header gets **Memory**, which links to `/memory/<stored project>` (decision 8). It links to
  `/memory/operator` when no project is stored.

- [ ] **Step 1: Strings** (en, cs): `memory.title`, `memory.preferences`, `memory.toPreferences`,
  `memory.toProject`, `memory.kind.*` for the five kinds and pinned, `memory.edit`, `memory.save`, `memory.cancel`,
  `memory.pin`, `memory.unpin`, `memory.done`, `memory.forget`, `memory.forgetConfirm`, `memory.showDone`,
  `memory.empty`, `memory.source`, `memory.forgetNote`.
- [ ] **Step 2: Write `views/memory.js`**, its route in `app.js` (`/^\/memory\/([a-z0-9_-]+)$/`) and the nav entry.
- [ ] **Step 3: Run `npm run check` and `npm test`.**
- [ ] **Step 4: Check in the browser:**
  - edit, pin, done and forget an item;
  - an edit holding a token-like text is refused, with the reason shown;
  - a forgotten item is gone after a reload, and from the next reception context (`ooat ask` in the same project).
- [ ] **Step 5: Commit** — `git add core/src/ooat_core/web/app/views/memory.js` and the modified files by name, then
  `git commit -m "feat: the web's Memory and Operator preferences pages (08b task 4)"`.

### Task 5: The docs as built

**Files:** `docs/description.md`, `tasks/f1-skeleton/task-08-reception/design.md` (status line only), and
`.claude/lessons.md` when something non-obvious turned up.

- [ ] Describe the home page, the conversation page, Memory and Operator preferences, and `GET /projects` where the
  web app and the REST API are described. Remove "the web app … move to it with plans 08b" from the reception's
  paragraph.
- [ ] Run the whole suite: the core suite, then `npm run check` and `npm test` in `core/`.
- [ ] Commit by explicit paths: `docs: the web app talks to the reception (08b task 5)`.

## After the plan

- A review of the branch (the `reviewer` role):
  - the DOM rule (no HTML from data);
  - the session key on every request;
  - `GET /projects` leaking nothing above the cap, and no folder path;
  - redaction;
  - the Review Focus.
- A PR to `main`. Merging and the production update (`C:\scripts\OOAT`, a restart of `OoatServe`) happen only on the
  owner's go.
- Still out: wishlist §12, and the owner's eval message set (the candidates wait for the owner's choice).

# Reception, Conversations and Project Memory in the Core (08a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person's message to `ooat-core` becomes, through one reception call, a direct answer, one question, a
confirmation, a task with goal and acceptance criteria written by the reception, the continuation of an earlier task,
a status from the ledger, a cancel, an honest "OOAT cannot run that", or a project switch. It lives in a conversation
that continues across tasks, and project memory the operator can forget.

**Architecture:** New package `ooat_core.reception`:
- `context.py` gathers what the reception sees, within a budget;
- `model.py` holds the prompts and the calls through the gateway, with output checked against
  `spec/schemas/reception.schema.json`;
- `__init__.py` holds `Reception`, which records messages and taps, applies the design's rules to the model's
  decision and acts through `Runtime`, `hil.answer` and the memory module;
- `desk.py` is the thread of `ooat serve`: it waits for a quiet window, decides, writes the reports of finished tasks
  and closes silent conversations.

Two more core modules come with it. `conversations.py` is a pure projection over the ledger, like `state.py`.
`memory.py` holds the memory texts in their own folder beside the ledger, with a secret scan. The REST resource is
`conversation_endpoints.py`, the Python client gains its methods, and `ooat ask` runs the reception from the CLI.

**Tech Stack:** Python 3.12+ standard library, FastAPI and Pydantic v2 (already used), jsonschema (already used),
pytest. No new dependency.

**Spec:** `tasks/f1-skeleton/task-08-reception/design.md` (approved 2026-10-15, addendum §14 the same day); ADR 0018
with its amendment; ADR 0009, 0010, 0011, 0016, 0017; spec §3, §6, §7, §10.

## Global Constraints

- Only `ooat-core` writes the ledger; it is append-only. The reception's events are written by `Reception`; a
  surface never builds an event.
- Every model call goes through the provider gateway with a declared data class, at least the project's (ADR 0010,
  ADR 0017). No client calls a model.
- R2 and R3 are never decided by a model: a reception decision whose `risk_hint` is R2 or R3 is always a `confirm`,
  and the reception never lowers a risk class (ADR 0011, ADR 0018 point 3).
- Memory texts never enter the ledger. `MEMORY_*` events carry ids and SHA-256 hashes only (ADR 0018 point 6);
  forgetting deletes the file.
- A text that the secret scan flags is never stored as memory. The reply says why, without quoting it.
- Project memory never crosses projects. Operator preferences (scope `operator`) are the one shared section, at most
  20 items.
- A token's data-class cap applies to every conversation and memory read (views stub what is above it). A token
  never edits a memory text or pins an item; it may forget one and mark an open point done.
- A direct answer reads only: grant `write = false`, at most 40 operations, and its estimate must be at most
  USD 0.05 (`[reception] max_answer_usd`).
- The reception runs no command and never submits a task for a `command` decision.
- Defaults, all in `[reception]` of `ooat.toml`: `batch_seconds = 8`, `silence_hours = 24`, `context_tokens = 3000`,
  `max_answer_usd = 0.05`, `max_answer_operations = 40`, `theta = 0.7`.
- No new dependency. Tests stay offline: fake connectors only.
- Code, comments, docs and commits are in English, with lines of at most 120 characters. Reception replies use the
  message's language; the fallback line is Czech or English by the message.
- Explicit git paths in every commit, never `git add -A`.

**Decisions this plan takes where the design is silent** (for the owner's review):

1. **The reply is asynchronous** (design §8, addendum §14). `POST /conversations/messages` returns
   `{conversation, message}` at once, and the decision comes as an event on `GET /conversations/{id}/events`. A tap
   (`POST /conversations/{id}/taps`) is decided at once and returned in its response, because it needs no model call
   and no batch.
2. **The reception's interim θ is 0.7, not the 1.0 of a text-model Gate decision.** ADR 0011's 1.0 keeps a text
   model from acting alone on a Gate rule. A reception decision only proposes a task, and that task still passes the
   Gate with its own rules, so a wrong reception decision costs one task that the operator can cancel and revert.
   - Below 5 rated reception decisions, θ is `[reception] theta`.
   - From 5 to 19, θ is the larger of that and the computed one.
   - From 20 on, θ is the computed one (ε of R1).
3. **Verdicts on reception decisions come from the conversation, not from `TASK_RATED`.**
   - A **Yes** tap on a confirmation confirms the proposed decision; **Differently** corrects it.
   - A task cancelled within 2 minutes of its start corrects the decision that started it.
   - An accepted rating of that task confirms it.

   The design's "rated not what I meant" has no rating option yet, so it is left out.
4. **Escalation is by θ only.** A message carries no task value, so "a task above `v_min`" cannot be known at the
   reception; a task's value is still handled by the Gate.
   - The first call is recorded as a `RECEPTION_DECIDED` with `decision: "escalated"` and its cost.
   - The workhorse decision follows as a second `RECEPTION_DECIDED`.
   - When even that is below θ, a `task` or `continue_task` becomes a `confirm`.
5. **Context budget order** (design §5). The current messages and the last 4 turns are never cut. Material is cut in
   this order: older summaries first, then older turns, then unpinned memory, then the project's instructions.
   Preferences are never cut. Size is measured as characters / 4.
6. **A continuation goes to the task in this order:**
   - an open question of that task that takes text (`clarify`, `narrow_scope`) is answered with the message (rule 3:
     the Gate's question answered inside the conversation, `HIL_RESPONSE` as before);
   - otherwise a follow-up task starts, with `follows` and the earlier task's document as the untrusted attachment
     `previous-task.md`. The runner is Solo, so it runs after the earlier one.
7. **Memory location:** `ooat-memory/` beside a file ledger, as `ooat-login/`, one `<mem id>.txt` per item, UTF-8.
   An in-memory ledger has no memory store: the reception works without memory. The folder is added to the
   workspace grant's hidden paths.
8. **Secret scan for memory:**
   - a PEM header;
   - a `password|passwd|pwd|secret|token|api key` word followed by `:` or `=` and a value;
   - a connection string with `password=` or `pwd=`;
   - known token prefixes (`sk-`, `ghp_`, `github_pat_`, `xox`, `AKIA`, `ooat_`);
   - a long mixed run of the shape the workspace already hides.

   Personal data does not refuse an item: it raises the item's class (pii.py), as the design says.
9. **A message's attachments** are stored as untrusted artifacts referenced by its `CONVERSATION_MESSAGE`. The
   reception sees their names and first 1 000 characters, and a task started from the message gets them as its
   files.
10. **Reports** are written when the runner closes a conversation's task: the runner calls back into the desk.
    The desk's 60 s tick also catches any report missed across a restart.
11. **`ooat ask --project P "text"`** decides in the foreground (no batch window) and prints the reply and the task
    it started. It lets the owner try the reception before 08b and 08c ship.
12. **The eval runner for the owner's message set** is a script, `evals/reception/run.py`, run by the owner with real
    connectors. The repository holds only a made-up example set (`evals/reception/example.json`). The owner's own
    set lives outside the repository until the owner has picked and cleaned it (design §11).

## Review Focus

- **A message that arrives while the decision on the previous one runs.** The second message must not be decided
  twice, and neither message may be lost. Batches are taken under a lock, and "undecided" is a ledger fact (a
  message with no later `RECEPTION_DECIDED` naming it). Test in Task 7.
- **A model reply that is not JSON, or JSON that breaks the schema** (a fenced block, a trailing comment, an
  unknown decision, a `switch` to a project that is not configured). It gets one retry on the same tier, then the
  fallback task; a bad `switch` becomes an `ask`. Tests in Task 5.
- **A message whose text has personal data in a project of class `internal`.** The decision call, the stored message
  and any memory note must all be raised to `personal`. A token capped at `internal` then sees stubs only. Tests in
  Tasks 5 and 9.
- **"Forget" from a token on an item above its cap**, or on another project's item. It must be refused, never a
  silent no-op. Test in Task 9.
- **A burst that straddles a task's start.** Message 1 starts a task, and message 2 arrives 3 s later. Message 2 must
  see the started task in its context, so it can be a `continue_task`, not a second unrelated task. Test in Task 5.

## File Structure

| File | Responsibility |
|---|---|
| `core/src/ooat_core/ids.py` (modify) | prefixes `cnv`, `mem` |
| `spec/schemas/event.schema.json` (modify) | new event types and bodies, `task: null` rules, `TASK_SUBMITTED.conversation`, `WORKSPACE_USED` of a conversation, `QUOTA_WARNING` with `task: null` |
| `spec/schemas/reception.schema.json` (create) | the model's decision output |
| `core/src/ooat_core/ledger.py` (modify) | intake key check for `CONVERSATION_MESSAGE` |
| `core/src/ooat_core/config.py` (modify) | `[reception]` |
| `core/src/ooat_core/connectors/__init__.py`, `gateway.py` (modify) | `ModelRequest.conversation`; a call belongs to a task or a conversation |
| `core/src/ooat_core/memory.py` (create) | memory store, secret scan, note / edit / forget / done, projection |
| `core/src/ooat_core/conversations.py` (create) | conversation projection: open, history, undecided messages, options, views |
| `core/src/ooat_core/reception/__init__.py` (create) | `Reception`: receive, decide, tap, report, close; the rules |
| `core/src/ooat_core/reception/context.py` (create) | the context within the budget |
| `core/src/ooat_core/reception/model.py` (create) | prompts, calls, parsing, the read-only answer |
| `core/src/ooat_core/reception/desk.py` (create) | the thread: quiet window, reports, silence |
| `core/src/ooat_core/runtime.py` (modify) | `submit(conversation=…)` |
| `core/src/ooat_core/workspace/runs.py`, `grant.py` (modify) | `record(conversation=…)`, hidden memory folder |
| `core/src/ooat_core/thresholds.py` (modify) | reception verdicts and θ |
| `core/src/ooat_core/runner.py` (modify) | `on_closed` callback |
| `core/src/ooat_core/api.py`, `conversation_endpoints.py` (create), `views.py`, `stats.py` (modify) | REST resource, caps, the reception's cost line |
| `core/src/ooat_core/reception_cli.py` (create), `operator_cli.py` (modify) | `ooat ask` |
| `sdk/python/src/ooat_client/client.py` (modify) | `send_message`, `tap`, `conversation`, `conversation_events`, `follow_conversation`, `memory`, `forget` |
| `evals/reception/` (create) | `run.py`, `example.json`, `README.md` |
| Docs | `core/description.md`, `docs/description.md`, `docs/chat-bridge.md`, `sdk/python/README.md`, `.claude/lessons.md` |

---

### Task 1: Schemas, ids and the ledger's intake check

**Files:**
- Modify: `core/src/ooat_core/ids.py`, `spec/schemas/event.schema.json`, `core/src/ooat_core/ledger.py`
- Create: `spec/schemas/reception.schema.json`
- Test: `core/tests/test_conversation_events.py` (create), `core/tests/test_ids.py`

**Interfaces:**
- Produces:
  - `new_id("cnv")` and `new_id("mem")`;
  - the event types `CONVERSATION_MESSAGE`, `RECEPTION_DECIDED`, `CONVERSATION_REPORTED`, `CONVERSATION_CLOSED`,
    `MEMORY_NOTED`, `MEMORY_EDITED`, `MEMORY_FORGOTTEN`;
  - `validate("reception", decision)`;
  - `DuplicateIntake.earlier` (the earlier event).

Event bodies. `additionalProperties: false` everywhere, every new type has `task: null`, and the actor rules are the
design's:

```
CONVERSATION_MESSAGE  (hil)    conversation, project, channel, text? | tap?, tap_text?, reply_to? (evt), intake_key?,
                               data_class, attachment_names?        -- text or tap required
RECEPTION_DECIDED     (system) conversation, project, messages [evt, 1..], decision, reply?, interpretation?,
                               options [text, ≤ 9], buttons [enum], task? (tsk started or targeted),
                               cancelled? [tsk], switch_to? (slug), memory? [mem], pending? {goal, acceptance,
                               risk_class?, follows?}, record? {engine, model, confidence, threshold},
                               context [ids], data_class, fallback? (bool), reading? (bool)
CONVERSATION_REPORTED (system) conversation, project, task, reply, options [text], data_class
CONVERSATION_CLOSED   (system) conversation, project, reason (silence|new_conversation|switched|operator),
                               summary? (mem)
MEMORY_NOTED          (system|hil) memory, scope, kind (preference|fact|glossary|summary|todo), data_class,
                               source (evt|tsk), sha256, conversation?, pinned?
MEMORY_EDITED         (hil)    memory, sha256?, pinned?, done?, channel
MEMORY_FORGOTTEN      (hil)    memory, reason?, channel
```

The `decision` enum is `answer`, `task`, `confirm`, `ask`, `continue_task`, `status`, `cancel`, `command`,
`switch`, `forget` and `escalated`. The `buttons` enum is `yes`, `differently`, `new_thing`, `make_task`, `todo`,
`forget:<mem>` and `done:<mem>`, written as a pattern.

Other schema changes:
- `TASK_SUBMITTED` gains `conversation` (`cnv`).
- `WORKSPACE_USED` may have `task: null` only with `body.conversation`, and gains `by: "reception"`.
- `QUOTA_WARNING` may have `task: null`.

`reception.schema.json` (the model's output):

```json
{"type": "object", "required": ["decision", "reply", "confidence"], "additionalProperties": false,
 "properties": {
  "decision": {"enum": ["answer", "task", "confirm", "ask", "continue_task", "status", "cancel", "command",
                        "switch", "forget"]},
  "reply": {"type": "string", "maxLength": 6000}, "interpretation": {"type": "string", "maxLength": 1000},
  "goal": {"type": "string", "maxLength": 4000},
  "acceptance": {"type": "array", "maxItems": 8, "items": {"type": "string", "minLength": 1, "maxLength": 500}},
  "risk_hint": {"enum": ["R0", "R1", "R2", "R3"]}, "task": {"$ref": "common.schema.json#/$defs/task_id"},
  "options": {"type": "array", "maxItems": 9, "items": {"type": "string", "minLength": 1, "maxLength": 300}},
  "needs_files": {"type": "boolean"}, "project": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]*$"},
  "memory": {"type": "string", "pattern": "^mem_[0-7][0-9A-HJKMNP-TV-Z]{25}$"},
  "confidence": {"type": "number", "minimum": 0, "maximum": 1},
  "memory_notes": {"type": "array", "maxItems": 3, "items": {"type": "object", "required": ["kind", "text"],
    "additionalProperties": false, "properties": {"kind": {"enum": ["preference", "fact", "glossary", "todo"]},
    "text": {"type": "string", "minLength": 1, "maxLength": 500}, "scope": {"enum": ["project", "operator"]}}}}},
 "allOf": [
  {"if": {"properties": {"decision": {"enum": ["task", "confirm"]}}}, "then": {"required": ["goal"]}},
  {"if": {"properties": {"decision": {"const": "continue_task"}}}, "then": {"required": ["task"]}},
  {"if": {"properties": {"decision": {"const": "switch"}}}, "then": {"required": ["project"]}},
  {"if": {"properties": {"decision": {"const": "forget"}}}, "then": {"required": ["memory"]}}]}
```

- [ ] **Step 1: Write the failing tests.** In `test_conversation_events.py`:
  - one valid event of each new type is appended to `Ledger.open("sqlite:///:memory:")`;
  - a `CONVERSATION_MESSAGE` with a task id is refused;
  - a `CONVERSATION_MESSAGE` by a system actor is refused (humans only);
  - `MEMORY_NOTED` with a `text` key is refused (never the text);
  - a `WORKSPACE_USED` with `task: null` and no `conversation` is refused, and with one it is accepted;
  - a `QUOTA_WARNING` with `task: null` is accepted;
  - a repeated `intake_key` of a `CONVERSATION_MESSAGE` on the same channel raises `DuplicateIntake` whose
    `earlier["id"]` is the first message.

  Also add a `validate("reception", …)` test with one valid decision of each kind, plus four refusals:
  `task` without `goal`, `continue_task` without `task`, an unknown decision, and 4 memory notes. In `test_ids.py`,
  `new_id("cnv")` and `new_id("mem")` match the schema patterns.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest core/tests/test_conversation_events.py core/tests/test_ids.py -q`:
  FAIL (unknown prefix, unknown event type).
- [ ] **Step 3: Implement.**
  - Add the prefixes.
  - Add the schema `$defs` and `allOf` entries. Exempt the seven new types and `QUOTA_WARNING` from the "task is
    required" rule. Pin the seven to `task: null`. Allow `WORKSPACE_USED` with `task: null` only when
    `body.conversation` is present. Add `CONVERSATION_MESSAGE`, `MEMORY_EDITED` and `MEMORY_FORGOTTEN` to the
    humans-only rule.
  - In `Ledger._check_intake`, check the types `TASK_SUBMITTED` and `CONVERSATION_MESSAGE` on their own type and
    channel. `DuplicateIntake(task, earlier)` keeps `task` (a message's is `None`) and adds `earlier`.
- [ ] **Step 4: Run** the two test files and `core/tests/test_ledger.py`: PASS.
- [ ] **Step 5: Commit** `feat: ledger events for conversations, reception decisions and memory (08a task 1)` with
  the explicit paths above.

### Task 2: `[reception]` settings, and gateway calls that belong to a conversation

**Files:**
- Modify: `core/src/ooat_core/config.py`, `core/src/ooat_core/connectors/__init__.py`,
  `core/src/ooat_core/gateway.py`
- Test: `core/tests/test_config.py`, `core/tests/test_gateway.py`

**Interfaces:**
- Produces:
  - `config.ReceptionSettings(batch_seconds: float = 8, silence_hours: float = 24, context_tokens: int = 3000,
    max_answer_usd: float = 0.05, max_answer_operations: int = 40, theta: float = 0.7)`;
  - `Config.reception: ReceptionSettings`;
  - `ModelRequest.conversation: str | None = None`.
- `Gateway.call` accepts a request with `task=None` when `conversation` is set. A quota cool-down caused by such a
  call appends `QUOTA_WARNING` with `task: null`.

- [ ] **Step 1: Write the failing tests.**
  - `[reception]` with every key parses.
  - An unknown key is refused naming the setting, never its value.
  - `theta = 1.2` is refused ("a share from 0 to 1"). `max_answer_operations = 2.5` is refused (whole number).
  - Gateway: a `ModelRequest(task=None, conversation="cnv_…")` call returns a cost.
  - A request with neither a task nor a conversation still raises `ValueError`.
  - A `QUOTA_EXHAUSTED` connector on a conversation call appends a `QUOTA_WARNING` with `task` None.
- [ ] **Step 2: Run** the two files: FAIL.
- [ ] **Step 3: Implement.** In `parse_config`, `unknown` gains `"reception"`. `_reception(data)` follows `_serve`'s
  pattern. In `call`, the check becomes `if request.task is None and request.conversation is None`. `_cool_down`
  already passes `request.task`.
- [ ] **Step 4: Run:** PASS.
- [ ] **Step 5: Commit** `feat: [reception] settings and gateway calls for a conversation (08a task 2)`.

### Task 3: Memory store, secret scan and memory projection

**Files:**
- Create: `core/src/ooat_core/memory.py`
- Modify: `core/src/ooat_core/workspace/grant.py` (hide the memory folder)
- Test: `core/tests/test_memory.py` (create), `core/tests/test_workspace_guard.py`

**Interfaces:**
- Produces:
  - `KINDS = ("preference", "fact", "glossary", "summary", "todo")`, `OPERATOR_SCOPE = "operator"` and
    `MAX_PREFERENCES = 20`;
  - `memory_folder(ledger_url) -> Path | None`;
  - `class MemoryStore(folder: Path)` with `.write(mem_id, text) -> sha256`, `.read(mem_id) -> str | None` and
    `.delete(mem_id) -> None`;
  - `looks_secret(text) -> str | None` (the kind of secret, never the value);
  - `class SecretRefused(ValueError)`;
  - `class MemoryItem(id, scope, kind, data_class, source, text | None, pinned, done, noted, conversation)` (frozen);
  - `note(ledger, store, *, scope, kind, text, data_class, source, actor, conversation=None, pinned=False) -> MemoryItem`;
  - `edit(ledger, store, mem_id, *, operator, channel, text=None, pinned=None, done=None) -> dict`;
  - `forget(ledger, store, mem_id, *, operator, channel, reason=None) -> dict`;
  - `items(events, store, *, scope, cap=None, kinds=KINDS, include_done=False) -> list[MemoryItem]`;
  - `find(events, mem_id) -> dict | None` (its `MEMORY_NOTED`);
  - `class UnknownMemory(ValueError)`.

Rules pinned by tests:
- `note` refuses a secret with `SecretRefused`, and nothing is written.
- `data_class = raised_class(data_class, text)`, so personal data raises the class.
- The file is written before the event. If the event fails, the file is deleted again, so no orphan text is kept.
- Preferences above 20 are refused (`ValueError`).
- `forget` deletes the file and appends `MEMORY_FORGOTTEN`. An item forgotten twice raises `UnknownMemory`.
- `items` leaves out forgotten items, items whose file is missing, items above the cap and done open points (unless
  `include_done`). Each item shows its latest text, and pinned items come first, then the newest.
- `edit` with text writes the new text and appends a hash that matches it. With `done=True` it is allowed only for
  `todo` items.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_note_keeps_its_text_out_of_the_ledger`: the ledger JSON does not contain the text, and its `sha256`
    equals the file's.
  - `test_a_secret_is_never_stored`, parametrised:
    - `"heslo: Tajne123!"`;
    - `"password=hunter22"`;
    - `"Server=db;User Id=sa;Password=x1;"`;
    - `"-----BEGIN PRIVATE KEY-----"`;
    - `"ghp_" + "a1B2" * 9`;
    - `"sk-" + "x9Y8" * 10`;
    - `"ooat_" + "Q" * 40`.

    Each raises `SecretRefused`; no file exists and no event is written.
  - `test_ordinary_text_is_not_a_secret`, parametrised: "Ceny uvádíme s DPH.", "token budget is 2 USD",
    "password reset page is /reset".
  - `test_personal_data_raises_the_class` (an e-mail gives `personal`).
  - `test_forgetting_deletes_the_file_and_the_item_is_gone`.
  - `test_a_missing_file_reads_as_forgotten`.
  - `test_items_are_capped_by_class`.
  - `test_project_memory_never_crosses_projects`.
  - `test_twenty_preferences_at_most`.
  - `test_an_edit_records_the_new_hash`.
  - `test_done_is_only_for_open_points`.
  - `test_pinned_items_come_first`.

  In `test_workspace_guard.py`: `ooat-memory` beside a file ledger is in `grant.hidden`.
- [ ] **Step 2: Run:** FAIL (no module).
- [ ] **Step 3: Implement** `memory.py`.
  - Store files as `<folder>/<mem id>.txt`. Create the folder with mode 0o700, as `ooat-login`.
  - Write atomically through a `.partial` file and `os.replace`.
  - The secret patterns are module constants with bounded repeats (`.claude/lessons.md`: linear regexes).
  - In `grant._ledger_paths`, add `Path(location).parent / "ooat-memory"`.
- [ ] **Step 4: Run** `test_memory.py`, `test_workspace_guard.py`: PASS.
- [ ] **Step 5: Commit** `feat: project memory with texts outside the ledger and a secret scan (08a task 3)`.

### Task 4: Conversations as a projection

**Files:**
- Create: `core/src/ooat_core/conversations.py`
- Modify: `core/src/ooat_core/runtime.py` (`submit(conversation=…)`)
- Test: `core/tests/test_conversations.py` (create), `core/tests/test_runtime.py`

**Interfaces:**
- Produces:
  - `TYPES = ("CONVERSATION_MESSAGE", "RECEPTION_DECIDED", "CONVERSATION_REPORTED", "CONVERSATION_CLOSED")`;
  - `@dataclass(frozen=True) Conversation(id, operator, project, channel, started, last_message, closed: str | None)`;
  - `conversations(events) -> dict[str, Conversation]`;
  - `events_of(events, cnv) -> list[dict]` (its own events, in order);
  - `open_for(events, *, operator, project, channel, now, silence_hours) -> Conversation | None` (newest unclosed,
    last message within the silence);
  - `silent(events, now, silence_hours) -> list[Conversation]` (unclosed, silent);
  - `undecided(events_of_cnv) -> list[dict]` (`CONVERSATION_MESSAGE` events with text, not named in any later
    `RECEPTION_DECIDED.messages`);
  - `questions_in_a_row(events_of_cnv) -> int` (trailing `ask` and `confirm` decisions since the last other decision);
  - `last_options(events_of_cnv) -> list[str]` (of the latest decision or report that has options);
  - `pending(events_of_cnv) -> dict | None` (the latest `confirm`'s `pending`, unless a later decision exists);
  - `tasks_of(events, cnv) -> list[str]` (tasks whose `TASK_SUBMITTED.body.conversation` is the conversation).
- `Runtime.submit(..., conversation: str | None = None)` puts it in the body.

- [ ] **Step 1: Write the failing tests**, from hand-built events:
  - a conversation is found by operator, project and channel;
  - another channel or another project gets none;
  - a conversation whose last message is 25 h old is not open, and is listed by `silent`;
  - a closed one is never open;
  - `undecided` leaves out messages named by a decision, also when the decision named two of them (a batch);
  - a tap message (no text) is not "undecided";
  - `questions_in_a_row` is 2 after ask, confirm, and 0 after ask, task;
  - `last_options` reads a report's options when the report is newer;
  - `pending` is None once a later decision exists;
  - `Runtime.submit(conversation=…)` writes `body.conversation`, and `tasks_of` finds the task.
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement** the projections. Pure functions over event lists, no ledger access, like `state.py`.
- [ ] **Step 4: Run:** PASS.
- [ ] **Step 5: Commit** `feat: conversations as a projection over the ledger (08a task 4)`.

### Task 5: The reception decides: context, model call, rules, acting

**Files:**
- Create: `core/src/ooat_core/reception/__init__.py`, `reception/context.py`, `reception/model.py`
- Test: `core/tests/reception_fakes.py` (create), `core/tests/test_reception.py` (create)

**Interfaces:**
- Consumes: Tasks 1–4. `Runtime.submit`, `Runtime.cancel`, `hil.answer`, `hil.open_requests`, `task_state`,
  `gate.task_facts`, `memory.*`, `conversations.*`.
- Produces:
  - `ACTOR = {"kind": "system", "id": "ooat-reception"}`;
  - `class Reception(runtime: Runtime, memory: MemoryStore | None, settings: ReceptionSettings, projects:
    dict[str, Project], clock)`;
  - `.receive(*, operator, project, channel, text, conversation=None, reply_to=None, files=(), file_names=(),
    intake_key=None) -> dict` (the `CONVERSATION_MESSAGE`; it closes a silent open conversation first, with reason
    `silence`, and its summary is written by Task 7);
  - `.decide(conversation) -> dict | None` (the final `RECEPTION_DECIDED` for all undecided messages, None when
    there are none);
  - `.tap(conversation, tap, *, operator, channel, text=None) -> dict` (the `RECEPTION_DECIDED`).
- `context.gather(reception, conversation_events, project, operator, data_class) -> Context`:
  `Context(text: str, ids: list[str], data_class: str)`.
- `model.decide_call(gateway, *, tier, context, messages, conversation, data_class) -> tuple[dict, dict, str, str]`
  (decision, cost, engine, model). It raises `model.Unusable` (with `.cost`) after a reply that is not valid JSON
  for the schema.
- In `reception_fakes.py`, `ReceptionModel(replies: list[dict | str])` is a `FakeConnector` for tiers `economy` and
  `workhorse`. It answers each call with the next scripted reply (a dict is sent as JSON) and records `calls`.
  `reception(tmp_path, replies, projects=…) -> (Reception, Runtime, model)` builds it all on a SQLite file ledger.

Rules applied in `Reception.decide` after the model (each a test):

1. A `Done when:` or `Hotovo když:` line in the messages wins: the acceptance comes from it, the goal is the text
   before it (`split_done_when`).
2. The `risk_hint` is R2 or R3 → `confirm`, with `pending.risk_class` set; never a direct task.
3. The confidence is below θ for `task` or `continue_task` → one escalation to `workhorse` (an `escalated` event
   first). Still below → `confirm`.
4. `questions_in_a_row >= 2` and the decision is `ask` or `confirm` → `task` with the interpretation (goal: the
   model's goal, or the messages). The reply starts with the interpretation.
5. `switch` to a slug not in `projects` → `ask` naming the configured ones.
6. `command` never submits. The buttons are `todo`.
7. `cancel` cancels the open tasks of the conversation (`Runtime.cancel`) and lists them in `cancelled`. With none
   open, the reply says nothing is running.
8. `continue_task`:
   - to a task not of this conversation or project → `ask`;
   - with an open text question → `hil.answer(choice="clarify" | "narrow_scope", text=…)`;
   - otherwise a follow-up task (decision 6).
9. `status`: the reply is the model's, built from the context, which holds the project's open tasks, the
   conversation's tasks and open points.
10. `forget`: the reply asks for the tap; the buttons are `forget:<mem>`. It is never forgotten without the tap.
11. Memory notes: at most 3, each through `memory.note`. A refused note adds one line saying it was not kept.
    Each kept note adds a line `🧠 <text>` and a `forget:<mem>` button.
12. A gateway failure, or `Unusable` twice → fallback: a task from the messages. The reply notes "reception
    unavailable" in the message's language, and the event has `fallback: true`.
13. The data class of the call is the project's class raised by the messages' text and attachments (pii), and it is
    recorded on the event.

- [ ] **Step 1: Write `reception_fakes.py`.** Write `test_reception.py` with one test per rule above, plus these:
  - `test_a_clear_request_starts_a_task_with_written_criteria`;
  - `test_a_question_is_answered_without_a_task`;
  - `test_a_vague_request_asks_one_question_with_options`;
  - `test_two_messages_in_a_batch_are_one_decision` (`decision.messages` names both);
  - `test_a_second_message_sees_the_task_the_first_started` (Review Focus 5: the context text holds the task id);
  - `test_numbered_answer_sees_the_last_options` (the context lists them numbered);
  - `test_a_reply_that_is_not_json_is_retried_once_then_falls_back` (a fenced JSON block is accepted);
  - `test_personal_data_raises_the_decision_call` (the `ModelRequest.data_class` is `personal`);
  - `test_an_unmapped_project_is_answered_from_memory_only` (`needs_files` true, but no folders: no second call);
  - `test_status_lists_open_points`;
  - `test_the_messages_text_is_untrusted` (the context marks the messages as data between fresh markers).
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement.**
  - `context.py` builds sections in the budget order of decision 5, each item tagged with its id. Project
    instructions are read through `Guard` from each folder's `CLAUDE.md` and `AGENTS.md`, at most 4 000 characters.
  - `model.py`:
    - `SYSTEM` holds the decision rules in English: the person's language, sized to the request, no ids or jargon
      in `reply`, no commands, at most one question;
    - the prompt puts the context and the messages between fresh markers, as `worker_prompt` does;
    - `parse(text)` strips a code fence, loads the JSON and validates it against `reception`.
  - `Reception` puts it together. `θ` comes from `thresholds.reception_threshold` (Task 8); until Task 8 lands it
    is `settings.theta`.
- [ ] **Step 4: Run** `test_reception.py`: PASS. Run the whole core suite: PASS.
- [ ] **Step 5: Commit** `feat: the reception decides a conversation's messages and acts on them (08a task 5)`.

### Task 6: Direct answers that read the project's files

**Files:**
- Modify: `core/src/ooat_core/reception/model.py`, `reception/__init__.py`, `core/src/ooat_core/workspace/runs.py`
- Test: `core/tests/test_reception_answer.py` (create)

**Interfaces:**
- Produces:
  - `model.answer_call(gateway, *, context, messages, grant, conversation, data_class, max_usd) -> AnswerOutput(text,
    cost, limit_reached: bool)`;
  - `Workspaces.answer_grant(conversation, event, project, max_operations) -> WorkspaceGrant` (`write=False`,
    journal `root/<cnv>/<evt>`);
  - `Workspaces.record(..., conversation: str | None = None)`. With a conversation, the event has `task: None`,
    `body.conversation` and `by: "reception"`, and the journal starts at 0.

Behaviour:
- A decision `answer` with `needs_files: true` on a mapped project makes a second call on `economy` with the grant.
  - The grant lists only the 4 read tools. Its estimate must be at most `max_answer_usd`; else the reply offers
    **Make it a task** and nothing is called.
  - The journal becomes `WORKSPACE_USED` with the conversation.
  - A reached limit gives the partial answer, a line saying so, and the `make_task` button.
  - Two events, two costs. The decision call's `RECEPTION_DECIDED` has `decision: "answer"` and `reading: true`,
    and its reply is the model's short "looking into the files" line in the message's language, so a surface can
    show it at once. The answer call's `RECEPTION_DECIDED` follows, carrying the answer as its reply.
    `conversations.undecided` treats the messages as decided by the first event; a crash between the two leaves the
    reading line without an answer, and the desk's tick does not retry it (the operator asks again).

- [ ] **Step 1: Write the failing tests.** Use `WorkspaceModel` from `runtime_fakes.py` with tool calls `read_file`,
  then `edit_file`:
  - the edit is refused, the file is unchanged, and the answer arrives;
  - `WORKSPACE_USED` has `task` None, `body.conversation`, `by` "reception" and `write` false;
  - an estimate above the cap makes no second call and offers `make_task`;
  - the operation limit of 40 is reached: the reply says the answer is partial and offers `make_task`;
  - a project file with an e-mail raises the answer event's data class to `personal`.
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file and `test_workspace_runs.py`: PASS.
- [ ] **Step 5: Commit** `feat: direct answers read a project's folders with a read-only grant (08a task 6)`.

### Task 7: Reports, summaries and the desk thread

**Files:**
- Create: `core/src/ooat_core/reception/desk.py`
- Modify: `core/src/ooat_core/reception/__init__.py`, `reception/model.py`, `core/src/ooat_core/runner.py`
- Test: `core/tests/test_reception_desk.py` (create), `core/tests/test_runner.py`

**Interfaces:**
- Produces:
  - `Reception.report(task) -> dict | None` (`CONVERSATION_REPORTED` when the task is closed, came from a
    conversation and has no report yet);
  - `Reception.close(conversation, reason) -> dict` (`CONVERSATION_CLOSED`, with a `summary` memory item when the
    conversation had at least one decision and a memory store exists);
  - `Reception.unreported() -> list[str]`;
  - `class Desk(make_reception: Callable[[], Reception], *, clock, batch_seconds, tick_seconds=60.0)` with
    `.enqueue(conversation)`, `.report_later(task)`, `.start()`, `.stop()`, `.tick()` and `.run_due() -> list[str]`
    (the latter two for tests);
  - `Runner(..., on_closed: Callable[[str], None] | None = None)`, called after a run that leaves the task closed.

Behaviour:
- `run_due` decides a conversation only when its last undecided message is at least `batch_seconds` old. A
  conversation enqueued again meanwhile is decided once.
- `tick` writes missing reports and closes silent conversations.
- A report's call gets the task's goal, its state and summary, the document (the first 6 000 characters, untrusted,
  between markers) and the change list. It writes "asked, how solved, state, what next" in the conversation's
  language, sized to the work, with numbered options, at the task's data class.

- [ ] **Step 1: Write the failing tests:**
  - `test_messages_wait_for_the_quiet_window` (with a fake clock, nothing at 5 s, one decision at 9 s);
  - `test_a_conversation_is_decided_once_when_enqueued_twice`;
  - `test_a_message_arriving_during_a_decision_is_decided_next` (Review Focus 1: a model whose call appends a
    second message through `receive`, then exactly two decisions, each naming its own message);
  - `test_a_closed_conversation_task_gets_one_report_with_options`;
  - `test_the_runner_calls_back_when_a_task_closes`;
  - `test_a_silent_conversation_is_closed_with_a_summary` (memory item of kind `summary`);
  - `test_a_report_above_a_tokens_class_is_written_but_marked` (the event's `data_class` is the task's).
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement.** The desk has one thread and one queue, like `Runner`. A conversation is decided under a
  per-desk lock, and "undecided" is reread from the ledger right before the model call.
- [ ] **Step 4: Run:** PASS.
- [ ] **Step 5: Commit** `feat: the reception desk - quiet window, reports of finished tasks, summaries (08a task 7)`.

### Task 8: θ for the reception from the operator's verdicts

**Files:**
- Modify: `core/src/ooat_core/thresholds.py`, `core/src/ooat_core/reception/__init__.py`
- Test: `core/tests/test_thresholds.py`

**Interfaces:**
- Produces:
  - `reception_verdicts(events) -> list[RatedDecision]` (point `"reception"`);
  - `reception_threshold(events, engine, model, interim) -> float`.

Verdicts (decision 3):
- **Yes** after a `confirm` → the record of that confirm's decision is confirmed;
- **Differently** → corrected;
- a task started by a decision and cancelled within 2 minutes of its `TASK_SUBMITTED` → corrected;
- that task rated `accepted: true` → confirmed.

- [ ] **Step 1: Write the failing tests:**
  - `test_interim_theta_until_five_verdicts`;
  - `test_floor_is_the_interim_until_twenty`;
  - `test_a_quick_cancel_corrects_the_decision`;
  - `test_yes_confirms_and_differently_corrects`;
  - `test_thresholds_are_per_engine_and_model`.
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement**, reusing `computed_threshold` with `EPSILON["R1"]`. `Reception` reads θ through it.
- [ ] **Step 4: Run** `test_thresholds.py` and `test_reception.py`: PASS.
- [ ] **Step 5: Commit** `feat: the reception's threshold calibrated from the operator's verdicts (08a task 8)`.

### Task 9: The REST resource, views, caps and usage

**Files:**
- Create: `core/src/ooat_core/conversation_endpoints.py`
- Modify: `core/src/ooat_core/api.py` (`Server.reception()`, `Server.desk`, lifespan, error mapping), `views.py`,
  `stats.py`
- Test: `core/tests/test_api_conversations.py` (create), `core/tests/test_stats.py`

**Interfaces:**
- Routes, all under `/api/v1`, scopes as in design §8:
  - `POST /conversations/messages` (`submit`): body `{project, text, conversation?, reply_to?, attachments?}`, header
    `Idempotency-Key`. Returns 202 `{conversation, message}`.
  - `POST /conversations/{id}/taps` (`answer`): `{tap, text?}`. Returns 200 `{conversation, decision}` (the view).
  - `GET /conversations?project=` (`read`) and `GET /conversations/{id}` (`read`).
  - `GET /conversations/{id}/events` (`read`): JSON `{events, next}`, or SSE (as tasks; it ends after 15 minutes or
    at `CONVERSATION_CLOSED`).
  - `GET /memory/{scope}` (`read`): `?kind=&done=`.
  - `PATCH /memory/{scope}/{id}`: `{text?, pinned?, done?}`. `text` and `pinned` need a web session (`SCOPE`
    otherwise); `done` needs `answer`.
  - `DELETE /memory/{scope}/{id}` (`answer`): forget.
- `views.conversation_view(events_of_cnv, cap)`, `views.decision_view(event, cap)` and
  `views.memory_view(item, cap)`: text, reply, options and memory texts above the cap become `stub`. Ids, decisions,
  buttons and states stay.
- `stats.role_of`: actor `ooat-reception` → `"reception"`. The project of an event with `task: None` comes from
  `body.project`.

Rules:
- The project must be in `ooat.toml` or be a slug as for tasks. `require_within(who, project class)`, as `/tasks`.
- A message's raised class above the token's cap is accepted (the chat already holds the text), but every reply is
  stubbed for that token.
- The conversation id in a path belongs to the principal's operator. Another operator's id is 404 (it reads like an
  unknown one).
- Memory routes check that the item belongs to the scope in the path and is within the cap.
- `UnknownMemory` and `SecretRefused` map to 404 and 400 (`SECRET_REFUSED`).

- [ ] **Step 1: Write the failing tests** with `Served` from `api_fakes.py` and a reception model in the registry:
  - a message returns 202 and its event exists;
  - after `server.desk.run_due()` (with the window at 0), the events route lists the decision;
  - the SSE stream yields the decision and ends at close;
  - a repeated `Idempotency-Key` returns the same message;
  - a tap `yes` on a confirm starts the task and returns it;
  - a token without `answer` cannot tap;
  - a token capped at `internal` reads a stub for a `personal` reply (Review Focus 3);
  - a token cannot `PATCH` a text (403 `SCOPE`) but can mark `done` and `DELETE`;
  - deleting another project's item through this scope's path is 404, and one above the cap is 403 (Review
    Focus 4);
  - another operator's conversation is 404;
  - `/stats` has a `reception` row.
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement.**
  - `Server.reception()` is per thread like `runtime()`. `Server.desk` starts and stops in the lifespan, next to
    the runner.
  - The runner's `on_closed` is `desk.report_later`.
  - A message endpoint calls `desk.enqueue(cnv)`.
- [ ] **Step 4: Run** the new file, `test_api.py`, `test_api_security.py` and `test_stats.py`: PASS.
- [ ] **Step 5: Commit** `feat: conversations and memory in the REST API, with caps and usage (08a task 9)`.

### Task 10: Python client and `ooat ask`

**Files:**
- Modify: `sdk/python/src/ooat_client/client.py`, `core/src/ooat_core/operator_cli.py`
- Create: `core/src/ooat_core/reception_cli.py`
- Test: `sdk/python/tests/test_ooat_client.py`, `core/tests/test_reception_cli.py` (create)

**Interfaces:**
- `OoatClient` methods:
  - `send_message(*, project, text, conversation=None, reply_to=None, files=(), intake_key=None) -> dict`;
  - `tap(conversation, tap, text=None) -> dict`;
  - `conversation(cnv) -> dict`;
  - `conversation_events(cnv, after=None) -> list[dict]`;
  - `follow_conversation(cnv, after=None, stop=None) -> Iterator[dict]` (the same reconnect rules as `follow`);
  - `memory(scope, kind=None) -> list[dict]`;
  - `forget(scope, mem) -> dict`;
  - `done(scope, mem) -> dict`.
- `ooat ask --project P [--operator NAME] TEXT`: records the message on channel `cli`, decides at once, prints the
  reply, its numbered options and, when a task started, its id and `ooat task run <id>` (or "`ooat serve` runs it").

- [ ] **Step 1: Write the failing tests:**
  - the client sends the right method, path, body and `Idempotency-Key` (with `stub_http.py`);
  - `follow_conversation` stops at `CONVERSATION_CLOSED`;
  - `ooat ask` prints a reply from a scripted reception model and refuses an unknown project.
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the SDK tests and the new CLI test: PASS.
- [ ] **Step 5: Commit** `feat: conversations in the Python client and ooat ask (08a task 10)`.

### Task 11: The eval runner, docs and lessons

**Files:**
- Create: `evals/reception/run.py`, `evals/reception/example.json`, `evals/reception/README.md`
- Modify: `core/description.md`, `docs/description.md`, `docs/chat-bridge.md`, `sdk/python/README.md`,
  `.claude/lessons.md`
- Test: `core/tests/test_reception_eval.py` (create)

**Interfaces:**
- `python evals/reception/run.py --config ooat.toml --cases <file.json> [--project P]`.
  - Each case is `{"text": "...", "context": [earlier messages], "expected": "<decision>"}`.
  - It runs the decision call only (no acting) on an in-memory ledger with the operator's connectors.
  - It prints one row per case (expected, got, confidence, USD), then the share decided as expected, the share with
    at most one question, and the mean cost per message, against design §1's targets.

- [ ] **Step 1: Write the failing test.** The runner's `evaluate(cases, decide)` with a stub `decide` returns the
  three figures, and a case file with a missing `expected` is refused naming the case number.
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement**, and write the docs:
  - the As-is description of conversations, the reception and memory in `core/description.md` and
    `docs/description.md`;
  - in `docs/chat-bridge.md`, a note that the conversation resource exists and that the bridge moves to it in 08c;
  - the client methods in `sdk/python/README.md`;
  - any gotcha found on the way in `.claude/lessons.md`.

  `example.json` holds 8 made-up messages, one per decision kind, none from the owner's log.
- [ ] **Step 4: Run** the full suite, `.venv/Scripts/python -m pytest -q`: PASS.
- [ ] **Step 5: Commit** `docs: the reception, conversations and memory as built; eval runner for the message set (08a
  task 11)`.

---

## Self-review

- **Design coverage:**
  - §4 decisions and rules 1–10 → Task 5, plus Task 6 (answers), Task 7 (reports, rule 8) and Task 8 (rule 7);
  - §5 context → Task 5;
  - §6 memory → Tasks 3 and 5;
  - §7 events → Task 1;
  - §8 API → Tasks 9 and 10;
  - §10 errors → Tasks 5, 6 and 9;
  - §11 tests → each task, and the message set → Task 11;
  - §14 → Tasks 5 and 7.
  - §9 surfaces (web, Telegram) are 08b and 08c.
- **Not in 08a:**
  - the web's Conversation and Memory pages (08b);
  - the bridge's move to conversations, the `switch` and hand-over handling, and `/pamet` (08c, with the bot's
    task-04);
  - rephrasing a Gate question in plain words in chat (08c shows it).
- **Type names** used across tasks: `ReceptionSettings`, `MemoryStore`, `MemoryItem`, `SecretRefused`,
  `UnknownMemory`, `Conversation`, `Reception`, `Desk`, `Context`, `AnswerOutput`, `Unusable`, `ACTOR`.

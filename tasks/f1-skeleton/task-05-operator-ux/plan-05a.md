# `ooat serve`: REST API, Sessions, Tokens and the Runner (05a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ooat serve` runs one local process with an authenticated REST API (web sessions and operator API tokens), the task runner and its lock, so the web app (05b), the chat bridge (05c) and the setup wizard (01c) can do everything the `ooat` commands do, without a second rule set.

**Architecture:** The ledger becomes safe for threads and processes (WAL, a busy timeout, every append one `BEGIN IMMEDIATE` transaction that also enforces one task per intake key). The operator's actions get one shared path each (`Runtime.submit`, the new `Runtime.cancel`, `hil.answer`, `rate`, `connector_admin.*`) that records the channel and refuses R3. Tokens are ledger events (`tokens.py`); `stats.py` and `views.py` are pure projections, `views.py` applying a token's data-class cap. `api.py` is the HTTP shell (Host, Origin, CSRF, size limit, sessions, tokens, errors, log); `endpoints.py` holds the resources; `runner.py` is one thread with a FIFO queue rebuilt from the ledger; `serve_cli.py` adds `ooat serve`, `ooat login` and `ooat tokens`.

**Tech Stack:** Python 3.12+, FastAPI (Pydantic v2) on uvicorn, SQLite (WAL), pytest with FastAPI's `TestClient` (in-process, no socket, no network).

**Spec:** `tasks/f1-skeleton/task-05-operator-ux/design.md` (approved 2026-10-09; §5–§8, §11–§14); spec §3, §7, §8, §9, §10; ADR 0003, 0010–0015; ADR 0016 (drafted in Task 1).

> **STOP after Task 1.** Task 1 drafts ADR 0016 with the status "proposed". Do not start Task 2 until the owner has
> accepted ADR 0016 (status changed to "accepted" by the owner or on the owner's explicit word). Tasks 2–10 change
> the OOA Spec schemas and text, which CLAUDE.md reserves for the owner.

## Global Constraints

- Only `ooat-core` writes to the ledger; append-only (no UPDATE/DELETE). Every append runs its ledger checks and its insert in one `BEGIN IMMEDIATE` transaction.
- SQLite: one connection per thread (`check_same_thread` stays on); `journal_mode=WAL`, `busy_timeout=5000` ms, `synchronous` left at FULL; a write still waiting after the timeout is `LedgerBusyError` → HTTP 503 `LEDGER_BUSY`. The ledger must be on a local disk.
- Bind `127.0.0.1` by default; a non-loopback host refuses to start without `[serve] tls_cert` and `tls_key`.
- Every endpoint is authenticated except `GET /login`, `GET /login.js` and `POST /api/v1/login`. Every request's `Host` must be allowed (`localhost`, `127.0.0.1`, `::1`, `[serve] hosts`); no CORS; an unsafe request without `Authorization` must carry this server's `Origin`; a cookie session's unsafe request needs its CSRF token.
- Sign-in code: one-time, 5 minutes, in the URL fragment; session: HttpOnly, SameSite=Strict cookie (Secure under TLS), 12 hours, plus a CSRF token.
- API tokens: 256 random bits (`ooat_` prefix), shown once; the ledger keeps only the SHA-256, compared with `hmac.compare_digest`; `Authorization: Bearer`.
- The actor of every human event written through the API is the operator bound to the session or token, never a name from the request body; the event records `channel` (`cli`, `web`, `token:<tok_id>`).
- A token's `max_data_class` (default `internal`) caps reads (stub `{"redacted": "above this token's data class; open in the web app", "link"}`) and writes (403 `DATA_CLASS_ABOVE_TOKEN`). Web sessions on loopback have no cap.
- R3 is refused on every channel (`R3_NEEDS_BOUND_IDENTITY`) until a bound identity exists (ADR 0016).
- No secrets, cookies, tokens, request bodies or query strings in logs, the ledger, error details or the UI; the API logs method, path and status only; uvicorn's access log is off.
- Headers on every response: `Content-Security-Policy: default-src 'self'` (no inline script), `frame-ancestors 'none'`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`; `Cache-Control: no-store` on `/api/`. Artifacts are served as `text/plain` (never HTML) or as an attachment.
- Request bodies at most 20 MB (413 `TOO_LARGE`); errors as `{"error": {"code", "message", "details"}}`.
- New dependencies, nothing else: `fastapi>=0.143` (Task 8) and `uvicorn>=0.54` (Task 10) in `core/pyproject.toml` (the API and its server, named in the CLAUDE.md stack); `httpx2==2.13.1` (pinned) in `requirements-dev.txt` (test-only: FastAPI's `TestClient` imports it; current Starlette asks for it (its import error says `pip install httpx2`) and deprecates plain `httpx`; published by Pydantic, github.com/pydantic/httpx2; verified by the orchestrator 2026-10-10).
- Tests are offline: `TestClient(app, base_url="http://127.0.0.1:8765")` in-process, `uvicorn.run` replaced in CLI tests, fake connectors from `core/tests/runtime_fakes.py`.
- Code, comments, docs and commits in English; lines at most 120 characters; event types, error and reason codes English.

**Owner decisions (2026-10-10, review of PR #34):**
- The plan is approved and is executed natively (superpowers:executing-plans). Execution stops after Task 1
  until the owner accepts ADR 0016.
- Cancel through the API only (web app and bot); no CLI `ooat task cancel` for now.
- Accepted behaviour changes: a task is rated once (409 `ALREADY_RATED`); concurrent CLI runs on one ledger are
  serialised by the runner lock.
- PyPI distribution name: `ooat-core` (ADR 0016 point 10); each release still only on the owner's go.
- Web sessions beyond loopback are capped at `internal`, and TLS is required (decision 1 below stands).

**Decisions this plan takes where the design is silent** (accepted with the plan, 2026-10-10):
1. Served beyond loopback, web sessions are capped at `internal` like a token (design §14 offered this or a responsibility statement); there is no override in 05a.
2. Cancel is a human `DECISION` ("cancel the task", with `channel`); the runtime closes the task `CANCELLED` at its next step. A call in flight finishes first (its cost is recorded) and a document it delivered is kept, without paying for its checks. A cancelled task's open questions vanish from `GET /hil` and get no default. Cancelling needs the `submit` scope. No CLI command (owner, 2026-10-10).
3. Beyond `hil.answer`'s refusal, the ledger itself accepts a response to an R3 request only from `default-on-silence`, so no code path can bypass the R3 rule; and a response under `default-on-silence` must carry `default_applied: true` and choose the request's `default_on_silence` (review of PR #34), so the reserved name can never act.
4. The runner retries a task paused by a provider failure after 60 s, doubling per further failure up to 30 minutes, so the 60-s tick does not spend the budget on retries during an outage (failed calls are charged their estimate, ADR 0014).
5. A task is rated once (409 `ALREADY_RATED`); a second rating would count its verdicts twice in θ.
6. A task's class for the cap is the class it runs under: gated (declared, pre-scan, A10) raised by its attachments.
7. Each F1 attempt writes a new artifact, not a new version, so `GET /artifacts/{ref}/diff?against=` compares two text artifacts of one task.
8. Sessions live in the server's memory (a restart signs out); sign-in codes are files named by the code's SHA-256 in `ooat-login/` beside the ledger, so `ooat login` in another terminal can make one. 05a ships a minimal `/login` page (+ `login.js`) so the printed link works before 05b.
9. GET endpoints never write: defaults on silence are applied by the runner's tick, at most 60 s late.
10. Projections are not cached by `seq` (design §7 allows it); Solo volumes are fast enough, and a cache is added when measured.
11. Chunked request bodies are refused (411 `LENGTH_REQUIRED`) so the 20 MB limit holds by `Content-Length`.
12. `ooat task run` (and `submit` / `hil answer` when they run) take the runner lock too, so two CLI runs on one ledger no longer run side by side either.
13. Any operator may revoke any token, with a required reason; `OPERATOR_TOKEN_REVOKED.body.operator` (also the actor) is who revoked it, `reason` why. Operator names are self-declared, so an issuer-only rule would protect little and would block an emergency revoke (review of PR #34). Revoking is CLI-only in 05a.
14. Sign-in hardening (review of PR #34): a `Content-Length` that is not a number is 400 `INVALID`; `ooat-login/` is created with mode 0o700. On Windows the mode is ignored: the folder lies beside the ledger in the operator's profile and inherits its ACL, which OOAT does not change.
15. An open Server-Sent Events stream authenticates its reader again on every poll (session open, token not revoked or expired, `read` scope) and applies the cap afresh; when that fails it sends one `UNAUTHENTICATED` event and ends.
16. Hook approval (ADR 0015) approves code that runs on this machine: `POST /connectors/{id}/approve-hooks` is allowed from a web session only (and the CLI), never with a bearer token (403 `SCOPE`), whatever its scopes.
17. Examples and tests use the operator name `operator` (and `second-operator`), as the existing fixtures do, not real first names.

## Review Focus

1. A chat bot retries one message while the first delivery is still in flight, or after a server restart → exactly one task, and the retry gets its id (Task 3 test `test_two_deliveries_of_one_chat_message_at_once_create_one_task`; Task 9 test `test_a_repeated_idempotency_key_returns_the_first_task_also_after_a_restart`).
2. A provider is down for an hour while `ooat serve` runs → the task stays paused and is retried with a growing pause, not every minute at the charged estimate (Task 6 test `test_a_paused_task_is_tried_again_after_a_growing_pause`).
3. The operator cancels while the runner is in the middle of a worker call → the task closes `CANCELLED` once the call returns, its cost is recorded, no acceptance check is paid for, and its open question can no longer be answered or defaulted (Task 4 tests `test_a_cancel_during_the_worker_call_keeps_the_document_and_skips_the_checks`, `test_the_question_of_a_cancelled_task_is_neither_open_nor_answerable`).
4. Another process (a CLI run, a backup tool) holds the ledger's write lock past the busy timeout → 503 `LEDGER_BUSY` with nothing written, also when the request opens a fresh connection, never a 500 (Task 3 test `test_a_write_still_locked_out_after_the_timeout_is_busy_and_writes_nothing`; Task 9 test `test_a_ledger_locked_past_the_busy_timeout_answers_503_and_writes_nothing`).
5. The operator types `ooat task run` or `ooat task submit` while `ooat serve` runs → no task is run by two processes: `run` refuses, `submit` and `hil answer` only record (Task 6 test `test_while_the_server_holds_the_runner_lock_the_cli_only_records`).

---

## File Structure

```
docs/adr/0016-operator-api-tokens.md                                                       (Task 1)
spec/schemas/{event,common}.schema.json, spec/examples/valid/event.operator_token_*.json,
spec/tests/test_schemas.py, spec/ooat-specification.md, spec/README.md, docs/adr/0003-*.md,
core/src/ooat_core/ids.py, core/tests/test_ids.py                                           (Task 2)
core/src/ooat_core/backends/{__init__,sqlite}.py, ledger.py, core/tests/test_{sqlite_backend,ledger}.py   (Task 3)
core/src/ooat_core/hil.py, runtime.py, rating.py, connector_admin.py, task_cli.py, operator_cli.py, ledger.py,
core/tests/test_{hil,runtime,rating,task_cli,operator_cli,ledger}.py                        (Task 4)
core/src/ooat_core/tokens.py, serve_cli.py, operator_cli.py, core/tests/test_tokens.py      (Task 5)
core/src/ooat_core/runner_lock.py, runner.py, task_cli.py, core/tests/test_runner.py, test_task_cli.py   (Task 6)
core/src/ooat_core/stats.py, views.py, core/tests/test_{stats,views}.py                     (Task 7)
core/src/ooat_core/sessions.py, api.py, web/login.{html,js}, core/pyproject.toml, requirements-dev.txt,
core/tests/api_fakes.py, test_api_security.py                                               (Task 8)
core/src/ooat_core/endpoints.py, api.py, core/tests/test_api.py                             (Task 9)
core/src/ooat_core/config.py, serve_cli.py, operator_cli.py, core/pyproject.toml, core/tests/test_serve_cli.py,
core/description.md, docs/description.md, README.md, .claude/lessons.md                     (Task 10)
```

How to apply a "replace" step: the old text occurs exactly once in the file; replace it with the new text. Files may have CRLF line endings on Windows — match the text, not the line endings. Work on a branch `feat/05a-serve` from `main`; run commands from the repository root with the project virtual environment active (`python -m pip install -r requirements-dev.txt -e core -e adapters/...` as in `docs/description.md`; Task 8 and Task 10 install the new dependencies).

---

### Task 1: Draft ADR 0016 (then stop for the owner)

**Files:**
- Create: `docs/adr/0016-operator-api-tokens.md`

**Interfaces:**
- Produces: the decisions Tasks 2–10 implement: event types `OPERATOR_TOKEN_ISSUED` / `OPERATOR_TOKEN_REVOKED`, `channel`, `intake_key`, the cap rules, `R3_NEEDS_BOUND_IDENTITY`, the error codes.

- [ ] **Step 1: Write the ADR**

Create `docs/adr/0016-operator-api-tokens.md`:

```markdown
# ADR 0016 — Operator API: tokens, channels, intake keys and the R3 identity rule

**Status:** proposed — the owner accepts it before Task 2 of plan 05a · **Date:** 2026-10-10 · **Context:** the
operator experience design (`tasks/f1-skeleton/task-05-operator-ux/design.md`, approved by the owner 2026-10-09,
§6, §12, §13, §14) adds `ooat serve`: a REST API for the web app and the owner's chat bot. Bots act through API
tokens, so who could act for whom must be in the audit log, and a chat platform stores what it receives.

## Decision

1. **Operator tokens are ledger events.** `ooat tokens create --operator NAME --name NAME --scopes ...` appends
   `OPERATOR_TOKEN_ISSUED` (human actor, `task: null`; body: `token` (`tok_<ULID>`), `operator`, `name`, `scopes`,
   `max_data_class`, `sha256`, `expires`, and `responsibility.confirmed_on` for a cap above `internal`).
   `ooat tokens revoke` appends `OPERATOR_TOKEN_REVOKED` (`token`; `operator`, who revoked it; the required
   `reason`). Any operator may revoke any token: names are self-declared, and a leaked token must be stoppable
   at once by whoever notices. The token is 256 random
   bits with the prefix `ooat_`, printed once; the ledger keeps only its SHA-256, compared in constant time. Scopes:
   `submit` (also cancels), `read`, `answer`, `rate`, `connectors`. A token expires after 1 to 365 days (default 90)
   and acts as the operator who issued it. An open event stream checks its token or session again on every
   poll and ends with an `UNAUTHENTICATED` event once it no longer holds. Approving a connector's hooks
   (ADR 0015) approves code that runs on this machine, so it is done from the CLI or a web session only, never
   with a token (403 `SCOPE`).
2. **ADR 0003 §3 is amended:** `task: null` is allowed for `ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`,
   `OPERATOR_TOKEN_ISSUED` and `OPERATOR_TOKEN_REVOKED`, and required for the two token events. The event schema's
   null-task conditional admits them.
3. **Channel.** The bodies of `TASK_SUBMITTED`, `HIL_RESPONSE`, `TASK_RATED`, `ADAPTER_ACKNOWLEDGED`,
   `ADAPTER_DISABLED` and `DECISION` (the operator's cancel) may carry `channel`: `cli`, `web` or `token:<tok_id>`.
   The actor of a human event written through the API is the operator bound to the session or token, never a name
   from the request body.
4. **Intake key.** `TASK_SUBMITTED.body.intake_key` (printable ASCII without spaces, 1 to 128 characters, only with
   a `channel`) is the client's idempotency key, e.g. a chat message id. It is unique per `(channel, key)`;
   `Ledger.append` checks it inside the same `BEGIN IMMEDIATE` write transaction as the insert, so two concurrent or
   retried deliveries create one task, also across a restart. A repeat returns the task the key created.
5. **Data-class cap.** A token's `max_data_class` (default `internal`; `special_category` never) caps every read the
   token makes: content above it comes back as a stub, while ids, states, costs and deadlines stay visible. It caps
   writes too: answering, rating or cancelling a task above it, submitting above it, or enabling a connector for a
   class above it is refused with `DATA_CLASS_ABOVE_TOKEN`. A task's class is the class it runs under (declared,
   raised by the pre-scan, the Gate's A10 and its attachments); an artifact's is its own. Raising a cap above
   `internal` is the operator's responsibility statement, recorded with the date as in ADR 0012. A web session on
   loopback has no cap (owner, 2026-10-09). A server bound beyond loopback needs `[serve] tls_cert` and `tls_key`,
   and caps its web sessions at `internal` like a token (design 05 §14: the plan chose the cap over a
   responsibility statement).
6. **R3 needs a bound identity (amends spec §9).** A named approver is an operator identity bound to something the
   operator holds, such as a passkey (WebAuthn) or an OS-account check. A self-declared name (the CLI's
   `--operator`, `ooat login --operator`) or a token never answers an R3 request. Until such a binding exists every
   R3 request is refused on every channel with `R3_NEEDS_BOUND_IDENTITY`, and the ledger accepts a response to an
   R3 request only from `default-on-silence`. A response under `default-on-silence` must carry
   `default_applied: true` and choose the request's `default_on_silence`, so the reserved name never acts. F1 has no R3 request, so nothing breaks today; the binding is a
   precondition for the first R3 gate, not part of 05.
7. **The dashboard is JavaScript checked by tsc (amends spec §3).** Plain ES modules with JSDoc types, checked in
   CI by `tsc --noEmit --checkJs`, served as static files from the `ooat-core` wheel without a build step (owner,
   2026-10-09). The TypeScript SDK stays TypeScript. CLAUDE.md's stack line ("TypeScript dashboard") is
   updated to match; this ADR is the owner's approval of that change.
8. **A Usage view in F1 (amends spec §10)**, ahead of the F2 Economics view: calls, tokens and cost by role,
   connector, tier and project, metered and subscription shadow cost, tasks by outcome, cost per accepted task,
   HIL waiting time.
9. **The operator cancels a task** with a `DECISION` ("cancel the task", human actor, `channel`). The runtime
   closes the task as `CANCELLED` at its next step; a call in flight finishes first, so its cost is recorded, and
   its document is kept. A cancelled task's open questions are no longer listed and get no default.
10. **Publishing on PyPI.** The owner approved publishing OOAT on PyPI on 2026-10-09. The distribution name is
    `ooat-core` (owner, 2026-10-10) and the command it installs is `ooat`, so `pipx install ooat-core` becomes the
    documented install once a release is cut. Each release is still published only on the owner's go; the
    CLAUDE.md rule on publishing stays in force for every release.

## Consequences

- Schema changes, all additive: `common.schema.json#/$defs/token_id`; event types `OPERATOR_TOKEN_ISSUED` and
  `OPERATOR_TOKEN_REVOKED` with their bodies; `channel` in six bodies; `intake_key` in `TASK_SUBMITTED`.
- Spec v0.2 text: §3 (dashboard), §7 (event types, `task: null`), §9 (R3, HIL rule 6), §10 (Usage view).
- Behaviour changes: `ooat hil answer` refuses R3 requests; a task is rated once (a second rating would count its
  verdicts twice in the thresholds); while `ooat serve` runs, `ooat task run` refuses and `ooat task submit` and
  `ooat hil answer` only record, and the server runs the task.
- API error codes (English, stable): `INVALID`, `HOST_NOT_ALLOWED` (400); `UNAUTHENTICATED` (401); `SCOPE`, `CSRF`,
  `ORIGIN_NOT_ALLOWED`, `DATA_CLASS_ABOVE_TOKEN`, `R3_NEEDS_BOUND_IDENTITY` (403); `NOT_FOUND` (404);
  `ALREADY_ANSWERED`, `NOT_CLOSED`, `ALREADY_RATED`, `NOT_OPEN`, `HOOKS_CHANGED` (409); `LENGTH_REQUIRED` (411);
  `TOO_LARGE` (413); `SPEC_VALIDATION` (422); `LEDGER_BUSY` (503).
- Decided by the owner on 2026-10-09 (design 05 §13); this record is proposed on 2026-10-10 and takes effect when
  the owner accepts it.
```

- [ ] **Step 2: Check it renders and names every point the plan relies on**

Run: `python -c "t=open('docs/adr/0016-operator-api-tokens.md',encoding='utf-8').read(); print(all(k in t for k in ['OPERATOR_TOKEN_ISSUED','intake_key','R3_NEEDS_BOUND_IDENTITY','tsc --noEmit --checkJs','PyPI','ADR 0003 §3','proposed']))"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add docs/adr/0016-operator-api-tokens.md
git commit -m "docs: ADR 0016 (proposed) - operator API tokens, channels, intake keys, R3 identity"
```

- [ ] **Step 4: STOP — ask the owner to accept ADR 0016**

Report to the owner: ADR 0016 is drafted as "proposed"; Tasks 2–10 need it accepted. Do not continue until the owner has accepted it. When they have, change its status line to `**Status:** accepted · **Date:** <the date of acceptance>` and commit that as the first step of Task 2.

---

### Task 2: Schema and spec changes of ADR 0016

**Files:**
- Modify: `docs/adr/0016-operator-api-tokens.md` (status), `docs/adr/0003-schema-interpretations.md` (amendment)
- Modify: `spec/schemas/common.schema.json`, `spec/schemas/event.schema.json`
- Create: `spec/examples/valid/event.operator_token_issued.json`, `spec/examples/valid/event.operator_token_revoked.json`
- Modify: `spec/tests/test_schemas.py`, `spec/ooat-specification.md`, `spec/README.md`, `CLAUDE.md` (stack line)
- Modify: `core/src/ooat_core/ids.py`, `core/tests/test_ids.py`

**Interfaces:**
- Produces: schema `$defs/channel` (`^(cli|web|token:tok_<ULID>)$`), `common.schema.json#/$defs/token_id`, bodies `body_operator_token_issued` / `body_operator_token_revoked`, `TASK_SUBMITTED.body.intake_key` (`^[!-~]{1,128}$`, requires `channel`), `channel` in the bodies of `TASK_SUBMITTED`, `HIL_RESPONSE`, `TASK_RATED`, `ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`, `DECISION`; `ids.new_id("tok")`.

- [ ] **Step 1: Record the acceptance**

In `docs/adr/0016-operator-api-tokens.md` replace `**Status:** proposed — the owner accepts it before Task 2 of plan 05a · **Date:** 2026-10-10` with `**Status:** accepted · **Date:** <date the owner accepted it>`. Append to `docs/adr/0003-schema-interpretations.md`:

```markdown

## Amendment (ADR 0016)

#3 now reads: `ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`, `OPERATOR_TOKEN_ISSUED` and `OPERATOR_TOKEN_REVOKED` have
`task: null`; every other event type requires a task, and the two token events require `null`.
```

- [ ] **Step 2: Write the failing schema tests and the examples**

Create `spec/examples/valid/event.operator_token_issued.json`:

```json
{
  "id": "evt_01J9ZQ80A0K3M5N7P9Q1R3S5T7",
  "ts": "2026-10-10T09:00:00Z",
  "task": null,
  "actor": {"kind": "hil", "id": "operator"},
  "type": "OPERATOR_TOKEN_ISSUED",
  "refs": [],
  "body": {
    "token": "tok_01J9ZQ80B0K3M5N7P9Q1R3S5T7",
    "operator": "operator",
    "name": "telegram",
    "scopes": ["submit", "read", "answer", "rate"],
    "max_data_class": "internal",
    "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "expires": "2027-01-08T09:00:00Z"
  }
}
```

Create `spec/examples/valid/event.operator_token_revoked.json`:

```json
{
  "id": "evt_01J9ZQ81A0K3M5N7P9Q1R3S5T7",
  "ts": "2026-10-11T09:00:00Z",
  "task": null,
  "actor": {"kind": "hil", "id": "operator"},
  "type": "OPERATOR_TOKEN_REVOKED",
  "refs": [],
  "body": {
    "token": "tok_01J9ZQ80B0K3M5N7P9Q1R3S5T7",
    "operator": "operator",
    "reason": "The bot moved to another server."
  }
}
```

In `spec/tests/test_schemas.py` replace

```python
    ("event_responsibility_training_stated_false", "event", "event.adapter_acknowledged_responsibility.json",
     _set(["body", "responsibility", "no_training"], False)),
]
```

with

```python
    ("event_responsibility_training_stated_false", "event", "event.adapter_acknowledged_responsibility.json",
     _set(["body", "responsibility", "no_training"], False)),
    # ADR 0016
    ("event_token_issued_by_system", "event", "event.operator_token_issued.json",
     _set(["actor"], {"kind": "system", "id": "ooat-core"})),
    ("event_token_issued_on_a_task", "event", "event.operator_token_issued.json",
     _set(["task"], "tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7")),
    ("event_token_issued_with_the_token_itself", "event", "event.operator_token_issued.json",
     _set(["body", "secret"], "ooat_abc")),
    ("event_token_unknown_scope", "event", "event.operator_token_issued.json", _set(["body", "scopes"], ["admin"])),
    ("event_token_special_category_cap", "event", "event.operator_token_issued.json",
     _set(["body", "max_data_class"], "special_category")),
    ("event_token_personal_cap_without_responsibility", "event", "event.operator_token_issued.json",
     _set(["body", "max_data_class"], "personal")),
    ("event_token_revoked_without_reason", "event", "event.operator_token_revoked.json", _delete(["body", "reason"])),
    ("event_channel_not_a_known_kind", "event", "event.task_submitted.json", _set(["body", "channel"], "telegram")),
    ("event_intake_key_with_spaces", "event", "event.task_submitted.json",
     lambda doc: doc["body"].update(channel="web", intake_key="chat 42 message 7")),
    ("event_intake_key_without_channel", "event", "event.task_submitted.json", _set(["body", "intake_key"], "m-7")),
]
```

and append at the end of the file:

```python


def test_human_events_record_their_channel_and_a_submission_its_intake_key():  # ADR 0016
    doc = load("event.task_submitted.json")
    doc["body"] |= {"channel": "token:tok_01J9ZQ80B0K3M5N7P9Q1R3S5T7", "intake_key": "chat-42:msg-7"}
    assert validator("event").is_valid(doc)
    for source in ("event.task_rated.json", "event.adapter_disabled.json", "event.adapter_acknowledged.json"):
        doc = load(source)
        doc["body"]["channel"] = "web"
        assert validator("event").is_valid(doc), source
```

In `core/tests/test_ids.py` replace `@pytest.mark.parametrize("prefix", ["tsk", "ctr", "agt", "evt", "art"])` with `@pytest.mark.parametrize("prefix", ["tsk", "ctr", "agt", "evt", "art", "tok"])`.

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest spec/tests core/tests/test_ids.py -q`
Expected: FAIL — `test_valid_example[event.operator_token_issued.json]` (unknown event type), `test_human_events_record_their_channel...` (additional property), `event_channel_not_a_known_kind` and the intake cases (the base passes, the mutation is not refused), `test_new_id_matches_spec_pattern[tok]` (`unknown id prefix: tok`).

- [ ] **Step 4: Change the schemas and the id prefixes**

In `spec/schemas/common.schema.json` replace

```json
    "event_id": {"type": "string", "pattern": "^evt_[0-7][0-9A-HJKMNP-TV-Z]{25}$"},
```

with

```json
    "event_id": {"type": "string", "pattern": "^evt_[0-7][0-9A-HJKMNP-TV-Z]{25}$"},
    "token_id": {"description": "An operator API token (ADR 0016); the token itself is never stored.", "type": "string", "pattern": "^tok_[0-7][0-9A-HJKMNP-TV-Z]{25}$"},
```

In `spec/schemas/event.schema.json` apply these replacements (each old text occurs once):

1. `"description": "Task id. ADAPTER_ACKNOWLEDGED and ADAPTER_DISABLED are not tied to a task and use null."` →
   `"description": "Task id. ADAPTER_ACKNOWLEDGED, ADAPTER_DISABLED, OPERATOR_TOKEN_ISSUED and OPERATOR_TOKEN_REVOKED are not tied to a task and use null (ADR 0003, ADR 0016)."`
2. Replace

```json
      "if": {"properties": {"type": {"not": {"enum": ["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"]}}}},
      "then": {"properties": {"task": {"$ref": "common.schema.json#/$defs/task_id"}}}
    },
```

with

```json
      "if": {"properties": {"type": {"not": {"enum": ["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED", "OPERATOR_TOKEN_ISSUED", "OPERATOR_TOKEN_REVOKED"]}}}},
      "then": {"properties": {"task": {"$ref": "common.schema.json#/$defs/task_id"}}}
    },
    {
      "description": "An operator token belongs to no task (ADR 0016).",
      "if": {"properties": {"type": {"enum": ["OPERATOR_TOKEN_ISSUED", "OPERATOR_TOKEN_REVOKED"]}}},
      "then": {"properties": {"task": {"type": "null"}}}
    },
```

3. Replace

```json
      "description": "Only a human answers, rates, reports defects, acknowledges or disables adapters.",
      "if": {"properties": {"type": {"enum": ["HIL_RESPONSE", "TASK_RATED", "DEFECT_FOUND", "ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"]}}},
```

with

```json
      "description": "Only a human answers, rates, reports defects, acknowledges or disables adapters, issues or revokes operator tokens.",
      "if": {"properties": {"type": {"enum": ["HIL_RESPONSE", "TASK_RATED", "DEFECT_FOUND", "ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED", "OPERATOR_TOKEN_ISSUED", "OPERATOR_TOKEN_REVOKED"]}}},
```

4. Replace

```json
    {"if": {"properties": {"type": {"const": "ADAPTER_DISABLED"}}}, "then": {"properties": {"body": {"$ref": "#/$defs/body_adapter_disabled"}}}}
  ],
```

with

```json
    {"if": {"properties": {"type": {"const": "ADAPTER_DISABLED"}}}, "then": {"properties": {"body": {"$ref": "#/$defs/body_adapter_disabled"}}}},
    {"if": {"properties": {"type": {"const": "OPERATOR_TOKEN_ISSUED"}}}, "then": {"properties": {"body": {"$ref": "#/$defs/body_operator_token_issued"}}}},
    {"if": {"properties": {"type": {"const": "OPERATOR_TOKEN_REVOKED"}}}, "then": {"properties": {"body": {"$ref": "#/$defs/body_operator_token_revoked"}}}}
  ],
```

5. Replace

```json
        "TASK_CLOSED", "TASK_RATED", "DEFECT_FOUND", "ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"
      ]
```

with

```json
        "TASK_CLOSED", "TASK_RATED", "DEFECT_FOUND", "ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED",
        "OPERATOR_TOKEN_ISSUED", "OPERATOR_TOKEN_REVOKED"
      ]
```

6. Replace `    "text": {"type": "string", "minLength": 1},` with

```json
    "text": {"type": "string", "minLength": 1},
    "channel": {"description": "Where a human event came from: the CLI, a web session, or an operator token (ADR 0016).", "type": "string", "pattern": "^(cli|web|token:tok_[0-7][0-9A-HJKMNP-TV-Z]{25})$"},
```

7. In `body_task_submitted` replace

```json
        "deadline": {"type": "string", "format": "date-time"}
      }
    },
    "body_topology_decided": {
```

with

```json
        "deadline": {"type": "string", "format": "date-time"},
        "channel": {"$ref": "#/$defs/channel"},
        "intake_key": {"description": "The client's idempotency key; unique per channel, checked by the ledger (ADR 0016).", "type": "string", "pattern": "^[!-~]{1,128}$"}
      },
      "dependentRequired": {"intake_key": ["channel"]}
    },
    "body_topology_decided": {
```

8. In `body_decision` replace

```json
        "supersedes": {"$ref": "common.schema.json#/$defs/event_id"}
      }
    },
    "body_gate": {
```

with

```json
        "supersedes": {"$ref": "common.schema.json#/$defs/event_id"},
        "channel": {"$ref": "#/$defs/channel"}
      }
    },
    "body_gate": {
```

9. In `body_hil_response` replace

```json
        "default_applied": {"description": "True when the deadline passed and the default was applied.", "type": "boolean"}
      },
```

with

```json
        "default_applied": {"description": "True when the deadline passed and the default was applied.", "type": "boolean"},
        "channel": {"$ref": "#/$defs/channel"}
      },
```

10. In `body_task_rated` replace

```json
        "note": {"$ref": "#/$defs/text"},
        "decisions": {
```

with

```json
        "note": {"$ref": "#/$defs/text"},
        "channel": {"$ref": "#/$defs/channel"},
        "decisions": {
```

11. In `body_adapter_acknowledged` replace

```json
        "jurisdiction_sha256": {"description": "Fingerprint of the acknowledged jurisdiction block (ADR 0010).", "type": "string", "pattern": "^[0-9a-f]{64}$"},
```

with

```json
        "jurisdiction_sha256": {"description": "Fingerprint of the acknowledged jurisdiction block (ADR 0010).", "type": "string", "pattern": "^[0-9a-f]{64}$"},
        "channel": {"$ref": "#/$defs/channel"},
```

12. Replace the end of the file

```json
        "adapter": {"$ref": "common.schema.json#/$defs/provider_id"},
        "operator": {"$ref": "#/$defs/text"},
        "reason": {"$ref": "#/$defs/text"}
      }
    }
  }
}
```

with

```json
        "adapter": {"$ref": "common.schema.json#/$defs/provider_id"},
        "operator": {"$ref": "#/$defs/text"},
        "reason": {"$ref": "#/$defs/text"},
        "channel": {"$ref": "#/$defs/channel"}
      }
    },
    "token_scope": {"enum": ["submit", "read", "answer", "rate", "connectors"]},
    "body_operator_token_issued": {
      "description": "A named operator issued an API token that acts as them (ADR 0016). Only the token's SHA-256 is recorded, never the token. A cap above internal is the operator's responsibility statement (ADR 0012).",
      "type": "object",
      "required": ["token", "operator", "name", "scopes", "max_data_class", "sha256", "expires"],
      "additionalProperties": false,
      "properties": {
        "token": {"$ref": "common.schema.json#/$defs/token_id"},
        "operator": {"$ref": "#/$defs/text"},
        "name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{0,31}$"},
        "scopes": {"type": "array", "minItems": 1, "uniqueItems": true, "items": {"$ref": "#/$defs/token_scope"}},
        "max_data_class": {"enum": ["public", "internal", "client_confidential", "personal"]},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "expires": {"type": "string", "format": "date-time", "pattern": "Z$"},
        "responsibility": {
          "type": "object",
          "required": ["confirmed_on"],
          "additionalProperties": false,
          "properties": {"confirmed_on": {"type": "string", "format": "date"}}
        }
      },
      "if": {"properties": {"max_data_class": {"enum": ["client_confidential", "personal"]}}},
      "then": {"required": ["responsibility"]}
    },
    "body_operator_token_revoked": {
      "type": "object",
      "required": ["token", "operator", "reason"],
      "additionalProperties": false,
      "properties": {
        "token": {"$ref": "common.schema.json#/$defs/token_id"},
        "operator": {"$ref": "#/$defs/text"},
        "reason": {"$ref": "#/$defs/text"}
      }
    }
  }
}
```

In `core/src/ooat_core/ids.py` replace `PREFIXES = frozenset({"tsk", "ctr", "agt", "evt", "art"})` with
`PREFIXES = frozenset({"tsk", "ctr", "agt", "evt", "art", "tok"})  # tok: an operator API token (ADR 0016)`.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest spec/tests core/tests/test_ids.py core/tests/test_validation.py -q`
Expected: PASS (every schema case, including the new ADR 0016 ones)

- [ ] **Step 6: Carry ADR 0016 into the spec text**

In `spec/ooat-specification.md` make these edits. Each "old" text occurs once; "after" means: insert the new text as
the next line (or the next paragraph, with a blank line, for item 9).

1. After the line `- ADR 0015: the operator approves the hooks a connector's CLI runs (§7, §9).` insert:

```text
- ADR 0016: operator API tokens and channels in the ledger, `task: null` for token events, intake keys, R3 needs a bound identity, the dashboard in tsc-checked JavaScript, a Usage view in F1 (§2, §3, §7, §9, §10).
```

2. Replace (§2, domain model)

```text
Every event belongs to a Task except the connector events `ADAPTER_ACKNOWLEDGED` and `ADAPTER_DISABLED`, which have `task: null` (ADR 0003, ADR 0010).
```

with

```text
Every event belongs to a Task except the connector events `ADAPTER_ACKNOWLEDGED` and `ADAPTER_DISABLED` and the operator token events `OPERATOR_TOKEN_ISSUED` and `OPERATOR_TOKEN_REVOKED`, which have `task: null` (ADR 0003, ADR 0010, ADR 0016).
```

3. Replace (§3, deliverables)

```text
| Dashboard | TypeScript web app | HIL queue, exceptions, economics, calibration |
```

with

```text
| Dashboard | JavaScript web app (ES modules, JSDoc types checked by `tsc --noEmit --checkJs`, no build step; ADR 0016) | HIL queue, exceptions, usage, economics, calibration |
```

4. Replace `TypeScript for the UI and for teams building on Node.` with

```text
TypeScript for teams building on Node; the dashboard is JavaScript with types checked by `tsc`, so the operator needs no Node and no build step (ADR 0016).
```

5. Replace (§7, event envelope)

```text
`task` is required on every event except `ADAPTER_ACKNOWLEDGED` and `ADAPTER_DISABLED`, which have `task: null` (ADR 0003, ADR 0010).
```

with

```text
`task` is required on every event except `ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`, `OPERATOR_TOKEN_ISSUED` and `OPERATOR_TOKEN_REVOKED`, which have `task: null` (ADR 0003, ADR 0010, ADR 0016).
```

6. After the event-types table row for ADAPTER_DISABLED (§7; it starts with `| ` and the event type, then `| Human (named operator) | Connector disabled:`) insert:

```text
| `OPERATOR_TOKEN_ISSUED` | Human (named operator) | An API token acting as the operator: token id, name, scopes, `max_data_class`, SHA-256 of the token (never the token), expiry; `task: null` (ADR 0016) | API, dashboard |
| `OPERATOR_TOKEN_REVOKED` | Human (named operator) | Token revoked: token id, operator, reason; `task: null` (ADR 0016) | API, dashboard |
```

7. Replace

```text
only humans emit `HIL_RESPONSE`, `TASK_RATED`, `DEFECT_FOUND`, `ADAPTER_ACKNOWLEDGED` and `ADAPTER_DISABLED`.
```

with

```text
only humans emit `HIL_RESPONSE`, `TASK_RATED`, `DEFECT_FOUND`, `ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`, `OPERATOR_TOKEN_ISSUED` and `OPERATOR_TOKEN_REVOKED`; their actor is the operator bound to the session or token, never a name from a request, and they record the `channel` (`cli`, `web`, `token:<id>`) they came from (ADR 0016).
```

8. Replace `-- NULL only for ADAPTER_ACKNOWLEDGED / ADAPTER_DISABLED` with `-- NULL only for connector and operator token events`.
9. After the paragraph that starts with "Any `impl: llm` capability able to perform an R3 action" (§9, risk classes) insert the paragraph:

```text
A named approver is an operator identity bound to something the operator holds, such as a passkey (WebAuthn) or an OS-account check. A self-declared name (the CLI's `--operator`, `ooat login --operator`) or an API token is never one. Until such a binding exists, every R3 request is refused on every channel (`R3_NEEDS_BOUND_IDENTITY`) and only its default on silence applies (ADR 0016).
```

10. After the line that starts with `5. That response is written under the reserved actor id` (§9, HIL rules) insert:

```text
6. A response to an R3 request is accepted only from `default-on-silence` until operator identities are bound (ADR 0016).
```

11. After the table row that starts with `| Rating queue |` (§10) insert:

```text
| Usage | Calls, tokens and cost by role, connector, tier and project; metered vs. subscription shadow cost; tasks by outcome, cost per accepted task, estimate vs. actual; HIL waiting time | ledger | F1 (ADR 0016) |
```

In `spec/README.md`: replace

```text
- Only agents emit `CLAIM`/`RESULT`/`OBJECTION`; only humans emit `HIL_RESPONSE`, `TASK_RATED`, `DEFECT_FOUND`, `ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`,
```

with

```text
- Only agents emit `CLAIM`/`RESULT`/`OBJECTION`; only humans emit `HIL_RESPONSE`, `TASK_RATED`, `DEFECT_FOUND`, `ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`, `OPERATOR_TOKEN_ISSUED`, `OPERATOR_TOKEN_REVOKED`,
```

after the line ``- Timestamps are UTC (`Z`).`` insert

```text
- Token events have `task: null` and carry the token's SHA-256, never the token; a cap above `internal` carries the responsibility date; an `intake_key` needs a `channel` (ADR 0016).
```

and after the line `- Referenced capabilities, roles, adapters and schema paths exist.` insert

```text
- One `TASK_SUBMITTED` per `intake_key` and `channel`, and a response to an R3 request only from `default-on-silence` (the ledger, ADR 0016).
```

In `CLAUDE.md` (owner-approved through ADR 0016 point 7) replace

```text
- Stack: Python 3.12+ (FastAPI, Pydantic v2, SQLite→Postgres), TypeScript dashboard, JSON Schema 2020-12.
```

with

```text
- Stack: Python 3.12+ (FastAPI, Pydantic v2, SQLite→Postgres), JavaScript dashboard with JSDoc types checked by `tsc --noEmit --checkJs`, no build step (ADR 0016), TypeScript SDK, JSON Schema 2020-12.
```

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS (nothing in the core uses the new schema parts yet)

- [ ] **Step 8: Commit**

```bash
git add docs/adr/0016-operator-api-tokens.md docs/adr/0003-schema-interpretations.md spec/schemas/common.schema.json spec/schemas/event.schema.json spec/examples/valid/event.operator_token_issued.json spec/examples/valid/event.operator_token_revoked.json spec/tests/test_schemas.py spec/ooat-specification.md spec/README.md CLAUDE.md core/src/ooat_core/ids.py core/tests/test_ids.py
git commit -m "feat(spec): token events, channel and intake_key; spec text of ADR 0016"
```

---

### Task 3: SQLite for threads and processes; one task per intake key

**Files:**
- Modify: `core/src/ooat_core/backends/__init__.py` (`LedgerBusyError`, `transaction()` in the protocol)
- Modify: `core/src/ooat_core/backends/sqlite.py` (WAL, busy timeout, `transaction()`, `insert()`)
- Modify: `core/src/ooat_core/ledger.py` (`DuplicateIntake`, checks inside the transaction, `_check_intake`)
- Test: `core/tests/test_sqlite_backend.py`, `core/tests/test_ledger.py`

**Interfaces:**
- Consumes: `channel` / `intake_key` in the `TASK_SUBMITTED` schema (Task 2); `new_id("tok")` (Task 2).
- Produces: `backends.LedgerBusyError(Exception)`; `LedgerBackend.transaction() -> ContextManager[None]` (raises `LedgerBusyError`, does not nest); `backends.sqlite.BUSY_TIMEOUT_MS = 5000` (read when a connection opens, so tests can lower it); `ledger.DuplicateIntake(ValueError)` with `.task: str`, raised by `Ledger.append` for a repeated `(channel, intake_key)`.

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_sqlite_backend.py` replace the imports

```python
import sqlite3

import pytest

from ooat_core.backends import LedgerIntegrityError
from ooat_core.backends.sqlite import SCHEMA_VERSION, SqliteBackend
```

with

```python
import sqlite3
import threading

import pytest

from ooat_core.backends import LedgerBusyError, LedgerIntegrityError
from ooat_core.backends.sqlite import BUSY_TIMEOUT_MS, SCHEMA_VERSION, SqliteBackend
```

and append at the end of the file:

```python


# Threads and processes (design 05 §7) ---------------------------------------------------------------------------

def test_a_file_ledger_uses_wal_and_a_five_second_busy_timeout(tmp_path):
    backend = SqliteBackend(tmp_path / "ledger.sqlite")
    assert backend._db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert backend._db.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS == 5000
    assert backend._db.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL, for an audit log
    backend.close()


def test_a_write_still_locked_out_after_the_timeout_is_busy_and_writes_nothing(tmp_path):
    path = tmp_path / "ledger.sqlite"
    backend = SqliteBackend(path)
    backend._db.execute("PRAGMA busy_timeout = 50")  # keep the test short
    other = sqlite3.connect(path, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")  # another process holds the write lock
    with pytest.raises(LedgerBusyError):
        backend.insert(EVENT, [ARTIFACT])
    other.execute("ROLLBACK")
    other.close()
    backend.insert(EVENT, [ARTIFACT])
    assert [row["id"] for row in backend.select_events(None, [])] == ["evt_1"]
    backend.close()


def test_opening_a_connection_while_another_writer_holds_the_lock_is_busy_too(tmp_path, monkeypatch):
    from ooat_core.backends import sqlite as sqlite_backend

    path = tmp_path / "ledger.sqlite"
    SqliteBackend(path).close()
    monkeypatch.setattr(sqlite_backend, "BUSY_TIMEOUT_MS", 50)
    other = sqlite3.connect(path, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(LedgerBusyError):  # opening runs the DDL, which needs the write lock
            SqliteBackend(path)
    finally:
        other.execute("ROLLBACK")
        other.close()


def test_readers_see_committed_rows_while_a_writer_holds_the_lock(tmp_path):
    path = tmp_path / "ledger.sqlite"
    backend = SqliteBackend(path)
    backend.insert(EVENT, [])
    reader = sqlite3.connect(path)
    with backend.transaction():
        backend.insert({**EVENT, "id": "evt_2"}, [])
        assert [row[0] for row in reader.execute("SELECT id FROM event")] == ["evt_1"]  # not blocked, not dirty
    assert [row[0] for row in reader.execute("SELECT id FROM event")] == ["evt_1", "evt_2"]
    reader.close()
    backend.close()


def test_a_failed_insert_inside_a_transaction_rolls_back_the_whole_transaction(tmp_path):
    backend = SqliteBackend(tmp_path / "ledger.sqlite")
    with pytest.raises(LedgerIntegrityError):
        with backend.transaction():
            backend.insert(EVENT, [])
            backend.insert(EVENT, [])  # duplicate id
    assert backend.select_events(None, []) == []
    with pytest.raises(RuntimeError, match="nest"):
        with backend.transaction():
            with backend.transaction():
                pass
    backend.close()


def _race(path, make_event, rounds=1, threads=2):
    """Append make_event() from `threads` threads at once, each on its own connection; the outcomes per round."""
    from ooat_core.ledger import Ledger

    outcomes = []
    for _ in range(rounds):
        events = [make_event() for _ in range(threads)]
        barrier, results = threading.Barrier(threads), [None] * threads

        def append(n):
            ledger = Ledger.open(f"sqlite:///{path.as_posix()}")
            barrier.wait()
            try:
                ledger.append(events[n])
                results[n] = "written"
            except Exception as error:  # noqa: BLE001 - the test inspects which error the loser got
                results[n] = error
            finally:
                ledger.close()

        workers = [threading.Thread(target=append, args=(n,)) for n in range(threads)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        outcomes.append(results)
    return outcomes


def test_two_threads_answering_one_request_write_one_answer_and_the_other_is_told(tmp_path):
    from ooat_core.ids import new_id
    from ooat_core.ledger import Ledger, new_event
    from ooat_core.validation import SpecValidationError

    path = tmp_path / "ledger.sqlite"
    ledger = Ledger.open(f"sqlite:///{path.as_posix()}")
    requests = []
    for _ in range(10):
        task = new_id("tsk")
        requests.append(ledger.append(new_event("HIL_REQUEST", task=task, actor={"kind": "system", "id": "x"}, body={
            "question": "Pokračovat?", "options": [{"id": "yes", "label": "Ano", "cost_usd": 0.0},
                                                    {"id": "no", "label": "Ne", "cost_usd": 0.0, "acts": False}],
            "recommended": "yes", "default_on_silence": "no", "deadline": "2026-10-12T10:00:00Z",
            "blocking": True, "evidence": []})))
    outcomes = []
    for request in requests:
        outcomes += _race(path, lambda r=request: new_event("HIL_RESPONSE", task=r["task"], actor={
            "kind": "hil", "id": "operator"}, body={"request": r["id"], "choice": "yes"}))
    for results in outcomes:
        assert results.count("written") == 1
        (loser,) = [r for r in results if r != "written"]
        # The check runs inside the write transaction, so the loser is told why, not hit by the unique index.
        assert isinstance(loser, SpecValidationError) and "already answered" in str(loser)
    assert len(ledger.events(types=["HIL_RESPONSE"])) == 10
    ledger.close()


def test_two_deliveries_of_one_chat_message_at_once_create_one_task(tmp_path):
    from ooat_core.ids import new_id
    from ooat_core.ledger import DuplicateIntake, Ledger, new_event

    path = tmp_path / "ledger.sqlite"
    Ledger.open(f"sqlite:///{path.as_posix()}").close()
    channel = "token:" + new_id("tok")
    for n in range(10):
        key = f"chat-1:msg-{n}"
        (results,) = _race(path, lambda k=key: new_event("TASK_SUBMITTED", task=new_id("tsk"), actor={
            "kind": "hil", "id": "operator"}, body={"goal": "Shrň smlouvu.", "channel": channel, "intake_key": k}))
        assert results.count("written") == 1
        (loser,) = [r for r in results if r != "written"]
        assert isinstance(loser, DuplicateIntake) and loser.task.startswith("tsk_")
    ledger = Ledger.open(f"sqlite:///{path.as_posix()}")
    assert len(ledger.events(types=["TASK_SUBMITTED"])) == 10
    ledger.close()
```

In `core/tests/test_ledger.py` replace `from ooat_core.ledger import Ledger, StagedArtifact, _event_row, new_event` with
`from ooat_core.ledger import DuplicateIntake, Ledger, StagedArtifact, _event_row, new_event` and append at the end:

```python


def submission(key, channel="web"):
    return new_event("TASK_SUBMITTED", task=new_id("tsk"), actor=HIL,
                     body={"goal": "Shrnout výroční zprávu.", "channel": channel, "intake_key": key})


def test_a_repeated_intake_key_on_its_channel_is_refused_and_names_the_first_task(ledger):
    first = ledger.append(submission("msg-7"))
    with pytest.raises(DuplicateIntake) as refused:
        ledger.append(submission("msg-7"))
    assert refused.value.task == first["task"]
    assert len(ledger.events(types=["TASK_SUBMITTED"])) == 1


def test_the_same_intake_key_on_another_channel_is_another_task(ledger):
    ledger.append(submission("msg-7"))
    ledger.append(submission("msg-7", channel="token:" + new_id("tok")))
    ledger.append(new_event("TASK_SUBMITTED", task=new_id("tsk"), actor=HIL, body={"goal": "Bez klíče."}))
    assert len(ledger.events(types=["TASK_SUBMITTED"])) == 3


def test_a_refused_event_inside_the_transaction_leaves_the_ledger_writable(ledger):
    task = new_id("tsk")
    request = ledger.append(hil_request(task, "R1", "hold"))
    answer = new_event("HIL_RESPONSE", task=task, actor=HIL, body={"request": request["id"], "choice": "maybe"})
    with pytest.raises(SpecValidationError):
        ledger.append(answer)  # refused inside the write transaction, which must be rolled back
    ledger.append(new_event("HIL_RESPONSE", task=task, actor=HIL, body={"request": request["id"], "choice": "hold"}))
    assert len(ledger.events(task=task)) == 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest core/tests/test_sqlite_backend.py core/tests/test_ledger.py -q`
Expected: FAIL — `ImportError: cannot import name 'LedgerBusyError'` (and, once that exists, `DuplicateIntake`).

- [ ] **Step 3: Implement**

In `core/src/ooat_core/backends/__init__.py` replace

```python
from typing import Protocol
```

with

```python
from contextlib import AbstractContextManager
from typing import Protocol
```

and replace

```python
class LedgerBackend(Protocol):
    def insert(self, event_row: dict, artifact_rows: list[dict]) -> None:
        """Insert one event row and its artifact rows in a single transaction.
```

with

```python
class LedgerBusyError(Exception):
    """Another writer held the ledger past the busy timeout; nothing was written (API: 503 LEDGER_BUSY)."""


class LedgerBackend(Protocol):
    def transaction(self) -> AbstractContextManager[None]:
        """One write transaction holding the write lock from its start, so checks made inside it and the insert are
        serialised across threads and processes. Raises LedgerBusyError when the lock is not free in time."""

    def insert(self, event_row: dict, artifact_rows: list[dict]) -> None:
        """Insert one event row and its artifact rows in a single transaction (the open one, if any).
```

In `core/src/ooat_core/backends/sqlite.py` replace

```python
"""SQLite ledger backend (Solo profile)."""

import sqlite3
from pathlib import Path

from . import LedgerIntegrityError
```

with

```python
"""SQLite ledger backend (Solo profile).

One connection per thread (`check_same_thread` stays on). WAL lets readers run while one writer appends; every
write is one `BEGIN IMMEDIATE` transaction, so the ledger's checks and its insert are serialised across threads and
processes (design 05 §7). WAL needs a local disk: it does not work on network shares.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path

from . import LedgerBusyError, LedgerIntegrityError

BUSY_TIMEOUT_MS = 5000  # a writer waits this long for the lock, then the write fails as LedgerBusyError
_BUSY = frozenset({"SQLITE_BUSY", "SQLITE_LOCKED"})
```

replace

```python
    def __init__(self, path: str | Path):
        self._db = sqlite3.connect(str(path))
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        (version,) = self._db.execute("PRAGMA user_version").fetchone()
```

with

```python
    def __init__(self, path: str | Path):
        # No implicit transactions: transaction() opens BEGIN IMMEDIATE itself.
        self._db = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._in_transaction = False
        try:
            self._prepare()
        except sqlite3.OperationalError as error:  # another writer held the file past the busy timeout
            self._db.close()
            if error.sqlite_errorname in _BUSY:
                raise LedgerBusyError("the ledger is busy; try again") from error
            raise

    def _prepare(self) -> None:
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")  # persistent in the file; ":memory:" stays "memory"
        (version,) = self._db.execute("PRAGMA user_version").fetchone()
```

and replace

```python
    def insert(self, event_row: dict, artifact_rows: list[dict]) -> None:
        try:
            with self._db:  # commits on success, rolls back on any error
                self._insert("event", event_row)
                for row in artifact_rows:
                    self._insert("artifact", row)
        except sqlite3.IntegrityError as error:
            raise LedgerIntegrityError(str(error)) from error
```

with

```python
    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._in_transaction:
            raise RuntimeError("ledger transactions do not nest")
        try:
            self._db.execute("BEGIN IMMEDIATE")  # takes the write lock now, waiting up to the busy timeout
        except sqlite3.OperationalError as error:
            if error.sqlite_errorname in _BUSY:
                raise LedgerBusyError("the ledger is busy; try again") from error
            raise
        self._in_transaction = True
        try:
            yield
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        finally:
            self._in_transaction = False

    def insert(self, event_row: dict, artifact_rows: list[dict]) -> None:
        with nullcontext() if self._in_transaction else self.transaction():
            try:
                self._insert("event", event_row)
                for row in artifact_rows:
                    self._insert("artifact", row)
            except sqlite3.IntegrityError as error:
                raise LedgerIntegrityError(str(error)) from error
```

(`_prepare` keeps the rest of the old `__init__` unchanged: the newer-version refusal, `executescript(_DDL)`, the
`estimated_usd` migration and the `user_version` stamp. With `isolation_level=None` each of those statements commits
on its own, as before.)

In `core/src/ooat_core/ledger.py` replace

```python
def utc_now() -> str:
```

with

```python
class DuplicateIntake(ValueError):
    """A TASK_SUBMITTED repeats an intake key already used on its channel; `task` is the task that key created."""

    def __init__(self, task: str):
        super().__init__(f"this intake key already created {task}")
        self.task = task


def utc_now() -> str:
```

and replace the part of `Ledger.append` from `        self._check_hil(event)` to `        return event` with:

```python
        artifacts = list(artifacts)
        staged_refs = {a.ref for a in artifacts}
        unreferenced = sorted(staged_refs - set(event["refs"]))
        if unreferenced:
            raise ValueError(f"staged artifacts must be referenced by their event: {unreferenced}")
        # Checks that read the ledger run inside the write transaction, so another thread or process cannot slip an
        # answer, an artifact version or an intake key in between the check and the insert (design 05 §7).
        with self.backend.transaction():
            self._check_hil(event)
            self._check_intake(event)
            self._check_staged(artifacts)
            unknown = sorted(ref for ref in _artifact_refs([event["refs"], event["body"]])
                             if ref not in staged_refs and self.artifact(ref) is None)
            if unknown:
                raise ValueError(f"event references unknown artifacts: {unknown}")
            artifact_rows = []
            for artifact in artifacts:
                artifact_id, version = parse_artifact_ref(artifact.ref)
                artifact_rows.append({
                    "id": artifact_id, "version": version, "type": artifact.type, "data_class": artifact.data_class,
                    "untrusted": int(artifact.untrusted), "sha256": artifact.sha256, "uri": artifact.uri,
                    "produced_by_event": event["id"],
                })
            self.backend.insert(_event_row(event), artifact_rows)
        return event

    def _check_intake(self, event: dict) -> None:
        """One task per intake key and channel, also across restarts and racing deliveries (ADR 0016)."""
        key = event["body"].get("intake_key") if event["type"] == "TASK_SUBMITTED" else None
        if key is None:
            return
        channel = event["body"].get("channel")
        for earlier in self.events(types=["TASK_SUBMITTED"]):
            if earlier["body"].get("intake_key") == key and earlier["body"].get("channel") == channel:
                raise DuplicateIntake(earlier["task"])
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest core/tests/test_sqlite_backend.py core/tests/test_ledger.py -q`
Expected: PASS

Run: `python -m pytest -q`
Expected: PASS (the whole suite: nothing else depends on the old implicit transactions)

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/backends/__init__.py core/src/ooat_core/backends/sqlite.py core/src/ooat_core/ledger.py core/tests/test_sqlite_backend.py core/tests/test_ledger.py
git commit -m "feat(core): WAL ledger, BEGIN IMMEDIATE appends, one task per intake key (plan 05a)"
```

---

### Task 4: One path per human action: channel, cancel, R3 on every channel

**Files:**
- Create: `core/src/ooat_core/hil.py`
- Modify: `core/src/ooat_core/runtime.py` (`submit` channel and intake key, `cancel`, the cancel checks, `expire`, `runnable`)
- Modify: `core/src/ooat_core/ledger.py` (R3 answered only by its default on silence)
- Modify: `core/src/ooat_core/rating.py` (`channel`, `NotClosed`, `AlreadyRated`)
- Modify: `core/src/ooat_core/connector_admin.py` (`channel` on `acknowledge`, `approve_hooks`, `disable`)
- Modify: `core/src/ooat_core/task_cli.py` (`hil list` / `hil answer` through `hil.py`, channel `cli`)
- Modify: `core/src/ooat_core/operator_cli.py` (channel `cli` on the connector actions)
- Test: `core/tests/test_hil.py` (new), `core/tests/test_runtime.py`, `core/tests/test_ledger.py`, `core/tests/test_rating.py`, `core/tests/test_task_cli.py`, `core/tests/test_operator_cli.py`

**Interfaces:**
- Consumes: `DuplicateIntake` (Task 3); the schema's `channel` in six bodies (Task 2).
- Produces:
  - `hil.open_requests(ledger) -> list[dict]` (open tasks only); `hil.find_request(ledger, request_id) -> dict | None`;
    `hil.answer(ledger, runtime, request_id, *, operator: str, choice: str | None = None, text: str | None = None,
    channel: str | None = None) -> dict` (the appended `HIL_RESPONSE`); errors `hil.UnknownRequest`,
    `hil.AlreadyAnswered`, `hil.R3NeedsBoundIdentity` (attribute `code = "R3_NEEDS_BOUND_IDENTITY"`), all `ValueError`.
  - `Runtime.submit(..., channel: str | None = None, intake_key: str | None = None) -> str` (a repeated key returns
    the first task); `Runtime.cancel(task, *, operator: str, channel: str | None = None) -> bool` (False when already
    asked); `runtime.CANCEL = "cancel the task"`; errors `runtime.UnknownTask`, `runtime.TaskClosed` (`ValueError`).
  - `rate(..., channel: str | None = None)`; errors `rating.NotClosed`, `rating.AlreadyRated` (`ValueError`).
  - `connector_admin.acknowledge(..., channel=None)`, `approve_hooks(..., channel=None)`, `disable(..., channel=None)`.
  - `ledger.SILENCE_ACTOR_ID = "default-on-silence"`; the ledger refuses a response under that actor unless it
    carries `default_applied: true` and chooses the request's `default_on_silence`, and refuses any other actor's
    response to an R3 request.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_hil.py`:

```python
"""The shared answer path, R3 on every channel, and who may write a human event (design 05 §6, ADR 0016)."""

import re
from datetime import timedelta
from pathlib import Path

import pytest
from test_runtime import NOW, Setup

import ooat_core
from ooat_core.hil import AlreadyAnswered, R3NeedsBoundIdentity, UnknownRequest, answer, open_requests
from ooat_core.ids import new_id
from ooat_core.ledger import new_event
from ooat_core.runtime import TaskClosed

TOKEN_CHANNEL = "token:tok_01J9ZQ80B0K3M5N7P9Q1R3S5T7"


def waiting(tmp_path):
    """A task waiting for a clarification, and its open request."""
    setup = Setup(tmp_path)
    task = setup.submit(acceptance=())
    return setup, task, setup.runtime.run(task).request


def r3_request(setup, task):
    return setup.ledger.append(new_event("HIL_REQUEST", task=task, actor={"kind": "system", "id": "ooat-runtime"},
                                         body={"question": "Odeslat nabídku klientovi?", "risk_class": "R3",
                                               "options": [{"id": "send", "label": "Odeslat", "cost_usd": 0.0},
                                                           {"id": "hold", "label": "Neodesílat", "cost_usd": 0.0,
                                                            "acts": False}],
                                               "recommended": "send", "default_on_silence": "hold",
                                               "deadline": "2026-10-03T12:00:00Z", "blocking": True,
                                               "evidence": []}))


def test_an_answer_records_the_operator_and_the_channel(tmp_path):
    setup, task, request = waiting(tmp_path)
    response = answer(setup.ledger, setup.runtime, request, operator=" operator ", text=" Nejvýše 300 slov. ",
                      channel=TOKEN_CHANNEL)
    assert response["actor"] == {"kind": "hil", "id": "operator"}
    assert response["body"] == {"request": request, "text": "Nejvýše 300 slov.", "channel": TOKEN_CHANNEL}
    assert open_requests(setup.ledger) == []


@pytest.mark.parametrize("channel", ["cli", "web", TOKEN_CHANNEL])
def test_an_r3_request_is_refused_on_every_channel(tmp_path, channel):
    setup, task, _ = waiting(tmp_path)
    request = r3_request(setup, task)
    for choice in ("send", "hold"):
        with pytest.raises(R3NeedsBoundIdentity):
            answer(setup.ledger, setup.runtime, request["id"], operator="operator", choice=choice, channel=channel)
    assert not any(e["body"]["request"] == request["id"] for e in setup.ledger.events(types=["HIL_RESPONSE"]))


def test_a_second_answer_and_a_late_answer_are_already_answered(tmp_path):
    setup, task, request = waiting(tmp_path)
    answer(setup.ledger, setup.runtime, request, operator="operator", choice="run_as_is", channel="web")
    with pytest.raises(AlreadyAnswered):
        answer(setup.ledger, setup.runtime, request, operator="second-operator", choice="do_not_run", channel="web")
    setup, task, request = waiting(tmp_path)
    setup.now = NOW + timedelta(hours=49)  # the default applies first
    with pytest.raises(AlreadyAnswered):
        answer(setup.ledger, setup.runtime, request, operator="operator", choice="run_as_is", channel="web")
    assert setup.last(task, "HIL_RESPONSE")["actor"]["id"] == "default-on-silence"


def test_mistakes_are_refused_before_anything_is_written(tmp_path):
    setup, task, request = waiting(tmp_path)
    with pytest.raises(UnknownRequest):
        answer(setup.ledger, setup.runtime, new_id("evt"), operator="operator", choice="clarify")
    with pytest.raises(ValueError, match="a choice, a text or both"):
        answer(setup.ledger, setup.runtime, request, operator="operator", text="  ")
    with pytest.raises(ValueError, match="reserved"):
        answer(setup.ledger, setup.runtime, request, operator="default-on-silence", choice="do_not_run")
    assert len(open_requests(setup.ledger)) == 1


def test_the_question_of_a_cancelled_task_is_neither_open_nor_answerable(tmp_path):
    setup, task, request = waiting(tmp_path)
    assert setup.runtime.cancel(task, operator="operator", channel="web")
    assert setup.runtime.run(task).state == "CANCELLED"
    assert open_requests(setup.ledger) == []
    with pytest.raises(TaskClosed):
        answer(setup.ledger, setup.runtime, request, operator="operator", choice="run_as_is")
    setup.now = NOW + timedelta(hours=49)
    assert setup.runtime.expire() == []  # no default is applied to a closed task


# Who may write a human event (design 05 §6) -------------------------------------------------------------------

HIL_ACTOR = re.compile(r"""["']kind["']\s*:\s*["']hil["']""")
# Runtime.submit, cancel and default-on-silence; rating; the answer path; connector state; operator tokens.
MAY_BUILD_A_HUMAN_ACTOR = {"runtime.py", "rating.py", "hil.py", "connector_admin.py", "tokens.py"}


def test_only_the_listed_modules_build_a_human_actor():
    source = Path(ooat_core.__file__).parent
    found = {path.relative_to(source).as_posix() for path in source.rglob("*.py")
             if HIL_ACTOR.search(path.read_text(encoding="utf-8"))}
    assert found <= MAY_BUILD_A_HUMAN_ACTOR, f"human actor outside the allow-list: {found - MAY_BUILD_A_HUMAN_ACTOR}"
    assert {"runtime.py", "rating.py", "hil.py", "connector_admin.py"} <= found  # the check finds what it guards
```

In `core/tests/test_runtime.py` append at the end:

```python


# Channel, intake key and the operator's cancel (design 05 §6, §12, §13) -----------------------------------------

def test_a_repeated_intake_key_returns_the_task_it_created(tmp_path):
    setup = Setup(tmp_path)
    first = setup.submit(channel="web", intake_key="chat-1:msg-7")
    assert setup.submit(channel="web", intake_key="chat-1:msg-7") == first
    assert setup.submit(channel="token:tok_01J9ZQ80B0K3M5N7P9Q1R3S5T7", intake_key="chat-1:msg-7") != first
    body = setup.last(first, "TASK_SUBMITTED")["body"]
    assert body["channel"] == "web" and body["intake_key"] == "chat-1:msg-7"


def test_a_cancelled_waiting_task_closes_as_cancelled_at_its_next_run(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit(acceptance=())
    assert setup.runtime.run(task).state == "CLARIFYING"
    assert setup.runtime.cancel(task, operator="operator", channel="web") is True
    assert setup.runtime.cancel(task, operator="operator") is False  # asked once is enough
    assert task in setup.runtime.runnable()  # the runner picks it up although it waits for an answer
    outcome = setup.runtime.run(task)
    assert outcome.state == "CANCELLED" and outcome.summary == "Cancelled by operator."
    decision = setup.last(task, "DECISION")
    assert decision["actor"] == {"kind": "hil", "id": "operator"}
    assert decision["body"] == {"decision": "cancel the task", "channel": "web"}
    assert task not in setup.runtime.runnable()


def test_a_cancel_during_the_worker_call_keeps_the_document_and_skips_the_checks(tmp_path):
    class CancelledWhileWriting(ScriptedModel):
        def complete(self, request, secrets):
            response = super().complete(request, secrets)
            if len(self.worker_prompts) == 1:  # the operator cancels while the worker writes
                setup.runtime.cancel(task, operator="operator")
            return response

    setup = Setup(tmp_path, model=CancelledWhileWriting())
    task = setup.submit()
    outcome = setup.runtime.run(task)
    assert outcome.state == "CANCELLED" and outcome.artifact
    assert setup.types(task)[-3:] == ["DECISION", "RESULT", "TASK_CLOSED"]  # the worker's cost is still recorded
    assert "GATE_PASSED" not in setup.types(task)[3:]  # no acceptance check was paid for after the cancel


def test_a_closed_or_unknown_task_cannot_be_cancelled(tmp_path):
    from ooat_core.runtime import TaskClosed, UnknownTask

    setup = Setup(tmp_path)
    task = setup.submit()
    setup.runtime.run(task)
    with pytest.raises(TaskClosed):
        setup.runtime.cancel(task, operator="operator")
    with pytest.raises(UnknownTask):
        setup.runtime.cancel("tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7", operator="operator")
```

In `core/tests/test_ledger.py` replace `HIL = {"kind": "hil", "id": "operator"}` with

```python
HIL = {"kind": "hil", "id": "operator"}
SILENCE = {"kind": "hil", "id": "default-on-silence"}
```

and in `test_default_applied_response_must_record_the_requests_default` replace

```python
    ledger.append(new_event("HIL_RESPONSE", task=task, actor=HIL,
                            body={"request": request["id"], "choice": "hold", "default_applied": True}))
```

with

```python
    ledger.append(new_event("HIL_RESPONSE", task=task, actor=SILENCE,
                            body={"request": request["id"], "choice": "hold", "default_applied": True}))


def test_an_r3_request_is_answered_only_by_its_default_on_silence(ledger):
    task = new_id("tsk")
    request = ledger.append(hil_request(task, "R3", "hold"))
    for choice in ("send", "hold"):  # not even the do-not-act option: no human may answer R3 yet (ADR 0016)
        with pytest.raises(SpecValidationError, match="R3_NEEDS_BOUND_IDENTITY"):
            ledger.append(new_event("HIL_RESPONSE", task=task, actor=HIL,
                                    body={"request": request["id"], "choice": choice}))
    ledger.append(new_event("HIL_RESPONSE", task=task, actor=SILENCE,
                            body={"request": request["id"], "choice": "hold", "default_applied": True}))


@pytest.mark.parametrize("risk", ["R1", "R3"])
@pytest.mark.parametrize("body", [{"choice": "send", "default_applied": True},  # an acting choice
                                  {"choice": "hold"},  # default_applied missing
                                  {"text": "Nikdo neodpověděl.", "default_applied": True}],  # no choice at all
                         ids=["acting_choice", "without_default_applied", "without_choice"])
def test_the_silence_actor_only_applies_the_declared_default(ledger, risk, body):
    task = new_id("tsk")
    request = ledger.append(hil_request(task, risk, "hold"))
    with pytest.raises(SpecValidationError, match="default-on-silence only applies"):
        ledger.append(new_event("HIL_RESPONSE", task=task, actor=SILENCE, body={"request": request["id"], **body}))
    assert ledger.events(types=["HIL_RESPONSE"]) == []
```

In `core/tests/test_rating.py` replace `def test_only_a_closed_task_can_be_rated(tmp_path):` with

```python
def test_a_task_is_rated_once_and_the_rating_records_its_channel(tmp_path):
    from ooat_core.rating import AlreadyRated

    setup, task = closed_task(tmp_path)
    event = rate(setup.ledger, task, operator="operator", accepted=True, value_class="B", channel="web")
    assert event["body"]["channel"] == "web"
    with pytest.raises(AlreadyRated):  # a second rating would count its verdicts twice in the thresholds
        rate(setup.ledger, task, operator="operator", accepted=False, value_class="C")


def test_only_a_closed_task_can_be_rated(tmp_path):
```

In `core/tests/test_task_cli.py` replace `def test_a_hand_over_after_the_decision_tier_failed_is_labelled_too():` with

```python
def test_cli_events_record_the_cli_channel(env):
    _, out = ooat(env, "task", "submit", "--operator", "operator", "--goal", "Shrň smlouvu.")
    task = task_id(out)
    request = out.split("Question ", 1)[1].split(" ", 1)[0]
    ooat(env, "hil", "answer", request, "--operator", "operator", "--text", "Shrnutí má nejvýše 300 slov.")
    ooat(env, "task", "rate", task, "--operator", "operator", "--accepted", "yes", "--value", "B", "--confirm-all")
    for kind in ("TASK_SUBMITTED", "HIL_RESPONSE", "TASK_RATED"):
        assert events(env, task, kind)[0]["body"]["channel"] == "cli", kind


def test_the_cli_refuses_to_answer_an_r3_request(env):
    from ooat_core.ledger import new_event

    _, out = ooat(env, "task", "submit", "--operator", "operator", "--goal", "Shrň smlouvu.", "--no-run")
    task = task_id(out)
    ledger = Ledger.open(env["ledger"])
    request = ledger.append(new_event("HIL_REQUEST", task=task, actor={"kind": "system", "id": "ooat-runtime"}, body={
        "question": "Odeslat nabídku?", "risk_class": "R3", "options": [
            {"id": "send", "label": "Odeslat", "cost_usd": 0.0}, {"id": "hold", "label": "Ne", "cost_usd": 0.0,
                                                                 "acts": False}],
        "recommended": "send", "default_on_silence": "hold", "deadline": "2026-10-03T12:00:00Z", "blocking": True,
        "evidence": []}))
    ledger.close()
    code, answered = ooat(env, "hil", "answer", request["id"], "--operator", "operator", "--choice", "hold")
    assert code == 1 and "named approver" in answered and events(env, task, "HIL_RESPONSE") == []


def test_a_hand_over_after_the_decision_tier_failed_is_labelled_too():
```

In `core/tests/test_operator_cli.py` replace
`        "adapter": "prv.fake.api", "operator": "Martin", "reason": "trial ended"}` with
`        "adapter": "prv.fake.api", "operator": "Martin", "reason": "trial ended", "channel": "cli"}`.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest core/tests/test_hil.py core/tests/test_runtime.py core/tests/test_ledger.py core/tests/test_rating.py core/tests/test_task_cli.py core/tests/test_operator_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.hil'`; after it exists, the cancel, channel, rating and R3 tests fail with `TypeError: ... unexpected keyword argument 'channel'` / `AttributeError: 'Runtime' object has no attribute 'cancel'` / no `R3_NEEDS_BOUND_IDENTITY`.

- [ ] **Step 3: Write `hil.py`**

Create `core/src/ooat_core/hil.py`:

```python
"""The operator's answer to a HIL request, shared by the CLI and the API (design 05 §6).

Every channel answers through `answer()`: it refuses R3 requests (spec §9 as amended by ADR 0016: no operator
identity is bound to something the operator holds yet), applies a passed deadline first so a late answer never wins,
refuses a request that already has its answer, and records the operator and the channel. The caller runs the task
on (the CLI) or queues it for the runner (the server); this module never runs a task.
"""

from .connector_admin import checked_operator
from .ledger import Ledger, new_event
from .runtime import Runtime, TaskClosed
from .validation import SpecValidationError


class UnknownRequest(ValueError):
    """No HIL_REQUEST with this id."""


class AlreadyAnswered(ValueError):
    """The request has its answer: the operator's, or the default applied after its deadline."""


class R3NeedsBoundIdentity(ValueError):
    """R3 needs a named approver bound to something they hold; a self-declared name or a token is not one."""

    code = "R3_NEEDS_BOUND_IDENTITY"


def open_requests(ledger: Ledger) -> list[dict]:
    """HIL_REQUEST events of open tasks without a HIL_RESPONSE, oldest first."""
    events = ledger.events(types=["HIL_REQUEST", "HIL_RESPONSE", "TASK_CLOSED"])
    answered = {e["body"]["request"] for e in events if e["type"] == "HIL_RESPONSE"}
    closed = {e["task"] for e in events if e["type"] == "TASK_CLOSED"}
    return [e for e in events if e["type"] == "HIL_REQUEST" and e["id"] not in answered and e["task"] not in closed]


def find_request(ledger: Ledger, request_id: str) -> dict | None:
    return next((e for e in ledger.events(types=["HIL_REQUEST"]) if e["id"] == request_id), None)


def answer(ledger: Ledger, runtime: Runtime, request_id: str, *, operator: str, choice: str | None = None,
           text: str | None = None, channel: str | None = None) -> dict:
    """Append the operator's HIL_RESPONSE and return it."""
    operator = checked_operator(operator)
    text = (text or "").strip() or None
    if choice is None and text is None:
        raise ValueError("give a choice, a text or both")
    if choice == "narrow_scope" and text is None:  # it would use up a budget question
        raise ValueError("narrow_scope needs the narrowed scope as text")
    request = find_request(ledger, request_id)
    if request is None:
        raise UnknownRequest(f"no question {request_id}")
    if request["body"].get("risk_class") == "R3":
        raise R3NeedsBoundIdentity("an R3 request needs a named approver bound to something they hold (a passkey "
                                   "or an OS-account check); a typed name or a token is not one (ADR 0016)")
    runtime.expire(request["task"])  # past its deadline the default has applied; a late answer must not win
    events = ledger.events(task=request["task"], types=["HIL_RESPONSE", "TASK_CLOSED"])
    if any(e["type"] == "HIL_RESPONSE" and e["body"]["request"] == request_id for e in events):
        raise AlreadyAnswered(f"{request_id} is already answered (after its deadline the default applies)")
    if any(e["type"] == "TASK_CLOSED" for e in events):
        raise TaskClosed(f"task {request['task']} is closed; its question needs no answer")
    body = {"request": request_id}
    if choice is not None:
        body["choice"] = choice
    if text is not None:
        body["text"] = text
    if channel is not None:
        body["channel"] = channel
    try:
        return ledger.append(new_event("HIL_RESPONSE", task=request["task"], actor={"kind": "hil", "id": operator},
                                       body=body))
    except SpecValidationError as error:  # another writer answered between the check above and the append
        if any("is already answered" in message for message in error.messages):
            raise AlreadyAnswered(f"{request_id} is already answered") from None
        raise
```

- [ ] **Step 4: Change the runtime, the ledger, rating and connector actions**

In `core/src/ooat_core/runtime.py`:

1. Replace `from .ledger import Ledger, new_event` with `from .ledger import DuplicateIntake, Ledger, new_event`.
2. Replace `ABSTAIN_FOR = {"NOT_PERMITTED": "ABSTAIN_NOT_PERMITTED"}` with

```python
ABSTAIN_FOR = {"NOT_PERMITTED": "ABSTAIN_NOT_PERMITTED"}
CANCEL = "cancel the task"  # the operator's DECISION that stops a task (owner, 2026-10-09)


class UnknownTask(ValueError):
    """No TASK_SUBMITTED with this id."""


class TaskClosed(ValueError):
    """The task is already closed; nothing can change it but a rating."""
```

3. Replace

```python
def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
```

with

```python
def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _cancel(events: list[dict]) -> dict | None:
    """The operator's cancel DECISION among the task's events, if any."""
    return next((e for e in events if e["type"] == "DECISION" and e["actor"]["kind"] == "hil"
                 and e["body"]["decision"] == CANCEL), None)
```

4. In `submit` replace

```python
               files: list[bytes] = (), file_names: list[str] = ()) -> str:
        """TASK_SUBMITTED by the named operator; files become untrusted artifacts of the task, stored under the
        declared class raised by the personal-data pre-scan of their text."""
        body = {"goal": goal.strip()}
        optional = {"project": project, "expected_output": expected_output, "value": value, "budget_usd": budget_usd,
                    "data_class": data_class, "risk_class": risk_class}
```

with

```python
               files: list[bytes] = (), file_names: list[str] = (), channel: str | None = None,
               intake_key: str | None = None) -> str:
        """TASK_SUBMITTED by the named operator; files become untrusted artifacts of the task, stored under the
        declared class raised by the personal-data pre-scan of their text. A repeated `intake_key` on the same
        channel returns the task it created instead of a new one (ADR 0016)."""
        body = {"goal": goal.strip()}
        optional = {"project": project, "expected_output": expected_output, "value": value, "budget_usd": budget_usd,
                    "data_class": data_class, "risk_class": risk_class, "channel": channel, "intake_key": intake_key}
```

5. Replace

```python
        self.ledger.append(new_event("TASK_SUBMITTED", task=task, actor=actor, refs=[s.ref for s in staged], body=body),
                           staged)
        return task
```

with

```python
        try:
            self.ledger.append(new_event("TASK_SUBMITTED", task=task, actor=actor, refs=[s.ref for s in staged],
                                         body=body), staged)
        except DuplicateIntake as repeated:  # a retried delivery; the staged blobs stay unreferenced
            return repeated.task
        return task

    def cancel(self, task: str, *, operator: str, channel: str | None = None) -> bool:
        """The operator stops a task: a DECISION by them, after which the task closes as CANCELLED at its next run.
        A task the runner is running closes after the call in flight, so that call's cost is still recorded.
        Returns False when a cancel was already asked for."""
        operator = checked_operator(operator)
        events = self.ledger.events(task=task)
        state = task_state(events)
        if state is None:
            raise UnknownTask(f"unknown task {task}")
        if state in CLOSED:
            raise TaskClosed(f"task {task} is {state}")
        if _cancel(events) is not None:
            return False
        body = {"decision": CANCEL} | ({"channel": channel} if channel else {})
        self.ledger.append(new_event("DECISION", task=task, actor={"kind": "hil", "id": operator}, body=body))
        return True

    def _stopped(self, task: str, artifacts: list[str] = ()) -> RunOutcome | None:
        """Close a task whose cancel the operator asked for; None when nobody did."""
        cancel = _cancel(self.ledger.events(task=task, types=["DECISION"]))
        if cancel is None:
            return None
        return self._close(task, "CANCELLED", f"Cancelled by {cancel['actor']['id']}.", artifacts=artifacts)
```

6. In `run` replace

```python
        if state in CLOSED:
            return RunOutcome(state, "The task is closed.")
        facts = task_facts(events, self.settings)
```

with

```python
        if state in CLOSED:
            return RunOutcome(state, "The task is closed.")
        stopped = self._stopped(task)
        if stopped is not None:
            return stopped
        facts = task_facts(events, self.settings)
```

7. In `expire` replace

```python
        events = self.ledger.events(task=task, types=["HIL_REQUEST", "HIL_RESPONSE"])
        answered = {e["body"]["request"] for e in events if e["type"] == "HIL_RESPONSE"}
        now, expired = self.clock(), []
        for request in events:
            if request["type"] == "HIL_REQUEST" and request["id"] not in answered \
```

with

```python
        events = self.ledger.events(task=task, types=["HIL_REQUEST", "HIL_RESPONSE", "TASK_CLOSED"])
        answered = {e["body"]["request"] for e in events if e["type"] == "HIL_RESPONSE"}
        closed = {e["task"] for e in events if e["type"] == "TASK_CLOSED"}  # e.g. cancelled while it waited
        now, expired = self.clock(), []
        for request in events:
            if request["type"] == "HIL_REQUEST" and request["id"] not in answered and request["task"] not in closed \
```

8. Replace the end of `runnable`

```python
        """Tasks that can move without the operator: submitted, gated, or paused by a provider failure."""
        self.expire()
        tasks = {}
        for event in self.ledger.events():
            if event["task"] is not None:
                tasks.setdefault(event["task"], []).append(event)
        return [task for task, events in tasks.items()
                if task_state(events) in ("SUBMITTED", "GATED", "RUNNING")]
```

with

```python
        """Tasks that can move without the operator: submitted, gated, paused by a provider failure, or waiting
        with a cancel the operator asked for."""
        self.expire()
        tasks = {}
        for event in self.ledger.events():
            if event["task"] is not None:
                tasks.setdefault(event["task"], []).append(event)
        return [task for task, events in tasks.items() if (state := task_state(events)) in
                ("SUBMITTED", "GATED", "RUNNING") or (state not in CLOSED and _cancel(events) is not None)]
```

9. In `_execute` replace

```python
        resumed = True  # only the first pass of a run picks up a document delivered before an interruption
        while True:
            results = [e for e in self.ledger.events(task=task, types=["RESULT"]) if e.get("contract") == contract]
```

with

```python
        resumed = True  # only the first pass of a run picks up a document delivered before an interruption
        while True:
            stopped = self._stopped(task)
            if stopped is not None:
                return stopped
            results = [e for e in self.ledger.events(task=task, types=["RESULT"]) if e.get("contract") == contract]
```

and replace

```python
            resumed = False
            try:
                result = check_output(
```

with

```python
            resumed = False
            stopped = self._stopped(task, artifacts=[artifact])  # cancelled during the worker call: keep its document
            if stopped is not None:
                return stopped
            try:
                result = check_output(
```

In `core/src/ooat_core/ledger.py` replace

```python
DATA_CLASSES = frozenset({"public", "internal", "client_confidential", "personal", "special_category"})
```

with

```python
DATA_CLASSES = frozenset({"public", "internal", "client_confidential", "personal", "special_category"})
SILENCE_ACTOR_ID = "default-on-silence"  # the runtime applying a request's declared default (spec §9 rule 5)
```

and in `_check_hil` replace `                if request["body"].get("risk_class") == "R3" and "choice" not in body:` with

```python
                if event["actor"]["id"] == SILENCE_ACTOR_ID and not (
                        body.get("default_applied") is True
                        and body.get("choice") == request["body"]["default_on_silence"]):
                    errors.append("$.body: default-on-silence only applies the request's default, with "
                                  "default_applied: true")
                if request["body"].get("risk_class") == "R3" and event["actor"]["id"] != SILENCE_ACTOR_ID:
                    # Spec §9 as amended by ADR 0016: no identity bound to something the operator holds exists yet.
                    errors.append("R3_NEEDS_BOUND_IDENTITY: an R3 request needs a named approver with a bound "
                                  "identity; until one exists only its default on silence applies")
                if request["body"].get("risk_class") == "R3" and "choice" not in body:
```

In `core/src/ooat_core/rating.py` replace

```python
CHOICE_OPTIONS = {"a5": set(BRANCHES), "a10": set(DATA_CLASSES)}  # the Gate's choice questions
```

with

```python
CHOICE_OPTIONS = {"a5": set(BRANCHES), "a10": set(DATA_CLASSES)}  # the Gate's choice questions


class NotClosed(ValueError):
    """Only a closed task is rated."""


class AlreadyRated(ValueError):
    """A task is rated once."""
```

replace `         verdicts: dict[tuple[str, str], object] = None, note: str | None = None) -> dict:` with
`         verdicts: dict[tuple[str, str], object] = None, note: str | None = None, channel: str | None = None) -> dict:`,
replace

```python
    if state not in CLOSED:
        raise ValueError(f"task {task} is {state}; rate it once it is closed")
    operator = checked_operator(operator)
```

with

```python
    if state not in CLOSED:
        raise NotClosed(f"task {task} is {state}; rate it once it is closed")
    if any(e["type"] == "TASK_RATED" for e in events):  # a second rating would count its verdicts twice in θ
        raise AlreadyRated(f"task {task} is already rated")
    operator = checked_operator(operator)
```

and replace

```python
    if note and note.strip():
        body["note"] = note.strip()
    closed = [e["id"] for e in events if e["type"] == "TASK_CLOSED"]
```

with

```python
    if note and note.strip():
        body["note"] = note.strip()
    if channel is not None:
        body["channel"] = channel
    closed = [e["id"] for e in events if e["type"] == "TASK_CLOSED"]
```

In `core/src/ooat_core/connector_admin.py`:

1. Replace `                automation_confirmed: bool, responsibility: dict | None = None, today: date | None = None) -> dict:` with

```python
                automation_confirmed: bool, responsibility: dict | None = None, today: date | None = None,
                channel: str | None = None) -> dict:
```

2. Replace

```python
        body["responsibility"] = {**responsibility, "confirmed_on": today.isoformat()}
    return ledger.append(
```

with

```python
        body["responsibility"] = {**responsibility, "confirmed_on": today.isoformat()}
    if channel is not None:
        body["channel"] = channel
    return ledger.append(
```

3. Replace `def approve_hooks(ledger: Ledger, connector: ModelConnector, operator: str, hooks: Iterable[tuple[str, str]]) -> dict:` with

```python
def approve_hooks(ledger: Ledger, connector: ModelConnector, operator: str, hooks: Iterable[tuple[str, str]],
                  channel: str | None = None) -> dict:
```

4. Replace

```python
    body = {**current, "operator": operator, "approved_hooks": approved}
    return ledger.append(
```

with

```python
    body = {key: value for key, value in current.items() if key != "channel"}  # the channel is this approval's
    body |= {"operator": operator, "approved_hooks": approved} | ({"channel": channel} if channel else {})
    return ledger.append(
```

5. Replace the whole `disable` function with

```python
def disable(ledger: Ledger, connector_id: str, operator: str, reason: str, channel: str | None = None) -> dict:
    operator, reason = checked_operator(operator), reason.strip()
    if not reason:
        raise ValueError("a reason is required")
    body = {"adapter": connector_id, "operator": operator, "reason": reason}
    if channel is not None:
        body["channel"] = channel
    return ledger.append(new_event("ADAPTER_DISABLED", task=None, actor={"kind": "hil", "id": operator}, body=body))
```

- [ ] **Step 5: Route the CLI through the shared paths**

In `core/src/ooat_core/task_cli.py`:

1. Replace the module docstring's last two sentences

```python
`--operator` name is self-declared; remote identity (REST, Telegram) is verified in 05. Only these commands, and the
runtime applying a declared default after a deadline, append `actor.kind = hil` events.
"""
```

with

```python
`--operator` name is self-declared, so it never answers an R3 request (ADR 0016). The operator's events are built by
runtime.py, rating.py and hil.py, which these commands call with the channel `cli`.
"""
```

2. Replace

```python
from .artifacts import ArtifactStore
from .blobs import BlobStore
from .catalog import routing_path
from .connector_admin import checked_operator
from .credentials_env import SecretResolver
from .gate import settings_from_config
from .gateway import Gateway, GatewayError
from .ledger import DATA_CLASSES, Ledger, new_event
```

with

```python
from . import hil
from .artifacts import ArtifactStore
from .blobs import BlobStore
from .catalog import routing_path
from .credentials_env import SecretResolver
from .gate import settings_from_config
from .gateway import Gateway, GatewayError
from .ledger import DATA_CLASSES, Ledger
```

3. In `_submit` replace `                          file_names=[Path(name).name for name in args.file])` with
   `                          file_names=[Path(name).name for name in args.file], channel="cli")`.
4. In `_rate` replace `                 verdicts=verdicts, note=args.note)` with `                 verdicts=verdicts, note=args.note, channel="cli")`.
5. Replace the whole `_hil_list` and `_hil_answer` functions (from `def _hil_list(` to the end of the file) with

```python
def _hil_list(args, ledger, runtime, stdin, stdout, ask) -> int:
    runtime.expire()
    requests = hil.open_requests(ledger)
    if not requests:
        stdout.write("No open questions.\n")
    for request in requests:
        stdout.write(f"Task {request['task']}\n{_question(request)}")
    return 0


def _hil_answer(args, ledger, runtime, stdin, stdout, ask) -> int:
    if args.choice is None and not (args.text or "").strip():
        raise ValueError("give --choice, --text or both")
    if args.choice == "narrow_scope" and not (args.text or "").strip():
        raise ValueError("narrow_scope needs the narrowed scope as --text")
    response = hil.answer(ledger, runtime, args.request, operator=args.operator, choice=args.choice, text=args.text,
                          channel="cli")
    stdout.write(f"Answered {args.request}.\n")
    return _report(response["task"], runtime.run(response["task"]), ledger, stdout)
```

In `core/src/ooat_core/operator_cli.py` replace
`        connector_admin.approve_hooks(ledger, connector, args.operator, [(path, sha) for path, sha, _ in files])` with

```python
        connector_admin.approve_hooks(ledger, connector, args.operator, [(path, sha) for path, sha, _ in files],
                                      channel="cli")
```

replace `        connector_admin.disable(ledger, args.connector, args.operator, args.reason)` with
`        connector_admin.disable(ledger, args.connector, args.operator, args.reason, channel="cli")`, and replace
`        connector_admin.acknowledge(ledger, connector, operator, classes, automation, responsibility, today)` with

```python
        connector_admin.acknowledge(ledger, connector, operator, classes, automation, responsibility, today,
                                    channel="cli")
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest core/tests/test_hil.py core/tests/test_runtime.py core/tests/test_ledger.py core/tests/test_rating.py core/tests/test_task_cli.py core/tests/test_operator_cli.py -q`
Expected: PASS

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add core/src/ooat_core/hil.py core/src/ooat_core/runtime.py core/src/ooat_core/ledger.py core/src/ooat_core/rating.py core/src/ooat_core/connector_admin.py core/src/ooat_core/task_cli.py core/src/ooat_core/operator_cli.py core/tests/test_hil.py core/tests/test_runtime.py core/tests/test_ledger.py core/tests/test_rating.py core/tests/test_task_cli.py core/tests/test_operator_cli.py
git commit -m "feat(core): shared human actions with channel, operator cancel, R3 refused on every channel (plan 05a)"
```

---

### Task 5: Operator API tokens and `ooat tokens`

**Files:**
- Create: `core/src/ooat_core/tokens.py`, `core/src/ooat_core/serve_cli.py`
- Modify: `core/src/ooat_core/operator_cli.py` (wire `ooat tokens`)
- Test: `core/tests/test_tokens.py`

**Interfaces:**
- Consumes: the token event schemas (Task 2); `connector_admin.checked_operator`.
- Produces: `tokens.SCOPES = ("submit", "read", "answer", "rate", "connectors")`, `tokens.CAPS`, `tokens.RESPONSIBLE_CAPS`,
  `tokens.EVENTS`, `tokens.DEFAULT_DAYS = 90`; `@dataclass Token(id, operator, name, scopes: frozenset[str],
  max_data_class, expires: datetime, sha256, revoked=False)`; `tokens.issue(ledger, *, operator, name, scopes,
  max_data_class="internal", days=90, responsibility=False, now) -> tuple[str, dict]` (the secret, the event);
  `tokens.tokens(events) -> dict[str, Token]`; `tokens.revoke(ledger, *, operator, token_id, reason) -> dict` (any operator, with a required reason);
  `tokens.authenticate(events, presented: str, now) -> Token | None`; `serve_cli.add_commands(commands)`,
  `serve_cli.run(args, config, path, stdin, stdout, clock, ask) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_tokens.py`:

```python
"""Operator API tokens and `ooat tokens` (design 05 §6, ADR 0016)."""

import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from ooat_core import tokens
from ooat_core.ledger import Ledger
from ooat_core.operator_cli import main

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def ledger():
    led = Ledger.open("sqlite:///:memory:")
    yield led
    led.close()


def issue(ledger, **extra):
    return tokens.issue(ledger, **{"operator": "operator", "name": "telegram", "scopes": ["submit", "read"],
                                   "now": NOW, **extra})


def test_a_token_is_shown_once_and_only_its_hash_is_recorded(ledger):
    secret, event = issue(ledger)
    assert secret.startswith("ooat_") and len(secret) >= 47  # 32 random bytes, URL-safe
    stored = json.dumps(ledger.events())
    assert secret not in stored and secret[5:] not in stored
    body = event["body"]
    assert event["task"] is None and event["actor"] == {"kind": "hil", "id": "operator"}
    assert body["max_data_class"] == "internal" and body["expires"] == "2027-01-08T09:00:00Z"
    assert tokens.authenticate(ledger.events(types=tokens.EVENTS), secret, NOW).operator == "operator"


def test_a_wrong_expired_or_revoked_token_does_not_authenticate(ledger):
    secret, event = issue(ledger, days=1)
    events = ledger.events(types=tokens.EVENTS)
    assert tokens.authenticate(events, secret[:-1] + ("A" if secret[-1] != "A" else "B"), NOW) is None
    assert tokens.authenticate(events, "Bearer " + secret, NOW) is None
    assert tokens.authenticate(events, secret, NOW + timedelta(days=1)) is None
    for reason in ("", "   "):  # an emergency revoke still says why
        with pytest.raises(ValueError, match="reason is required"):
            tokens.revoke(ledger, operator="second-operator", token_id=event["body"]["token"], reason=reason)
    assert tokens.authenticate(ledger.events(types=tokens.EVENTS), secret, NOW).operator == "operator"
    revoked = tokens.revoke(ledger, operator="second-operator", token_id=event["body"]["token"],
                            reason=" leaked in a chat log ")  # any operator may revoke any token
    assert revoked["actor"] == {"kind": "hil", "id": "second-operator"}
    assert revoked["body"] == {"token": event["body"]["token"], "operator": "second-operator",
                               "reason": "leaked in a chat log"}
    assert tokens.authenticate(ledger.events(types=tokens.EVENTS), secret, NOW) is None
    with pytest.raises(ValueError, match="already revoked"):
        tokens.revoke(ledger, operator="operator", token_id=event["body"]["token"], reason="again")


@pytest.mark.parametrize("extra, message", [
    ({"name": "Telegram Bot"}, "token name"),
    ({"scopes": ["admin"]}, "unknown"),
    ({"scopes": []}, "scopes are"),
    ({"max_data_class": "special_category"}, "never leaves"),
    ({"max_data_class": "personal"}, "responsibility"),
    ({"days": 400}, "1 to 365 days"),
    ({"operator": "default-on-silence"}, "reserved"),
])
def test_mistakes_are_refused_and_nothing_is_written(ledger, extra, message):
    with pytest.raises(ValueError, match=message):
        issue(ledger, **extra)
    assert ledger.events() == []


def test_a_cap_above_internal_records_the_responsibility_statement(ledger):
    _, event = issue(ledger, max_data_class="client_confidential", responsibility=True)
    assert event["body"]["responsibility"] == {"confirmed_on": "2026-10-10"}


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "ooat.toml"
    path.write_text('[ledger]\nurl = "sqlite:///ledger.sqlite"\n', encoding="utf-8")
    return path


def ooat(config, *argv, answers=""):
    stdout = io.StringIO()
    code = main(["--config", str(config), *argv], stdin=io.StringIO(answers), stdout=stdout, clock=lambda: NOW)
    return code, stdout.getvalue()


def test_create_list_and_revoke_from_the_command_line(config):
    code, out = ooat(config, "tokens", "create", "--operator", "operator", "--name", "telegram",
                     "--scopes", "submit,read,answer,rate")
    assert code == 0 and "shown only now" in out
    secret = next(line.strip() for line in out.splitlines() if line.strip().startswith("ooat_"))
    token_id = out.split("Token ", 1)[1].split(" ", 1)[0]
    code, listed = ooat(config, "tokens", "list")
    assert code == 0 and token_id in listed and "[active]" in listed and secret not in listed
    code, out = ooat(config, "tokens", "revoke", token_id, "--operator", "operator", "--reason", "the bot moved")
    assert code == 0 and "[revoked]" in ooat(config, "tokens", "list")[1]


def test_a_personal_cap_asks_for_the_responsibility_and_no_means_no_token(config):
    code, out = ooat(config, "tokens", "create", "--operator", "operator", "--name", "crm", "--scopes", "read",
                     "--max-data-class", "personal", answers="no\n")
    assert code == 1 and "No token was created" in out and "ooat_" not in out
    assert ooat(config, "tokens", "list")[1] == "No tokens.\n"
    code, out = ooat(config, "tokens", "create", "--operator", "operator", "--name", "crm", "--scopes", "read",
                     "--max-data-class", "personal", answers="yes\n")
    assert code == 0 and "data up to personal" in out
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest core/tests/test_tokens.py -q`
Expected: FAIL with `ImportError: cannot import name 'tokens' from 'ooat_core'`

- [ ] **Step 3: Implement the tokens and the commands**

Create `core/src/ooat_core/tokens.py`:

```python
"""Operator API tokens for bots and scripts (design 05 §6, ADR 0016).

A token acts as the operator who issued it, within its scopes and its data-class cap. It is 256 random bits, shown
once; the ledger keeps only its SHA-256 (OPERATOR_TOKEN_ISSUED), compared in constant time, and revoking appends
OPERATOR_TOKEN_REVOKED, so who could act for whom is in the audit log. A cap above `internal` is the operator's
responsibility statement (ADR 0012): content of that class may then leave the machine through the token's client.
"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .connector_admin import checked_operator
from .ids import new_id
from .ledger import Ledger, new_event

SCOPES = ("submit", "read", "answer", "rate", "connectors")
CAPS = ("public", "internal", "client_confidential", "personal")  # special_category never leaves through a token
RESPONSIBLE_CAPS = ("client_confidential", "personal")
DEFAULT_DAYS, MAX_DAYS = 90, 365
PREFIX = "ooat_"  # makes a leaked token recognisable to secret scanners
EVENTS = ["OPERATOR_TOKEN_ISSUED", "OPERATOR_TOKEN_REVOKED"]
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class Token:
    id: str
    operator: str
    name: str
    scopes: frozenset[str]
    max_data_class: str
    expires: datetime
    sha256: str
    revoked: bool = False


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def issue(ledger: Ledger, *, operator: str, name: str, scopes: list[str], max_data_class: str = "internal",
          days: int = DEFAULT_DAYS, responsibility: bool = False, now: datetime) -> tuple[str, dict]:
    """Append OPERATOR_TOKEN_ISSUED and return (the token, the event). The token is never stored or logged."""
    operator = checked_operator(operator)
    if not _NAME.match(name):
        raise ValueError("a token name is 1 to 32 lowercase letters, digits, '-' or '_', e.g. telegram")
    scopes = list(dict.fromkeys(scopes))
    unknown = sorted(set(scopes) - set(SCOPES))
    if not scopes or unknown:
        raise ValueError(f"scopes are some of {', '.join(SCOPES)}" + (f"; unknown: {unknown}" if unknown else ""))
    if max_data_class not in CAPS:
        raise ValueError(f"a token's data class is one of {', '.join(CAPS)}; special_category never leaves")
    if max_data_class in RESPONSIBLE_CAPS and not responsibility:
        raise ValueError(f"a token for {max_data_class} data needs your responsibility statement")
    if type(days) is not int or not 1 <= days <= MAX_DAYS:
        raise ValueError(f"a token expires after 1 to {MAX_DAYS} days")
    secret = PREFIX + secrets.token_urlsafe(32)  # 256 bits
    body = {"token": new_id("tok"), "operator": operator, "name": name, "scopes": scopes,
            "max_data_class": max_data_class, "sha256": _digest(secret),
            "expires": (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if max_data_class in RESPONSIBLE_CAPS:
        body["responsibility"] = {"confirmed_on": now.date().isoformat()}
    event = ledger.append(new_event("OPERATOR_TOKEN_ISSUED", task=None, actor={"kind": "hil", "id": operator},
                                    body=body))
    return secret, event


def tokens(events: list[dict]) -> dict[str, Token]:
    """Every issued token by id, with whether it was revoked; the events are OPERATOR_TOKEN_* in ledger order."""
    found = {}
    for event in events:
        body = event["body"]
        if event["type"] == "OPERATOR_TOKEN_ISSUED":
            found[body["token"]] = Token(body["token"], body["operator"], body["name"], frozenset(body["scopes"]),
                                         body["max_data_class"], _utc(body["expires"]), body["sha256"])
        elif event["type"] == "OPERATOR_TOKEN_REVOKED" and body["token"] in found:
            found[body["token"]] = replace(found[body["token"]], revoked=True)
    return found


def revoke(ledger: Ledger, *, operator: str, token_id: str, reason: str) -> dict:
    """OPERATOR_TOKEN_REVOKED. Any operator may revoke any token, so a leaked token can be stopped at once by whoever
    notices; operator names are self-declared, so an issuer-only rule would protect little. The event records who
    revoked it (`operator`, also the actor) and the required reason."""
    operator, reason = checked_operator(operator), reason.strip()
    if not reason:
        raise ValueError("a reason is required")
    known = tokens(ledger.events(types=EVENTS)).get(token_id)
    if known is None:
        raise ValueError(f"no token {token_id} (see `ooat tokens list`)")
    if known.revoked:
        raise ValueError(f"{token_id} is already revoked")
    return ledger.append(new_event("OPERATOR_TOKEN_REVOKED", task=None, actor={"kind": "hil", "id": operator},
                                   body={"token": token_id, "operator": operator, "reason": reason}))


def authenticate(events: list[dict], presented: str, now: datetime) -> Token | None:
    """The active token whose hash matches, or None. Every stored hash is compared in constant time."""
    if not presented.startswith(PREFIX) or len(presented) > 128:
        return None
    digest, match = _digest(presented), None
    for token in tokens(events).values():
        if hmac.compare_digest(token.sha256, digest):
            match = token
    if match is None or match.revoked or match.expires <= now:
        return None
    return match
```

Create `core/src/ooat_core/serve_cli.py` (Task 10 adds `ooat serve` and `ooat login` to it):

```python
"""`ooat tokens create | list | revoke` (design 05 §6, ADR 0016); `ooat serve` and `ooat login` join in Task 10.

A token is printed once, at creation; nothing else prints or logs it.
"""

import re
import sqlite3

from . import tokens
from .ledger import Ledger

REFUSED = 1
RESPONSIBILITY = """
A token for client or personal data (ADR 0012, ADR 0016). Whatever the token's client reads leaves this machine
and may be stored by its platform, such as a chat service. By answering yes you state that you have a legal basis
and a processing agreement for that. OOAT records your name and today's date with the token.
"""


def add_commands(commands) -> None:
    group = commands.add_parser("tokens", help="API tokens for bots and scripts")
    actions = group.add_subparsers(dest="action", required=True)
    create = actions.add_parser("create", help="create a token; it is shown once")
    create.add_argument("--operator", required=True, help="the operator the token acts as")
    create.add_argument("--name", required=True, help="what uses it, e.g. telegram")
    create.add_argument("--scopes", required=True, help=f"comma-separated: {','.join(tokens.SCOPES)}")
    create.add_argument("--max-data-class", dest="max_data_class", default="internal", choices=tokens.CAPS,
                        help="the most sensitive data the token may read or write (default internal)")
    create.add_argument("--expires", default=f"{tokens.DEFAULT_DAYS}d", help="days until it expires, e.g. 90d")
    create.add_argument("--responsibility", choices=["yes", "no"],
                        help="take responsibility for client or personal data (asked when such a class is chosen)")
    actions.add_parser("list", help="tokens with their operator, scopes, data class and state")
    revoke = actions.add_parser("revoke", help="revoke a token")
    revoke.add_argument("token")
    revoke.add_argument("--operator", required=True)
    revoke.add_argument("--reason", required=True)


def run(args, config, path, stdin, stdout, clock, ask) -> int:
    if config is None:
        stdout.write(f"No {path} found: create one with a [ledger] url, or pass --config. Nothing was changed.\n")
        return REFUSED
    try:
        ledger = Ledger.open(config.ledger_url)
    except (ValueError, NotImplementedError, sqlite3.Error, OSError) as error:
        stdout.write(f"Cannot open ledger {config.ledger_url}: {error}\n")
        return REFUSED
    try:
        handler = {"create": _create, "list": _list, "revoke": _revoke}[args.action]
        return handler(args, ledger, stdin, stdout, clock, ask)
    except ValueError as error:  # includes SpecValidationError
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    finally:
        ledger.close()


def _create(args, ledger, stdin, stdout, clock, ask) -> int:
    match = re.fullmatch(r"(\d{1,3})d", args.expires)
    if match is None:
        raise ValueError("--expires is a number of days, e.g. 90d")
    responsible = False
    if args.max_data_class in tokens.RESPONSIBLE_CAPS:
        stdout.write(RESPONSIBILITY)
        answer = args.responsibility or (ask("Do you take this responsibility? (yes/no): ", stdin, stdout) or "")
        if answer.strip().lower() != "yes":
            stdout.write("No token was created.\n")
            return REFUSED
        responsible = True
    secret, event = tokens.issue(ledger, operator=args.operator, name=args.name,
                                 scopes=[s.strip() for s in args.scopes.split(",") if s.strip()],
                                 max_data_class=args.max_data_class, days=int(match.group(1)),
                                 responsibility=responsible, now=clock())
    body = event["body"]
    stdout.write(f"Token {body['token']} for {body['name']}: acts as {body['operator']}, scopes "
                 f"{','.join(body['scopes'])}, data up to {body['max_data_class']}, expires {body['expires']}.\n"
                 f"\n  {secret}\n\n"
                 "It is shown only now: put it in the client's own secret store. OOAT keeps only its SHA-256.\n")
    return 0


def _list(args, ledger, stdin, stdout, clock, ask) -> int:
    known = tokens.tokens(ledger.events(types=tokens.EVENTS))
    if not known:
        stdout.write("No tokens.\n")
    now = clock()
    for token in known.values():
        state = "revoked" if token.revoked else "expired" if token.expires <= now else "active"
        stdout.write(f"{token.id}  {token.name}  [{state}]  operator {token.operator}  scopes "
                     f"{','.join(sorted(token.scopes))}  data up to {token.max_data_class}  expires "
                     f"{token.expires:%Y-%m-%d}\n")
    return 0


def _revoke(args, ledger, stdin, stdout, clock, ask) -> int:
    tokens.revoke(ledger, operator=args.operator, token_id=args.token, reason=args.reason)
    stdout.write(f"{args.token} revoked; it stops working on its next request.\n")
    return 0
```

In `core/src/ooat_core/operator_cli.py`:

1. Replace the module docstring with

```python
"""`ooat` command line: `ooat connectors list | show | enable | disable`, the task and HIL commands of
task_cli.py (`ooat task ...`, `ooat hil ...`) and serve_cli.py (`ooat tokens ...`)."""
```

2. Replace `from . import connector_admin, task_cli` with `from . import connector_admin, serve_cli, task_cli`.
3. Replace

```python
    task_cli.add_commands(commands)
    return parser
```

with

```python
    task_cli.add_commands(commands)
    serve_cli.add_commands(commands)
    return parser
```

4. In `main` replace

```python
            return task_cli.run(args, config, path, stdin, stdout, registry or Registry.discover(), routing, clock,
                                _ask_or_end)
        return _run(
```

with

```python
            return task_cli.run(args, config, path, stdin, stdout, registry or Registry.discover(), routing, clock,
                                _ask_or_end)
        if args.command == "tokens":
            config, path, refusal = _config(args)
            if refusal is not None:
                stdout.write(refusal)
                return REFUSED
            return serve_cli.run(args, config, path, stdin, stdout, clock, _ask_or_end)
        return _run(
```

(the `return _run(` line continues unchanged).

- [ ] **Step 4: Run the tests**

Run: `python -m pytest core/tests/test_tokens.py core/tests/test_hil.py core/tests/test_operator_cli.py -q`
Expected: PASS (`test_only_the_listed_modules_build_a_human_actor` now also finds `tokens.py`, which is on its list)

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/tokens.py core/src/ooat_core/serve_cli.py core/src/ooat_core/operator_cli.py core/tests/test_tokens.py
git commit -m "feat(core): operator API tokens as ledger events and ooat tokens create|list|revoke (plan 05a)"
```

---

### Task 6: The runner, its lock, and the CLI while `ooat serve` runs

**Files:**
- Create: `core/src/ooat_core/runner_lock.py`, `core/src/ooat_core/runner.py`
- Modify: `core/src/ooat_core/task_cli.py` (take the runner lock to run; only record while another process holds it)
- Test: `core/tests/test_runner.py`, `core/tests/test_task_cli.py`

**Interfaces:**
- Consumes: `Runtime.runnable()`, `Runtime.run()`, `Runtime.cancel()` (Task 4).
- Produces: `runner_lock.RunnerLock(path)` with `.acquire() -> bool` (non-blocking) and `.release()`;
  `runner_lock.for_ledger(ledger_url) -> RunnerLock | None` (`<ledger file>.runner.lock`; None in memory);
  `runner.resume_after(events) -> datetime | None`; `runner.Runner(make_runtime: Callable[[], Runtime], *, clock,
  tick_seconds=60.0)` with `.enqueue(task)`, `.status() -> {"state": "idle"|"running", "task", "queued"}`,
  `.start()`, `.stop(timeout=30.0)`, `.tick()`, `.run_next() -> str | None`, `.drain() -> list[str]`, `.runtime()`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_runner.py`:

```python
"""The runner of `ooat serve` and the runner lock (design 05 §7, §14)."""

import logging
import time
from datetime import datetime, timedelta, timezone

from runtime_fakes import ScriptedModel, acknowledge, decisions, routing_document
from test_runtime import NOW, Setup

from ooat_core.artifacts import ArtifactStore
from ooat_core.blobs import BlobStore
from ooat_core.config import parse_config
from ooat_core.connectors import ConnectorError
from ooat_core.connectors.registry import Registry
from ooat_core.credentials_env import SecretResolver
from ooat_core.gateway import Gateway
from ooat_core.ledger import Ledger
from ooat_core.routing import RoutingPolicy
from ooat_core.runner import Runner, resume_after
from ooat_core.runner_lock import RunnerLock, for_ledger
from ooat_core.runtime import Runtime
from ooat_core.state import task_state

CRITERIA = ["Shrnutí má nejvýše 300 slov."]


def runner_for(setup, tick_seconds=60.0):
    return Runner(lambda: setup.runtime, clock=lambda: setup.now, tick_seconds=tick_seconds)


def state(setup, task):
    return task_state(setup.ledger.events(task=task))


def test_the_first_tick_rebuilds_the_queue_from_the_ledger_in_submission_order(tmp_path):
    setup = Setup(tmp_path)
    first, second = setup.submit(), setup.submit()  # e.g. `ooat task submit` while the server was down
    waiting = setup.submit(acceptance=())
    setup.runtime.run(waiting)  # waits for a clarification: not runnable
    runner = runner_for(setup)
    runner.tick()
    assert runner.status() == {"state": "idle", "task": None, "queued": 2}
    assert runner.drain() == [first, second]
    assert state(setup, first) == state(setup, second) == "CLOSED_DONE" and state(setup, waiting) == "CLARIFYING"


def test_a_task_is_queued_once_however_often_it_is_enqueued(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit()
    runner = runner_for(setup)
    for _ in range(3):
        runner.enqueue(task)
    runner.tick()
    assert runner.drain() == [task]


def test_a_paused_task_is_tried_again_after_a_growing_pause(tmp_path):
    model = ScriptedModel(outages={("worker", 1): ConnectorError("UNAVAILABLE", "HTTP 529"),
                                   ("worker", 2): ConnectorError("UNAVAILABLE", "HTTP 529")})
    setup = Setup(tmp_path, model=model)
    start = setup.now = datetime.now(timezone.utc)  # the ledger stamps events with the real time
    task = setup.submit()
    runner = runner_for(setup)
    runner.enqueue(task)
    runner.drain()
    assert state(setup, task) == "RUNNING"  # paused by the provider
    runner.tick()
    assert runner.drain() == []  # not before 60 s
    setup.now = start + timedelta(seconds=65)
    runner.tick()
    # Failed again. The ledger stamped that failure with the real time, a moment after `start`: next try in 120 s.
    assert runner.drain() == [task] and state(setup, task) == "RUNNING"
    setup.now = start + timedelta(seconds=100)
    runner.tick()
    assert runner.drain() == []
    setup.now = start + timedelta(seconds=180)
    runner.tick()
    assert runner.drain() == [task] and state(setup, task) == "CLOSED_DONE"


def test_the_pause_doubles_per_failure_up_to_thirty_minutes():
    def failed(n):
        return {"type": "RESULT", "ts": "2026-10-02T12:00:00Z", "actor": {"id": "agt"},
                "body": {"outcome": "FAILED", "error": {"code": "TIMEOUT", "message": "x"}}}
    start = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    assert resume_after([]) is None
    assert resume_after([failed(1)]) == start + timedelta(seconds=60)
    assert resume_after([failed(n) for n in range(3)]) == start + timedelta(seconds=240)
    assert resume_after([failed(n) for n in range(12)]) == start + timedelta(minutes=30)
    invalid = {**failed(0), "body": {"outcome": "FAILED", "error": {"code": "INVALID_OUTPUT", "message": "x"}}}
    assert resume_after([invalid]) is None  # a malformed reply is an attempt, not an outage


def test_one_failing_task_does_not_stop_the_runner_and_its_content_stays_out_of_the_log(tmp_path, caplog,
                                                                                       monkeypatch):
    setup = Setup(tmp_path)
    broken, fine = setup.submit(), setup.submit()
    real_run = Runtime.run

    def refuse(self, task):
        if task == broken:
            raise ValueError("Shrň smlouvu pro jednatele: secret client text")
        return real_run(self, task)
    monkeypatch.setattr(Runtime, "run", refuse)
    runner = runner_for(setup)
    runner.tick()
    with caplog.at_level(logging.INFO, logger="ooat.serve"):
        assert runner.drain() == [broken, fine]
    assert state(setup, fine) == "CLOSED_DONE"
    assert "ValueError" in caplog.text and "secret client text" not in caplog.text


def file_runtime(path, model, jev):
    """A Runtime on a file ledger, made in the thread that calls it (SQLite connections stay in their thread)."""
    def make():
        ledger = Ledger.open(f"sqlite:///{path.as_posix()}")
        config = parse_config({})
        gateway = Gateway(ledger, Registry([model, jev]), RoutingPolicy(routing_document()), config,
                          SecretResolver(config, {}), clock=lambda: NOW)
        return Runtime(ledger, gateway, ArtifactStore(ledger, BlobStore(path.parent / "blobs")), clock=lambda: NOW)
    return make


def test_the_runner_thread_runs_what_the_api_queues_and_stops(tmp_path):
    path = tmp_path / "ledger.sqlite"
    model, jev = ScriptedModel(), decisions()
    intake = file_runtime(path, model, jev)()  # the API's own connection, in this thread
    for connector in (model, jev):
        acknowledge(intake.ledger, connector)
    runner = Runner(file_runtime(path, model, jev), clock=lambda: NOW, tick_seconds=3600)
    runner.start()
    task = intake.submit(operator="operator", goal="Shrň smlouvu.", acceptance=CRITERIA, channel="web")
    runner.enqueue(task)
    deadline = time.monotonic() + 30
    while task_state(intake.ledger.events(task=task)) != "CLOSED_DONE" and time.monotonic() < deadline:
        time.sleep(0.05)
    runner.stop()
    assert task_state(intake.ledger.events(task=task)) == "CLOSED_DONE"
    assert not runner._thread.is_alive()
    intake.ledger.close()


def test_the_runner_lock_is_held_by_one_holder_at_a_time(tmp_path):
    lock = for_ledger(f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}")
    assert lock.path.name == "ledger.sqlite.runner.lock"
    other = RunnerLock(lock.path)
    assert lock.acquire() and not other.acquire()
    lock.release()
    assert other.acquire()
    other.release()
    assert for_ledger("sqlite:///:memory:") is None
```

In `core/tests/test_task_cli.py` replace `def test_a_hand_over_after_the_decision_tier_failed_is_labelled_too():` with

```python
def test_while_the_server_holds_the_runner_lock_the_cli_only_records(env):
    from ooat_core.runner_lock import for_ledger

    lock = for_ledger(env["ledger"])
    assert lock.acquire()  # as `ooat serve` does
    try:
        code, out = ooat(env, "task", "submit", "--operator", "operator", "--goal", "Shrň smlouvu.")
        task = task_id(out)
        assert code == 0 and "ooat serve` runs it" in out and events(env, task, "TOPOLOGY_DECIDED") == []
        code, out = ooat(env, "task", "run", task)
        assert code == 1 and "Nothing was run" in out
    finally:
        lock.release()
    code, out = ooat(env, "task", "run", task)  # without the server the CLI runs it again
    assert code == 0 and "CLARIFYING" in out
    request = out.split("Question ", 1)[1].split(" ", 1)[0]
    assert lock.acquire()
    try:
        code, out = ooat(env, "hil", "answer", request, "--operator", "operator", "--text", "Nejvýše 300 slov.")
        assert code == 0 and "ooat serve` runs it" in out and events(env, task, "CONTRACT_ISSUED") == []
    finally:
        lock.release()


def test_a_hand_over_after_the_decision_tier_failed_is_labelled_too():
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest core/tests/test_runner.py core/tests/test_task_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ooat_core.runner'` and, in `test_task_cli.py`, `No module named 'ooat_core.runner_lock'`

- [ ] **Step 3: Implement the lock and the runner**

Create `core/src/ooat_core/runner_lock.py`:

```python
"""An OS file lock beside the ledger: the process holding it is the one that runs tasks (design 05 §7).

`ooat serve` holds it while it runs; `ooat task run`, and `submit` or `hil answer` when they would run the task,
take it for their run. A process that cannot get it leaves running to the holder, so no task is ever run by two
processes. The OS releases the lock when the process ends, also after a crash.
"""

import os
from pathlib import Path


class RunnerLock:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._file = None

    def acquire(self) -> bool:
        """Take the lock without waiting; False when another process (or another RunnerLock) holds it."""
        if self._file is not None:
            raise RuntimeError("this lock is already held")
        file = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            file.close()
            return False
        self._file = file
        return True

    def release(self) -> None:
        if self._file is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._file.close()
            self._file = None


def for_ledger(ledger_url: str) -> RunnerLock | None:
    """The lock of a file ledger (`<ledger file>.runner.lock`); None for an in-memory ledger."""
    location = ledger_url.removeprefix("sqlite:///")
    if location == ledger_url or location == ":memory:":
        return None
    return RunnerLock(f"{location}.runner.lock")
```

Create `core/src/ooat_core/runner.py`:

```python
"""The task runner of `ooat serve` (design 05 §7, ADR 0014).

One thread, one FIFO queue: spec §3 sets Solo to one task at a time. The API queues a task when it is submitted,
answered or cancelled; every tick (60 s) the runner applies defaults on silence and queues what can move without
the operator, and its first tick at start rebuilds the queue from the ledger, so tasks from `ooat task submit` and
tasks queued before a restart are picked up. A task paused by a provider failure is tried again after 60 s, then
after twice as long per further failure, at most every 30 minutes, so an outage does not spend the budget on
retries. The runner's Runtime, with its own ledger connection, is made and used in the runner's thread only.
"""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta

from .runtime import Runtime

log = logging.getLogger("ooat.serve")
FIRST_RETRY_S, MAX_RETRY_S = 60, 1800


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def resume_after(events: list[dict]) -> datetime | None:
    """When a task paused by provider failures may be tried again; None when its last step did not fail."""
    failures, last = 0, None
    for event in events:
        body = event["body"]
        failed = (event["type"] == "RESULT" and body["outcome"] == "FAILED"
                  and body["error"]["code"] != "INVALID_OUTPUT") or (
            event["type"] == "DECISION" and event["actor"]["id"] == "ooat-runtime"
            and body["decision"].startswith("acceptance check paused"))
        if failed:
            failures, last = failures + 1, event["ts"]
        elif event["type"] in ("RESULT", "GATE_PASSED", "GATE_FAILED", "HIL_RESPONSE"):
            failures = 0
    if not failures:
        return None
    return _utc(last) + timedelta(seconds=min(FIRST_RETRY_S * 2 ** (failures - 1), MAX_RETRY_S))


class Runner:
    def __init__(self, make_runtime: Callable[[], Runtime], *, clock: Callable[[], datetime],
                 tick_seconds: float = 60.0):
        self._make_runtime, self.clock, self.tick_seconds = make_runtime, clock, tick_seconds
        self._runtime: Runtime | None = None
        self._queue: deque[str] = deque()
        self._current: str | None = None
        self._changed = threading.Condition()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    # Called from any thread ---------------------------------------------------------------------------------------

    def enqueue(self, task: str) -> None:
        with self._changed:
            if task != self._current and task not in self._queue:
                self._queue.append(task)
                self._changed.notify()

    def status(self) -> dict:
        with self._changed:
            return {"state": "running" if self._current else "idle", "task": self._current,
                    "queued": len(self._queue)}

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="ooat-runner", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        """Ask the thread to stop after the task in hand; a provider call in flight is not interrupted."""
        self._stopping.set()
        with self._changed:
            self._changed.notify()
        if self._thread is not None:
            self._thread.join(timeout)

    # Called in the runner's thread (or a test's) ----------------------------------------------------------------

    def runtime(self) -> Runtime:
        if self._runtime is None:
            self._runtime = self._make_runtime()
        return self._runtime

    def tick(self) -> None:
        """Apply defaults on silence and queue every task that can move, in the order it was submitted."""
        runtime, now = self.runtime(), self.clock()
        for task in runtime.runnable():  # applies expired defaults first
            due = resume_after(runtime.ledger.events(task=task))
            if due is None or due <= now:
                self.enqueue(task)

    def run_next(self) -> str | None:
        """Run the oldest queued task as far as it goes; returns it, or None when the queue is empty."""
        with self._changed:
            if not self._queue:
                return None
            task = self._current = self._queue.popleft()
        try:
            outcome = self.runtime().run(task)
            log.info("%s: %s", task, outcome.state)
        except Exception as error:  # one task must not stop the runner; the message may hold task content
            log.warning("%s: not run (%s %s)", task, type(error).__name__, getattr(error, "code", ""))
        finally:
            with self._changed:
                self._current = None
        return task

    def drain(self) -> list[str]:
        """Run queued tasks until none is left (tests and shutdown-free use)."""
        done = []
        while (task := self.run_next()) is not None:
            done.append(task)
        return done

    def _loop(self) -> None:
        next_tick = 0.0
        while not self._stopping.is_set():
            if time.monotonic() >= next_tick:
                try:
                    self.tick()
                except Exception as error:  # e.g. the ledger was busy: try again at the next tick
                    log.warning("tick failed (%s)", type(error).__name__)
                next_tick = time.monotonic() + self.tick_seconds
            if self.run_next() is None:
                with self._changed:
                    if not self._queue and not self._stopping.is_set():
                        self._changed.wait(max(next_tick - time.monotonic(), 0.0))
```

- [ ] **Step 4: Let the CLI step aside while the server runs**

In `core/src/ooat_core/task_cli.py`:

1. Replace `from . import hil` with `from . import hil, runner_lock`.
2. Replace `REFUSED = 1` with

```python
REFUSED = 1
RUNS = {("task", "submit"), ("task", "run"), ("hil", "answer")}  # commands that run a task in the foreground
SERVED = "`ooat serve` runs it within a minute; follow it in the web app.\n"
```

3. In `run` replace

```python
        handler = {("task", "submit"): _submit, ("task", "run"): _run_task, ("task", "show"): _show,
                   ("task", "rate"): _rate, ("hil", "list"): _hil_list, ("hil", "answer"): _hil_answer}
        return handler[(args.command, args.action)](args, ledger, runtime, stdin, stdout, ask)
```

with

```python
        handler = {("task", "submit"): _submit, ("task", "run"): _run_task, ("task", "show"): _show,
                   ("task", "rate"): _rate, ("hil", "list"): _hil_list, ("hil", "answer"): _hil_answer}
        runs = (args.command, args.action) in RUNS and not getattr(args, "no_run", False)
        lock = runner_lock.for_ledger(config.ledger_url) if runs else None
        # Another process holding the lock (`ooat serve`) runs the tasks; this one only records.
        args.served = lock is not None and not lock.acquire()
        try:
            return handler[(args.command, args.action)](args, ledger, runtime, stdin, stdout, ask)
        finally:
            if lock is not None and not args.served:
                lock.release()
```

4. In `_submit` replace

```python
    stdout.write(f"Submitted {task}.\n")
    if args.no_run:
        return 0
    return _report(task, runtime.run(task), ledger, stdout)
```

with

```python
    stdout.write(f"Submitted {task}.\n")
    if args.no_run:
        return 0
    if args.served:
        stdout.write(SERVED)
        return 0
    return _report(task, runtime.run(task), ledger, stdout)
```

5. In `_run_task` replace

```python
def _run_task(args, ledger, runtime, stdin, stdout, ask) -> int:
    if not args.all_tasks:
```

with

```python
def _run_task(args, ledger, runtime, stdin, stdout, ask) -> int:
    if args.served:
        stdout.write("Another process runs the tasks of this ledger (`ooat serve`): follow them in the web app. "
                     "Nothing was run.\n")
        return REFUSED
    if not args.all_tasks:
```

6. In `_hil_answer` replace

```python
    stdout.write(f"Answered {args.request}.\n")
    return _report(response["task"], runtime.run(response["task"]), ledger, stdout)
```

with

```python
    stdout.write(f"Answered {args.request}.\n")
    if args.served:
        stdout.write(SERVED)
        return 0
    return _report(response["task"], runtime.run(response["task"]), ledger, stdout)
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest core/tests/test_runner.py core/tests/test_task_cli.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/src/ooat_core/runner_lock.py core/src/ooat_core/runner.py core/src/ooat_core/task_cli.py core/tests/test_runner.py core/tests/test_task_cli.py
git commit -m "feat(core): runner thread with a queue rebuilt from the ledger, retry backoff, runner lock (plan 05a)"
```

---

### Task 7: Usage figures and capped views (`stats.py`, `views.py`)

**Files:**
- Create: `core/src/ooat_core/stats.py`, `core/src/ooat_core/views.py`
- Test: `core/tests/test_stats.py`, `core/tests/test_views.py`

**Interfaces:**
- Consumes: `gate.gated_data_class`, `pii.ORDER` / `higher_class`, `rating.task_decisions`, `state.task_state`,
  `hil.open_requests` (Task 4, in tests).
- Produces:
  - `stats.PERIODS` (days per period: `"1d"`, `"7d"`, `"30d"`, `"90d"`, `"all"` → None), `stats.GROUPS = ("role", "connector", "tier", "project")`,
    `stats.OTHER = "(other)"`; `stats.role_of(event) -> str`; `stats.usage(events, *, now, period="7d",
    project=None, group="role", above_cap=frozenset()) -> dict` with keys `period, project, group, spend
    {metered_usd, shadow_usd}, groups [{key, calls, tokens_in, tokens_cached, tokens_out, metered_usd, shadow_usd}],
    tasks {closed, by_state, rated, accepted, cost_usd, cost_per_accepted_usd, estimate_vs_actual}, hil {questions,
    answered, defaults_applied, median_wait_minutes}`.
  - `views.STUB_TEXT`; `views.within(data_class, cap: str | None) -> bool`; `views.stub(task) -> dict`;
    `views.by_task(events) -> dict[str, list[dict]]`; `views.task_class(events, artifact_class, settings=GateSettings())
    -> str`; `views.task_summary(task, events, data_class, cap) -> dict`; `views.task_detail(task, events,
    data_class, cap, artifact_record, open_requests) -> dict`; `views.timeline(events, data_class, cap, after=None)
    -> list[dict]` (raises `KeyError` for an unknown cursor); `views.hil_view(request, data_class, cap) -> dict`;
    `views.rating_queue(tasks, classes, cap) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_stats.py`:

```python
"""Usage figures from the ledger (design 05 §8)."""

from datetime import datetime, timedelta, timezone

import pytest
from test_runtime import Setup

from ooat_core.ids import new_id
from ooat_core.rating import rate
from ooat_core.stats import role_of, usage

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def at(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def call(task, minutes_ago, usd, basis="exact", adapter="prv.fake.api", tier="workhorse", actor=None, body=None):
    return {"id": new_id("evt"), "ts": at(minutes_ago), "task": task, "type": "RESULT", "refs": [],
            "actor": actor or {"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
            "body": body or {"outcome": "DONE"},
            "cost": {"adapter": adapter, "tier": tier, "tokens_in": 1000, "tokens_out": 200, "usd": usd,
                     "basis": basis}}


def submitted(task, project, minutes_ago=60):
    return {"id": new_id("evt"), "ts": at(minutes_ago), "task": task, "type": "TASK_SUBMITTED", "refs": [],
            "actor": {"kind": "hil", "id": "operator"}, "body": {"goal": "x", "project": project}}


def test_cost_is_split_into_metered_and_subscription_shadow_by_connector():
    task = new_id("tsk")
    events = [submitted(task, "docs"), call(task, 30, 0.40, adapter="prv.anthropic.api"),
              call(task, 20, 2.70, basis="shadow", adapter="prv.anthropic.subscription_cli"),
              call(task, 10, 0.05, basis="estimated", adapter="prv.anthropic.api")]
    figures = usage(events, now=NOW, group="connector")
    assert figures["spend"] == {"metered_usd": pytest.approx(0.45), "shadow_usd": pytest.approx(2.70)}
    assert [(r["key"], r["calls"], r["tokens_in"]) for r in figures["groups"]] == [
        ("prv.anthropic.subscription_cli", 1, 1000), ("prv.anthropic.api", 2, 2000)]


def test_the_period_and_the_project_filter_the_events():
    one, two = new_id("tsk"), new_id("tsk")
    events = [submitted(one, "docs", 60 * 24 * 10), call(one, 60 * 24 * 9, 1.0),
              submitted(two, "sales"), call(two, 5, 0.5)]
    assert usage(events, now=NOW, period="7d")["spend"]["metered_usd"] == 0.5
    assert usage(events, now=NOW, period="30d")["spend"]["metered_usd"] == 1.5
    assert usage(events, now=NOW, period="all", project="docs")["spend"]["metered_usd"] == 1.0
    with pytest.raises(ValueError, match="period"):
        usage(events, now=NOW, period="week")


def test_a_project_is_named_only_when_one_of_its_tasks_is_within_the_readers_cap():
    secret, shared, other = new_id("tsk"), new_id("tsk"), new_id("tsk")
    events = [submitted(secret, "client-x"), call(secret, 5, 1.0), submitted(shared, "docs"), call(shared, 5, 0.5),
              submitted(other, "docs"), call(other, 5, 0.25)]
    figures = usage(events, now=NOW, group="project", above_cap=frozenset({secret, other}))
    assert {r["key"]: r["metered_usd"] for r in figures["groups"]} == {"(other)": 1.0, "docs": 0.75}


def test_hil_waiting_time_is_the_median_of_human_answers_and_defaults_are_counted():
    task = new_id("tsk")
    requests = [{"id": new_id("evt"), "ts": at(m), "task": task, "type": "HIL_REQUEST", "refs": [],
                 "actor": {"kind": "system", "id": "ooat-gate"}, "body": {}} for m in (100, 90, 80)]
    answers = [{"id": new_id("evt"), "ts": at(m), "task": task, "type": "HIL_RESPONSE", "refs": [],
                "actor": {"kind": "hil", "id": who}, "body": {"request": r["id"], **extra}}
               for r, m, who, extra in ((requests[0], 90, "operator", {}), (requests[1], 60, "operator", {}),
                                        (requests[2], 0, "default-on-silence", {"default_applied": True}))]
    figures = usage(requests + answers, now=NOW)["hil"]
    assert figures == {"questions": 3, "answered": 2, "defaults_applied": 1, "median_wait_minutes": 20.0}


def test_a_real_task_shows_the_worker_the_gate_and_the_checks_and_its_cost_per_accepted_task(tmp_path):
    setup = Setup(tmp_path)
    setup.now = datetime.now(timezone.utc)  # the ledger stamps the real time
    task = setup.submit(project="docs")
    setup.runtime.run(task)
    rate(setup.ledger, task, operator="operator", accepted=True, value_class="B")
    events = setup.ledger.events()
    figures = usage(events, now=setup.now + timedelta(minutes=1), group="role")
    assert {r["key"] for r in figures["groups"]} == {"role.general.worker", "gate", "acceptance"}
    closed = setup.last(task, "TASK_CLOSED")["body"]["cost"]
    assert figures["tasks"]["closed"] == figures["tasks"]["accepted"] == 1
    assert figures["tasks"]["cost_per_accepted_usd"] == pytest.approx(sum(closed.values()))
    assert figures["tasks"]["estimate_vs_actual"] is not None
    assert role_of({"actor": {"kind": "system", "id": "ooat-runtime"},
                    "body": {"gate": "gate.critic.check_criterion"}}) == "critic"
```

Create `core/tests/test_views.py`:

```python
"""The API's views with a reader's data-class cap (design 05 §6)."""

import json

from test_runtime import Setup

from ooat_core.hil import open_requests
from ooat_core.views import STUB_TEXT, by_task, hil_view, rating_queue, task_class, task_detail, task_summary, \
    timeline, within

PERSONAL_GOAL = "Odpověz panu Novákovi na jan.novak@example.cz ohledně smlouvy."


def classes(setup):
    tasks = by_task(setup.ledger.events())
    return tasks, {task: task_class(events, lambda ref: setup.ledger.artifact(ref)["data_class"])
                   for task, events in tasks.items()}


def test_the_cap_orders_the_classes():
    assert within("internal", "internal") and within("public", "internal") and within("personal", None)
    assert not within("client_confidential", "internal") and not within("special_category", "personal")


def test_a_personal_task_is_a_stub_above_an_internal_cap_but_its_state_and_costs_stay(tmp_path):
    setup = Setup(tmp_path, classes=("public", "internal", "personal"))
    task = setup.runtime.submit(operator="operator", goal=PERSONAL_GOAL, project="client-x")  # no criteria: asks
    setup.runtime.run(task)
    tasks, found = classes(setup)
    assert found[task] == "personal"  # raised by the pre-scan
    summary = task_summary(task, tasks[task], found[task], "internal")
    assert summary["goal"] == {"redacted": STUB_TEXT, "link": f"/tasks/{task}"} and summary["project"] is None
    assert summary["state"] == "CLARIFYING" and "cost_usd" in summary and summary["data_class"] == "personal"
    detail = task_detail(task, tasks[task], found[task], "internal", setup.ledger.artifact, open_requests(setup.ledger))
    question = detail["questions"][0]
    assert question["question"]["redacted"] == STUB_TEXT and question["deadline"]
    assert all(option["label"]["redacted"] == STUB_TEXT for option in question["options"])
    events = timeline(tasks[task], found[task], "internal")
    assert all(e["body"]["redacted"] == STUB_TEXT for e in events) and events[0]["type"] == "TASK_SUBMITTED"
    assert "novak" not in json.dumps([summary, detail, events]).lower()
    assert task_summary(task, tasks[task], found[task], None)["goal"] == PERSONAL_GOAL  # the web app sees it


def test_an_attachment_above_the_cap_raises_the_task_and_is_not_readable(tmp_path):
    setup = Setup(tmp_path, classes=("public", "internal", "personal"))
    task = setup.submit(files=[b"Kontakt: jan.novak@example.cz"])
    setup.runtime.run(task)
    tasks, found = classes(setup)
    assert found[task] == "personal"
    detail = task_detail(task, tasks[task], found[task], "internal", setup.ledger.artifact, [])
    attachment = next(a for a in detail["artifacts"] if a["type"] == "attachment")
    assert attachment["untrusted"] and not attachment["readable"]
    assert detail["result"]["summary"]["redacted"] == STUB_TEXT and detail["result"]["cost"]


def test_an_internal_task_is_shown_whole_and_the_timeline_follows_a_cursor(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit(project="docs")
    setup.runtime.run(task)
    tasks, found = classes(setup)
    summary = task_summary(task, tasks[task], found[task], "internal")
    assert summary["goal"] == "Shrň smlouvu pro jednatele." and summary["project"] == "docs"
    events = timeline(tasks[task], found[task], "internal")
    later = timeline(tasks[task], found[task], "internal", after=events[2]["id"])
    assert [e["id"] for e in later] == [e["id"] for e in events[3:]]


def test_the_rating_queue_holds_closed_unrated_tasks_with_their_decisions(tmp_path):
    setup = Setup(tmp_path)  # no connector for personal data: that task closes at the Gate
    plain = setup.submit()
    personal = setup.runtime.submit(operator="operator", goal=PERSONAL_GOAL, acceptance=["Odpověď je zdvořilá."])
    for task in (plain, personal):
        assert setup.runtime.run(task).state.startswith("CLOSED")
    tasks, found = classes(setup)
    queue = {entry["task"]: entry for entry in rating_queue(tasks, found, "internal")}
    assert set(queue) == {plain, personal}
    assert [d["question"] for d in queue[plain]["decisions"]][:1] == ["a1.1"]
    assert queue[personal]["goal"]["redacted"] == STUB_TEXT
    request = hil_view({"id": "evt_x", "task": plain, "ts": "t", "body": {
        "question": "Q?", "deadline": "d", "blocking": True, "recommended": "a", "default_on_silence": "b",
        "options": [{"id": "a", "label": "A", "cost_usd": 0.0}, {"id": "b", "label": "B", "cost_usd": 0.0,
                                                                "acts": False}]}}, "internal", "internal")
    assert request["question"] == "Q?" and request["options"][1]["acts"] is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest core/tests/test_stats.py core/tests/test_views.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ooat_core.stats'` / `'ooat_core.views'`

- [ ] **Step 3: Implement**

Create `core/src/ooat_core/stats.py`:

```python
"""Usage figures from the ledger (design 05 §8): what ran, what it used, what it cost, how long questions waited.

Pure projections over events, like state.py: nothing is stored. Calls, tokens and cost are grouped by role,
connector, tier or project; cost is split into metered (`exact`, `estimated`) and the subscription shadow value
(`shadow`). Until T3 and the catalog the roles are few: the worker's role, the Gate, the acceptance checks and the
critic. HIL time is waiting time from request to answer; the ledger does not know how long a person worked on it.
"""

from datetime import datetime, timedelta
from statistics import median

from .acceptance import GATE_CRITIC
from .gate import ACTOR as GATE_ACTOR

PERIODS = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "all": None}
GROUPS = ("role", "connector", "tier", "project")
OTHER = "(other)"  # projects the reader may not see by name, and tasks without a project
COST_PARTS = ("contracts_usd", "gate_usd", "orchestrator_usd", "critic_usd")  # TASK_CLOSED.cost in USD


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def role_of(event: dict) -> str:
    """Who spent: the worker's role id, the Gate, the critic, or the runtime's acceptance decisions."""
    actor = event["actor"]
    if actor["kind"] == "agent":
        return actor["role"].split("@", 1)[0]
    if actor == GATE_ACTOR:
        return "gate"
    return "critic" if event["body"].get("gate") == GATE_CRITIC else "acceptance"


def usage(events: list[dict], *, now: datetime, period: str = "7d", project: str | None = None,
          group: str = "role", above_cap: frozenset[str] = frozenset()) -> dict:
    """The Usage figures for events in the period. `above_cap` holds the tasks above the reader's data class:
    their costs count, but their project is named only when another task of it is within the cap."""
    if period not in PERIODS:
        raise ValueError(f"period is one of {', '.join(PERIODS)}")
    if group not in GROUPS:
        raise ValueError(f"group is one of {', '.join(GROUPS)}")
    days = PERIODS[period]
    since = now - timedelta(days=days) if days else None
    projects = {e["task"]: e["body"].get("project") for e in events if e["type"] == "TASK_SUBMITTED"}
    named = {p for task, p in projects.items() if p and task not in above_cap}
    selected = [e for e in events if (since is None or _utc(e["ts"]) >= since)
                and (project is None or projects.get(e["task"]) == project)]

    def key(event: dict) -> str:
        if group == "role":
            return role_of(event)
        if group in ("connector", "tier"):
            return event["cost"].get("adapter" if group == "connector" else "tier") or OTHER
        name = projects.get(event["task"])
        return name if name in named else OTHER

    groups: dict[str, dict] = {}
    for event in selected:
        cost = event.get("cost")
        if not cost:
            continue
        row = groups.setdefault(key(event), {"calls": 0, "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0,
                                             "metered_usd": 0.0, "shadow_usd": 0.0})
        row["calls"] += 1
        for tokens in ("tokens_in", "tokens_cached", "tokens_out"):
            row[tokens] += cost.get(tokens, 0)
        row["shadow_usd" if cost["basis"] == "shadow" else "metered_usd"] += cost.get("usd", 0.0)
    rows = sorted(({"key": k, **v} for k, v in groups.items()),
                  key=lambda r: (-(r["metered_usd"] + r["shadow_usd"]), r["key"]))
    return {"period": period, "project": project, "group": group,
            "spend": {"metered_usd": sum(r["metered_usd"] for r in rows),
                      "shadow_usd": sum(r["shadow_usd"] for r in rows)},
            "groups": rows, "tasks": _tasks(selected, events), "hil": _hil(selected, events)}


def _tasks(selected: list[dict], events: list[dict]) -> dict:
    """Tasks closed in the period: by outcome, accepted, cost per accepted task, the Gate's estimate vs actual."""
    closed = {e["task"]: e for e in selected if e["type"] == "TASK_CLOSED"}
    rated = {e["task"]: e["body"]["accepted"] for e in events if e["type"] == "TASK_RATED" and e["task"] in closed}
    by_state: dict[str, int] = {}
    for event in closed.values():
        by_state[event["body"]["state"]] = by_state.get(event["body"]["state"], 0) + 1
    actual = {task: sum(e["body"]["cost"][part] for part in COST_PARTS) for task, e in closed.items()}
    estimates = {}
    for event in events:
        if event["type"] == "TOPOLOGY_DECIDED" and event["task"] in closed:
            estimate = [c["model_usd"] for c in event["body"]["candidates"] if "model_usd" in c]
            if estimate:
                estimates[event["task"]] = estimate[0]  # the last decision stands
    accepted = sum(1 for ok in rated.values() if ok)
    estimated = sum(estimates.values())
    return {"closed": len(closed), "by_state": by_state, "rated": len(rated), "accepted": accepted,
            "cost_usd": sum(actual.values()),
            "cost_per_accepted_usd": sum(actual.values()) / accepted if accepted else None,
            "estimate_vs_actual": (sum(actual[t] for t in estimates) - estimated) / estimated if estimated else None}


def _hil(selected: list[dict], events: list[dict]) -> dict:
    """Questions asked in the period, answers, defaults applied on silence, median wait for a human answer."""
    asked = {e["id"]: e for e in selected if e["type"] == "HIL_REQUEST"}
    responses = [e for e in events if e["type"] == "HIL_RESPONSE" and e["body"]["request"] in asked]
    defaults = [r for r in responses if r["body"].get("default_applied")]
    waits = [(_utc(r["ts"]) - _utc(asked[r["body"]["request"]]["ts"])).total_seconds() / 60
             for r in responses if not r["body"].get("default_applied")]
    return {"questions": len(asked), "answered": len(responses) - len(defaults), "defaults_applied": len(defaults),
            "median_wait_minutes": median(waits) if waits else None}
```

Create `core/src/ooat_core/views.py`:

```python
"""What a reader of the API sees (design 05 §5, §6): tasks, timelines, questions and the rating queue, with the
reader's data-class cap applied. Pure projections over events, like state.py.

A token caps every read, not only what it submits (ADR 0016): content of a task or artifact above the cap comes back
as a stub, while ids, states, costs and deadlines stay visible. A task's class is the class it runs under: the
declared one, raised by the pre-scan and the Gate's A10, and by its attachments. An artifact has its own class.
A web session on loopback has no cap (`cap=None`).
"""

from collections.abc import Callable

from .gate import GateSettings, gated_data_class
from .pii import ORDER, higher_class
from .rating import task_decisions
from .runtime import CLOSED
from .state import task_state

STUB_TEXT = "above this token's data class; open in the web app"


def within(data_class: str, cap: str | None) -> bool:
    return cap is None or ORDER.index(data_class) <= ORDER.index(cap)


def stub(task: str) -> dict:
    return {"redacted": STUB_TEXT, "link": f"/tasks/{task}"}


def by_task(events: list[dict]) -> dict[str, list[dict]]:
    """Events of every task, in submission order."""
    tasks: dict[str, list[dict]] = {}
    for event in events:
        if event["task"] is not None:
            tasks.setdefault(event["task"], []).append(event)
    return tasks


def task_class(events: list[dict], artifact_class: Callable[[str], str],
               settings: GateSettings = GateSettings()) -> str:
    """The class the task runs under: gated (declared, pre-scan, A10), raised by its attachments."""
    submitted = next(e for e in events if e["type"] == "TASK_SUBMITTED")
    data_class = gated_data_class(events, settings)
    for ref in submitted["refs"]:
        data_class = higher_class(data_class, artifact_class(ref))
    return data_class


def _latest(events: list[dict], kind: str) -> dict | None:
    return next((e for e in reversed(events) if e["type"] == kind), None)


def task_summary(task: str, events: list[dict], data_class: str, cap: str | None) -> dict:
    submitted = next(e for e in events if e["type"] == "TASK_SUBMITTED")
    decided, closed = _latest(events, "TOPOLOGY_DECIDED"), _latest(events, "TASK_CLOSED")
    visible = within(data_class, cap)
    estimates = [c["model_usd"] for c in decided["body"]["candidates"] if "model_usd" in c] if decided else []
    return {
        "task": task, "state": task_state(events), "data_class": data_class,
        "project": submitted["body"].get("project") if visible else None,
        "goal": submitted["body"]["goal"] if visible else stub(task),
        "topology": decided["body"]["topology"] if decided else None,
        "cost_usd": sum(e.get("cost", {}).get("usd", 0.0) for e in events),
        "budget_usd": submitted["body"].get("budget_usd"),
        "estimate_usd": estimates[0] if estimates else None,
        "submitted": submitted["ts"], "updated": events[-1]["ts"],
        "closed": closed["body"]["state"] if closed else None,
    }


def task_detail(task: str, events: list[dict], data_class: str, cap: str | None,
                artifact_record: Callable[[str], dict], open_requests: list[dict]) -> dict:
    visible = within(data_class, cap)
    submitted, closed = next(e for e in events if e["type"] == "TASK_SUBMITTED"), _latest(events, "TASK_CLOSED")
    refs = list(dict.fromkeys(ref for e in events for ref in e["refs"] if ref.startswith("art_")))
    artifacts = []
    for ref in refs:
        record = artifact_record(ref)
        artifacts.append({"ref": ref, "type": record["type"], "data_class": record["data_class"],
                          "untrusted": record["untrusted"], "readable": within(record["data_class"], cap)})
    detail = task_summary(task, events, data_class, cap)
    detail |= {
        "expected_output": submitted["body"].get("expected_output") if visible else None,
        "acceptance": submitted["body"].get("acceptance", []) if visible else stub(task),
        "result": None, "artifacts": artifacts,
        "questions": [hil_view(r, data_class, cap) for r in open_requests if r["task"] == task],
    }
    if closed is not None:
        body = closed["body"]
        detail["result"] = {"state": body["state"], "cost": body["cost"], "artifacts": body.get("artifacts", []),
                            "summary": body["summary"] if visible else stub(task),
                            "missing": body.get("missing") if visible else None}
    return detail


def timeline(events: list[dict], data_class: str, cap: str | None, after: str | None = None) -> list[dict]:
    """The task's events after the event `after` (a cursor), bodies stubbed above the cap."""
    if after is not None:
        ids = [e["id"] for e in events]
        if after not in ids:
            raise KeyError(after)
        events = events[ids.index(after) + 1:]
    visible = within(data_class, cap)
    return [{"id": e["id"], "ts": e["ts"], "type": e["type"], "actor": {"kind": e["actor"]["kind"],
                                                                        "id": e["actor"]["id"]},
             "refs": e["refs"], "cost": e.get("cost"), "body": e["body"] if visible else stub(e["task"])}
            for e in events]


def hil_view(request: dict, data_class: str, cap: str | None) -> dict:
    body, visible, task = request["body"], within(data_class, cap), request["task"]
    return {"request": request["id"], "task": task, "asked": request["ts"], "deadline": body["deadline"],
            "risk_class": body.get("risk_class"), "blocking": body["blocking"],
            "recommended": body["recommended"], "default_on_silence": body["default_on_silence"],
            "question": body["question"] if visible else stub(task),
            "options": [{"id": o["id"], "cost_usd": o["cost_usd"], "acts": o.get("acts", True),
                         "label": o["label"] if visible else stub(task)} for o in body["options"]]}


def rating_queue(tasks: dict[str, list[dict]], classes: dict[str, str], cap: str | None) -> list[dict]:
    """Closed tasks without a rating, with the decisions OOAT made alone."""
    queue = []
    for task, events in tasks.items():
        if task_state(events) not in CLOSED or any(e["type"] == "TASK_RATED" for e in events):
            continue
        entry = task_summary(task, events, classes[task], cap)
        entry["decisions"] = [{"event": d.event, "question": d.question, "kind": d.kind, "answer": d.answer,
                               "confidence": d.confidence, "disputed": d.disputed} for d in task_decisions(events)]
        queue.append(entry)
    return queue
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest core/tests/test_stats.py core/tests/test_views.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/stats.py core/src/ooat_core/views.py core/tests/test_stats.py core/tests/test_views.py
git commit -m "feat(core): usage figures and data-class capped views from the ledger (plan 05a)"
```

---

### Task 8: The HTTP shell: sessions, tokens, Host / Origin / CSRF, limits, errors, log

**Files:**
- Create: `core/src/ooat_core/sessions.py`, `core/src/ooat_core/api.py`, `core/src/ooat_core/web/login.html`, `core/src/ooat_core/web/login.js`
- Modify: `core/pyproject.toml` (`fastapi`), `requirements-dev.txt` (`httpx2`)
- Test: `core/tests/api_fakes.py` (new helper), `core/tests/test_api_security.py`

**Interfaces:**
- Consumes: `tokens.authenticate`, `tokens.SCOPES`, `tokens.EVENTS` (Task 5); `Runner` (Task 6); `views.within`
  (Task 7); the error classes of Task 4 (`hil.*`, `rating.NotClosed` / `AlreadyRated`, `runtime.UnknownTask` /
  `TaskClosed`) and `LedgerBusyError` (Task 3).
- Produces:
  - `sessions.LOGIN_TTL` (5 min), `sessions.SESSION_TTL` (12 h); `sessions.login_folder(ledger_url) -> Path | None`;
    `sessions.issue_login_code(folder, operator, now) -> str`; `sessions.redeem_login_code(folder, code, now) ->
    str | None`; `sessions.Sessions` with `.open(operator, now) -> (cookie, Session)`, `.get(cookie, now)`,
    `.close(cookie)`; `Session(operator, csrf, expires)`.
  - `api.ServeSettings(ledger_url, blobs_dir, operator=None, host="127.0.0.1", port=8765, hosts=(), tls=False)` with
    `.loopback`, `.session_cap` (`None` on loopback, else `"internal"`), `.allowed_hosts`;
    `api.Principal(operator, channel, scopes, max_data_class)`; `api.ApiError(status, code, message, details=None)`;
    `api.Server` with `.settings, .config, .registry, .routing, .clock, .sessions, .runner, .runtime(),
    .new_runtime()`; `api.server_of(request)`; dependencies `api.principal`, `api.scope(name)`;
    `api.require_within(who, data_class)`; `api.create_app(settings, *, config, registry, routing, clock,
    start_runner=True) -> FastAPI`; routers `api.login_routes()` and `api.session_routes()` (`POST /logout`,
    `GET /me`, `GET /status`); `api.SESSION_COOKIE = "ooat_session"`.

- [ ] **Step 1: Add the dependencies**

In `core/pyproject.toml` replace
`dependencies = ["jsonschema>=4.23", "referencing>=0.30", "rfc3339-validator>=0.1.4"]` with
`dependencies = ["jsonschema>=4.23", "referencing>=0.30", "rfc3339-validator>=0.1.4", "fastapi>=0.143"]`
(FastAPI with Pydantic v2 is the API stack CLAUDE.md names; it brings Starlette and Pydantic). Append to
`requirements-dev.txt` the line `httpx2==2.13.1` (pinned, the version tested; test-only: FastAPI's `TestClient` imports it; current Starlette asks for it (its import error says `pip install httpx2`) and deprecates plain `httpx`; published by Pydantic, github.com/pydantic/httpx2; verified by the orchestrator 2026-10-10). Then run `python -m pip install -r requirements-dev.txt -e core`.

- [ ] **Step 2: Write the failing tests**

Create `core/tests/api_fakes.py`:

```python
"""`ooat serve` in tests: the app on a file ledger with fake connectors, a bot token and a web session (no network;
the test client talks to the app in-process as http://127.0.0.1:8765)."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from runtime_fakes import ScriptedModel, acknowledge, decisions, routing_document

from ooat_core import tokens
from ooat_core.api import ServeSettings, create_app
from ooat_core.config import parse_config
from ooat_core.connectors.registry import Registry
from ooat_core.ledger import Ledger
from ooat_core.routing import RoutingPolicy
from ooat_core.sessions import issue_login_code, login_folder

ORIGIN = "http://127.0.0.1:8765"
CRITERIA = ["Shrnutí má nejvýše 300 slov."]
PERSONAL_GOAL = "Odpověz panu Novákovi na jan.novak@example.cz ohledně smlouvy."


def now() -> datetime:
    return datetime.now(timezone.utc)  # the ledger stamps events with the real time


class Served:
    def __init__(self, tmp_path, model=None, jev=None, classes=("public", "internal"), **settings):
        self.url = f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}"
        self.model, self.jev = model or ScriptedModel(), jev or decisions()
        with self.ledger() as ledger:
            acknowledge(ledger, self.model, classes)
            acknowledge(ledger, self.jev)
        self.settings = ServeSettings(ledger_url=self.url, blobs_dir=tmp_path / "blobs", operator="operator",
                                      **settings)
        self.app = create_app(self.settings, config=parse_config({}), registry=Registry([self.model, self.jev]),
                              routing=RoutingPolicy(routing_document()), clock=now, start_runner=False)
        self.server = self.app.state.server
        scheme = "https" if self.settings.tls else "http"
        host = self.settings.hosts[0] if self.settings.hosts else "127.0.0.1"
        self.origin = f"{scheme}://{host}:{self.settings.port}"
        self.client = TestClient(self.app, base_url=self.origin)

    def ledger(self):
        return _Opened(self.url)

    def run(self) -> list[str]:
        """What the runner thread does, here in the test's thread: rebuild the queue, run it."""
        self.server.runner.tick()
        return self.server.runner.drain()

    def token(self, scopes=("submit", "read", "answer", "rate"), cap="internal") -> dict:
        with self.ledger() as ledger:
            secret, _ = tokens.issue(ledger, operator="operator", name="telegram", scopes=list(scopes),
                                     max_data_class=cap, responsibility=cap in tokens.RESPONSIBLE_CAPS, now=now())
        return {"Authorization": f"Bearer {secret}"}

    def login(self, operator="operator") -> dict:
        """A web session: the client keeps the cookie; unsafe requests need these headers."""
        code = issue_login_code(login_folder(self.url), operator, now())
        response = self.client.post("/api/v1/login", json={"code": code}, headers={"Origin": self.origin})
        assert response.status_code == 200, response.text
        return {"Origin": self.origin, "X-CSRF-Token": response.json()["csrf"]}

    def submit(self, headers, **body) -> dict:
        response = self.client.post("/api/v1/tasks", headers=headers,
                                    json={"project": "docs", "goal": "Shrň smlouvu pro jednatele.", **body})
        assert response.status_code == 202, response.text
        return response.json()


class _Opened:
    def __init__(self, url):
        self.url = url

    def __enter__(self) -> Ledger:
        self.ledger = Ledger.open(self.url)
        return self.ledger

    def __exit__(self, *exc):
        self.ledger.close()
```

Create `core/tests/test_api_security.py`:

```python
"""`ooat serve`'s shell: sign-in, sessions, tokens, Host / Origin / CSRF, limits and the log (design 05 §6, §14)."""

import logging
import os
import stat
from datetime import timedelta

import pytest
from api_fakes import ORIGIN, Served, now

from ooat_core import tokens
from ooat_core.api import ServeSettings
from ooat_core.sessions import issue_login_code, login_folder


def test_a_sign_in_code_works_once_and_its_session_acts_as_its_operator(tmp_path):
    served = Served(tmp_path)
    code = issue_login_code(login_folder(served.url), "operator", now())
    assert not any(code in path.name for path in login_folder(served.url).iterdir())  # only its hash is on disk
    first = served.client.post("/api/v1/login", json={"code": code}, headers={"Origin": ORIGIN})
    assert first.status_code == 200 and first.json()["operator"] == "operator"
    cookie = first.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=43200" in cookie
    assert "secure" not in cookie  # plain http on loopback
    again = served.client.post("/api/v1/login", json={"code": code}, headers={"Origin": ORIGIN})
    assert again.status_code == 401 and again.json()["error"]["code"] == "UNAUTHENTICATED"
    me = served.client.get("/api/v1/me").json()
    assert me["operator"] == "operator" and me["channel"] == "web" and me["max_data_class"] is None
    assert me["csrf"] == first.json()["csrf"]


def test_an_expired_sign_in_code_is_refused(tmp_path):
    served = Served(tmp_path)
    code = issue_login_code(login_folder(served.url), "operator", now() - timedelta(minutes=6))
    assert served.client.post("/api/v1/login", json={"code": code}, headers={"Origin": ORIGIN}).status_code == 401


def test_logging_out_ends_the_session(tmp_path):
    served = Served(tmp_path)
    headers = served.login()
    assert served.client.post("/api/v1/logout", headers=headers).status_code == 200
    assert served.client.get("/api/v1/me").status_code == 401


def test_a_page_of_another_site_cannot_sign_in_or_act_for_the_operator(tmp_path):
    served = Served(tmp_path)
    headers = served.login()
    code = issue_login_code(login_folder(served.url), "second-operator", now())
    assert served.client.post("/api/v1/login", json={"code": code},
                              headers={"Origin": "http://evil.example"}).status_code == 403
    for refused in ({"Origin": "http://evil.example"}, {}, {"Origin": "http://127.0.0.1:9999"}, {"Origin": "null"},
                    {"Origin": "https://127.0.0.1:8765"}):
        response = served.client.post("/api/v1/logout", headers={**refused, "X-CSRF-Token": headers["X-CSRF-Token"]})
        assert response.status_code == 403 and response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED", refused
    wrong = served.client.post("/api/v1/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": "x"})
    assert wrong.status_code == 403 and wrong.json()["error"]["code"] == "CSRF"
    assert served.client.get("/api/v1/me").status_code == 200  # still signed in: nothing was done


def test_a_dns_rebinding_host_is_refused_before_anything_else(tmp_path):
    served = Served(tmp_path)
    token = served.token()
    for host in ("attacker.example", "attacker.example:8765", "127.0.0.1.attacker.example"):
        response = served.client.get("/api/v1/me", headers={**token, "Host": host})
        assert response.status_code == 400 and response.json()["error"]["code"] == "HOST_NOT_ALLOWED", host
    assert served.client.get("/api/v1/me", headers={**token, "Host": "localhost:8765"}).status_code == 200


def test_a_bearer_token_needs_no_origin_but_needs_its_scope(tmp_path):
    served = Served(tmp_path)
    submitter = served.token(scopes=("submit",))
    response = served.client.get("/api/v1/status", headers=submitter)
    assert response.status_code == 403 and response.json()["error"]["code"] == "SCOPE"
    assert served.client.get("/api/v1/status", headers=served.token(scopes=("read",))).json()["runner"] == {
        "state": "idle", "task": None, "queued": 0}
    for bad in ("Bearer ooat_not-a-token", "Basic dXNlcjpwYXNz", "ooat_x"):
        assert served.client.get("/api/v1/me", headers={"Authorization": bad}).status_code == 401, bad
    me = served.client.get("/api/v1/me", headers=submitter).json()
    assert me["channel"].startswith("token:tok_") and me["scopes"] == ["submit"] and "csrf" not in me


def test_a_revoked_token_stops_working_at_once(tmp_path):
    served = Served(tmp_path)
    headers = served.token()
    assert served.client.get("/api/v1/me", headers=headers).status_code == 200
    with served.ledger() as ledger:
        (token,) = tokens.tokens(ledger.events(types=tokens.EVENTS))
        tokens.revoke(ledger, operator="operator", token_id=token, reason="leaked")
    assert served.client.get("/api/v1/me", headers=headers).status_code == 401


def test_every_response_carries_the_security_headers_and_the_api_is_not_cached(tmp_path):
    served = Served(tmp_path)
    for path in ("/login", "/api/v1/me"):
        response = served.client.get(path)
        assert response.headers["content-security-policy"].startswith("default-src 'self'")
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"
    assert served.client.get("/api/v1/me").headers["cache-control"] == "no-store"
    page = served.client.get("/login").text
    assert '<script type="module" src="/login.js">' in page and "<script>" not in page  # no inline script
    assert "fetch(" in served.client.get("/login.js").text


def test_a_request_above_twenty_megabytes_is_refused_unread(tmp_path):
    served = Served(tmp_path)
    response = served.client.post("/api/v1/logout", headers=served.token(), content=b"x" * (20 * 1024 * 1024 + 1))
    assert response.status_code == 413 and response.json()["error"]["code"] == "TOO_LARGE"


def test_a_content_length_that_is_not_a_number_is_invalid(tmp_path):
    served = Served(tmp_path)
    for length in ("abc", "-1", "1e3"):
        response = served.client.post("/api/v1/login", content=b'{"code": "x"}',
                                      headers={"Origin": ORIGIN, "Content-Length": length})
        assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID", length


@pytest.mark.skipif(os.name == "nt", reason="Windows ignores the mode; the folder inherits the profile's ACL")
def test_the_sign_in_folder_is_private_to_its_owner(tmp_path):
    folder = tmp_path / "ooat-login"
    issue_login_code(folder, "operator", now())
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_the_log_records_method_path_and_status_only(tmp_path, caplog):
    served = Served(tmp_path)
    headers = served.token()
    with caplog.at_level(logging.INFO, logger="ooat.serve"):
        served.client.get("/api/v1/me?secret=Kocka123", headers=headers)
        served.login()
    assert "GET /api/v1/me 200" in caplog.text and "POST /api/v1/login 200" in caplog.text
    assert headers["Authorization"].split()[1] not in caplog.text and "Kocka123" not in caplog.text
    assert "ooat_session" not in caplog.text


def test_served_beyond_loopback_a_web_session_is_capped_like_a_token(tmp_path):
    served = Served(tmp_path, host="192.168.1.10", hosts=("ooat.lan",), tls=True)
    code = issue_login_code(login_folder(served.url), "operator", now())
    signed_in = served.client.post("/api/v1/login", json={"code": code}, headers={"Origin": served.origin})
    assert "secure" in signed_in.headers["set-cookie"].lower()
    assert served.client.get("/api/v1/me").json()["max_data_class"] == "internal"


@pytest.mark.parametrize("host, loopback", [("127.0.0.1", True), ("::1", True), ("localhost", True),
                                            ("0.0.0.0", False), ("192.168.1.10", False)])
def test_what_counts_as_loopback(tmp_path, host, loopback):
    assert ServeSettings(ledger_url="sqlite:///x", blobs_dir=tmp_path, host=host).loopback is loopback
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest core/tests/test_api_security.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ooat_core.api'`

- [ ] **Step 4: Implement sessions, the sign-in page and the shell**

Create `core/src/ooat_core/sessions.py`:

```python
"""Web sessions of `ooat serve` (design 05 §6).

A login code is a one-time secret printed in the terminal as a link; it sits in the URL fragment, so it never
reaches a server log, and the page posts it. `ooat serve` and `ooat login` write it as a file named by the code's
SHA-256 into the login folder beside the ledger: whoever can write there holds the terminal, the same trust as the
CLI's `--operator`. A code is valid 5 minutes and used once. The server turns it into a session: an HttpOnly,
SameSite=Strict cookie valid 12 hours, plus a CSRF token for unsafe methods. Sessions live in the server's memory,
so a restart signs everyone out.
"""

import hashlib
import json
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .connector_admin import checked_operator

LOGIN_TTL = timedelta(minutes=5)
SESSION_TTL = timedelta(hours=12)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def login_folder(ledger_url: str) -> Path | None:
    """`ooat-login` beside a file ledger; None for an in-memory ledger (nothing can log in to it)."""
    location = ledger_url.removeprefix("sqlite:///")
    if location == ledger_url or location == ":memory:":
        return None
    return Path(location).parent / "ooat-login"


def issue_login_code(folder: Path, operator: str, now: datetime) -> str:
    """A fresh one-time code for the operator; only its hash is written, with its expiry."""
    operator = checked_operator(operator)
    # Only its owner may read or add codes. On Windows the mode is ignored: the folder lies beside the ledger in the
    # operator's profile and inherits that folder's ACL, which OOAT does not change.
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    for old in folder.glob("*.json"):  # codes nobody used
        try:
            if _utc(json.loads(old.read_text(encoding="utf-8"))["expires"]) <= now:
                old.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError):
            continue
    code = secrets.token_urlsafe(32)
    (folder / f"{_digest(code)}.json").write_text(json.dumps({
        "operator": operator, "expires": (now + LOGIN_TTL).strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8")
    return code


def redeem_login_code(folder: Path, code: str, now: datetime) -> str | None:
    """The operator of a valid code, which is then used up; None for an unknown, used or expired code."""
    if not code or len(code) > 128:
        return None
    path = folder / f"{_digest(code)}.json"
    claimed = path.with_suffix(".used")
    try:
        path.replace(claimed)  # atomic: of two redeemers only one gets the file
    except OSError:
        return None
    try:
        data = json.loads(claimed.read_text(encoding="utf-8"))
    finally:
        claimed.unlink(missing_ok=True)
    return data["operator"] if _utc(data["expires"]) > now else None


@dataclass(frozen=True)
class Session:
    operator: str
    csrf: str
    expires: datetime


class Sessions:
    """Open web sessions, by the SHA-256 of their cookie value."""

    def __init__(self):
        self._open: dict[str, Session] = {}
        self._lock = threading.Lock()

    def open(self, operator: str, now: datetime) -> tuple[str, Session]:
        cookie, session = secrets.token_urlsafe(32), Session(operator, secrets.token_urlsafe(32), now + SESSION_TTL)
        with self._lock:
            self._open = {k: s for k, s in self._open.items() if s.expires > now}
            self._open[_digest(cookie)] = session
        return cookie, session

    def get(self, cookie: str, now: datetime) -> Session | None:
        with self._lock:
            session = self._open.get(_digest(cookie))
        return session if session is not None and session.expires > now else None

    def close(self, cookie: str) -> None:
        with self._lock:
            self._open.pop(_digest(cookie), None)
```

Create `core/src/ooat_core/web/login.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OOAT sign-in</title>
  <script type="module" src="/login.js"></script>
</head>
<body>
  <main>
    <h1>OOAT</h1>
    <p id="status">Signing in…</p>
  </main>
</body>
</html>
```

Create `core/src/ooat_core/web/login.js`:

```javascript
// Posts the one-time code from the link `ooat serve` or `ooat login` printed (design 05 §6). The code is in the URL
// fragment, which the browser never sends to a server, and is removed from the address bar before anything else.
const status = /** @type {HTMLElement} */ (document.getElementById("status"));
const code = new URLSearchParams(location.hash.slice(1)).get("code");
history.replaceState(null, "", location.pathname);

if (!code) {
  status.textContent = "Open the link that `ooat login --operator <name>` printed in your terminal.";
} else {
  const response = await fetch("/api/v1/login", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({code}),
  });
  const body = await response.json();
  status.textContent = response.ok ? `Signed in as ${body.operator}.` : body.error.message;
}
```

Create `core/src/ooat_core/api.py`:

```python
"""The HTTP shell of `ooat serve` (design 05 §5, §6, §7; ADR 0016): settings, who is asking, and the guards.

One process: this API, the sign-in page and the runner. Every endpoint is authenticated except the sign-in page and
`POST /api/v1/login`. A web session (cookie + CSRF token) acts as the operator who signed in; a bearer token acts as
the operator who issued it, within its scopes and its data-class cap. Every request's Host must be one this server
answers to (DNS rebinding), an unsafe request from a browser must carry this server's Origin, and the log records
method, path and status only. The resources are in endpoints.py.
"""

import hmac
import ipaddress
import logging
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import hil, tokens, views
from .artifacts import ArtifactStore
from .backends import LedgerBusyError
from .blobs import BlobStore
from .config import Config
from .connectors.registry import Registry
from .credentials_env import SecretResolver
from .gate import settings_from_config
from .gateway import Gateway
from .ledger import Ledger
from .rating import AlreadyRated, NotClosed
from .routing import RoutingPolicy
from .runner import Runner
from .runtime import Runtime, TaskClosed, UnknownTask
from .sessions import SESSION_TTL, Sessions, login_folder, redeem_login_code
from .validation import SpecValidationError

log = logging.getLogger("ooat.serve")
MAX_BODY = 20 * 1024 * 1024  # design 05 §5: 413 TOO_LARGE above it
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
SESSION_COOKIE = "ooat_session"
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
}


@dataclass(frozen=True)
class ServeSettings:
    ledger_url: str
    blobs_dir: Path
    operator: str | None = None  # [serve] operator: who the start-up sign-in link is for
    host: str = "127.0.0.1"
    port: int = 8765
    hosts: tuple[str, ...] = ()  # further names the Host header may carry, e.g. the machine's DNS name
    tls: bool = False

    @property
    def loopback(self) -> bool:
        try:
            return ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            return self.host == "localhost"

    @property
    def session_cap(self) -> str | None:
        """A web session is uncapped on loopback; served beyond it, it is capped like a token (design 05 §14)."""
        return None if self.loopback else "internal"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return LOOPBACK_NAMES | {h.lower() for h in self.hosts} | ({self.host.lower()} if not self.loopback else set())


@dataclass(frozen=True)
class Principal:
    operator: str
    channel: str  # "web" or "token:<id>"
    scopes: frozenset[str]
    max_data_class: str | None  # None: no cap


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def error_response(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details}}, status_code=status)


class Server:
    """What the handlers share. Each thread gets its own ledger connection and Runtime (SQLite stays per thread)."""

    def __init__(self, settings: ServeSettings, config: Config, registry: Registry, routing: RoutingPolicy,
                 clock: Callable[[], datetime]):
        self.settings, self.config, self.registry, self.routing, self.clock = settings, config, registry, routing, clock
        self.sessions = Sessions()
        self.runner = Runner(self.new_runtime, clock=clock)
        self._local = threading.local()

    def new_runtime(self) -> Runtime:
        ledger = Ledger.open(self.settings.ledger_url)
        gateway = Gateway(ledger, self.registry, self.routing, self.config, SecretResolver(self.config),
                          clock=self.clock)
        return Runtime(ledger, gateway, ArtifactStore(ledger, BlobStore(self.settings.blobs_dir)),
                       settings_from_config(self.config), clock=self.clock)

    def runtime(self) -> Runtime:
        """This thread's Runtime (API handlers run in a thread pool)."""
        runtime = getattr(self._local, "runtime", None)
        if runtime is None:
            runtime = self._local.runtime = self.new_runtime()
        return runtime


def server_of(request: Request) -> Server:
    return request.app.state.server


# Who is asking ----------------------------------------------------------------------------------------------------

def principal(request: Request) -> Principal:
    server = server_of(request)
    now = server.clock()
    header = request.headers.get("authorization")
    if header is not None:
        scheme, _, presented = header.partition(" ")
        token = tokens.authenticate(server.runtime().ledger.events(types=tokens.EVENTS), presented.strip(), now) \
            if scheme.lower() == "bearer" else None
        if token is None:
            raise ApiError(401, "UNAUTHENTICATED", "unknown, expired or revoked token")
        return Principal(token.operator, f"token:{token.id}", token.scopes, token.max_data_class)
    cookie = request.cookies.get(SESSION_COOKIE)
    session = server.sessions.get(cookie, now) if cookie else None
    if session is None:
        raise ApiError(401, "UNAUTHENTICATED", "sign in with the link `ooat login --operator <name>` prints")
    if request.method not in SAFE_METHODS and not hmac.compare_digest(
            request.headers.get("x-csrf-token", "").encode("utf-8"), session.csrf.encode("utf-8")):
        raise ApiError(403, "CSRF", "missing or wrong X-CSRF-Token header")
    return Principal(session.operator, "web", frozenset(tokens.SCOPES), server.settings.session_cap)


def scope(name: str) -> Callable[..., Principal]:
    def check(who: Principal = Depends(principal)) -> Principal:
        if name not in who.scopes:
            raise ApiError(403, "SCOPE", f"this token has no {name} scope")
        return who
    return check


def require_within(who: Principal, data_class: str) -> None:
    """A write on content above the reader's cap is refused like a read is stubbed (design 05 §14)."""
    if not views.within(data_class, who.max_data_class):
        raise ApiError(403, "DATA_CLASS_ABOVE_TOKEN", f"this is {data_class} data, above {who.max_data_class}")


# The app ----------------------------------------------------------------------------------------------------------

def create_app(settings: ServeSettings, *, config: Config, registry: Registry, routing: RoutingPolicy,
               clock: Callable[[], datetime], start_runner: bool = True) -> FastAPI:
    server = Server(settings, config, registry, routing, clock)

    @asynccontextmanager
    async def lifespan(app):
        if start_runner:
            server.runner.start()
        yield
        if start_runner:
            server.runner.stop()

    app = FastAPI(title="OOAT", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.server = server
    _guards(app, settings)
    _errors(app)
    app.include_router(login_routes())
    app.include_router(session_routes(), prefix="/api/v1")

    return app


def _origin_allowed(origin: str, settings: ServeSettings) -> bool:
    parts = urlsplit(origin)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return False
    return parts.scheme == ("https" if settings.tls else "http") and (parts.hostname or "") in settings.allowed_hosts \
        and port == settings.port


def _unsafe_allowed(request: Request, settings: ServeSettings) -> bool:
    """A browser sends Origin on every unsafe request; it must be this server. A bearer client (a bot) need not."""
    origin = request.headers.get("origin")
    if origin is not None:
        return _origin_allowed(origin, settings)
    return request.headers.get("authorization") is not None


def _guards(app: FastAPI, settings: ServeSettings) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = urlsplit("//" + request.headers.get("host", "")).hostname or ""
        length = request.headers.get("content-length")
        if host.lower() not in settings.allowed_hosts:  # stops DNS-rebinding pages from reaching the local API
            response = error_response(400, "HOST_NOT_ALLOWED", "this Host is not served")
        elif request.method not in SAFE_METHODS and not _unsafe_allowed(request, settings):
            response = error_response(403, "ORIGIN_NOT_ALLOWED", "an unsafe request needs this server's Origin")
        elif request.method not in SAFE_METHODS and length is None:
            response = error_response(411, "LENGTH_REQUIRED", "send a Content-Length")
        elif length is not None and not (length.isascii() and length.isdigit()):
            response = error_response(400, "INVALID", "Content-Length must be a number")
        elif int(length or 0) > MAX_BODY:
            response = error_response(413, "TOO_LARGE", "a request may carry at most 20 MB")
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        log.info("%s %s %s", request.method, request.url.path, response.status_code)  # no query, headers or body
        return response


def _errors(app: FastAPI) -> None:
    def handler(status: int, code: str):
        async def handle(request, error):
            return error_response(status, code, str(error))
        return handle

    @app.exception_handler(ApiError)
    async def api_error(request, error: ApiError):
        return error_response(error.status, error.code, error.message, error.details)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error: RequestValidationError):
        # Pydantic's details echo the input; keep only where and what, never an attachment's content.
        details = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in error.errors()]
        return error_response(400, "INVALID", "the request does not match the API", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error: StarletteHTTPException):
        return error_response(error.status_code, "NOT_FOUND" if error.status_code == 404 else "INVALID",
                              str(error.detail))

    # The functions the CLI calls raise these; the API maps them, it adds no rules of its own.
    for kind, status, code in ((SpecValidationError, 422, "SPEC_VALIDATION"), (LedgerBusyError, 503, "LEDGER_BUSY"),
                               (UnknownTask, 404, "NOT_FOUND"), (hil.UnknownRequest, 404, "NOT_FOUND"),
                               (hil.AlreadyAnswered, 409, "ALREADY_ANSWERED"), (NotClosed, 409, "NOT_CLOSED"),
                               (AlreadyRated, 409, "ALREADY_RATED"), (TaskClosed, 409, "NOT_OPEN"),
                               (hil.R3NeedsBoundIdentity, 403, "R3_NEEDS_BOUND_IDENTITY"),
                               (ValueError, 400, "INVALID")):
        app.add_exception_handler(kind, handler(status, code))


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=128)


def login_routes() -> APIRouter:
    """The sign-in page and the code exchange: the only routes without authentication."""
    router = APIRouter()
    web = files("ooat_core") / "web"

    @router.get("/login")
    def login_page() -> Response:
        return Response((web / "login.html").read_bytes(), media_type="text/html; charset=utf-8")

    @router.get("/login.js")
    def login_script() -> Response:
        return Response((web / "login.js").read_bytes(), media_type="text/javascript; charset=utf-8")

    @router.post("/api/v1/login")
    def login(body: LoginIn, request: Request) -> JSONResponse:
        server = server_of(request)
        folder = login_folder(server.settings.ledger_url)
        operator = redeem_login_code(folder, body.code, server.clock()) if folder else None
        if operator is None:
            raise ApiError(401, "UNAUTHENTICATED", "this sign-in link is unknown, used or expired; run `ooat login`")
        cookie, session = server.sessions.open(operator, server.clock())
        response = JSONResponse({"operator": operator, "csrf": session.csrf})
        response.set_cookie(SESSION_COOKIE, cookie, max_age=int(SESSION_TTL.total_seconds()), httponly=True,
                            samesite="strict", secure=server.settings.tls, path="/")
        return response

    return router


def session_routes() -> APIRouter:
    router = APIRouter()

    @router.post("/logout")
    def logout(request: Request, who: Principal = Depends(principal)) -> JSONResponse:
        server_of(request).sessions.close(request.cookies.get(SESSION_COOKIE, ""))
        response = JSONResponse({"operator": who.operator})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @router.get("/me")
    def me(request: Request, who: Principal = Depends(principal)) -> dict:
        found = {"operator": who.operator, "channel": who.channel, "scopes": sorted(who.scopes),
                 "max_data_class": who.max_data_class}
        if who.channel == "web":  # the page needs it after a reload; no other origin can read this response
            server = server_of(request)
            found["csrf"] = server.sessions.get(request.cookies[SESSION_COOKIE], server.clock()).csrf
        return found

    @router.get("/status")
    def status(request: Request, who: Principal = Depends(scope("read"))) -> dict:
        return {"runner": server_of(request).runner.status()}

    return router
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest core/tests/test_api_security.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/pyproject.toml requirements-dev.txt core/src/ooat_core/sessions.py core/src/ooat_core/api.py core/src/ooat_core/web/login.html core/src/ooat_core/web/login.js core/tests/api_fakes.py core/tests/test_api_security.py
git commit -m "feat(core): API shell - sessions, tokens, Host/Origin/CSRF guards, limits, typed errors (plan 05a)"
```

---

### Task 9: The resources: tasks, timeline, artifacts, questions, ratings, connectors, usage

**Files:**
- Create: `core/src/ooat_core/endpoints.py`
- Modify: `core/src/ooat_core/api.py` (`create_app` includes the resources)
- Test: `core/tests/test_api.py`

**Interfaces:**
- Consumes: everything `api.py` produces (Task 8); `Runtime.submit` / `cancel`, `hil.*`, `rate` (Task 4);
  `connector_admin.*`; `views.*`, `stats.usage` (Task 7).
- Produces: `endpoints.resource_routes() -> APIRouter` under `/api/v1`:
  `POST /tasks` (202 `{task, state}`, header `Idempotency-Key`), `GET /tasks?state=&project=&after=&limit=`
  (`{tasks, next}`), `GET /tasks/{task}`, `GET /tasks/{task}/events?after=` (`{events, next}`, or Server-Sent
  Events with `Accept: text/event-stream` and `Last-Event-ID`), `POST /tasks/{task}/cancel` (202), `GET
  /artifacts/{ref}`, `GET /artifacts/{ref}/diff?against=`, `GET /hil`, `POST /hil/{request_id}/answer` (202),
  `GET /ratings/queue`, `POST /tasks/{task}/rating` (201), `GET /connectors`, `GET /connectors/{id}/card`,
  `POST /connectors/{id}/enable|disable` (201), `GET /connectors/{id}/hooks`, `POST /connectors/{id}/approve-hooks`
  (201), `GET /stats?period=&project=&group=`. Helpers `endpoints.task_classes(server, tasks)`,
  `endpoints.one_task(server, task) -> (events, data_class)`; `endpoints._stream(server, task, cursor, recheck:
  Callable[[], Principal])` re-authenticates on every poll and ends with an `UNAUTHENTICATED` event.
  `approve-hooks` answers 403 `SCOPE` to any bearer token.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_api.py`:

```python
"""`ooat serve` endpoints end to end on a file ledger with fake connectors (design 05 §5, §6, §11)."""

import base64
import json

import pytest
from api_fakes import CRITERIA, PERSONAL_GOAL, Served

from ooat_core.ledger import new_event


def get(served, path, headers):
    response = served.client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_submit_answer_and_rate_through_the_api(tmp_path):
    served = Served(tmp_path)
    bot = served.token()
    submitted = served.submit(bot, acceptance=[])  # no criteria: the Gate asks (rule A1)
    task = submitted["task"]
    assert submitted["state"] == "SUBMITTED"
    assert served.run() == [task]
    (question,) = get(served, "/api/v1/hil", bot)["requests"]
    assert question["task"] == task and question["recommended"] and question["deadline"]
    answered = served.client.post(f"/api/v1/hil/{question['request']}/answer", headers=bot,
                                  json={"text": CRITERIA[0]})
    assert answered.status_code == 202
    served.run()
    detail = get(served, f"/api/v1/tasks/{task}", bot)
    assert detail["state"] == "CLOSED_DONE" and detail["result"]["cost"]["contracts_usd"] > 0
    (document,) = detail["result"]["artifacts"]
    shown = served.client.get(f"/api/v1/artifacts/{document}", headers=bot)
    assert shown.text == served.model.documents[0] and shown.headers["content-type"] == "text/plain; charset=utf-8"
    (entry,) = get(served, "/api/v1/ratings/queue", bot)["tasks"]
    decisions = [{"event": d["event"], "question": d["question"], "verdict": "confirmed"} for d in entry["decisions"]]
    rated = served.client.post(f"/api/v1/tasks/{task}/rating", headers=bot,
                               json={"accepted": True, "value_class": "B", "decisions": decisions})
    assert rated.status_code == 201 and rated.json()["decisions"] == len(decisions)
    again = served.client.post(f"/api/v1/tasks/{task}/rating", headers=bot, json={"accepted": True, "value_class": "B"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_RATED"
    assert get(served, "/api/v1/ratings/queue", bot)["tasks"] == []
    usage = get(served, "/api/v1/stats?period=7d&group=connector", bot)
    assert {g["key"] for g in usage["groups"]} == {"prv.fake.api", "prv.fakejev.api"}
    assert usage["tasks"]["accepted"] == 1 and usage["hil"]["answered"] == 1
    with served.ledger() as ledger:
        events = ledger.events(task=task)
    channel = submitted_channel = next(e for e in events if e["type"] == "TASK_SUBMITTED")["body"]["channel"]
    assert channel.startswith("token:tok_")
    for kind in ("HIL_RESPONSE", "TASK_RATED"):
        assert next(e for e in events if e["type"] == kind)["body"]["channel"] == submitted_channel
    assert all(e["actor"]["id"] == "operator" for e in events if e["actor"]["kind"] == "hil")


def test_a_repeated_idempotency_key_returns_the_first_task_also_after_a_restart(tmp_path):
    served = Served(tmp_path)
    bot = served.token()
    first = served.client.post("/api/v1/tasks", headers={**bot, "Idempotency-Key": "chat-1:msg-7"},
                               json={"project": "docs", "goal": "Shrň smlouvu."}).json()["task"]
    restarted = Served(tmp_path)  # a new server process on the same ledger
    again = restarted.client.post("/api/v1/tasks", headers={**bot, "Idempotency-Key": "chat-1:msg-7"},
                                  json={"project": "docs", "goal": "Shrň smlouvu."})
    assert again.status_code == 202 and again.json()["task"] == first
    with served.ledger() as ledger:
        assert len(ledger.events(types=["TASK_SUBMITTED"])) == 1


def test_a_second_answer_is_a_conflict(tmp_path):
    served = Served(tmp_path)
    bot = served.token()
    served.submit(bot, acceptance=[])
    served.run()
    (question,) = get(served, "/api/v1/hil", bot)["requests"]
    path = f"/api/v1/hil/{question['request']}/answer"
    assert served.client.post(path, headers=bot, json={"choice": "do_not_run"}).status_code == 202
    second = served.client.post(path, headers=bot, json={"choice": "run_as_is"})
    assert second.status_code == 409 and second.json()["error"]["code"] == "ALREADY_ANSWERED"


def test_cancel_closes_a_waiting_task_through_the_runner(tmp_path):
    served = Served(tmp_path)
    bot = served.token()
    task = served.submit(bot, acceptance=[])["task"]
    served.run()
    cancelled = served.client.post(f"/api/v1/tasks/{task}/cancel", headers=bot)
    assert cancelled.status_code == 202 and cancelled.json()["cancel"] == "requested"
    served.run()
    assert get(served, f"/api/v1/tasks/{task}", bot)["state"] == "CANCELLED"
    late = served.client.post(f"/api/v1/tasks/{task}/cancel", headers=bot)
    assert late.status_code == 409 and late.json()["error"]["code"] == "NOT_OPEN"


def test_the_timeline_follows_a_cursor_and_streams_until_the_task_is_closed(tmp_path):
    served = Served(tmp_path)
    bot = served.token()
    task = served.submit(bot, acceptance=CRITERIA)["task"]
    served.run()
    events = get(served, f"/api/v1/tasks/{task}/events", bot)["events"]
    assert events[0]["type"] == "TASK_SUBMITTED" and events[-1]["type"] == "TASK_CLOSED"
    later = get(served, f"/api/v1/tasks/{task}/events?after={events[2]['id']}", bot)
    assert [e["id"] for e in later["events"]] == [e["id"] for e in events[3:]]
    with served.client.stream("GET", f"/api/v1/tasks/{task}/events", headers={**bot, "Accept": "text/event-stream",
                                                                                "Last-Event-ID": events[-3]["id"]}) \
            as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        lines = [line for line in stream.iter_lines() if line.startswith("event: ")]
    assert lines == [f"event: {e['type']}" for e in events[-2:]]  # then the stream ends: the task is closed
    bad = served.client.get(f"/api/v1/tasks/{task}/events?after=evt_01J9ZQ70A0K3M5N7P9Q1R3S5T7", headers=bot)
    assert bad.status_code == 400


def test_a_token_revoked_while_its_stream_is_open_ends_the_stream_at_the_next_poll(tmp_path, monkeypatch):
    from ooat_core import endpoints, tokens

    from starlette.requests import Request

    from ooat_core.api import principal, scope

    monkeypatch.setattr(endpoints, "SSE_POLL_S", 0.01)
    served = Served(tmp_path)
    bot = served.token()
    task = served.submit(bot, acceptance=[])["task"]
    served.run()  # waits for a clarification: the stream stays open
    # The test client buffers a whole streamed body, so the stream's generator is driven here, step by step, with
    # the same re-check the endpoint gives it.
    request = Request({"type": "http", "method": "GET", "path": "/", "app": served.app, "query_string": b"",
                       "headers": [(b"authorization", bot["Authorization"].encode())]})
    stream = endpoints._stream(served.server, task, None, lambda: scope("read")(principal(request)))
    seen = []
    for chunk in stream:
        seen.append(chunk.split("\n", 2)[1] if chunk.startswith("id: ") else chunk.split("\n", 1)[0])
        if seen[-1] == "event: HIL_REQUEST":  # the timeline so far has arrived; now the token leaks
            with served.ledger() as ledger:
                (token,) = tokens.tokens(ledger.events(types=tokens.EVENTS))
                tokens.revoke(ledger, operator="operator", token_id=token, reason="leaked")
    assert seen[0] == "event: TASK_SUBMITTED" and seen[-1] == "event: UNAUTHENTICATED"  # and the stream ended


def test_the_documents_of_two_attempts_have_a_diff_and_the_list_filters(tmp_path):
    from runtime_fakes import ScriptedModel, decisions

    served = Served(tmp_path, model=ScriptedModel(["# Shrnutí\n\nPříliš dlouhé.\n", "# Shrnutí\n\nKrátké.\n"]),
                    jev=decisions(met=[False, True]))  # the first document misses its criterion: a second attempt
    bot = served.token()
    task = served.submit(bot, acceptance=CRITERIA)["task"]
    other = served.submit(bot, project="sales", acceptance=CRITERIA)["task"]
    served.run()
    first, second = [a["ref"] for a in get(served, f"/api/v1/tasks/{task}", bot)["artifacts"]]
    diff = served.client.get(f"/api/v1/artifacts/{second}/diff?against={first}", headers=bot)
    assert diff.status_code == 200 and "-Příliš dlouhé." in diff.text and "+Krátké." in diff.text
    foreign = get(served, f"/api/v1/tasks/{other}", bot)["result"]["artifacts"][0]
    assert served.client.get(f"/api/v1/artifacts/{second}/diff?against={foreign}", headers=bot).status_code == 400
    listed = get(served, "/api/v1/tasks?project=docs&state=CLOSED_DONE", bot)["tasks"]
    assert [t["task"] for t in listed] == [task]
    page = get(served, "/api/v1/tasks?limit=1", bot)
    assert [t["task"] for t in page["tasks"]] == [other] and page["next"] == other
    assert [t["task"] for t in get(served, f"/api/v1/tasks?after={other}", bot)["tasks"]] == [task]


def test_an_r3_request_is_refused_on_the_web_and_for_a_token(tmp_path):
    served = Served(tmp_path)
    bot, web = served.token(), served.login()
    task = served.submit(bot, acceptance=[])["task"]
    with served.ledger() as ledger:
        request = ledger.append(new_event("HIL_REQUEST", task=task, actor={"kind": "system", "id": "ooat-runtime"},
                                          body={"question": "Odeslat nabídku?", "risk_class": "R3", "options": [
                                              {"id": "send", "label": "Odeslat", "cost_usd": 0.0},
                                              {"id": "hold", "label": "Ne", "cost_usd": 0.0, "acts": False}],
                                              "recommended": "send", "default_on_silence": "hold",
                                              "deadline": "2099-01-01T00:00:00Z", "blocking": True, "evidence": []}))
    for headers in (web, bot):
        response = served.client.post(f"/api/v1/hil/{request['id']}/answer", headers=headers, json={"choice": "hold"})
        assert response.status_code == 403 and response.json()["error"]["code"] == "R3_NEEDS_BOUND_IDENTITY"


PERSONAL_ROUTE = ("public", "internal", "personal")  # the operator enabled the fake model for personal data


def personal_task(served, web):
    """A closed task with personal data in its goal and its attachment, submitted and cancelled in the web app."""
    attachment = base64.b64encode("Kontakt: jan.novak@example.cz".encode()).decode()
    task = served.submit(web, goal=PERSONAL_GOAL, project="client-x", data_class="personal",
                         attachments=[{"name": "kontakt.txt", "content_base64": attachment}])["task"]
    served.run()
    assert served.client.post(f"/api/v1/tasks/{task}/cancel", headers=web).status_code == 202
    served.run()
    return task


def test_content_above_a_tokens_cap_is_a_stub_on_every_read_endpoint(tmp_path):
    served = Served(tmp_path, classes=PERSONAL_ROUTE)
    web, bot = served.login(), served.token(cap="internal")
    task = personal_task(served, web)
    waiting = served.submit(web, goal=PERSONAL_GOAL, project="client-x", acceptance=[])["task"]
    served.run()
    detail = get(served, f"/api/v1/tasks/{task}", bot)
    attachment = next(a["ref"] for a in detail["artifacts"] if a["type"] == "attachment")
    responses = {
        "list": get(served, "/api/v1/tasks", bot), "detail": detail,
        "waiting": get(served, f"/api/v1/tasks/{waiting}", bot),
        "events": get(served, f"/api/v1/tasks/{task}/events", bot),
        "hil": get(served, "/api/v1/hil", bot), "ratings": get(served, "/api/v1/ratings/queue", bot),
        "artifact": get(served, f"/api/v1/artifacts/{attachment}", bot),
        "stats": get(served, "/api/v1/stats?group=project&period=all", bot),
    }
    for name, body in responses.items():
        text = json.dumps(body, ensure_ascii=False).lower()
        assert "novak" not in text and "client-x" not in text, name
    assert detail["state"] == "CANCELLED" and detail["goal"]["redacted"]  # the state and the costs stay visible
    assert responses["hil"]["requests"][0]["question"]["redacted"] and responses["artifact"]["redacted"]
    assert {g["key"] for g in responses["stats"]["groups"]} <= {"(other)"}  # never the project name
    assert "novak" in json.dumps(get(served, f"/api/v1/tasks/{task}", {})).lower()  # the web session sees it


def test_writes_on_a_task_above_a_tokens_cap_are_refused(tmp_path):
    served = Served(tmp_path, classes=PERSONAL_ROUTE)
    web, bot = served.login(), served.token(cap="internal")
    task = personal_task(served, web)
    waiting = served.submit(web, goal=PERSONAL_GOAL, project="client-x", acceptance=[])["task"]
    served.run()
    (question,) = get(served, "/api/v1/hil", web)["requests"]
    attempts = [served.client.post(f"/api/v1/hil/{question['request']}/answer", headers=bot, json={"choice": "clarify",
                                                                                                    "text": "x"}),
                served.client.post(f"/api/v1/tasks/{task}/rating", headers=bot,
                                   json={"accepted": False, "value_class": "C"}),
                served.client.post(f"/api/v1/tasks/{waiting}/cancel", headers=bot),
                served.client.post("/api/v1/tasks", headers=bot,
                                   json={"project": "docs", "goal": "x", "data_class": "client_confidential"})]
    for response in attempts:
        assert response.status_code == 403 and response.json()["error"]["code"] == "DATA_CLASS_ABOVE_TOKEN"


def test_connectors_need_their_scope_and_a_typed_confirmation(tmp_path):
    served = Served(tmp_path)
    web, bot = served.login(), served.token()
    assert served.client.get("/api/v1/connectors", headers=bot).status_code == 403
    listed = get(served, "/api/v1/connectors", web)["connectors"]
    assert {c["id"] for c in listed} == {"prv.fake.api", "prv.fakejev.api"}
    card = get(served, "/api/v1/connectors/prv.fake.api/card", web)["card"]
    assert card.startswith("Connection consequences: prv.fake.api")
    body = {"classes": ["public"], "automation": True, "confirm": "prv.fake"}
    assert served.client.post("/api/v1/connectors/prv.fake.api/enable", headers=web, json=body).status_code == 400
    enabled = served.client.post("/api/v1/connectors/prv.fake.api/enable", headers=web,
                                 json={**body, "confirm": "prv.fake.api"})
    assert enabled.status_code == 201
    disabled = served.client.post("/api/v1/connectors/prv.fake.api/disable", headers=web, json={"reason": "trial"})
    assert disabled.status_code == 201
    with served.ledger() as ledger:
        state = ledger.events(types=["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"])[-2:]
    assert [e["body"]["channel"] for e in state] == ["web", "web"]
    assert all(e["actor"] == {"kind": "hil", "id": "operator"} for e in state)


def test_errors_are_typed_and_never_echo_an_attachment(tmp_path):
    served = Served(tmp_path)
    token = served.token()
    unknown = served.client.get("/api/v1/tasks/tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7", headers=token)
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "NOT_FOUND"
    secret = "VERY-SECRET-ATTACHMENT-CONTENT"
    invalid = served.client.post("/api/v1/tasks", headers=token, json={
        "project": "Docs With Spaces", "goal": "x", "attachments": [{"name": "a.txt", "content_base64": secret}]})
    assert invalid.status_code == 400 and invalid.json()["error"]["code"] == "INVALID" and secret not in invalid.text
    for content, name in (("%%%", "not base64"), ("AAEC", "binary")):
        response = served.client.post("/api/v1/tasks", headers=token, json={
            "project": "docs", "goal": "x", "attachments": [{"name": "a.txt", "content_base64": content}]})
        assert response.status_code == 400, name
    bad_key = served.client.post("/api/v1/tasks", headers={**token, "Idempotency-Key": "a b"},
                                 json={"project": "docs", "goal": "x"})
    assert bad_key.status_code == 400
    with served.ledger() as ledger:
        assert ledger.events(types=["TASK_SUBMITTED"]) == []


def test_a_ledger_locked_past_the_busy_timeout_answers_503_and_writes_nothing(tmp_path, monkeypatch):
    import sqlite3

    from ooat_core.backends import sqlite as sqlite_backend

    monkeypatch.setattr(sqlite_backend, "BUSY_TIMEOUT_MS", 100)
    served = Served(tmp_path)
    headers = served.token()
    other = sqlite3.connect(tmp_path / "ledger.sqlite", isolation_level=None)
    other.execute("BEGIN IMMEDIATE")  # e.g. a long write by another process
    try:
        response = served.client.post("/api/v1/tasks", headers=headers, json={"project": "docs", "goal": "x"})
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert response.status_code == 503 and response.json()["error"]["code"] == "LEDGER_BUSY"
    with served.ledger() as ledger:
        assert ledger.events(types=["TASK_SUBMITTED"]) == []


def test_hooks_are_approved_from_a_web_session_never_with_a_token(tmp_path):
    served = Served(tmp_path)
    web, bot = served.login(), served.token(scopes=("connectors",))
    body = {"confirm": "prv.fake.api", "hooks": []}
    by_token = served.client.post("/api/v1/connectors/prv.fake.api/approve-hooks", headers=bot, json=body)
    assert by_token.status_code == 403 and by_token.json()["error"]["code"] == "SCOPE"
    by_web = served.client.post("/api/v1/connectors/prv.fake.api/approve-hooks", headers=web, json=body)
    assert by_web.status_code == 400 and "no hooks" in by_web.json()["error"]["message"]  # past the channel check


UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
OPEN = {"/login", "/login.js", "/api/v1/login"}


def test_every_endpoint_but_the_sign_in_needs_authentication(tmp_path):
    from ooat_core.api import login_routes, session_routes
    from ooat_core.endpoints import resource_routes

    served = Served(tmp_path)
    routes = [(method, "/api/v1" + route.path) for router in (session_routes(), resource_routes())
              for route in router.routes for method in route.methods]
    routes += [(method, route.path) for route in login_routes().routes for method in route.methods]
    routes = [(method, path) for method, path in routes if path not in OPEN]
    assert len(routes) >= 20
    for method, path in routes:
        url = path.replace("{task}", "tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7").replace(
            "{request_id}", "evt_01J9ZQ70A0K3M5N7P9Q1R3S5T7").replace("{ref}", "art_01J9ZQ6X9EK3M5N7P9Q1R3S5T7@v1") \
            .replace("{connector_id}", "prv.fake.api")
        headers = {"Origin": served.origin} if method in UNSAFE else {}
        response = served.client.request(method, url, headers=headers, json={} if method in UNSAFE else None)
        assert response.status_code == 401, (method, path, response.status_code)


@pytest.mark.parametrize("scope, method, path", [
    ("read", "GET", "/api/v1/tasks"), ("read", "GET", "/api/v1/hil"), ("read", "GET", "/api/v1/stats"),
    ("submit", "POST", "/api/v1/tasks/tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7/cancel"),
    ("answer", "POST", "/api/v1/hil/evt_01J9ZQ70A0K3M5N7P9Q1R3S5T7/answer"),
    ("rate", "POST", "/api/v1/tasks/tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7/rating"),
    ("connectors", "GET", "/api/v1/connectors"),
])
def test_each_endpoint_checks_its_scope(tmp_path, scope, method, path):
    served = Served(tmp_path)
    others = [s for s in ("submit", "read", "answer", "rate", "connectors") if s != scope]
    response = served.client.request(method, path, headers=served.token(scopes=others),
                                     json={"accepted": True, "value_class": "A"} if method == "POST" else None)
    assert response.status_code == 403 and response.json()["error"]["code"] == "SCOPE"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest core/tests/test_api.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ooat_core.endpoints'` in the route test, 404 `NOT_FOUND` for `POST /api/v1/tasks` elsewhere

- [ ] **Step 3: Implement the resources**

Create `core/src/ooat_core/endpoints.py`:

```python
"""The resources of the REST API (design 05 §5): tasks, timelines, artifacts, questions, ratings, connectors, usage.

Handlers call the same functions as the CLI (`Runtime.submit`, `Runtime.cancel`, `hil.answer`, `rate`,
`connector_admin.*`) with the operator and the channel of the principal, never a name from the request body; they
build no actor themselves. Every read applies the reader's data-class cap through views.py, and a write on content
above it is refused with DATA_CLASS_ABOVE_TOKEN. Whatever changes a task queues it for the runner.
"""

import base64
import binascii
import difflib
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from . import connector_admin, hil, stats, views
from .api import ApiError, Principal, Server, principal, require_within, scope, server_of
from .gate import settings_from_config
from .ids import parse_artifact_ref
from .rating import rate
from .runtime import CLOSED
from .state import task_state

INTAKE_KEY = re.compile(r"^[!-~]{1,128}$")  # printable ASCII without spaces, as the schema's intake_key
SSE_POLL_S, SSE_MAX_S = 1.0, 900.0  # a stream ends after 15 minutes; the client reconnects with Last-Event-ID
DataClass = Literal["public", "internal", "client_confidential", "personal", "special_category"]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttachmentIn(_Body):
    name: str = Field(min_length=1, max_length=255)
    content_base64: str


class TaskIn(_Body):
    project: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=64)
    goal: str = Field(min_length=1, max_length=20000)
    expected_output: str | None = Field(default=None, min_length=1, max_length=5000)
    acceptance: list[str] = Field(default=[], max_length=20)
    value: Literal["A", "B", "C"] | None = None
    value_usd: float | None = Field(default=None, ge=0)
    budget_usd: float | None = Field(default=None, gt=0)
    data_class: DataClass = "internal"
    attachments: list[AttachmentIn] = Field(default=[], max_length=20)


class AnswerIn(_Body):
    choice: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")
    text: str | None = Field(default=None, max_length=20000)


class VerdictIn(_Body):
    event: str
    question: str
    verdict: Literal["confirmed", "corrected"]
    value: StrictInt | StrictStr | None = None


class RatingIn(_Body):
    accepted: bool
    value_class: Literal["A", "B", "C"]
    note: str | None = Field(default=None, max_length=5000)
    decisions: list[VerdictIn] = []


class ResponsibilityIn(_Body):
    processing_regions: list[str] | None = None
    no_training: Literal[True] | None = None


class EnableIn(_Body):
    classes: list[DataClass] = Field(min_length=1)
    automation: bool
    confirm: str  # the connector id, typed again (spec §9 rule 1)
    responsibility: ResponsibilityIn | None = None  # stated for client_confidential or personal (ADR 0012)


class DisableIn(_Body):
    reason: str = Field(min_length=1, max_length=500)


class HookIn(_Body):
    path: str
    sha256: str


class HooksIn(_Body):
    confirm: str
    hooks: list[HookIn]  # exactly as GET .../hooks listed them: the operator approves what they saw


def task_classes(server: Server, tasks: dict[str, list[dict]]) -> dict[str, str]:
    ledger, settings = server.runtime().ledger, settings_from_config(server.config)
    return {task: views.task_class(events, lambda ref: ledger.artifact(ref)["data_class"], settings)
            for task, events in tasks.items()}


def submitted_tasks(server: Server) -> dict[str, list[dict]]:
    tasks = views.by_task(server.runtime().ledger.events())
    return {t: e for t, e in tasks.items() if any(x["type"] == "TASK_SUBMITTED" for x in e)}


def one_task(server: Server, task: str) -> tuple[list[dict], str]:
    """The task's events and class; 404 when there is no such task."""
    events = server.runtime().ledger.events(task=task)
    if not any(e["type"] == "TASK_SUBMITTED" for e in events):
        raise ApiError(404, "NOT_FOUND", f"no task {task}")
    return events, task_classes(server, {task: events})[task]


def resource_routes() -> APIRouter:
    api = APIRouter()

    # Tasks -----------------------------------------------------------------------------------------------------

    @api.post("/tasks", status_code=202)
    def submit(body: TaskIn, request: Request, who: Principal = Depends(scope("submit")),
               idempotency_key: str | None = Header(default=None)) -> dict:
        require_within(who, body.data_class)
        if idempotency_key is not None and not INTAKE_KEY.match(idempotency_key):
            raise ApiError(400, "INVALID", "Idempotency-Key is 1 to 128 printable ASCII characters without spaces")
        if body.value is not None and body.value_usd is not None:
            raise ApiError(400, "INVALID", "give value or value_usd, not both")
        try:
            contents = [base64.b64decode(a.content_base64, validate=True) for a in body.attachments]
        except (binascii.Error, ValueError):
            raise ApiError(400, "INVALID", "an attachment's content_base64 is not base64") from None
        server = server_of(request)
        runtime = server.runtime()
        value = {"class": body.value} if body.value else {"usd": body.value_usd} if body.value_usd is not None else None
        task = runtime.submit(operator=who.operator, goal=body.goal, acceptance=body.acceptance, project=body.project,
                              expected_output=body.expected_output, value=value, budget_usd=body.budget_usd,
                              data_class=body.data_class, files=contents,
                              file_names=[a.name for a in body.attachments], channel=who.channel,
                              intake_key=idempotency_key)
        server.runner.enqueue(task)
        return {"task": task, "state": task_state(runtime.ledger.events(task=task))}

    @api.get("/tasks")
    def list_tasks(request: Request, state: str | None = None, project: str | None = None, after: str | None = None,
                   limit: int = 50, who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        tasks = submitted_tasks(server)
        classes = task_classes(server, tasks)
        found = []
        for task in sorted(tasks, reverse=True):  # ULIDs sort by creation: newest first; `after` pages on
            if after is not None and task >= after:
                continue
            summary = views.task_summary(task, tasks[task], classes[task], who.max_data_class)
            if (state is None or summary["state"] == state) and (project is None or summary["project"] == project):
                found.append(summary)
        limit = max(1, min(limit, 200))
        return {"tasks": found[:limit], "next": found[limit - 1]["task"] if len(found) > limit else None}

    @api.get("/tasks/{task}")
    def show_task(task: str, request: Request, who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        events, data_class = one_task(server, task)
        return views.task_detail(task, events, data_class, who.max_data_class, server.runtime().ledger.artifact,
                                 hil.open_requests(server.runtime().ledger))

    @api.get("/tasks/{task}/events", response_model=None)
    def task_events(task: str, request: Request, after: str | None = None, who: Principal = Depends(scope("read")),
                    last_event_id: str | None = Header(default=None)) -> dict | StreamingResponse:
        server = server_of(request)
        events, data_class = one_task(server, task)
        cursor = last_event_id or after
        try:
            found = views.timeline(events, data_class, who.max_data_class, cursor)
        except KeyError:
            raise ApiError(400, "INVALID", f"{cursor} is not an event of {task}") from None
        if "text/event-stream" not in request.headers.get("accept", ""):
            return {"events": found, "next": found[-1]["id"] if found else cursor}
        return StreamingResponse(_stream(server, task, cursor, lambda: scope("read")(principal(request))),
                                 media_type="text/event-stream")

    @api.post("/tasks/{task}/cancel", status_code=202)
    def cancel(task: str, request: Request, who: Principal = Depends(scope("submit"))) -> dict:
        server = server_of(request)
        require_within(who, one_task(server, task)[1])
        asked = server.runtime().cancel(task, operator=who.operator, channel=who.channel)
        server.runner.enqueue(task)
        return {"task": task, "cancel": "requested" if asked else "already requested"}

    # Artifacts -------------------------------------------------------------------------------------------------

    def readable(server: Server, ref: str, who: Principal) -> tuple[dict, bytes | None]:
        """The artifact's record, and its content when it is within the reader's cap (else None)."""
        parse_artifact_ref(ref)  # 400 on a malformed reference
        record = server.runtime().ledger.artifact(ref)
        if record is None:
            raise ApiError(404, "NOT_FOUND", f"no artifact {ref}")
        if not views.within(record["data_class"], who.max_data_class):
            return record, None
        return record, server.runtime().artifacts.read(ref)

    def producing_task(server: Server, record: dict) -> str:
        """Attachments come with TASK_SUBMITTED, documents with RESULT."""
        return next(e["task"] for e in server.runtime().ledger.events(types=["TASK_SUBMITTED", "RESULT"])
                    if e["id"] == record["produced_by_event"])

    @api.get("/artifacts/{ref}", response_model=None)
    def artifact(ref: str, request: Request, who: Principal = Depends(scope("read"))) -> Response:
        server = server_of(request)
        record, content = readable(server, ref, who)
        if content is None:
            return JSONResponse(views.stub(producing_task(server, record)))
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return Response(content, media_type="application/octet-stream",
                            headers={"Content-Disposition": f'attachment; filename="{ref}"'})
        return Response(content, media_type="text/plain; charset=utf-8")  # never text/html: untrusted content

    @api.get("/artifacts/{ref}/diff", response_model=None)
    def diff(ref: str, against: str, request: Request, who: Principal = Depends(scope("read"))) -> Response:
        """A unified diff of two text artifacts of one task, e.g. the documents of two attempts."""
        server = server_of(request)
        (old, before), (new, now) = readable(server, against, who), readable(server, ref, who)
        task = producing_task(server, new)
        if producing_task(server, old) != task:
            raise ApiError(400, "INVALID", "a diff compares two artifacts of one task")
        if before is None or now is None:
            return JSONResponse(views.stub(task))
        try:
            lines = difflib.unified_diff(before.decode("utf-8").splitlines(keepends=True),
                                         now.decode("utf-8").splitlines(keepends=True), fromfile=against, tofile=ref)
        except UnicodeDecodeError:
            raise ApiError(400, "INVALID", "only text artifacts have a diff") from None
        return Response("".join(lines), media_type="text/plain; charset=utf-8")

    # Questions and ratings -------------------------------------------------------------------------------------

    @api.get("/hil")
    def questions(request: Request, who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        found = hil.open_requests(server.runtime().ledger)
        tasks = views.by_task(server.runtime().ledger.events())
        classes = task_classes(server, {r["task"]: tasks[r["task"]] for r in found})
        return {"requests": [views.hil_view(r, classes[r["task"]], who.max_data_class) for r in found]}

    @api.post("/hil/{request_id}/answer", status_code=202)
    def answer(request_id: str, body: AnswerIn, request: Request, who: Principal = Depends(scope("answer"))) -> dict:
        server = server_of(request)
        found = hil.find_request(server.runtime().ledger, request_id)
        if found is None:
            raise ApiError(404, "NOT_FOUND", f"no question {request_id}")
        require_within(who, one_task(server, found["task"])[1])
        response = hil.answer(server.runtime().ledger, server.runtime(), request_id, operator=who.operator,
                              choice=body.choice, text=body.text, channel=who.channel)
        server.runner.enqueue(response["task"])
        return {"task": response["task"], "response": response["id"]}

    @api.get("/ratings/queue")
    def rating_queue(request: Request, who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        closed = {t: e for t, e in submitted_tasks(server).items() if task_state(e) in CLOSED}
        return {"tasks": views.rating_queue(closed, task_classes(server, closed), who.max_data_class)}

    @api.post("/tasks/{task}/rating", status_code=201)
    def rate_task(task: str, body: RatingIn, request: Request, who: Principal = Depends(scope("rate"))) -> dict:
        server = server_of(request)
        require_within(who, one_task(server, task)[1])
        verdicts = {}
        for decision in body.decisions:
            if decision.verdict == "corrected" and decision.value is None:
                raise ApiError(400, "INVALID", f"{decision.question}: a correction needs its value")
            verdicts[(decision.event, decision.question)] = \
                "confirmed" if decision.verdict == "confirmed" else decision.value
        event = rate(server.runtime().ledger, task, operator=who.operator, accepted=body.accepted,
                     value_class=body.value_class, verdicts=verdicts, note=body.note, channel=who.channel)
        return {"task": task, "rating": event["id"], "decisions": len(event["body"]["decisions"])}

    # Connectors ------------------------------------------------------------------------------------------------

    def installed(server: Server, connector_id: str):
        found = server.registry.get(connector_id)
        if found is None:
            raise ApiError(404, "NOT_FOUND", f"{connector_id} is not installed")
        return found

    @api.get("/connectors")
    def connectors(request: Request, who: Principal = Depends(scope("connectors"))) -> dict:
        server = server_of(request)
        statuses = connector_admin.connector_statuses(server.registry, server.runtime().ledger,
                                                      server.clock().date(), server.config)
        return {"connectors": [asdict(s) for s in statuses]}

    @api.get("/connectors/{connector_id}/card")
    def card(connector_id: str, request: Request, who: Principal = Depends(scope("connectors"))) -> dict:
        server = server_of(request)
        manifest = installed(server, connector_id).manifest
        return {"connector": connector_id,
                "card": connector_admin.consequences_card(manifest, server.clock().date(), server.config)}

    @api.post("/connectors/{connector_id}/enable", status_code=201)
    def enable(connector_id: str, body: EnableIn, request: Request,
               who: Principal = Depends(scope("connectors"))) -> dict:
        server = server_of(request)
        connector = installed(server, connector_id)
        if body.confirm != connector_id:
            raise ApiError(400, "INVALID", "type the connector id to confirm")
        for data_class in body.classes:
            require_within(who, data_class)
        responsibility = body.responsibility.model_dump(exclude_none=True) if body.responsibility else None
        event = connector_admin.acknowledge(server.runtime().ledger, connector, who.operator, body.classes,
                                            body.automation, responsibility, server.clock().date(),
                                            channel=who.channel)
        return {"connector": connector_id, "event": event["id"]}

    @api.post("/connectors/{connector_id}/disable", status_code=201)
    def disable(connector_id: str, body: DisableIn, request: Request,
                who: Principal = Depends(scope("connectors"))) -> dict:
        event = connector_admin.disable(server_of(request).runtime().ledger, connector_id, who.operator, body.reason,
                                        channel=who.channel)
        return {"connector": connector_id, "event": event["id"]}

    @api.get("/connectors/{connector_id}/hooks")
    def hooks(connector_id: str, request: Request, who: Principal = Depends(scope("connectors"))) -> dict:
        connector = installed(server_of(request), connector_id)
        listed = connector.hooks() if hasattr(connector, "hooks") else []
        return {"hooks": [{"path": path, "sha256": sha, "text": text} for path, sha, text in listed]}

    @api.post("/connectors/{connector_id}/approve-hooks", status_code=201)
    def approve_hooks(connector_id: str, body: HooksIn, request: Request,
                      who: Principal = Depends(scope("connectors"))) -> dict:
        # Approving a hook approves code that runs on this machine (ADR 0015): the CLI or a web session, never a token.
        if who.channel != "web":
            raise ApiError(403, "SCOPE", "hooks are approved in the web app or with `ooat connectors approve-hooks`, "
                                         "never with an API token")
        server = server_of(request)
        connector = installed(server, connector_id)
        if body.confirm != connector_id:
            raise ApiError(400, "INVALID", "type the connector id to confirm")
        current =[(path, sha) for path, sha, _ in (connector.hooks() if hasattr(connector, "hooks") else [])]
        if not current or any(not sha for _, sha in current):
            raise ApiError(400, "INVALID", "there are no hooks that can be approved")
        if [(h.path, h.sha256) for h in body.hooks] != current:
            raise ApiError(409, "HOOKS_CHANGED", "the hooks changed since they were listed; review them again")
        event = connector_admin.approve_hooks(server.runtime().ledger, connector, who.operator, current,
                                              channel=who.channel)
        return {"connector": connector_id, "event": event["id"]}

    # Usage -----------------------------------------------------------------------------------------------------

    @api.get("/stats")
    def usage(request: Request, period: str = "7d", project: str | None = None, group: str = "role",
              who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        tasks = submitted_tasks(server)
        above = frozenset(t for t, c in task_classes(server, tasks).items() if not views.within(c, who.max_data_class))
        return stats.usage(server.runtime().ledger.events(), now=server.clock(), period=period, project=project,
                           group=group, above_cap=above)

    return api


def _stream(server: Server, task: str, cursor: str | None, recheck: Callable[[], Principal]):
    """Server-Sent Events: the timeline after the cursor, then each new event, until the task is closed. Each step
    reads the ledger through the thread it runs on (Starlette iterates a sync generator in its thread pool).

    Every poll authenticates the reader again (session still open, token not revoked or expired, `read` scope) and
    applies its cap afresh, so a revoked token's stream ends at the next poll with an UNAUTHENTICATED event."""
    started = time.monotonic()
    while True:
        try:
            who = recheck()
        except ApiError as error:
            body = {"error": {"code": "UNAUTHENTICATED", "message": error.message, "details": None}}
            yield f"event: UNAUTHENTICATED\ndata: {json.dumps(body)}\n\n"
            return
        events, data_class = one_task(server, task)
        for event in views.timeline(events, data_class, who.max_data_class, cursor):
            yield f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            cursor = event["id"]
        if task_state(events) in CLOSED or time.monotonic() - started > SSE_MAX_S:
            return
        time.sleep(SSE_POLL_S)
```

In `core/src/ooat_core/api.py` replace

```python
    app.include_router(login_routes())
    app.include_router(session_routes(), prefix="/api/v1")
    return app
```

with

```python
    app.include_router(login_routes())
    app.include_router(session_routes(), prefix="/api/v1")
    from .endpoints import resource_routes  # endpoints.py builds on this module

    app.include_router(resource_routes(), prefix="/api/v1")
    return app
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest core/tests/test_api.py core/tests/test_api_security.py -q`
Expected: PASS

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/endpoints.py core/src/ooat_core/api.py core/tests/test_api.py
git commit -m "feat(core): REST resources - tasks, timeline and SSE, artifacts, HIL, ratings, connectors, usage (plan 05a)"
```

---

### Task 10: `ooat serve`, `ooat login`, `[serve]`, and the documentation

**Files:**
- Modify: `core/src/ooat_core/config.py` (`[serve]`), `core/src/ooat_core/serve_cli.py` (whole file), `core/src/ooat_core/operator_cli.py`, `core/pyproject.toml` (`uvicorn`)
- Test: `core/tests/test_serve_cli.py`
- Modify: `core/description.md`, `docs/description.md`, `README.md`, `.claude/lessons.md`

**Interfaces:**
- Consumes: `api.create_app`, `api.ServeSettings` (Task 8); `sessions.issue_login_code`, `login_folder` (Task 8);
  `runner_lock.for_ledger` (Task 6); `task_cli._blobs_dir`.
- Produces: `Config.serve: dict` (`operator`, `host`, `port`, `hosts`, `tls_cert`, `tls_key`; TLS paths resolved
  against the config file's folder); `serve_cli.serve_settings(config, host=None, port=None) -> (ServeSettings |
  None, refusal | None)`; `serve_cli.sign_in_link(settings, code) -> str`; commands `ooat serve [--host] [--port]
  [--no-browser]`, `ooat login --operator NAME`.

- [ ] **Step 1: Add the server dependency**

In `core/pyproject.toml` replace `"rfc3339-validator>=0.1.4", "fastapi>=0.143"]` with
`"rfc3339-validator>=0.1.4", "fastapi>=0.143", "uvicorn>=0.54"]` (the ASGI server `ooat serve` runs; plain uvicorn,
pure-Python HTTP, no C extras). Run `python -m pip install -e core`.

- [ ] **Step 2: Write the failing tests**

Create `core/tests/test_serve_cli.py`:

```python
"""`ooat serve`, `ooat login` and the [serve] configuration (design 05 §6, §7); uvicorn is replaced, no socket."""

import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from runtime_fakes import ScriptedModel, decisions, routing_document

from ooat_core.config import load_config, parse_config
from ooat_core.connectors.registry import Registry
from ooat_core.operator_cli import main
from ooat_core.routing import RoutingPolicy
from ooat_core.runner_lock import RunnerLock

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def started(monkeypatch):
    """uvicorn.run replaced: records what it was given and whether the runner lock was held meanwhile."""
    import uvicorn

    calls = []

    def run(app, **options):
        lock = RunnerLock(app.state.server.settings.ledger_url.removeprefix("sqlite:///") + ".runner.lock")
        calls.append({"app": app, **options, "lock_free": lock.acquire()})
        lock.release()
    monkeypatch.setattr(uvicorn, "run", run)
    return calls


def write_config(tmp_path, serve=""):
    path = tmp_path / "ooat.toml"
    path.write_text(f'[ledger]\nurl = "sqlite:///ledger.sqlite"\n\n[serve]\n{serve}', encoding="utf-8")
    return path


def ooat(config, *argv):
    stdout = io.StringIO()
    code = main(["--config", str(config), *argv], stdout=stdout, clock=lambda: datetime.now(timezone.utc),
                registry=Registry([ScriptedModel(), decisions()]), routing=RoutingPolicy(routing_document()))
    return code, stdout.getvalue()


def test_serve_listens_on_loopback_without_an_access_log_and_holds_the_runner_lock(tmp_path, started):
    config = write_config(tmp_path, 'operator = "operator"\n')
    code, out = ooat(config, "serve", "--no-browser")
    assert code == 0
    (call,) = started
    assert call["host"] == "127.0.0.1" and call["port"] == 8765 and call["access_log"] is False
    assert "ssl_certfile" not in call and call["lock_free"] is False  # the runner lock was held while serving
    link = next(word for word in out.split() if "/login#code=" in word)
    assert link.startswith("http://127.0.0.1:8765/login#code=")
    client = TestClient(call["app"], base_url="http://127.0.0.1:8765")
    signed_in = client.post("/api/v1/login", json={"code": link.split("#code=")[1]},
                            headers={"Origin": "http://127.0.0.1:8765"})
    assert signed_in.status_code == 200 and signed_in.json()["operator"] == "operator"
    assert RunnerLock(tmp_path / "ledger.sqlite.runner.lock").acquire()  # released when serving ends


def test_a_non_loopback_host_without_tls_refuses_to_start(tmp_path, started):
    code, out = ooat(write_config(tmp_path), "serve", "--host", "0.0.0.0", "--no-browser")
    assert code == 1 and "tls_cert" in out and started == []


def test_beyond_loopback_with_tls_the_certificate_is_used_and_the_link_names_the_host(tmp_path, started):
    config = write_config(tmp_path, 'host = "0.0.0.0"\nhosts = ["ooat.lan"]\ntls_cert = "cert.pem"\n'
                                    'tls_key = "key.pem"\noperator = "operator"\n')
    code, out = ooat(config, "serve", "--no-browser")
    assert code == 0 and "https://ooat.lan:8765/login#code=" in out
    (call,) = started
    assert call["ssl_certfile"] == (tmp_path / "cert.pem").as_posix() and call["host"] == "0.0.0.0"


def test_serve_refuses_while_another_process_runs_the_tasks(tmp_path, started):
    config = write_config(tmp_path)
    lock = RunnerLock(tmp_path / "ledger.sqlite.runner.lock")
    assert lock.acquire()
    try:
        code, out = ooat(config, "serve", "--no-browser")
    finally:
        lock.release()
    assert code == 1 and "Another process" in out and started == []


def test_login_prints_a_one_time_link_for_the_named_operator(tmp_path):
    code, out = ooat(write_config(tmp_path), "login", "--operator", "second-operator")
    assert code == 0 and "Sign in as second-operator" in out and "http://127.0.0.1:8765/login#code=" in out
    assert len(list((tmp_path / "ooat-login").glob("*.json"))) == 1
    code, out = ooat(write_config(tmp_path), "login", "--operator", "default-on-silence")
    assert code == 1 and "reserved" in out


@pytest.mark.parametrize("serve, message", [
    ({"port": 0}, "port"), ({"host": "a b"}, "host"), ({"hosts": "ooat.lan"}, "hosts"),
    ({"tls_cert": "cert.pem"}, "go together"), ({"password": "x"}, "unknown settings"), ({"operator": " "}, "name"),
])
def test_serve_settings_are_checked(serve, message):
    with pytest.raises(ValueError, match=message):
        parse_config({"serve": serve})


def test_tls_paths_are_resolved_against_the_config_folder(tmp_path):
    config = load_config(write_config(tmp_path, 'tls_cert = "tls/cert.pem"\ntls_key = "tls/key.pem"\n'))
    assert config.serve["tls_cert"] == (tmp_path / "tls" / "cert.pem").as_posix()
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest core/tests/test_serve_cli.py -q`
Expected: FAIL — `argparse` exits with `invalid choice: 'serve'`, and `parse_config({"serve": ...})` raises `unknown config sections: ['serve']` where the test expects the specific message

- [ ] **Step 4: Read `[serve]`**

In `core/src/ooat_core/config.py`:

1. Replace `REGION = re.compile(r"^[a-z]{2}(-[a-z0-9-]+)?$")` with

```python
REGION = re.compile(r"^[a-z]{2}(-[a-z0-9-]+)?$")
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOST = re.compile(rf"^{_LABEL}(?:\.{_LABEL})*$|^[0-9a-fA-F:]{{2,39}}$")  # a DNS name, IPv4 or IPv6 address
```

2. Replace `    gate: dict = field(default_factory=dict)  # [gate] overrides of GateSettings` with

```python
    gate: dict = field(default_factory=dict)  # [gate] overrides of GateSettings
    serve: dict = field(default_factory=dict)  # [serve]: operator, host, port, hosts, tls_cert, tls_key (design 05)
```

3. Replace `    unknown = set(data) - {"ledger", "routing", "connectors", "policy", "gate"}` with
   `    unknown = set(data) - {"ledger", "routing", "connectors", "policy", "gate", "serve"}`.
4. Replace `                  blobs_dir=blobs_dir, gate=dict(gate))` with

```python
                  blobs_dir=blobs_dir, gate=dict(gate), serve=_serve(data))


def _serve(data: dict) -> dict:
    """[serve] of `ooat serve` (design 05 §6). The certificate and key are named by path, never pasted."""
    serve = _table(data, "serve", {"operator", "host", "port", "hosts", "tls_cert", "tls_key"})
    if "operator" in serve and (not isinstance(serve["operator"], str) or not serve["operator"].strip()):
        raise ValueError("serve.operator must be your name")
    if "host" in serve and (not isinstance(serve["host"], str) or not _HOST.match(serve["host"])):
        raise ValueError("serve.host must be an address or a host name, e.g. 127.0.0.1")
    if "port" in serve and not (type(serve["port"]) is int and 1 <= serve["port"] <= 65535):
        raise ValueError("serve.port must be a port number from 1 to 65535")
    hosts = serve.get("hosts", [])
    if not isinstance(hosts, list) or not all(isinstance(h, str) and _HOST.match(h) for h in hosts):
        raise ValueError("serve.hosts must list host names, e.g. [\"ooat.lan\"]")
    for key in ("tls_cert", "tls_key"):
        if key in serve and (not isinstance(serve[key], str) or not serve[key].strip()):
            raise ValueError(f"serve.{key} must be a file path")
    if ("tls_cert" in serve) != ("tls_key" in serve):
        raise ValueError("serve.tls_cert and serve.tls_key go together")
    return dict(serve)
```

5. In `load_config` replace

```python
        config = dataclasses.replace(config, blobs_dir=(Path(path).resolve().parent / blobs).as_posix())
    return config
```

with

```python
        config = dataclasses.replace(config, blobs_dir=(Path(path).resolve().parent / blobs).as_posix())
    tls = {key: (Path(path).resolve().parent / config.serve[key]).as_posix()  # an absolute path stays as written
           for key in ("tls_cert", "tls_key") if key in config.serve}
    if tls:
        config = dataclasses.replace(config, serve={**config.serve, **tls})
    return config
```

- [ ] **Step 5: `ooat serve` and `ooat login`**

Replace the whole of `core/src/ooat_core/serve_cli.py` with:

```python
"""`ooat serve`, `ooat login` and `ooat tokens create | list | revoke` (design 05 §6, §7; ADR 0016).

A token is printed once, at creation, and a sign-in link once, when it is made; nothing else prints or logs either.
"""

import logging
import re
import sqlite3
import webbrowser

from . import runner_lock, tokens
from .catalog import routing_path
from .connectors.registry import Registry
from .ledger import Ledger
from .routing import load_routing
from .sessions import issue_login_code, login_folder
from .task_cli import _blobs_dir

REFUSED = 1
DEFAULT_PORT = 8765
RESPONSIBILITY = """
A token for client or personal data (ADR 0012, ADR 0016). Whatever the token's client reads leaves this machine
and may be stored by its platform, such as a chat service. By answering yes you state that you have a legal basis
and a processing agreement for that. OOAT records your name and today's date with the token.
"""


def add_commands(commands) -> None:
    serve = commands.add_parser("serve", help="the web app and the API on this machine, and the task runner")
    serve.add_argument("--host", help="address to listen on (default 127.0.0.1; any other needs [serve] TLS)")
    serve.add_argument("--port", type=int, help=f"port (default {DEFAULT_PORT})")
    serve.add_argument("--no-browser", dest="no_browser", action="store_true", help="do not open the browser")
    login = commands.add_parser("login", help="print a one-time sign-in link for the web app")
    login.add_argument("--operator", required=True, help="who signs in; recorded on everything they do there")
    group = commands.add_parser("tokens", help="API tokens for bots and scripts")
    actions = group.add_subparsers(dest="action", required=True)
    create = actions.add_parser("create", help="create a token; it is shown once")
    create.add_argument("--operator", required=True, help="the operator the token acts as")
    create.add_argument("--name", required=True, help="what uses it, e.g. telegram")
    create.add_argument("--scopes", required=True, help=f"comma-separated: {','.join(tokens.SCOPES)}")
    create.add_argument("--max-data-class", dest="max_data_class", default="internal", choices=tokens.CAPS,
                        help="the most sensitive data the token may read or write (default internal)")
    create.add_argument("--expires", default=f"{tokens.DEFAULT_DAYS}d", help="days until it expires, e.g. 90d")
    create.add_argument("--responsibility", choices=["yes", "no"],
                        help="take responsibility for client or personal data (asked when such a class is chosen)")
    actions.add_parser("list", help="tokens with their operator, scopes, data class and state")
    revoke = actions.add_parser("revoke", help="revoke a token")
    revoke.add_argument("token")
    revoke.add_argument("--operator", required=True)
    revoke.add_argument("--reason", required=True)


def run(args, config, path, stdin, stdout, clock, ask, registry=None, routing=None) -> int:
    if config is None:
        stdout.write(f"No {path} found: create one with a [ledger] url, or pass --config. Nothing was changed.\n")
        return REFUSED
    if args.command == "serve":
        return _serve(args, config, stdout, clock, registry, routing)
    if args.command == "login":
        return _login(args, config, stdout, clock)
    try:
        ledger = Ledger.open(config.ledger_url)
    except (ValueError, NotImplementedError, sqlite3.Error, OSError) as error:
        stdout.write(f"Cannot open ledger {config.ledger_url}: {error}\n")
        return REFUSED
    try:
        handler = {"create": _create, "list": _list, "revoke": _revoke}[args.action]
        return handler(args, ledger, stdin, stdout, clock, ask)
    except ValueError as error:  # includes SpecValidationError
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    finally:
        ledger.close()


# `ooat serve` and `ooat login` ------------------------------------------------------------------------------------

def serve_settings(config, host: str | None = None, port: int | None = None):
    """(ServeSettings, None) from [serve] and the command line, or (None, why it cannot serve)."""
    from .api import ServeSettings

    serve, blobs = config.serve, _blobs_dir(config)
    if login_folder(config.ledger_url) is None or blobs is None:
        return None, "`ooat serve` needs a ledger file on a local disk ([ledger] url = \"sqlite:///...\").\n"
    settings = ServeSettings(ledger_url=config.ledger_url, blobs_dir=blobs, operator=serve.get("operator"),
                             host=host or serve.get("host", "127.0.0.1"), port=port or serve.get("port", DEFAULT_PORT),
                             hosts=tuple(serve.get("hosts", [])), tls="tls_cert" in serve)
    if not settings.loopback and not settings.tls:  # design 05 §6: beyond loopback only with TLS
        return None, (f"Serving on {settings.host} lets other machines reach OOAT: set [serve] tls_cert and tls_key "
                      "first. Nothing was started.\n")
    return settings, None


def sign_in_link(settings, code: str) -> str:
    """The code goes in the fragment, which the browser never sends to a server."""
    host = settings.hosts[0] if settings.hosts else "127.0.0.1" if settings.loopback else settings.host
    host = f"[{host}]" if ":" in host else host
    return f"{'https' if settings.tls else 'http'}://{host}:{settings.port}/login#code={code}"


def _serve(args, config, stdout, clock, registry, routing) -> int:
    """The API, the sign-in page and the runner until Ctrl+C, holding the runner lock all the while."""
    import uvicorn

    from .api import create_app

    settings, refusal = serve_settings(config, args.host, args.port)
    if refusal:
        stdout.write(refusal)
        return REFUSED
    lock = runner_lock.for_ledger(config.ledger_url)
    if not lock.acquire():
        stdout.write("Another process runs the tasks of this ledger (`ooat serve` or `ooat task run`). "
                     "Nothing was started.\n")
        return REFUSED
    try:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
        app = create_app(settings, config=config, registry=registry or Registry.discover(),
                         routing=routing or load_routing(routing_path()), clock=clock)
        stdout.write(f"OOAT serves {config.ledger_url} on {settings.host}:{settings.port}; the ledger must be on a "
                     "local disk. Stop with Ctrl+C.\n")
        if settings.operator:
            link = sign_in_link(settings, issue_login_code(login_folder(config.ledger_url), settings.operator,
                                                           clock()))
            stdout.write(f"Sign in as {settings.operator} (valid 5 minutes, once): {link}\n")
            if not args.no_browser:
                webbrowser.open(link)
        else:
            stdout.write("Sign in with the link `ooat login --operator <your name>` prints.\n")
        stdout.flush()
        tls = {"ssl_certfile": config.serve["tls_cert"], "ssl_keyfile": config.serve["tls_key"]} if settings.tls \
            else {}
        # No access log: it would record query strings and client addresses; the API logs method, path, status.
        uvicorn.run(app, host=settings.host, port=settings.port, access_log=False, server_header=False,
                    log_level="info", **tls)
        return 0
    finally:
        lock.release()


def _login(args, config, stdout, clock) -> int:
    settings, refusal = serve_settings(config)
    if refusal:
        stdout.write(refusal)
        return REFUSED
    try:
        code = issue_login_code(login_folder(config.ledger_url), args.operator, clock())
    except ValueError as error:
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    stdout.write(f"Sign in as {args.operator.strip()} (valid 5 minutes, once): {sign_in_link(settings, code)}\n")
    return 0


# `ooat tokens` ----------------------------------------------------------------------------------------------------

def _create(args, ledger, stdin, stdout, clock, ask) -> int:
    match = re.fullmatch(r"(\d{1,3})d", args.expires)
    if match is None:
        raise ValueError("--expires is a number of days, e.g. 90d")
    responsible = False
    if args.max_data_class in tokens.RESPONSIBLE_CAPS:
        stdout.write(RESPONSIBILITY)
        answer = args.responsibility or (ask("Do you take this responsibility? (yes/no): ", stdin, stdout) or "")
        if answer.strip().lower() != "yes":
            stdout.write("No token was created.\n")
            return REFUSED
        responsible = True
    secret, event = tokens.issue(ledger, operator=args.operator, name=args.name,
                                 scopes=[s.strip() for s in args.scopes.split(",") if s.strip()],
                                 max_data_class=args.max_data_class, days=int(match.group(1)),
                                 responsibility=responsible, now=clock())
    body = event["body"]
    stdout.write(f"Token {body['token']} for {body['name']}: acts as {body['operator']}, scopes "
                 f"{','.join(body['scopes'])}, data up to {body['max_data_class']}, expires {body['expires']}.\n"
                 f"\n  {secret}\n\n"
                 "It is shown only now: put it in the client's own secret store. OOAT keeps only its SHA-256.\n")
    return 0


def _list(args, ledger, stdin, stdout, clock, ask) -> int:
    known = tokens.tokens(ledger.events(types=tokens.EVENTS))
    if not known:
        stdout.write("No tokens.\n")
    now = clock()
    for token in known.values():
        state = "revoked" if token.revoked else "expired" if token.expires <= now else "active"
        stdout.write(f"{token.id}  {token.name}  [{state}]  operator {token.operator}  scopes "
                     f"{','.join(sorted(token.scopes))}  data up to {token.max_data_class}  expires "
                     f"{token.expires:%Y-%m-%d}\n")
    return 0


def _revoke(args, ledger, stdin, stdout, clock, ask) -> int:
    tokens.revoke(ledger, operator=args.operator, token_id=args.token, reason=args.reason)
    stdout.write(f"{args.token} revoked; it stops working on its next request.\n")
    return 0
```

In `core/src/ooat_core/operator_cli.py` replace the module docstring with

```python
"""`ooat` command line: `ooat connectors list | show | enable | disable`, the task and HIL commands of
task_cli.py (`ooat task ...`, `ooat hil ...`) and serve_cli.py (`ooat serve`, `ooat login`, `ooat tokens ...`)."""
```

and in `main` replace

```python
        if args.command == "tokens":
            config, path, refusal = _config(args)
            if refusal is not None:
                stdout.write(refusal)
                return REFUSED
            return serve_cli.run(args, config, path, stdin, stdout, clock, _ask_or_end)
```

with

```python
        if args.command in ("serve", "login", "tokens"):
            config, path, refusal = _config(args)
            if refusal is not None:
                stdout.write(refusal)
                return REFUSED
            return serve_cli.run(args, config, path, stdin, stdout, clock, _ask_or_end, registry, routing)
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest core/tests/test_serve_cli.py core/tests/test_config.py core/tests/test_tokens.py -q`
Expected: PASS

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Try it by hand (optional, binds 127.0.0.1 only)**

In a scratch folder outside every web root, with `ooat.toml` holding `[ledger] url = "sqlite:///ooat-ledger.sqlite"`
and `[serve] operator = "Your Name"`: run `ooat serve`, open the printed link, check that `/login` says
"Signed in as Your Name", then `curl -s http://127.0.0.1:8765/api/v1/me` answers 401 and Ctrl+C stops the server
(the runner lock file is released: a following `ooat task run --all` runs).

- [ ] **Step 8: Update the documentation**

In `core/description.md`:

1. Replace

```markdown
its `ooat task` / `ooat hil` commands (one worker, acceptance checks, closing, rating). The REST API and teams
(T3+) are not implemented yet.
```

with

```markdown
its `ooat task` / `ooat hil` commands (one worker, acceptance checks, closing, rating), and `ooat serve`: the REST
API with web sessions and operator tokens, and the task runner (design 05a). Teams (T3+) are not implemented yet.
```

2. Replace the two lines

```markdown
- `ledger.py` — `Ledger`: the only write path; validates events (schema, finite numbers, 64-bit token counts, known artifact references, HIL options incl. R3 default "do not act", responses to existing requests) and staged artifact records, writes an event and its artifacts atomically
- `backends/` — `LedgerBackend` protocol and `open_backend(url)`; implemented: SQLite with schema version in `PRAGMA user_version` (ADR 0008)
```

with

```markdown
- `ledger.py` — `Ledger`: the only write path; validates events (schema, finite numbers, 64-bit token counts, known artifact references, HIL options incl. R3 default "do not act", responses to existing requests, an R3 request answered only by its default on silence) and staged artifact records, and writes an event and its artifacts atomically; its checks and the insert run in one write transaction, which also keeps one task per intake key and channel (`DuplicateIntake`)
- `backends/` — `LedgerBackend` protocol and `open_backend(url)`; implemented: SQLite with schema version in `PRAGMA user_version` (ADR 0008), WAL, a 5 s busy timeout and `BEGIN IMMEDIATE` write transactions (`LedgerBusyError` when the lock stays taken)
```

3. Replace the two lines

```markdown
- `operator_cli.py` — the `ooat` command: `ooat connectors list | show | enable | disable`
- `task_cli.py` — `ooat task submit | run [--all] | show | rate` and `ooat hil list | answer`
```

with

```markdown
- `operator_cli.py` — the `ooat` command: `ooat connectors list | show | enable | disable`
- `task_cli.py` — `ooat task submit | run [--all] | show | rate` and `ooat hil list | answer`; while another
  process holds the runner lock (`ooat serve`), `run` refuses and `submit` / `hil answer` only record
- `hil.py` — `answer()`: the operator's HIL_RESPONSE from every channel; refuses R3 (ADR 0016), a late or second
  answer and a closed task's question; `open_requests()`
- `tokens.py` — `issue()`, `revoke()`, `authenticate()`: operator API tokens as `OPERATOR_TOKEN_*` events, the
  SHA-256 only, scopes and a data-class cap (ADR 0016)
- `stats.py` — `usage()`: calls, tokens, metered and shadow cost by role, connector, tier or project; tasks by
  outcome, cost per accepted task, estimate vs. actual; HIL waiting time (design 05 §8)
- `views.py` — the API's task, timeline, HIL and rating views with a reader's data-class cap (stubs above it)
- `runner_lock.py`, `runner.py` — the OS file lock beside the ledger; the runner thread with its FIFO queue rebuilt
  from the ledger, a 60 s tick (defaults on silence, runnable tasks) and a growing pause for paused tasks
- `sessions.py` — one-time sign-in codes (hash-named files in `ooat-login/` beside the ledger) and web sessions
- `api.py` — `create_app()`: the HTTP shell of `ooat serve` (Host, Origin, CSRF, 20 MB limit, sessions and tokens,
  typed errors, security headers, a log of method, path and status); `endpoints.py` — the REST resources
- `serve_cli.py` — `ooat serve`, `ooat login --operator`, `ooat tokens create | list | revoke`
```

4. In the `runtime.py` line replace `` `Runtime.submit()` / `.run()` / `.expire()`: `` with `` `Runtime.submit()` / `.run()` / `.expire()` / `.cancel()`: ``, and in the `rating.py` entry replace `` `rate()`: TASK_RATED with the operator's verdict per`` with `` `rate()`: TASK_RATED (once per task) with the operator's verdict per``.
5. Replace `` `load_routing()`, `SecretResolver`, `connector_admin`, the `ooat` console script.`` with `` `load_routing()`, `SecretResolver`, `connector_admin`, `hil.answer()`, `tokens`, `stats.usage()`, `create_app()`, the `ooat` console script.``

In `docs/description.md`:

1. Replace `` `ooat hil` commands (no REST API and no teams yet).`` with `` `ooat hil` commands, and `ooat serve` with the REST API, sessions, operator tokens and the task runner (no web screens and no teams yet).``
2. Replace

```markdown
- Decision connector `adapters/typesafe-jev`: TypeSafe System One API (Jev), with the economy text tier as
  fallback (ADR 0011)

Chosen by decision (`docs/adr/`), not yet used in code:
- FastAPI and Pydantic v2 for the API
- PostgreSQL (Team) and optional SQL Server ledger backends (ADR 0008)
- Dashboard and TS SDK: TypeScript
```

with

```markdown
- Decision connector `adapters/typesafe-jev`: TypeSafe System One API (Jev), with the economy text tier as
  fallback (ADR 0011)
- REST API: FastAPI (Pydantic v2) on uvicorn, `ooat serve` (design 05a, ADR 0016)

Chosen by decision (`docs/adr/`), not yet used in code:
- PostgreSQL (Team) and optional SQL Server ledger backends (ADR 0008)
- Dashboard: JavaScript with JSDoc types checked by `tsc --noEmit --checkJs`, no build step (ADR 0016); TS SDK:
  TypeScript
```

3. In the Configuration section replace

```markdown
ADR 0015); a changed file stops the connector until it is approved again.
```

with

```markdown
ADR 0015); a changed file stops the connector until it is approved again. `[serve]` holds what `ooat serve` needs
(`operator`, `host`, `port`, `hosts`, `tls_cert`, `tls_key`); bots get operator tokens from `ooat tokens create`,
kept in the ledger as SHA-256 only (ADR 0016). Tests of the API also need `httpx2` from `requirements-dev.txt`.
```
4. Replace `- R3 actions only with a named human approver.` with

```markdown
- R3 actions only with a named human approver bound to something they hold; until that exists every R3 request
  is refused (ADR 0016).
- Every API endpoint is authenticated except the sign-in; a token's data class caps what it reads and writes.
```

In `README.md` replace `` for T0–T2 and the task runtime (`ooat task`, `ooat hil`) exist; the REST API and teams (T3+) do not yet.`` with `` for T0–T2, the task runtime (`ooat task`, `ooat hil`) and `ooat serve` (REST API, sessions, operator tokens) exist; the web screens and teams (T3+) do not yet.`` and, after the code block that ends with `ooat task rate <tsk_id> --operator "Your Name" --accepted yes --value B` and its closing fence, add:

````markdown

`ooat serve` runs the REST API and the task runner on `127.0.0.1:8765` and prints a one-time sign-in link for
`[serve] operator` (`ooat login --operator <name>` prints another). A bot gets its own token, shown once:

```sh
ooat serve
ooat tokens create --operator "Your Name" --name telegram --scopes submit,read,answer,rate
```
````

Append to `.claude/lessons.md`:

```markdown
- FastAPI 0.143 includes routers lazily: `app.routes` holds `_IncludedRouter` objects, not the routes. Tests that
  list every endpoint enumerate each router's own `.routes` (`api.login_routes()`, `session_routes()`,
  `endpoints.resource_routes()`).
- The ledger stamps `ts` with the real time while tests fake the runtime's clock. A test that compares event times
  with the clock (runner backoff, stats periods) starts its fake clock at `datetime.now(timezone.utc)`.
- Starlette 1.x's `TestClient` wants `httpx2` (Pydantic's fork, github.com/pydantic/httpx2); plain `httpx` still works but warns. The test client buffers a whole streamed body, so a test that acts while a Server-Sent Events stream is open drives the stream's generator itself (`endpoints._stream`).
- Opening a SQLite connection runs the ledger's DDL, which needs the write lock: a connection opened while another
  writer holds it fails busy too. `SqliteBackend` maps that, like a busy `BEGIN IMMEDIATE`, to `LedgerBusyError`.
- FastAPI runs sync endpoints in a thread pool and iterates a sync streaming generator there too: the API keeps one
  ledger connection per thread (`threading.local`) and reads through `server.runtime()` at every step.
```

- [ ] **Step 9: Run the whole suite and check line lengths**

Run: `python -m pytest -q`
Expected: PASS (about 127 more tests than before Task 2)

Run: `python -c "import pathlib,sys; bad=[f'{p}:{n}' for p in pathlib.Path('core').rglob('*.py') for n,l in enumerate(p.read_text(encoding='utf-8').splitlines(),1) if len(l)>120 and p.name in {'api.py','endpoints.py','hil.py','tokens.py','runner.py','runner_lock.py','stats.py','views.py','sessions.py','serve_cli.py','test_api.py','test_api_security.py','test_hil.py','test_tokens.py','test_runner.py','test_stats.py','test_views.py','test_serve_cli.py','api_fakes.py'}]; print(bad or 'ok')"`
Expected: `ok`

- [ ] **Step 10: Commit**

```bash
git add core/src/ooat_core/config.py core/src/ooat_core/serve_cli.py core/src/ooat_core/operator_cli.py core/pyproject.toml core/tests/test_serve_cli.py core/description.md docs/description.md README.md .claude/lessons.md
git commit -m "feat(core): ooat serve and ooat login, [serve] settings, docs for 05a"
```

---

## Self-review against the design

| Design | Where |
|---|---|
| §5 endpoints, codes, 20 MB, handlers call the CLI's functions | Task 9 (resources), Task 8 (errors, limit) |
| §5 `Idempotency-Key` → `intake_key`, also after a restart | Task 3 (ledger), Task 4 (`Runtime.submit`), Task 9 (header, restart test) |
| §5 / §6 stub on every read endpoint; the cap on writes (§14) | Task 7 (`views`), Task 9 (`test_content_above_a_tokens_cap_is_a_stub_on_every_read_endpoint`, `test_writes_on_a_task_above_a_tokens_cap_are_refused`) |
| §6 bind, TLS beyond loopback, Host, no CORS, Origin, CSRF, cookie flags, sign-in link | Task 8, Task 10 |
| §6 tokens: 256 bits, shown once, SHA-256, constant time, revoke, events | Task 5, Task 2 |
| §6 HIL identity from the session or token; channel; the allow-list test | Task 4 (`test_only_the_listed_modules_build_a_human_actor`), Task 9 (actor and channel assertions) |
| §6 R3 refused on every channel; §14 R3 everywhere | Task 4 (`hil.answer`, ledger, CLI), Task 9 (web and token) |
| §6 no secrets in the log; security headers | Task 8 (`test_the_log_records_method_path_and_status_only`, headers test) |
| §7 one runner, FIFO, 60 s tick, queue rebuilt on start (§14), runner lock and CLI behaviour | Task 6 |
| §7 SQLite: per-thread connections, WAL, busy timeout, FULL, `BEGIN IMMEDIATE`, 503 | Task 3, Task 8 (`Server.runtime()`), Task 9 (503 test) |
| §8 statistics | Task 7, Task 9 (`GET /stats`) |
| §11 tests: e2e submit → answer → rate, two-writer race, Host/Origin/CSRF/scope, stubs, R3, allow-list | Tasks 3, 4, 8, 9 |
| §12 schema and spec changes; §13 cancel; §14 PyPI in ADR 0016 | Task 1, Task 2, Task 4 |

Not in 05a, by the design's phases: the web screens and `tsc` CI (05b), the Python client and the bridge contract
(05c), the setup wizard (01c), the projection cache (decision 10 above).

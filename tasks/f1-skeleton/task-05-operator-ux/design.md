# Operator experience: `ooat serve`, web app and chat bridge — design

**Epic:** f1-skeleton · **Sub-project:** 05 (with 01c) · **Status:** approved by the owner 2026-10-09
**Spec:** §3 (components, profiles, portability), §8 (lifecycle), §9 (HIL format and rules, security), §10
(dashboard); ADR 0010, 0011, 0012, 0014, 0015; task runtime design (`../task-04-task-runtime/design.md`)

## 1. Intent

The owner (2026-10-05, 2026-10-09): the `ooat` commands are "extremely user-unfriendly". Everyday work (submit,
answer, rate, look at results and artifacts, see costs) must need no command line, must work for the public on
Windows, macOS and Linux, and the owner's own chat bot must be able to send its messages to OOAT instead of calling
an AI CLI directly, so that the only visible change is a usage view: which roles and connectors worked, tokens, cost.

Success: after `pipx install` and one command (`ooat serve`) a new user gets a browser tab that walks through
setup, then submits a task, watches its timeline, opens the document, answers a question with one tap and rates the
task, without typing a flag. An existing chat bot switches to OOAT by replacing its "run the AI CLI" call with
three client calls, and answers `/stats`.

## 2. Options for the operator's surface

| | Local web app (`ooat serve`) | Desktop app (Electron / Tauri) | Terminal UI (Textual) |
|---|---|---|---|
| Install on 3 OSes | already there: Python + any browser | per-OS builds, code signing, notarisation, updater | Python only |
| Markdown, code, diff | native in a browser | native | approximate; no images, poor wrapping |
| Phone, remote | through the chat bridge (§9) | no | SSH only |
| Shares the API with bots | yes, the same REST API | needs the API anyway | no |
| Maintainer cost | one codebase | three release pipelines, larger security surface | small, but a second UI later anyway |

**Recommendation: the local web app.** It is what spec §3 already names ("web app served by `ooat-core`"), it is
the only option that needs no per-OS packaging, and its REST API is the same one the chat bridge and the CLI use:
one API, three thin clients. A desktop wrapper can be added later around the same page without changing anything.

**No build step for the operator.** The page is plain ES modules served as static files from the `ooat-core`
wheel: no Node, no npm, no bundler. Code is JavaScript with JSDoc types checked in CI by `tsc --noEmit --checkJs`,
which keeps type safety without a build (owner decision, §13; a deviation from spec §3's "TypeScript web app", listed in §12). One vendored
library: a Markdown renderer with raw HTML disabled (markdown-it, MIT). UI strings in `en` and `cs` (spec §10).

## 3. One way to do each thing

| Need | The one way | Fallback for scripts / headless machines |
|---|---|---|
| Start | `ooat serve` (opens the browser; first run opens Setup) | `ooat init` in the terminal (01c, same steps) |
| Submit | "New task" box on the inbox, or a chat message | `ooat task submit` |
| Answer a question | the card's buttons (web or chat) | `ooat hil answer` |
| Rate | the rating card | `ooat task rate` |
| Results, artifacts | the task page | `ooat task show` |
| Connectors | Connectors screen: card, consequences, typed confirmation | `ooat connectors` |
| Costs, usage | Usage screen, or `/stats` in chat | — |

Nothing in 05 removes a command. The one change in CLI behaviour: `ooat hil answer` refuses R3 requests (§6).

## 4. Screens

Home answers spec §10's three questions in 10 seconds: what waits for me, what is stuck, what it costs.

```
INBOX                                            today $0.42 · week $3.10 · ● runner idle
┌ New task ────────────────────────────────────────────────────────────────────────────┐
│ What should be done? [______________________________________________] [📎] [Submit] │
│ Done when (one per line, optional) [_________________________]  Project [docs ▾]    │
└──────────────────────────────────────────────────────────────────────────────────────┘
WAITING FOR YOU (2)
 ? Budget: estimate $1.20 > budget $1.00        [Raise to 1.20 ★] [Narrow…] [Do not run]  in 23 h
 ★ Rate: "Release notes 0.3"  CLOSED_DONE $0.08 [Accepted A] [Accepted B] [Not accepted] [Details]
STUCK / EXCEPTIONS (1)
 ⏸ "Summarise ADRs" paused: quota exhausted on prv.openai.subscription_cli, resumes automatically
TASKS                                   state        topology  cost / budget   updated
 Release notes 0.3                       CLOSED_DONE  T2        $0.08 / $1.00   2 min
```
★ marks the recommended option; the default on silence and the deadline are always printed on the card.

```
TASK  Release notes 0.3                         CLOSED_DONE · T2 · $0.08 of $1.00 (estimate $0.10)
TIMELINE (live)                                 RESULT
 10:02 Submitted by Operator (web)                [Document v2 ▾]  [Markdown | Source | Diff v1→v2]
 10:02 Gate: T2 · A1 checkable 0.93 (θ 0.80)    ┌───────────────────────────────────────────┐
 10:03 Attempt 1 → document v1  $0.03           │ # Release notes 0.3                        │
 10:04 ✗ "mentions breaking changes" 0.41→critic│ …rendered Markdown…                        │
 10:05 Attempt 2 → document v2  $0.04           └───────────────────────────────────────────┘
 10:05 ✓ all criteria · closed DONE             Attachments: changelog.txt (untrusted)  [Download]
```
"Live" is the ledger timeline (typed events polled by cursor), and "intermediate results" are the document of
every attempt with its checks. It is not a stream of model tokens or agent conversation, which spec §10 excludes
before F4.

The artifact viewer shows Markdown rendered, any text as source with line numbers, and a diff between two versions
of one artifact (computed by the server with `difflib`). Binary artifacts are offered for download only.

```
RATING  Release notes 0.3          Accepted? [Yes] [No]   Value [A] [B] [C]   Note [__________]
 Decisions OOAT made alone — were they right?
  Gate A1 "criterion 1 checkable": yes (0.93)            [Right] [Wrong]
  Acceptance "mentions breaking changes", attempt 2: met  [Right] [Wrong]
                                                         [Save rating]   [Rate later]
```
Decisions left unmarked stay unrated (as `rating.rate()` allows); marking them is what calibrates θ (ADR 0011).

```
CONNECTORS  prv.anthropic.subscription_cli  ● enabled  public, internal   hooks approved 0
            prv.google.subscription_cli     ○ off                          [Read card and enable]
CARD prv.google.subscription_cli: vendor · country · processing regions · training on inputs · …
  (from the manifest's jurisdiction block; unknown values are shown as "unknown")
  Allow: [x] public [x] internal [ ] client_confidential [ ] personal   Unattended use permitted? [ ]
  Type the connector id to confirm: [____]  [Enable]
```
The card is the one `ooat connectors show` prints; responsibility (ADR 0012) and hook approval (ADR 0015) are the
same steps as in the CLI, with the operator taken from the session, never from a form field.

```
USAGE   period [7 days ▾]   project [all ▾]          spend $3.10 (API $0.40 · subscription shadow $2.70)
 BY ROLE          calls  tokens in/out   cost      BY CONNECTOR                   calls  tokens in/out  cost
  general.worker  12     410k / 38k      $2.60     prv.anthropic.subscription_cli 14     420k / 40k     $2.70
  gate            36     52k / —         $0.002    prv.typesafe.api               36     52k / —        $0.002
  critic           5     61k / 2k        $0.40     prv.anthropic.api               5     61k / 2k       $0.40
 TASKS 12 · accepted 9 · partial 2 · abstained 1 · cost per accepted task $0.34 · estimate vs actual +8 %
 HIL 7 questions · median wait 14 min · defaults applied 1
```

## 5. REST API (05a)

`ooat serve` runs one process: the API (FastAPI, uvicorn), the static page, and the runner (§7). Base path
`/api/v1`, JSON, errors as `{"error": {"code", "message", "details"}}`.

| Endpoint | Purpose | Scope |
|---|---|---|
| `POST /tasks` | `{project, goal, expected_output?, acceptance[], value? | value_usd?, budget_usd?, data_class?, attachments[{name, content_base64}]}` → `202 {task, state}`. Optional `Idempotency-Key` header, stored in `TASK_SUBMITTED.body.intake_key` (§12): a repeated key from the same token returns the existing task, also after a restart. `data_class` defaults to `internal` and may not exceed the token's cap (403 `DATA_CLASS_ABOVE_TOKEN`); the pre-scan can still raise it | `submit` |
| `GET /tasks`, `GET /tasks/{id}` | list (filter `state`, `project`, cursor); detail: state, topology, costs, estimate, artifacts, open questions | `read` |
| `GET /tasks/{id}/events?after=evt_…` | timeline after a cursor; with `Accept: text/event-stream` the same as Server-Sent Events | `read` |
| `GET /artifacts/{ref}` · `GET /artifacts/{ref}/diff?against={ref}` | content (`nosniff`, attachment disposition unless text) · unified diff | `read` |
| `GET /hil` · `POST /hil/{evt}/answer` | open requests with options, recommendation, default, deadline · `{choice?, text?}` | `read` · `answer` |
| `GET /ratings/queue` · `POST /tasks/{id}/rating` | closed unrated tasks with their decisions · `{accepted, value_class, note?, decisions[{event, question, verdict}]}` | `read` · `rate` |
| `GET /connectors`, `GET /connectors/{id}/card`, `POST /connectors/{id}/enable|disable|approve-hooks` | the `ooat connectors` actions | `connectors` |
| `GET /stats?period=&project=&group=role|connector|project|tier` | the Usage figures of §8 | `read` |

Codes: 400 `INVALID`, 401 `UNAUTHENTICATED`, 403 `SCOPE` / `DATA_CLASS_ABOVE_TOKEN` / `R3_NEEDS_BOUND_IDENTITY`, 404,
409 `ALREADY_ANSWERED` / `NOT_CLOSED` / `ALREADY_RATED`, 413 `TOO_LARGE` (20 MB per request), 422
`SPEC_VALIDATION` (the ledger's own errors), 503 `LEDGER_BUSY` (§7). Every `read` endpoint applies the token's
data-class cap and returns the redacted stub of §6 for content above it. Handlers call the same functions the CLI
calls (`Runtime.submit`, `rate`, `connector_admin.*`); the API adds no second rule set.

## 6. Security and identity

- **Bind:** `127.0.0.1` by default. A non-loopback `--host` refuses to start without `[serve] tls_cert` and
  `tls_key`. Every request's `Host` must be an allowed name (`localhost`, `127.0.0.1`, configured names), which
  stops DNS-rebinding pages from reaching the local API. No CORS; unsafe methods must carry a matching `Origin`.
- **Every endpoint is authenticated**, including the static page's data calls; only `/login` is open.
- **Web session:** `ooat serve` prints a one-time login link (code in the URL fragment, posted by the page, valid
  5 minutes, single use) for the operator named in `[serve] operator`; `ooat login --operator NAME` prints one for
  another operator. Whoever holds the terminal is the operator, the same trust as the 04 CLI. The code becomes an
  HttpOnly, SameSite=Strict cookie (Secure under TLS, 12 h) plus a CSRF token for unsafe methods.
- **API tokens** for bots and scripts: `ooat tokens create --operator NAME --name telegram --scopes
  submit,read,answer,rate [--max-data-class internal] [--expires 90d]` prints a 256-bit token once; the ledger keeps
  only its SHA-256, compared in constant time. `ooat tokens revoke`. Sent as `Authorization: Bearer`.
- **HIL identity:** the actor of every human event written through the API (`actor.kind = hil`) is the operator
  bound to the session or token, never a name from the request body; the event records the channel (`web` or the
  token id). A test holds an allow-list of the modules that may build a `hil` actor and fails on any other:
  `Runtime.submit` (`TASK_SUBMITTED` by the operator), `rating.py` (`TASK_RATED`), the HIL answer path
  (`HIL_RESPONSE`, in `task_cli` today), the new cancel action, `connector_admin` (`ADAPTER_ACKNOWLEDGED`,
  `ADAPTER_DISABLED`), the new `ooat tokens` commands (`OPERATOR_TOKEN_ISSUED`, `OPERATOR_TOKEN_REVOKED`), and the
  runtime's `default-on-silence`. The API handlers and the CLI call these modules; they build no actor themselves.
- **R3** (named approver, spec §9): refused everywhere until a bound identity exists: web, tokens and the CLI's
  `ooat hil answer` alike (error `R3_NEEDS_BOUND_IDENTITY`). A web session from `ooat login --operator NAME`
  carries the same self-declared name as the CLI's `--operator`: whoever holds the terminal can claim any name, so
  neither is a named approver. The operator must first be bound to something they hold, such as a passkey
  (WebAuthn) or an OS-account check. For the CLI this changes today's behaviour for R3 requests only; no R3
  request exists in F1, so nothing breaks today. The binding is a precondition for the first R3 gate, not for 05
  (ADR 0016).
- **Data leaving through a chat platform:** a chat service stores messages on its own servers. A token's
  `max_data_class` (default `internal`) caps every read the token can make, not only what it submits. A task's
  class is its gated class (declared, raised by the pre-scan or A10), an artifact's is its own. Content above the
  cap comes back as a stub (`{"redacted": "above this token's data class; open in the web app", "link"}`) in place
  of: the goal and summary in `GET /tasks` and `/tasks/{id}`, event bodies in the timeline and stream, HIL question
  and option text, rating-queue entries, artifacts and diffs, and task titles in stats; ids, states, costs and
  deadlines stay visible. Stats name a project only when it has a task within the cap. Raising a token's cap to
  `client_confidential` or `personal` is the operator's responsibility statement, recorded like ADR 0012. Tests
  cover the stub on each read endpoint.
- **No secrets in the UI or ledger:** the UI shows environment variable names and whether they are set, never
  values; tokens appear once at creation; logs record method, path and status only (no headers, cookies or
  bodies). Headers: CSP `default-src 'self'` without inline script, `frame-ancestors 'none'`,
  `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on the API. Markdown renders with raw HTML off and
  `javascript:` links refused: artifacts derived from untrusted attachments are never trusted markup.
- **Outbound webhooks** are not part of 05; the bridge pulls (§9). When a push notifier is added, it signs
  `timestamp.body` with HMAC-SHA256 and the receiver rejects messages older than 5 minutes.

## 7. Concurrency and the runner

- **One process, one runner.** The runner is a single thread with a FIFO queue: spec §3 sets Solo to one task at a
  time. `POST /tasks` appends `TASK_SUBMITTED` and returns; the runner picks it up. Every 60 s it applies defaults
  on silence (`Runtime.expire`) and resumes paused tasks (`Runtime.runnable`), as ADR 0014 promised for 05.
- **Runner lock:** `ooat serve` holds an OS file lock beside the ledger. While it is held, `ooat task run` refuses
  and points to the web app, and `ooat task submit` only appends, so no task is ever run by two processes.
- **SQLite:** each thread opens its own connection (`check_same_thread` stays on; API handlers run in a thread
  pool). `journal_mode=WAL` (readers never block the writer), `busy_timeout=5000`, `synchronous` left at FULL for
  an append-only audit log. `Ledger.append` runs its checks and the insert inside one `BEGIN IMMEDIATE`
  transaction, so "already answered", artifact versions and the insert are serialised across threads and processes
  (the unique index on HIL responses stays as the last guard). A write still waiting after the timeout returns 503
  `LEDGER_BUSY`. The ledger must be on a local disk (WAL does not work on network shares); setup says so.
- Projections read the whole ledger (as `runnable()` does today); the server caches them by the last `seq`, which
  is enough for Solo volumes. PostgreSQL (01b) replaces this for Team.

## 8. Statistics

Already in every metered event: `adapter`, `tier`, `tokens_in`, `tokens_cached`, `tokens_out`, `quota_units`,
`cost_usd`, `cost_basis` (`exact`, `estimated`, `shadow`), `estimated_usd`, `price_ver`, the actor (agent with
role version, the Gate, the runtime's critic), the task's `project` (`TASK_SUBMITTED`), decision records, HIL
requests and responses with timestamps, `TASK_CLOSED` cost parts, `TASK_RATED`.

New: one module `stats.py`, pure projections over events like `state.py`, grouped by role, connector, tier and
project for a period: calls, tokens, cost split into metered (`exact`, `estimated`) and subscription shadow value
(`shadow`); tasks by outcome, cost per accepted task, estimate vs. actual; HIL questions, median wait from request
to response and defaults applied. "HIL hours" is reported as waiting time: the ledger does not know how long a
human worked on an answer. No schema change; SQL views come with PostgreSQL. Until T3 and the catalog (02), the
role list is short (worker, Gate, critic): the view shows what ran, not what the catalog will hold.

## 9. Chat bridge contract (05c)

A chat bridge is any bot that holds one API token and maps chat actions to the API. OOAT ships a small Python
client in `sdk/python` (standard library only) and this contract; the bot stays the operator's own program.

| Chat action | API |
|---|---|
| A message (with files) in a project's chat | `POST /tasks` with the chat's mapped project, the text as `goal`, lines after a "Done when:" line as `acceptance`, files as attachments, the chat message id as `Idempotency-Key` |
| Progress | follow `GET /tasks/{id}/events` (SSE, or poll by cursor); post one short line per state change |
| A question | inline buttons, one per option, recommended marked, default and deadline in the text; a button calls `POST /hil/{evt}/answer`; a reply to the question message answers with text |
| Result | the final artifact as text (split at the platform's limit) or as a file when long, and a footer: topology, cost, tokens, time |
| Rate | buttons Accepted A / B / C and Not accepted under the result (decisions stay for the web rating card) |
| `/stats` | `GET /stats?period=7d&project=…` formatted as text |

Minimal use in a bot that today calls an AI CLI:

```python
ooat = OoatClient(base_url, token)              # token from the bot's own secret store, never in code
task = ooat.submit(project=chat_project, goal=text, attachments=files, key=message_id)
async for update in ooat.follow(task):           # state lines, questions, the result
    await reply(render(update))                  # the bot keeps its own message format
```

The bot itself must still check that the message comes from its allowed chat or user before calling OOAT: OOAT
trusts the token, the bot vouches for the person.

What does change for a bot that ran a coding CLI in a project folder: an OOAT task in F1 turns text into a
document. It has no tools (no file edits, no commands) and no conversation memory (each message is its own task,
with clarifications inside the task), and every task pays for the Gate and the acceptance checks. The bridge is
therefore best added as one more engine the bot can switch to per chat, next to the direct CLI, until tool
capabilities and sessions exist (owner decision, §13).

## 10. Setup wizard (01c)

The same steps in the browser (first `ooat serve` without a configuration) and in the terminal (`ooat init`):
1. Data folder: the OS user data directory by default (`%APPDATA%\ooat`, `~/Library/Application Support/ooat`,
   `~/.local/share/ooat`); SQLite unless the machine has PostgreSQL and the operator picks it (ADR 0008).
2. Your name (the operator).
3. Connectors found: CLIs on `PATH` and logged in, API key variables set (names only); each opens its card.
4. Chat bridge: optional; creates a token for it and shows it once.
5. Done: the inbox, with a sample task prefilled.

## 11. Phases

| Plan | Content | Depends on |
|---|---|---|
| 05a | `ooat serve`: API, sessions, tokens, runner, runner lock, SQLite threading, `stats.py`, schema additions (§12) | 04, ADR 0016 accepted by the owner |
| 05b | Web app: inbox, task page with timeline and artifact viewer, HIL cards, rating, connectors, usage, `en`/`cs` | 05a |
| 05c | Python client in `sdk/python`, chat bridge contract in `docs/`, a reference bridge test; the private bot's change is done in its own repository | 05a |
| 01c | Setup wizard, browser and terminal | 05a (browser), 01 |

05b and 05c can run in parallel after 05a. Tests stay offline: API through FastAPI's test client on a file
ledger with fake connectors, an end-to-end submit → answer → rate through the API, a two-writer race on one HIL
answer, Host/Origin/CSRF and token-scope refusals, the data-class stub on each read endpoint, R3 refused on
every channel, and the allow-list test for `hil` actors.

## 12. Schema and spec changes (ADR 0016, proposed)

- Event types `OPERATOR_TOKEN_ISSUED` and `OPERATOR_TOKEN_REVOKED` (human actor, `task: null`; body: token id,
  operator, name, scopes, `max_data_class`, `sha256`, `expires`), so who could answer for whom is in the audit log.
  This amends ADR 0003 §3 (only adapter events have `task: null`) and the event schema's null-task conditional to
  admit the two token events.
- Optional `channel` (`cli`, `web`, `token:<id>`) in the bodies of `TASK_SUBMITTED`, `HIL_RESPONSE`, `TASK_RATED`,
  `ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`.
- Optional `TASK_SUBMITTED.body.intake_key` (the client's idempotency key), unique per `(channel, key)` and checked
  inside the same `BEGIN IMMEDIATE` transaction as `Ledger.append`, so two concurrent or retried deliveries of one
  chat message never create two tasks, also across a restart.
- Spec §9: R3 needs an operator identity bound to something the operator holds (passkey/WebAuthn or an OS-account
  check); a self-declared name (CLI `--operator`, `ooat login --operator`) or a token never answers R3. Since F1 has
  no R3 action, the binding is a precondition for the first R3 gate, not part of 05.
- Spec §3: the dashboard is JavaScript with JSDoc types checked by `tsc --noEmit --checkJs`, without a build step,
  instead of a "TypeScript web app" (owner decision, §13).
- Spec §10: a Usage view in F1 ahead of the F2 Economics view.

## 13. Owner decisions (2026-10-09)

The owner approved this design on 2026-10-09 with these answers:
- Dashboard: JavaScript with JSDoc types checked by `tsc --noEmit --checkJs`, no build step.
- Tasks from chat without "Done when:" lines: today's rule A1 stays (one-tap clarify / run as it is / do not run).
- The bridge token's data-class cap is `internal`; client or personal content stays in the web app.
- Web sessions have no data-class cap: the operator sees everything in their own browser on their own machine; caps
  apply to tokens, which leave the machine.
- 05a adds a human `cancel` action (a runtime path ending `CANCELLED`), used by the bot's `/cancel`.
- Token and channel events go into the ledger (ADR 0016, §12).
- The private bot gets OOAT as an additional engine per chat (`/engine ooat`); its direct CLI engines stay for coding
  work.

- Public install: the owner approved publishing `ooat` on PyPI (2026-10-09), so `pipx install ooat` becomes the
  documented install once a release is cut; each release is still published only on the owner's go.

## 14. Review points carried into the 05a plan

- A server bound beyond loopback (`--host`) caps web sessions like tokens, or the operator records a responsibility
  statement for it (ADR 0012 style); the plan picks one.
- A token's data-class cap gates writes too: answering, rating or cancelling a task above the cap is refused with
  `DATA_CLASS_ABOVE_TOKEN`, with a test.
- The owner's PyPI approval is recorded in ADR 0016 (CLAUDE.md gates publishing on the owner); each release still on
  the owner's go.
- The runner's queue is rebuilt from the ledger on start, so tasks from `ooat task submit` and tasks queued before a
  restart are picked up.

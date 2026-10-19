# OOAT — overview (As-is)

## Purpose
OOAT is an open-source framework for multi-agent AI work in which a Topology Gate decides per task whether
a team is worth its cost. The repository currently contains the specification and the OOA Spec v0.2 JSON Schemas with tests;
the starter catalog holds role families, capability names and the first cards (`cap.general.complete_task`,
`cap.general.check_criterion`, `role.general.worker`) with their schemas in `catalog/schemas/` and first eval
cases in `evals/`; `ooat-core` has the ledger foundation, the provider gateway
with model and decision connectors, the Topology Gate for T0–T2 and the task runtime with the `ooat task` and
`ooat hil` commands, and `ooat serve` with the REST API, sessions, operator tokens, the task runner and the web app (no teams yet).

`ooat serve` opens the web app. Its home page is one box like a search field with a project picker (the projects of
`ooat.toml` and those already used, from `GET /projects`; the last one is remembered). The conversation with the
reception runs below it: replies with numbered options and buttons, a link to each task it started, and the task's
report. Then the project's earlier conversations, a folded form for a task with exact criteria, and the inbox's lists
(questions and ratings waiting, tasks paused by a provider failure, all tasks). A conversation has its own page,
read only unless it is open on the web. Memory lists a project's items and the operator's preferences, with add (by
hand, `POST /memory/{scope}`, web session only), edit, pin, done and forget. The app also has a task page
(live timeline, the document of every attempt rendered, as source or as a diff,
attachments, cancel, the rating card; for a task on a project's folders the files OOAT saw change, the diff and
revert behind a confirm step, also for a limit question's `revert` answer), Usage (spend, calls and tokens by role and by connector,
then What it learns from `GET /learning`: acceptance per capability and task type, decision thresholds, the
reception's decisions with the Differently and quick cancels that followed them, memory notes forgotten later, and
the rejected tasks within the reader's cap) and Connectors (the
consequences card, enable with a typed confirmation, disable, hooks). English or Czech. The app is plain
JavaScript served from the `ooat-core` wheel; the operator needs no Node.

The first `ooat serve` sets OOAT up in the user data folder and opens Setup in the browser (data, the operator,
the connectors found, a chat bridge token, a sample task); `ooat init` walks the same steps in the terminal.

Bots use the Python client `ooat-client` (`sdk/python`, standard library only) and its reference chat bridge: a
chat message goes to the reception (or becomes a task, for a bot without it), questions come with buttons, the result
with a rating, `/pamet` shows the project's memory and `/stats` shows usage. The
contract is in `docs/chat-bridge.md`.

A reception in `ooat-core` (design 08, ADR 0018) turns a person's messages into answers, one question, a
confirmation or a task with criteria it writes itself, within a conversation that continues across tasks and with
project memory the operator can forget. It is in the REST API (`/conversations`, `/memory`, `/projects`), the
Python client, `ooat ask`, the web app's home page and the chat bridge. After a Differently with a correction it
may offer a lesson (a lasting preference or fact); the Remember button stores it as the operator's memory item,
never the reception on its own. `evals/reception/` measures it against a message set; `evals/candidates.py` exports
corrections and rejected tasks to a file outside the repository, for the owner to pick cases from
(`evals/reception/cases/`, run with `--min-expected`).

OOAT learns from the ledger without storing what it learns (`learning.py`, plan 09): `p_accept` per capability and
task type is the mean of a Beta distribution whose prior is the card's `prior.p_accept` weighted as 5 ratings (a
justified abstention does not count, a lazy one does), and the Gate records it with the expected utility
`V × p_accept − cost` on its candidate; a task whose expected utility is negative is closed as not worth its cost.
The cards in `catalog/` keep `"observed": {"n": 0}`.

## Technology
In use:
- Core runtime: Python 3.12+ (`core/`), JSON Schema 2020-12 validation (`jsonschema`)
- Ledger backend: SQLite, selected by URL (ADR 0008)
- Model connectors as separate packages in `adapters/`: Claude Code CLI, Codex CLI, Antigravity CLI (`agy`),
  Anthropic Messages API
- Decision connector `adapters/typesafe-jev`: TypeSafe System One API (Jev), with the economy text tier as
  fallback (ADR 0011)
- REST API: FastAPI (Pydantic v2) on uvicorn, `ooat serve` (design 05a, ADR 0016)
- Web app: plain JavaScript ES modules with JSDoc types, checked by TypeScript 6.0.3 (`checkJs`) and tested with
  `node --test` (Node 22, developers and CI only); markdown-it 15.0.2 vendored (plan 05b, ADR 0016)
- Python client and reference chat bridge: `ooat-client` in `sdk/python`, standard library only (plan 05c)

Chosen by decision (`docs/adr/`), not yet used in code:
- PostgreSQL (Team) and optional SQL Server ledger backends (ADR 0008)
- Dashboard: JavaScript with JSDoc types checked by `tsc --noEmit --checkJs`, no build step (ADR 0016); TS SDK:
  TypeScript

## Project structure
- `spec/ooat-specification.md` — normative design, draft v0.2 (sections 1–14)
- `spec/manifesto.md` — rationale for non-technical readers
- `spec/schemas/`, `spec/examples/`, `spec/tests/` — OOA Spec v0.2 JSON Schemas, examples, pytest (see `spec/README.md`)
- `catalog/families/` — `family.base` and 5 abstract families (analyst, builder, reviewer, communicator, orchestrator)
- `catalog/taxonomy.json` — 13 starter domains + `general` fallback; 103 capability names with summary, proposed `impl` and per-domain target
- `catalog/tests/` — schema, family-chain and taxonomy checks
- `core/` — `ooat-core` package: ledger, artifact storage, state projections, provider gateway core (see `core/description.md`)
- `adapters/` — connector packages `ooat-adapter-claude-code`, `ooat-adapter-codex`, `ooat-adapter-anthropic-api`,
  `ooat-adapter-typesafe-jev`, `ooat-adapter-antigravity-cli`
  (each with `description.md`), `integration_tests/` (gateway with the real connectors, no network)
- `catalog/routing.json` — reference routing policy: Anthropic, OpenAI (Codex models), Google (Antigravity models) and TypeSafe (Jev) list prices with source and date, data-class policy
- `sdk/python/` — `ooat-client`: the REST API client and the reference chat bridge (`docs/chat-bridge.md`)
- `evals/` — eval cases of the catalog's cards and the reception's message set runner (`evals/reception/`)
- `dashboard/` — empty
- `docs/adr/` — decision records; `docs/assets/` — images (social preview)
- `.github/` — CI (`tests.yml`: pytest on 3.12 and 3.13), Claude review workflows (`claude-review.yml` automatic on same-repo PRs, `claude.yml` on `@claude` mentions; Opus 5.5, comment-only, advisory per ADR 0007; auth via `CLAUDE_CODE_OAUTH_TOKEN`), issue and PR templates
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` — contribution rules, Contributor Covenant 2.1, private vulnerability reporting
- `tasks/` — open work (To-be), one folder per task

## Configuration
`ooat.toml` is `--config`, else `./ooat.toml`, else the one in OOAT's data folder (`OOAT_HOME`, else the OS user
data folder); setup writes it there and never overwrites one (plan 01c). `ooat.toml` holds
operator preferences (ledger URL, per-tier pins, connector settings, `[policy]` limits on countries
and personal-data regions; `[projects.<slug>]` maps a project to its folders, with `write`, `data_class`, `deny`
and limits, for agents that work on files through OOAT's own tools; secrets only as environment variable names).
A task on such a project runs its worker on the real files, records every call as `WORKSPACE_USED`, and asks at a
limit whether to raise it for the task, continue in a follow-up task, keep the changes or revert them; a closed
task's changes are reverted with `POST /tasks/{id}/revert`, `ooat task revert` or `OoatClient.revert` (the web app
and the chat bridge follow with plan 07c). Config files holding connection strings are not hidden by default: add
them to the project's `deny`, e.g. `deny = ["appsettings*.json", "web.config"]`. Connector enablement is ledger state
(`ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`, ADR 0010), written by `ooat connectors enable | disable` after the
operator has read the connection consequences card; for client or personal data the operator also takes
responsibility there (legal basis, processing agreement, region; ADR 0012), renewed every 12 months. Hook files a
connector's CLI would run are approved with `ooat connectors approve-hooks` (fingerprints on the acknowledgement,
ADR 0015); a changed file stops the connector until it is approved again. `[serve]` holds what `ooat serve` needs
(`operator`, `host`, `port`, `hosts`, `tls_cert`, `tls_key`); bots get operator tokens from `ooat tokens create`,
kept in the ledger as SHA-256 only (ADR 0016). `[reception]` holds the reception's settings (`batch_seconds`,
`silence_hours`, `context_tokens`, `max_answer_usd`, `max_answer_operations`, `theta`; design 08). Tests of the API also need `httpx2` from `requirements-dev.txt`.
Prices and the data-class policy: `catalog/routing.json`. Dev dependencies: `requirements-dev.txt`, then
`pip install -e core -e adapters/claude-code -e adapters/codex -e adapters/anthropic-api -e adapters/typesafe-jev -e adapters/antigravity-cli -e sdk/python`;
run `python -m pytest`
(paths in `pytest.ini`). Tests that spend quota or credit run only with `OOAT_LIVE=1`.

## Security invariants
- No secrets in the repository.
- Ledger append-only; only `ooat-core` writes to it.
- R3 actions only with a named human approver bound to something they hold; until that exists every R3 request
  is refused (ADR 0016).
- Every API endpoint is authenticated except the sign-in; a token's data class caps what it reads and writes.
- Data classes are enforced in the provider gateway, not in prompts.

## Related documentation
- `.claude/lessons.md` — gotchas
- `docs/chat-bridge.md` — the chat bridge contract
- `docs/adr/` — decisions

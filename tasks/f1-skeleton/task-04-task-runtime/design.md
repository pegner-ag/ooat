# Task runtime with Topology Gate and decision tier — design

**Epic:** f1-skeleton · **Sub-project:** 04 · **Status:** design for owner review
**Spec:** `spec/ooat-specification.md` §4 (Topology Gate), §5 (implementation kinds), §6 (decision tier, decision
points, confidence-gated autonomy), §8 (lifecycle), §11 (calibration); ADR 0009, ADR 0010, ADR 0011 (new);
gateway design (`../task-03-provider-gateway/design.md`)

## 1. Intent

What the owner decided (2026-10-01):

- The first end-to-end task flow: submit a task, let the Gate decide, run one worker (T2), check acceptance, close
  the task, rate it.
- The worker turns text into a document (no tools, no changes on the server).
- Tasks and answers go through `ooat` commands now; the REST API and the owner's Telegram bot follow in 05.
- Jev (TypeSafe) decides from the first task, for Gate step A and the data-class guard. The first 5 rated tasks
  calibrate it: from then on each decision point uses its own threshold, recomputed with every rating.

Success: `ooat task submit` with a goal and acceptance criteria produces a closed task whose ledger shows the Gate's
decisions (with Jev's probabilities), the pre-start estimate, the worker's result as an artifact, per-criterion
acceptance checks, and actual cost next to the estimate; `ooat task rate` records the rating and the confirmation
of each Gate decision.

## 2. Scope

| Plan | Content |
|---|---|
| 04a | Decision layer: decision connector contract, Jev connector package, `Gateway.decide()` (routing, metering, estimate, order-swap check), LLM fallback decider, schema changes of ADR 0011 |
| 04b | Topology Gate for T0–T2: step A as one decision batch, data-class guard, pre-start estimate with budget and value checks, clarification flow, calibration thresholds |
| 04c | Task runtime and commands: intake, contract for `cap.general.complete_task`, worker, acceptance checks, abstentions, closing, rating, `ooat task submit | show | rate`, `ooat hil list | answer` |

Out of scope: teams (T3–T5), tools for workers, REST API and Telegram (05), dashboard (05), real catalog beyond the
general worker (02).

## 3. Decision layer (04a)

```python
@dataclass(frozen=True)
class DecisionQuestion:
    type: Literal["noul", "choice", "score"]
    instructions: str
    criteria: dict | list | None = None   # noul: {"true":..,"false":..}; choice: {option: description}; score: levels

@dataclass(frozen=True)
class DecisionRequest:
    state: str                 # the text the questions are about
    questions: dict[str, DecisionQuestion]
    data_class: str            # required, as for model requests
    task: str
    contract: str | None = None

@dataclass(frozen=True)
class DecisionAnswer:
    type: str
    value: float | str         # noul: 0..1; choice: option; score: weighted level
    probabilities: dict[str, float] | None
    confidence: float          # noul: max(p, 1-p)

class DecisionConnector(Protocol):
    kind: Literal["decision"]
    manifest: dict             # tiers {"decision": "<model>"}
    def detect(self) -> Detection: ...
    def decide(self, request: DecisionRequest, secrets) -> DecisionResponse: ...   # answers, tokens, model
```

- The registry accepts `kind == "decision"` next to `"model"`; `Gateway.decide(request)` routes decision connectors
  with the same rules as model connectors: data class, acknowledgement, automation, quota, price, budget, metering,
  `estimated_usd`, secret redaction.
- **Order-swap check** (spec §6): every `choice` question is asked twice with the option order reversed, in the same
  call; the lower confidence of the two is used, and a disagreement sets confidence to 0.
- **Fallback:** when no decision connector can serve the request (none enabled, quota, data class not allowed on
  Jev), the gateway answers the same questions through the `economy` text tier with a JSON-only prompt and parses
  the answers into the same `DecisionAnswer` shape (`confidence` from the model's stated probability). Every
  decision records the engine (connector id) and the model version the provider reported (`jev-1.13.0`, not the
  `jev-latest` alias), because thresholds are calibrated per engine and model version (§4).
- **Jev connector** (`adapters/typesafe-jev`, `prv.typesafe.api`), facts from TypeSafe's API reference
  (https://docs.typesafe.ai/api.md) and model page (https://docs.typesafe.ai/models.md), accessed 2026-10-01:
  `POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer <key>` from `secret_env`, request
  `{state, model: "jev-latest", questions}`, response `{model, answers, usage: {input_tokens, output_tokens}}`;
  a `noul` answer carries only the value, `choice` and `score` carry `probabilities` and `confidence`. Documented
  statuses: 401 invalid key → `UNAVAILABLE`, 422 validation failure → `API_ERROR`, 429 rate limit →
  `QUOTA_EXHAUSTED` (short cool-down), 529 overloaded → `UNAVAILABLE`; any other status → `API_ERROR`. Limits:
  64k tokens per request, 32k for `state` plus the longest question; the connector refuses larger states before
  sending. English is optimised, other languages are "supported but less accurate" (models page): Czech tasks are
  exactly what calibration must measure. Manifest: US processing, allowed data classes `public` and `internal`
  (spec §9 reference policy), jurisdiction facts with source URLs, `verified_on: null` until the operator
  verifies them. Price in `catalog/routing.json`: USD 0.042 per million input tokens, output free (models page).

## 4. Topology Gate for T0–T2 (04b)

One decision batch over the task text (goal, expected output, acceptance criteria, attachment previews):

| Rule | Question | Type | Effect in F1 |
|---|---|---|---|
| A1 | Is each acceptance criterion checkable from the output alone? (no criteria → T0 without asking Jev) | noul per criterion, ids `a1.1`, `a1.2`, … | not checkable → T0, clarifying question |
| A4 | Does each step depend on the previous one? | noul | recorded (limits T3+ later) |
| A5 | How many independent branches? (1, 2, 3+) | choice | recorded |
| A7 | Do branches need the same large context or files? | noul | recorded |
| A10 | Data class of the text; does it contain personal or special-category data? | choice, noul | raises the class; special category without a permitted route → T0 `ABSTAIN_NOT_PERMITTED` |

Deterministic rules, no question: A2 (verified recipe → T1) never fires in F1 because no recipes exist yet; A3
(value below `v_min`, default USD 15) sends the task to T2 without step B. A6, A8, A9 concern T3+ or R2/R3 actions,
which 04 does not have.

- **Autonomy (ADR 0011):** an answer is acted on when its confidence reaches the threshold θ of its key: decision
  point (A1, A4, A5, A7, A10, acceptance), engine and model version. Only R0 and R1 tasks act on decisions alone
  (spec §6); every task in 04 is R0 or R1 because the worker only writes artifacts.
  - Interim θ while a key has fewer than 5 rated decisions: 0.8 for a decision connector (Jev); 1 for the
    text-model fallback, so a model's self-stated probability never acts alone before OOAT has rated it (spec §4
    "not on the vendor's word").
  - θ_computed: the smallest θ on the grid 0.50, 0.51, …, 0.99 for which the rated decisions with confidence ≥ θ
    number at least 5 and their error rate is at most ε (R0: 5 %, R1: 2 %). When no θ qualifies, θ_computed = 1
    and nothing on that key acts alone.
  - From 5 to 19 ratings: θ = max(0.8, θ_computed), recomputed after every rating. The floor stops five samples
    from pushing θ low (spec §11 warns about n = 5); θ_computed can still raise it. From 20 ratings: θ = θ_computed.
  - Ratings of another model version do not count, so a new Jev version starts again at the interim θ.
  - Below θ the safer outcome applies (A1: ask; A10: keep the declared class, or the higher one if detected).
- **The data class is never lowered** below the class the operator declared; detection can only raise it.
- **What reaches Jev before A10 has run.** A10 is routed by the declared class, so undeclared personal data in an
  `internal` task would reach a US processor before detection could raise the class. Two measures:
  1. A local deterministic pre-scan runs first, before anything leaves the machine: e-mail addresses, phone
     numbers, IBANs, payment card numbers (Luhn) and Czech/Slovak birth numbers (format plus checksum). A hit raises
     the class to `personal` before any routing, so Jev is not used for that task unless the operator enabled it
     for `personal`.
  2. Residual risk, stated in the design and in `ooat task submit --help`: personal data the pre-scan cannot
     recognise (names, free-text health details) is sent under the declared class. The declared class is the
     operator's statement (spec §9); an operator who submits such texts declares `personal` and Jev is then not
     used unless enabled for it.
- **Pre-start estimate:** `Gateway.estimate()` for the worker contract (workhorse tier) plus the acceptance
  checks. Estimate above the task budget → `HIL_REQUEST` "raise budget to X / narrow scope / do not run" (default on
  silence: do not run). Estimate above the task value → T0 (value classes map to USD in `ooat.toml`, defaults
  A = 1000, B = 300, C = 50).
- `TOPOLOGY_DECIDED` records the topology, rules applied, the candidates with estimates, and every decision
  (question id, engine, model version, answer, confidence, threshold used).
- **Clarification:** T0 by A1 issues a blocking `HIL_REQUEST` with the question; the `HIL_RESPONSE` text is the
  clarification itself (no extra event), the task returns to `SUBMITTED` (ADR 0009) and the Gate runs again with
  the task text plus every clarification so far. At most 3 clarifying questions per task (spec A1, ADR 0009): if
  the Gate would ask a fourth, the task closes as `CLOSED_ABSTAINED` with `ABSTAIN_UNABLE` and `missing` naming
  the criteria that are still not checkable.

## 5. Task runtime and commands (04c)

- **Catalog:** the first real cards. `role.general.worker` (family `analyst`, no new family) holds
  `cap.general.complete_task` (impl `llm`, tier `workhorse`; acceptance: output non-empty, then one `decision`
  check per task criterion through `cap.general.check_criterion`, impl `decision`, tier `decision`, as the
  capability schema requires).
- **Intake:** `ooat task submit --project P --goal "…" [--expected-output "…"] --acceptance "…" (repeatable)
  [--value A|B|C | --value-usd N] [--budget USD] [--data-class C] [--file PATH (repeatable)]`. Files become
  `untrusted` artifacts of the task. Default data class `internal`, default budget from `ooat.toml`.
- **Run:** in the Solo profile `submit` runs the task in the foreground: Gate → contract → worker → acceptance →
  close. `ooat task run <id>` resumes a task after a HIL answer.
- **Worker (T2):** a stable prompt prefix (family rules → role → contract) plus the task; artifacts by reference
  with previews of at most 6,000 characters. The model answers either with the deliverable or with an abstention
  in a fixed JSON form (`{"abstain": "UNKNOWN", "reason": "…", "missing": "…", "confidence": 0.x}`) → `ABSTAIN`.
- **Acceptance:** deterministic checks first (non-empty, size limit), then one Jev `noul` per criterion on the
  output ("does the output meet: …?"). An answer below θ is not a pass: per spec §6 the criterion goes to the LLM
  critic (workhorse tier, JSON verdict with reason); a critic that is also unsure counts the criterion as unmet, so
  an uncertain answer can never produce `DONE`. When any input of the task is `untrusted` (an attached file), the
  output may carry text written to steer a checker, so a "met" answer never passes alone: the critic confirms it.
  Each criterion's decision is recorded in its `GATE_PASSED` / `GATE_FAILED` event (`criteria[].decision`), so
  acceptance decisions are rated and calibrated like Gate decisions. All met → `RESULT DONE`; otherwise one retry with the failed criteria as
  feedback (`max_attempts` 2); still failing → `RESULT PARTIAL` with the unmet criteria as `remaining`, or
  `ABSTAIN_UNABLE` when nothing usable came back. Every check is a `GATE_PASSED` / `GATE_FAILED` event.
- **Closing:** `TASK_CLOSED` with the four cost parts (contracts, gate, orchestrator = 0 in T2, critic) and the
  final artifact; `ooat task show <id>` prints the timeline, costs, estimate vs. actual and the artifact path.
- **Rating:** `ooat task rate <id> --accepted yes|no --value A|B|C [--note …]` asks to confirm or correct each
  decision of the task, Gate and acceptance, every Gate run and every attempt (one word each); stored in
  `TASK_RATED` (ADR 0011) and used for the thresholds of §4.
- **HIL:** `ooat hil list` (open requests with deadline, recommendation, default) and
  `ooat hil answer <evt> --choice X | --text "…"`. The answering human is the `--operator` named on the command
  line. Local `ooat` commands are trusted as the operator's own hand (whoever can run them can also edit the
  ledger file); remote identity (REST, Telegram) is verified in 05. Only these commands append `actor.kind = hil`
  events; the worker and the Gate cannot. The `--operator` name is self-declared: acceptable while 04 has no R2/R3
  action, and to be revisited before any R3 gate accepts a local answer (spec §9: named human approver).
- **Concurrency:** one task runs at a time in the foreground; the SQLite threading model for concurrent requests
  moves to 05 together with the REST intake.

## 6. Schema changes (ADR 0011)

- `TASK_SUBMITTED.body.project` (optional, `^[a-z0-9][a-z0-9_-]*$`).
- Decision record `{question, engine, model, answer, confidence, threshold}` in
  `TOPOLOGY_DECIDED.body.decisions[]` (Gate) and in `GATE_PASSED` / `GATE_FAILED` `body.criteria[].decision`
  (acceptance).
- `TASK_RATED.body.decisions`: list of `{event, question, verdict: confirmed | corrected, value}`. `event` is the
  event that holds the decision record, so a question asked again after a clarification or in a retry is rated
  separately; `value` (the correct answer: option, 0/1 or level) is required when corrected.
- Provider manifests: tier `decision` already exists in `common.schema.json`; connector `kind` stays a code
  attribute.

## 7. Errors and safety

- Gate and acceptance never fail a task silently: a decision error falls back (§3); a fallback error makes the
  Gate ask the operator (A1) or keep the safer outcome (A10).
- R2 and R3 actions do not exist in 04 (the worker writes only artifacts); nothing is sent or published.
- Attachments are `untrusted`: the worker sees them as data, never as instructions; no tools exist to act on them.

## 8. Testing

- Fake decision connector and fake model connector; the whole flow runs offline in tests.
- Jev connector parsing tested on documented response shapes; live tests (`OOAT_LIVE=1`) cost fractions of a cent.
- An end-to-end test: submit → Gate → worker → acceptance → close → rate, all through `ooat` commands on a file ledger.

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
  decision records which engine answered.
- **Jev connector** (`adapters/typesafe-jev`, `prv.typesafe.api`): `POST https://api.typesafe.ai/v1/systemone`,
  `Authorization: Bearer <key>` from `secret_env`, model `jev-latest`; 401 → `UNAVAILABLE`, 422 → `API_ERROR`,
  429 → `QUOTA_EXHAUSTED`, 529 → `UNAVAILABLE`. Manifest: US processing (data classes `public`, `internal`),
  jurisdiction facts from the spec with their sources, `verified_on: null` until the operator verifies them.
  Price in `catalog/routing.json` with source and date: spec §6 states USD 0.042 per million input tokens; the
  output price is taken from TypeSafe's published list when the plan is written, or left unknown (estimates then
  use the input price only and say so).

## 4. Topology Gate for T0–T2 (04b)

One decision batch over the task text (goal, expected output, acceptance criteria, attachment previews):

| Rule | Question | Type | Effect in F1 |
|---|---|---|---|
| A1 | Is each acceptance criterion checkable from the output alone? (no criteria → T0 without asking Jev) | noul per criterion | not checkable → T0, clarifying question |
| A4 | Does each step depend on the previous one? | noul | recorded (limits T3+ later) |
| A5 | How many independent branches? (1, 2, 3+) | choice | recorded |
| A7 | Do branches need the same large context or files? | noul | recorded |
| A10 | Data class of the text; does it contain personal or special-category data? | choice, noul | raises the class; special category without a permitted route → T0 `ABSTAIN_NOT_PERMITTED` |

Deterministic rules, no question: A2 (verified recipe → T1) never fires in F1 because no recipes exist yet; A3
(value below `v_min`, default USD 15) sends the task to T2 without step B. A6, A8, A9 concern T3+ or R2/R3 actions,
which 04 does not have.

- **Autonomy (ADR 0011):** Jev's answer is acted on when its confidence reaches the decision point's threshold:
  0.8 until 5 rated tasks exist for that point, then the threshold from spec §6 computed on the rated history
  (`min θ with error rate ≤ ε`, ε = 5 % for R0) and recomputed after every rating. Below the threshold the safer
  outcome applies (A1: ask; A10: keep the declared class, or the higher one if Jev detected it).
- **The data class is never lowered** below the class the operator declared; Jev can only raise it.
- **Pre-start estimate:** `Gateway.estimate()` for the worker contract (workhorse tier) plus the acceptance
  checks. Estimate above the task budget → `HIL_REQUEST` "raise budget to X / narrow scope / do not run" (default on
  silence: do not run). Estimate above the task value → T0 (value classes map to USD in `ooat.toml`, defaults
  A = 1000, B = 300, C = 50).
- `TOPOLOGY_DECIDED` records the topology, rules applied, the candidates with estimates, and every decision
  (question id, engine, answer, confidence, threshold used).
- **Clarification:** T0 by A1 issues a blocking `HIL_REQUEST` with the question; the answer's text is appended to
  the task as a `DECISION` event, the task returns to `SUBMITTED` (ADR 0009) and the Gate runs again.

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
  output ("does the output meet: …?"). All met → `RESULT DONE`; otherwise one retry with the failed criteria as
  feedback (`max_attempts` 2); still failing → `RESULT PARTIAL` with the unmet criteria as `remaining`, or
  `ABSTAIN_UNABLE` when nothing usable came back. Every check is a `GATE_PASSED` / `GATE_FAILED` event.
- **Closing:** `TASK_CLOSED` with the four cost parts (contracts, gate, orchestrator = 0 in T2, critic = 0) and the
  final artifact; `ooat task show <id>` prints the timeline, costs, estimate vs. actual and the artifact path.
- **Rating:** `ooat task rate <id> --accepted yes|no --value A|B|C [--note …]` asks to confirm or correct each Gate
  decision of the task (one word each); stored in `TASK_RATED` (ADR 0011) and used for the thresholds of §4.
- **HIL:** `ooat hil list` (open requests with deadline, recommendation, default) and
  `ooat hil answer <evt> --choice X | --text "…"`. The answering human is the `--operator` named on the command
  line. Local `ooat` commands are trusted as the operator's own hand (whoever can run them can also edit the
  ledger file); remote identity (REST, Telegram) is verified in 05. Only these commands append `actor.kind = hil`
  events; the worker and the Gate cannot.
- **Concurrency:** one task runs at a time in the foreground; the SQLite threading model for concurrent requests
  moves to 05 together with the REST intake.

## 6. Schema changes (ADR 0011)

- `TASK_SUBMITTED.body.project` (optional, `^[a-z0-9][a-z0-9_-]*$`).
- `TOPOLOGY_DECIDED.body.decisions`: list of `{question, engine, answer, confidence, threshold}`.
- `TASK_RATED.body.decisions`: map question id → `confirmed` | `corrected`.
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

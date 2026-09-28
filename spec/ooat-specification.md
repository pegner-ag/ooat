# OOAT: Object-Oriented Agent Team, open framework specification

Sep 28, 2026 · @Martin Pegner

## 1. Purpose, goals and principles

OOAT is an open, vendor-neutral framework in which every task first passes an economic decision on whether a team of agents is worth its cost. Only then is a team assembled from a catalog of typed capabilities, each with a contract, a price and the right to say “I don't know”. The default path is one agent; a team has to earn its cost.

### What is new

The parts exist separately: MetaGPT (roles and SOPs), CrewAI (hierarchical manager), A2A (Agent Card), NOOA (typed contracts), Claude Code agent teams (shared task list). No project combines them with these seven properties:

1. **Topology Gate as an economic decision.** Before every task the expected value and cost of each topology, from “do not run” to a full team, are computed; the cheapest one that meets the target quality wins.
2. **A role is a contract with a price tag.** Every capability carries typed input and output, acceptance criteria, a model tier and a measured cost. No persona text.
3. **Abstention is a typed, valued outcome.** UNKNOWN, INCAPABLE, UNABLE, OVER\_BUDGET and NOT\_PERMITTED are valid results with a stated reason. A silent error is penalised more than admitted ignorance.
4. **Code versus model split per capability.** Each capability is deterministic (code, test, validation), a typed decision (a System One model such as Jev choosing among options declared in advance, with calibrated probabilities), or LLM-implemented (“the three dots”). An auditor always sees where a person decided, where a decision model chose among declared options, and where a generative model wrote freely.
5. **A learning price list.** Actual cost, acceptance rate and abstention rate flow back into the catalog and sharpen the next Gate decision.
6. **The meeting point is a ledger, not a chat.** Typed events with references to artifacts; debate only as a structured objection with a round budget.
7. **Provider-neutral, including subscriptions.** Metered APIs and flat-rate subscriptions (Anthropic, OpenAI, Google Gemini and others) are priced on one scale, so the Gate can compare them.

### Object orientation in OOAT

OOAT applies object orientation at the level of contracts, following Alan Kay's original emphasis on hidden implementation and communication by messages rather than on class hierarchies. It is not a Python class harness: NVIDIA's NOOA is one possible runtime behind a capability, not the model OOAT copies.

| OO concept | OOAT construct |
| --- | --- |
| Interface | Capability contract: JSON Schema input and output, acceptance criteria |
| Encapsulation | Consumers see the contract and the cost card, never the prompt, model or provider behind it |
| Message passing | Agents interact only through typed ledger events that reference artifacts |
| Inheritance | Role families pass rules, permissions and gates down to roles; roles may only narrow them |
| Polymorphism | Any implementation that satisfies a contract is interchangeable: deterministic code, any LLM provider, a NOOA class, or a human |
| Object identity and state | Agent instances, contracts and artifacts have stable IDs; state is reconstructed from events |

### Measurable goals (hypotheses, validated in F2)

| Goal | Metric | Target |
| --- | --- | --- |
| Lower cost of finished work | Cost per accepted task vs. single-agent baseline | ≤ 1.0× across the task mix, ≤ 2.0× for tasks routed to a team |
| Fewer human interventions | Unplanned HIL interventions per 10 tasks | ≥ 40 % reduction vs. baseline |
| Right topology chosen | Share of tasks where retrospective analysis confirms the Gate | ≥ 80 % |
| Honest abstention | Justified abstentions; silent errors | ≥ 70 % justified; silent errors ≤ 5 % |
| Budget discipline | Tasks exceeding approved budget | ≤ 5 %, always with escalation |

Targets are proposals, not commitments; F2 replaces them with measured baselines.

### Out of scope

Model training or fine-tuning; autonomous production actions without a gate; a hosted SaaS offering (the project ships software and a specification, not a service); A2A federation between organisations before F4.

### Design principles

1. One agent is the default; a team is an exception that must justify its cost.
2. Contract before persona: types, acceptance, budget, permissions.
3. Deterministic checks wherever code can decide; an LLM critic is the second line.
4. Artifacts are passed by reference, not copied into context.
5. Structured event IDs instead of free text.
6. Baseline before activation: no role or routing change goes live without an eval run.
7. “I don't know” is a result, not a failure. Unadmitted uncertainty is the failure.
8. Every irreversible action has a named approver.
9. Runs on an ordinary CPU server or laptop. GPUs and local models are optional.

### Distribution and language

OOAT is published as open source for anyone who wants to work with multiple agents reliably. The specification, schemas, code and documentation are in English. Tasks, artifacts and free-text fields are in the user's language; event types, reason codes and schema keys stay in English so that ledgers are comparable across installations. Proposed licence: Apache 2.0 (explicit patent grant); see open questions.

## 2. Terminology and domain model

The basic unit is the capability, not the agent. A role is a named bundle of capabilities; an agent is a running instance of a role for one task.

| Entity | Definition | Lives in | Key |
| --- | --- | --- | --- |
| Capability | One typed operation: input and output schema, acceptance, impl `deterministic` or `llm`, tier, cost card | `catalog/capabilities/*.json` | `cap.<domain>.<verb>_<object>` |
| Role | Bundle of capabilities + permissions + budget + gates; inherits from a family | `catalog/roles/*.json` | `role.<family>.<name>` |
| Role family | Abstract ancestor (e.g. `analyst-base`, `reviewer-base`) with shared rules | `catalog/families/*.json` | `family.<name>` |
| Provider adapter | Declared access to one model source: API or subscription, metering, terms, data policy | `providers/*.json` | `prv.<vendor>.<access>` |
| Agent instance | A role running for one Task with its own context and budget | runtime, row in store | `agt_<ulid>` |
| Task | A request with goal, acceptance criteria, budget, risk class and working language | store | `tsk_<ulid>` |
| Contract | Instance of a capability contract for one Task: input references, expected output, budget, deadline | store | `ctr_<ulid>` |
| Artifact | Versioned output (document, code, schema, dataset) with type, classification and hash | artifact store | `art_<ulid>@v<n>` |
| Event | Immutable ledger record: type, actor, references, cost | append-only table | `evt_<ulid>` |
| Gate | Checkpoint: deterministic, critic or HIL | defined in role, instances in store | `gate.<type>.<name>` |
| Topology | How a task is executed (T0 to T5, section 4) | Task attribute | `T0`…`T5` |
| Tier | Abstract model class, mapped to concrete models and providers by routing policy | `catalog/routing.json` | `local`, `economy`, `workhorse`, `frontier` |

A capability's `impl` is one of `deterministic`, `decision` or `llm` (section 5). Tiers include a separate `decision` tier for System One models, which return typed choices, scores and truth values instead of text (section 6).

### Relationships

- A Task has exactly one Topology and 1 to N Contracts.
- A Contract references exactly one Capability and is assigned to exactly one Agent instance.
- An Agent instance is created from a Role; a Role inherits from a Role family (single inheritance, max. depth 3).
- An Agent instance calls models only through Provider adapters selected by the routing policy.
- Every state change of a Task or Contract is an Event; state is never overwritten without one.
- An Artifact is created only as a Contract output or as HIL input; it never has anonymous provenance.

### Contract outcomes

| Outcome | Meaning | Next step |
| --- | --- | --- |
| `DONE` | Output meets acceptance | continue |
| `PARTIAL` | Part of the output is done, the remainder is named | orchestrator decides |
| `ABSTAIN_UNKNOWN` | Required information is missing and cannot be obtained with available tools | ask HIL or another source |
| `ABSTAIN_INCAPABLE` | The capability does not cover this kind of task | re-staff with another role |
| `ABSTAIN_UNABLE` | Attempted; acceptance repeatedly not met | tier escalation or HIL |
| `ABSTAIN_BUDGET` | Completion would exceed the budget | HIL approves more budget or narrows scope |
| `ABSTAIN_NOT_PERMITTED` | Data policy or permissions forbid the only viable route (e.g. special-category data with no permitted model) | HIL decides or task closes |
| `FAILED` | Technical error (tool, timeout, API, quota) | retry per policy |

An abstention must carry `reason` (max. 300 characters, in the task language), `missing` (exactly what is missing) and `confidence` (0 to 1). An abstention without these fields is validated as `FAILED`.

## 3. Architecture and deployment profiles

The specification is language-neutral (JSON Schema plus event types); the reference implementation is a Python core with Python and TypeScript SDKs and a web dashboard. Nothing in the architecture assumes a particular server, cloud, orchestration tool or GPU.

&#91;embedded content: OOAT reference architecture · 9 components\]

Orchestrator and workers only propose and return results. Only `ooat-core` writes to the ledger, and every model call goes through the provider gateway, where it is metered.

### What the project publishes

| Deliverable | Language | Purpose |
| --- | --- | --- |
| OOA Spec | JSON Schema 2020-12 + Markdown | Normative: capability, role, family, provider, contract, event, routing schemas and semantics |
| `ooat-core` | Python 3.12+ | Reference runtime: Topology Gate, dispatcher, contracts, budgets, state machine |
| `ooat-sdk` (Python, TypeScript) | Python, TypeScript | Define capabilities and deterministic checks, submit tasks, read the ledger |
| `ooat-cli` | Python | Run tasks, validate and resolve the catalog, run evals |
| Dashboard | TypeScript web app | HIL queue, exceptions, economics, calibration |
| Starter catalog | JSON | 13 families, \~100 capability stubs, eval set templates |
| Adapters | Python | Providers (API and subscription), stores, notifiers (e-mail, Slack, Microsoft Teams, messaging bots, webhooks) |
| Integrations (optional) | various | Claude Code plugin, MCP server exposing OOAT as tools, A2A Agent Cards (F4) |

Python for the core because most provider and agent SDKs ship there first; TypeScript for the UI and for teams building on Node. A Claude Code skill or plugin is a thin client of the framework, not the framework itself.

### Components

| Component | Responsibility | Default | Alternatives |
| --- | --- | --- | --- |
| Intake | Accept tasks | REST API + CLI | Notifier bots, webhooks, workflow tools (n8n, Make) |
| `ooat-core` | Gate, dispatcher, contracts, budget enforcement, state machine | Python, FastAPI, Pydantic v2 | none: single write path by design |
| Orchestrator (LLM) | Decomposition, contract drafting, synthesis | `frontier` tier worker | any provider meeting the tier |
| Agent workers | Run agent instances against contracts | Process per instance; Claude Agent SDK runtime in F1 | OpenAI Agents SDK, subscription CLI runner, NOOA (F4 pilot) |
| Provider gateway | Tier → provider mapping, metering, quotas, data-policy enforcement | Own thin layer over adapters | LiteLLM as backend for metered APIs |
| Store (ledger + state) | Append-only events, materialised state, costs | SQLite (Solo) | Postgres (Team) |
| Artifact store | Versioned, hash-addressed artifacts | Local filesystem; git for code | S3-compatible object storage |
| Catalog | Capabilities, roles, families, routing, providers | JSON in git, validated in CI | mirrored into the store at runtime |
| Role index | Top-k retrieval for the dispatcher | SQLite FTS5 + sqlite-vec, hybrid BM25 + vector | Postgres + pgvector |
| Sandbox | Isolation of generated code and tools | Container per contract (Docker or Podman) | no container runtime → `code_exec` capabilities disabled |
| Dashboard | Exceptions, HIL queue, economics | Web app served by `ooat-core` | read-only API for other UIs |
| Eval runner | Regression tests for capabilities and the Gate | pytest + LLM judge | CI or nightly |

### Deployment profiles

| Profile | For | Store | Isolation | Hardware |
| --- | --- | --- | --- | --- |
| Solo | One person, one machine | SQLite, filesystem | Docker optional | Ordinary CPU machine, no GPU; proposed minimum 4 vCPU, 8 GB RAM |
| Team | Small team, shared server | Postgres, S3-compatible | Docker required | CPU server |
| Scaled | Many concurrent tasks | Postgres, object storage | Kubernetes | after F4, out of scope before |

The reference development instance is a Solo installation on an ordinary CPU server without a GPU. Anything such a machine cannot do, such as running local models, must remain optional in the framework.

### Non-functional requirements

- **Idempotence:** every Contract can be re-run from the same references; workers write results only through `ooat-core`.
- **Recoverable runs:** state is rebuilt from the ledger; a crashed worker restarts a Contract, not a Task.
- **Traceability:** from any artifact one can reach its Contract, provider, model, role version, cost and the gates it passed.
- **Version pinning:** a running Task finishes on the catalog version it started with.
- **Secrets:** API keys and subscription sessions live only in the gateway; never in agent context or artifacts.
- **Capacity targets:** Solo 1 concurrent Task, max. 5 agent instances; Team 3 Tasks, 15 instances.
- **Portability:** Linux, macOS and Windows for Solo; containers for Team.

## 4. Topology Gate: when a team and when one agent

The Topology Gate picks, for every task, the cheapest topology that meets the target quality and records the decision together with the rejected alternatives. The most expensive input is usually human attention, not tokens, so the Gate optimises both together.

### Topologies

| Code | Topology | When | Typical cost vs. T2 |
| --- | --- | --- | --- |
| T0 | Do not run: ask back or decline | Goal or acceptance missing; value below minimum cost; out of scope; no permitted route for the data | \~0.05× |
| T1 | Deterministic recipe, no LLM | A verified script or workflow exists for this task type | \~0× tokens |
| T2 | One general-purpose agent for the task type | Default; sequential work; low value | 1.0× |
| T3 | One agent + critic + deterministic gates | Higher risk or strict acceptance, work stays sequential | 1.3 to 1.6× |
| T4 | Orchestrator + parallel workers, no peer communication | ≥ 3 truly independent branches, or volume exceeds one context | 2 to 4× |
| T5 | Team with meeting point and objections | Branches must exchange intermediate results or resolve competing hypotheses | 3 to 6× |

The multipliers are cold-start priors anchored in Anthropic's measurements (agent \~4× chat, multi-agent \~15× chat, i.e. \~3.75× an agent). From F2 onward, measured values from the ledger replace them.

&#91;embedded content: Topology Gate decision flow · 3 filters, step A, step B\]

Three cheap filters settle simple tasks without any calculation; the economic model runs only when more than one topology is plausible.

### Step A: hard rules (deterministic, optionally an `economy` classifier)

| # | Rule | Effect | Basis |
| --- | --- | --- | --- |
| A1 | Goal, output or acceptance criterion missing | T0: max. 3 clarifying questions to HIL | MAST: 41.8 % of failures are specification issues |
| A2 | A verified recipe exists for the task type | T1 | practice |
| A3 | Task value V below `v_min` (default USD 15) | T2 without further calculation | the Gate must not cost more than it saves |
| A4 | The task is a sequential chain (each step depends on the previous one) | at most T3 | Google/MIT: −39 to −70 % on sequential tasks |
| A5 | Fewer than 3 independent branches | at most T3 | Claude Code docs, Anthropic |
| A6 | Historical acceptance for the task class: T2 ≥ 45 % and T3 ≥ 75 % | at most T3 | Google/MIT: saturation around 45 % |
| A7 | Branches need the same large context or edit the same files | at most T3 | Cognition: conflicting implicit decisions |
| A8 | Irreversible action, external communication, production data | at least T3 + HIL gate | AI4DataLeaders essay |
| A9 | Many tools (> 16) that cannot be split across branches | prefer T2/T3 | Google/MIT: tool-coordination trade-off |
| A10 | Input classified `special_category` and no permitted route (no local tier, redaction not verifiable) | T0 with `ABSTAIN_NOT_PERMITTED` | data policy, section 9 |

Where a `decision` tier is available, the judgement rules (A1, A4, A5, A7, A9, A10) run as one batch of typed questions against the task state: Noul for “is the acceptance criterion missing?”, Choice for the dependency structure, Score for decomposability. At Jev's list price a 5,000-token task state costs about USD 0.0002 for the whole step, so the Gate can run on every task, including those below `v_min`. Without a decision tier, step A uses the `economy` LLM tier through a structured-decision wrapper. Either way, the calibrated probabilities become Gate inputs only after OOAT's own calibration (section 11), not on the vendor's word.

### Step B: economic choice among the remaining candidates

For each permitted topology T, compute the expected net benefit and pick the maximum subject to budget and minimum quality:

```latex
EU(T) = V \cdot P_T(\mathrm{accept}) - C_T^{\mathrm{model}} - c_{\mathrm{HIL}} \cdot E[h_T] - c_{\mathrm{fail}} \cdot P_T(\mathrm{silent})
```

```latex
T^{*} = \arg\max_T EU(T) \quad \text{s.t.} \quad C_T^{\mathrm{model}} \le B, \; P_T(\mathrm{accept}) \ge q_{\min}, \; \mathrm{quota}_T \le \mathrm{quota}_{\mathrm{free}}
```

| Symbol | Meaning | Source |
| --- | --- | --- |
| V | Value of the completed task | HIL at submission (class A/B/C or amount); default per task type |
| P\_T(accept) | Probability that the output passes acceptance | Prior from cost cards, posterior from the ledger per task class |
| C\_T^model | Expected model cost incl. retries and coordination: metered API cost plus shadow price of subscription quota (section 6) | Sum of contract cost cards × (1 + retry rate) + topology overhead |
| c\_HIL | Price of one hour of human attention | Configuration; reference instance USD 100/h (CZK 2,000/h) |
| E\[h\_T\] | Expected HIL hours (gates, questions, corrections) | Ledger |
| c\_fail | Cost of a silent error that reaches the client | Default 0.5 × V; client-facing outputs 1.5 × V |
| P\_T(silent) | Probability of an error no gate catches | Ledger (defects found later) |
| B, q\_min, quota\_free | Budget, minimum quality, remaining subscription quota | Task or task-type defaults; provider adapters |

All amounts are held in USD internally; the display currency and exchange-rate source are configuration.

### Worked example (illustrative parameters)

Task 1: research on 30 competitors for an SME-AI website, decomposable, V = USD 400, c\_fail = 0.5 × V.

| T | P(accept) | Model USD | HIL h | HIL USD | P(silent) | Silent error USD | EU USD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T2 | 0.55 | 4.0 | 0.50 | 50 | 0.10 | 20 | 146 |
| T3 | 0.65 | 5.5 | 0.40 | 40 | 0.05 | 10 | 204.5 |
| **T4** | **0.85** | **15.0** | **0.25** | **25** | **0.04** | **8** | **292** |
| T5 | 0.87 | 30.0 | 0.30 | 30 | 0.04 | 8 | 280 |

Result: T4. T5 is 2 points better on acceptance, but the debate costs more in both tokens and attention.

Task 2: a new feature in an existing web application, sequential, V = USD 250. Rule A4 limits the candidates to T2 and T3.

| T | P(accept) | Model USD | HIL USD | Silent error USD | EU USD |
| --- | --- | --- | --- | --- | --- |
| T2 | 0.70 | 7.5 | 50 | 10 | 107.5 |
| **T3** | **0.78** | **10.0** | **35** | **5** | **145** |

For comparison: without A4, T4 (P = 0.50, model USD 22.5, HIL USD 80, silent error USD 12.5) would score EU of USD 10. Rule A4 is not caution; it protects \~USD 135 per task.

Observation for the design: in these examples model cost is 1 to 8 % of task value, while human attention and silent errors are 8 to 37 %. A framework that saves tokens at the price of more HIL questions is economically wrong.

### Gate requirements

- Cost of the decision itself ≤ 1 % of V, max. 4,000 tokens on the `economy` tier; below `v_min` nothing is computed.
- Output is a `TOPOLOGY_DECIDED` record listing all candidates, their EU, the parameters used and the rules that eliminated candidates.
- The Gate may return `ABSTAIN_UNKNOWN` when the EU gap between the top two candidates is smaller than their uncertainty. It then picks the cheaper candidate and flags the task for calibration.
- HIL may override the topology before start; the override is an event and a calibration input.
- In F2 a shadow mode runs T2 alongside the chosen topology on calibration tasks and compares realised EU (section 11).

## 5. Capability and role catalog

The catalog has three levels: \~100 capabilities as units of work, 13 families as abstract ancestors, and roles as named bundles. The role format extends the A2A Agent Card v1.0 so that a role can later be exposed to other systems unchanged.

### Starter capability domains

The starter catalog targets knowledge work typical for consulting, data and small-business projects. Anyone can add domains; the starter set is a seed, not a boundary.

| Family | Example capabilities | Target count |
| --- | --- | --- |
| `mgmt` management | decompose request, phase plan, status report, risk register | 8 |
| `account` client | summarise client requirements, draft proposal, client e-mail (HIL) | 6 |
| `arch` architecture | ADR, context diagram, technology selection, ArchiMate view | 8 |
| `data` data engineering | DWH layer design, lakehouse notebook, data contract, DWH-automation metadata | 10 |
| `bi` BI and analytics | KPI tree, semantic model, measure definition, report spec | 8 |
| `dev` software | implement from spec, refactor, unit tests, deployment script | 12 |
| `ai` AI engineering | prompt or skill, eval set, RAG pipeline, model selection | 8 |
| `qa` quality | critique against acceptance, fact-check with sources, test scenarios | 8 |
| `sec` security and compliance | threat model, GDPR assessment, EU AI Act classification, permission review | 7 |
| `fin` finance | document extraction, bank-payment matching, cash-flow model, unit economics | 8 |
| `mkt` marketing and sales | landing-page funnel, SEO audit, copy, competitor profile | 8 |
| `research` research | web research with sources, public-register lookup, literature scan | 6 |
| `doc` documentation and language | technical document, translation, meeting summary | 5 |
| **Total** |  | **102** |

Roles are combinations: a BI developer = 5 capabilities from `bi` + 1 from `data` + 1 from `doc`. One capability can belong to many roles; it is measured and priced once.

### Implementation kinds

Every capability declares how its contract is fulfilled. The rule is to use the lowest kind that can do the job: `deterministic` before `decision` before `llm`.

| `impl` | Output | Engine | Typical use | Verified by |
| --- | --- | --- | --- | --- |
| `deterministic` | Any typed value | Code | Checks, transforms, verified recipes, redaction | Unit tests |
| `decision` | Choice among declared options (max. 255 per question on Jev), Score on a declared rubric, Noul truth value 0 to 1; each with probability and confidence | System One model (Jev) or an LLM through a structured-decision wrapper | Classification, routing, scoring, Gate step A, acceptance pre-checks, guardrails | Eval set + calibration curve |
| `llm` | Free text, code, documents | Generative model | Design, writing, code, synthesis | Acceptance criteria + critic |

Two consequences for catalog design:

1. **Judgements move out of generative capabilities.** An acceptance criterion such as “every KPI is mapped to a measure” becomes a `decision` capability that checks the `llm` output, instead of one more sentence in the critic's prompt. TypeSafe's own guidance points the same way: atomic questions, combined in code.
2. **Decision capabilities stay polymorphic.** TypeSafe publishes an adapter that answers the same typed questions with an LLM, so a `decision` capability can run on Jev or fall back to any text model without a contract change; the router picks by cost, latency and eval result.

### Capability card

```json
{
  "id": "cap.bi.design_semantic_model",
  "version": "1.2.0",
  "status": "active",
  "summary": "Designs a star-schema semantic model and maps KPIs to measures.",
  "i18n": {"cs": {"summary": "Navrhne hvězdicový sémantický model a mapování KPI na míry."}},
  "tags": ["semantic-model", "kpi", "star-schema"],
  "impl": "llm",
  "input_schema": "schemas/requirements_spec.v1.json",
  "output_schema": "schemas/semantic_model_design.v1.json",
  "acceptance": [
    {"id": "schema_valid", "type": "deterministic", "check": "jsonschema"},
    {"id": "all_kpis_mapped", "type": "deterministic", "check": "script:checks/kpi_coverage.py"},
    {"id": "grain_consistent", "type": "critic", "rubric": "rubrics/star_schema.md"}
  ],
  "model_policy": {
    "tier": "workhorse",
    "escalate_to": "frontier",
    "escalate_when": "acceptance_failed >= 2",
    "max_attempts": 3,
    "data_classes_allowed": ["public", "internal", "client_confidential"]
  },
  "tools": ["read_artifact", "sql_metadata_read"],
  "cost_card": {
    "prior": {"tokens_in_p50": 18000, "tokens_out_p50": 4000, "p_accept": 0.7},
    "observed": {"n": 0, "usd_p50": null, "usd_p90": null, "quota_units_p50": null, "p_accept": null, "p_abstain": null, "p_silent": null}
  },
  "abstain_conditions": [
    "KPI list or KPI definitions are missing",
    "Source schema is unavailable, even as metadata"
  ],
  "eval_set": "evals/cap.bi.design_semantic_model/"
}
```

`cost_card.observed` is written only by `ooat-core` from the ledger; manual edits are rejected in CI. `abstain_conditions` are part of both the prompt and validation: if a condition holds and the agent still returns `DONE`, the critic scores it as an error. `summary` is English; `i18n` holds optional translations for UIs and prompts in other languages.

### Role card

```json
{
  "id": "role.bi.developer",
  "extends": "family.analyst",
  "version": "1.0.0",
  "a2a": {"name": "BI Developer", "description": "Semantic model, measures and report specifications.", "skills_from": "capabilities"},
  "capabilities": [
    "cap.bi.kpi_tree", "cap.bi.design_semantic_model", "cap.bi.write_measure",
    "cap.bi.report_spec", "cap.bi.validate_measure", "cap.data.read_dwh_metadata", "cap.doc.tech_note"
  ],
  "consumes": ["requirements_spec", "dwh_schema"],
  "produces": ["semantic_model_design", "measures", "report_spec"],
  "can_object_to": ["dwh_schema", "report_spec"],
  "permissions": {"read": ["art:*", "repo:bi/*"], "write": ["repo:bi/*"], "network": false, "code_exec": "sandbox"},
  "budget": {"max_usd_per_contract": 3.0, "max_turns": 25},
  "gates": [
    {"on": "write:prod", "type": "hil", "risk": "R3"},
    {"on": "output", "type": "critic", "critic_role": "role.arch.data_architect"}
  ]
}
```

### Inheritance rules

1. A family defines shared output format, logging, escalation rules, default permissions and default gates.
2. A role may only narrow permissions, never widen them beyond its family. Widening requires a new family and HIL approval.
3. Gates accumulate: a role adds gates, never removes them.
4. Max. inheritance depth 3 (`family.base` → `family.analyst` → `role.bi.developer`).
5. The linter resolves every role into `catalog/_resolved/`; the runtime reads only resolved cards.

### Index record for the dispatcher

The dispatcher never reads full cards of all roles. It receives the top-k (k = 3 to 5) from a hybrid index; each record is \~60 tokens: `id`, `summary`, `tags`, `produces`, `usd_p50`, `p_accept`. For 100 roles the whole index is \~6,000 tokens; full cards load only for the selected roles.

### Versioning and lifecycle

- SemVer: major = input or output schema change, minor = prompt or tier change, patch = wording.
- States: `draft` → `shadow` (runs on calibration tasks, results not used) → `active` → `deprecated` → `retired`.
- `shadow` → `active` only after the eval threshold (section 11) and HIL approval.
- Changing the concrete model or provider behind a tier is a routing change, not a card change, and triggers evals of every capability on that tier.

## 6. Providers, routing and economics

Cards reference tiers; the routing policy maps tiers to provider adapters; every model call is metered, whether it is paid per token or out of a subscription quota. Without a price on subscription quota, a flat-rate plan looks free and the Gate would always pick the largest team.

### Provider access types

| Access type | Examples | Metering | Marginal cost | Main constraint |
| --- | --- | --- | --- | --- |
| `api` | Anthropic, OpenAI, Google Gemini and other vendor APIs | Exact tokens from the response | Per token | Budget, rate limits |
| `subscription_cli` | Official headless CLIs running on a personal or team plan (e.g. Claude Code, OpenAI Codex CLI, Gemini CLI) | Reported by the CLI, otherwise estimated | Shadow price of quota | Quota windows, concurrency, provider terms |
| `subscription_manual` | A subscription chat UI where automated access is not permitted | None; a human relays input and output | c\_HIL × relay time | Human time; only for HIL-approved steps |
| `local` (optional) | Ollama or llama.cpp on the user's hardware | Exact | Close to zero | Hardware; never required |

The reference installation will trial Anthropic, OpenAI, Google Gemini, Meta and JEV, often through subscriptions. Each vendor and access mode is one adapter; `ooat-core` knows no vendor names.

### Provider adapter manifest

```json
{
  "id": "prv.anthropic.subscription_cli",
  "vendor": "anthropic",
  "access": "subscription_cli",
  "runner": "claude-code-headless",
  "tiers": {"workhorse": "<model-id>", "frontier": "<model-id>"},
  "metering": "reported",
  "plan": {"fee_usd_month": 100, "quota_window_hours": null, "units": "token_equivalent"},
  "automation_permitted": "operator_confirmed",
  "concurrency": 1,
  "data_policy": {"training_on_inputs": false, "retention_days": null, "allowed_data_classes": ["public", "internal", "client_confidential"]},
  "features": {"tool_use": true, "vision": true, "context_tokens": null}
}
```

`automation_permitted` takes `operator_confirmed`, `not_permitted` or `unknown`. Only `operator_confirmed` adapters may run unattended; the other two are limited to `subscription_manual` with HIL. The framework never works around provider terms; the operator confirms, for each plan, that automated use is allowed. Unknown fields stay `null` until measured or confirmed, never guessed.

### Shadow price of subscription quota

```latex
p_{\mathrm{unit}} = \frac{F_{\mathrm{month}}}{U_{\mathrm{eff}}}, \qquad p_{\mathrm{call}} = p_{\mathrm{unit}} \cdot u_{\mathrm{call}} \cdot (1 + \mathbb{1}[w > 0.8])
```

F\_month is the plan fee, U\_eff the units actually usable per month (learned from the ledger: units consumed before quota limits hit), u\_call the units a call consumes, w the utilisation of the current quota window. Above 80 % utilisation the shadow price doubles, which pushes non-urgent work to metered APIs or to the next window and keeps quota for HIL-critical tasks. Until U\_eff is measured, the adapter uses the API list price of an equivalent model as the prior.

### Tiers

| Tier | Use | Candidate models (any vendor) | Rule |
| --- | --- | --- | --- |
| `local` | Classification, extraction, embeddings, redaction | Small open-weight models on CPU or GPU | Optional; only for deterministically verifiable outputs |
| `economy` | Gate step A, routing, log summaries, formatting | Small fast models (Claude Haiku class and equivalents) | Default for meta-work |
| `workhorse` | Most capabilities: design, code, analysis, writing | Mid-size models (Claude Sonnet class and equivalents) | Default for workers |
| `frontier` | Orchestration, synthesis, critique of high-risk outputs, escalation | Largest models (Claude Opus class and equivalents) | Only orchestrator, T3+ critic and escalation |

Prices per million tokens are deliberately absent from this document. `routing.json` loads them from provider price lists with a validity date; the exchange rate for display currency comes from a configured source (e.g. the Czech National Bank daily rate).

### Decision tier

The `decision` tier is for System One models: no text generation, typed answers to declared questions, every question scored in parallel against the same state. It serves only `impl: decision` capabilities and never writes artifacts. Its economics differ by orders of magnitude: TypeSafe lists Jev at USD 0.042 per million input tokens with free output and 70 to 500 ms per call, against USD 0.20 to 10 per million input tokens for text models. This makes checks that would be too expensive with an LLM affordable on every contract: acceptance pre-checks, data-class detection, untrusted-content flags, routing. The price may be subsidised; TypeSafe says so itself, so cost cards treat it as a measured value, not a constant.

### Named providers (as of 2026-09-29)

| Provider | Product | OOAT access | Tier fit | Status and constraints |
| --- | --- | --- | --- | --- |
| TypeSafe | Jev, first System One model; HTTP API, Python and TypeScript SDKs | `api` | `decision` | Early access since 2026-09-15. Hosted in the US; privacy policy says inputs are not used for training. Max. 255 options per Choice. Vendor claims on calibration and speed are not independently replicated; one community test reports that reversing option order moved a probability across a 0.9 threshold. |
| Meta | Muse Spark models through the Meta Model API (OpenAI-compatible), also via OpenRouter | `api` | `workhorse` candidate | Public preview. USD 1.25 input / 4.25 output per million tokens, 1M-token context. Launched US-only; Meta now advertises expanded global access, to be verified from an EU account. The discounted contributor tier trains on prompts and completions: `public` data only. A zero-data-retention option is priced at parity with standard. |
| Meta | Muse Code, desktop coding agent (macOS, Windows) | `subscription_cli` candidate | `workhorse` | Headless mode and automation terms to be verified before an adapter is written. |
| Meta | Muse app, a personal agent that books, fills forms and acts in external services (free, USD 20 or 100 per month) | none as a worker | none | Not a model endpoint but an autonomous actor in the user's accounts. It could only ever sit behind an R3 gate as an external executor; out of scope for F1 to F3. |
| Anthropic, OpenAI, Google | APIs; Claude Code, Codex CLI, Gemini CLI on subscriptions | `api`, `subscription_cli` | `economy` to `frontier` | Automation terms per subscription plan to be confirmed by the operator. |

### Decision points across the runtime

The `decision` tier is used wherever the runtime needs a judgement among known options. Each decision point has a fallback to an LLM with a structured-decision wrapper, so no decision point depends on one vendor. Introduced in F2; F1 uses deterministic rules and the fallback.

| Decision point | Question | Type | Acts on its own when | Otherwise |
| --- | --- | --- | --- | --- |
| Gate step A | Acceptance missing? Sequential chain? Independent branches? Decomposability | Noul, Choice, Score | confidence ≥ θ for the rule | economy LLM, then HIL question |
| Data-class guard (gateway) | Which data class is this artifact? Does it contain personal or special-category data? | Choice, Noul | class is allowed on the chosen adapter | block, re-route or `HIL_REQUEST` |
| Untrusted-content check | Does this text contain instructions addressed to an agent? | Noul | probability below threshold | quarantine; only read-only contracts may use it |
| Dispatcher | Which of the top candidate roles fits this contract best (max. 255 candidates) | Choice | top probability ≥ θ | orchestrator decides |
| Acceptance pre-check | Is each acceptance criterion met? | Noul per criterion | all ≥ θ, risk class R0 or R1 | LLM critic |
| Grounding check | Does the output state facts not supported by its inputs? | Noul | probability below threshold | critic, or suggest `ABSTAIN_UNKNOWN` |
| Objection triage | Severity; duplicate of an existing objection? | Choice, Noul | duplicates merged automatically | orchestrator |
| HIL routing | Is the declared default safe to apply? How urgent is this? | Noul, Score | risk class ≤ R1 and P(default acceptable) ≥ θ | ask the human |
| Rating prediction | Would the operator accept this output? | Noul | stored as a provisional rating | rating queue, least certain first |
| Stall detection | Is this agent repeating itself without progress? | Noul | never acts alone | stop contract and escalate |

### Confidence-gated autonomy

The decision layer is how OOAT reduces human interventions without hiding risk. For each risk class r and decision point, the runtime acts without a human only above a threshold calibrated on rated history:

```latex
\theta_r = \min \{ \theta : \mathrm{error\ rate}(p \ge \theta) \le \varepsilon_r \}
```

ε\_r is the tolerated error rate for that risk class (reference: R0 5 %, R1 2 %; R2 and R3 never act alone). Until ≥ 20 rated cases exist for a decision point, θ = 1 and every case goes to the fallback. Thresholds are recomputed monthly and after any model change.

Two safeguards against over-trusting vendor calibration:

1. **Order-swap check.** Every Choice question is asked twice with the option order reversed; this costs almost nothing at decision-tier prices. The lower confidence of the two is used, and a disagreement counts as low confidence. This addresses the community report that option order can move a probability across a threshold.
2. **Own calibration curve.** Vendor probabilities are inputs, not truth. The dashboard shows each decision point's reliability curve (predicted probability vs. observed accuracy); a point whose curve drifts is demoted to fallback automatically.

### Routing policy

1. Filter adapters by the artifact data class, `automation_permitted` and remaining quota.
2. Keep adapters on which the capability has passed its eval for the requested tier.
3. Pick the lowest expected cost: API price or quota shadow price.
4. The critic of a T3+ output should run on a different vendor than the author where one is available, to reduce correlated errors.
5. A capability that passes evals on several vendors is polymorphic; the router may switch between them without a card change.

### Contract cost

```latex
C_{\mathrm{contract}} = \sum_{\mathrm{api\ calls}} (t_{\mathrm{in}} p_{\mathrm{in}} + t_{\mathrm{cache}} p_{\mathrm{cache}} + t_{\mathrm{out}} p_{\mathrm{out}}) + \sum_{\mathrm{subscription\ calls}} p_{\mathrm{call}} + c_{\mathrm{HIL}} \cdot h_{\mathrm{relay}}
```

Topology cost = contracts + Gate + orchestrator + critic. The ledger stores the four separately so coordination overhead can be measured, and flags each cost as `exact` or `estimated`.

### Budgets

| Level | Set by | Soft limit | Hard limit |
| --- | --- | --- | --- |
| Monthly system budget | Operator | 80 %: daily report | 100 %: new Tasks only T0 to T2 |
| Subscription quota | Adapter | 80 % of window: shadow price doubles | 100 %: adapter unavailable until reset |
| Task | Gate from V and task type; HIL may override | 80 %: dashboard warning | 100 %: `ABSTAIN_BUDGET`, HIL decides |
| Contract | Role card (`max_usd_per_contract`) | 80 %: agent is told the remaining budget | 100 %: contract ends as `PARTIAL` or abstention |
| Debate (T5) | Orchestrator | none | max. 2 objection rounds per artifact |

### Levers for saving tokens (in order of expected effect)

1. **Do not run a team when it is not needed.** Topology Gate; sequential tasks never above T3.
2. **Pass by reference.** An agent gets `art_` references and a preview (max. 1,500 tokens per artifact) and requests full content through a tool. NOOA reached roughly half the token use at comparable accuracy this way.
3. **Top-k selection of roles and tools.** Neither the dispatcher nor an agent ever sees the whole catalog.
4. **Stable prefixes for prompt caching.** Context order: family rules → role card → contract → variable data.
5. **The cheapest tier and adapter that pass the eval.** Escalate only after failed acceptance; try a lower tier monthly in shadow mode.
6. **Structured objections instead of free debate.** Model in section 7: about 20× fewer tokens than an open thread.
7. **Deterministic checks before the LLM critic.** The critic sees only outputs that passed schema and tests.

### Economic reporting

Monthly: cost per accepted task by topology and task class; coordination overhead share; HIL hours and their USD equivalent; API spend vs. subscription quota consumed and its shadow value; the 10 most expensive capabilities and their trend. Target for coordination overhead: ≤ 25 % of T4 and T5 cost.

## 7. Meeting point: ledger of events and artifacts

Agents never talk in free text. Every message is a typed event in an append-only ledger with references to artifacts; an agent sees only events whose types and artifacts it subscribes to through `consumes` and `can_object_to`.

### Event envelope

```json
{
  "id": "evt_01J9ZQ8M2K",
  "ts": "2026-09-28T21:14:03Z",
  "task": "tsk_01J9ZQ7A1B",
  "contract": "ctr_01J9ZQ7F3C",
  "actor": {"kind": "agent", "id": "agt_01J9ZQ7G4D", "role": "role.bi.developer@1.0.0"},
  "type": "OBJECTION",
  "refs": ["art_01J9ZQ6X9E@v2"],
  "lang": "cs",
  "body": {"reason_code": "GRAIN_MISMATCH", "claim": "Fakt Prodej má grain den×produkt, KPI marže vyžaduje den×produkt×sklad.", "proposed_fix": "Přidat sklad do grainu nebo změnit definici KPI.", "severity": "blocking"},
  "cost": {"adapter": "prv.anthropic.api", "tier": "workhorse", "tokens_in": 6200, "tokens_out": 310, "usd": 0.0, "basis": "exact"}
}
```

The example shows the language rule: keys, event types and reason codes are English, free-text fields follow the task language (`lang`). `body` is validated against the schema for its `type`; an event that fails is not written and the agent receives the error. `usd` is filled in by the gateway.

### Event types

| Type | Actor | Content | Subscribers |
| --- | --- | --- | --- |
| `TASK_SUBMITTED` | HIL, intake | Request, V, budget, risk class, language | Gate |
| `TOPOLOGY_DECIDED` | Gate | Candidates, EU, rules, choice | Orchestrator, dashboard |
| `CONTRACT_ISSUED` | Orchestrator via `ooat-core` | Capability, input refs, budget, deadline | Assigned agent |
| `CLAIM` | Agent | Contract accepted | Orchestrator |
| `RESULT` | Agent | Outcome (`DONE`/`PARTIAL`), `art_` refs, self-assessed acceptance | Gates, artifact consumers |
| `ABSTAIN` | Agent, Gate | Abstention type, `reason`, `missing`, `confidence` | Orchestrator, dashboard |
| `OBJECTION` | Agent with `can_object_to` | Objection to an artifact, `reason_code`, proposed fix, severity | Artifact author, orchestrator |
| `OBJECTION_RESOLVED` | Author or orchestrator | Accepted or rejected with reason, new artifact version | Objector |
| `DECISION` | Orchestrator, HIL | A decision binding further contracts (a small ADR) | Everyone in the Task |
| `GATE_PASSED` / `GATE_FAILED` | Gate runner, critic, HIL | Check result with evidence | Orchestrator |
| `HIL_REQUEST` | Anyone via `ooat-core` | Question or approval, options, deadline, default on silence | HIL (notifier, dashboard) |
| `HIL_RESPONSE` | Human | Answer, approval, scope change | Requester, orchestrator |
| `BUDGET_WARNING` / `QUOTA_WARNING` | Gateway | Soft limit reached | Agent, orchestrator |
| `TASK_CLOSED` | Orchestrator | Outcome, costs, final artifact | Dashboard, calibration |
| `TASK_RATED` / `DEFECT_FOUND` | Human | Acceptance rating, value class; defect found after closing | Calibration |

### Debate rules

1. An objection always points to a specific artifact version and carries a `reason_code` from a closed list (e.g. `SPEC_VIOLATION`, `FACT_UNSUPPORTED`, `GRAIN_MISMATCH`, `SECURITY_RISK`, `COST_RISK`, `INCONSISTENT_WITH_DECISION`).
2. Only a role that lists the artifact type in `can_object_to` may object.
3. Max. 2 rounds per artifact; an unresolved blocking objection after round 2 becomes a `HIL_REQUEST` with two options and the orchestrator's recommendation.
4. Agents do not read the whole thread. They get the artifact, the objections to it and the valid `DECISION` events.
5. Agreement is not written. “I agree” messages are forbidden: they cost tokens and carry no information.
6. A critic never reviews its own output or output of the same role; a critic from another family, and ideally another vendor, is preferred.

### Why not free debate: a cost model

If n agents in each of R rounds read the whole thread and each adds a message of m tokens, reading alone costs:

```latex
C_{\mathrm{read}} \approx n^2 \cdot m \cdot \frac{R(R+1)}{2}
```

For n = 5, m = 800, R = 4 that is 200,000 tokens before any output or system prompt. The structured variant (one position per agent with references, one synthesis by the critic) costs ≈ 2 × n × m + synthesis ≈ 10,000 tokens: about 20× less.

### Minimal ledger schema (SQLite and Postgres compatible)

```sql
CREATE TABLE event (
  id            TEXT PRIMARY KEY,
  ts            TEXT NOT NULL,          -- ISO 8601 UTC
  task_id       TEXT NOT NULL,
  contract_id   TEXT,
  actor_kind    TEXT NOT NULL CHECK (actor_kind IN ('agent','hil','system')),
  actor_id      TEXT NOT NULL,
  role_ver      TEXT,
  type          TEXT NOT NULL,
  refs          TEXT NOT NULL DEFAULT '[]',  -- JSON array
  lang          TEXT,
  body          TEXT NOT NULL,              -- JSON, validated per type
  adapter       TEXT,
  tier          TEXT,
  tokens_in     INTEGER, tokens_cached INTEGER, tokens_out INTEGER,
  quota_units   REAL,
  cost_usd      REAL,
  cost_basis    TEXT CHECK (cost_basis IN ('exact','estimated','shadow')),
  price_ver     TEXT
);
CREATE INDEX event_task_ts ON event (task_id, ts);
CREATE INDEX event_type_ts ON event (type, ts);
-- No UPDATE or DELETE: the application role has INSERT and SELECT only.
```

Task and Contract states are views over `event`; artifacts have their own table `artifact(id, version, type, data_class, sha256, uri, produced_by_event)`.

## 8. Orchestrator and task lifecycle

The orchestrator is one role, `role.mgmt.orchestrator`. CEO, project manager and key account are not different personas but three parameter profiles of the same role. The orchestrator proposes; `ooat-core` validates and writes. The orchestrator may not approve its own gates or produce artifacts other than the synthesis.

### Orchestrator profiles

| Profile | When | Priority | c\_fail | HIL gates |
| --- | --- | --- | --- | --- |
| `ceo` | Internal work for the operator's own organisation | Value vs. cost | 0.5 × V | Irreversible actions and budget only |
| `pm` | Delivery projects with phases and deadlines | Schedule and scope | 1.0 × V | End of phase + irreversible actions |
| `key_account` | Outputs that go to a client | Quality and reputation | 1.5 × V | Every client-facing output |

A profile sets Gate parameters and gate strictness, not writing style. It is chosen at task submission or per project; installations can define more profiles in configuration.

### Orchestrator responsibilities (T3 to T5 only)

1. Decompose the task into a DAG of contracts; each node is one capability, edges are artifact types (`produces` → `consumes`).
2. Staff nodes from the top-k index; on a tie choose the lower `usd_p50 / p_accept`.
3. Write each contract: goal, output schema, permitted tools and sources, boundaries (what not to do), budget, deadline, applicable `DECISION` events. Anthropic reports that short, vague instructions cause duplicated work and gaps.
4. Record a `DECISION` whenever a choice in one branch constrains others (style, grain, technology). This addresses the implicit-decision problem.
5. Handle abstentions and objections as below.
6. Synthesise the result and close the Task, including an honest “we could not”.

### Handling abstentions

| Abstention | First response | Second response | Limit |
| --- | --- | --- | --- |
| `UNKNOWN` | Contract for a `research` capability if the missing information can be found | `HIL_REQUEST` with the exact `missing` | 1 research attempt |
| `INCAPABLE` | Re-staff with another role from the top-k | `HIL_REQUEST`; the missing capability enters the catalog backlog | 1 re-staffing |
| `UNABLE` | Escalate tier (`workhorse` → `frontier`) or switch vendor | `HIL_REQUEST` with attempts and failure reason | 1 escalation |
| `BUDGET` | Orchestrator considers narrowing scope | `HIL_REQUEST`: increase, narrow or stop | no automatic increase |
| `NOT_PERMITTED` | Look for a permitted route (redaction, other adapter) | `HIL_REQUEST`: provide data differently or close | no bypass of data policy |

Abstention is not scored as failure in calibration; its justification is. An abstention that HIL or another agent resolves with sources that were available is a “lazy abstention” and lowers the capability's `p_accept`. A silent error that should have been an abstention is penalised 3× more than a lazy abstention.

### Task lifecycle

| State | Entered on | Leaves to |
| --- | --- | --- |
| `SUBMITTED` | `TASK_SUBMITTED` | Gate step A |
| `CLARIFYING` | Rule A1 | `HIL_RESPONSE`, or after 48 h `CLOSED_ABSTAINED` |
| `GATED` | `TOPOLOGY_DECIDED` | T0 → closed; T1, T2 → `RUNNING`; T3 to T5 → `PLANNED` |
| `PLANNED` | Contract DAG accepted by `ooat-core` (and HIL if the profile requires) | `RUNNING` |
| `RUNNING` | `CONTRACT_ISSUED`, `CLAIM`, `RESULT`, `ABSTAIN`, `OBJECTION` | `REVIEW` when the DAG completes |
| `REVIEW` | Deterministic gates, critic, synthesis | `HIL_WAIT` or closed |
| `HIL_WAIT` | `HIL_REQUEST` | `HIL_RESPONSE`; after the deadline the declared default applies |
| `CLOSED_DONE` / `CLOSED_PARTIAL` / `CLOSED_ABSTAINED` / `CANCELLED` | `TASK_CLOSED` | Rating request, then calibration |

`CLOSED_ABSTAINED` is a valid end state: it records what was achieved, what is missing, why, and what it cost. The dashboard shows it as its own category, not as an error.

## 9. HIL, gates, governance and security

HIL gates follow the risk class of the action, not the task type, and every HIL request must be answerable with one click. The aim is fewer, better-prepared interventions.

### Risk classes

| Class | Example actions | Gates |
| --- | --- | --- |
| R0 | Reading, research, drafts in the workspace | Deterministic (schema, tests) |
| R1 | Writes to an internal repository, internal documents | Deterministic + critic per profile |
| R2 | Client-facing output, publication, catalog or routing change | Deterministic + critic + HIL approval |
| R3 | Irreversible: production data, payments, sending e-mail, deletion, external write APIs | HIL approval of every action by a named approver; cannot be delegated |

Any `impl: llm` capability able to perform an R3 action requires a one-time named approval when it moves to `active`, separate from ordinary catalog review. This implements the AI4DataLeaders essay's recommendation directly.

### HIL request format

```json
{
  "type": "HIL_REQUEST",
  "lang": "cs",
  "question": "Blokující námitka ke grainu faktu Prodej po 2 kolech.",
  "options": [
    {"id": "a", "label": "Přidat sklad do grainu", "cost_usd": 1.8, "impact": "+1 den práce agentů, KPI marže přesné"},
    {"id": "b", "label": "Změnit definici KPI na úroveň produktu", "cost_usd": 0.3, "impact": "Marže bez rozpadu na sklady"}
  ],
  "recommended": "a",
  "default_on_silence": "b",
  "deadline": "2026-09-29T10:00:00Z",
  "blocking": true,
  "evidence": ["art_01J9ZQ6X9E@v2", "evt_01J9ZQ8M2K"]
}
```

Rules: max. 3 options, always a recommendation, always a default on silence (for R3 the default is “do not act”), a cost per option. Non-blocking questions are collected into a digest twice a day; blocking ones go out immediately through the configured notifier with one-tap answers.

### Defined HIL entry points

Besides risk-based gates, fixed checkpoints can be switched on per task: before start (topology and budget), after planning (contract DAG), at phase end and before closing. The human can pause a Task, change scope or add a `DECISION` at any time; every intervention is an event.

### Security

1. **Least privilege:** permissions live in the role card and are enforced by the runtime, not the prompt. Default: no network, writes only to the contract workspace.
2. **Untrusted content:** artifacts from the web, e-mail and client documents carry an `untrusted` flag. A contract that reads an `untrusted` artifact may not hold R2 or R3 permissions; a separate contract acts on a structured extract.
3. **Sandbox:** `code_exec` capabilities run in an isolated container. Static checks and deny-lists are not a containment boundary; NOOA's documentation says so explicitly. Without a container runtime these capabilities are disabled.
4. **Secrets:** API keys and subscription sessions live only in the gateway and tools; agents receive tool handles, never credentials.
5. **Audit:** the ledger is append-only; backup and retention are configuration (reference: 24 months).
6. **Supply chain:** adapters and catalog packs are versioned and signed; third-party catalog packs start in `shadow`.

### Data protection without local models

- Artifacts carry a class: `public`, `internal`, `client_confidential`, `personal`, `special_category`.
- Routing enforces classes against each adapter's `allowed_data_classes`; the check is in the gateway, not in prompts.
- `personal` and `client_confidential` go only to adapters whose data policy excludes training on inputs.
- `special_category` (health, genetic, biometric data) may leave the machine only after redaction by a deterministic or CPU-based detector (e.g. Microsoft Presidio) with a verification test that no detected entity remains. Where redaction cannot be verified, the result is `ABSTAIN_NOT_PERMITTED`.
- Some data cannot be anonymised by redaction at all: raw genetic data is identifying by nature. Such inputs are processed only by deterministic capabilities on the operator's machine, or by a `local` tier if one exists; only aggregated or derived non-identifying outputs may reach external models.
- The capability and role inventory doubles as an inventory of AI systems for EU AI Act purposes.

Vendor-specific rules in the reference routing policy: Meta's contributor tier trains on inputs, so it is restricted to `public`. TypeSafe processes in the US, so personal data of EEA users sent to Jev is a transfer outside the EEA and needs the operator's legal basis; the adapter declares `region: us` and the gateway blocks `personal` and `special_category` unless the operator enables it.

### Operator responsibility and connection consequences

OOAT does not assess or certify regulatory compliance; the operator who connects a model is responsible for it. The framework's obligation is disclosure and enforcement: the operator must see the consequences of every connection before it is enabled, and the runtime must enforce the operator's choice.

Every adapter manifest carries a `jurisdiction` block. Unknown values stay `null` and are shown as unknown, never guessed:

```json
"jurisdiction": {
  "vendor_entity": "TypeSafe AI, Inc.",
  "vendor_country": "US",
  "host_entity": "TypeSafe AI, Inc.",
  "processing_regions": ["us"],
  "eu_region_available": false,
  "model_origin_country": "US",
  "training_on_inputs": false,
  "retention": null,
  "zero_retention_available": null,
  "transfer_notes": "EEA personal data leaves the EEA; operator needs a transfer mechanism.",
  "source_urls": ["https://typesafe.ai/legal/privacy-policy"],
  "verified_on": "2026-09-29"
}
```

Rules:

1. An adapter starts disabled. Enabling it shows a **connection consequences card** generated from the `jurisdiction` block and the data classes the operator wants to allow. Confirming writes an `ADAPTER_ACKNOWLEDGED` event (operator, time, manifest version, allowed data classes).
2. A change in the manifest's jurisdiction fields, or a `verified_on` older than 12 months, disables the adapter for `personal` and higher classes until re-acknowledged.
3. Data jurisdiction follows the host, model risk follows the model. An open-weight model from any country run by the operator or an EU host has the host's jurisdiction; its own evals still apply.
4. The starter catalog ships reference manifests with sources and a verification date. They are informative defaults, not legal opinions, and the card says so.
5. The reference routing policy, which operators can change: `public` and `internal` to any adapter that passed evals; `client_confidential` and `personal` only to adapters with `training_on_inputs: false`, a contract and a known region; `special_category` only after verified redaction, or not at all.

The [OOAT Manifesto](https://claude.ai/code/artifact/a3726dc6-25c8-403c-92d6-5deb7bf26cf5) explains these consequences for non-technical readers, including the current state of EU-US transfers and hosted Chinese services.

### Catalog governance

A change to a card, family, routing or adapter is a pull request → schema validation → eval run of affected capabilities → shadow run → HIL approval (R2). Agents may propose catalog changes (for example from repeated `INCAPABLE` abstentions), never apply them.

## 10. Dashboard and observability

The dashboard shows exceptions and economics, not the flow of conversation. The home screen must answer three questions within 10 seconds: what is waiting for me, what is stuck, what does it cost.

| View | Content | Source | Phase |
| --- | --- | --- | --- |
| HIL queue | Blocking requests with deadline and default, then the digest; one-click actions | `HIL_REQUEST` without `HIL_RESPONSE` | F1 |
| Rating queue | Closed tasks awaiting a 1-click acceptance rating and value class | `TASK_CLOSED` without `TASK_RATED` | F1 |
| Exceptions | `GATE_FAILED`, objections unresolved after round 2, budget and quota warnings, abstentions, stuck contracts (no event > 15 min) | ledger | F1 |
| Tasks | List with topology, state, cost vs. budget, orchestrator profile | views | F1 |
| Task detail | Contract DAG with states, event timeline, artifact versions, `TOPOLOGY_DECIDED` with all candidates and EU | ledger, artifacts | F1 (no DAG), F3 (DAG) |
| Economics | Cost per accepted task by topology and class, coordination overhead, HIL hours, API spend vs. subscription quota and shadow value | ledger, routing, adapters | F2 |
| Calibration | Predicted vs. realised EU, p\_accept and cost; abstention justification; share of correct topologies | ledger + eval results | F2 |
| Catalog | Capabilities and roles with state, version, cost card, acceptance trend, backlog from `INCAPABLE` | catalog + ledger | F3 |

Debate detail (objections and their resolution) opens from an artifact, not as a feed. A live stream of agent conversation is not built in F1 to F3: it costs attention and produces no decisions. UI strings are localisable; the reference UI ships in English and Czech.

### Observability for development

- Every model call has a trace ID linked to an `evt_`, token counts or quota units, latency, adapter and prompt version; traces export via OpenTelemetry.
- Full prompts and responses are kept for a configurable period (reference: 30 days), then metadata only; for `special_category` they are never stored.
- A weekly job classifies failures of closed Tasks using the MAST taxonomy (specification, inter-agent misalignment, verification) on the `economy` tier and feeds the calibration view.
- Alerts through the notifier: gateway failure, ledger not accepting writes, monthly budget ≥ 80 %, quota window exhausted.

## 11. Evaluation, calibration and acceptance

Nothing goes live without measurement against the single-agent baseline. Evaluation runs at three levels: capability, Topology Gate and the whole framework. Calibration starts small and grows from real use instead of a large up-front test set.

### Capability evals

- 10 to 20 cases per capability, of which ≥ 3 are cases where the correct answer is an abstention (missing input, out of scope, contradictory request).
- Deterministic checks where possible; otherwise an LLM judge in a single call with a rubric, a 0 to 1 score and pass/fail. Anthropic reports that one judge with one rubric was more consistent than several judges.
- 10 % of judge verdicts are checked by a human; disagreement above 15 % means rewriting the rubric.
- Threshold for `active`: p\_accept ≥ the card prior, abstention precision ≥ 70 %, zero silent errors on the eval set, median cost ≤ 1.3 × prior.
- The starter catalog ships eval templates; community catalog packs must include evals to be accepted.

### Calibration set: start with 5, grow by use

| Stage | Tasks | Purpose | Who rates |
| --- | --- | --- | --- |
| F1 seed | 5 hand-picked real tasks with V and acceptance defined in advance | Pipeline works end to end; rough T2 baseline; first cost cards | Operator |
| F1 to F2 organic | Every closed real task, rated in the rating queue (≈ 2 minutes: accept/reject, value class A/B/C) | Grow the set without separate test work | Operator |
| F2 exit | ≥ 20 rated tasks in total, ≥ 5 of them decomposable | Enough to judge the Gate, not enough for statistics per task class | Operator |
| Community | Public synthetic task suite shipped in the repository | Comparable results across installations and providers | Maintainers, contributors |

Five tasks are enough to prove the machinery, not to prove the Gate. With 5 tasks one wrong choice moves Gate accuracy by 20 points, so no F2 decision rests on the seed alone.

### Topology Gate evaluation

- Each calibration task runs in T2 and in the topology chosen by the Gate (shadow mode); decomposable tasks additionally in all permitted topologies while budget allows.
- Metrics: share of tasks where the Gate chose the topology with the highest realised EU; average EU loss on wrong choices, in USD and as a share of V.
- Threshold: ≥ 80 % correct choices and average loss ≤ 10 % of V, measured on ≥ 20 tasks.

### Price-list calibration

- `p_accept` and `p_silent` per capability × task class: Beta distribution, prior from the card weighted as 5 observations, updated on every rating.
- Cost: p50 and p90 over the last 50 runs, per adapter; history is split when the model behind a tier changes.
- Subscription U\_eff (usable units per month) is learned per adapter from quota-limit events.
- Self-reported `confidence` is scored with the Brier score against actual acceptance; roles with Brier > 0.25 receive a trust penalty in the Gate.
- Silent errors are found retrospectively: any correction after closing is a `DEFECT_FOUND` event linked to artifact and contract.

### Framework acceptance criteria (exit from F2)

- [ ] Topology Gate meets its threshold on ≥ 20 rated tasks.
- [ ] Cost per accepted task ≤ 1.0 × T2 baseline across the task mix.
- [ ] Unplanned HIL interventions ≥ 40 % below baseline.
- [ ] Silent errors ≤ 5 % of closed tasks; justified abstentions ≥ 70 %.
- [ ] Coordination overhead ≤ 25 % of T4 and T5 cost.
- [ ] Every artifact traceable to contract, adapter, model, role version, cost and gates.

If F2 misses the criteria, the framework is reduced to T0 to T3 (Gate + one agent + critic) and T4/T5 are postponed. That variant still has value: catalog, price list and ledger remain.

## 12. Phases F0 to F5

Measure the single-agent baseline first, then build the Gate, and add teams only once the Gate has shown value. The estimated effort to the end of F3 is 8 to 11 weeks for one senior developer with AI assistance; this is an estimate, not a plan. The repository is public from F0.

&#91;embedded content: OOAT roadmap · 6 phases, 2 exit gates, not to scale\]

The two exit gates are the only go/no-go points. If F2 fails, the framework stays at T0 to T3 and still delivers catalog, price list and ledger.

### F0 Foundation (est. 1 week)

- [ ] Public repository `ooat` with `spec/`, `catalog/`, `core/`, `sdk/`, `adapters/`, `dashboard/`, `evals/`; licence, CONTRIBUTING, code of conduct, decision records (ADR) folder.
- [ ] OOA Spec v0.1: JSON Schemas for capability, family, role, provider adapter, contract, event, routing.
- [ ] Taxonomy of 13 families and \~100 capability names with one-line summaries (no implementation).
- [ ] 5 seed calibration tasks with V and acceptance, defined by the operator.

### F1 Skeleton and baseline (est. 2 to 3 weeks)

- [ ] `ooat-core` with SQLite store (Solo profile), artifact store, gateway with USD metering.
- [ ] Adapters: at least one metered API and one `subscription_cli` adapter, both with data-class enforcement.
- [ ] Topologies T0 to T2, 15 capabilities, 5 roles, their eval sets.
- [ ] HIL through one notifier with one-tap answers; dashboard: HIL queue, rating queue, exceptions, tasks.
- [ ] Baseline: 5 seed tasks in T2 with cost, HIL hours and acceptance; every further real task rated organically.

### F2 Topology Gate and calibration (est. 2 to 3 weeks)

- [ ] Gate step A (rules A1 to A10) and step B (EU model incl. subscription shadow prices), `TOPOLOGY_DECIDED` records.
- [ ] T3: critic + deterministic gates, risk classes R0 to R3.
- [ ] Shadow mode, Beta calibration of the price list, Calibration and Economics views.
- [ ] Postgres store (Team profile).
- [ ] **F2 exit gate:** acceptance criteria from section 11 on ≥ 20 rated tasks. If missed, stop at T0 to T3.

### F3 Teams (est. 3 to 4 weeks)

- [ ] Orchestrator with `ceo`, `pm` and `key_account` profiles, contract DAG, `DECISION` events.
- [ ] T4 parallel workers, role index with top-k retrieval, catalog at 40 capabilities, adapters for at least three vendors.
- [ ] T5 in limited form: objections with `reason_code`, max. 2 rounds, escalation to HIL.
- [ ] Public release v0.3 with documentation and the community calibration suite.
- [ ] **F3 exit gate:** on decomposable tasks, T4 realises higher EU than T3 in ≥ 70 % of cases.

### F4 Extension (ongoing)

- [ ] Catalog towards \~100 capabilities driven by the `INCAPABLE` backlog and real demand, not by plan; community catalog packs.
- [ ] A2A Agent Card export of roles; MCP server exposing OOAT as tools.
- [ ] NOOA runtime adapter as a pilot for high-volume capabilities, kept only if evals confirm savings.
- [ ] Optional `local` tier adapters for installations with suitable hardware.

### F5 Operations

- [ ] Monthly: attempt a lower tier or cheaper adapter in shadow mode; economics report.
- [ ] Quarterly: retire unused capabilities, re-check rules A1 to A10 against data, refresh evals after model changes.
- [ ] Versioned releases of the spec (SemVer) with migration notes.

## 13. Risks, decisions and open questions

The biggest risk is not technical: it is a catalog that looks complete but is never measured, and a Gate that depends on a badly estimated V. Both are addressed by mandatory evals and calibration, not by more architecture.

### Risks and failure modes

| Risk | Mechanism | Dashboard signal | Mitigation |
| --- | --- | --- | --- |
| Mis-estimated V | Gate optimises against a fictional value; inflated V leads to expensive teams | High cost on tasks later rated unimportant | A/B/C classes instead of amounts; type defaults; 1-click rating |
| Vague specification | Largest MAST failure category (41.8 %) | Repeated `GATE_FAILED` on the same criterion | Rule A1, typed output schema, acceptance before start |
| Inter-agent misalignment | Implicit decisions in parallel branches (36.9 % in MAST) | Objections of type `INCONSISTENT_WITH_DECISION` | `DECISION` events, rule A7, T4 without shared files |
| Superficial verification | Critic approves whatever compiles | Silent errors above 5 % | Deterministic checks before the critic, critic from another family and vendor, 10 % human check |
| Error propagation | One agent's error reaches the synthesis | Defects traced to a single contract | Central validation in `ooat-core` (Google/MIT: 4.4× vs. 17.2× for independent agents) |
| Lazy abstention | Agents learn that “I don't know” is safe | Abstention rate rises, justification falls | Penalty in p\_accept; evals where abstention is wrong |
| Subscription terms | Automated use of a consumer plan may breach provider terms or get the account limited | Adapter with `automation_permitted` ≠ `operator_confirmed` in unattended use | Enforced in gateway; operator confirmation per plan; API fallback |
| Quota exhaustion | A flat-rate plan runs out mid-task | `QUOTA_WARNING`, stalled contracts | Shadow price above 80 % utilisation, API fallback, resume after reset |
| Multi-vendor drift | Many adapters, frequent model changes, differing tool-use formats | Eval failures after vendor updates | Tiers instead of models, adapter conformance tests, evals on routing change |
| Catalog decay | New models change tier economics every 3 to 6 months | Cost cards without observations > 60 days | Quarterly review; retirement of unused capabilities |
| Prompt injection | Untrusted content steers an agent with write access | R2/R3 attempt from a contract with `untrusted` input | Read/act split, sandbox, R3 only with HIL |
| Sensitive-data leak | Special-category data reaches an external model | Data class vs. adapter in gateway log | Gateway enforcement, verified redaction, `ABSTAIN_NOT_PERMITTED` |
| HIL fatigue | Too many questions; approvals without reading | Median answer time < 5 s on R2/R3 | Digest, recommendation and default, per-task question limit, typed confirmation for R3 |
| Open-source burden | Maintenance, support and low-quality community packs | Issue backlog, failing pack evals | Packs start in `shadow`, evals mandatory, narrow core scope |
| Framework as goal | Building OOAT costs more time than it saves | Cumulative savings vs. development hours | Exit gates F2 and F3; fallback to T0 to T3 |

Early-access vendors add one more risk: preview APIs change pricing, limits and regions without notice. Every preview adapter carries `status: preview`, is never the only adapter for a tier, and its prices are re-read monthly.

### Decisions taken (2026-09-28)

| # | Question | Decision |
| --- | --- | --- |
| D1 | Skill or code | Code: language-neutral spec + Python reference implementation + Python/TypeScript SDKs. A Claude Code skill or plugin is an optional client. |
| D2 | Platform binding | None. Solo and Team deployment profiles; the operator's CPU server is only the reference instance. |
| D3 | Language | Specification, code and documentation in English; tasks and free text in the user's language. |
| D4 | Local AI | Optional. The framework must work fully without GPU or local models. |
| D5 (Q1) | Price of attention | c\_HIL = USD 100/h (CZK 2,000/h) for the reference instance; configurable. |
| D6 (Q2) | Special-category data without GPU | Verified redaction or `ABSTAIN_NOT_PERMITTED`; some tasks will not be processable. |
| D7 (Q3) | Providers | Mixed vendors (Anthropic, OpenAI, Google Gemini, Meta, JEV), often through subscriptions; subscription quota priced by shadow price. |
| D8 (Q4) | Calibration set | Start with 5 seed tasks rated by the operator; grow organically to ≥ 20 before the F2 exit. |
| D9 (Q5) | Audience | Open source for anyone who wants to work multi-agent with quality; not an internal tool. |
| D10 (Q6) | Agent runtime | Claude Agent SDK as the F1 default, NOOA as a F4 pilot adapter. OOAT defines its own OO contract standard with transparency as the goal, not a copy of NOOA. |

D11 (Q7, 2026-09-29): Jev enters OOAT as the engine of a new `decision` tier and implementation kind, not as a text worker. Muse Spark enters as a `workhorse` candidate through the Meta Model API. The Muse app is not an adapter: it is an autonomous actor in the user's own accounts, not a model endpoint.

### Open questions

1. **Q7 Access check:** does the operator have Jev early access, and does the Meta Model API accept an EU account today? Both decide whether the `decision` tier and the Muse Spark adapter exist in F1 or wait.
2. **Q8 First adapters for F1:** proposal: Anthropic API (`workhorse`, `frontier`) + Jev (`decision`) + one subscription CLI the operator already pays for.
3. **Q9 Licence:** Apache 2.0 (explicit patent grant, proposed) or MIT (shorter, no patent clause)?
4. **Q10 Name:** is “OOAT” free to use as a project name and package name on PyPI and npm?
5. **Q11 Maintainers:** who besides the operator reviews pull requests and catalog packs, and under which governance model?
6. **Q12 Seed tasks:** which 5 real tasks, with at least 2 decomposable and at least 1 sequential, so that both sides of the Gate are exercised from day one?

## 14. Sources

| Source | Publisher | Date | Used in section |
| --- | --- | --- | --- |
| [Three Dots Between Control and Autonomy](https://www.ai4dataleaders.com/essays/three-dots-between-control-and-autonomy.html) | AI4DataLeaders | 2026-09-21 | 1, 4, 9 |
| [Six Agent Harness Capabilities for Higher Model Performance](https://developer.nvidia.com/blog/six-agent-harness-capabilities-for-higher-model-performance/) | NVIDIA Technical Blog | 2026-07-27 | 1, 6 |
| [NVIDIA-NeMo/labs-OO-Agents (NOOA)](https://github.com/nvidia-nemo/labs-OO-Agents) | NVIDIA, GitHub | accessed 2026-09-28 | 1, 9, 12 |
| [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) | Anthropic | 2025-06-13 | 4, 6, 8, 11 |
| [Towards a Science of Scaling Agent Systems](https://arxiv.org/abs/2512.08296) | Google Research, MIT (arXiv) | 2025-12-09 | 4, 13 |
| [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/abs/2503.13657) | UC Berkeley (arXiv, NeurIPS 2025) | 2025-03, rev. 2025-10 | 4, 10, 13 |
| [Silent Failure in LLM Agent Systems](https://arxiv.org/pdf/2606.08162) (MAST category shares) | arXiv | 2026-06 | 13 |
| [Don't Build Multi-Agents](https://cognition.com/blog/dont-build-multi-agents) | Cognition | 2025-06-12 | 4, 8 |
| [RAG-MCP: Mitigating Prompt Bloat in LLM Tool Selection](https://arxiv.org/abs/2505.03275) | arXiv | 2025-05-06 | 5, 6 |
| [Personas in System Prompts Do Not Improve Performances of LLMs](https://arxiv.org/abs/2311.10054) | Zheng et al., EMNLP Findings | 2024 | 1 |
| [Expert Personas Don't Improve Factual Accuracy](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5879722) | Wharton (Mollick et al.) | 2025-12-05 | 1 |
| [MetaGPT: Meta Programming for a Multi-Agent Collaborative Framework](https://arxiv.org/html/2308.00352v6) | Hong et al. (arXiv, ICLR 2024) | 2024 | 1, 7 |
| [Orchestrate teams of Claude Code sessions](https://code.claude.com/docs/en/agent-teams) | Anthropic, Claude Code Docs | accessed 2026-09-28 | 1, 4 |
| [A2A protocol](https://github.com/a2aproject/A2A) | Linux Foundation, GitHub | accessed 2026-09-28 | 5, 12 |
| [Hierarchical Process](https://docs.crewai.com/en/learn/hierarchical-process) | CrewAI Docs | accessed 2026-09-28 | 1 |

Added 2026-09-29 for the decision tier and named providers:

| Source | Publisher | Date | Used in section |
| --- | --- | --- | --- |
| [Introducing System One Models & Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) | TypeSafe AI | 2026-09-15 | 4, 5, 6 |
| [Jev documentation: Introduction](https://docs.typesafe.ai/introduction) | TypeSafe AI | accessed 2026-09-29 | 5, 6 |
| [TypeSafe privacy policy](https://typesafe.ai/legal/privacy-policy) | TypeSafe AI | 2025-11-19 | 6, 9 |
| [An Introduction to Jev](https://towardsdatascience.com/an-introduction-to-jev/) | Towards Data Science | 2026-09 | 6 (search snippet only; site blocks automated reading) |
| [awesome-jev community list](https://github.com/kydlikebtc/awesome-jev/wiki) (option-order sensitivity note) | community, GitHub | accessed 2026-09-29 | 6 (single unreplicated source) |
| [Muse, Meta's personal AI agent](https://ai.meta.com/muse/) and [CNBC coverage](https://www.cnbc.com/2026/09/08/meta-personal-ai-agents-public-reckoning-privacy-safety.html) | Meta; CNBC | 2026-09-08 | 6 |
| [Introducing Muse Spark 1.1 and the Meta Model API](https://ai.meta.com/blog/introducing-muse-spark-meta-model-api/) | Meta | 2026-07-09 | 6 |
| [Meta Model API](https://developer.meta.com/ai/products/meta-model-api/) and [pricing and rate limits](https://dev.meta.ai/docs/pricing-rate-limits) | Meta for Developers | accessed 2026-09-29 | 6, 9 |
| [Muse Code](https://developer.meta.com/ai/products/muse-code/) | Meta for Developers | accessed 2026-09-29 | 6 |
| [Meta Llama & Muse: versions and EU availability](https://innfactory.ai/en/ai-models/meta-llama/) | innFactory | 2026-09 | 6 |

Added 2026-09-29 for jurisdiction disclosure: [EDPB calls for review of the EU-US Data Privacy Framework](https://www.hunton.com/privacy-and-cybersecurity-law-blog/edpb-calls-for-review-of-eu-u-s-data-privacy-framework-after-u-s-supreme-court-decision-on-ftc-independence) (Hunton, 2026-08-05) · [EU-US DPF status and pending CJEU appeal](https://www.recordinglaw.com/world-laws/world-data-privacy-laws/eu-us-data-privacy-framework/) (Recording Law, 2026-05) · [DeepSeek hosted vs. self-hosted data flows](https://www.promptquorum.com/local-llms/deepseek-local-china-data-privacy-2026) (PromptQuorum, 2026-06) · [DeepSeek regulatory response one year on](https://ai-regulation.com/deepseek-one-year-later-regulatory-storm-global-surge/) (MIAI, 2026-02).

Topology cost multipliers, worked-example parameters, targets, the subscription shadow-price rule and effort estimates are proposals by the author of this specification, not measurements; F1 and F2 data replace them. Provider terms for automated use of subscriptions were not reviewed for this document and must be checked per plan (Q7, Q8).

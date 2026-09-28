# OOAT Manifesto: agent teams that earn their cost

Sep 29, 2026 · @Martin Pegner

OOAT (Object-Oriented Agent Team, working name) is an open-source framework for getting real work done with several AI agents without paying for theatre. Before any work starts, it asks one question: is a team worth its cost here, or will one agent do? When a team is justified, OOAT builds it from specialists that behave like well-designed software objects: each has a clear contract, a known price, a record of how often it succeeds, and permission to say “I don't know”. Every step is written to a ledger that a person can read, and every irreversible action waits for a named human. OOAT works with the AI models you already pay for, from any vendor, and runs on an ordinary server or laptop.

## The problem

Multi-agent AI is sold as a digital company: a project manager, an architect, a developer and a reviewer talking to each other until the job is done. In practice three things go wrong.

- **It is expensive.** Anthropic measured that agents use about 4 times the tokens of a chat, and multi-agent systems about 15 times. That is worth it only when the task is worth it.
- **It often makes results worse.** A controlled study by Google Research and MIT found that on tasks where each step depends on the previous one, every multi-agent variant tested performed 39 to 70 % worse than a single agent. Teams help on work that splits into independent parts, and hurt on work that does not.
- **It fails quietly.** An analysis of more than 1,600 execution traces across seven frameworks traced most failures to vague specifications and agents misunderstanding each other, not to weak models. Giving an agent a job title does not fix that: studies of 162 personas found that “you are an expert X” does not improve accuracy.

The result is familiar: impressive demos, long transcripts of agents agreeing with each other, surprising bills, and a person who still has to check everything. OOAT starts from the opposite end. Agents are cheap to add and expensive to coordinate, so coordination has to justify itself, task by task, in money and in human attention.

## Ten principles

1. **One agent first.** A team is an exception that must beat a single agent in expected value, including the cost of your attention.
2. **Contracts, not personas.** An agent is defined by what it takes in, what it returns, how its output is checked, what it may touch and what it costs. Job titles and backstories are left out.
3. **Every decision has a price.** Tokens, subscription quota and human minutes are counted on one scale, so the system can compare them honestly.
4. **“I don't know” is an answer.** Admitting missing information, missing ability or missing budget is a valid result. Hiding it is the failure.
5. **Code before decisions, decisions before prose.** What code can check, code checks. What needs judgement among known options goes to a fast decision model. Only what needs free text goes to a generative model.
6. **Humans own the irreversible.** Sending, paying, deleting and publishing wait for a named person. Everything else is designed to need them less.
7. **A ledger, not a chat.** Agents exchange typed events and references to documents, never long conversations. Anyone can reconstruct who decided what, with which model, at what cost.
8. **Vendor-neutral by construction.** Any model from any vendor can fill a role if it passes that role's tests. Switching vendors is a configuration change, not a rewrite.
9. **Transparent about where data goes.** Before a model is connected, the operator sees which country and which company will process the data, and confirms it.
10. **Measure before you trust.** No role, model or rule goes live without tests, and the system keeps learning its own real success rates and costs.

## How it works

&#91;embedded content: how a task flows through OOAT · 5 steps, 4 outcomes of the Gate\]

A task enters with a goal, an acceptance criterion, a value and a data class. The Topology Gate first applies hard rules (for example: work where each step depends on the last never goes to a team), then compares the remaining options by expected value in money. Whatever runs is split into contracts; each output passes code checks, a fast decision model and, where the risk justifies it, a critic from a different vendor. People are asked only where an action cannot be undone. Everything lands in a ledger, and the real costs and success rates it records sharpen the next Gate decision.

The decision layer deserves a word. Next to generative models that write text, OOAT uses decision models such as TypeSafe's Jev, which do not write at all: they answer typed questions (pick one of these options, score this on that scale, is this statement true) with calibrated probabilities in well under a second, at a small fraction of the cost of a text model. They classify data before it leaves, check outputs against acceptance criteria, route tasks and decide when a human is really needed. Any decision they make can also be taken by a text model; they are an optimisation, not a dependency.

## What you gain

| Benefit | How OOAT delivers it | How you can check it |
| --- | --- | --- |
| Lower cost per finished task | Teams only where they pay off; cheap checks before expensive ones; documents passed by reference instead of copied into every prompt | Cost per accepted task, compared with a single agent, on your own tasks |
| Fewer interruptions | Humans are asked only at defined risk points, with prepared options, a recommendation and a default | Human interventions per 10 tasks |
| Honest results | Agents may abstain; silent errors are tracked and penalised | Share of abstentions that were justified; defects found after delivery |
| Full audit trail | Every result traces back to the contract, model, vendor, version, cost and checks behind it | Open any result in the dashboard |
| Freedom to switch vendors | Roles are defined by contracts and tests, not by a vendor's API | Run the same role's tests on another model |
| Knowledge that grows | The catalog learns real costs and success rates per task type | Calibration view: predicted vs. actual |

The targets in the specification (for example, at least 40 % fewer unplanned human interventions) are hypotheses to be measured on your own work, not promises.

## What it costs and what can go wrong

OOAT does not make AI free or infallible. It makes costs and failures visible early.

- **Setup effort.** Every role needs a contract and a small test set. Starting with 5 to 15 well-tested capabilities beats 100 untested ones.
- **Your time for rating.** The system learns only if someone rates finished tasks, about two minutes each. Without ratings, the economics are guesses.
- **Teams still cost more per task.** Even when a team is the right choice, it spends 2 to 6 times the tokens of one agent. OOAT's promise is fewer wasted teams, not cheap teams.
- **Wrong value estimates.** If a task's value is overstated, the system will over-invest in it. Value classes and after-the-fact ratings limit, but do not remove, this risk.
- **Vendor dependence and change.** Models, prices, quotas and terms change often; preview services change without notice. Tests catch regressions, but someone has to run and read them.
- **Subscription limits.** Many flat-rate plans restrict automated use or run out mid-task. OOAT refuses to run a subscription unattended unless the operator confirms the plan allows it.
- **Security.** Agents that read web pages, e-mails or client documents can be manipulated by what they read. OOAT separates reading from acting and sandboxes generated code, but no framework removes this risk completely.
- **A framework can become the goal.** If building and tuning OOAT takes more time than it saves, stop at the simplest level (one agent, a critic, clear checks). That level alone is useful.

## Conditions for it to work

- [ ] Tasks come with a goal and at least one checkable acceptance criterion. If they do not, OOAT asks back instead of guessing.
- [ ] Someone owns the ratings and the approvals, and their hour has a price in the configuration.
- [ ] At least one model provider account whose terms allow automated use: a metered API, or a subscription plan the operator has checked.
- [ ] A monthly budget is set; OOAT enforces it.
- [ ] A container runtime (Docker or Podman) if agents are to run code; without it, code execution is switched off.
- [ ] The operator has decided, before connecting any model, which data classes may go to which vendors and countries (next section).
- [ ] An ordinary machine: no GPU and no local models are required.

## Your data, your jurisdiction, your responsibility

OOAT does not certify legal compliance. Whoever connects a model decides, and answers for, where data goes. OOAT's job is to make the consequences of that decision impossible to miss, and to enforce it once made.

### What OOAT does before a model is connected

Every model connection shows a **connection consequences card** that the operator must acknowledge before the adapter is enabled. The acknowledgement is stored in the ledger with name and date. The card states:

- the vendor's legal entity and home jurisdiction, and the company that actually hosts the model;
- where requests are processed and stored, and whether an EU region is available;
- whether inputs may be used for training, retention period, and whether zero-retention is offered;
- the country of origin of the model, which may differ from the host;
- which data classes the operator allows on this connection: public, internal, client confidential, personal, special category.

At run time a fast decision model classifies every outgoing document into those classes. Anything the operator has not allowed for that connection is blocked, not warned about.

### Where data goes, by route (as of 2026-09-29)

| Route | Processing | What the operator should know |
| --- | --- | --- |
| EU-hosted API or an EU region of a cloud provider | EEA | Least transfer friction. Still check the data processing agreement, training settings and retention. |
| US vendor, US processing | United States | Transfers from the EEA usually rely on the EU-US Data Privacy Framework. It is in force today, but after the US Supreme Court's June 2026 ruling on the independence of the FTC, the European Data Protection Board asked the Commission on 31 July 2026 to examine its validity, and an appeal is pending at the EU Court of Justice. Plan a fallback such as standard contractual clauses. |
| Chinese vendor, hosted service (for example the DeepSeek app or API) | People's Republic of China | DeepSeek's own privacy policy states that personal data is stored in China. Italy's data protection authority restricted the service in January 2025 and several other EU authorities opened investigations. Unsuitable for personal or confidential data unless a legal assessment says otherwise. |
| Open-weight model (for example DeepSeek or Llama) run by you or an EU host | Where you run it | Removes the cross-border data flow. Concerns about the model itself (susceptibility to jailbreaks, biased outputs) remain wherever it runs, so it still needs its own tests. |
| Consumer or team subscription used through a CLI | Vendor's region | Subscription terms may differ from API terms on training, retention and automated use. Check each plan. |

Two rules follow. **Data jurisdiction follows the host, not the model's country of origin. Model risks follow the model, not the host.** A sensible default for most organisations: public and internal data to any connection that passed tests; client-confidential and personal data only to routes with a contract, no training on inputs and a known region; special-category data (health, genetic, biometric) only after verified redaction, or not at all.

This section describes the situation, not legal advice. The legal landscape for transfers to the US and China is moving; review it when you connect a new vendor and at least once a year.

## Connecting to what you already use

OOAT is meant to sit behind the tools a team already works in, not to replace them. Every connection goes through one of four doors: a REST API, webhooks, an MCP server, or an adapter.

| What you already use | How OOAT connects | What it is good for |
| --- | --- | --- |
| Messaging and chat bots, e-mail, Slack, Microsoft Teams | Intake and notifier adapters with one-tap answers | Submit a task from a message; approve, decide or rate from the phone |
| Workflow automation (n8n, Make, Zapier, Power Automate) | REST API to submit tasks, webhooks for results and approvals | Start agent work from a business event; hand results back into an existing flow |
| AI assistants and IDEs that speak MCP (for example Claude Desktop, Claude Code) | OOAT MCP server with tools such as submit task, task status, answer approval | Delegate from the assistant you already use and read the ledger from it |
| Coding and agent CLIs on existing subscriptions | Subscription adapters, if the plan allows automated use | Reuse plans you already pay for, with quota tracked and priced |
| Cloud model contracts (Azure, AWS, Google Cloud) and direct vendor APIs | API adapters | Keep existing procurement, regions and data agreements |
| Issue trackers and project tools (Jira, GitHub, Linear) | Intake adapter; results as comments or pull requests behind approval gates | Turn tickets into contracts with acceptance criteria |
| Document stores and wikis (SharePoint, Google Drive, Confluence, git) | Artifact connectors; everything read from outside is marked untrusted | Work on real documents without copying them into prompts |
| Databases, lakehouses and BI tools | Deterministic tools, read-only metadata by default | Analysis and design against live structure without write access |
| Other agent systems | A2A Agent Cards exported from roles (planned) | Offer a tested role to another system, or call one |

A typical first integration takes one intake channel, one notifier and one model account. Everything else can come later.

## When not to use OOAT

- **Quick questions and one-off chats.** A chat assistant is faster and cheaper.
- **Open-ended creative exploration** with no way to say what a good result is. Without acceptance criteria, OOAT can only ask back.
- **Nobody will rate or approve.** OOAT without a human owner degrades into guesses about value and quality.
- **Decisions about people** (hiring, credit, health, legal status) where regulation or ethics require a human to decide. OOAT can prepare, never decide.
- **You need guaranteed correctness.** OOAT reduces and exposes errors; it does not eliminate them.

For strictly sequential work such as implementing one feature, OOAT will usually choose a single agent with a critic. That is the framework working as intended, not a reason to avoid it.

## Status and how to take part

OOAT is at specification stage (draft v0.1). The plan is phased: first measure a single agent on real tasks, then build the Topology Gate, and add teams only if the Gate proves its value. Each phase ends with a go or no-go decision based on measurements. The specification, code and catalog will be published under an open-source licence (Apache 2.0 proposed); the name is a working name.

Ways to contribute once the repository opens:

- **Catalog packs:** capabilities with contracts and test sets for your domain.
- **Adapters:** model vendors, subscriptions, notifiers, workflow tools.
- **Calibration tasks:** anonymised real tasks with value classes and acceptance criteria, so installations can compare results.
- **Critique:** failure reports and counter-evidence are as welcome as code.

The detailed technical design is in the [OOAT specification](https://claude.ai/code/artifact/64726677-9413-4761-9bee-e61aef24d992).

### Sources

[Anthropic, multi-agent research system (2025-06-13)](https://www.anthropic.com/engineering/multi-agent-research-system) · [Google Research and MIT, Towards a Science of Scaling Agent Systems (2025-12)](https://arxiv.org/abs/2512.08296) · [Why Do Multi-Agent LLM Systems Fail? (2025)](https://arxiv.org/abs/2503.13657) · [Personas in system prompts do not improve performance (2024)](https://arxiv.org/abs/2311.10054) · [EDPB letter on the Data Privacy Framework, Hunton (2026-08-05)](https://www.hunton.com/privacy-and-cybersecurity-law-blog/edpb-calls-for-review-of-eu-u-s-data-privacy-framework-after-u-s-supreme-court-decision-on-ftc-independence) · [DPF status and pending appeal, Recording Law (2026-05)](https://www.recordinglaw.com/world-laws/world-data-privacy-laws/eu-us-data-privacy-framework/) · [DeepSeek hosted vs. self-hosted, PromptQuorum (2026-06)](https://www.promptquorum.com/local-llms/deepseek-local-china-data-privacy-2026) · [DeepSeek regulatory response, MIAI (2026-02)](https://ai-regulation.com/deepseek-one-year-later-regulatory-storm-global-surge/)

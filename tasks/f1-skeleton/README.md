# Epic F1 — Skeleton and baseline

**Origin:** spec §12 F1 (est. 2–3 weeks) · **Decisions:** ADR 0003–0008

F1 delivers `ooat-core` for the Solo profile with topologies T0–T2 and measures the single-agent baseline.
It is split into sub-projects, each producing working, tested software on its own. A detailed plan is
written for a sub-project only when the ones it depends on are done, so it can use their real interfaces.

| # | Sub-project | Depends on | Plan |
|---|---|---|---|
| 01 | Core ledger: ids, spec validation, append-only SQLite ledger, artifact store, state projections | — | `task-01-core-ledger/plan.md` |
| 01d | Ledger hardening: deferred review findings (`task-01d-ledger-hardening/task.md`) — done | 01 | — |
| 01b | Server ledger backends: PostgreSQL and optional SQL Server (ADR 0008) — PostgreSQL is an F2 item (spec §12); listed here only for its dependency on 01, not part of the F1 exit | 01 | later |
| 01c | First-run setup `ooat init`: detect available databases, ask, write config, install only the chosen driver (ADR 0008); later also adapter acknowledgement and notifier choice | 01 | later |
| 02 | Catalog runtime: load and resolve families/roles/capabilities (linter rules from `spec/README.md`), 15 capabilities, 5 roles, eval sets | 01, task-04 seed tasks | later |
| 03 | Provider gateway — design: `task-03-provider-gateway/design.md` (ADR 0010). Plans: 03a gateway core + connector contract (done), 03b connectors (Claude Code CLI, Codex CLI, Anthropic API), 03c `ooat connectors` + consequences card | 01 | 03b next |
| 04 | Task runtime T0–T2: intake (CLI + REST), minimal Gate (A1, A2, A3, A10) with pre-start cost estimate and budget checkpoint (design §9), worker, deterministic acceptance, abstentions, task closing | 01–03 | later |
| 05 | HIL and dashboard: one notifier with one-tap answers; HIL queue, rating queue, exceptions, tasks | 04 | later |
| 06 | Baseline: eval runner, 5 seed tasks at T2 with cost, HIL hours and acceptance | 02–05 | later |

## Constraints carried into later sub-projects

- The ledger does not authenticate actors. HIL identity is verified at intake and notifier (04, 05); only those
  paths may append events with `actor.kind = hil`, so a worker can never write a human approval (R3, spec §9).
- 04 (REST intake, up to 5 agent instances) defines the threading model of the SQLite backend
  (`check_same_thread`, WAL, `busy_timeout`) before serving concurrent requests.

## Phase

F0 is still open (seed tasks, task-04). Execution of F1 sub-project 01 started on the owner's instruction on
2026-10-01; F1 exit still requires the F0 deliverables.

## Owner questions

### Before 05

- Notifier channel for HIL (Telegram bot, e-mail, Slack, …).

## Exit

All F1 items of spec §12 checked; baseline recorded in the ledger.

# Seed calibration tasks

Five real engineering tasks, anonymised, used as the F1 baseline (spec §11; `tasks/f0-foundation/task-04`).
They were chosen on 2026-10-06 from ten candidates on the owner's server. Five others need a tool-using agent
that builds and runs code (F2+) or inputs larger than one context.

- Each task asks for a single Markdown document, because the F1 worker has no tools. Its acceptance criteria can
  be checked from that document. The operator runs the delivered tests while rating (`key`).
- `attachments` are paths relative to the operator's working folder (`ooat-work/seed/`). The source files never
  enter this repository; their projects are named only there.
- Value classes use the `[gate]` defaults: A 1,000, B 300, C 50 USD. `expected_topology` is the operator's
  expectation, which the Gate's decision is compared against. It is T2 for all five, because F1 knows only T0 and
  T2; the three decomposable tasks are the candidates for T4 once it exists, so the Gate's step A answers on
  them (A5, A7) are what calibrates that side.
- Structure: sequential s1, s5; decomposable s2, s3, s4.

Submit one with `ooat task submit` in the working folder. Pass `--goal`, each `--acceptance`, `--value`,
`--data-class`, `--risk-class` and every `--file` from the JSON.

# ADR 0001 — Initial decisions

**Status:** accepted · **Date:** 2026-09-28/29 · **Source:** `spec/ooat-specification.md` §13

| # | Question | Decision |
|---|---|---|
| D1 | Skill or code | Code: language-neutral spec + Python reference implementation + Python/TypeScript SDKs. A Claude Code skill or plugin is an optional client. |
| D2 | Platform binding | None. Solo and Team deployment profiles; the operator's CPU server is only the reference instance. |
| D3 | Language | Specification, code and documentation in English; tasks and free text in the user's language. |
| D4 | Local AI | Optional. The framework must work fully without GPU or local models. |
| D5 | Price of attention | c_HIL = USD 100/h (CZK 2,000/h) for the reference instance; configurable. |
| D6 | Special-category data without GPU | Verified redaction or `ABSTAIN_NOT_PERMITTED`. |
| D7 | Providers | Mixed vendors (Anthropic, OpenAI, Google Gemini, Meta, JEV), often via subscriptions; quota priced by shadow price. |
| D8 | Calibration set | 5 seed tasks rated by the operator; grow organically to ≥ 20 before F2 exit. |
| D9 | Audience | Open source for anyone; not an internal tool. |
| D10 | Agent runtime | Claude Agent SDK as F1 default; NOOA as F4 pilot adapter. |
| D11 | Jev / Muse | Jev = engine of the `decision` tier; Muse Spark = `workhorse` candidate via Meta Model API; Muse app is not an adapter. |

Later decisions: ADR 0002 (licence), 0005 (Q7, Q8), 0006 (Q10), 0007 (Q11). Q12 is tracked in `tasks/f0-foundation/task-04-seed-calibration-tasks/`.

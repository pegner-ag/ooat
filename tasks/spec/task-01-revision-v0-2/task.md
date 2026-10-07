# Specification revision v0.2: fold accepted ADRs into the text

**Epic:** spec  **Status:** open — owner approves the revised text
**Origin:** Claude review on PR #3 (spec drift)

## Goal
The normative text of `spec/ooat-specification.md` says what the accepted ADRs decided, so readers do not
need to know the ADRs to read the spec correctly.

## Amendments to fold in
- ADR 0003: full 26-char ULIDs; `FAILED` as `RESULT` with `error`; `task: null` only for `ADAPTER_ACKNOWLEDGED`;
  `acts: false` and R3 default on silence; objection severity and closed `reason_code` list; role id middle
  segment = domain; schema `$id` base `https://moonindustries.eu/ooat/spec/v0.2/` (ADR 0013; the version segment moved with
  this revision, owner 2026-10-07).
- ADR 0004: domains vs. role families (§2, §5 tables).
- ADR 0008: pluggable ledger backends (§3 components and profiles); §7 ledger schema with `seq`, nullable
  `task_id`, `(task_id, seq)` / `(type, seq)` indexes, `artifact` table with `untrusted`.
- ADR 0009: §8 lifecycle row `CLARIFYING` → `SUBMITTED` once every clarifying question is answered.
- ADR 0011 and ADR 0012: decision tier and operator data responsibility into §2, §4, §6, §8, §9 and §11.
- ADR 0014: provider failures pause a task (§8), the budget HIL question (§9), contract budget capped by the
  role, the T2 critic exception to §7 rule 6.
- §6 provider tables: Google's subscription CLI is now Antigravity CLI (`agy`), not Gemini CLI (design 03f).
- Spec §4 rule A3 (below `v_min` → T2 without further calculation): the Gate only records A3 and may still close
  or clarify; align the text or the code.
- Ledger-enforced HIL rules (§9): options named by `recommended`/`default_on_silence`, one response per
  request, `default_applied` responses choose the default.

## Acceptance criteria
- [x] Each amendment is reflected in the spec text with a reference to its ADR.
- [x] Version line `draft v0.2`; `spec/README.md` and schemas unchanged unless an amendment requires it.
- [x] Owner approval recorded in the PR (owner, 2026-10-07: merge #22 to #25; open points decided: `$id` to v0.2, A10 text follows the code,
      `default-on-silence` stated as HIL rule 5).

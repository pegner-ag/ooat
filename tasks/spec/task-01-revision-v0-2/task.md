# Specification revision v0.2: fold accepted ADRs into the text

**Epic:** spec  **Status:** open — owner approves the revised text
**Origin:** Claude review on PR #3 (spec drift)

## Goal
The normative text of `spec/ooat-specification.md` says what the accepted ADRs decided, so readers do not
need to know the ADRs to read the spec correctly.

## Amendments to fold in
- ADR 0003: full 26-char ULIDs; `FAILED` as `RESULT` with `error`; `task: null` only for `ADAPTER_ACKNOWLEDGED`;
  `acts: false` and R3 default on silence; objection severity and closed `reason_code` list; role id middle
  segment = domain; schema `$id` placeholder.
- ADR 0004: domains vs. role families (§2, §5 tables).
- ADR 0008: pluggable ledger backends (§3 components and profiles); §7 ledger schema with `seq`, nullable
  `task_id`, `(task_id, seq)` / `(type, seq)` indexes, `artifact` table with `untrusted`.
- ADR 0009: §8 lifecycle row `CLARIFYING` → `SUBMITTED` once every clarifying question is answered.
- Ledger-enforced HIL rules (§9): options named by `recommended`/`default_on_silence`, one response per
  request, `default_applied` responses choose the default.

## Acceptance criteria
- [ ] Each amendment is reflected in the spec text with a reference to its ADR.
- [ ] Version line `draft v0.2`; `spec/README.md` and schemas unchanged unless an amendment requires it.
- [ ] Owner approval recorded in the PR.

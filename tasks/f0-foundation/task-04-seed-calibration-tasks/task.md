# Seed calibration tasks (owner input required)

**Epic:** f0-foundation  **Status:** done — five tasks chosen by the owner (2026-10-07)
**Origin:** spec §11, §12 F0, open question Q12

## Goal
5 real tasks defined by the operator, used as the F1 baseline.

## Context
Spec §11 "Calibration set". At least 2 decomposable and at least 1 sequential task, so both sides of the
Gate are exercised. Real client data must not be committed — store an anonymised description only.

## Acceptance criteria
- [x] 5 files in `evals/calibration/seed/`, each with: goal, acceptance criteria (checkable), value V
      (class A/B/C or USD), data class, expected structure (sequential / decomposable), working language.
- [x] ≥ 2 decomposable, ≥ 1 sequential.
- [x] No personal or client-confidential content in the repository.

## Out of scope
Running them (F1).

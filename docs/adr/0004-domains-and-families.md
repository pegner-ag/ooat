# ADR 0004 — Capability domains and role families

**Status:** accepted · **Date:** 2026-09-29 · **Context:** spec §2 and §5 use "family" both for the 13 starter domains and for abstract role ancestors

## Decision

1. **Domains** (`mgmt`, `account`, `arch`, `data`, `bi`, `dev`, `ai`, `qa`, `sec`, `fin`, `mkt`, `research`, `doc`)
   are namespaces only: the middle segment of `cap.<domain>.<verb>_<object>` and `role.<domain>.<name>`.
   They carry no rules or permissions. The list lives in `catalog/taxonomy.json`, which also holds each
   domain's target count; further domains are added there without changing tests or schemas.
   Domain `general` holds `cap.general.complete_task`, the one-agent fallback (T2 default) for tasks no
   specialised capability fits; repeated failures or cost there feed the catalog backlog.
2. **Families** are abstract role ancestors grouped by kind of work and risk, not by field:
   `family.base` → `analyst`, `builder`, `reviewer`, `communicator`, `orchestrator`.
   They carry rules, permissions, budget and gates (`catalog/families/`).
3. Permissions and budgets are **ceilings**: every level (family and role) may only narrow its parent.
   `family.base` is therefore the ceiling for the whole catalog. Gates accumulate down the chain.
4. Chain depth stays ≤ 3: `family.base` → `family.<kind>` → `role.<domain>.<name>`.

## Why

Permissions and gates follow the risk of the work (reading, building, reviewing, talking to clients),
which cuts across fields: a reviewer in `bi` needs the same rules as one in `dev`. Domain families would
repeat those rules 13 times.

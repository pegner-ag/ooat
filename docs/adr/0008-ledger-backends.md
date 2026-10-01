# ADR 0008 — Pluggable ledger backends

**Status:** accepted · **Date:** 2026-10-01 · **Context:** spec §3 names SQLite (Solo) and Postgres (Team); the
reference server also runs Microsoft SQL Server, and the owner wants the database to be a choice.

## Decision

1. The ledger is split into `Ledger` (spec rules: validation, provenance, atomic event + artifacts, row mapping)
   and a `LedgerBackend` (database dialect only), selected by URL:
   `sqlite:///<path>`, `postgresql://…`, `mssql://…`.
2. Supported backends: **SQLite** (F1, Solo default), **PostgreSQL** (F2, Team profile per spec),
   **Microsoft SQL Server** (optional; built when an installation needs it).
3. Append order is an explicit `seq` column (identity / autoincrement), not a dialect feature such as `rowid`.
4. **First-run choice, no forced installs.** `ooat init` detects what the machine already has (SQLite is
   always available as part of Python; a reachable SQL Server or PostgreSQL is offered when found), asks
   the operator which to use and writes the ledger URL to the configuration. OOAT never installs a database
   itself; for a missing one it shows how to install it. Only the chosen backend's driver is installed, as an
   optional extra (`ooat-core[postgresql]`, `ooat-core[mssql]`). Credentials are not written to the
   configuration; they come from environment variables or the OS credential store.
5. Every backend must pass the shared conformance tests in `core/tests/test_ledger.py`; append-only
   enforcement (triggers, and for server databases an application role with INSERT and SELECT only) is
   tested per backend.

## Consequences

- Choosing a database is configuration, consistent with principle 8 (vendor-neutral by construction).
- Server backends add a driver dependency each (e.g. psycopg, pyodbc) as optional extras, never as core
  requirements.
- Creating databases or logins on a shared server is an operator action outside OOAT.

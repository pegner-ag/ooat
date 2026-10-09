# ADR 0015 — The operator approves the hooks a connector's CLI runs

**Status:** accepted · **Date:** 2026-10-07 · **Context:** a subscription CLI can run hook commands around every
agent step (Antigravity CLI reads `~/.gemini/config/hooks.json`). Hooks run outside OOAT's isolation, so the
Antigravity connector refused every call while any hook was configured (design 03f). The owner uses Orca, which
registers such hooks for its own panes, and wants Orca and OOAT to use `agy` side by side (owner, 2026-10-06).

## Decision

1. A connector that knows its CLI's hook files exposes `hooks()`: each file's path, sha256 of its bytes, and text.
2. `ooat connectors approve-hooks <connector> --operator <name>` shows every hook file and, once the operator types
   the connector id, appends a new `ADAPTER_ACKNOWLEDGED` that repeats the one in force and adds
   `approved_hooks` (path and sha256 per file). Classes, automation and any responsibility stay as given; the
   approval replaces earlier hook approvals.
3. The gateway passes the approved fingerprints to the connector on every call (`ModelRequest.approved_hooks`). A
   hook file whose fingerprint is not approved — new, changed in any byte, or unreadable — stops the call with a
   message naming the command to run.
4. A hook may receive the CLI's prompts and replies, and it runs outside the gateway. Hooks can therefore only be
   approved while the connector is enabled for `public` or `internal` data; enabling it again for other classes
   writes an acknowledgement without the approval. A hook file holding `{}`, `[]` or `null` defines no hooks.
5. OOAT still passes the CLI only the allow-listed environment, so a hook gets no `ORCA_*` or other variables it
   was not meant to see. Approving a hook does not widen what the agent itself may do.

## Consequences

- Schema change: `body_adapter_acknowledged.approved_hooks` (array of `{path, sha256}`), additive.
- Orca's hooks in `config/hooks.json` can be approved once; after Orca rewrites the file, OOAT asks again.
- Decided by the owner on 2026-10-06 ("postav schvalování hooků"); recorded on 2026-10-07.

## Amendment (owner, 2026-10-09)

The approval first covered `hooks.json` only, so a script its commands call could change without a new approval:
Orca's per-event scripts call `antigravity-hook.cmd`, which `hooks.json` never names. `hooks()` now also lists every
file in the folder of each program a hook command starts, and each needs the operator's approval. A change to any
of them stops the connector until it is approved again.

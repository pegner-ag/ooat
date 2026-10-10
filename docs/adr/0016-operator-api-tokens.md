# ADR 0016 — Operator API: tokens, channels, intake keys and the R3 identity rule

**Status:** proposed — the owner accepts it before Task 2 of plan 05a · **Date:** 2026-10-10 · **Context:** the
operator experience design (`tasks/f1-skeleton/task-05-operator-ux/design.md`, approved by the owner 2026-10-09,
§6, §12, §13, §14) adds `ooat serve`: a REST API for the web app and the owner's chat bot. Bots act through API
tokens, so who could act for whom must be in the audit log, and a chat platform stores what it receives.

## Decision

1. **Operator tokens are ledger events.** `ooat tokens create --operator NAME --name NAME --scopes ...` appends
   `OPERATOR_TOKEN_ISSUED` (human actor, `task: null`; body: `token` (`tok_<ULID>`), `operator`, `name`, `scopes`,
   `max_data_class`, `sha256`, `expires`, and `responsibility.confirmed_on` for a cap above `internal`).
   `ooat tokens revoke` appends `OPERATOR_TOKEN_REVOKED` (`token`; `operator`, who revoked it; the required
   `reason`). Any operator may revoke any token: names are self-declared, and a leaked token must be stoppable
   at once by whoever notices. The token is 256 random
   bits with the prefix `ooat_`, printed once; the ledger keeps only its SHA-256, compared in constant time. Scopes:
   `submit` (also cancels), `read`, `answer`, `rate`, `connectors`. A token expires after 1 to 365 days (default 90)
   and acts as the operator who issued it. An open event stream checks its token or session again on every
   poll and ends with an `UNAUTHENTICATED` event once it no longer holds. Approving a connector's hooks
   (ADR 0015) approves code that runs on this machine, so it is done from the CLI or a web session only, never
   with a token (403 `SCOPE`).
2. **ADR 0003 §3 is amended:** `task: null` is allowed for `ADAPTER_ACKNOWLEDGED`, `ADAPTER_DISABLED`,
   `OPERATOR_TOKEN_ISSUED` and `OPERATOR_TOKEN_REVOKED`, and required for the two token events. The event schema's
   null-task conditional admits them.
3. **Channel.** The bodies of `TASK_SUBMITTED`, `HIL_RESPONSE`, `TASK_RATED`, `ADAPTER_ACKNOWLEDGED`,
   `ADAPTER_DISABLED` and `DECISION` (the operator's cancel) may carry `channel`: `cli`, `web` or `token:<tok_id>`.
   The actor of a human event written through the API is the operator bound to the session or token, never a name
   from the request body.
4. **Intake key.** `TASK_SUBMITTED.body.intake_key` (printable ASCII without spaces, 1 to 128 characters, only with
   a `channel`) is the client's idempotency key, e.g. a chat message id. It is unique per `(channel, key)`;
   `Ledger.append` checks it inside the same `BEGIN IMMEDIATE` write transaction as the insert, so two concurrent or
   retried deliveries create one task, also across a restart. A repeat returns the task the key created.
5. **Data-class cap.** A token's `max_data_class` (default `internal`; `special_category` never) caps every read the
   token makes: content above it comes back as a stub, while ids, states, costs and deadlines stay visible. It caps
   writes too: answering, rating or cancelling a task above it, submitting above it, or enabling a connector for a
   class above it is refused with `DATA_CLASS_ABOVE_TOKEN`. A task's class is the class it runs under (declared,
   raised by the pre-scan, the Gate's A10 and its attachments); an artifact's is its own. Raising a cap above
   `internal` is the operator's responsibility statement, recorded with the date as in ADR 0012. A web session on
   loopback has no cap (owner, 2026-10-09). A server bound beyond loopback needs `[serve] tls_cert` and `tls_key`,
   and caps its web sessions at `internal` like a token (design 05 §14: the plan chose the cap over a
   responsibility statement).
6. **R3 needs a bound identity (amends spec §9).** A named approver is an operator identity bound to something the
   operator holds, such as a passkey (WebAuthn) or an OS-account check. A self-declared name (the CLI's
   `--operator`, `ooat login --operator`) or a token never answers an R3 request. Until such a binding exists every
   R3 request is refused on every channel with `R3_NEEDS_BOUND_IDENTITY`, and the ledger accepts a response to an
   R3 request only from `default-on-silence`. A response under `default-on-silence` must carry
   `default_applied: true` and choose the request's `default_on_silence`, so the reserved name never acts. F1 has no R3 request, so nothing breaks today; the binding is a
   precondition for the first R3 gate, not part of 05.
7. **The dashboard is JavaScript checked by tsc (amends spec §3).** Plain ES modules with JSDoc types, checked in
   CI by `tsc --noEmit --checkJs`, served as static files from the `ooat-core` wheel without a build step (owner,
   2026-10-09). The TypeScript SDK stays TypeScript. CLAUDE.md's stack line ("TypeScript dashboard") is
   updated to match; this ADR is the owner's approval of that change.
8. **A Usage view in F1 (amends spec §10)**, ahead of the F2 Economics view: calls, tokens and cost by role,
   connector, tier and project, metered and subscription shadow cost, tasks by outcome, cost per accepted task,
   HIL waiting time.
9. **The operator cancels a task** with a `DECISION` ("cancel the task", human actor, `channel`). The runtime
   closes the task as `CANCELLED` at its next step; a call in flight finishes first, so its cost is recorded, and
   its document is kept. A cancelled task's open questions are no longer listed and get no default.
10. **Publishing on PyPI.** The owner approved publishing OOAT on PyPI on 2026-10-09. The distribution name is
    `ooat-core` (owner, 2026-10-10) and the command it installs is `ooat`, so `pipx install ooat-core` becomes the
    documented install once a release is cut. Each release is still published only on the owner's go; the
    CLAUDE.md rule on publishing stays in force for every release.

## Consequences

- Schema changes, all additive: `common.schema.json#/$defs/token_id`; event types `OPERATOR_TOKEN_ISSUED` and
  `OPERATOR_TOKEN_REVOKED` with their bodies; `channel` in six bodies; `intake_key` in `TASK_SUBMITTED`.
- Spec v0.2 text: §3 (dashboard), §7 (event types, `task: null`), §9 (R3, HIL rule 6), §10 (Usage view).
- Behaviour changes: `ooat hil answer` refuses R3 requests; a task is rated once (a second rating would count its
  verdicts twice in the thresholds); while `ooat serve` runs, `ooat task run` refuses and `ooat task submit` and
  `ooat hil answer` only record, and the server runs the task.
- API error codes (English, stable): `INVALID`, `HOST_NOT_ALLOWED` (400); `UNAUTHENTICATED` (401); `SCOPE`, `CSRF`,
  `ORIGIN_NOT_ALLOWED`, `DATA_CLASS_ABOVE_TOKEN`, `R3_NEEDS_BOUND_IDENTITY` (403); `NOT_FOUND` (404);
  `ALREADY_ANSWERED`, `NOT_CLOSED`, `ALREADY_RATED`, `NOT_OPEN`, `HOOKS_CHANGED` (409); `LENGTH_REQUIRED` (411);
  `TOO_LARGE` (413); `SPEC_VALIDATION` (422); `LEDGER_BUSY` (503).
- Decided by the owner on 2026-10-09 (design 05 §13); this record is proposed on 2026-10-10 and takes effect when
  the owner accepts it.

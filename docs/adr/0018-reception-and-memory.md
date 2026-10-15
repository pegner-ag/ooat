# ADR 0018 — A reception turns messages into answers or tasks, with conversations and project memory

**Status:** proposed · **Date:** 2026-10-15 · **Context:** OOAT accepts work only as tasks with a goal and
acceptance criteria (spec §4 rule A1, §7 `TASK_SUBMITTED`); the chat bridge reads the criteria from a `Done when:`
line, every message is a new task without memory of the previous one, and the Gate's clarifying questions arrive
as formal questions. The owner finds this clumsy and wants OOAT to be used "almost like a Google query", coping with
unclear goals, with memory and context (owner, 2026-10-15). Design:
`tasks/f1-skeleton/task-08-reception/design.md`.

## Decision

1. `ooat-core` gains **conversations** (`cnv_`) above tasks: one per operator, project and channel. Messages,
   the reception's decisions and closing are ledger events with `task: null`: `CONVERSATION_MESSAGE`,
   `RECEPTION_DECIDED`, `CONVERSATION_CLOSED`. A conversation closes after 24 h without a message.
2. The **reception** decides each message with one structured call on the `economy` tier through the gateway:
   `answer`, `task`, `confirm`, `ask` or `continue_task`. It writes the goal and acceptance criteria of a task
   itself; a `Done when:` line in the message wins. It asks at most one question per message and at most two in a
   row, then states its interpretation and starts.
3. It never lowers a risk class; R2 and R3 are always confirmed by a person, R3 still needs a named approver
   (ADR 0011). The Gate, contracts and their checks are unchanged; a Gate clarifying question is asked by the
   reception inside the conversation and answered as the same `HIL_RESPONSE` (ADR 0009).
4. A reception decision is a **decision point** with its own θ, calibrated per engine and model version from the
   operator's verdicts (a **Differently** tap, a correction, an early cancel). Below θ, or for a task above
   `v_min`, the decision is repeated on the `workhorse` tier; both calls are on the ledger. No provider-side
   advisor tool is used for this.
5. A **direct answer** reads the project's folders with a read-only grant (`list_dir`, `find_files`, `search`,
   `read_file`; guard and `deny` of ADR 0017), at most 40 operations and a cost cap per message, recorded as
   `WORKSPACE_USED` with the conversation. It skips the Gate: for a read-only R0 request below `v_min` this is the
   Gate's own outcome (rule A3, T1, no step B).
6. **Project memory** and the operator's **preferences** are items (`mem_`) of kind `preference`, `fact`,
   `glossary` or `summary`, each with a scope, a data class (at least the project's) and a source. Events
   `MEMORY_NOTED`, `MEMORY_EDITED`, `MEMORY_FORGOTTEN` carry ids and SHA-256 hashes, never the text. The texts live
   in a separate store `ooat-memory/` beside the ledger, one file per item; forgetting deletes the file. Project
   memory never crosses projects.
7. The reception notes at most 3 items after a task or answer, visibly, with a Forget button, and a summary when a
   conversation closes. Text that the local secret and personal-data scan flags as a secret is never stored.
   Forgetting works from every surface; editing a text or pinning needs a named operator's web session, not an
   API token.
8. When the reception fails, a message becomes a task as before, and the reply says so.

## Consequences

- Schemas: event types above; `reception_decision`; `body.conversation` on `TASK_SUBMITTED` and
  `WORKSPACE_USED`; id prefixes `cnv` and `mem`. Spec §3, §6, §7 and §10 gain the matching text.
- The ledger stays append-only and the single write path; memory texts are the first operator data OOAT deletes
  for real, so the ledger proves only that an item existed and was forgotten, not what it said.
- Conversation messages are permanent in the ledger like task requests; forgetting a memory item does not remove
  the message it came from.
- Every reception call costs money even when no task follows; it is a separate line in Usage and `/stats`, with a
  target of USD 0.02 per message on average.
- `POST /api/v1/tasks` stays for scripts and workflow tools; the chat bridge and the web move to conversations.
- Spec §10's rule against a live stream of agent conversation stands: a conversation is the operator's dialogue
  with the reception, not agents talking to each other.

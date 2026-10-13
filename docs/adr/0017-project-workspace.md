# ADR 0017 — Agents work on a project's folders through OOAT's own file tools

**Status:** accepted · **Date:** 2026-10-12 · **Context:** a task worker turns text into a document: the
subscription CLI connectors run in an empty temporary folder with their built-in tools switched off (`--tools ""`),
so an agent never sees a file on disk (design 04). The owner wants tasks sent from Telegram or the web to work on
the files of the chat's current project, read and write, directly in its folders (owner, 2026-10-12). Spec §9 names
R0 (reading, drafts in the workspace) and R1 (writes to an internal repository) but defines no workspace, and keeps
code execution in a container (§9 point 3). Design: `tasks/f1-skeleton/task-07-project-workspace/design.md`.

## Decision

1. The operator maps a project slug to folders in `ooat.toml` (`[projects.<slug>]`: `folders`, `write`,
   `data_class`, `deny`, limits). A task's `project` selects them; a chat bridge or token can never name a folder.
   A project without an entry runs text only, as before.
2. The runtime puts a workspace grant on the model request; the gateway routes it only to a connector whose
   manifest has `features.workspace: true`, else the gateway answers `NOT_PERMITTED` with "no enabled connector can
   work with project folders" and the task closes abstained. A workspace task
   never runs without its files.
3. The agent gets OOAT's file tools over MCP (`list_dir`, `find_files`, `search`, `read_file`, `edit_file`,
   `write_file`) and no built-in tools of its CLI. Every path passes OOAT's guard: relative to a granted folder,
   resolved to its real path inside it, never a fixed protected name (`.env*`, keys, certificates and credential
   files, `.git`, OOAT's own config, ledger and blobs) nor a `deny` pattern, text files only. Files that
   development tools run (`CLAUDE.md`, `AGENTS.md`, `.mcp.json`, `.claude/`, `.vscode/`, `.github/`, `.idea/`) are
   read only, and so are OOAT's own code, its connectors and the interpreter. No delete, rename or command.
4. A project with `write = true` makes the task R1, read only R0; the project's `data_class` is the task's
   minimum class. Routing by data class (ADR 0010, ADR 0012) is unchanged.
5. The tools journal every operation; after each call `ooat-core` appends `WORKSPACE_USED` (paths, hashes,
   counts, refusals, the limit reached — never contents). Before a file is first changed its original is stored
   as an artifact, so the operator can revert a task's changes (`WORKSPACE_REVERTED`); revert never deletes a
   created file and skips a file changed since.
6. Per task limits (default 300 operations, 5 MB written, per project in the config). When one is reached the task
   pauses with a `HIL_REQUEST`: raise the limit for this task, continue in a follow-up task, keep as is (default on
   silence), or revert. One writing task per project at a time.
7. The first connector with the workspace is Claude Code; others follow once a test proves they see only OOAT's
   tools. Commands (tests, git, build) stay outside this decision: spec §9 point 3 stands, and containers are a
   later sub-project whose technology the owner chooses.

## Consequences

- Schemas: event types `WORKSPACE_USED`, `WORKSPACE_REVERTED`; artifact kinds `workspace_original`,
  `workspace_diff`; `TASK_SUBMITTED.body.workspace` and `body.follows`; `features.workspace` in the provider
  manifest. Spec §7 and §9 gain the matching text.
- The boundary is enforced by OOAT for every connector, not by each CLI's settings; a connector that cannot attach
  OOAT's MCP server without built-in tools cannot take workspace tasks.
- An agent writes the operator's real files without a copy or branch. The safety net is the journal, the stored
  originals and revert, not isolation; content in the files can still steer the agent within the granted folders.
- The agent cannot run tests, so a change it makes is unverified by execution until containers exist.
- "One writing task per project" holds under the Solo profile through the runner lock: one process runs one task
  at a time. The per-project lock (plan 07b) only keeps a revert from writing during a call. A profile that runs
  tasks concurrently needs the project lock held for the whole task.
- Decided by the owner on 2026-10-12 with design 07: `keep` is the default after 48 h, and revert asks for a
  second confirmation.

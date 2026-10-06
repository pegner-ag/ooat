# ooat-adapter-antigravity-cli

## Purpose
Model connector `prv.google.subscription_cli`: runs Google's Antigravity CLI headless (`agy -p`, stream-json) on
the operator's Google account and its existing login. Antigravity CLI replaced Gemini CLI.

## How a call runs
- System text and request go to stdin as one stream-json message
  (`{"event":"user","message":{"content":"…"}}`), never in argv; system text first, a blank line, then the request.
- Flags: `--input-format stream-json --output-format stream-json --sandbox --disable-slash-commands -p=` and
  `--model=<id>`. Never `--dangerously-skip-permissions`, `--add-dir`, `--continue` or `--conversation`.
- An empty temporary directory is the working directory, with the allow-listed environment of `connectors/cli.py`.
  In headless mode every tool that needs a permission is soft-denied (commands, writes, URLs, files outside the
  workspace); reading inside the workspace needs none, and the workspace is empty.
- Before each call the connector refuses to run when the agy setup could give the agent a tool: settings keys
  it has not checked, `permissions` other than an empty allow list and deny rules, an MCP server
  (`agy mcp list`) or a plugin (`agy plugin list`). `detect()` checks only the settings file, so it stays offline.
- The executable is found on `PATH`, else at `%LOCALAPPDATA%\agy\bin\agy.exe` (winget's install folder).
- A run whose tools were all denied ends with an empty answer, which the task's output check counts as an empty
  attempt; it is not a provider failure, so the task does not pause on it.
- Usage: `tokens_out` = `output_tokens` + `thinking_tokens`; `tokens_cached` = `cache_read_tokens`; metering
  `reported`.
- Errors: a result with a status other than `SUCCESS` is typed by its message (rate or quota limit →
  `QUOTA_EXHAUSTED`, login → `UNAVAILABLE`, else `API_ERROR`); no result line → `UNAVAILABLE` for a login message
  on stderr, else `API_ERROR`; past the timeout → `TIMEOUT`.

## Manifest facts
Vendor `google`; vendor entity, country, regions and retention `null`. `training_on_inputs` is `true`: the
Antigravity terms let Google use Interactions to improve its products and machine learning, with human review, on
a consumer login (Google AI Pro included); a setting changes this, but OOAT cannot see it. Allowed classes
`public` and `internal`; client and personal data can never be added, because the provider trains (ADR 0012).
`automation_permitted` is `unknown`: Google support called a local child process on the cached login supported
(forum, 2026-09-15), the terms forbid third-party software accessing the service; the operator decides when
acknowledging. agy keeps conversations under `~/.gemini/antigravity-cli/conversations`.

## Public API
`AntigravityConnector` (entry point `ooat.connectors: antigravity`).

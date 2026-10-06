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
  (`agy mcp list`) or a plugin (`agy plugin list`), or hooks in `~/.gemini/config/hooks.json` or in
  Gemini CLI's `~/.gemini/settings.json` (whether agy still reads the latter is not documented, so it refuses
  too). `detect()` checks only the files, so it stays offline.
- The executable is found on `PATH`, else at `%LOCALAPPDATA%\agy\bin\agy.exe` (winget's install folder).
- A run whose tools were all denied ends with an empty answer, which the task's output check counts as an empty
  attempt; it is not a provider failure, so the task does not pause on it.
- Usage: `tokens_out` = `output_tokens` + `thinking_tokens`; `tokens_cached` = `cache_read_tokens`; metering
  `reported`.
- Errors: a result with a status other than `SUCCESS` is typed by its message (rate or quota limit →
  `QUOTA_EXHAUSTED`, login → `UNAVAILABLE`, else `API_ERROR`); no result line → `UNAVAILABLE` for a login message
  on stderr, else `API_ERROR`; past the timeout → `TIMEOUT`.

## Measured (2026-10-06, agy 1.3.0)
- A shell command is soft-denied with and without `--sandbox`; `--sandbox` additionally restricts the terminal
  for any command an operator might allow. `--disable-slash-commands` stops slash-command and skill expansion in
  the prompt. Both flags stay.
- `-p=` with stream-json input reads the whole prompt from the stdin message.
- A minimal call carries about 11,700–12,800 input tokens (agy's own system prompt and tool list).
- Cache counting: two identical 3,700-character prompts a minute apart showed `cache_read_tokens` 0 both times,
  so whether `input_tokens` includes cache reads could not be measured. `INPUT_INCLUDES_CACHE` is `False`: if it
  does include them, cached tokens are counted twice, which overstates the shadow cost rather than hiding cost.
- Settings (https://antigravity.google/docs/settings/, /docs/permissions/): `toolPermission`,
  `artifactReviewPolicy` and `allowNonWorkspaceAccess` widen what the agent may do, and `permissions` holds
  `allow`, `ask` and `deny` lists. Keys accepted without refusing: `model`, `trustedWorkspaces` (present in the
  operator's file), `enableTelemetry` (data collection only; switching it off must not stop the connector) and
  the display keys `altScreenMode`, `colorScheme`, `runningLightSpeed`, `verbosity`, `showTips`,
  `showFeedbackSurvey`, `notifications`, `editorMode`. Any other key, such as `editor` or `useG1Credits`
  (spends AI credits when the quota runs out), stops the connector until it is reviewed.

## Prices
`catalog/routing.json` prices the three default tiers at Google's Gemini API list prices
(https://ai.google.dev/gemini-api/docs/pricing, checked 2026-10-06), as shadow cost on the plan. The `-low` /
`-high` suffixes are agy's reasoning-effort variants of the API models `gemini-3.8-flash` (0.75 / 3.75 USD per
1M tokens until 2026-12-31, then 1.5 / 7.5) and `gemini-3.1-pro-preview` (2 / 12, the price for prompts up to
200k tokens; a longer prompt costs more than the shadow price says). `valid_from` is the day the prices were
checked, because the page does not say since when they apply. Other agy models stay unpriced, so the gateway
does not route to them.

## Manifest facts
Vendor `google`; vendor entity, country, regions and retention `null`. `training_on_inputs` is `true`: the
Antigravity terms let Google use Interactions to improve its products and machine learning, with human review, on
a consumer login (Google AI Pro included); a setting changes this, but OOAT cannot see it. Allowed classes
`public` and `internal`; client and personal data can never be added, because the provider trains (ADR 0012).
`automation_permitted` is `unknown`: Google support called a local child process on the cached login supported
(forum, 2026-09-15), the terms forbid third-party software accessing the service; the operator decides when
acknowledging. Owner decision (2026-10-06): enabled for `public` data only, because Gemini is priced below
Claude Code in every tier and would otherwise take over internal work.

Local copies: agy stores every call on this machine under `~/.gemini/antigravity-cli`: `conversations/`,
`brain/<conversation id>/`, `implicit/*.pb`, `conversation_summaries.db` and `jetbox_summaries_proto.pb`; no flag
turns this off. A two-call canary (2026-10-06: a code word in one call, asked for in the next) found no carry-over
between calls.

## Public API
`AntigravityConnector` (entry point `ooat.connectors: antigravity`).

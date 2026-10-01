# ooat-adapter-codex

## Purpose
Model connector `prv.openai.subscription_cli`: runs `codex exec --json` on the operator's ChatGPT plan and its
existing login.

## How a call runs
- Prompt (system text first, then the request) on stdin, in an empty temporary directory with an allow-listed
  environment, `--disable shell_tool` (the agent cannot run commands or read local files; recorded in
  `tests/fixtures/no_shell.jsonl`), read-only sandbox as a second line, `--ephemeral`, `--ignore-rules`, plugins
  and apps disabled.
- Codex still loads the user's skill descriptions: a measured "OK" call carried about 17,000 input tokens. Fewer
  installed skills mean cheaper calls.
- The model per tier comes from `ooat.toml` (`models`); the manifest names none, so the connector is unused until
  the operator sets one and adds its price to `routing.json`.
- Usage: OpenAI counts cached input inside `input_tokens`, so `tokens_in` = `input_tokens` − `cached_input_tokens`,
  `tokens_cached` = `cached_input_tokens`, `tokens_out` = `output_tokens`; metering `reported`.
- Errors: `turn.failed` and top-level `error` events; usage limits → `QUOTA_EXHAUSTED`, login problems →
  `UNAVAILABLE`, others → `API_ERROR`. Item-level `error` items (warnings) are ignored.

## Public API
`CodexConnector` (entry point `ooat.connectors: codex`).

# ooat-adapter-claude-code

## Purpose
Model connector `prv.anthropic.subscription_cli`: runs Claude Code headless (`claude -p --output-format json`) on
the operator's Claude subscription and its existing login.

## How a call runs
- Prompt on stdin, in an empty temporary directory, with `--system-prompt`, `--setting-sources ""`,
  `--strict-mcp-config`, `--disable-slash-commands`, `--tools ""` and `--no-session-persistence`. This keeps the
  context to the request itself: a measured "OK" call carried about 500 tokens instead of about 50,000 with the
  user's default settings and memory.
- `--model` is the model the gateway routed (`claude-haiku-4-5-20251001`, `claude-sonnet-5-5`, `claude-opus-5-5`).
- Usage: `tokens_in` = `input_tokens` + `cache_creation_input_tokens`, `tokens_cached` = `cache_read_input_tokens`,
  `tokens_out` = `output_tokens`; metering `reported`.
- Errors: "Not logged in" → `UNAVAILABLE`; usage or rate limits → `QUOTA_EXHAUSTED`; other errors → `API_ERROR`.

## Manifest facts
Vendor entity and country are stated with sources; training on inputs, retention and processing region of
consumer plans are `null` (they depend on the operator's plan and settings) and `verified_on` is `null` until the
operator verifies them, so personal data stays refused (ADR 0010). `automation_permitted` is `unknown`: the
operator confirms the plan's terms when acknowledging.

## Public API
`ClaudeCodeConnector` (entry point `ooat.connectors: claude-code`).

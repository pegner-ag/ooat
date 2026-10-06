# Antigravity CLI connector — design

**Epic:** f1-skeleton · **Sub-project:** 03f · **Status:** design for owner review
**Spec:** §5 (implementation kinds), §6 (tiers), §9 (adapter acknowledgement); ADR 0005, ADR 0010, ADR 0012;
gateway design (`../task-03-provider-gateway/design.md`), connector pattern of `adapters/claude-code` and
`adapters/codex`.

## 1. Intent

The owner's third subscription: Google's Antigravity CLI (`agy`), which replaced Gemini CLI. One connector,
`prv.google.subscription_cli`, runs `agy` headless on the operator's Google login. It gives OOAT a model of a third
vendor, which spec §7 wants for a critic that is not of the worker's vendor (`routing.json` `critic_other_vendor`).

## 2. Facts measured on this server (2026-10-06, agy 1.3.0)

- Installed with `winget install Google.AntigravityCLI` to `%LOCALAPPDATA%\agy\bin\agy.exe`, a real executable,
  not a `.cmd` shim. A process started before the install does not have it on `PATH`.
- `agy models` lists what the account can use: Gemini 3.8 / 3.7 / 3.6 Flash (high, medium, low), Gemini 3.1 Pro
  (high, low), `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium`.
- Headless: `agy -p=<prompt> --output-format json --model <id>` prints one JSON object: `status` (`SUCCESS`,
  `ERROR`, …), `response`, `usage` (`input_tokens`, `output_tokens`, `thinking_tokens`, `cache_read_tokens`),
  `denied_actions`. Output reaches a pipe and a file (the old non-TTY bug, issue #76, does not occur).
- Prompt on stdin: `--input-format stream-json --output-format stream-json -p=""` reads one line
  `{"event":"user","message":{"content":"…"}}`; the last line is `{"event":"result","result":{…}}` with the same
  fields as the JSON output. `-p` without `=` swallows the next flag.
- Tools: in headless mode, anything that needs permission is soft-denied (exit 0, `response` empty,
  `denied_actions` names it): `run_command`, `write_file`, `read_url`, and reading a file outside the workspace.
  Reading a file **inside** the working directory is allowed without asking.
- A minimal call carries about 11,700 input tokens (the agent's own system prompt and tool list).
- The operator's `~/.gemini/antigravity-cli/settings.json` holds no `permissions.allow` rules today.
- Terms: Google support answered on 2026-09-15 that launching the official `agy` binary as a local child process
  in headless mode on the cached Google login "is fully supported" and uses the same limits as interactive use;
  extracting tokens or calling backend endpoints is not supported (forum link in §6).

## 3. How a call runs

- Prompt and system text go to stdin as one stream-json `user` message, never in argv (long prompts would hit the
  Windows command-line limit). The system text is sent first, marked as the operator's instructions.
- An empty temporary directory is the working directory, so the one tool allowed without asking (reading a file in
  the workspace) finds nothing. The allow-listed environment of `connectors/cli.py` applies (no API keys).
- Flags: `--input-format stream-json --output-format stream-json -p= --model <id> --sandbox
  --disable-slash-commands`. Never `--dangerously-skip-permissions`, `--add-dir`, `--continue` or `--conversation`.
- Detection: the connector refuses to run when `settings.json` has `permissions.allow` rules (the operator could
  have allowed commands or writes for every caller); `ooat connectors list` says so.
- The executable is found on `PATH`, else at `%LOCALAPPDATA%\agy\bin\agy.exe`.
- A reply with `denied_actions` and an empty `response` is returned as an empty answer, not as a provider failure:
  the deterministic output check finds it empty and it uses an attempt. As a provider failure it would pause the task
  (ADR 0014) and repeat on every resume, because the model would try the same tool again.
- Usage: `tokens_in` = `input_tokens` − `cache_read_tokens`, `tokens_cached` = `cache_read_tokens`,
  `tokens_out` = `output_tokens` + `thinking_tokens`; metering `reported`. Whether `input_tokens` includes cache
  reads is measured in the plan's first task, not assumed.
- Errors: "authentication required" → `UNAVAILABLE`; rate or quota limits → `QUOTA_EXHAUSTED`; `status` other
  than `SUCCESS`, a missing `result` line or unreadable JSON → `API_ERROR`; past the timeout → `TIMEOUT`.

## 4. Manifest, tiers and prices

- Vendor `google`, access `subscription_cli`, `automation_permitted` `permitted` with the forum answer as its
  source; the operator still confirms when acknowledging.
- Tiers as defaults the operator can change in `ooat.toml` `models`: economy `gemini-3.8-flash-low`, workhorse
  `gemini-3.8-flash-high`, frontier `gemini-3.1-pro-high`. The Claude and gpt-oss models are reachable by
  setting them, but they come from another model vendor through Google; their jurisdiction is Google's.
- Prices: shadow cost at Google's Gemini API list prices for the configured ids, with source and date, added only
  where Google publishes a price for that id; an id without a published price stays unpriced, so the gateway
  does not route to it.
- Data: `training_on_inputs`, `retention_days` and regions stay `null` until sourced: on a free individual account
  Google may use inputs to improve its products, on Google AI Pro / Ultra the terms differ. Allowed classes
  `public` and `internal`; client and personal data only with the operator's responsibility (ADR 0012), which
  `may_extend()` refuses while the provider may train.
- Local data: `agy` keeps conversations under `~/.gemini/antigravity-cli/conversations`, and no flag turns that
  off. The consequences card says so.

## 5. Scope and tests

One plan, `plan-03f.md`: the adapter package `adapters/antigravity-cli` (connector, manifest, description), the
prices in `routing.json`, entry point `ooat.connectors: antigravity`, unit tests on recorded stream-json fixtures
(success, denied tool, auth error, quota, malformed), and one live test skipped unless `OOAT_LIVE_AGY=1`.
Out of scope: allowing tools, Antigravity's IDE, remote control, MCP.

## 6. Owner questions

1. Which plan is the Google account on (free individual, Google AI Pro, Ultra)? It decides the data facts in §4.
2. Default models per tier as proposed in §4?

Sources: https://antigravity.google/docs/cli/headless/ ·
https://discuss.ai.google.dev/t/is-external-orchestration-of-antigravity-cli-headless-mode-supported-with-account-based-usage/183051

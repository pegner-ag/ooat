# ooat-adapter-anthropic-api

## Purpose
Model connector `prv.anthropic.api`: the Anthropic Messages API, metered per token. The fallback when a
subscription is out of quota (ADR 0005) and the F1 metered-API adapter.

## How a call runs
- `POST https://api.anthropic.com/v1/messages` with the standard library (no extra dependency); the key comes from
  the environment variable named by `secret_env` in `ooat.toml` and is sent only in the `x-api-key` header.
- Usage: `tokens_in` = `input_tokens` + `cache_creation_input_tokens`, `tokens_cached` = `cache_read_input_tokens`,
  `tokens_out` = `output_tokens`; metering `exact`.
- Errors: 401/403 → `UNAVAILABLE`, 429 → `QUOTA_EXHAUSTED` (with `retry-after` as reset time), timeout →
  `TIMEOUT`, unreachable → `UNAVAILABLE`, others → `API_ERROR`.

## Manifest facts
Commercial API terms: no training on inputs; personal data still needs the operator to verify the jurisdiction
(`verified_on` is `null` until then) and the routing policy's requirements.

## Public API
`AnthropicApiConnector(opener=..., clock=...)` (entry point `ooat.connectors: anthropic-api`).

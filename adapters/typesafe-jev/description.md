# ooat-adapter-typesafe-jev

## Purpose
Decision connector `prv.typesafe.api`: TypeSafe's System One API with the model Jev. It answers typed questions
(noul, choice, score) about a state for the `decision` tier: Gate step A, acceptance pre-checks, data-class
detection (ADR 0011). It never writes text or artifacts.

## How a call runs
- `POST https://api.typesafe.ai/v1/systemone` with the standard library; the key comes from the environment
  variable named by `secret_env` in `ooat.toml` and is sent only in the `Authorization: Bearer` header.
- Model `jev-latest` (alias); the reply names the version that answered (e.g. `jev-1.13.0`), which the gateway
  prices and records, so thresholds are calibrated per version.
- Question ids are sent as `q0`, `q1`, … and mapped back. A noul answer has no confidence field; the connector
  uses max(p, 1 − p).
- A state above about 32k tokens (characters / 3) is refused before sending (`UNAVAILABLE`, the gateway then
  falls back to the economy text tier).
- Errors: 401 and 529 → `UNAVAILABLE`, 429 → `QUOTA_EXHAUSTED` with a 60-second cool-down, timeout → `TIMEOUT`,
  unreachable or an unusable key value → `UNAVAILABLE`, 422 and anything else → `API_ERROR`.

## Manifest facts
US processing by TypeSafe AI, Inc.; inputs not used for training (privacy policy, models page). Allowed data
classes: `public`, `internal`. `verified_on` is `null` until the operator verifies the facts. Status `preview`
(early access); the gateway's economy fallback keeps the tier from depending on it alone. English is optimised,
other languages are "supported but less accurate": calibration on the operator's own tasks decides how far
answers are trusted.

## Public API
`JevConnector(opener=..., clock=...)` (entry point `ooat.connectors: typesafe-jev`); `parse_reply(data, wire)`.

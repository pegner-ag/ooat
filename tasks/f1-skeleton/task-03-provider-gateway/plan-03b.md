# Model Connectors (03b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the three F1 model connectors as separate packages — Claude Code CLI and Codex CLI on the operator's subscriptions, the Anthropic Messages API as metered fallback — plus a reference `catalog/routing.json` with sourced prices, so the gateway can route real calls.

**Architecture:** Each connector is its own distribution in `adapters/<name>/`, registered under the entry-point group `ooat.connectors` and depending only on `ooat-core` and the standard library. CLI connectors run through a shared `ooat_core.connectors.cli.run_cli()` (prompt on stdin, empty temporary working directory, typed failures) with flags that keep the call to the request itself. The gateway passes the routed model in `ModelRequest.model`. Parsing is tested on recorded CLI output; live calls run only with `OOAT_LIVE=1`.

**Tech Stack:** Python 3.12+ standard library (`subprocess`, `urllib`, `json`), hatchling, pytest.

**Spec:** `tasks/f1-skeleton/task-03-provider-gateway/design.md` (sections 3, 4, 8, 10); ADR 0005 (first adapters), ADR 0010; plan 03a (gateway core).

## Global Constraints

- `ooat-core` stays vendor-neutral; vendor names live only in `adapters/`.
- Connector packages depend on `ooat-core` and the standard library only.
- Manifests never guess: unknown facts are `null`; stated facts carry `source_urls`; `verified_on` stays `null` until the operator verifies (personal data refused until then, ADR 0010).
- Subscription manifests say `automation_permitted: "unknown"`; the operator confirms the plan's terms when acknowledging.
- Prompts go to CLIs through stdin, never the command line; CLIs run in an empty temporary directory.
- Secrets reach a connector only through the `SecretSource` it is given; no secret in any message, fixture or log.
- Token convention: `tokens_in` excludes cache reads and includes cache writes; `tokens_cached` is cache reads.
- Prices come from the provider's published list with `source` and `valid_from`; nothing is guessed.
- Tests that spend quota or credit run only with `OOAT_LIVE=1`; CI never sets it.

## Review Focus

1. A prompt with non-ASCII text (Czech) must reach the CLI unchanged on Windows — `test_stdin_reaches_the_process_and_stdout_comes_back` (Task 1).
2. A CLI that is not installed must yield `UNAVAILABLE`, not a crash, and `detect()` must say so offline — `test_missing_executable_is_unavailable` (Task 1), `test_conformance` (Tasks 2–4).
3. Codex warning items of type `error` (e.g. shortened skill descriptions) must not fail a successful call — `test_recorded_success_is_parsed_and_warnings_ignored` (Task 3).
4. An API error must never echo the API key — `test_transport_errors_are_typed_and_carry_no_key` (Task 4).
5. With the real catalog prices, the subscription must win over the API at equal list price, and client-confidential data must be refused while contracts cannot be verified — `test_subscription_wins_over_the_api_at_the_same_list_price`, `test_reference_policy_refuses_client_data_until_contracts_can_be_verified` (Task 5).

---

## File Structure

```
core/src/ooat_core/connectors/cli.py           run_cli(), find_executable(), CliResult (Task 1)
core/src/ooat_core/connectors/conformance.py   check_connector() (Task 1)
core/src/ooat_core/connectors/__init__.py      ModelRequest.model (Task 1)
core/src/ooat_core/gateway.py                  passes the routed model (Task 1)
adapters/claude-code/   pyproject.toml, description.md, src/ooat_adapter_claude_code/__init__.py, tests/ (Task 2)
adapters/codex/         pyproject.toml, description.md, src/ooat_adapter_codex/__init__.py, tests/ (Task 3)
adapters/anthropic-api/ pyproject.toml, description.md, src/ooat_adapter_anthropic_api/__init__.py, tests/ (Task 4)
adapters/integration_tests/test_gateway_with_connectors.py   (Task 5)
catalog/routing.json, catalog/tests/test_routing_catalog.py  (Task 5)
pytest.ini, .github/workflows/tests.yml                      (Task 5)
```

How to apply a "replace" step: the old text occurs exactly once; replace it with the new text. Files may have CRLF line endings on Windows — match the text, not the line endings. Install each new package with `python -m pip install -e <dir>` before running its tests.

---

### Task 1: Core support for connectors

**Files:**
- Create: `core/src/ooat_core/connectors/cli.py`, `core/src/ooat_core/connectors/conformance.py`
- Modify: `core/src/ooat_core/connectors/__init__.py`, `core/src/ooat_core/gateway.py`
- Test: `core/tests/test_connector_cli.py`, `core/tests/test_gateway.py`

**Interfaces:**
- Consumes: `ConnectorError`, `Detection`, `jurisdiction_fingerprint` (03a); `validate`; `FakeConnector` (`core/tests/connector_fakes.py`).
- Produces: `ModelRequest.model: str | None = None` (set by the gateway to the routed model); `CliResult(returncode, stdout, stderr)`; `find_executable(name) -> str | None`; `run_cli(args: list[str], stdin: str, timeout_s: float) -> CliResult` (`ConnectorError` `UNAVAILABLE` / `TIMEOUT`); `check_connector(connector) -> None` (`AssertionError` or `SpecValidationError`).

- [ ] **Step 1: Write the failing tests**

`core/tests/test_connector_cli.py`:

```python
import sys

import pytest
from connector_fakes import FakeConnector

from ooat_core.connectors import ConnectorError, cli
from ooat_core.connectors.conformance import check_connector


def python(code):
    # UTF-8 mode: the vendor CLIs (Node, Rust) read stdin as UTF-8; a Windows Python child would use the locale.
    return [sys.executable, "-X", "utf8", "-c", code]


def test_stdin_reaches_the_process_and_stdout_comes_back():
    result = cli.run_cli(python("import sys; print(sys.stdin.read().upper())"), "dobrý den", 30)
    assert result.returncode == 0 and result.stdout.strip() == "DOBRÝ DEN"


def test_process_runs_in_an_empty_directory():
    result = cli.run_cli(python("import os; print(len(os.listdir('.')))"), "", 30)
    assert result.stdout.strip() == "0"


def test_missing_executable_is_unavailable():
    with pytest.raises(ConnectorError) as info:
        cli.run_cli(["ooat-no-such-cli"], "", 30)
    assert info.value.code == "UNAVAILABLE"


def test_slow_process_times_out():
    with pytest.raises(ConnectorError) as info:
        cli.run_cli(python("import time; time.sleep(5)"), "", 0.5)
    assert info.value.code == "TIMEOUT"


def test_conformance_accepts_the_fake_connector():
    check_connector(FakeConnector())


def test_conformance_rejects_an_invalid_manifest():
    connector = FakeConnector()
    del connector.manifest["jurisdiction"]
    with pytest.raises(Exception):
        check_connector(connector)
```

In `core/tests/test_gateway.py`, replace:

```python
# Review Focus ---
```

with:

```python
# Routed model ------------------------------------------------------------------------------------------------

def test_connector_receives_the_routed_model():
    manifest = fake_manifest("prv.cli.subscription_cli", "subscription_cli", tiers={"workhorse": None})
    setup = ready(manifest, settings={"prv.cli.subscription_cli": {"models": {"workhorse": "fake-model"}}})
    setup.gateway.call(setup.request())
    assert setup.connectors[0].calls[0].model == "fake-model"


# Review Focus ---
```


- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests -q`
Expected: FAIL — `test_connector_cli.py` cannot import `ooat_core.connectors.cli`; `test_connector_receives_the_routed_model` fails (`ModelRequest` has no `model`).

- [ ] **Step 3: Implement** — `core/src/ooat_core/connectors/cli.py`:

```python
"""Running a vendor CLI as a connector backend (vendor-neutral helper for subscription_cli connectors).

The prompt goes through stdin (not visible in process lists, no command-line length limit), the process runs in an
empty temporary directory (no project files or instructions are picked up), and failures become ConnectorErrors.
"""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from . import ConnectorError


@dataclass(frozen=True)
class CliResult:
    returncode: int
    stdout: str
    stderr: str


def find_executable(name: str) -> str | None:
    return shutil.which(name)


def run_cli(args: list[str], stdin: str, timeout_s: float) -> CliResult:
    """Run args[0] with stdin; UNAVAILABLE if it is not installed, TIMEOUT if it runs past timeout_s."""
    executable = find_executable(args[0])
    if executable is None:
        raise ConnectorError("UNAVAILABLE", f"{args[0]} is not installed or not on PATH")
    with tempfile.TemporaryDirectory(prefix="ooat-cli-") as workdir:
        try:
            completed = subprocess.run([executable, *args[1:]], input=stdin, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=timeout_s, cwd=workdir)
        except subprocess.TimeoutExpired:
            raise ConnectorError("TIMEOUT", f"{args[0]} did not finish within {timeout_s:g} s") from None
        except OSError as error:
            raise ConnectorError("UNAVAILABLE", f"{args[0]} could not be started: {error}") from None
    return CliResult(completed.returncode, completed.stdout, completed.stderr)
```

`core/src/ooat_core/connectors/conformance.py`:

```python
"""Checks every model connector package runs in its own tests (gateway design §10)."""

import time

from ..validation import validate
from . import Detection, jurisdiction_fingerprint


def check_connector(connector) -> None:
    """Raise AssertionError unless the connector meets the contract every OOAT connector must meet."""
    assert connector.kind == "model", "only model connectors are supported"
    validate("provider", connector.manifest)
    assert len(jurisdiction_fingerprint(connector.manifest)) == 64
    started = time.monotonic()
    detection = connector.detect()
    assert isinstance(detection, Detection) and detection.detail, "detect() returns a Detection with a detail"
    assert time.monotonic() - started < 5, "detect() must be fast and offline"
```

In `core/src/ooat_core/connectors/__init__.py`, replace:

```python
    timeout_s: float = 600
```

with:

```python
    timeout_s: float = 600
    model: str | None = None  # set by the gateway to the routed model; connectors must use it
```

In `core/src/ooat_core/gateway.py`, replace:

```python
            response = candidate.connector.complete(request, _OwnSecret(self._secrets, connector_id))
```

with:

```python
            routed = dataclasses.replace(request, model=candidate.estimate.model)
            response = candidate.connector.complete(routed, _OwnSecret(self._secrets, connector_id))
```


- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/connectors core/src/ooat_core/gateway.py core/tests/test_connector_cli.py core/tests/test_gateway.py
git commit -m "core: routed model for connectors, CLI runner and connector conformance check"
```

---

### Task 2: Claude Code connector

**Files:**
- Create: `adapters/claude-code/pyproject.toml`, `adapters/claude-code/description.md`, `adapters/claude-code/src/ooat_adapter_claude_code/__init__.py`
- Create: `adapters/claude-code/tests/fixtures/success.json` (recorded), `not_logged_in.json` (recorded), `usage_limit_synthetic.json`
- Test: `adapters/claude-code/tests/test_claude_code_connector.py`

**Interfaces:**
- Consumes: `run_cli`, `find_executable`, `CliResult` (Task 1); `ConnectorError`, `Detection`, `ModelRequest`, `ModelResponse`; `check_connector`; `Registry.discover()`.
- Produces: `ClaudeCodeConnector(executable="claude")` with `MANIFEST` id `prv.anthropic.subscription_cli` (tiers economy `claude-haiku-4-5-20251001`, workhorse `claude-sonnet-5-5`, frontier `claude-opus-5-5`); `parse_result(stdout, stderr, requested_model) -> ModelResponse`; entry point `ooat.connectors: claude-code`.

- [ ] **Step 1: Create the package skeleton and fixtures, then write the failing test**

`adapters/claude-code/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "ooat-adapter-claude-code"
version = "0.1.0"
description = "OOAT model connector for Claude Code in headless mode on a Claude subscription."
readme = "description.md"
requires-python = ">=3.12"
license = "Apache-2.0"
dependencies = ["ooat-core"]

[project.entry-points."ooat.connectors"]
claude-code = "ooat_adapter_claude_code:ClaudeCodeConnector"

[tool.hatch.build.targets.wheel]
packages = ["src/ooat_adapter_claude_code"]
```

`adapters/claude-code/description.md`:

```markdown
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
```

`adapters/claude-code/src/ooat_adapter_claude_code/__init__.py` (empty placeholder so the package installs):

```python
"""OOAT model connector for Claude Code headless on a Claude subscription (prv.anthropic.subscription_cli)."""
```

`adapters/claude-code/tests/fixtures/success.json` (recorded 2026-10-01, Claude Code 2.1.286, minimal-context flags):

```json
{
 "duration_api_ms": 1956,
 "stop_reason": "end_turn",
 "session_id": "5a48542f-5089-4e89-bbe5-a507d5af3922",
 "total_cost_usd": 0.004240000000000001,
 "usage": {
  "input_tokens": 2,
  "cache_creation_input_tokens": 519,
  "cache_read_input_tokens": 0,
  "output_tokens": 4,
  "output_tokens_details": {
   "thinking_tokens": 0
  },
  "server_tool_use": {
   "web_search_requests": 0,
   "web_fetch_requests": 0
  },
  "service_tier": "standard",
  "cache_creation": {
   "ephemeral_1h_input_tokens": 519,
   "ephemeral_5m_input_tokens": 0
  },
  "inference_geo": "not_available",
  "iterations": [
   {
    "input_tokens": 2,
    "output_tokens": 4,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 519,
    "cache_creation": {
     "ephemeral_5m_input_tokens": 0,
     "ephemeral_1h_input_tokens": 519
    },
    "type": "message"
   }
  ],
  "speed": "standard",
  "fallback_credit": null
 },
 "modelUsage": {
  "claude-opus-5-5": {
   "inputTokens": 2,
   "outputTokens": 4,
   "cacheReadInputTokens": 0,
   "cacheCreationInputTokens": 519,
   "webSearchRequests": 0,
   "costUSD": 0.004240000000000001,
   "contextWindow": 1000000,
   "maxOutputTokens": 128000,
   "thinkingTokens": 0,
   "canonicalModel": "claude-opus-5-5",
   "provider": "firstParty",
   "costBasis": "list"
  }
 },
 "permission_denials": [],
 "terminal_reason": "completed",
 "fast_mode_state": "off",
 "fast_mode_disabled_reason": "sdk_opt_in_required",
 "subagent_stats": {
  "spawned": 0,
  "requested": {
   "background": 0,
   "foreground": 0,
   "unset": 0
  },
  "started_in_background": 0,
  "max_depth": 0,
  "spawned_by_subagents": 0,
  "completed": 0,
  "failed": 0,
  "killed": {
   "parent": 0,
   "user": 0,
   "system": 0
  },
  "refused": {
   "depth_limit": 0,
   "concurrency_limit": 0,
   "budget": 0
  },
  "by_type": {}
 },
 "is_error": false,
 "num_turns": 1,
 "subtype": "success",
 "api_error_status": null,
 "result": "OK",
 "ttft_ms": 4392,
 "type": "result",
 "duration_ms": 4530,
 "uuid": "69c80e0a-6bba-47b3-b782-b8f7592cc000",
 "ttft_stream_ms": 4390,
 "time_to_request_ms": 2503,
 "first_content_frame_ms": 4390,
 "queued_turn_count": 0,
 "result_index": 0
}
```

`adapters/claude-code/tests/fixtures/not_logged_in.json` (recorded with `--bare`, which skips the subscription login):

```json
{
 "duration_api_ms": 0,
 "stop_reason": "stop_sequence",
 "session_id": "f171b657-110d-4e6a-b771-1fd3399cc04d",
 "total_cost_usd": 0,
 "usage": {
  "output_tokens_details": {
   "thinking_tokens": 0
  },
  "input_tokens": 0,
  "cache_creation_input_tokens": 0,
  "cache_read_input_tokens": 0,
  "output_tokens": 0,
  "server_tool_use": {
   "web_search_requests": 0,
   "web_fetch_requests": 0
  },
  "service_tier": "standard",
  "cache_creation": {
   "ephemeral_1h_input_tokens": 0,
   "ephemeral_5m_input_tokens": 0
  },
  "inference_geo": "",
  "iterations": [],
  "speed": "standard",
  "fallback_credit": null
 },
 "modelUsage": {},
 "permission_denials": [],
 "terminal_reason": "api_error",
 "fast_mode_state": "off",
 "fast_mode_disabled_reason": "sdk_opt_in_required",
 "subagent_stats": {
  "spawned": 0,
  "requested": {
   "background": 0,
   "foreground": 0,
   "unset": 0
  },
  "started_in_background": 0,
  "max_depth": 0,
  "spawned_by_subagents": 0,
  "completed": 0,
  "failed": 0,
  "killed": {
   "parent": 0,
   "user": 0,
   "system": 0
  },
  "refused": {
   "depth_limit": 0,
   "concurrency_limit": 0,
   "budget": 0
  },
  "by_type": {}
 },
 "is_error": true,
 "num_turns": 1,
 "subtype": "success",
 "api_error_status": null,
 "result": "Not logged in \u00b7 Please run /login",
 "type": "result",
 "duration_ms": 392,
 "uuid": "30c50a60-f2d0-4884-98e2-0175e738397a",
 "queued_turn_count": 0,
 "result_index": 0
}
```

`adapters/claude-code/tests/fixtures/usage_limit_synthetic.json`:

```json
{
 "duration_api_ms": 0,
 "stop_reason": "stop_sequence",
 "session_id": "f171b657-110d-4e6a-b771-1fd3399cc04d",
 "total_cost_usd": 0,
 "usage": {
  "output_tokens_details": {
   "thinking_tokens": 0
  },
  "input_tokens": 0,
  "cache_creation_input_tokens": 0,
  "cache_read_input_tokens": 0,
  "output_tokens": 0,
  "server_tool_use": {
   "web_search_requests": 0,
   "web_fetch_requests": 0
  },
  "service_tier": "standard",
  "cache_creation": {
   "ephemeral_1h_input_tokens": 0,
   "ephemeral_5m_input_tokens": 0
  },
  "inference_geo": "",
  "iterations": [],
  "speed": "standard",
  "fallback_credit": null
 },
 "modelUsage": {},
 "permission_denials": [],
 "terminal_reason": "api_error",
 "fast_mode_state": "off",
 "fast_mode_disabled_reason": "sdk_opt_in_required",
 "subagent_stats": {
  "spawned": 0,
  "requested": {
   "background": 0,
   "foreground": 0,
   "unset": 0
  },
  "started_in_background": 0,
  "max_depth": 0,
  "spawned_by_subagents": 0,
  "completed": 0,
  "failed": 0,
  "killed": {
   "parent": 0,
   "user": 0,
   "system": 0
  },
  "refused": {
   "depth_limit": 0,
   "concurrency_limit": 0,
   "budget": 0
  },
  "by_type": {}
 },
 "is_error": true,
 "num_turns": 1,
 "subtype": "success",
 "api_error_status": null,
 "result": "Claude usage limit reached. Your limit will reset at 5pm (Europe/Prague).",
 "type": "result",
 "duration_ms": 392,
 "uuid": "30c50a60-f2d0-4884-98e2-0175e738397a",
 "queued_turn_count": 0,
 "result_index": 0,
 "_note": "synthetic: shape of a recorded error result, message of a usage-limit error"
}
```

`adapters/claude-code/tests/test_claude_code_connector.py`:

```python
import os
from pathlib import Path

import pytest

import ooat_adapter_claude_code as adapter
from ooat_adapter_claude_code import ClaudeCodeConnector, parse_result
from ooat_core.connectors import ConnectorError, ModelRequest
from ooat_core.connectors.cli import CliResult
from ooat_core.connectors.conformance import check_connector
from ooat_core.connectors.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def request(**extra):
    return ModelRequest(tier="workhorse", prompt="Reply with OK.", data_class="internal", **extra)


def test_conformance():
    check_connector(ClaudeCodeConnector())


def test_entry_point_is_registered():
    assert isinstance(Registry.discover().get("prv.anthropic.subscription_cli"), ClaudeCodeConnector)


def test_recorded_success_is_parsed():
    response = parse_result(fixture("success.json"), "", "claude-sonnet-5-5")
    assert response.text == "OK"
    assert response.model == "claude-opus-5-5"  # the recording ran on the CLI's default model
    assert (response.tokens_in, response.tokens_cached, response.tokens_out) == (2 + 519, 0, 4)
    assert response.metering == "reported"


@pytest.mark.parametrize("name, code", [("not_logged_in.json", "UNAVAILABLE"),
                                        ("usage_limit_synthetic.json", "QUOTA_EXHAUSTED")])
def test_recorded_errors_are_typed(name, code):
    with pytest.raises(ConnectorError) as info:
        parse_result(fixture(name), "", "claude-sonnet-5-5")
    assert info.value.code == code


def test_unreadable_output_is_an_api_error():
    with pytest.raises(ConnectorError) as info:
        parse_result("Error: something broke", "stack trace", "claude-sonnet-5-5")
    assert info.value.code == "API_ERROR"


def test_call_isolates_the_cli_and_uses_the_routed_model(monkeypatch):
    seen = {}

    def fake_run(args, stdin, timeout_s):
        seen.update(args=args, stdin=stdin, timeout=timeout_s)
        return CliResult(0, fixture("success.json"), "")

    monkeypatch.setattr(adapter, "run_cli", fake_run)
    ClaudeCodeConnector().complete(request(model="claude-haiku-4-5-20251001", system="Be brief.", timeout_s=60), None)
    args = seen["args"]
    assert args[:4] == ["claude", "-p", "--output-format", "json"]
    assert args[args.index("--model") + 1] == "claude-haiku-4-5-20251001"
    assert args[args.index("--system-prompt") + 1] == "Be brief."
    for flag in ("--setting-sources", "--strict-mcp-config", "--disable-slash-commands", "--tools",
                 "--no-session-persistence"):
        assert flag in args
    assert args[args.index("--tools") + 1] == "" and args[args.index("--setting-sources") + 1] == ""
    assert seen["stdin"] == "Reply with OK." and seen["timeout"] == 60
    assert "Reply with OK." not in args  # the prompt never appears on the command line


@pytest.mark.skipif(os.environ.get("OOAT_LIVE") != "1", reason="spends subscription quota; set OOAT_LIVE=1")
def test_live_minimal_call():
    response = ClaudeCodeConnector().complete(
        ModelRequest(tier="economy", prompt="Reply with the single word OK.", data_class="public",
                     model="claude-haiku-4-5-20251001", timeout_s=120), None)
    assert "OK" in response.text and response.tokens_out and response.tokens_in < 5000
```

Install: `python -m pip install -e adapters/claude-code`

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest adapters/claude-code -q`
Expected: FAIL — `ImportError: cannot import name 'ClaudeCodeConnector'`

- [ ] **Step 3: Implement** — replace `adapters/claude-code/src/ooat_adapter_claude_code/__init__.py` with:

```python
"""OOAT model connector for Claude Code headless on a Claude subscription (prv.anthropic.subscription_cli)."""

import json
import re

from ooat_core.connectors import ConnectorError, Detection, ModelRequest, ModelResponse
from ooat_core.connectors.cli import find_executable, run_cli

MANIFEST = {
    "id": "prv.anthropic.subscription_cli",
    "version": "0.1.0",
    "vendor": "anthropic",
    "access": "subscription_cli",
    "runner": "claude-code-headless",
    "tiers": {"economy": "claude-haiku-4-5-20251001", "workhorse": "claude-sonnet-5-5", "frontier": "claude-opus-5-5"},
    "metering": "reported",
    "plan": {"fee_usd_month": None, "quota_window_hours": None, "units": "token_equivalent"},
    "automation_permitted": "unknown",
    "concurrency": 1,
    "data_policy": {"training_on_inputs": None, "retention_days": None, "allowed_data_classes": ["public", "internal"]},
    "features": {"tool_use": True, "vision": True, "context_tokens": None},
    "jurisdiction": {
        "vendor_entity": "Anthropic, PBC",
        "vendor_country": "US",
        "host_entity": None,
        "processing_regions": None,
        "eu_region_available": None,
        "model_origin_country": "US",
        "training_on_inputs": None,
        "retention": None,
        "zero_retention_available": None,
        "transfer_notes": None,
        "source_urls": ["https://www.anthropic.com/legal/consumer-terms", "https://www.anthropic.com/legal/privacy"],
        "verified_on": None,
    },
}
DEFAULT_SYSTEM = "You are a precise assistant. Answer only what is asked."
# Flags that keep the call to the request itself: no user settings, memory, MCP servers, skills or tools.
ISOLATION = ["--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands", "--tools", "",
             "--no-session-persistence"]
_QUOTA = re.compile(r"usage limit|rate limit|limit reached|too many requests", re.IGNORECASE)
_LOGIN = re.compile(r"not logged in|/login|authenticat|invalid api key", re.IGNORECASE)


class ClaudeCodeConnector:
    kind = "model"

    def __init__(self, executable: str = "claude"):
        self.manifest = MANIFEST
        self._executable = executable

    def detect(self) -> Detection:
        path = find_executable(self._executable)
        if path is None:
            return Detection(False, f"{self._executable} is not on PATH; install Claude Code and log in")
        return Detection(True, f"{self._executable} found at {path}; uses its existing login")

    def complete(self, request: ModelRequest, secrets) -> ModelResponse:
        model = request.model or self.manifest["tiers"][request.tier]
        args = [self._executable, "-p", "--output-format", "json", "--model", model,
                "--system-prompt", request.system or DEFAULT_SYSTEM, *ISOLATION]
        result = run_cli(args, request.prompt, request.timeout_s)
        return parse_result(result.stdout, result.stderr, model)


def parse_result(stdout: str, stderr: str, requested_model: str) -> ModelResponse:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        raise ConnectorError("API_ERROR", f"unreadable claude output: {(stderr or stdout)[-300:]}") from None
    if data.get("is_error") or data.get("subtype") != "success":
        message = str(data.get("result") or stderr or "claude reported an error")[:500]
        if _LOGIN.search(message):
            raise ConnectorError("UNAVAILABLE", message)
        if data.get("api_error_status") == 429 or _QUOTA.search(message):
            raise ConnectorError("QUOTA_EXHAUSTED", message)
        raise ConnectorError("API_ERROR", message)
    usage = data.get("usage") or {}
    models = list(data.get("modelUsage") or {})
    model = models[0].split("[")[0] if models else requested_model  # "claude-opus-5-5[1m]" -> "claude-opus-5-5"
    return ModelResponse(
        text=str(data.get("result", "")),
        model=model,
        tokens_in=usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0),
        tokens_cached=usage.get("cache_read_input_tokens", 0),
        tokens_out=usage.get("output_tokens"),
        quota_units=None,
        metering="reported",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest adapters/claude-code -q`
Expected: 7 passed, 1 skipped (live). Optional, spends about 0.001 USD of subscription quota: `OOAT_LIVE=1 python -m pytest adapters/claude-code -q -k live` → 1 passed.

- [ ] **Step 5: Commit**

```bash
git add adapters/claude-code
git commit -m "adapters: Claude Code connector (headless, isolated, subscription)"
```

---

### Task 3: Codex connector

**Files:**
- Create: `adapters/codex/pyproject.toml`, `adapters/codex/description.md`, `adapters/codex/src/ooat_adapter_codex/__init__.py`
- Create: `adapters/codex/tests/fixtures/success.jsonl` (recorded), `usage_limit_synthetic.jsonl`, `logged_out_synthetic.jsonl`, `README.md`
- Test: `adapters/codex/tests/test_codex_connector.py`

**Interfaces:**
- Consumes: as Task 2.
- Produces: `CodexConnector(executable="codex")` with `MANIFEST` id `prv.openai.subscription_cli` (tiers `{"workhorse": None}`; the operator sets the model in `ooat.toml`); `parse_events(stdout, stderr, model) -> ModelResponse`; entry point `ooat.connectors: codex`.

- [ ] **Step 1: Create the package skeleton and fixtures, then write the failing test**

`adapters/codex/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "ooat-adapter-codex"
version = "0.1.0"
description = "OOAT model connector for OpenAI Codex CLI (codex exec) on a ChatGPT plan."
readme = "description.md"
requires-python = ">=3.12"
license = "Apache-2.0"
dependencies = ["ooat-core"]

[project.entry-points."ooat.connectors"]
codex = "ooat_adapter_codex:CodexConnector"

[tool.hatch.build.targets.wheel]
packages = ["src/ooat_adapter_codex"]
```

`adapters/codex/description.md`:

```markdown
# ooat-adapter-codex

## Purpose
Model connector `prv.openai.subscription_cli`: runs `codex exec --json` on the operator's ChatGPT plan and its
existing login.

## How a call runs
- Prompt (system text first, then the request) on stdin, in an empty temporary directory, read-only sandbox,
  `--ephemeral`, `--ignore-rules`, plugins and apps disabled.
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
```

`adapters/codex/src/ooat_adapter_codex/__init__.py` (placeholder):

```python
"""OOAT model connector for OpenAI Codex CLI (`codex exec --json`) on a ChatGPT plan (prv.openai.subscription_cli)."""
```

`adapters/codex/tests/fixtures/success.jsonl` (recorded 2026-10-01, codex-cli 0.153.4):

```json
{"type":"thread.started","thread_id":"01a0f753-7f54-77b2-977e-a3b7198878da"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"error","message":"Skill descriptions were shortened to fit the skills context budget. Codex can still see every skill, but some descriptions are shorter. Disable unused skills or plugins to leave more room for the rest."}}
{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"OK"}}
{"type":"turn.completed","usage":{"input_tokens":16762,"cached_input_tokens":2432,"cache_write_input_tokens":0,"output_tokens":5,"reasoning_output_tokens":0}}
```

`adapters/codex/tests/fixtures/usage_limit_synthetic.jsonl`:

```json
{"type":"thread.started","thread_id":"00000000-0000-0000-0000-000000000000"}
{"type":"turn.started"}
{"type": "turn.failed", "error": {"message": "You've hit your usage limit. Try again in 3 hours."}}
```

`adapters/codex/tests/fixtures/logged_out_synthetic.jsonl`:

```json
{"type":"thread.started","thread_id":"00000000-0000-0000-0000-000000000000"}
{"type":"turn.started"}
{"type": "error", "message": "Not logged in. Run codex login."}
```

`adapters/codex/tests/fixtures/README.md`:

```markdown
`success.jsonl` is a recorded `codex exec --json` run (codex-cli 0.153.4, 2026-10-01).
Files named `*_synthetic.jsonl` are hand-written error events in the documented event shapes; replace them
with recordings when such errors are observed.
```

`adapters/codex/tests/test_codex_connector.py`:

```python
import os
from pathlib import Path

import pytest

import ooat_adapter_codex as adapter
from ooat_adapter_codex import CodexConnector, parse_events
from ooat_core.connectors import ConnectorError, ModelRequest
from ooat_core.connectors.cli import CliResult
from ooat_core.connectors.conformance import check_connector
from ooat_core.connectors.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_conformance():
    check_connector(CodexConnector())


def test_entry_point_is_registered():
    assert isinstance(Registry.discover().get("prv.openai.subscription_cli"), CodexConnector)


def test_recorded_success_is_parsed_and_warnings_ignored():
    response = parse_events(fixture("success.jsonl"), "", "gpt-test")
    assert response.text == "OK"
    assert (response.tokens_in, response.tokens_cached, response.tokens_out) == (16762 - 2432, 2432, 5)
    assert response.model == "gpt-test" and response.metering == "reported"


@pytest.mark.parametrize("name, code", [("usage_limit_synthetic.jsonl", "QUOTA_EXHAUSTED"),
                                        ("logged_out_synthetic.jsonl", "UNAVAILABLE")])
def test_error_events_are_typed(name, code):
    with pytest.raises(ConnectorError) as info:
        parse_events(fixture(name), "", "gpt-test")
    assert info.value.code == code


def test_output_without_a_completed_turn_is_an_api_error():
    with pytest.raises(ConnectorError) as info:
        parse_events('{"type":"turn.started"}\nnot json\n', "crashed", "gpt-test")
    assert info.value.code == "API_ERROR"


def test_call_needs_a_configured_model():
    with pytest.raises(ConnectorError) as info:
        CodexConnector().complete(ModelRequest(tier="workhorse", prompt="x", data_class="internal"), None)
    assert info.value.code == "UNAVAILABLE"


def test_call_isolates_the_cli_and_sends_system_and_prompt_on_stdin(monkeypatch):
    seen = {}

    def fake_run(args, stdin, timeout_s):
        seen.update(args=args, stdin=stdin)
        return CliResult(0, fixture("success.jsonl"), "")

    monkeypatch.setattr(adapter, "run_cli", fake_run)
    CodexConnector().complete(ModelRequest(tier="workhorse", prompt="Reply with OK.", data_class="internal",
                                           system="Be brief.", model="gpt-test"), None)
    args = seen["args"]
    assert args[:2] == ["codex", "exec"] and args[-1] == "-"
    assert args[args.index("-m") + 1] == "gpt-test"
    assert args[args.index("--sandbox") + 1] == "read-only"
    for flag in ("--json", "--ephemeral", "--ignore-rules", "--skip-git-repo-check"):
        assert flag in args
    assert seen["stdin"] == "Be brief.\n\nReply with OK."


@pytest.mark.skipif(os.environ.get("OOAT_LIVE") != "1" or not os.environ.get("OOAT_CODEX_MODEL"),
                    reason="spends subscription quota; set OOAT_LIVE=1 and OOAT_CODEX_MODEL")
def test_live_minimal_call():
    response = CodexConnector().complete(
        ModelRequest(tier="workhorse", prompt="Reply with the single word OK.", data_class="public",
                     model=os.environ["OOAT_CODEX_MODEL"], timeout_s=180), None)
    assert "OK" in response.text and response.tokens_out
```

Install: `python -m pip install -e adapters/codex`

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest adapters/codex -q`
Expected: FAIL — `ImportError: cannot import name 'CodexConnector'`

- [ ] **Step 3: Implement** — replace `adapters/codex/src/ooat_adapter_codex/__init__.py` with:

```python
"""OOAT model connector for OpenAI Codex CLI (`codex exec --json`) on a ChatGPT plan (prv.openai.subscription_cli)."""

import json
import re

from ooat_core.connectors import ConnectorError, Detection, ModelRequest, ModelResponse
from ooat_core.connectors.cli import find_executable, run_cli

MANIFEST = {
    "id": "prv.openai.subscription_cli",
    "version": "0.1.0",
    "vendor": "openai",
    "access": "subscription_cli",
    "runner": "codex-exec",
    # Model ids are set by the operator in ooat.toml ([connectors."prv.openai.subscription_cli"] models), not guessed.
    "tiers": {"workhorse": None},
    "metering": "reported",
    "plan": {"fee_usd_month": None, "quota_window_hours": None, "units": "token_equivalent"},
    "automation_permitted": "unknown",
    "concurrency": 1,
    "data_policy": {"training_on_inputs": None, "retention_days": None, "allowed_data_classes": ["public", "internal"]},
    "features": {"tool_use": True, "vision": True, "context_tokens": None},
    "jurisdiction": {
        "vendor_entity": None,
        "vendor_country": "US",
        "host_entity": None,
        "processing_regions": None,
        "eu_region_available": None,
        "model_origin_country": "US",
        "training_on_inputs": None,
        "retention": None,
        "zero_retention_available": None,
        "transfer_notes": None,
        "source_urls": ["https://openai.com/policies/terms-of-use/", "https://openai.com/policies/privacy-policy/"],
        "verified_on": None,
    },
}
# Read-only sandbox, no session files, no repository rules, no plugins or apps; the prompt comes from stdin ("-").
ISOLATION = ["--json", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only", "--ignore-rules",
             "--disable", "plugins", "--disable", "apps"]
_QUOTA = re.compile(r"usage limit|rate limit|limit reached|too many requests|429", re.IGNORECASE)
_LOGIN = re.compile(r"log ?in|logged out|unauthori[sz]ed|401|authentication", re.IGNORECASE)


class CodexConnector:
    kind = "model"

    def __init__(self, executable: str = "codex"):
        self.manifest = MANIFEST
        self._executable = executable

    def detect(self) -> Detection:
        path = find_executable(self._executable)
        if path is None:
            return Detection(False, f"{self._executable} is not on PATH; install Codex CLI and log in")
        return Detection(True, f"{self._executable} found at {path}; uses its existing login")

    def complete(self, request: ModelRequest, secrets) -> ModelResponse:
        model = request.model or self.manifest["tiers"].get(request.tier)
        if model is None:
            raise ConnectorError("UNAVAILABLE", f"no model configured for tier {request.tier}")
        prompt = f"{request.system}\n\n{request.prompt}" if request.system else request.prompt  # no system flag
        result = run_cli([self._executable, "exec", *ISOLATION, "-m", model, "-"], prompt, request.timeout_s)
        return parse_events(result.stdout, result.stderr, model)


def _failure(message: str) -> ConnectorError:
    message = message[:500]
    if _QUOTA.search(message):
        return ConnectorError("QUOTA_EXHAUSTED", message)
    if _LOGIN.search(message):
        return ConnectorError("UNAVAILABLE", message)
    return ConnectorError("API_ERROR", message)


def parse_events(stdout: str, stderr: str, model: str) -> ModelResponse:
    messages, usage = [], None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # codex may print plain progress lines; only JSON events count
        kind = event.get("type")
        if kind == "item.completed" and event.get("item", {}).get("type") == "agent_message":
            messages.append(str(event["item"].get("text", "")))
        elif kind == "turn.completed":
            usage = event.get("usage") or {}
        elif kind == "turn.failed":
            raise _failure(str((event.get("error") or {}).get("message", "codex turn failed")))
        elif kind == "error":  # a top-level error event; item-level "error" items are warnings, not failures
            raise _failure(str(event.get("message", "codex reported an error")))
    if usage is None:
        raise _failure(f"codex ended without a completed turn: {stderr[-300:]}")
    cached = usage.get("cached_input_tokens", 0)
    return ModelResponse(
        text=messages[-1] if messages else "",
        model=model,
        tokens_in=usage.get("input_tokens", 0) - cached,  # OpenAI counts cached input inside input_tokens
        tokens_cached=cached,
        tokens_out=usage.get("output_tokens"),
        quota_units=None,
        metering="reported",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest adapters/codex -q`
Expected: 8 passed, 1 skipped (live; needs `OOAT_LIVE=1` and `OOAT_CODEX_MODEL`).

- [ ] **Step 5: Commit**

```bash
git add adapters/codex
git commit -m "adapters: Codex CLI connector (codex exec --json, subscription)"
```

---

### Task 4: Anthropic API connector

**Files:**
- Create: `adapters/anthropic-api/pyproject.toml`, `adapters/anthropic-api/description.md`, `adapters/anthropic-api/src/ooat_adapter_anthropic_api/__init__.py`
- Test: `adapters/anthropic-api/tests/test_anthropic_api_connector.py`

**Interfaces:**
- Consumes: `ConnectorError`, `Detection`, `ModelRequest`, `ModelResponse`, `check_connector`, `Registry`, `parse_config`, `SecretResolver`.
- Produces: `AnthropicApiConnector(opener=<urllib>, clock=<utc now>)` with `MANIFEST` id `prv.anthropic.api` (same tier models as Task 2, `automation_permitted: "permitted"`, `training_on_inputs: false`); `parse_message(data: dict) -> ModelResponse`; entry point `ooat.connectors: anthropic-api`.

- [ ] **Step 1: Create the package skeleton, then write the failing test**

`adapters/anthropic-api/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "ooat-adapter-anthropic-api"
version = "0.1.0"
description = "OOAT model connector for the Anthropic Messages API (metered)."
readme = "description.md"
requires-python = ">=3.12"
license = "Apache-2.0"
dependencies = ["ooat-core"]

[project.entry-points."ooat.connectors"]
anthropic-api = "ooat_adapter_anthropic_api:AnthropicApiConnector"

[tool.hatch.build.targets.wheel]
packages = ["src/ooat_adapter_anthropic_api"]
```

`adapters/anthropic-api/description.md`:

```markdown
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
```

`adapters/anthropic-api/src/ooat_adapter_anthropic_api/__init__.py` (placeholder):

```python
"""OOAT model connector for the Anthropic Messages API (prv.anthropic.api), metered per token."""
```

`adapters/anthropic-api/tests/test_anthropic_api_connector.py`:

```python
import io
import json
import os
import socket
import urllib.error
from datetime import datetime, timezone
from email.message import Message

import pytest

from ooat_adapter_anthropic_api import AnthropicApiConnector, parse_message
from ooat_core.config import parse_config
from ooat_core.connectors import ConnectorError, ModelRequest
from ooat_core.connectors.conformance import check_connector
from ooat_core.connectors.registry import Registry
from ooat_core.secrets import SecretResolver

KEY = "sk-ant-test-0123456789"
MESSAGE = {
    "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-haiku-4-5-20251001",
    "content": [{"type": "text", "text": "Dobrý den"}], "stop_reason": "end_turn",
    "usage": {"input_tokens": 12, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100,
              "output_tokens": 5},
}


class Secrets:
    def get(self, connector_id):
        assert connector_id == "prv.anthropic.api"
        return KEY


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def request(**extra):
    return ModelRequest(tier="economy", prompt="Pozdrav.", data_class="internal", **extra)


def http_error(code, message, headers=None):
    header_map = Message()
    for name, value in (headers or {}).items():
        header_map[name] = value
    body = io.BytesIO(json.dumps({"type": "error", "error": {"type": "x", "message": message}}).encode())
    return urllib.error.HTTPError("https://api.anthropic.com/v1/messages", code, message, header_map, body)


def test_conformance():
    check_connector(AnthropicApiConnector())


def test_entry_point_is_registered():
    assert isinstance(Registry.discover().get("prv.anthropic.api"), AnthropicApiConnector)


def test_request_shape_and_parsed_response():
    sent = {}

    def opener(req, timeout):
        sent.update(url=req.full_url, headers=dict(req.header_items()), body=json.loads(req.data), timeout=timeout)
        return Reply(json.dumps(MESSAGE).encode())

    response = AnthropicApiConnector(opener).complete(request(system="Stručně.", max_output_tokens=50,
                                                              model="claude-haiku-4-5-20251001"), Secrets())
    assert sent["url"] == "https://api.anthropic.com/v1/messages"
    assert sent["headers"]["X-api-key"] == KEY and sent["headers"]["Anthropic-version"] == "2023-06-01"
    assert sent["body"] == {"model": "claude-haiku-4-5-20251001", "max_tokens": 50, "system": "Stručně.",
                            "messages": [{"role": "user", "content": "Pozdrav."}]}
    assert response.text == "Dobrý den" and response.metering == "exact"
    assert (response.tokens_in, response.tokens_cached, response.tokens_out) == (12, 100, 5)


@pytest.mark.parametrize("error, code", [
    (http_error(401, "invalid x-api-key"), "UNAVAILABLE"),
    (http_error(529, "overloaded"), "API_ERROR"),
    (urllib.error.URLError("name resolution failed"), "UNAVAILABLE"),
    (socket.timeout("timed out"), "TIMEOUT"),
])
def test_transport_errors_are_typed_and_carry_no_key(error, code):
    def opener(req, timeout):
        raise error

    with pytest.raises(ConnectorError) as info:
        AnthropicApiConnector(opener).complete(request(), Secrets())
    assert info.value.code == code and KEY not in str(info.value)


def test_rate_limit_reports_the_reset_time():
    def opener(req, timeout):
        raise http_error(429, "rate limited", {"retry-after": "30"})

    clock = lambda: datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)  # noqa: E731
    with pytest.raises(ConnectorError) as info:
        AnthropicApiConnector(opener, clock).complete(request(), Secrets())
    assert info.value.code == "QUOTA_EXHAUSTED" and info.value.resets_at == "2026-10-01T12:00:30Z"


def test_parse_message_joins_text_blocks():
    data = dict(MESSAGE, content=[{"type": "text", "text": "a"}, {"type": "tool_use"}, {"type": "text", "text": "b"}])
    assert parse_message(data).text == "ab"


@pytest.mark.skipif(os.environ.get("OOAT_LIVE") != "1" or not os.environ.get("ANTHROPIC_API_KEY"),
                    reason="spends API credit; set OOAT_LIVE=1 and ANTHROPIC_API_KEY")
def test_live_minimal_call():
    secrets = SecretResolver(parse_config({"connectors": {"prv.anthropic.api": {"secret_env": "ANTHROPIC_API_KEY"}}}))
    response = AnthropicApiConnector().complete(
        ModelRequest(tier="economy", prompt="Reply with the single word OK.", data_class="public",
                     max_output_tokens=10, timeout_s=60), secrets)
    assert "OK" in response.text and response.tokens_out
```

Install: `python -m pip install -e adapters/anthropic-api`

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest adapters/anthropic-api -q`
Expected: FAIL — `ImportError: cannot import name 'AnthropicApiConnector'`

- [ ] **Step 3: Implement** — replace `adapters/anthropic-api/src/ooat_adapter_anthropic_api/__init__.py` with:

```python
"""OOAT model connector for the Anthropic Messages API (prv.anthropic.api), metered per token."""

import json
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from ooat_core.connectors import ConnectorError, Detection, ModelRequest, ModelResponse

MANIFEST = {
    "id": "prv.anthropic.api",
    "version": "0.1.0",
    "vendor": "anthropic",
    "access": "api",
    "tiers": {"economy": "claude-haiku-4-5-20251001", "workhorse": "claude-sonnet-5-5", "frontier": "claude-opus-5-5"},
    "metering": "exact",
    "automation_permitted": "permitted",
    "concurrency": 4,
    "data_policy": {"training_on_inputs": False, "retention_days": None,
                    "allowed_data_classes": ["public", "internal", "client_confidential", "personal"]},
    "features": {"tool_use": True, "vision": True, "context_tokens": 1000000},
    "jurisdiction": {
        "vendor_entity": "Anthropic, PBC",
        "vendor_country": "US",
        "host_entity": "Anthropic, PBC",
        "processing_regions": None,
        "eu_region_available": None,
        "model_origin_country": "US",
        "training_on_inputs": False,
        "retention": None,
        "zero_retention_available": None,
        "transfer_notes": "EEA personal data leaves the EEA; the operator needs a transfer mechanism.",
        "source_urls": ["https://www.anthropic.com/legal/commercial-terms", "https://www.anthropic.com/legal/privacy"],
        "verified_on": None,
    },
}
URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


def _default_open(req: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout)


class AnthropicApiConnector:
    kind = "model"

    def __init__(self, opener=_default_open, clock=lambda: datetime.now(timezone.utc)):
        self.manifest = MANIFEST
        self._open = opener  # injectable transport for tests; production uses urllib
        self._clock = clock

    def detect(self) -> Detection:
        return Detection(True, "HTTPS client ready; the API key comes from the secret_env set for prv.anthropic.api")

    def complete(self, request: ModelRequest, secrets) -> ModelResponse:
        key = secrets.get(self.manifest["id"])
        model = request.model or self.manifest["tiers"][request.tier]
        body = {"model": model, "max_tokens": request.max_output_tokens,
                "messages": [{"role": "user", "content": request.prompt}]}
        if request.system:
            body["system"] = request.system
        req = urllib.request.Request(URL, data=json.dumps(body).encode("utf-8"), method="POST", headers={
            "x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json"})
        try:
            with self._open(req, request.timeout_s) as reply:
                data = json.loads(reply.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise self._http_error(error) from None
        except (socket.timeout, TimeoutError):
            raise ConnectorError("TIMEOUT", f"no answer within {request.timeout_s:g} s") from None
        except urllib.error.URLError as error:
            raise ConnectorError("UNAVAILABLE", f"cannot reach the API: {error.reason}") from None
        return parse_message(data)

    def _http_error(self, error: urllib.error.HTTPError) -> ConnectorError:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("error", {}).get("message", "")
        except (ValueError, AttributeError, OSError):
            detail = ""
        message = f"HTTP {error.code}: {detail}"[:500]
        if error.code in (401, 403):
            return ConnectorError("UNAVAILABLE", message)
        if error.code == 429:
            retry_after = (error.headers or {}).get("retry-after")
            resets_at = None
            if retry_after and retry_after.isdigit():
                resets_at = (self._clock() + timedelta(seconds=int(retry_after))).strftime("%Y-%m-%dT%H:%M:%SZ")
            return ConnectorError("QUOTA_EXHAUSTED", message, resets_at=resets_at)
        return ConnectorError("API_ERROR", message)


def parse_message(data: dict) -> ModelResponse:
    usage = data.get("usage") or {}
    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    return ModelResponse(
        text=text,
        model=str(data.get("model", "")),
        tokens_in=usage.get("input_tokens", 0) + (usage.get("cache_creation_input_tokens") or 0),
        tokens_cached=usage.get("cache_read_input_tokens") or 0,
        tokens_out=usage.get("output_tokens"),
        quota_units=None,
        metering="exact",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest adapters/anthropic-api -q`
Expected: 9 passed, 1 skipped (live; needs `OOAT_LIVE=1` and `ANTHROPIC_API_KEY`).

- [ ] **Step 5: Commit**

```bash
git add adapters/anthropic-api
git commit -m "adapters: Anthropic Messages API connector (metered fallback)"
```

---

### Task 5: Reference routing, integration and CI

**Files:**
- Create: `catalog/routing.json`, `catalog/tests/test_routing_catalog.py`, `adapters/integration_tests/test_gateway_with_connectors.py`
- Modify: `pytest.ini`, `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: the three connectors (Tasks 2–4); `Gateway`, `load_routing`, `Ledger`, `new_event`, `jurisdiction_fingerprint`.
- Produces: `catalog/routing.json` with Anthropic list prices (source `https://platform.claude.com/docs/en/about-claude/pricing`, valid from 2026-10-01) and the reference data-class policy; CI installs and tests the adapters.

- [ ] **Step 1: Write the failing tests**

`catalog/tests/test_routing_catalog.py`:

```python
import json
from datetime import date
from pathlib import Path

from ooat_core.routing import RoutingPolicy

ROUTING = Path(__file__).resolve().parents[1] / "routing.json"


def test_reference_routing_is_valid_and_sourced():
    document = json.loads(ROUTING.read_text(encoding="utf-8"))
    RoutingPolicy(document)  # validates against spec/schemas/routing.schema.json
    for price in document["prices"]:
        assert price["source"].startswith("https://")
        date.fromisoformat(price["valid_from"])


def test_reference_policy_keeps_client_and_personal_data_off_unverified_routes():
    policy = json.loads(ROUTING.read_text(encoding="utf-8"))["data_class_policy"]
    for data_class in ("client_confidential", "personal"):
        assert policy[data_class].get("require_no_training") and policy[data_class].get("require_contract")
    assert policy["special_category"].get("require_verified_redaction")
```

`adapters/integration_tests/test_gateway_with_connectors.py`:

```python
"""The gateway with the real connector packages and catalog/routing.json; no network, no CLI runs."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

import ooat_adapter_claude_code as claude_code
from ooat_adapter_anthropic_api import AnthropicApiConnector
from ooat_adapter_claude_code import ClaudeCodeConnector
from ooat_adapter_codex import CodexConnector
from ooat_core.config import parse_config
from ooat_core.connectors import ModelRequest, jurisdiction_fingerprint
from ooat_core.connectors.cli import CliResult
from ooat_core.connectors.registry import Registry
from ooat_core.gateway import Gateway, GatewayError
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger, new_event
from ooat_core.routing import load_routing

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
RECORDED = (ROOT / "adapters" / "claude-code" / "tests" / "fixtures" / "success.json").read_text(encoding="utf-8")


def unused_opener(req, timeout):
    raise AssertionError("the API must not be called when the subscription wins")


@pytest.fixture
def setup():
    ledger = Ledger.open("sqlite:///:memory:")
    connectors = [ClaudeCodeConnector(), CodexConnector(), AnthropicApiConnector(unused_opener)]
    for connector in connectors:
        ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor={"kind": "hil", "id": "operator"}, body={
            "adapter": connector.manifest["id"], "manifest_version": connector.manifest["version"],
            "allowed_data_classes": ["public", "internal"], "operator": "Operator", "automation_confirmed": True,
            "jurisdiction_sha256": jurisdiction_fingerprint(connector.manifest)}))
    config = parse_config({"connectors": {"prv.anthropic.api": {"secret_env": "ANTHROPIC_API_KEY"}}})
    gateway = Gateway(ledger, Registry(connectors), load_routing(ROOT / "catalog" / "routing.json"), config,
                      clock=lambda: NOW)
    yield gateway
    ledger.close()


def request(data_class="internal"):
    return ModelRequest(tier="economy", prompt="Reply with OK.", data_class=data_class, task=new_id("tsk"))


def test_subscription_wins_over_the_api_at_the_same_list_price(setup):
    estimate = setup.estimate(request())
    assert estimate.connector == "prv.anthropic.subscription_cli"
    assert estimate.model == "claude-haiku-4-5-20251001"


def test_codex_waits_for_a_configured_model_and_price(setup):
    only_codex = Gateway(setup._ledger, Registry([CodexConnector()]), setup._routing, setup._config,
                         clock=lambda: NOW)
    with pytest.raises(GatewayError) as info:
        only_codex.estimate(ModelRequest(tier="workhorse", prompt="x", data_class="internal"))
    assert "no model configured" in info.value.trace[0]


def test_call_runs_the_cli_once_and_meters_a_shadow_price(setup, monkeypatch):
    calls = []
    monkeypatch.setattr(claude_code, "run_cli", lambda args, stdin, timeout: calls.append(args) or CliResult(0, RECORDED, ""))
    result = setup.call(request())
    assert len(calls) == 1 and calls[0][calls[0].index("--model") + 1] == "claude-haiku-4-5-20251001"
    assert result.cost["adapter"] == "prv.anthropic.subscription_cli" and result.cost["basis"] == "shadow"
    assert result.cost["usd"] > 0 and result.cost["estimated_usd"] > 0


def test_reference_policy_refuses_client_data_until_contracts_can_be_verified(setup):
    with pytest.raises(GatewayError) as info:
        setup.estimate(request("client_confidential"))
    assert info.value.code == "NOT_PERMITTED"
```

In `pytest.ini`, replace:

```ini
testpaths = spec/tests catalog/tests core/tests
```

with:

```ini
testpaths = spec/tests catalog/tests core/tests adapters
```

In `.github/workflows/tests.yml`, replace:

```yaml
      - run: python -m pip install -e core
```

with:

```yaml
      - run: python -m pip install -e core
      - run: python -m pip install -e adapters/claude-code -e adapters/codex -e adapters/anthropic-api
```


- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest catalog/tests adapters/integration_tests -q`
Expected: FAIL — `FileNotFoundError` for `catalog/routing.json`.

- [ ] **Step 3: Create the reference routing** — `catalog/routing.json`:

```json
{
  "version": "0.1.0",
  "prices": [
    {
      "adapter": "prv.anthropic.api",
      "model": "claude-haiku-4-5-20251001",
      "usd_per_mtok_in": 1,
      "usd_per_mtok_cached": 0.1,
      "usd_per_mtok_out": 5,
      "valid_from": "2026-10-01",
      "source": "https://platform.claude.com/docs/en/about-claude/pricing"
    },
    {
      "adapter": "prv.anthropic.api",
      "model": "claude-sonnet-5-5",
      "usd_per_mtok_in": 2,
      "usd_per_mtok_cached": 0.2,
      "usd_per_mtok_out": 10,
      "valid_from": "2026-10-01",
      "source": "https://platform.claude.com/docs/en/about-claude/pricing"
    },
    {
      "adapter": "prv.anthropic.api",
      "model": "claude-opus-5-5",
      "usd_per_mtok_in": 4,
      "usd_per_mtok_cached": 0.2,
      "usd_per_mtok_out": 20,
      "valid_from": "2026-10-01",
      "source": "https://platform.claude.com/docs/en/about-claude/pricing"
    }
  ],
  "data_class_policy": {
    "public": {
      "allowed": true
    },
    "internal": {
      "allowed": true
    },
    "client_confidential": {
      "allowed": true,
      "require_no_training": true,
      "require_known_region": true,
      "require_contract": true
    },
    "personal": {
      "allowed": true,
      "require_no_training": true,
      "require_known_region": true,
      "require_contract": true
    },
    "special_category": {
      "allowed": true,
      "require_verified_redaction": true
    }
  },
  "critic_other_vendor": true,
  "display": {
    "currency": "CZK",
    "fx_source": "https://www.cnb.cz/"
  }
}
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest -q`
Expected: PASS (live tests skipped)

- [ ] **Step 5: Commit**

```bash
git add catalog/routing.json catalog/tests/test_routing_catalog.py adapters/integration_tests pytest.ini .github/workflows/tests.yml
git commit -m "catalog: reference routing with sourced prices; gateway integration tests; CI installs adapters"
```

---

### Task 6: Documentation

**Files:**
- Modify: `docs/description.md`, `core/description.md`, `tasks/f1-skeleton/README.md`, `tasks/f1-skeleton/task-03d-gateway-hardening/task.md`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: As-is documentation.

- [ ] **Step 1: Update the documents**

In `docs/description.md`, replace:

```markdown
- Ledger backend: SQLite, selected by URL (ADR 0008)
```

with:

```markdown
- Ledger backend: SQLite, selected by URL (ADR 0008)
- Model connectors as separate packages in `adapters/`: Claude Code CLI, Codex CLI, Anthropic Messages API
```

In `docs/description.md`, replace:

```markdown
- `sdk/`, `adapters/`, `dashboard/`, `evals/` — empty
```

with:

```markdown
- `adapters/` — connector packages `ooat-adapter-claude-code`, `ooat-adapter-codex`, `ooat-adapter-anthropic-api`
  (each with `description.md`), `integration_tests/` (gateway with the real connectors, no network)
- `catalog/routing.json` — reference routing policy: Anthropic list prices with source and date, data-class policy
- `sdk/`, `dashboard/`, `evals/` — empty
```

In `docs/description.md`, replace:

```markdown
Dev dependencies: `requirements-dev.txt`; run `python -m pytest` (paths in `pytest.ini`).
```

with:

```markdown
Prices and the data-class policy: `catalog/routing.json`. Dev dependencies: `requirements-dev.txt`, then
`pip install -e core -e adapters/claude-code -e adapters/codex -e adapters/anthropic-api`; run `python -m pytest`
(paths in `pytest.ini`). Tests that spend quota or credit run only with `OOAT_LIVE=1`.
```

In `core/description.md`, replace:

```markdown
  the ledger, quota cool-down, pins, cheapest connector, contract budget, cost record with `estimated_usd`
```

with:

```markdown
  the ledger, quota cool-down, pins, cheapest connector, contract budget, cost record with `estimated_usd`;
  passes the routed model to the connector in `ModelRequest.model`
- `connectors/cli.py` — `run_cli()`: vendor CLI with the prompt on stdin, in an empty temporary directory,
  typed `UNAVAILABLE` / `TIMEOUT` failures
- `connectors/conformance.py` — `check_connector()`: the contract every connector package tests
```

In `tasks/f1-skeleton/README.md`, replace:

```markdown
03b connectors (Claude Code CLI, Codex CLI, Anthropic API), 03c `ooat connectors` + consequences card | 01 | 03b next |
```

with:

```markdown
03b connectors (Claude Code CLI, Codex CLI, Anthropic API) (done), 03c `ooat connectors` + consequences card | 01 | 03c next |
```

In `tasks/f1-skeleton/task-03d-gateway-hardening/task.md`, replace:

```markdown
- [ ] Token accounting convention defined and documented: `tokens_in` excludes cached input; `tokens_cached`
      is billed at the cached price (settled with the connectors in 03b).
```

with:

```markdown
- [x] Token accounting convention: `tokens_in` excludes cache reads and includes cache writes; `tokens_cached`
      is cache reads, billed at the cached price (documented in each connector's `description.md`, 03b).
- [ ] Cache writes are billed at the base input price; Anthropic charges 1.25x (5-minute) or 2x (1-hour).
```


- [ ] **Step 2: Run all tests**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add docs/description.md core/description.md tasks/f1-skeleton/README.md tasks/f1-skeleton/task-03d-gateway-hardening/task.md
git commit -m "docs: describe the model connectors and the reference routing"
```

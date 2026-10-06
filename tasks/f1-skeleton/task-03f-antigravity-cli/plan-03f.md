# Antigravity CLI Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A model connector `prv.google.subscription_cli` that runs Google's Antigravity CLI (`agy`) headless on
the operator's Google login, with no tools, priced at Gemini API list prices as shadow cost.

**Architecture:** A new adapter package `adapters/antigravity-cli` beside `adapters/codex`, built the same way:
a manifest, `detect()`, `complete()` through `ooat_core.connectors.cli.run_cli` (empty temp dir, allow-listed
environment), and a pure `parse_stream()` tested on recorded stream-json. Before every call the connector checks
that the operator's agy setup gives the agent no extra tools (permission allow rules, MCP servers, plugins).
Prices go into `catalog/routing.json`; no change to `ooat-core`.

**Tech Stack:** Python 3.12+, hatchling, pytest; agy 1.3.0 on Windows Server 2025.

**Spec:** `tasks/f1-skeleton/task-03f-antigravity-cli/design.md` (design 03f; spec §5, §6, §9; ADR 0005, 0010,
0012, 0014).

## Global Constraints

- Language (D3): code, docs and commits in English.
- Secrets live only in the provider gateway: the connector never reads `~/.gemini/oauth_creds.json`,
  `google_accounts.json` or any token; it starts the official `agy` binary and nothing else (design §2, terms).
- Unknown manifest values stay `null`, never guessed; `automation_permitted` is `"unknown"` (design §4).
- `training_on_inputs` is `true`; allowed data classes `public`, `internal` (design §4).
- The prompt never goes into argv; it goes to stdin as one stream-json message (design §3).
- Never pass `--dangerously-skip-permissions`, `--add-dir`, `--continue`, `--conversation` (design §3).
- Default tiers: economy `gemini-3.8-flash-low`, workhorse `gemini-3.8-flash-high`, frontier
  `gemini-3.1-pro-high` (owner, 2026-10-06).
- Prices only from https://ai.google.dev/gemini-api/docs/pricing with `valid_from`; an id without a published
  price stays unpriced.
- Recorded fixtures must not carry the operator's paths, account e-mail or conversation ids of real work: replace
  the `cwd` with `C:\\work` and ids with `00000000-0000-0000-0000-000000000000`.

## Review Focus

1. The operator adds an MCP server or a plugin to agy after OOAT was enabled → the next call refuses
   (`UNAVAILABLE`, naming the cause) instead of letting the agent use it (Task 3 test
   `test_an_mcp_server_added_later_stops_the_next_call`).
2. The model tries a tool and every tool is denied → an empty answer, not a provider failure, so the task does
   not pause and repeat forever (Task 2 test `test_a_denied_tool_gives_an_empty_answer_not_an_error`).
3. `agy` is installed but not on the `PATH` of the running process (installed after the shell started) → the
   connector finds `%LOCALAPPDATA%\agy\bin\agy.exe` (Task 3 test `test_agy_is_found_in_its_install_folder`).
4. A prompt with quotes, newlines and Czech characters → reaches agy unchanged as JSON on stdin (Task 3 test
   `test_prompt_and_system_go_to_stdin_as_one_stream_json_message`).
5. `agy` prints progress lines or a huge `init` event before the result → ignored; only the `result` event counts
   (Task 2 test `test_non_json_lines_and_init_are_ignored`).

## Owner decision (2026-10-06): option C

The gateway picks the cheapest permitted connector per tier. At these prices Gemini is cheaper than Claude Code in
every tier, so with Antigravity enabled for `internal` data the worker and the critic would move to a provider that
trains on inputs. The owner chose **C**: the operator enables Antigravity for `public` data only, so `internal`
work stays on Claude Code. The code is the same; only the acknowledgement differs.
Facts for later: a `[routing.pin]` is per tier (it would pin the critic too) and does not fall back when the pinned
connector cools down; nothing in `core/` reads `routing.json` `critic_other_vendor` yet (recorded in the 03d list).

## File Structure

```
adapters/antigravity-cli/
  pyproject.toml                      package ooat-adapter-antigravity-cli, entry point antigravity
  description.md                      how a call runs, measured facts, manifest facts
  src/ooat_adapter_antigravity_cli/__init__.py   MANIFEST, AntigravityConnector, parse_stream, exposed_tools
  tests/test_antigravity_connector.py
  tests/fixtures/README.md, success.jsonl, denied_tool.jsonl, auth_error_synthetic.jsonl,
                 quota_synthetic.jsonl
catalog/routing.json                  three Gemini price rows (+ the 2027 Flash rows)
adapters/integration_tests/test_gateway_with_connectors.py   routing with the real routing.json
.github/workflows/tests.yml, README.md, docs/description.md  install line and package list
tasks/f1-skeleton/README.md           03f status
```

---

### Task 1: Package, manifest and conformance

**Files:**
- Create: `adapters/antigravity-cli/pyproject.toml`, `adapters/antigravity-cli/description.md`,
  `adapters/antigravity-cli/src/ooat_adapter_antigravity_cli/__init__.py`
- Test: `adapters/antigravity-cli/tests/test_antigravity_connector.py`

**Interfaces:**
- Produces: `MANIFEST: dict`; `class AntigravityConnector(executable: str | None = None,
  settings_path: Path | None = None)` with `kind = "model"`, `manifest`, `detect() -> Detection`,
  `complete(request: ModelRequest, secrets) -> ModelResponse`; entry point `ooat.connectors: antigravity`.

- [ ] **Step 1: Write the failing tests**

```python
import os
from pathlib import Path

import pytest

import ooat_adapter_antigravity_cli as adapter
from ooat_adapter_antigravity_cli import MANIFEST, AntigravityConnector
from ooat_core.connectors import ConnectorError, ModelRequest
from ooat_core.connectors.cli import CliResult
from ooat_core.connectors.conformance import check_connector
from ooat_core.connectors.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_conformance():
    check_connector(AntigravityConnector(executable="agy-not-installed"))


def test_entry_point_is_registered():
    assert isinstance(Registry.discover().get("prv.google.subscription_cli"), AntigravityConnector)


def test_manifest_states_training_and_leaves_unknowns_null():
    assert MANIFEST["data_policy"]["training_on_inputs"] is True
    assert MANIFEST["jurisdiction"]["training_on_inputs"] is True
    assert MANIFEST["data_policy"]["allowed_data_classes"] == ["public", "internal"]
    assert MANIFEST["automation_permitted"] == "unknown"
    assert MANIFEST["jurisdiction"]["verified_on"] is None and MANIFEST["jurisdiction"]["vendor_entity"] is None
    assert MANIFEST["tiers"] == {"economy": "gemini-3.8-flash-low", "workhorse": "gemini-3.8-flash-high",
                                 "frontier": "gemini-3.1-pro-high"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest adapters/antigravity-cli -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ooat_adapter_antigravity_cli'`

- [ ] **Step 3: Write the package**

`adapters/antigravity-cli/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "ooat-adapter-antigravity-cli"
version = "0.1.0"
description = "OOAT model connector for Google Antigravity CLI (agy) on a Google account."
readme = "description.md"
requires-python = ">=3.12"
license = "Apache-2.0"
dependencies = ["ooat-core"]

[project.entry-points."ooat.connectors"]
antigravity = "ooat_adapter_antigravity_cli:AntigravityConnector"

[tool.hatch.build.targets.wheel]
packages = ["src/ooat_adapter_antigravity_cli"]
```

`src/ooat_adapter_antigravity_cli/__init__.py` (this task: manifest and the class shell; `complete()` and the
parser follow in Tasks 2 and 3):

```python
"""OOAT model connector for Google Antigravity CLI (`agy -p`, stream-json) on a Google login
(prv.google.subscription_cli)."""

import json
import os
import re
from pathlib import Path

from ooat_core.connectors import ConnectorError, Detection, ModelRequest, ModelResponse
from ooat_core.connectors.cli import find_executable, run_cli

TERMS = "https://antigravity.google/terms/"
FORUM = ("https://discuss.ai.google.dev/t/is-external-orchestration-of-antigravity-cli-headless-mode-supported-"
         "with-account-based-usage/183051")
MANIFEST = {
    "id": "prv.google.subscription_cli",
    "version": "0.1.0",
    "vendor": "google",
    "access": "subscription_cli",
    "runner": "agy-print",
    "tiers": {"economy": "gemini-3.8-flash-low", "workhorse": "gemini-3.8-flash-high",
              "frontier": "gemini-3.1-pro-high"},
    "metering": "reported",
    "plan": {"fee_usd_month": None, "quota_window_hours": None, "units": "token_equivalent"},
    # The forum reply allows a local child process on the cached login; the terms forbid "third party software"
    # without naming this case. The operator decides when acknowledging (design 03f §2, §6).
    "automation_permitted": "unknown",
    "concurrency": 1,
    "data_policy": {"training_on_inputs": True, "retention_days": None, "allowed_data_classes": ["public", "internal"]},
    "features": {"tool_use": None, "vision": None, "context_tokens": None},  # unsourced facts stay null
    "jurisdiction": {
        "vendor_entity": None,
        "vendor_country": None,
        "host_entity": None,
        "processing_regions": None,
        "eu_region_available": None,
        "model_origin_country": "US",
        "training_on_inputs": True,
        "retention": None,
        "zero_retention_available": None,
        "transfer_notes": (
            "Terms: Google uses Interactions to improve its products and machine learning, and its staff and "
            "contractors may review them; a setting changes how they are used, but OOAT cannot see it. "
            "Automated use: a Google support reply on the forum (2026-09-15) calls a local child process on the "
            "cached login supported; the terms forbid third-party software accessing the service. agy keeps "
            "conversations locally under ~/.gemini/antigravity-cli/conversations."),
        "source_urls": [TERMS, "https://policies.google.com/privacy", FORUM],
        "verified_on": None,
    },
}


class AntigravityConnector:
    kind = "model"

    def __init__(self, executable: str | None = None, settings_path: Path | None = None):
        self.manifest = MANIFEST
        self._executable = executable
        self._settings = settings_path or Path.home() / ".gemini" / "antigravity-cli" / "settings.json"

    def detect(self) -> Detection:
        path = self._find()
        if path is None:
            return Detection(False, "agy is not installed; install Antigravity CLI and log in once with agy")
        return Detection(True, f"agy found at {path}; uses its existing Google login")

    def _find(self) -> str | None:
        if self._executable is not None:
            return find_executable(self._executable)
        installed = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
        return find_executable("agy") or (str(installed) if os.environ.get("LOCALAPPDATA") and installed.is_file()
                                          else None)

    def complete(self, request: ModelRequest, secrets) -> ModelResponse:
        raise ConnectorError("UNAVAILABLE", "not implemented yet")
```

`description.md`: copy design 03f §2–§4 as "How a call runs" and "Manifest facts" in the style of
`adapters/codex/description.md` (Purpose, How a call runs, Manifest facts, Public API `AntigravityConnector`,
entry point `ooat.connectors: antigravity`).

- [ ] **Step 4: Install and run**

Run: `.venv\Scripts\python.exe -m pip install -e adapters/antigravity-cli` then
`.venv\Scripts\python.exe -m pytest adapters/antigravity-cli -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add adapters/antigravity-cli/pyproject.toml adapters/antigravity-cli/description.md adapters/antigravity-cli/src/ooat_adapter_antigravity_cli/__init__.py adapters/antigravity-cli/tests/test_antigravity_connector.py
git commit -m "feat(adapters): Antigravity CLI connector package and manifest (03f)"
```

---

### Task 2: Measurements, fixtures and `parse_stream`

**Files:**
- Create: `adapters/antigravity-cli/tests/fixtures/README.md`, `success.jsonl`, `denied_tool.jsonl`,
  `auth_error_synthetic.jsonl`, `quota_synthetic.jsonl`
- Modify: `adapters/antigravity-cli/src/ooat_adapter_antigravity_cli/__init__.py`,
  `adapters/antigravity-cli/description.md`
- Test: `adapters/antigravity-cli/tests/test_antigravity_connector.py`

**Interfaces:**
- Produces: `parse_stream(stdout: str, stderr: str, returncode: int, model: str) -> ModelResponse`; raises
  `ConnectorError` (`QUOTA_EXHAUSTED`, `UNAVAILABLE`, `API_ERROR`).

- [ ] **Step 1: Measure and record (live, in an empty scratch folder outside the repo)**

Run each from an empty folder with the full path to agy and save stdout:

```bash
A="$LOCALAPPDATA/agy/bin/agy.exe"
echo '{"event":"user","message":{"content":"Reply with the single word OK."}}' | "$A" --input-format stream-json --output-format stream-json --model gemini-3.8-flash-low --sandbox --disable-slash-commands -p= > success.jsonl
echo '{"event":"user","message":{"content":"Run the shell command whoami and print its output."}}' | "$A" --input-format stream-json --output-format stream-json --model gemini-3.8-flash-low --sandbox --disable-slash-commands -p= > denied_tool.jsonl
```

Then measure, and write each result into `description.md` ("Measured on <date>, agy <version>"):
1. `--sandbox` alone and `--disable-slash-commands` alone on the `whoami` prompt: is the command still denied
   without `--sandbox`? (Either way both flags stay; record what each does.)
2. Cache counting: send the same ~3,000-character prompt twice within a minute; if the second `usage` shows
   `cache_read_tokens > 0` and `input_tokens` did not drop by about that amount, `input_tokens` includes cache
   reads → keep `INPUT_INCLUDES_CACHE = True` below; otherwise set it to `False`.
3. `-p=` with an empty value and stream-json input: confirm the stdin message is the whole prompt.
4. Settings keys: read the agy settings reference (https://antigravity.google/docs/cli/) for every key that
   approves tools, runs hooks or adds tool sources. If a harmless key appears in the operator's `settings.json`
   besides `model` and `trustedWorkspaces`, add it to `SAFE_SETTINGS` with its doc reference in `description.md`;
   never add one that approves tools or runs commands.

Sanitise both fixtures (Global Constraints: `cwd` → `C:\\work`, every `conversation_id` → zeros; delete the long
`tools` array from the `init` event, keeping `"tools":["view_file"]`). Write the synthetic fixtures:

`auth_error_synthetic.jsonl`:
```
{"event":"result","result":{"conversation_id":"00000000-0000-0000-0000-000000000000","status":"ERROR","error":"authentication required: run agy once to sign in","response":"","num_turns":0}}
```
`quota_synthetic.jsonl`:
```
{"event":"result","result":{"conversation_id":"00000000-0000-0000-0000-000000000000","status":"ERROR","error":"You have reached your rate limit. Try again later.","response":"","num_turns":0}}
```
`README.md`: which files are recorded (agy version, date, command) and which are synthetic, as in
`adapters/codex/tests/fixtures/README.md`.

- [ ] **Step 2: Write the failing tests** (change the import line to
  `from ooat_adapter_antigravity_cli import MANIFEST, AntigravityConnector, parse_stream`)

```python
def test_recorded_success_is_parsed():
    response = parse_stream(fixture("success.jsonl"), "", 0, "gemini-3.8-flash-low")
    assert response.text.strip() == "OK"
    assert response.model == "gemini-3.8-flash-low" and response.metering == "reported"
    assert response.tokens_in > 0 and response.tokens_out >= 1 and response.tokens_cached >= 0


def test_a_denied_tool_gives_an_empty_answer_not_an_error():
    response = parse_stream(fixture("denied_tool.jsonl"), "jetski: no output produced - a tool required the "
                            "\"command\" permission", 0, "gemini-3.8-flash-low")
    assert response.text == ""  # the output check counts it as an empty attempt; the task does not pause


@pytest.mark.parametrize("name, code", [("auth_error_synthetic.jsonl", "UNAVAILABLE"),
                                        ("quota_synthetic.jsonl", "QUOTA_EXHAUSTED")])
def test_error_results_are_typed(name, code):
    with pytest.raises(ConnectorError) as info:
        parse_stream(fixture(name), "", 1, "gemini-3.8-flash-low")
    assert info.value.code == code


def test_non_json_lines_and_init_are_ignored():
    stream = 'Fetching...\n{"event":"init","init":{"tools":["view_file"]}}\n' + fixture("success.jsonl")
    assert parse_stream(stream, "", 0, "gemini-3.8-flash-low").text.strip() == "OK"


def test_output_without_a_result_is_an_api_error():
    with pytest.raises(ConnectorError) as info:
        parse_stream('{"event":"step_update","step_update":{}}\n', "panic: crashed", 2, "gemini-3.8-flash-low")
    assert info.value.code == "API_ERROR" and "crashed" in info.value.message


def test_a_rate_limit_word_on_stderr_without_a_result_is_not_a_quota_cool_down():
    with pytest.raises(ConnectorError) as info:
        parse_stream("", "warning: rate limit config ignored; crashed", 1, "gemini-3.8-flash-low")
    assert info.value.code == "API_ERROR"


def test_a_missing_login_without_a_result_is_unavailable():
    with pytest.raises(ConnectorError) as info:
        parse_stream("", "Error: authentication required", 1, "gemini-3.8-flash-low")
    assert info.value.code == "UNAVAILABLE"


def test_login_words_inside_other_words_are_not_a_login_error():
    line = '{"event":"result","result":{"status":"ERROR","error":"catalogin service failed"}}'
    with pytest.raises(ConnectorError) as info:
        parse_stream(line, "", 1, "gemini-3.8-flash-low")
    assert info.value.code == "API_ERROR"


def test_thinking_tokens_count_as_output():
    line = ('{"event":"result","result":{"status":"SUCCESS","response":"Hi","usage":{"input_tokens":100,'
            '"output_tokens":5,"thinking_tokens":40,"cache_read_tokens":30,"total_tokens":145}}}')
    response = parse_stream(line, "", 0, "gemini-3.8-flash-high")
    assert response.tokens_out == 45 and response.tokens_cached == 30
    assert response.tokens_in == (70 if adapter.INPUT_INCLUDES_CACHE else 100)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest adapters/antigravity-cli -q`
Expected: FAIL with `ImportError: cannot import name 'parse_stream'`

- [ ] **Step 4: Implement**

Add to `__init__.py`:

```python
INPUT_INCLUDES_CACHE = True  # measured in plan 03f Task 2 (description.md); input_tokens counts cache reads
_QUOTA = re.compile(r"rate limit|quota|limit reached|too many requests|resource.?exhausted|\b429\b", re.IGNORECASE)
_LOGIN = re.compile(r"\bauthentication required\b|\bsign ?in\b|\blog ?in\b|\blogged out\b|\bunauthori[sz]ed\b"
                    r"|\b401\b", re.IGNORECASE)


def _failure(message: str) -> ConnectorError:
    message = message[:500]
    if _QUOTA.search(message):
        return ConnectorError("QUOTA_EXHAUSTED", message)
    if _LOGIN.search(message):
        return ConnectorError("UNAVAILABLE", message)
    return ConnectorError("API_ERROR", message)


def parse_stream(stdout: str, stderr: str, returncode: int, model: str) -> ModelResponse:
    """The `result` event of an `agy --output-format stream-json` run; other lines and events are ignored.

    A run whose tools were all denied ends SUCCESS with an empty response: it is returned as an empty answer,
    not raised, so the task's output check uses up an attempt instead of pausing the task (design 03f §3).
    """
    result = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == "result" and isinstance(event.get("result"), dict):
            result = event["result"]
    if result is None:  # only a login problem is told apart; anything else is an API error, never a cool-down
        message = f"agy ended without a result (exit {returncode}): {stderr[-300:]}"
        raise ConnectorError("UNAVAILABLE" if _LOGIN.search(stderr) else "API_ERROR", message[:500])
    if result.get("status") != "SUCCESS":
        raise _failure(str(result.get("error") or f"agy status {result.get('status')}"))
    usage = result.get("usage") or {}
    cached = usage.get("cache_read_tokens", 0)
    tokens_in = usage.get("input_tokens", 0) - (cached if INPUT_INCLUDES_CACHE else 0)
    return ModelResponse(
        text=str(result.get("response") or ""),
        model=model,
        tokens_in=max(tokens_in, 0),
        tokens_cached=cached,
        tokens_out=usage.get("output_tokens", 0) + usage.get("thinking_tokens", 0),  # thinking is billed as output
        quota_units=None,
        metering="reported",
    )
```

If the measurement of Step 1.2 said `False`, set `INPUT_INCLUDES_CACHE = False` and record a ruling in the
execution ledger (`.superpowers/sdd/plan-03f/progress.md`, not the OOAT ledger).

- [ ] **Step 5: Run tests**

Run: `.venv\Scripts\python.exe -m pytest adapters/antigravity-cli -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add adapters/antigravity-cli/tests/fixtures adapters/antigravity-cli/tests/test_antigravity_connector.py adapters/antigravity-cli/src/ooat_adapter_antigravity_cli/__init__.py adapters/antigravity-cli/description.md
git commit -m "feat(adapters): Antigravity stream-json parser on recorded runs (03f)"
```

---

### Task 3: `complete()`, isolation checks and the executable

**Files:**
- Modify: `adapters/antigravity-cli/src/ooat_adapter_antigravity_cli/__init__.py`
- Test: `adapters/antigravity-cli/tests/test_antigravity_connector.py`

**Interfaces:**
- Consumes: `parse_stream` (Task 2); `run_cli(args, stdin, timeout_s, files=None) -> CliResult` from
  `ooat_core.connectors.cli`.
- Produces: `exposed_tools(executable: str, settings_path: Path) -> str | None` (the reason the agent could get a
  tool, or None); `ISOLATION: list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
CLEAN = {("mcp", "list"): "No MCP servers configured.\n", ("plugin", "list"): "No imported plugins.\n"}


def fake_cli(monkeypatch, listings=None, stream=None):
    calls = []
    listings = dict(CLEAN, **(listings or {}))

    def run(args, stdin, timeout_s, files=None):
        calls.append({"args": args, "stdin": stdin})
        key = tuple(args[1:3])
        if key in listings:
            return CliResult(0, listings[key], "")
        return CliResult(0, stream or fixture("success.jsonl"), "")
    monkeypatch.setattr(adapter, "run_cli", run)
    monkeypatch.setattr(adapter, "find_executable", lambda name: "C:/agy/agy.exe")
    return calls


def connector(tmp_path, settings=None):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings or {"model": "x"}), encoding="utf-8")
    return AntigravityConnector(executable="agy", settings_path=path)


def request(**extra):
    return ModelRequest(tier="workhorse", prompt='Shrň "smlouvu"\na odpověz česky.', data_class="internal",
                        system="Be brief.", model="gemini-3.8-flash-high", **extra)


def test_prompt_and_system_go_to_stdin_as_one_stream_json_message(tmp_path, monkeypatch):
    calls = fake_cli(monkeypatch)
    connector(tmp_path).complete(request(), None)
    call = calls[-1]
    message = json.loads(call["stdin"].splitlines()[0])
    assert message == {"event": "user", "message": {"content": 'Be brief.\n\nShrň "smlouvu"\na odpověz česky.'}}
    assert "Shrň" not in " ".join(call["args"])  # never in argv


def test_the_call_runs_without_tools_and_with_the_routed_model(tmp_path, monkeypatch):
    calls = fake_cli(monkeypatch)
    connector(tmp_path).complete(request(), None)
    args = calls[-1]["args"]
    for flag in ("--sandbox", "--disable-slash-commands", "-p="):
        assert flag in args
    assert "--model=gemini-3.8-flash-high" in args
    assert args[args.index("--input-format") + 1] == args[args.index("--output-format") + 1] == "stream-json"
    for forbidden in ("--dangerously-skip-permissions", "--add-dir", "--continue", "-c", "--conversation"):
        assert forbidden not in args


@pytest.mark.parametrize("settings, listings, cause", [
    ({"permissions": {"allow": ["command(git)"]}}, None, "permissions.allow"),
    (None, {("mcp", "list"): "github  enabled  npx @mcp/github\n"}, "MCP server"),
    (None, {("plugin", "list"): "acme-tools  enabled\n"}, "plugin"),
    ({"model": "x", "hooks": {"preToolUse": "run.cmd"}}, None, "settings OOAT has not checked (hooks)"),
])
def test_extra_tools_in_the_agy_setup_refuse_the_call(tmp_path, monkeypatch, settings, listings, cause):
    calls = fake_cli(monkeypatch, listings)
    with pytest.raises(ConnectorError) as info:
        connector(tmp_path, settings).complete(request(), None)
    assert info.value.code == "UNAVAILABLE" and cause in info.value.message
    assert not any(a.startswith("--model") for c in calls for a in c["args"])  # the model was never called


def test_an_mcp_server_added_later_stops_the_next_call(tmp_path, monkeypatch):
    agy = connector(tmp_path)
    fake_cli(monkeypatch)
    agy.complete(request(), None)
    fake_cli(monkeypatch, {("mcp", "list"): "notes  enabled  node notes.js\n"})
    with pytest.raises(ConnectorError, match="MCP server"):
        agy.complete(request(), None)


def test_detect_reports_extra_tools(tmp_path, monkeypatch):
    fake_cli(monkeypatch, {("plugin", "list"): "acme-tools  enabled\n"})
    detection = connector(tmp_path).detect()
    assert not detection.available and "plugin" in detection.detail


def test_agy_is_found_in_its_install_folder(tmp_path, monkeypatch):
    installed = tmp_path / "agy" / "bin" / "agy.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(adapter, "find_executable", lambda name: name if name == str(installed) else None)
    assert AntigravityConnector()._find() == str(installed)


def test_model_id_with_shell_characters_is_refused(tmp_path, monkeypatch):
    fake_cli(monkeypatch)
    with pytest.raises(ConnectorError) as info:
        connector(tmp_path).complete(ModelRequest(tier="workhorse", prompt="x", data_class="internal",
                                                  model="gemini & calc"), None)
    assert info.value.code == "UNAVAILABLE"
    with pytest.raises(ConnectorError):
        connector(tmp_path).complete(ModelRequest(tier="workhorse", prompt="x", data_class="internal",
                                                  model="--dangerously-skip-permissions"), None)


@pytest.mark.skipif(os.environ.get("OOAT_LIVE_AGY") != "1", reason="spends Google quota; set OOAT_LIVE_AGY=1")
def test_live_minimal_call():
    response = AntigravityConnector().complete(
        ModelRequest(tier="economy", prompt="Reply with the single word OK.", data_class="public",
                     model="gemini-3.8-flash-low", timeout_s=180), None)
    assert "OK" in response.text and response.tokens_out
```

(Add `import json` to the test file's imports.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest adapters/antigravity-cli -q`
Expected: FAIL — `complete()` raises "not implemented yet"; `detect()` reports available.

- [ ] **Step 3: Implement**

Replace `detect()` and `complete()` and add:

```python
# Read-only by design: no tool runs without a permission headless mode cannot grant (design 03f §2); the empty
# temporary working directory leaves nothing for the one tool that needs none (reading inside the workspace).
ISOLATION = ["--input-format", "stream-json", "--output-format", "stream-json", "--sandbox",
             "--disable-slash-commands", "-p="]
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")  # no leading "-": it could read as a flag
_NO_MCP, _NO_PLUGINS = "No MCP servers configured.", "No imported plugins."
# Settings keys measured as harmless (plan 03f Task 2); "permissions" is checked separately.
SAFE_SETTINGS = frozenset({"model", "trustedWorkspaces", "permissions"})


def exposed_tools(executable: str, settings_path: Path) -> str | None:
    """Why the operator's agy setup could give the agent a tool beyond the soft-denied built-ins, or None."""
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
    except (OSError, ValueError):
        return f"cannot read {settings_path}; refusing to run without knowing its permissions"
    if (settings.get("permissions") or {}).get("allow"):
        return f"{settings_path} has permissions.allow rules; remove them so the agent stays without tools"
    unknown = sorted(set(settings) - SAFE_SETTINGS)
    if unknown:  # fail closed: a key OOAT does not know could approve tools or run hooks
        return f"{settings_path} has settings OOAT has not checked ({', '.join(unknown)}); see description.md"
    if run_cli([executable, "mcp", "list"], "", 30).stdout.strip() != _NO_MCP:
        return "agy has an MCP server configured (agy mcp list); remove it so the agent stays without tools"
    if run_cli([executable, "plugin", "list"], "", 30).stdout.strip() != _NO_PLUGINS:
        return "agy has a plugin imported (agy plugin list); remove it so the agent stays without tools"
    return None
```

```python
    def detect(self) -> Detection:
        path = self._find()
        if path is None:
            return Detection(False, "agy is not installed; install Antigravity CLI and log in once with agy")
        reason = exposed_tools(path, self._settings)
        if reason is not None:
            return Detection(False, reason)
        return Detection(True, f"agy found at {path}; uses its existing Google login")

    def complete(self, request: ModelRequest, secrets) -> ModelResponse:
        model = request.model or self.manifest["tiers"].get(request.tier)
        if model is None:
            raise ConnectorError("UNAVAILABLE", f"no model configured for tier {request.tier}")
        if not _MODEL_ID.match(model):
            raise ConnectorError("UNAVAILABLE", "model id contains characters that are not allowed")
        path = self._find()
        if path is None:
            raise ConnectorError("UNAVAILABLE", "agy is not installed")
        reason = exposed_tools(path, self._settings)  # checked on every call: the setup can change at any time
        if reason is not None:
            raise ConnectorError("UNAVAILABLE", reason)
        content = f"{request.system}\n\n{request.prompt}" if request.system else request.prompt
        message = json.dumps({"event": "user", "message": {"content": content}}, ensure_ascii=False)
        result = run_cli([path, *ISOLATION, f"--model={model}"], message + "\n", request.timeout_s)
        return parse_stream(result.stdout, result.stderr, result.returncode, model)
```

`test_conformance` keeps passing because `executable="agy-not-installed"` is not found, so `detect()` returns
fast without running agy.

- [ ] **Step 4: Run tests**

Run: `.venv\Scripts\python.exe -m pytest adapters/antigravity-cli -q`
Expected: all pass, live test skipped. Then once by hand: `set OOAT_LIVE_AGY=1` and run the live test; expected
pass.

- [ ] **Step 5: Commit**

```bash
git add adapters/antigravity-cli/src/ooat_adapter_antigravity_cli/__init__.py adapters/antigravity-cli/tests/test_antigravity_connector.py
git commit -m "feat(adapters): Antigravity call on stdin without tools; refuse an agy setup with extra tools (03f)"
```

---

### Task 4: Prices, routing test, install lines and docs

**Files:**
- Modify: `catalog/routing.json`, `adapters/integration_tests/test_gateway_with_connectors.py`,
  `.github/workflows/tests.yml`, `README.md`, `docs/description.md`, `tasks/f1-skeleton/README.md`

**Interfaces:**
- Consumes: `AntigravityConnector` (Tasks 1–3); `RoutingPolicy.price(connector_id, model, on)`.

- [ ] **Step 1: Write the failing test** (append to the integration test file; add
  `from ooat_adapter_antigravity_cli import AntigravityConnector` to its imports)

```python
def test_antigravity_tiers_are_priced_and_the_2027_flash_price_applies_from_january(setup):
    routing = setup._routing
    for model in ("gemini-3.8-flash-low", "gemini-3.8-flash-high", "gemini-3.1-pro-high"):
        assert routing.price("prv.google.subscription_cli", model, NOW.date(), fallback=False) is not None
    flash = routing.price("prv.google.subscription_cli", "gemini-3.8-flash-low", NOW.date(), fallback=False)
    later = routing.price("prv.google.subscription_cli", "gemini-3.8-flash-low",
                          datetime(2027, 1, 1).date(), fallback=False)
    assert (flash.usd_per_mtok_in, later.usd_per_mtok_in) == (0.75, 1.5)


def test_antigravity_never_receives_client_or_personal_data(setup):
    agy = AntigravityConnector(executable="agy-not-installed")
    setup._ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor={"kind": "hil", "id": "operator"}, body={
        "adapter": "prv.google.subscription_cli", "manifest_version": agy.manifest["version"],
        "allowed_data_classes": ["public", "internal"], "operator": "Operator", "automation_confirmed": True,
        "jurisdiction_sha256": jurisdiction_fingerprint(agy.manifest)}))
    only_agy = Gateway(setup._ledger, Registry([agy]), setup._routing, setup._config, clock=lambda: NOW)
    assert only_agy.estimate(request("internal")).connector == "prv.google.subscription_cli"
    for data_class in ("client_confidential", "personal"):
        with pytest.raises(GatewayError) as info:
            only_agy.estimate(request(data_class))
        assert info.value.code == "NOT_PERMITTED"


def test_the_operators_responsibility_cannot_extend_antigravity_because_it_trains():
    from ooat_core.connector_admin import checked_classes
    agy = AntigravityConnector(executable="agy-not-installed")
    for classes in (["internal", "personal"], ["client_confidential"]):
        with pytest.raises(ValueError, match="trains on inputs"):
            checked_classes(agy.manifest, classes, {"no_training": True})
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest adapters/integration_tests -q`
Expected: FAIL — `price(...)` is None for the Gemini ids.

- [ ] **Step 3: Add the prices** to `catalog/routing.json` `prices` (same shape as the OpenAI rows; source
  `https://ai.google.dev/gemini-api/docs/pricing`, checked 2026-10-06; Pro at the ≤200k-token prompt price, which
  covers every OOAT prompt today):

| adapter | model | in | cached | out | valid_from | valid_until |
|---|---|---|---|---|---|---|
| prv.google.subscription_cli | gemini-3.8-flash-low | 0.75 | 0.075 | 3.75 | 2026-10-06 | 2026-12-31 |
| prv.google.subscription_cli | gemini-3.8-flash-low | 1.5 | 0.15 | 7.5 | 2027-01-01 | — |
| prv.google.subscription_cli | gemini-3.8-flash-high | 0.75 | 0.075 | 3.75 | 2026-10-06 | 2026-12-31 |
| prv.google.subscription_cli | gemini-3.8-flash-high | 1.5 | 0.15 | 7.5 | 2027-01-01 | — |
| prv.google.subscription_cli | gemini-3.1-pro-high | 2 | 0.2 | 12 | 2026-10-06 | — |

Keys: `usd_per_mtok_in`, `usd_per_mtok_cached`, `usd_per_mtok_out`, `valid_from`, `valid_until` (only where
given), `source`. The `-low`/`-high` suffixes are agy's reasoning-effort variants of the API models
`gemini-3.8-flash` and `gemini-3.1-pro-preview`; say so in `adapters/antigravity-cli/description.md`.

- [ ] **Step 4: Install lines and docs**
  - `.github/workflows/tests.yml`: add `-e adapters/antigravity-cli` to the adapters install line.
  - `README.md` and `docs/description.md`: add `adapters/antigravity-cli` to the install command and the package
    list; `docs/description.md` routing line: "Anthropic, OpenAI (Codex models), Google (Antigravity models) and
    TypeSafe (Jev) list prices".
  - `tasks/f1-skeleton/README.md`: 03f row → plan `task-03f-antigravity-cli/plan-03f.md`, status done.

- [ ] **Step 5: Run the whole suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass (live tests skipped).

- [ ] **Step 6: Commit**

```bash
git add catalog/routing.json adapters/integration_tests/test_gateway_with_connectors.py .github/workflows/tests.yml README.md docs/description.md tasks/f1-skeleton/README.md adapters/antigravity-cli/description.md
git commit -m "feat(catalog): Gemini prices for the Antigravity tiers; install and docs (03f)"
```

---

## After execution (operator, not code)

- Enable for `public` only (owner decision C): `ooat connectors enable prv.google.subscription_cli --operator
  "<name>"` in the working folder, allowing only `public`; the card quotes the terms and the forum reply.

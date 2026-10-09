"""OOAT model connector for Google Antigravity CLI (`agy -p`, stream-json) on a Google login
(prv.google.subscription_cli)."""

import hashlib
import json
import os
import re
import shlex
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
            "cached login supported; the terms forbid third-party software accessing the service. agy keeps every "
            "call on this machine under ~/.gemini/antigravity-cli (conversations, brain, implicit, "
            "conversation_summaries.db), with no setting to turn it off. Gemini is priced below Claude "
            "Code in every tier: allowing internal data here moves internal work to this connector."),
        "source_urls": [TERMS, "https://policies.google.com/privacy", FORUM],
        "verified_on": None,
    },
}


# Not measurable on 2026-10-06 (no call read from the cache). False counts cached tokens twice if input_tokens
# already holds them, which overstates the shadow cost; True would understate it if they are separate.
INPUT_INCLUDES_CACHE = False
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


# Read-only by design: no tool runs without a permission headless mode cannot grant (design 03f §2); the empty
# temporary working directory leaves nothing for the one tool that needs none (reading inside the workspace).
ISOLATION = ["--input-format", "stream-json", "--output-format", "stream-json", "--sandbox",
             "--disable-slash-commands", "-p="]
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")  # no leading "-": it could read as a flag
_NO_MCP, _NO_PLUGINS = "No MCP servers configured.", "No imported plugins."
# Settings keys measured or documented as harmless (description.md); "permissions" is checked separately.
SAFE_SETTINGS = frozenset({"model", "trustedWorkspaces", "permissions", "enableTelemetry", "altScreenMode",
                           "colorScheme", "runningLightSpeed", "verbosity", "showTips", "showFeedbackSurvey",
                           "notifications", "editorMode", "statusLine", "allowNonWorkspaceAccess"})


def settings_risk(settings_path: Path) -> str | None:
    """Why the operator's agy settings could approve a tool, or None. Fast and offline (used by detect())."""
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
    except (OSError, ValueError):
        return f"cannot read {settings_path}; refusing to run without knowing its permissions"
    if not isinstance(settings, dict):
        return f"{settings_path} is not a JSON object; refusing to run without knowing its permissions"
    if settings.get("allowNonWorkspaceAccess", False) is not False:  # the empty workspace would no longer isolate
        return (f"{settings_path}: allowNonWorkspaceAccess is true, so the agent could read files outside its empty "
                "workspace; set it to false (or remove it) to use this connector")
    unknown = sorted(set(settings) - SAFE_SETTINGS)
    if unknown:  # fail closed: a key OOAT does not know could approve tools or run hooks
        return f"{settings_path} has settings OOAT has not checked ({', '.join(unknown)}); see description.md"
    permissions = settings.get("permissions", {})
    if not isinstance(permissions, dict) or set(permissions) - {"allow", "deny"} or permissions.get("allow"):
        return (f"{settings_path} has permissions OOAT does not accept (only an empty allow list and deny rules); "
                "remove them so the agent stays without tools")
    return None


def _commands(data) -> list[str]:
    """Every "command" string anywhere in a hooks.json document."""
    if isinstance(data, dict):
        return [c for key, value in data.items()
                for c in ([value] if key == "command" and isinstance(value, str) else _commands(value))]
    if isinstance(data, list):
        return [c for item in data for c in _commands(item)]
    return []


SCRIPT_SUFFIXES = frozenset({".cmd", ".bat", ".ps1", ".py", ".js", ".mjs", ".cjs", ".sh", ".vbs"})
MAX_FOLDER_FILES = 200


def _files(command: str) -> list[Path] | None:
    """Every existing file a command names: the program and, for an interpreter (`node x.js`, `powershell -File
    x.ps1`), its script. None when it names none, so nothing could be fingerprinted (fail closed)."""
    try:
        tokens = [t.strip('"') for t in shlex.split(command, posix=False)]
    except ValueError:
        return None
    found = [Path(t) for t in tokens if t and Path(t).is_file()]
    return found or None


def _fingerprint(path: Path) -> tuple[str, str, str]:
    try:
        data = path.read_bytes()
    except OSError:
        return str(path), "", ""  # unreadable: an empty fingerprint is never approved, so the call refuses
    return str(path), hashlib.sha256(data).hexdigest(), data.decode("utf-8", errors="replace")


def hook_files(gemini_home: Path) -> list[tuple[str, str, str]]:
    """(path, sha256 of the bytes, text) of config/hooks.json and of every file in the folder of each program its
    commands start: a script may call its neighbours (Orca's per-event scripts call antigravity-hook.cmd), so a
    change to any of them needs a new approval (ADR 0015). Gemini CLI's hooks in ~/.gemini/settings.json are not
    run by agy (measured 2026-10-06: no process started during a call)."""
    path = gemini_home / "config" / "hooks.json"
    try:
        data = path.read_bytes() if path.is_file() else b""
    except OSError:
        return [(str(path), "", "")]
    try:
        parsed = json.loads(data) if data.strip() else None
    except ValueError:
        return [_fingerprint(path)]  # not JSON: agy may still read it, so it needs approval as it is
    if not parsed:  # {}, [] and null define no hooks
        return []
    entries, folders, files = [_fingerprint(path)], set(), set()
    for command in _commands(parsed):
        named = _files(command)
        if named is None:  # nothing to fingerprint: never approvable
            entries.append((f"{path}: command {command[:80]!r} names no file OOAT can check", "", ""))
            continue
        for file in named:  # a script may call its neighbours; a program in a system folder does not
            (folders if file.suffix.lower() in SCRIPT_SUFFIXES else files).add(file.parent if
                                                                            file.suffix.lower() in SCRIPT_SUFFIXES
                                                                            else file)
    for folder in sorted(folders):
        try:
            listed = sorted(f for f in folder.iterdir() if f.is_file())
        except OSError:
            entries.append((str(folder), "", ""))
            continue
        if len(listed) > MAX_FOLDER_FILES:
            entries.append((f"{folder}: more than {MAX_FOLDER_FILES} files", "", ""))
            continue
        files.update(listed)
    return entries + [_fingerprint(file) for file in sorted(files)]


def hooks_risk(gemini_home: Path, approved: tuple[str, ...] = ()) -> str | None:
    """Why hooks would run commands around agy's steps without the operator's approval, or None (ADR 0015)."""
    for path, sha, _ in hook_files(gemini_home):
        if sha not in approved or not sha:
            return (f"{path} defines hooks the operator has not approved, or they changed since; review them with "
                    "`ooat connectors approve-hooks prv.google.subscription_cli`")
    return None


def exposed_tools(executable: str, settings_path: Path) -> str | None:
    """Why the operator's agy setup could give the agent a tool beyond the soft-denied built-ins, or None.
    Runs `agy mcp list` and `agy plugin list`, so it is used before each call, not by detect()."""
    reason = settings_risk(settings_path)
    if reason is not None:
        return reason
    for command, empty, what in (("mcp", _NO_MCP, "an MCP server configured"), ("plugin", _NO_PLUGINS,
                                                                                "a plugin imported")):
        listing = run_cli([executable, command, "list"], "", 30)
        if listing.returncode != 0:
            return f"could not verify agy {command} list (exit {listing.returncode}); refusing to run"
        if listing.stdout.strip() != empty:
            return f"agy has {what} (agy {command} list); remove it so the agent stays without tools"
    return None


class AntigravityConnector:
    kind = "model"

    def __init__(self, executable: str | None = None, settings_path: Path | None = None,
                 gemini_home: Path | None = None):
        self.manifest = MANIFEST
        self._executable = executable
        self._gemini = gemini_home or Path.home() / ".gemini"
        self._settings = settings_path or self._gemini / "antigravity-cli" / "settings.json"

    def detect(self) -> Detection:
        path = self._find()
        if path is None:
            return Detection(False, "agy is not installed; install Antigravity CLI and log in once with agy")
        reason = settings_risk(self._settings)  # offline; listings and hook approvals are checked per call
        if reason is not None:
            return Detection(False, reason)
        hooks = "; hooks run only once approved (ooat connectors approve-hooks)" if self.hooks() else ""
        return Detection(True, f"agy found at {path}; uses its existing Google login{hooks}")

    def hooks(self) -> list[tuple[str, str, str]]:
        """Hook files the operator must approve before calls run (path, sha256, text)."""
        return hook_files(self._gemini)

    def _find(self) -> str | None:
        if self._executable is not None:
            return find_executable(self._executable)
        installed = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
        return find_executable("agy") or (str(installed) if os.environ.get("LOCALAPPDATA") and installed.is_file()
                                          else None)

    def complete(self, request: ModelRequest, secrets) -> ModelResponse:
        model = request.model or self.manifest["tiers"].get(request.tier)
        if model is None:
            raise ConnectorError("UNAVAILABLE", f"no model configured for tier {request.tier}")
        if not _MODEL_ID.match(model):
            raise ConnectorError("UNAVAILABLE", "model id contains characters that are not allowed")
        path = self._find()
        if path is None:
            raise ConnectorError("UNAVAILABLE", "agy is not installed")
        # checked on every call: the setup can change at any time
        reason = hooks_risk(self._gemini, request.approved_hooks) or exposed_tools(path, self._settings)
        if reason is not None:
            raise ConnectorError("UNAVAILABLE", reason)
        content = f"{request.system}\n\n{request.prompt}" if request.system else request.prompt
        message = json.dumps({"event": "user", "message": {"content": content}}, ensure_ascii=False)
        result = run_cli([path, *ISOLATION, f"--model={model}"], message + "\n", request.timeout_s)
        return parse_stream(result.stdout, result.stderr, result.returncode, model)

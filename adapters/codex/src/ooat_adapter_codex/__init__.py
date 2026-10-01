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
    "features": {"tool_use": None, "vision": None, "context_tokens": None},  # unsourced facts stay null
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
# No shell tool (the agent cannot run commands or read local files), read-only sandbox as a second line, no session
# files, no repository rules, no plugins or apps; the prompt comes from stdin ("-").
ISOLATION = ["--json", "--ephemeral", "--skip-git-repo-check", "--disable", "shell_tool", "--sandbox", "read-only",
             "--ignore-rules", "--disable", "plugins", "--disable", "apps"]
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

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
    "features": {"tool_use": None, "vision": None, "context_tokens": None},  # unsourced facts stay null
    "jurisdiction": {
        "vendor_entity": None,
        "vendor_country": None,
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
_MODEL_ID = re.compile(r"^[A-Za-z0-9._:/\[\]-]+$")


def _checked_model(model: str) -> str:
    if not _MODEL_ID.match(model):
        raise ConnectorError("UNAVAILABLE", "model id contains characters that are not allowed")
    return model


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
        model = _checked_model(request.model or self.manifest["tiers"][request.tier])
        # System text goes in a file and the prompt through stdin: no caller text in argv (see connectors/cli.py).
        args = [self._executable, "-p", "--output-format", "json", "--model", model,
                "--system-prompt-file", "system.txt", *ISOLATION]
        result = run_cli(args, request.prompt, request.timeout_s,
                         files={"system.txt": request.system or DEFAULT_SYSTEM})
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
    model_usage = data.get("modelUsage") or {}
    if model_usage:
        name, details = next(iter(model_usage.items()))
        model = (details or {}).get("canonicalModel") or name.split("[")[0]  # "claude-opus-5-5[1m]"
    else:
        model = requested_model
    # Usage is reported as one aggregate; with several models it cannot be priced exactly.
    metering = "reported" if len(model_usage) <= 1 else "estimated"
    return ModelResponse(
        text=str(data.get("result", "")),
        model=model,
        tokens_in=usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0),
        tokens_cached=usage.get("cache_read_input_tokens", 0),
        tokens_out=usage.get("output_tokens"),
        quota_units=None,
        metering=metering,
    )

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
            "conversations locally under ~/.gemini/antigravity-cli/conversations. Gemini is priced below Claude "
            "Code in every tier: allowing internal data here moves internal work to this connector."),
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

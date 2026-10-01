"""Connector contract (gateway design §4).

Connectors are installed packages registered under the entry-point group "ooat.connectors"; ooat-core knows no
vendor names. Model connectors are served now; tool connectors (MCP, REST, CLI tools) follow with their own contract.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Protocol

ENTRY_POINT_GROUP = "ooat.connectors"
# The RESULT.error.code values a connector may raise (event schema, ADR 0010).
ERROR_CODES = frozenset({"QUOTA_EXHAUSTED", "UNAVAILABLE", "API_ERROR", "TIMEOUT"})


@dataclass(frozen=True)
class Detection:
    available: bool
    detail: str


@dataclass(frozen=True)
class ModelRequest:
    tier: str
    prompt: str
    data_class: str  # required: the gateway never guesses a class (spec §9)
    system: str = ""
    max_output_tokens: int = 4000
    expected_output_tokens: int | None = None
    task: str | None = None
    contract: str | None = None
    timeout_s: float = 600
    model: str | None = None  # set by the gateway to the routed model; connectors must use it


@dataclass(frozen=True)
class ModelResponse:
    text: str
    model: str
    tokens_in: int | None
    tokens_cached: int | None
    tokens_out: int | None
    quota_units: float | None
    metering: Literal["exact", "reported", "estimated"]


class ConnectorError(Exception):
    def __init__(self, code: str, message: str, resets_at: str | None = None):
        if code not in ERROR_CODES:
            raise ValueError(f"unknown connector error code: {code}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.resets_at = resets_at  # ISO 8601 UTC, for QUOTA_EXHAUSTED when the provider says


class SecretSource(Protocol):
    def get(self, connector_id: str) -> str: ...


class ModelConnector(Protocol):
    kind: Literal["model"]
    manifest: dict  # valid against spec/schemas/provider.schema.json

    def detect(self) -> Detection: ...

    def complete(self, request: ModelRequest, secrets: SecretSource) -> ModelResponse: ...


def jurisdiction_fingerprint(manifest: dict) -> str:
    """SHA-256 of the canonical JSON of the manifest's jurisdiction block (ADR 0010)."""
    canonical = json.dumps(manifest["jurisdiction"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

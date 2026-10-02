"""Connector contract (gateway design §4).

Connectors are installed packages registered under the entry-point group "ooat.connectors"; ooat-core knows no
vendor names. Model connectors (kind "model") write text; decision connectors (kind "decision", ADR 0011) answer
typed questions about a state. Tool connectors (MCP, REST, CLI tools) follow with their own contract.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import ClassVar, Literal, Protocol

ENTRY_POINT_GROUP = "ooat.connectors"
# The RESULT.error.code values a connector may raise (event schema, ADR 0010).
ERROR_CODES = frozenset({"QUOTA_EXHAUSTED", "UNAVAILABLE", "API_ERROR", "TIMEOUT"})
CONNECTOR_KINDS = frozenset({"model", "decision"})


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


@dataclass(frozen=True)
class DecisionQuestion:
    """One typed question (spec §5): noul (0..1), choice (one declared option), score (position on 2-10 levels).

    criteria: noul - None or {"true": ..., "false": ...}; choice - {option: description}; score - [level, ...].
    """
    type: Literal["noul", "choice", "score"]
    instructions: str
    criteria: dict | list | None = None


@dataclass(frozen=True)
class DecisionRequest:
    state: str  # the text the questions are about; untrusted data, never instructions
    questions: dict[str, DecisionQuestion]
    data_class: str  # required, as for model requests
    task: str | None = None
    contract: str | None = None
    timeout_s: float = 30
    model: str | None = None  # set by the gateway to the routed model; connectors must use it
    tier: ClassVar[str] = "decision"


@dataclass(frozen=True)
class DecisionAnswer:
    type: str
    value: float | str  # noul: probability of true; choice: the option; score: position 0..levels-1
    confidence: float  # noul: max(p, 1 - p)
    probabilities: dict[str, float] | None = None


@dataclass(frozen=True)
class DecisionResponse:
    answers: dict[str, DecisionAnswer]
    model: str  # the version that answered (e.g. "jev-1.13.0"), not an alias
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


class DecisionConnector(Protocol):
    kind: Literal["decision"]
    manifest: dict  # tiers {"decision": "<model>"}

    def detect(self) -> Detection: ...

    def decide(self, request: DecisionRequest, secrets: SecretSource) -> DecisionResponse: ...


def jurisdiction_fingerprint(manifest: dict) -> str:
    """SHA-256 of the canonical JSON of the manifest's jurisdiction block (ADR 0010)."""
    canonical = json.dumps(manifest["jurisdiction"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def jurisdiction_stale(manifest: dict, acknowledgement: dict, today: date, responsible: bool = True) -> bool:
    """Spec §9 rule 2: the jurisdiction changed since acknowledgement, or was not verified within 12 months.

    A stale connector stays enabled but refuses personal and special-category data until acknowledged again.
    An operator who takes responsibility (ADR 0012) checks the facts on the card that day, so the later of the
    manifest's verified_on and the responsibility's confirmed_on counts - only for the classes the responsibility
    covers (`responsible`); special-category data keeps the manifest's date alone.
    """
    confirmed_on = (acknowledgement.get("responsibility") or {}).get("confirmed_on") if responsible else None
    dates = [d for d in (manifest["jurisdiction"]["verified_on"], confirmed_on) if d]
    if not dates or (today - max(date.fromisoformat(d) for d in dates)).days > 365:
        return True
    return jurisdiction_fingerprint(manifest) != acknowledgement.get("jurisdiction_sha256")

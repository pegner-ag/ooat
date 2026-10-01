"""Append-only ledger of events and artifact records (spec §7).

This is the single write path of OOAT: agents and the orchestrator only propose events; ooat-core appends them.
Ledger owns the spec rules (validation, provenance, atomicity); the backend owns the database dialect.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from .backends import LedgerBackend, open_backend
from .ids import is_artifact_ref, new_id, parse_artifact_ref
from .validation import SpecValidationError, validate

_SQL_INT_MAX = 2**63 - 1
_COST_INTEGERS = ("tokens_in", "tokens_cached", "tokens_out")
_HEX = frozenset("0123456789abcdef")
DATA_CLASSES = frozenset({"public", "internal", "client_confidential", "personal", "special_category"})

# The envelope's cost keys differ from the spec's column names for usd and basis.
_COST_COLUMNS = {
    "adapter": "adapter", "tier": "tier", "tokens_in": "tokens_in", "tokens_cached": "tokens_cached",
    "tokens_out": "tokens_out", "quota_units": "quota_units", "usd": "cost_usd", "basis": "cost_basis",
    "price_ver": "price_ver", "estimated_usd": "estimated_usd",
}


@dataclass(frozen=True)
class StagedArtifact:
    """An artifact body already in blob storage, waiting for the event that produces it."""

    ref: str
    type: str
    data_class: str
    untrusted: bool
    sha256: str
    uri: str


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_event(
    event_type: str,
    *,
    task: str | None,
    actor: dict,
    body: dict,
    refs: Iterable[str] = (),
    contract: str | None = None,
    lang: str | None = None,
    cost: dict | None = None,
) -> dict:
    """Build an event envelope with a fresh id and timestamp. Optional keys that are None are omitted."""
    event = {"id": new_id("evt"), "ts": utc_now(), "task": task, "actor": actor, "type": event_type,
             "refs": list(refs), "body": body}
    for key, value in (("contract", contract), ("lang", lang), ("cost", cost)):
        if value is not None:
            event[key] = value
    return event


def _artifact_refs(value) -> set[str]:
    """Every artifact reference in a JSON value; free text that merely mentions one is not a reference."""
    if isinstance(value, str):
        return {value} if is_artifact_ref(value) else set()
    items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    return set().union(*(_artifact_refs(item) for item in items))


def _event_row(event: dict) -> dict:
    actor, cost = event["actor"], event.get("cost", {})
    return {
        "id": event["id"], "ts": event["ts"], "task_id": event["task"], "contract_id": event.get("contract"),
        "actor_kind": actor["kind"], "actor_id": actor["id"], "role_ver": actor.get("role"),
        "type": event["type"], "refs": json.dumps(event["refs"]), "lang": event.get("lang"),
        "body": json.dumps(event["body"], ensure_ascii=False),
        **{column: cost.get(key) for key, column in _COST_COLUMNS.items()},
    }


def _row_event(row: dict) -> dict:
    event = {
        "id": row["id"], "ts": row["ts"], "task": row["task_id"],
        "actor": {"kind": row["actor_kind"], "id": row["actor_id"]},
        "type": row["type"], "refs": json.loads(row["refs"]), "body": json.loads(row["body"]),
    }
    if row["role_ver"] is not None:
        event["actor"]["role"] = row["role_ver"]
    if row["contract_id"] is not None:
        event["contract"] = row["contract_id"]
    if row["lang"] is not None:
        event["lang"] = row["lang"]
    cost = {key: row[column] for key, column in _COST_COLUMNS.items() if row[column] is not None}
    if cost:
        event["cost"] = cost
    return event


class Ledger:
    def __init__(self, backend: LedgerBackend):
        self.backend = backend

    @classmethod
    def open(cls, url: str) -> "Ledger":
        """Open a ledger by URL, e.g. sqlite:///ledger.sqlite or sqlite:///:memory:."""
        return cls(open_backend(url))

    def close(self) -> None:
        self.backend.close()

    def append(self, event: dict, artifacts: Iterable[StagedArtifact] = ()) -> dict:
        """Validate and append one event together with the artifacts it produces, atomically.

        Raises SpecValidationError without writing anything if the event does not match the spec.
        """
        validate("event", event)
        try:
            # JSON Schema accepts NaN and Infinity; SQL stores them as NULL or invalid JSON, losing data.
            json.dumps(event, allow_nan=False)
        except ValueError:
            raise SpecValidationError("event", ["numbers must be finite (no NaN or Infinity)"]) from None
        too_large = [key for key in _COST_INTEGERS if event.get("cost", {}).get(key, 0) > _SQL_INT_MAX]
        if too_large:
            raise SpecValidationError("event", [f"$.cost.{key}: exceeds a 64-bit integer" for key in too_large])
        self._check_hil(event)
        artifacts = list(artifacts)
        self._check_staged(artifacts)
        staged_refs = {a.ref for a in artifacts}
        unreferenced = sorted(staged_refs - set(event["refs"]))
        if unreferenced:
            raise ValueError(f"staged artifacts must be referenced by their event: {unreferenced}")
        unknown = sorted(ref for ref in _artifact_refs([event["refs"], event["body"]])
                         if ref not in staged_refs and self.artifact(ref) is None)
        if unknown:
            raise ValueError(f"event references unknown artifacts: {unknown}")
        artifact_rows = []
        for artifact in artifacts:
            artifact_id, version = parse_artifact_ref(artifact.ref)
            artifact_rows.append({
                "id": artifact_id, "version": version, "type": artifact.type, "data_class": artifact.data_class,
                "untrusted": int(artifact.untrusted), "sha256": artifact.sha256, "uri": artifact.uri,
                "produced_by_event": event["id"],
            })
        self.backend.insert(_event_row(event), artifact_rows)
        return event

    def _check_hil(self, event: dict) -> None:
        """Cross-field HIL rules JSON Schema cannot express (spec §9, ADR 0003 #4)."""
        body, errors = event["body"], []
        if event["type"] == "HIL_REQUEST":
            options = {option["id"]: option for option in body["options"]}
            for key in ("recommended", "default_on_silence"):
                if body[key] not in options:
                    errors.append(f"$.body.{key}: {body[key]!r} is not one of the options")
            default = options.get(body["default_on_silence"])
            # An R3 action is irreversible: when nobody answers, nothing may happen.
            if body.get("risk_class") == "R3" and default is not None and default.get("acts") is not False:
                errors.append("$.body.default_on_silence: an R3 request must default to the option with acts: false")
        elif event["type"] == "HIL_RESPONSE":
            hil = self.events(task=event["task"], types=["HIL_REQUEST", "HIL_RESPONSE"])
            request = next((e for e in hil if e["type"] == "HIL_REQUEST" and e["id"] == body["request"]), None)
            if request is None:
                errors.append(f"$.body.request: no HIL_REQUEST {body['request']} in this task")
            elif any(e["type"] == "HIL_RESPONSE" and e["body"]["request"] == body["request"] for e in hil):
                errors.append(f"$.body.request: {body['request']} is already answered")
            else:
                if request["body"].get("risk_class") == "R3" and "choice" not in body:
                    errors.append("$.body.choice: an R3 request needs an explicit choice, not only text")
                if "choice" in body and body["choice"] not in {o["id"] for o in request["body"]["options"]}:
                    errors.append(f"$.body.choice: {body['choice']!r} is not an option of {body['request']}")
                # Silence may only ever apply the declared default; for R3 that is the do-not-act option.
                if body.get("default_applied") and body.get("choice") != request["body"]["default_on_silence"]:
                    errors.append("$.body.choice: a default_applied response must choose the request's default")
        if errors:
            raise SpecValidationError("event", errors)

    def _check_staged(self, artifacts: list[StagedArtifact]) -> None:
        """Staged records must look like ArtifactStore output: digest format, blob URI, next version without gaps.

        Whether the blob itself exists is checked by BlobStore on read, not here.
        """
        expected: dict[str, int] = {}
        for artifact in artifacts:
            if not artifact.type:
                raise ValueError(f"{artifact.ref}: artifact type is empty")
            if artifact.data_class not in DATA_CLASSES:
                raise ValueError(f"{artifact.ref}: unknown data class {artifact.data_class!r}")
            if len(artifact.sha256) != 64 or not set(artifact.sha256) <= _HEX:
                raise ValueError(f"{artifact.ref}: not a SHA-256 hex digest")
            if artifact.uri != f"blob:{artifact.sha256}":
                raise ValueError(f"{artifact.ref}: uri must be blob:<sha256>")
            artifact_id, version = parse_artifact_ref(artifact.ref)
            next_version = expected.get(artifact_id) or self.next_artifact_version(artifact_id)
            if version != next_version:
                raise ValueError(f"{artifact.ref}: expected version {next_version}")
            expected[artifact_id] = version + 1

    def events(self, task: str | None = None, types: Iterable[str] = ()) -> list[dict]:
        """Events in append order, optionally filtered by task and event types.

        Optional envelope keys stored as null (e.g. "contract": null) are omitted, and quota_units come back
        as float; read events compare equal to what was appended but are not byte-identical JSON.
        """
        if isinstance(types, str):
            raise TypeError("types must be a list of event types, not a string")
        return [_row_event(row) for row in self.backend.select_events(task, list(types))]

    def artifact(self, ref: str) -> dict | None:
        """The artifact record for art_<ulid>@v<n>, or None if no appended event produced it."""
        record = self.backend.select_artifact(*parse_artifact_ref(ref))
        if record is not None:
            record["untrusted"] = bool(record["untrusted"])
        return record

    def next_artifact_version(self, artifact_id: str) -> int:
        return self.backend.max_artifact_version(artifact_id) + 1

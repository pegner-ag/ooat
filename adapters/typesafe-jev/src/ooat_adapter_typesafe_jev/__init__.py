"""OOAT decision connector for TypeSafe's System One API (prv.typesafe.api, model Jev), metered per token.

API facts from https://docs.typesafe.ai/api.md and https://docs.typesafe.ai/models.md (accessed 2026-10-01).
"""

import json
import math
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from ooat_core.connectors import ConnectorError, DecisionAnswer, DecisionRequest, DecisionResponse, Detection

MANIFEST = {
    "id": "prv.typesafe.api",
    "version": "0.1.0",
    "status": "preview",  # early access since 2026-09-15; the economy text tier is the fallback (spec §6)
    "vendor": "typesafe",
    "access": "api",
    "tiers": {"decision": "jev-latest"},
    "metering": "exact",
    "automation_permitted": "unknown",
    "concurrency": 4,
    # US processing: the reference policy keeps it to public and internal data (spec §9, ADR 0011).
    "data_policy": {"training_on_inputs": False, "retention_days": None, "allowed_data_classes": ["public", "internal"]},
    "jurisdiction": {
        "vendor_entity": "TypeSafe AI, Inc.",
        "vendor_country": "US",
        "host_entity": "TypeSafe AI, Inc.",
        "processing_regions": ["us"],
        "eu_region_available": False,
        "model_origin_country": "US",
        "training_on_inputs": False,
        "retention": None,
        "zero_retention_available": None,  # "enterprise customers can request" it; not a plan fact for operators
        "transfer_notes": "EEA personal data leaves the EEA; operator needs a transfer mechanism.",
        "source_urls": ["https://typesafe.ai/legal/privacy-policy", "https://docs.typesafe.ai/models.md"],
        "verified_on": None,
    },
}
URL = "https://api.typesafe.ai/v1/systemone"
# 32k tokens for the state plus the longest question (models page). Characters / 3 overestimates tokens for
# Czech and English text, so a request refused here would almost surely have been refused by the API.
MAX_INPUT_TOKENS = 32_000
RATE_LIMIT_COOL_DOWN_S = 60  # 429 is a per-second rate limit (40 requests/s), not a quota window


def _default_open(req: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout)


def _approx_tokens(text: str) -> int:
    return math.ceil(len(text) / 3)


class JevConnector:
    kind = "decision"

    def __init__(self, opener=_default_open, clock=lambda: datetime.now(timezone.utc)):
        self.manifest = MANIFEST
        self._open = opener  # injectable transport for tests; production uses urllib
        self._clock = clock

    def detect(self) -> Detection:
        return Detection(True, "HTTPS client ready; the API key comes from the secret_env set for prv.typesafe.api")

    def decide(self, request: DecisionRequest, secrets) -> DecisionResponse:
        # Question ids go out as q0, q1, ...: the API's id rules are not documented, OOAT's are stricter anyway.
        wire = {f"q{index}": question_id for index, question_id in enumerate(request.questions)}
        questions = {}
        for wire_id, question_id in wire.items():
            question = request.questions[question_id]
            questions[wire_id] = {"type": question.type, "instructions": question.instructions}
            if question.criteria is not None:
                questions[wire_id]["criteria"] = question.criteria
        longest = max(len(json.dumps(q, ensure_ascii=False)) for q in questions.values())
        approx = _approx_tokens(request.state) + math.ceil(longest / 3)
        if approx > MAX_INPUT_TOKENS:
            raise ConnectorError("UNAVAILABLE", f"state too large for Jev (about {approx} tokens, limit "
                                                f"{MAX_INPUT_TOKENS}); nothing was sent")
        key = secrets.get(self.manifest["id"])
        body = {"state": request.state, "model": request.model or self.manifest["tiers"]["decision"],
                "questions": questions}
        req = urllib.request.Request(URL, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                                     headers={"Authorization": f"Bearer {key}", "content-type": "application/json"})
        try:
            with self._open(req, request.timeout_s) as reply:
                raw = reply.read()
        except urllib.error.HTTPError as error:
            raise self._http_error(error) from None
        except (socket.timeout, TimeoutError):
            raise ConnectorError("TIMEOUT", f"no answer within {request.timeout_s:g} s") from None
        except urllib.error.URLError as error:
            raise ConnectorError("UNAVAILABLE", f"cannot reach the API: {error.reason}") from None
        except ValueError:  # e.g. an invalid header value; its message would quote the key, so it is dropped
            raise ConnectorError("UNAVAILABLE", "the request could not be built (check the API key value)") from None
        try:  # the provider answered, so the call was billed: an unreadable reply is an API error, not "did not run"
            data = json.loads(raw.decode("utf-8"))
            return parse_reply(data, wire)
        except (UnicodeDecodeError, ValueError, TypeError, AttributeError, KeyError):
            raise ConnectorError("API_ERROR", "the API returned an unreadable reply") from None

    def _http_error(self, error: urllib.error.HTTPError) -> ConnectorError:
        try:
            detail = json.loads(error.read().decode("utf-8"))
            detail = detail.get("error", detail) if isinstance(detail, dict) else detail
            detail = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        except (ValueError, AttributeError, OSError):
            detail = ""
        message = f"HTTP {error.code}: {detail}"[:500]
        if error.code in (401, 529):  # invalid key; overloaded - nothing ran
            return ConnectorError("UNAVAILABLE", message)
        if error.code == 429:
            resets_at = (self._clock() + timedelta(seconds=RATE_LIMIT_COOL_DOWN_S)).strftime("%Y-%m-%dT%H:%M:%SZ")
            return ConnectorError("QUOTA_EXHAUSTED", message, resets_at=resets_at)
        return ConnectorError("API_ERROR", message)  # 422 validation failure and anything undocumented


def parse_reply(data: dict, wire: dict[str, str]) -> DecisionResponse:
    """Map a System One reply back to OOAT question ids. Shape errors raise; the gateway checks the values."""
    answers = {}
    for wire_id, answer in data["answers"].items():
        if wire_id not in wire:
            continue
        kind = answer["type"]
        if kind == "noul":
            p = answer["noul"]
            decided = DecisionAnswer("noul", p, max(p, 1 - p), {"true": p, "false": 1 - p})
        elif kind == "choice":
            decided = DecisionAnswer("choice", answer["choice"], answer["confidence"], answer.get("probabilities"))
        else:
            decided = DecisionAnswer(kind, answer["score"], answer["confidence"], answer.get("probabilities"))
        answers[wire[wire_id]] = decided
    usage = data.get("usage") or {}
    return DecisionResponse(answers, str(data.get("model", "")), usage.get("input_tokens"), None,
                            usage.get("output_tokens"), None, "exact")

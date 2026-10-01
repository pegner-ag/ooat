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
    "features": {"tool_use": None, "vision": None, "context_tokens": None},  # differs per model; unsourced stays null
    "jurisdiction": {
        "vendor_entity": None,
        "vendor_country": None,
        "host_entity": None,
        "processing_regions": None,
        "eu_region_available": None,
        "model_origin_country": "US",
        "training_on_inputs": False,
        "retention": None,
        "zero_retention_available": None,
        "transfer_notes": None,
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
        except ValueError:  # e.g. an invalid header value; its message would quote the key, so it is dropped
            raise ConnectorError("UNAVAILABLE", "the request could not be built (check the API key value)") from None
        return parse_message(data)

    def _http_error(self, error: urllib.error.HTTPError) -> ConnectorError:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("error", {}).get("message", "")
        except (ValueError, AttributeError, OSError):
            detail = ""
        message = f"HTTP {error.code}: {detail}"[:500]
        if error.code in (401, 403, 529):  # 529: overloaded, nothing ran
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
        tokens_in=(usage.get("input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0),
        tokens_cached=usage.get("cache_read_input_tokens") or 0,
        tokens_out=usage.get("output_tokens"),
        quota_units=None,
        metering="exact",
    )

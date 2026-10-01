import io
import json
import os
import socket
import urllib.error
from datetime import datetime, timezone
from email.message import Message

import pytest

from ooat_adapter_anthropic_api import AnthropicApiConnector, parse_message
from ooat_core.config import parse_config
from ooat_core.connectors import ConnectorError, ModelRequest
from ooat_core.connectors.conformance import check_connector
from ooat_core.connectors.registry import Registry
from ooat_core.secrets import SecretResolver

KEY = "sk-ant-test-0123456789"
MESSAGE = {
    "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-haiku-4-5-20251001",
    "content": [{"type": "text", "text": "Dobrý den"}], "stop_reason": "end_turn",
    "usage": {"input_tokens": 12, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100,
              "output_tokens": 5},
}


class Secrets:
    def get(self, connector_id):
        assert connector_id == "prv.anthropic.api"
        return KEY


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def request(**extra):
    return ModelRequest(tier="economy", prompt="Pozdrav.", data_class="internal", **extra)


def http_error(code, message, headers=None):
    header_map = Message()
    for name, value in (headers or {}).items():
        header_map[name] = value
    body = io.BytesIO(json.dumps({"type": "error", "error": {"type": "x", "message": message}}).encode())
    return urllib.error.HTTPError("https://api.anthropic.com/v1/messages", code, message, header_map, body)


def test_conformance():
    check_connector(AnthropicApiConnector())


def test_entry_point_is_registered():
    assert isinstance(Registry.discover().get("prv.anthropic.api"), AnthropicApiConnector)


def test_request_shape_and_parsed_response():
    sent = {}

    def opener(req, timeout):
        sent.update(url=req.full_url, headers=dict(req.header_items()), body=json.loads(req.data), timeout=timeout)
        return Reply(json.dumps(MESSAGE).encode())

    response = AnthropicApiConnector(opener).complete(request(system="Stručně.", max_output_tokens=50,
                                                              model="claude-haiku-4-5-20251001"), Secrets())
    assert sent["url"] == "https://api.anthropic.com/v1/messages"
    assert sent["headers"]["X-api-key"] == KEY and sent["headers"]["Anthropic-version"] == "2023-06-01"
    assert sent["body"] == {"model": "claude-haiku-4-5-20251001", "max_tokens": 50, "system": "Stručně.",
                            "messages": [{"role": "user", "content": "Pozdrav."}]}
    assert response.text == "Dobrý den" and response.metering == "exact"
    assert (response.tokens_in, response.tokens_cached, response.tokens_out) == (12, 100, 5)


@pytest.mark.parametrize("error, code", [
    (http_error(401, "invalid x-api-key"), "UNAVAILABLE"),
    (http_error(529, "overloaded"), "UNAVAILABLE"),
    (http_error(500, "internal error"), "API_ERROR"),
    (ValueError("Invalid header value b'sk-ant-test-0123456789\\n'"), "UNAVAILABLE"),
    (urllib.error.URLError("name resolution failed"), "UNAVAILABLE"),
    (socket.timeout("timed out"), "TIMEOUT"),
])
def test_transport_errors_are_typed_and_carry_no_key(error, code):
    def opener(req, timeout):
        raise error

    with pytest.raises(ConnectorError) as info:
        AnthropicApiConnector(opener).complete(request(), Secrets())
    assert info.value.code == code and KEY not in str(info.value)


def test_rate_limit_reports_the_reset_time():
    def opener(req, timeout):
        raise http_error(429, "rate limited", {"retry-after": "30"})

    clock = lambda: datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)  # noqa: E731
    with pytest.raises(ConnectorError) as info:
        AnthropicApiConnector(opener, clock).complete(request(), Secrets())
    assert info.value.code == "QUOTA_EXHAUSTED" and info.value.resets_at == "2026-10-01T12:00:30Z"


def test_parse_message_joins_text_blocks():
    data = dict(MESSAGE, content=[{"type": "text", "text": "a"}, {"type": "tool_use"}, {"type": "text", "text": "b"}])
    assert parse_message(data).text == "ab"


@pytest.mark.skipif(os.environ.get("OOAT_LIVE") != "1" or not os.environ.get("ANTHROPIC_API_KEY"),
                    reason="spends API credit; set OOAT_LIVE=1 and ANTHROPIC_API_KEY")
def test_live_minimal_call():
    secrets = SecretResolver(parse_config({"connectors": {"prv.anthropic.api": {"secret_env": "ANTHROPIC_API_KEY"}}}))
    response = AnthropicApiConnector().complete(
        ModelRequest(tier="economy", prompt="Reply with the single word OK.", data_class="public",
                     max_output_tokens=10, timeout_s=60), secrets)
    assert "OK" in response.text and response.tokens_out


def test_null_usage_counts_are_read_as_zero():
    data = dict(MESSAGE, usage={"input_tokens": None, "output_tokens": 3})
    assert parse_message(data).tokens_in == 0

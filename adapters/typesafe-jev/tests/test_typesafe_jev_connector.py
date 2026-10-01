import io
import json
import os
import socket
import urllib.error
from datetime import datetime, timezone
from email.message import Message

import pytest

from ooat_adapter_typesafe_jev import JevConnector, parse_reply
from ooat_core.config import parse_config
from ooat_core.connectors import ConnectorError, DecisionQuestion, DecisionRequest
from ooat_core.connectors.conformance import check_connector
from ooat_core.connectors.registry import Registry
from ooat_core.credentials_env import SecretResolver

KEY = "ts-test-0123456789"
CHECKABLE = DecisionQuestion("noul", "Is the criterion checkable from the output alone?")
BRANCHES = DecisionQuestion("choice", "How many independent branches?", {"one": "1", "two": "2", "many": "3+"})
DEPTH = DecisionQuestion("score", "How decomposable?", ["not", "partly", "fully"])
# Shapes from https://docs.typesafe.ai/primitives/{noul,choice,score}.md
REPLY = {
    "model": "jev-1.13.0",
    "answers": {
        "q0": {"type": "noul", "noul": 0.93},
        "q1": {"type": "choice", "choice": "two", "confidence": 0.8,
               "probabilities": {"one": 0.1, "two": 0.85, "many": 0.05}},
        "q2": {"type": "score", "score": 1.43, "confidence": 0.35,
               "legend": {"0": "not", "1": "partly", "2": "fully"}, "probabilities": {"0": 0.0, "1": 0.57, "2": 0.43}},
    },
    "usage": {"input_tokens": 332, "output_tokens": 18},
}


class Secrets:
    def get(self, connector_id):
        assert connector_id == "prv.typesafe.api"
        return KEY


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def request(state="Napiš shrnutí smlouvy pro jednatele.", **extra):
    return DecisionRequest(state, {"a1.1": CHECKABLE, "a5": BRANCHES, "a7": DEPTH}, "internal", **extra)


def http_error(code, message):
    body = io.BytesIO(json.dumps({"error": {"message": message}}).encode())
    return urllib.error.HTTPError("https://api.typesafe.ai/v1/systemone", code, message, Message(), body)


def test_conformance():
    check_connector(JevConnector())


def test_entry_point_is_registered_as_a_decision_connector():
    registry = Registry.discover()
    assert isinstance(registry.get("prv.typesafe.api"), JevConnector)
    assert "prv.typesafe.api" in registry.ids("decision")


def test_request_shape_and_parsed_reply():
    sent = {}

    def opener(req, timeout):
        sent.update(url=req.full_url, headers=dict(req.header_items()), body=json.loads(req.data), timeout=timeout)
        return Reply(json.dumps(REPLY).encode())

    response = JevConnector(opener).decide(request(model="jev-latest", timeout_s=20), Secrets())
    assert sent["url"] == "https://api.typesafe.ai/v1/systemone" and sent["timeout"] == 20
    assert sent["headers"]["Authorization"] == f"Bearer {KEY}"
    assert sent["body"]["model"] == "jev-latest" and sent["body"]["state"] == "Napiš shrnutí smlouvy pro jednatele."
    assert sent["body"]["questions"] == {
        "q0": {"type": "noul", "instructions": CHECKABLE.instructions},
        "q1": {"type": "choice", "instructions": BRANCHES.instructions, "criteria": BRANCHES.criteria},
        "q2": {"type": "score", "instructions": DEPTH.instructions, "criteria": DEPTH.criteria}}
    assert response.model == "jev-1.13.0" and (response.tokens_in, response.tokens_out) == (332, 18)
    assert response.answers["a1.1"].value == 0.93 and response.answers["a1.1"].confidence == 0.93
    assert response.answers["a5"].value == "two" and response.answers["a5"].confidence == 0.8
    assert response.answers["a7"].value == 1.43 and response.answers["a7"].probabilities["1"] == 0.57


def test_a_noul_below_one_half_is_confident_in_no():
    answer = parse_reply({"answers": {"q0": {"type": "noul", "noul": 0.1}}}, {"q0": "a1"}).answers["a1"]
    assert answer.value == 0.1 and answer.confidence == 0.9


def test_answers_to_unknown_ids_are_ignored():
    assert parse_reply({"answers": {"q9": {"type": "noul", "noul": 1}}}, {"q0": "a1"}).answers == {}


@pytest.mark.parametrize("error, code", [
    (http_error(401, "invalid api key"), "UNAVAILABLE"),
    (http_error(529, "overloaded"), "UNAVAILABLE"),
    (http_error(422, "criteria must have at least two levels"), "API_ERROR"),
    (http_error(500, "internal error"), "API_ERROR"),
    (ValueError("Invalid header value b'Bearer ts-test-0123456789\\n'"), "UNAVAILABLE"),
    (urllib.error.URLError("name resolution failed"), "UNAVAILABLE"),
    (socket.timeout("timed out"), "TIMEOUT"),
])
def test_transport_errors_are_typed_and_carry_no_key(error, code):
    def opener(req, timeout):
        raise error

    with pytest.raises(ConnectorError) as info:
        JevConnector(opener).decide(request(), Secrets())
    assert info.value.code == code and KEY not in str(info.value)


def test_rate_limit_cools_down_for_a_minute():
    def opener(req, timeout):
        raise http_error(429, "too many requests")

    clock = lambda: datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)  # noqa: E731
    with pytest.raises(ConnectorError) as info:
        JevConnector(opener, clock).decide(request(), Secrets())
    assert info.value.code == "QUOTA_EXHAUSTED" and info.value.resets_at == "2026-10-01T12:01:00Z"


@pytest.mark.parametrize("raw", [
    b"<html>not json</html>", b'{"answers": []}', b'{"model": "jev-1.13.0"}', b'{"answers": {"q0": {"type": "noul"}}}',
    b'{"answers": {"q0": {"type": "noul", "noul": "yes"}}}'])
def test_unreadable_200_reply_is_an_api_error_because_the_call_was_billed(raw):
    def opener(req, timeout):
        return Reply(raw)

    with pytest.raises(ConnectorError) as info:
        JevConnector(opener).decide(request(), Secrets())
    assert info.value.code == "API_ERROR"


def test_a_state_too_large_for_jev_is_refused_before_sending():
    def opener(req, timeout):
        raise AssertionError("nothing may be sent")

    with pytest.raises(ConnectorError) as info:
        JevConnector(opener).decide(request(state="x" * 100_000), Secrets())
    assert info.value.code == "UNAVAILABLE" and "too large" in info.value.message


@pytest.mark.skipif(os.environ.get("OOAT_LIVE") != "1" or not os.environ.get("TYPESAFE_API_KEY"),
                    reason="spends API credit; set OOAT_LIVE=1 and TYPESAFE_API_KEY")
def test_live_minimal_call():
    secrets = SecretResolver(parse_config({"connectors": {"prv.typesafe.api": {"secret_env": "TYPESAFE_API_KEY"}}}))
    response = JevConnector().decide(DecisionRequest(
        "The invoice total is 1,200 EUR and is due on 15 October.", {
            "has_amount": DecisionQuestion("noul", "Does the text state an amount of money?"),
            "topic": DecisionQuestion("choice", "What is the text about?", {"billing": "Invoices and payments",
                                                                          "shipping": "Deliveries"})},
        "public", timeout_s=30), secrets)
    assert response.answers["has_amount"].value > 0.5 and response.answers["topic"].value == "billing"
    assert response.model.startswith("jev-") and response.tokens_in

"""The gateway with the real connector packages and catalog/routing.json; no network, no CLI runs."""

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import ooat_adapter_claude_code as claude_code
from ooat_adapter_anthropic_api import AnthropicApiConnector
from ooat_adapter_claude_code import ClaudeCodeConnector
from ooat_adapter_codex import CodexConnector
from ooat_adapter_typesafe_jev import JevConnector
from ooat_core.config import parse_config
from ooat_core.connectors import DecisionQuestion, DecisionRequest, ModelRequest, jurisdiction_fingerprint
from ooat_core.connectors.cli import CliResult
from ooat_core.connectors.registry import Registry
from ooat_core.credentials_env import SecretResolver
from ooat_core.gateway import Gateway, GatewayError
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger, new_event
from ooat_core.routing import load_routing

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
RECORDED = (ROOT / "adapters" / "claude-code" / "tests" / "fixtures" / "success.json").read_text(encoding="utf-8")


def unused_opener(req, timeout):
    raise AssertionError("the API must not be called when the subscription wins")


@pytest.fixture
def setup():
    ledger = Ledger.open("sqlite:///:memory:")
    connectors = [ClaudeCodeConnector(), CodexConnector(), AnthropicApiConnector(unused_opener)]
    for connector in connectors:
        ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor={"kind": "hil", "id": "operator"}, body={
            "adapter": connector.manifest["id"], "manifest_version": connector.manifest["version"],
            "allowed_data_classes": ["public", "internal", "client_confidential", "personal"], "operator": "Operator",
            "automation_confirmed": True,
            "jurisdiction_sha256": jurisdiction_fingerprint(connector.manifest)}))
    config = parse_config({"connectors": {"prv.anthropic.api": {"secret_env": "ANTHROPIC_API_KEY"}}})
    gateway = Gateway(ledger, Registry(connectors), load_routing(ROOT / "catalog" / "routing.json"), config,
                      clock=lambda: NOW)
    yield gateway
    ledger.close()


def request(data_class="internal"):
    return ModelRequest(tier="economy", prompt="Reply with OK.", data_class=data_class, task=new_id("tsk"))


def test_subscription_wins_over_the_api_at_the_same_list_price(setup):
    estimate = setup.estimate(request())
    assert estimate.connector == "prv.anthropic.subscription_cli"
    assert estimate.model == "claude-haiku-4-5-20251001"


def test_codex_waits_for_a_configured_model_and_price(setup):
    only_codex = Gateway(setup._ledger, Registry([CodexConnector()]), setup._routing, setup._config,
                         clock=lambda: NOW)
    with pytest.raises(GatewayError) as info:
        only_codex.estimate(ModelRequest(tier="workhorse", prompt="x", data_class="internal"))
    assert "no model configured" in info.value.trace[0]


def test_call_runs_the_cli_once_and_meters_a_shadow_price(setup, monkeypatch):
    calls = []
    monkeypatch.setattr(claude_code, "run_cli",
                        lambda args, stdin, timeout, files=None: calls.append(args) or CliResult(0, RECORDED, ""))
    result = setup.call(request())
    assert len(calls) == 1 and calls[0][calls[0].index("--model") + 1] == "claude-haiku-4-5-20251001"
    assert result.cost["adapter"] == "prv.anthropic.subscription_cli" and result.cost["basis"] == "shadow"
    assert result.cost["usd"] > 0 and result.cost["estimated_usd"] > 0


def test_reference_policy_refuses_client_data_until_contracts_can_be_verified(setup):
    with pytest.raises(GatewayError) as info:
        setup.estimate(request("client_confidential"))
    assert info.value.code == "NOT_PERMITTED"
    # The API connector is acknowledged for the class and does not train on inputs: the policy itself refuses it.
    assert "prv.anthropic.api: client_confidential requires a known processing region" in info.value.trace


# Decisions on Jev with the reference routing -------------------------------------------------------------------

class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def jev_gateway(setup, opener):
    jev = JevConnector(opener)
    setup._ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor={"kind": "hil", "id": "operator"}, body={
        "adapter": "prv.typesafe.api", "manifest_version": jev.manifest["version"],
        "allowed_data_classes": ["public", "internal"], "operator": "Operator", "automation_confirmed": True,
        "jurisdiction_sha256": jurisdiction_fingerprint(jev.manifest)}))
    config = parse_config({"connectors": {"prv.typesafe.api": {"secret_env": "TYPESAFE_API_KEY"}}})
    return Gateway(setup._ledger, Registry([ClaudeCodeConnector(), jev]), setup._routing, config,
                   SecretResolver(config, {"TYPESAFE_API_KEY": "ts-test-key"}), clock=lambda: NOW)


def decision(data_class="internal"):
    return DecisionRequest("Shrň smlouvu.", {"a1.1": DecisionQuestion("noul", "Is the criterion checkable?")},
                           data_class, task=new_id("tsk"))


def test_internal_decisions_go_to_jev_at_its_list_price(setup):
    reply = {"model": "jev-1.13.0", "answers": {"q0": {"type": "noul", "noul": 0.9}},
             "usage": {"input_tokens": 332, "output_tokens": 18}}
    result = jev_gateway(setup, lambda req, timeout: Reply(json.dumps(reply).encode())).decide(decision())
    assert result.engine == "prv.typesafe.api" and result.model == "jev-1.13.0" and result.fallback_from is None
    assert result.cost["basis"] == "exact" and result.cost["usd"] == pytest.approx(332 * 0.042 / 1e6)


def test_personal_data_reaches_neither_jev_nor_an_unverified_subscription(setup):
    def opener(req, timeout):
        raise AssertionError("personal data must not be sent to Jev")

    with pytest.raises(GatewayError) as info:
        jev_gateway(setup, opener).decide(decision("personal"))
    assert info.value.code == "NOT_PERMITTED"
    assert "prv.typesafe.api: personal is not allowed by the manifest" in info.value.trace

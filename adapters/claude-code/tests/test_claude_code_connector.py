import os
from pathlib import Path

import pytest

import ooat_adapter_claude_code as adapter
from ooat_adapter_claude_code import ClaudeCodeConnector, parse_result
from ooat_core.connectors import ConnectorError, ModelRequest
from ooat_core.connectors.cli import CliResult
from ooat_core.connectors.conformance import check_connector
from ooat_core.connectors.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def request(**extra):
    return ModelRequest(tier="workhorse", prompt="Reply with OK.", data_class="internal", **extra)


def test_conformance():
    check_connector(ClaudeCodeConnector())


def test_entry_point_is_registered():
    assert isinstance(Registry.discover().get("prv.anthropic.subscription_cli"), ClaudeCodeConnector)


def test_recorded_success_is_parsed():
    response = parse_result(fixture("success.json"), "", "claude-sonnet-5-5")
    assert response.text == "OK"
    assert response.model == "claude-opus-5-5"  # the recording ran on the CLI's default model
    assert (response.tokens_in, response.tokens_cached, response.tokens_out) == (2 + 519, 0, 4)
    assert response.metering == "reported"


@pytest.mark.parametrize("name, code", [("not_logged_in.json", "UNAVAILABLE"),
                                        ("usage_limit_synthetic.json", "QUOTA_EXHAUSTED")])
def test_recorded_errors_are_typed(name, code):
    with pytest.raises(ConnectorError) as info:
        parse_result(fixture(name), "", "claude-sonnet-5-5")
    assert info.value.code == code


def test_unreadable_output_is_an_api_error():
    with pytest.raises(ConnectorError) as info:
        parse_result("Error: something broke", "stack trace", "claude-sonnet-5-5")
    assert info.value.code == "API_ERROR"


def test_call_isolates_the_cli_and_uses_the_routed_model(monkeypatch):
    seen = {}

    def fake_run(args, stdin, timeout_s, files=None):
        seen.update(args=args, stdin=stdin, timeout=timeout_s, files=files)
        return CliResult(0, fixture("success.json"), "")

    monkeypatch.setattr(adapter, "run_cli", fake_run)
    ClaudeCodeConnector().complete(request(model="claude-haiku-4-5-20251001", system="Be brief.", timeout_s=60), None)
    args = seen["args"]
    assert args[:4] == ["claude", "-p", "--output-format", "json"]
    assert args[args.index("--model") + 1] == "claude-haiku-4-5-20251001"
    assert args[args.index("--system-prompt-file") + 1] == "system.txt"
    assert seen["files"] == {"system.txt": "Be brief."}
    assert "Be brief." not in args and "--system-prompt" not in args  # caller text never reaches argv
    for flag in ("--setting-sources", "--strict-mcp-config", "--disable-slash-commands", "--tools",
                 "--no-session-persistence"):
        assert flag in args
    assert args[args.index("--tools") + 1] == "" and args[args.index("--setting-sources") + 1] == ""
    assert seen["stdin"] == "Reply with OK." and seen["timeout"] == 60
    assert "Reply with OK." not in args  # the prompt never appears on the command line


@pytest.mark.skipif(os.environ.get("OOAT_LIVE") != "1", reason="spends subscription quota; set OOAT_LIVE=1")
def test_live_minimal_call():
    response = ClaudeCodeConnector().complete(
        ModelRequest(tier="economy", prompt="Reply with the single word OK.", data_class="public",
                     model="claude-haiku-4-5-20251001", timeout_s=120), None)
    assert "OK" in response.text and response.tokens_out and response.tokens_in < 5000


def test_model_id_with_shell_characters_is_refused(monkeypatch):
    monkeypatch.setattr(adapter, "run_cli", lambda *a, **k: pytest.fail("must not run"))
    with pytest.raises(ConnectorError) as info:
        ClaudeCodeConnector().complete(request(model='x" & calc & "'), None)
    assert info.value.code == "UNAVAILABLE"


def test_canonical_model_is_reported_and_mixed_models_are_estimated():
    import json

    data = json.loads(fixture("success.json"))
    assert parse_result(json.dumps(data), "", "x").model == "claude-opus-5-5"
    data["modelUsage"]["claude-haiku-4-5-20251001"] = {"canonicalModel": "claude-haiku-4-5-20251001"}
    assert parse_result(json.dumps(data), "", "x").metering == "estimated"

import os
from pathlib import Path

import pytest

import ooat_adapter_codex as adapter
from ooat_adapter_codex import CodexConnector, parse_events
from ooat_core.connectors import ConnectorError, ModelRequest
from ooat_core.connectors.cli import CliResult
from ooat_core.connectors.conformance import check_connector
from ooat_core.connectors.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_conformance():
    check_connector(CodexConnector())


def test_entry_point_is_registered():
    assert isinstance(Registry.discover().get("prv.openai.subscription_cli"), CodexConnector)


def test_recorded_success_is_parsed_and_warnings_ignored():
    response = parse_events(fixture("success.jsonl"), "", "gpt-test")
    assert response.text == "OK"
    assert (response.tokens_in, response.tokens_cached, response.tokens_out) == (16762 - 2432, 2432, 5)
    assert response.model == "gpt-test" and response.metering == "reported"


@pytest.mark.parametrize("name, code", [("usage_limit_synthetic.jsonl", "QUOTA_EXHAUSTED"),
                                        ("logged_out_synthetic.jsonl", "UNAVAILABLE")])
def test_error_events_are_typed(name, code):
    with pytest.raises(ConnectorError) as info:
        parse_events(fixture(name), "", "gpt-test")
    assert info.value.code == code


def test_output_without_a_completed_turn_is_an_api_error():
    with pytest.raises(ConnectorError) as info:
        parse_events('{"type":"turn.started"}\nnot json\n', "crashed", "gpt-test")
    assert info.value.code == "API_ERROR"


def test_call_needs_a_configured_model():
    with pytest.raises(ConnectorError) as info:
        CodexConnector().complete(ModelRequest(tier="workhorse", prompt="x", data_class="internal"), None)
    assert info.value.code == "UNAVAILABLE"


def test_call_isolates_the_cli_and_sends_system_and_prompt_on_stdin(monkeypatch):
    seen = {}

    def fake_run(args, stdin, timeout_s):
        seen.update(args=args, stdin=stdin)
        return CliResult(0, fixture("success.jsonl"), "")

    monkeypatch.setattr(adapter, "run_cli", fake_run)
    CodexConnector().complete(ModelRequest(tier="workhorse", prompt="Reply with OK.", data_class="internal",
                                           system="Be brief.", model="gpt-test"), None)
    args = seen["args"]
    assert args[:2] == ["codex", "exec"] and args[-1] == "-"
    assert args[args.index("-m") + 1] == "gpt-test"
    assert args[args.index("--sandbox") + 1] == "read-only"
    for flag in ("--json", "--ephemeral", "--ignore-rules", "--skip-git-repo-check"):
        assert flag in args
    disabled = {args[i + 1] for i, arg in enumerate(args) if arg == "--disable"}
    assert {"shell_tool", "plugins", "apps"} <= disabled
    assert seen["stdin"] == "Be brief.\n\nReply with OK."


@pytest.mark.skipif(os.environ.get("OOAT_LIVE") != "1" or not os.environ.get("OOAT_CODEX_MODEL"),
                    reason="spends subscription quota; set OOAT_LIVE=1 and OOAT_CODEX_MODEL")
def test_live_minimal_call():
    response = CodexConnector().complete(
        ModelRequest(tier="workhorse", prompt="Reply with the single word OK.", data_class="public",
                     model=os.environ["OOAT_CODEX_MODEL"], timeout_s=180), None)
    assert "OK" in response.text and response.tokens_out



def test_recorded_call_without_shell_tool_cannot_run_commands():
    response = parse_events(fixture("no_shell.jsonl"), "", "gpt-test")
    assert response.text == "NO-SHELL"
    assert response.tokens_out == 57  # reasoning_output_tokens (48) are part of output_tokens

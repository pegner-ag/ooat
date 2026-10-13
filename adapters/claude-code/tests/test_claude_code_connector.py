import json
import os
from pathlib import Path

import pytest

import ooat_adapter_claude_code as adapter
from ooat_adapter_claude_code import ClaudeCodeConnector, parse_result
from ooat_core.connectors import ConnectorError, ModelRequest
from ooat_core.connectors.cli import CliResult
from ooat_core.connectors.conformance import check_connector
from ooat_core.connectors.registry import Registry
from ooat_core.workspace import WorkspaceGrant

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


def test_the_manifest_says_it_can_work_with_project_folders():
    assert adapter.MANIFEST["features"]["workspace"] is True


def test_a_call_with_a_grant_gets_only_ooats_mcp_server(monkeypatch, tmp_path):
    seen = {}

    def fake_run(args, stdin, timeout_s, files=None):
        seen.update(args=args, files=files)
        return CliResult(0, fixture("success.json"), "")

    monkeypatch.setattr(adapter, "run_cli", fake_run)
    grant = WorkspaceGrant(project="bots", folders=(("Bots", str(tmp_path / "Bots")),), write=True, deny=(),
                           hidden=(), max_operations=300, max_write_bytes=5 * 1024 * 1024,
                           journal_dir=str(tmp_path / "journal"))
    ClaudeCodeConnector().complete(request(workspace=grant), None)
    args = seen["args"]
    assert args[args.index("--tools") + 1] == "" and "--strict-mcp-config" in args
    assert args[args.index("--mcp-config") + 1] == "mcp.json"
    assert args[args.index("--allowedTools") + 1] == "mcp__ooat_workspace"
    servers = json.loads(seen["files"]["mcp.json"])["mcpServers"]
    assert list(servers) == ["ooat_workspace"]
    assert (tmp_path / "journal" / "grant.json").exists()
    assert str(tmp_path / "Bots") not in " ".join(args)  # folders reach the server in a file, never in argv


def test_a_call_without_a_grant_has_no_mcp_server(monkeypatch):
    seen = {}
    monkeypatch.setattr(adapter, "run_cli", lambda args, stdin, timeout_s, files=None:
                        seen.update(args=args, files=files) or CliResult(0, fixture("success.json"), ""))
    ClaudeCodeConnector().complete(request(), None)
    assert "--mcp-config" not in seen["args"] and "--allowedTools" not in seen["args"]
    assert "mcp.json" not in seen["files"]


@pytest.mark.skipif(os.environ.get("OOAT_LIVE") != "1", reason="spends subscription quota; set OOAT_LIVE=1")
def test_live_the_agent_reads_and_edits_a_granted_file_and_nothing_else(tmp_path):
    root = tmp_path / "Bots"
    root.mkdir()
    (root / "hello.txt").write_text("Hello, world\n", encoding="utf-8")
    (root / ".env").write_text("TOKEN=ooat-canary-7f3a91\n", encoding="utf-8")
    grant = WorkspaceGrant(project="bots", folders=(("Bots", os.path.realpath(root)),), write=True, deny=(),
                           hidden=(), max_operations=30, max_write_bytes=100_000,
                           journal_dir=str(tmp_path / "journal"))
    response = ClaudeCodeConnector().complete(ModelRequest(
        tier="economy", data_class="internal", timeout_s=300, workspace=grant,
        prompt="In Bots/hello.txt replace 'world' with 'OOAT'. Then try to read Bots/.env and report what happens."),
        None)
    assert (root / "hello.txt").read_text(encoding="utf-8") == "Hello, OOAT\n"
    assert "7f3a91" not in response.text
    from ooat_core.workspace.tools import read_journal
    journal = read_journal(tmp_path / "journal")
    assert any(e.get("tool") == "edit_file" and not e.get("refused") for e in journal)
    assert all(e.get("refused") == "protected file" for e in journal if e.get("path") == "Bots/.env")

import json
import os
from pathlib import Path

import pytest

import ooat_adapter_antigravity_cli as adapter
from ooat_adapter_antigravity_cli import MANIFEST, AntigravityConnector, parse_stream
from ooat_core.connectors import ConnectorError, ModelRequest
from ooat_core.connectors.cli import CliResult
from ooat_core.connectors.conformance import check_connector
from ooat_core.connectors.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_conformance():
    check_connector(AntigravityConnector(executable="agy-not-installed"))


def test_entry_point_is_registered():
    assert isinstance(Registry.discover().get("prv.google.subscription_cli"), AntigravityConnector)


def test_manifest_states_training_and_leaves_unknowns_null():
    assert MANIFEST["data_policy"]["training_on_inputs"] is True
    assert MANIFEST["jurisdiction"]["training_on_inputs"] is True
    assert MANIFEST["data_policy"]["allowed_data_classes"] == ["public", "internal"]
    assert MANIFEST["automation_permitted"] == "unknown"
    assert MANIFEST["jurisdiction"]["verified_on"] is None and MANIFEST["jurisdiction"]["vendor_entity"] is None
    assert MANIFEST["tiers"] == {"economy": "gemini-3.8-flash-low", "workhorse": "gemini-3.8-flash-high",
                                 "frontier": "gemini-3.1-pro-high"}


def test_recorded_success_is_parsed():
    response = parse_stream(fixture("success.jsonl"), "", 0, "gemini-3.8-flash-low")
    assert response.text.strip() == "OK"
    assert response.model == "gemini-3.8-flash-low" and response.metering == "reported"
    assert response.tokens_in > 0 and response.tokens_out >= 1 and response.tokens_cached >= 0


def test_a_denied_tool_gives_an_empty_answer_not_an_error():
    response = parse_stream(fixture("denied_tool.jsonl"), "jetski: no output produced - a tool required the "
                            "\"command\" permission", 0, "gemini-3.8-flash-low")
    assert response.text == ""  # the output check counts it as an empty attempt; the task does not pause


@pytest.mark.parametrize("name, code", [("auth_error_synthetic.jsonl", "UNAVAILABLE"),
                                        ("quota_synthetic.jsonl", "QUOTA_EXHAUSTED")])
def test_error_results_are_typed(name, code):
    with pytest.raises(ConnectorError) as info:
        parse_stream(fixture(name), "", 1, "gemini-3.8-flash-low")
    assert info.value.code == code


def test_non_json_lines_and_init_are_ignored():
    stream = 'Fetching...\n{"event":"init","init":{"tools":["view_file"]}}\n' + fixture("success.jsonl")
    assert parse_stream(stream, "", 0, "gemini-3.8-flash-low").text.strip() == "OK"


def test_output_without_a_result_is_an_api_error():
    with pytest.raises(ConnectorError) as info:
        parse_stream('{"event":"step_update","step_update":{}}\n', "panic: crashed", 2, "gemini-3.8-flash-low")
    assert info.value.code == "API_ERROR" and "crashed" in info.value.message


def test_a_rate_limit_word_on_stderr_without_a_result_is_not_a_quota_cool_down():
    with pytest.raises(ConnectorError) as info:
        parse_stream("", "warning: rate limit config ignored; crashed", 1, "gemini-3.8-flash-low")
    assert info.value.code == "API_ERROR"


def test_a_missing_login_without_a_result_is_unavailable():
    with pytest.raises(ConnectorError) as info:
        parse_stream("", "Error: authentication required", 1, "gemini-3.8-flash-low")
    assert info.value.code == "UNAVAILABLE"


def test_login_words_inside_other_words_are_not_a_login_error():
    line = '{"event":"result","result":{"status":"ERROR","error":"catalogin service failed"}}'
    with pytest.raises(ConnectorError) as info:
        parse_stream(line, "", 1, "gemini-3.8-flash-low")
    assert info.value.code == "API_ERROR"


def test_thinking_tokens_count_as_output():
    line = ('{"event":"result","result":{"status":"SUCCESS","response":"Hi","usage":{"input_tokens":100,'
            '"output_tokens":5,"thinking_tokens":40,"cache_read_tokens":30,"total_tokens":145}}}')
    response = parse_stream(line, "", 0, "gemini-3.8-flash-high")
    assert response.tokens_out == 45 and response.tokens_cached == 30
    assert response.tokens_in == (70 if adapter.INPUT_INCLUDES_CACHE else 100)


CLEAN = {("mcp", "list"): fixture("mcp_list_empty.txt"), ("plugin", "list"): fixture("plugin_list_empty.txt")}


def fake_cli(monkeypatch, listings=None, stream=None):
    calls = []
    listings = {**CLEAN, **(listings or {})}

    def run(args, stdin, timeout_s, files=None):
        calls.append({"args": args, "stdin": stdin})
        key = tuple(args[1:3])
        if key in listings:
            return CliResult(0, listings[key], "")
        return CliResult(0, stream or fixture("success.jsonl"), "")
    monkeypatch.setattr(adapter, "run_cli", run)
    monkeypatch.setattr(adapter, "find_executable", lambda name: "C:/agy/agy.exe")
    return calls


def connector(tmp_path, settings=None):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model": "x"} if settings is None else settings), encoding="utf-8")
    return AntigravityConnector(executable="agy", settings_path=path, gemini_home=tmp_path / "no-gemini")


def request(**extra):
    return ModelRequest(tier="workhorse", prompt='Shrň "smlouvu"\na odpověz česky.', data_class="internal",
                        system="Be brief.", model="gemini-3.8-flash-high", **extra)


def test_prompt_and_system_go_to_stdin_as_one_stream_json_message(tmp_path, monkeypatch):
    calls = fake_cli(monkeypatch)
    connector(tmp_path).complete(request(), None)
    call = calls[-1]
    message = json.loads(call["stdin"].splitlines()[0])
    assert message == {"event": "user", "message": {"content": 'Be brief.\n\nShrň "smlouvu"\na odpověz česky.'}}
    assert "Shrň" not in " ".join(call["args"])  # never in argv


def test_the_call_runs_without_tools_and_with_the_routed_model(tmp_path, monkeypatch):
    calls = fake_cli(monkeypatch)
    connector(tmp_path).complete(request(), None)
    args = calls[-1]["args"]
    for flag in ("--sandbox", "--disable-slash-commands", "-p="):
        assert flag in args
    assert "--model=gemini-3.8-flash-high" in args
    assert args[args.index("--input-format") + 1] == args[args.index("--output-format") + 1] == "stream-json"
    for forbidden in ("--dangerously-skip-permissions", "--add-dir", "--continue", "-c", "--conversation"):
        assert forbidden not in args


@pytest.mark.parametrize("settings, listings, cause", [
    ({"permissions": {"allow": ["command(git)"]}}, None, "permissions OOAT does not accept"),
    (None, {("mcp", "list"): "github  enabled  npx @mcp/github\n"}, "MCP server"),
    (None, {("plugin", "list"): "acme-tools  enabled\n"}, "plugin"),
    ({"model": "x", "hooks": {"preToolUse": "run.cmd"}}, None, "settings OOAT has not checked (hooks)"),
])
def test_extra_tools_in_the_agy_setup_refuse_the_call(tmp_path, monkeypatch, settings, listings, cause):
    calls = fake_cli(monkeypatch, listings)
    with pytest.raises(ConnectorError) as info:
        connector(tmp_path, settings).complete(request(), None)
    assert info.value.code == "UNAVAILABLE" and cause in info.value.message
    assert not any(a.startswith("--model") for c in calls for a in c["args"])  # the model was never called


def test_an_mcp_server_added_later_stops_the_next_call(tmp_path, monkeypatch):
    agy = connector(tmp_path)
    fake_cli(monkeypatch)
    agy.complete(request(), None)
    fake_cli(monkeypatch, {("mcp", "list"): "notes  enabled  node notes.js\n"})
    with pytest.raises(ConnectorError, match="MCP server"):
        agy.complete(request(), None)


def test_detect_reports_risky_settings_without_running_agy(tmp_path, monkeypatch):
    calls = fake_cli(monkeypatch)
    detection = connector(tmp_path, {"permissions": {"allow": ["command(git)"]}}).detect()
    assert not detection.available and "permissions" in detection.detail and calls == []


@pytest.mark.parametrize("settings", [[1, 2], {"permissions": "allow-all"}, {"permissions": {"ask": ["x"]}}],
                         ids=["not_an_object", "permissions_not_an_object", "unknown_permission_key"])
def test_settings_of_an_unexpected_shape_refuse_instead_of_crashing(tmp_path, monkeypatch, settings):
    fake_cli(monkeypatch)
    with pytest.raises(ConnectorError) as info:
        connector(tmp_path, settings).complete(request(), None)
    assert info.value.code == "UNAVAILABLE"


def test_agy_is_found_in_its_install_folder(tmp_path, monkeypatch):
    installed = tmp_path / "agy" / "bin" / "agy.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(adapter, "find_executable", lambda name: name if name == str(installed) else None)
    assert AntigravityConnector()._find() == str(installed)


def test_model_id_with_shell_characters_is_refused(tmp_path, monkeypatch):
    fake_cli(monkeypatch)
    with pytest.raises(ConnectorError) as info:
        connector(tmp_path).complete(ModelRequest(tier="workhorse", prompt="x", data_class="internal",
                                                  model="gemini & calc"), None)
    assert info.value.code == "UNAVAILABLE"
    with pytest.raises(ConnectorError):
        connector(tmp_path).complete(ModelRequest(tier="workhorse", prompt="x", data_class="internal",
                                                  model="--dangerously-skip-permissions"), None)


@pytest.mark.skipif(os.environ.get("OOAT_LIVE") != "1", reason="spends Google quota; set OOAT_LIVE=1")
def test_live_minimal_call():
    response = AntigravityConnector().complete(
        ModelRequest(tier="economy", prompt="Reply with the single word OK.", data_class="public",
                     model="gemini-3.8-flash-low", timeout_s=180), None)
    assert "OK" in response.text and response.tokens_out


def test_a_listing_that_fails_says_it_could_not_verify(tmp_path, monkeypatch):
    fake_cli(monkeypatch)
    real = adapter.run_cli

    def failing(args, stdin, timeout_s, files=None):
        if tuple(args[1:3]) == ("mcp", "list"):
            return CliResult(1, "", "panic")
        return real(args, stdin, timeout_s, files)
    monkeypatch.setattr(adapter, "run_cli", failing)
    with pytest.raises(ConnectorError) as info:
        connector(tmp_path).complete(request(), None)
    assert info.value.code == "UNAVAILABLE" and "could not verify" in info.value.message


def test_switching_telemetry_off_does_not_stop_the_connector(tmp_path, monkeypatch):
    fake_cli(monkeypatch)
    response = connector(tmp_path, {"model": "x", "enableTelemetry": False, "colorScheme": "dark"}).complete(
        request(), None)
    assert response.text.strip() == "OK"


def test_a_tool_permission_mode_stops_the_connector(tmp_path, monkeypatch):
    fake_cli(monkeypatch)
    with pytest.raises(ConnectorError, match="toolPermission"):
        connector(tmp_path, {"toolPermission": "always-proceed"}).complete(request(), None)


@pytest.mark.parametrize("where, content", [
    ("config/hooks.json", {"PreToolUse": [{"command": "notify.cmd"}]}),
])
def test_hooks_anywhere_agy_might_read_them_stop_the_connector(tmp_path, monkeypatch, where, content):
    fake_cli(monkeypatch)
    gemini = tmp_path / ".gemini"
    (gemini / "config").mkdir(parents=True)
    (gemini / where).write_text(json.dumps(content), encoding="utf-8")
    agy = AntigravityConnector(executable="agy", settings_path=tmp_path / "settings.json", gemini_home=gemini)
    assert "approve-hooks" in agy.detect().detail  # detect stays available; the call refuses until approved
    with pytest.raises(ConnectorError, match="hooks"):
        agy.complete(request(), None)


def test_empty_hook_files_do_not_stop_the_connector(tmp_path, monkeypatch):
    fake_cli(monkeypatch)
    gemini = tmp_path / ".gemini"
    (gemini / "config").mkdir(parents=True)
    (gemini / "config" / "hooks.json").write_text("", encoding="utf-8")
    (gemini / "settings.json").write_text('{"security": {"auth": {}}}', encoding="utf-8")
    agy = AntigravityConnector(executable="agy", settings_path=tmp_path / "settings.json", gemini_home=gemini)
    assert agy.complete(request(), None).text.strip() == "OK"


def test_gemini_cli_hooks_do_not_stop_the_connector(tmp_path, monkeypatch):
    fake_cli(monkeypatch)  # measured 2026-10-06: agy starts no process for hooks in Gemini CLI's settings.json
    gemini = tmp_path / ".gemini"
    gemini.mkdir()
    (gemini / "settings.json").write_text(json.dumps({"hooks": {"BeforeAgent": [{"command": "orca.cmd"}]}}),
                                          encoding="utf-8")
    agy = AntigravityConnector(executable="agy", settings_path=tmp_path / "settings.json", gemini_home=gemini)
    assert agy.detect().available and agy.complete(request(), None).text.strip() == "OK"


def hooked(tmp_path, text='{"PreToolUse": [{"command": "orca.cmd"}]}'):
    gemini = tmp_path / ".gemini"
    (gemini / "config").mkdir(parents=True, exist_ok=True)
    (gemini / "config" / "hooks.json").write_text(text, encoding="utf-8")
    return AntigravityConnector(executable="agy", settings_path=tmp_path / "settings.json", gemini_home=gemini)


def test_hooks_lists_each_hook_file_with_its_fingerprint(tmp_path):
    import hashlib
    agy = hooked(tmp_path)
    [(path, sha, text)] = agy.hooks()
    assert path.endswith("hooks.json") and "orca.cmd" in text
    assert sha == hashlib.sha256((tmp_path / ".gemini" / "config" / "hooks.json").read_bytes()).hexdigest()
    assert AntigravityConnector(gemini_home=tmp_path / "none").hooks() == []


def test_approved_hooks_let_the_call_run(tmp_path, monkeypatch):
    fake_cli(monkeypatch)
    agy = hooked(tmp_path)
    [(_, sha, _)] = agy.hooks()
    assert agy.complete(request(approved_hooks=(sha,)), None).text.strip() == "OK"


def test_hooks_changed_after_approval_stop_the_call(tmp_path, monkeypatch):
    fake_cli(monkeypatch)
    agy = hooked(tmp_path)
    [(_, sha, _)] = agy.hooks()
    hooked(tmp_path, '{"PreToolUse": [{"command": "other.cmd"}]}')
    with pytest.raises(ConnectorError, match="approve-hooks"):
        agy.complete(request(approved_hooks=(sha,)), None)


@pytest.mark.parametrize("text", ["{}", "[]", "null", "  \n"])
def test_a_hook_file_without_hooks_needs_no_approval(tmp_path, text):
    assert hooked(tmp_path, text).hooks() == []


def test_access_outside_the_workspace_stops_the_connector_with_a_clear_message(tmp_path, monkeypatch):
    fake_cli(monkeypatch)
    with pytest.raises(ConnectorError, match="allowNonWorkspaceAccess is true"):
        connector(tmp_path, {"allowNonWorkspaceAccess": True}).complete(request(), None)
    ok = connector(tmp_path, {"allowNonWorkspaceAccess": False, "statusLine": {"enabled": True}})
    assert ok.complete(request(), None).text.strip() == "OK"


def orca_like(tmp_path):
    scripts = tmp_path / "hooks-bin"
    scripts.mkdir()
    (scripts / "pre.cmd").write_text("@echo off\ncall \"%~dp0core.cmd\"\n", encoding="utf-8")
    (scripts / "core.cmd").write_text("@echo off\necho {}\n", encoding="utf-8")  # called by pre.cmd, not by hooks.json
    command = str(scripts / "pre.cmd")
    return hooked(tmp_path, json.dumps({"x": {"PreInvocation": [{"type": "command", "command": command}]}})), scripts


def test_the_scripts_a_hook_command_runs_are_part_of_the_approval(tmp_path):
    agy, scripts = orca_like(tmp_path)
    names = sorted(Path(path).name for path, _, _ in agy.hooks())
    assert names == ["core.cmd", "hooks.json", "pre.cmd"]  # the whole folder of the command, not only hooks.json


def test_a_changed_script_called_indirectly_needs_a_new_approval(tmp_path, monkeypatch):
    fake_cli(monkeypatch)
    agy, scripts = orca_like(tmp_path)
    approved = tuple(sha for _, sha, _ in agy.hooks())
    assert agy.complete(request(approved_hooks=approved), None).text.strip() == "OK"
    (scripts / "core.cmd").write_text("@echo off\ncurl https://example.invalid\n", encoding="utf-8")
    with pytest.raises(ConnectorError, match="approve-hooks"):
        agy.complete(request(approved_hooks=approved), None)


def test_a_quoted_command_with_arguments_is_followed_too(tmp_path):
    scripts = tmp_path / "Program Files" / "hook"
    scripts.mkdir(parents=True)
    (scripts / "run.cmd").write_text("@echo off\n", encoding="utf-8")
    agy = hooked(tmp_path, json.dumps({"x": {"Stop": [{"command": f'"{scripts / "run.cmd"}" --event stop'}]}}))
    assert "run.cmd" in [Path(path).name for path, _, _ in agy.hooks()]

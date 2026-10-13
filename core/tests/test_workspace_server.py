"""The workspace tools over MCP (stdio, newline-delimited JSON-RPC 2.0)."""

import io
import json
import os
import subprocess
import sys

import pytest

from ooat_core.workspace import WorkspaceGrant, mcp_config
from ooat_core.workspace.server import TOOLS, handle, serve
from ooat_core.workspace.tools import Workspace, read_journal


def grant(root, tmp_path, write=True):
    return WorkspaceGrant(project="bots", folders=(("Bots", os.path.realpath(root)),), write=write, deny=(),
                          hidden=(), max_operations=300, max_write_bytes=5 * 1024 * 1024,
                          journal_dir=str(tmp_path / "journal"))


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "Bots"
    root.mkdir()
    (root / "Průvodce.md").write_text("Ahoj světe\n", encoding="utf-8")
    return root


def test_initialize_lists_the_tools_and_answers_ping(root, tmp_path):
    ws = Workspace(grant(root, tmp_path))
    init = handle(ws, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["capabilities"] == {"tools": {}}
    assert handle(ws, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert handle(ws, {"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}
    names = [t["name"] for t in handle(ws, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]]
    assert names == ["list_dir", "find_files", "search", "read_file", "edit_file", "write_file"]


def test_a_read_only_grant_lists_no_write_tools(root, tmp_path):
    ws = Workspace(grant(root, tmp_path, write=False))
    tools = handle(ws, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    assert [t["name"] for t in tools] == ["list_dir", "find_files", "search", "read_file"]


def test_a_tool_call_answers_with_text_and_a_refusal_is_an_error_result(root, tmp_path):
    ws = Workspace(grant(root, tmp_path))
    ok = handle(ws, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": "read_file", "arguments": {"path": "Bots/Průvodce.md"}}})
    assert ok["result"]["isError"] is False and "Ahoj světe" in ok["result"]["content"][0]["text"]
    refused = handle(ws, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                          "params": {"name": "read_file", "arguments": {"path": "/etc/passwd"}}})
    assert refused["result"]["isError"] is True and "absolute" in refused["result"]["content"][0]["text"]


def test_unknown_methods_and_bad_json_get_json_rpc_errors(root, tmp_path):
    ws = Workspace(grant(root, tmp_path))
    assert handle(ws, {"jsonrpc": "2.0", "id": 1, "method": "resources/list"})["error"]["code"] == -32601
    out = io.StringIO()
    serve(ws, io.StringIO("not json\n\n"), out)
    assert json.loads(out.getvalue())["error"]["code"] == -32700


def test_every_tool_has_an_object_schema_with_its_required_arguments():
    required = {"list_dir": ["path"], "find_files": ["pattern"], "search": ["query"], "read_file": ["path"],
                "edit_file": ["path", "old", "new"], "write_file": ["path", "content"]}
    assert {t["name"]: t["inputSchema"]["required"] for t in TOOLS} == required
    assert all(t["inputSchema"]["type"] == "object" and t["description"] for t in TOOLS)


def test_the_module_serves_utf8_json_lines_over_stdio(root, tmp_path):
    config = json.loads(mcp_config(grant(root, tmp_path)))["mcpServers"]["ooat_workspace"]
    assert config["command"] == sys.executable and config["args"][:2] == ["-m", "ooat_core.workspace"]
    messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "edit_file", "arguments": {"path": "Bots/Průvodce.md", "old": "světe",
                                                               "new": "Česko"}}}]
    stdin = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages).encode("utf-8")
    done = subprocess.run([config["command"], *config["args"]], input=stdin, capture_output=True, timeout=60)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.split(b"\n")
    assert lines[-1] == b"" and all(not line.endswith(b"\r") for line in lines)
    answers = [json.loads(line) for line in lines[:-1]]
    assert [a["id"] for a in answers] == [1, 2] and answers[1]["result"]["isError"] is False
    assert (root / "Průvodce.md").read_text(encoding="utf-8") == "Ahoj Česko\n"
    assert read_journal(tmp_path / "journal")[-1]["path"] == "Bots/Průvodce.md"


def test_the_module_refuses_to_start_without_a_grant_file():
    done = subprocess.run([sys.executable, "-m", "ooat_core.workspace"], capture_output=True, timeout=60)
    assert done.returncode == 2 and b"usage" in done.stderr


def test_a_malformed_call_is_an_error_answer_not_the_end_of_the_server(root, tmp_path):
    ws = Workspace(grant(root, tmp_path))
    for params in ("x", {"name": "list_dir", "arguments": "x"}):
        answer = handle(ws, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
        assert answer["result"]["isError"] is True
    assert handle(ws, {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": "x"})["result"]

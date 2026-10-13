"""The runtime's side of a project workspace: grants, the lock, the journal in the ledger (design 07 §5, §7)."""

import json
import os
from types import SimpleNamespace
from unittest.mock import ANY

import pytest

from ooat_core.artifacts import ArtifactStore
from ooat_core.blobs import BlobStore
from ooat_core.config import parse_config
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger
from ooat_core.workspace.grant import WorkspaceUnavailable
from ooat_core.workspace.runs import JournalLost, Workspaces, change_section
from ooat_core.workspace.tools import ToolError, Workspace

ORIGINAL = b"import os\r\n\r\ndef main():\r\n    return 1\r\n"


@pytest.fixture
def s(tmp_path):
    root = tmp_path / "Bots"
    (root / "src").mkdir(parents=True)
    (root / "src" / "bot.py").write_bytes(ORIGINAL)
    (root / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    config = parse_config({"projects": {"bots": {"folders": [str(root)], "write": True, "max_operations": 5}}})
    ledger = Ledger.open("sqlite:///:memory:")
    return SimpleNamespace(root=root, ledger=ledger, artifacts=ArtifactStore(ledger, BlobStore(tmp_path / "blobs")),
                           workspaces=Workspaces(config, None, tmp_path / "ws"), task=new_id("tsk"))


def record(s, grant, role="worker"):
    return s.workspaces.record(s.ledger, s.artifacts, task=s.task, contract=None, role=role, grant=grant,
                               data_class="internal")


def write_journal(grant, *lines):
    os.makedirs(grant.journal_dir, exist_ok=True)
    with open(os.path.join(grant.journal_dir, "journal.jsonl"), "w", encoding="utf-8", newline="\n") as journal:
        journal.write("".join(json.dumps(line) + "\n" for line in lines))


def test_grants_are_per_task_and_role_and_a_raised_limit_multiplies(s):
    worker, critic = s.workspaces.grant(s.task, "bots"), s.workspaces.grant(s.task, "bots", role="critic")
    assert worker.write and not critic.write and worker.journal_dir != critic.journal_dir
    assert worker.journal_dir.endswith("worker") and s.task in worker.journal_dir
    raised = s.workspaces.grant(s.task, "bots", factor=2)
    assert (raised.max_operations, raised.max_write_bytes) == (10, worker.max_write_bytes * 2)
    assert s.workspaces.timeout_s("bots") == 30 * 60
    with pytest.raises(WorkspaceUnavailable, match="not in ooat.toml"):
        s.workspaces.grant(s.task, "gone")


def test_the_journal_becomes_workspace_used_with_originals_and_a_diff(s):
    grant = s.workspaces.grant(s.task, "bots")
    tools = Workspace(grant)
    tools.call("read_file", {"path": "Bots/src/bot.py"})
    tools.call("edit_file", {"path": "Bots/src/bot.py", "old": "return 1", "new": "return 2"})
    tools.call("write_file", {"path": "Bots/tests/test_bot.py", "content": "def test():\n    pass\n"})
    with pytest.raises(ToolError):
        tools.call("read_file", {"path": "Bots/.env"})
    body = record(s, grant)["body"]
    assert body["read"] == [{"path": "Bots/src/bot.py", "times": 1}]
    (changed,) = body["changed"]
    assert (changed["path"], changed["added"], changed["removed"]) == ("Bots/src/bot.py", 1, 1)
    assert s.artifacts.read(changed["original"]) == ORIGINAL
    assert s.ledger.artifact(changed["original"])["type"] == "workspace_original"
    assert body["created"] == [{"path": "Bots/tests/test_bot.py", "after": ANY, "added": 2}]
    assert body["refused"] == [{"path": "Bots/.env", "tool": "read_file", "reason": "protected file"}]
    assert (body["operations"], body["limit"], body["journal_lines"], body["by"]) == (4, None, 4, "worker")
    diff = s.artifacts.read(body["diff"]).decode("utf-8")
    assert "-    return 1" in diff and "+    return 2" in diff and "+++ b/Bots/tests/test_bot.py" in diff
    assert "TOKEN" not in json.dumps(body)


def test_each_record_covers_only_the_lines_since_the_last_one_of_its_role(s):
    grant = s.workspaces.grant(s.task, "bots")
    Workspace(grant).call("read_file", {"path": "Bots/src/bot.py"})
    assert record(s, grant)["body"]["journal_lines"] == 1
    assert record(s, grant) is None  # nothing new: no event
    Workspace(grant).call("list_dir", {"path": "Bots"})
    second = record(s, grant)["body"]
    assert (second["read"], second["journal_lines"], second["operations"]) == ([], 2, 2)
    critic = s.workspaces.grant(s.task, "bots", role="critic")
    Workspace(critic).call("read_file", {"path": "Bots/src/bot.py"})
    assert record(s, critic, "critic")["body"]["journal_lines"] == 1


def test_the_limit_names_the_operation_the_tool_and_the_path(s):
    grant = s.workspaces.grant(s.task, "bots")
    tools = Workspace(grant)
    for _ in range(5):
        tools.call("read_file", {"path": "Bots/src/bot.py"})
    with pytest.raises(ToolError):
        tools.call("edit_file", {"path": "Bots/src/bot.py", "old": "return 1", "new": "return 2"})
    assert record(s, grant)["body"]["limit"] == {"kind": "operations", "operation": 6, "tool": "edit_file",
                                                 "path": "Bots/src/bot.py"}


def test_a_failed_write_is_not_a_change_and_a_long_path_is_cut(s):
    grant = s.workspaces.grant(s.task, "bots")
    write_journal(grant,
                  {"n": 1, "tool": "write_file", "path": "Bots/x.txt", "real": "x", "before": None,
                   "after": "sha256:" + "0" * 64, "bytes": 3, "added": 1, "removed": 0},
                  {"n": 1, "tool": "write_file", "path": "Bots/x.txt", "failed": True},
                  {"n": 2, "tool": "read_file", "path": "Bots/" + "k" * 5000, "refused": "protected file"})
    body = record(s, grant)["body"]
    assert (body["created"], body["changed"], body["written_bytes"], "diff" in body) == ([], [], 0, False)
    assert len(body["refused"][0]["path"]) == 300


def test_a_path_segment_that_looks_like_a_token_never_reaches_the_ledger(s):
    secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    grant = s.workspaces.grant(s.task, "bots")
    write_journal(grant, {"n": 1, "tool": "read_file", "path": f"Bots/{secret}/x", "refused": "unknown"},
                  {"n": 2, "tool": "read_file", "path": "Bots/a_rather_long_but_ordinary_file_name_for_tests.py"})
    body = record(s, grant)["body"]
    assert body["refused"][0]["path"] == "Bots/[hidden]/x" and secret not in json.dumps(body)
    assert body["read"] == [{"path": "Bots/a_rather_long_but_ordinary_file_name_for_tests.py", "times": 1}]


def test_an_original_with_personal_data_is_stored_in_a_raised_class(s):
    (s.root / "src" / "contacts.txt").write_text("jan.novak@example.cz\n", encoding="utf-8")
    grant = s.workspaces.grant(s.task, "bots")
    Workspace(grant).call("edit_file", {"path": "Bots/src/contacts.txt", "old": "jan", "new": "petr"})
    body = record(s, grant)["body"]
    assert s.ledger.artifact(body["changed"][0]["original"])["data_class"] == "personal"
    assert s.ledger.artifact(body["diff"])["data_class"] == "personal"


def test_a_damaged_journal_is_lost_not_guessed(s):
    grant = s.workspaces.grant(s.task, "bots")
    write_journal(grant, {"n": 1, "tool": "read_file", "path": "Bots/src/bot.py"})
    with open(os.path.join(grant.journal_dir, "journal.jsonl"), "a", encoding="utf-8") as journal:
        journal.write("{broken\n")
    with pytest.raises(JournalLost):
        record(s, grant)


def test_the_change_section_lists_what_the_worker_changed_and_created(s):
    grant = s.workspaces.grant(s.task, "bots")
    tools = Workspace(grant)
    tools.call("edit_file", {"path": "Bots/src/bot.py", "old": "return 1", "new": "return 2"})
    tools.call("write_file", {"path": "Bots/new.md", "content": "a\nb\n"})
    with pytest.raises(ToolError):
        tools.call("read_file", {"path": "Bots/.env"})
    record(s, grant)
    section = change_section(s.ledger.events(task=s.task))
    assert section.startswith("## Files changed (recorded by OOAT)")
    assert "- `Bots/src/bot.py`: changed, +1 -1" in section and "- `Bots/new.md`: created, +2" in section
    assert "1 operation was refused" in section
    assert "- none" in change_section([])


def test_a_project_lock_is_held_by_one_holder(s):
    first, second = s.workspaces.lock("bots"), s.workspaces.lock("bots")
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


def test_the_mcp_server_never_imports_the_ledger():
    import subprocess
    import sys

    code = "import sys, ooat_core.workspace.__main__; print('ooat_core.ledger' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"

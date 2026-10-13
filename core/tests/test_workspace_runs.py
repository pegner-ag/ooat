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


from ooat_core.workspace.runs import AlreadyReverted, WorkspaceBusy  # noqa: E402
from ooat_core.workspace.tools import sha256  # noqa: E402

EDITED = ORIGINAL.replace(b"return 1", b"return 2")


def changed_task(s):
    """One worker call: bot.py edited, a test file created; recorded."""
    grant = s.workspaces.grant(s.task, "bots")
    tools = Workspace(grant)
    tools.call("edit_file", {"path": "Bots/src/bot.py", "old": "return 1", "new": "return 2"})
    tools.call("write_file", {"path": "Bots/tests/test_bot.py", "content": "def test():\n    pass\n"})
    record(s, grant)
    return grant


def revert(s, **extra):
    return s.workspaces.revert(s.ledger, s.artifacts, s.task, operator="Martin", **extra)


def test_revert_writes_the_originals_back_byte_for_byte_and_keeps_created_files(s):
    changed_task(s)
    assert (s.root / "src" / "bot.py").read_bytes() == EDITED
    event = revert(s, channel="cli")
    assert (s.root / "src" / "bot.py").read_bytes() == ORIGINAL  # CRLF kept exactly
    assert (s.root / "tests" / "test_bot.py").exists()
    assert event["body"] == {"project": "bots", "restored": [{"path": "Bots/src/bot.py", "after": sha256(ORIGINAL)}],
                             "skipped": [], "kept": ["Bots/tests/test_bot.py"], "channel": "cli"}
    assert event["actor"] == {"kind": "hil", "id": "Martin"}


def test_revert_skips_a_file_changed_since_the_task_and_runs_once(s):
    changed_task(s)
    (s.root / "src" / "bot.py").write_bytes(b"changed by hand\r\n")
    event = revert(s)
    assert event["body"]["skipped"] == [{"path": "Bots/src/bot.py", "reason": "changed since the task"}]
    assert (s.root / "src" / "bot.py").read_bytes() == b"changed by hand\r\n"
    with pytest.raises(AlreadyReverted):
        revert(s)


def test_a_file_created_and_edited_in_a_later_call_stays_created(s):
    grant = s.workspaces.grant(s.task, "bots")
    Workspace(grant).call("write_file", {"path": "Bots/notes.md", "content": "a\n"})
    record(s, grant)
    Workspace(grant).call("edit_file", {"path": "Bots/notes.md", "old": "a", "new": "b"})
    record(s, grant)
    event = revert(s)
    assert (event["body"]["restored"], event["body"]["kept"]) == ([], ["Bots/notes.md"])
    assert (s.root / "notes.md").read_text(encoding="utf-8") == "b\n"


def test_revert_does_not_write_while_the_project_is_locked(s):
    changed_task(s)
    lock = s.workspaces.lock("bots")
    assert lock.acquire()
    try:
        with pytest.raises(WorkspaceBusy):
            revert(s)
    finally:
        lock.release()
    assert (s.root / "src" / "bot.py").read_bytes() == EDITED


def test_revert_goes_through_the_guard_of_the_projects_current_config(s, tmp_path):
    changed_task(s)
    s.workspaces = Workspaces(parse_config({"projects": {"bots": {"folders": [str(s.root)], "write": True,
                                                                  "deny": ["src/**"]}}}), None, tmp_path / "ws")
    event = revert(s)
    assert event["body"]["skipped"] == [{"path": "Bots/src/bot.py",
                                         "reason": "refused: denied by the project's settings"}]
    assert (s.root / "src" / "bot.py").read_bytes() == EDITED


def test_a_revert_the_ledger_refuses_leaves_the_files_as_they_were(s, monkeypatch):
    changed_task(s)

    def refuse(event, artifacts=()):
        raise OSError("disk full")

    monkeypatch.setattr(s.ledger, "append", refuse)
    with pytest.raises(OSError):
        revert(s)
    assert (s.root / "src" / "bot.py").read_bytes() == EDITED  # written back to what it was before the revert


def test_a_task_that_changed_nothing_has_nothing_to_revert(s):
    with pytest.raises(ValueError, match="changed no project files"):
        revert(s)


# Final review of plan 07b ----------------------------------------------------------------------------------------

from ooat_core.workspace import runs as runs_module  # noqa: E402
from ooat_core.workspace import tools as tools_module  # noqa: E402

BY_HAND = EDITED.replace(b"import os", b"import sys")


def test_an_edit_by_someone_else_between_calls_is_never_overwritten(s):
    grant = s.workspaces.grant(s.task, "bots")
    Workspace(grant).call("edit_file", {"path": "Bots/src/bot.py", "old": "return 1", "new": "return 2"})
    record(s, grant)
    (s.root / "src" / "bot.py").write_bytes(BY_HAND)  # the operator, while the task waits
    Workspace(grant).call("edit_file", {"path": "Bots/src/bot.py", "old": "return 2", "new": "return 3"})
    record(s, grant)
    event = revert(s)
    assert event["body"]["skipped"] == [{"path": "Bots/src/bot.py",
                                         "reason": "changed by someone else during the task"}]
    assert b"import sys" in (s.root / "src" / "bot.py").read_bytes()


def test_an_edit_by_someone_else_within_one_call_is_never_overwritten(s):
    grant = s.workspaces.grant(s.task, "bots")
    tools = Workspace(grant)
    tools.call("edit_file", {"path": "Bots/src/bot.py", "old": "return 1", "new": "return 2"})
    (s.root / "src" / "bot.py").write_bytes(BY_HAND)
    tools.call("edit_file", {"path": "Bots/src/bot.py", "old": "return 2", "new": "return 3"})
    record(s, grant)
    assert revert(s)["body"]["skipped"][0]["reason"] == "changed by someone else during the task"
    assert b"import sys" in (s.root / "src" / "bot.py").read_bytes()


def test_a_failed_first_write_keeps_the_original_for_the_diff_and_revert(s, monkeypatch):
    written = tools_module._atomic_write
    attempts = []

    def locked_once(path, data):
        attempts.append(path)
        if len(attempts) == 1:
            raise PermissionError("the file is open in another process")
        written(path, data)

    monkeypatch.setattr(tools_module, "_atomic_write", locked_once)
    grant = s.workspaces.grant(s.task, "bots")
    tools = Workspace(grant)
    with pytest.raises(ToolError):
        tools.call("edit_file", {"path": "Bots/src/bot.py", "old": "return 1", "new": "return 2"})
    tools.call("edit_file", {"path": "Bots/src/bot.py", "old": "return 1", "new": "return 2"})
    body = record(s, grant)["body"]
    assert s.artifacts.read(body["changed"][0]["original"]) == ORIGINAL
    assert "+    return 2" in s.artifacts.read(body["diff"]).decode("utf-8")
    assert revert(s)["body"]["restored"][0]["path"] == "Bots/src/bot.py"
    assert (s.root / "src" / "bot.py").read_bytes() == ORIGINAL


def two_changed_files(s):
    (s.root / "README.md").write_bytes(b"# Bots\n")
    grant = s.workspaces.grant(s.task, "bots")
    tools = Workspace(grant)
    tools.call("edit_file", {"path": "Bots/src/bot.py", "old": "return 1", "new": "return 2"})
    tools.call("edit_file", {"path": "Bots/README.md", "old": "Bots", "new": "Boti"})
    record(s, grant)


def test_a_file_locked_during_revert_is_skipped_and_the_rest_is_reverted(s, monkeypatch):
    two_changed_files(s)
    written = runs_module._atomic_write

    def locked(path, data):
        if path.name == "bot.py":
            raise PermissionError("the file is open in another process")
        written(path, data)

    monkeypatch.setattr(runs_module, "_atomic_write", locked)
    event = revert(s)
    assert event["body"]["skipped"] == [{"path": "Bots/src/bot.py", "reason": "not writable now (open elsewhere?)"}]
    assert event["body"]["restored"][0]["path"] == "Bots/README.md"
    assert (s.root / "README.md").read_bytes() == b"# Bots\n"


def test_when_the_ledger_refuses_every_undo_is_tried(s, monkeypatch):
    two_changed_files(s)
    written, undone = runs_module._atomic_write, []

    def undo_of_readme_fails(path, data):
        if path.name == "README.md" and data == b"# Boti\n":  # writing README back to what the task left
            raise PermissionError("locked")
        undone.append(path.name)
        written(path, data)

    def refuse(event, artifacts=()):
        raise OSError("disk full")

    monkeypatch.setattr(runs_module, "_atomic_write", undo_of_readme_fails)
    monkeypatch.setattr(s.ledger, "append", refuse)
    with pytest.raises(OSError):
        revert(s)
    assert (s.root / "src" / "bot.py").read_bytes() == EDITED  # undone although README's undo failed

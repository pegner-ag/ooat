"""The workspace tools and their journal (design 07 §5, §7)."""

import os

import pytest

from ooat_core.workspace import WorkspaceGrant
from ooat_core.workspace.tools import STOP, ToolError, Workspace, read_journal


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "Bots"
    (root / "src").mkdir(parents=True)
    (root / "src" / "bot.py").write_bytes(b"import os\r\n\r\ndef main():\r\n    return 1\r\n")
    (root / "README.md").write_text("# Bots\nPrůvodce\n", encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0")
    (root / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    return root


def workspace(root, tmp_path, write=True, operations=300, write_bytes=5 * 1024 * 1024):
    return Workspace(WorkspaceGrant(project="bots", folders=(("Bots", os.path.realpath(root)),), write=write,
                                    deny=(), hidden=(), max_operations=operations, max_write_bytes=write_bytes,
                                    journal_dir=str(tmp_path / "journal")))


def test_list_dir_shows_sizes_and_folders_and_hides_protected_files(root, tmp_path):
    out = workspace(root, tmp_path).call("list_dir", {"path": "Bots"})
    assert "src/" in out and "README.md" in out and ".env" not in out


def test_find_files_matches_shown_paths_and_skips_protected_ones(root, tmp_path):
    ws = workspace(root, tmp_path)
    assert ws.call("find_files", {"pattern": "**/*.py"}) == "Bots/src/bot.py"
    assert ".env" not in ws.call("find_files", {"pattern": "Bots/**"})


def test_find_files_does_not_follow_a_link_into_a_loop(root, tmp_path):
    try:
        os.symlink(root, root / "src" / "loop", target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks needs a privilege on this machine")
    assert workspace(root, tmp_path).call("find_files", {"pattern": "**/*.py"}) == "Bots/src/bot.py"


def test_search_finds_lines_in_text_files_only(root, tmp_path):
    ws = workspace(root, tmp_path)
    assert ws.call("search", {"query": "def main"}) == "Bots/src/bot.py:3: def main():"
    assert ws.call("search", {"query": r"Pr.vodce", "regex": True}) == "Bots/README.md:2: Průvodce"
    assert ws.call("search", {"query": "PNG"}) == "(no matches)"
    with pytest.raises(ToolError, match="regular expression"):
        ws.call("search", {"query": "(", "regex": True})


def test_read_file_reads_a_line_range_and_refuses_binary_and_protected_files(root, tmp_path):
    ws = workspace(root, tmp_path)
    out = ws.call("read_file", {"path": "Bots/src/bot.py", "offset": 3, "limit": 1})
    assert out.splitlines()[0] == "Bots/src/bot.py, lines 3-3 of 4; read on with offset=4"
    assert out.splitlines()[1] == "def main():"
    with pytest.raises(ToolError, match="not a text file"):
        ws.call("read_file", {"path": "Bots/logo.png"})
    with pytest.raises(ToolError, match="protected file"):
        ws.call("read_file", {"path": "Bots/.env"})


def test_edit_file_replaces_one_occurrence_and_keeps_crlf(root, tmp_path):
    ws = workspace(root, tmp_path)
    assert ws.call("edit_file", {"path": "Bots/src/bot.py", "old": "def main():\n    return 1",
                                 "new": "def main():\n    return 2"}) == "edited Bots/src/bot.py"
    assert (root / "src" / "bot.py").read_bytes() == b"import os\r\n\r\ndef main():\r\n    return 2\r\n"
    (entry,) = [e for e in read_journal(tmp_path / "journal") if e["tool"] == "edit_file"]
    assert (entry["added"], entry["removed"]) == (1, 1) and entry["before"] != entry["after"]
    assert (tmp_path / "journal" / entry["original"]).read_bytes().endswith(b"return 1\r\n")


def test_edit_file_refuses_text_that_occurs_zero_or_several_times(root, tmp_path):
    ws = workspace(root, tmp_path)
    with pytest.raises(ToolError, match="0 times"):
        ws.call("edit_file", {"path": "Bots/src/bot.py", "old": "return 9", "new": "x"})
    (root / "twice.txt").write_text("a\na\n", encoding="utf-8")
    with pytest.raises(ToolError, match="2 times"):
        ws.call("edit_file", {"path": "Bots/twice.txt", "old": "a", "new": "b"})


def test_write_file_creates_parents_and_keeps_the_files_line_endings(root, tmp_path):
    ws = workspace(root, tmp_path)
    ws.call("write_file", {"path": "Bots/tests/test_x.py", "content": "def test():\n    pass\n"})
    assert (root / "tests" / "test_x.py").read_bytes() == b"def test():\n    pass\n"
    ws.call("write_file", {"path": "Bots/src/bot.py", "content": "print(1)\n"})
    assert (root / "src" / "bot.py").read_bytes() == b"print(1)\r\n"
    created, replaced = [e for e in read_journal(tmp_path / "journal") if e["tool"] == "write_file"]
    assert created["before"] is None and "original" not in created
    assert replaced["original"] and replaced["removed"] == 4 and replaced["added"] == 1


def test_only_the_first_change_of_a_file_saves_its_original(root, tmp_path):
    ws = workspace(root, tmp_path)
    ws.call("edit_file", {"path": "Bots/README.md", "old": "# Bots", "new": "# Bots 1"})
    ws.call("edit_file", {"path": "Bots/README.md", "old": "# Bots 1", "new": "# Bots 2"})
    originals = [e["original"] for e in read_journal(tmp_path / "journal") if e.get("original")]
    assert len(originals) == 1
    assert (tmp_path / "journal" / originals[0]).read_text(encoding="utf-8") == "# Bots\nPrůvodce\n"


def test_a_read_only_grant_refuses_writes(root, tmp_path):
    ws = workspace(root, tmp_path, write=False)
    with pytest.raises(ToolError, match="read only"):
        ws.call("write_file", {"path": "Bots/x.txt", "content": "x"})
    assert not (root / "x.txt").exists()


def test_the_operation_limit_stops_every_later_call_and_names_where(root, tmp_path):
    ws = workspace(root, tmp_path, operations=2)
    ws.call("list_dir", {"path": "Bots"})
    ws.call("read_file", {"path": "Bots/README.md"})
    for _ in range(2):
        with pytest.raises(ToolError) as info:
            ws.call("edit_file", {"path": "Bots/README.md", "old": "# Bots", "new": "#"})
        assert str(info.value) == STOP
    limits = [e for e in read_journal(tmp_path / "journal") if e.get("limit")]
    assert limits == [{"n": 3, "tool": "edit_file", "path": "Bots/README.md", "limit": "operations"}]
    assert (root / "README.md").read_text(encoding="utf-8").startswith("# Bots")


def test_the_write_limit_refuses_the_write_that_would_pass_it(root, tmp_path):
    ws = workspace(root, tmp_path, write_bytes=10)
    with pytest.raises(ToolError) as info:
        ws.call("write_file", {"path": "Bots/big.txt", "content": "x" * 11})
    assert str(info.value) == STOP and not (root / "big.txt").exists()
    (limit,) = [e for e in read_journal(tmp_path / "journal") if e.get("limit")]
    assert limit["limit"] == "write_bytes" and limit["path"] == "Bots/big.txt"


def test_a_second_server_on_the_same_journal_continues_the_counts(root, tmp_path):
    first = workspace(root, tmp_path)
    first.call("edit_file", {"path": "Bots/README.md", "old": "# Bots", "new": "# Bots 1"})
    second = workspace(root, tmp_path, operations=2)
    second.call("edit_file", {"path": "Bots/README.md", "old": "# Bots 1", "new": "# Bots 2"})
    with pytest.raises(ToolError):
        second.call("list_dir", {"path": "Bots"})
    assert len([e for e in read_journal(tmp_path / "journal") if e.get("original")]) == 1


def test_refusals_and_bad_arguments_are_journaled_answers(root, tmp_path):
    ws = workspace(root, tmp_path)
    with pytest.raises(ToolError, match="outside"):
        ws.call("read_file", {"path": "Bots/../x"})
    with pytest.raises(ToolError, match="invalid arguments"):
        ws.call("read_file", {"file": "Bots/README.md"})
    with pytest.raises(ToolError, match="unknown tool"):
        ws.call("delete_file", {"path": "Bots/README.md"})
    journal = read_journal(tmp_path / "journal")
    assert journal[0]["refused"] == "outside the project folders" and len(journal) == 3


def test_a_journal_ends_with_a_complete_line_even_after_a_crash_mid_line(tmp_path):
    (tmp_path / "journal").mkdir()
    (tmp_path / "journal" / "journal.jsonl").write_text('{"n": 1, "tool": "list_dir", "path": "Bots"}\n{"n": 2, "to',
                                                        encoding="utf-8")
    assert read_journal(tmp_path / "journal") == [{"n": 1, "tool": "list_dir", "path": "Bots"}]


def test_a_file_that_development_tools_run_is_not_written(root, tmp_path):
    with pytest.raises(ToolError, match="development tools run this file"):
        workspace(root, tmp_path).call("write_file", {"path": "Bots/.claude/settings.json", "content": "{}"})
    assert not (root / ".claude").exists()


def test_search_refuses_a_long_regular_expression_and_stops_at_its_deadline(root, tmp_path, monkeypatch):
    from ooat_core.workspace import tools
    ws = workspace(root, tmp_path)
    with pytest.raises(ToolError, match="at most 200 characters"):
        ws.call("search", {"query": "a" * 201, "regex": True})
    monkeypatch.setattr(tools, "SEARCH_SECONDS", 0)
    assert ws.call("search", {"query": "def main"}).endswith("(search stopped after 0 s; narrow the search)")


def test_a_server_after_a_crash_mid_line_ends_the_cut_line_and_the_next_one_still_reads(root, tmp_path):
    (tmp_path / "journal").mkdir()
    (tmp_path / "journal" / "journal.jsonl").write_text('{"n": 1, "tool": "list_dir", "path": "Bots"}\n{"n": 2, "to',
                                                        encoding="utf-8")
    workspace(root, tmp_path).call("list_dir", {"path": "Bots"})
    third = workspace(root, tmp_path)
    assert [e["n"] for e in read_journal(tmp_path / "journal")] == [1, 2]
    third.call("list_dir", {"path": "Bots"})
    assert read_journal(tmp_path / "journal")[-1]["n"] == 3


def test_a_tool_answer_that_is_not_a_refusal_is_journaled_too(root, tmp_path):
    ws = workspace(root, tmp_path)
    with pytest.raises(ToolError, match="no such file"):
        ws.call("read_file", {"path": "Bots/missing.txt"})
    (entry,) = read_journal(tmp_path / "journal")
    assert entry["n"] == 1 and entry["path"] == "Bots/missing.txt" and "no such file" in entry["error"]
    with pytest.raises(ToolError) as info:
        workspace(root, tmp_path, operations=1).call("list_dir", {"path": "Bots"})
    assert str(info.value) == STOP


def test_search_skips_a_file_it_cannot_read(root, tmp_path, monkeypatch):
    from pathlib import Path
    real_read = Path.read_bytes

    def locked(self):
        if self.name == "README.md":
            raise PermissionError(13, "locked by another process")
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", locked)
    assert workspace(root, tmp_path).call("search", {"query": "def main"}) == "Bots/src/bot.py:3: def main():"


def test_a_failed_write_does_not_count_against_the_limit_after_a_restart(root, tmp_path):
    journal = tmp_path / "journal"
    journal.mkdir()
    (journal / "journal.jsonl").write_bytes(
        b'{"n": 1, "tool": "write_file", "path": "Bots/a.txt", "real": "x", "before": null, "after": "sha256:'
        + b"0" * 64 + b'", "bytes": 100, "added": 1, "removed": 0}\n'
        b'{"n": 1, "tool": "write_file", "path": "Bots/a.txt", "failed": true}\n')
    ws = workspace(root, tmp_path, write_bytes=150)
    assert ws.call("write_file", {"path": "Bots/b.txt", "content": "x" * 100}) == "wrote Bots/b.txt"

"""The workspace path guard (design 07 §5): nothing outside the granted folders, nothing protected."""

import os
import subprocess
import sys

import pytest

from ooat_core.config import parse_config
from ooat_core.workspace import Refused, WorkspaceGrant, WorkspaceUnavailable, grant_for
from ooat_core.workspace.guard import Guard


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "Bots"
    (root / "src").mkdir(parents=True)
    (root / "src" / "bot.py").write_text("print('hi')\n", encoding="utf-8")
    (root / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / "logs").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("no\n", encoding="utf-8")
    return root, outside


def guard(root, deny=(), hidden=(), write=True):
    return Guard(WorkspaceGrant(project="bots", folders=(("Bots", os.path.realpath(root)),), write=write,
                                deny=tuple(deny), hidden=tuple(hidden), max_operations=300,
                                max_write_bytes=5 * 1024 * 1024, journal_dir=""))


def refused(g, path):
    with pytest.raises(Refused) as info:
        g.resolve(path)
    return info.value.reason


def test_a_path_inside_resolves_to_its_shown_and_real_path(project):
    root, _ = project
    shown, real = guard(root).resolve("Bots\\src/./bot.py")
    assert shown == "Bots/src/bot.py" and real == root.resolve() / "src" / "bot.py"
    assert guard(root).resolve("bots/src")[0] == "Bots/src"  # the folder name is matched case-insensitively
    assert guard(root).resolve("Bots")[0] == "Bots"


@pytest.mark.parametrize("path, reason", [
    ("", "no path"), ("/etc/passwd", "absolute"), ("C:/Windows/win.ini", "absolute"), ("c:x", "absolute"),
    ("\\\\server\\share\\x", "absolute"), ("Bots/../outside/secret.txt", "outside"), ("Other/x", "unknown folder"),
    ("Bots/a.txt:hidden", "alternate data stream"), ("Bots/a.txt::$DATA", "alternate data stream"),
    ("Bots/NUL", "device"), ("Bots/con.txt", "device"), ("Bots/src/COM1", "device"),
    ("Bots/.env.", "dot or a space"), ("Bots/.env ", "dot or a space"),
])
def test_lexically_unsafe_paths_are_refused_before_the_disk_is_touched(project, path, reason):
    assert reason in refused(guard(project[0]), path)


@pytest.mark.parametrize("path", ["Bots/.env", "Bots/.ENV", "Bots/config/.env.production", "Bots/certs/site.PEM",
                                  "Bots/k/server.key", "Bots/a.pfx", "Bots/a.p12", "Bots/vault.kdbx",
                                  "Bots/home/id_rsa", "Bots/home/Id_Ed25519.pub", "Bots/id_ecdsa",
                                  "Bots/.git/config", "Bots/src/.GIT/HEAD", "Bots/.git"])
def test_protected_files_are_never_visible(project, path):
    assert refused(guard(project[0]), path) == "protected file"


def test_the_projects_deny_patterns_apply_case_insensitively_to_files_and_folders(project):
    g = guard(project[0], deny=["src/projects.json*", "logs/**", "**/*.sqlite", "private"])
    for path in ("Bots/src/projects.json", "Bots/src/Projects.JSON.AG-VM-02", "Bots/logs/today.log",
                 "Bots/data/x.sqlite", "Bots/private", "Bots/private/notes.md"):
        assert refused(g, path) == "denied by the project's settings"
    assert g.resolve("Bots/src/bot.py")[0] == "Bots/src/bot.py"


def test_ooats_own_files_are_hidden_even_inside_a_project(project):
    root, _ = project
    (root / "ooat.toml").write_text("", encoding="utf-8")
    g = guard(root, hidden=[os.path.realpath(root / "ooat.toml"), os.path.realpath(root / "data")])
    assert refused(g, "Bots/ooat.toml") == "OOAT's own data"
    assert refused(g, "Bots/data/ooat-ledger.sqlite") == "OOAT's own data"


def test_a_symlink_out_of_the_folder_is_refused(project):
    root, outside = project
    try:
        os.symlink(outside / "secret.txt", root / "src" / "link.txt")
        os.symlink(outside, root / "src" / "linkdir", target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks needs a privilege on this machine")
    assert refused(guard(root), "Bots/src/link.txt") == "outside the project folders"
    assert refused(guard(root), "Bots/src/linkdir/secret.txt") == "outside the project folders"


def test_a_symlink_to_a_protected_file_inside_is_refused(project):
    root, _ = project
    try:
        os.symlink(root / ".env", root / "src" / "settings.txt")
    except OSError:
        pytest.skip("creating symlinks needs a privilege on this machine")
    assert refused(guard(root), "Bots/src/settings.txt") == "protected file"


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
def test_a_junction_out_of_the_folder_is_refused(project):
    import _winapi
    root, outside = project
    _winapi.CreateJunction(str(outside), str(root / "src" / "junction"))
    assert refused(guard(root), "Bots/src/junction/secret.txt") == "outside the project folders"


@pytest.mark.skipif(sys.platform != "win32", reason="8.3 short names are a Windows feature")
def test_a_short_name_resolves_to_the_protected_long_name(project):
    import ctypes
    root, _ = project
    target = root / ".env.local"
    target.write_text("TOKEN=y\n", encoding="utf-8")
    buffer = ctypes.create_unicode_buffer(260)
    ctypes.windll.kernel32.GetShortPathNameW(str(target), buffer, 260)
    short = os.path.basename(buffer.value)
    if short.lower() == ".env.local":
        pytest.skip("8.3 names are off on this volume")
    assert refused(guard(root), f"Bots/{short}") == "protected file"


def test_the_grant_round_trips_through_json(project):
    g = guard(project[0]).grant
    assert WorkspaceGrant.from_json(g.to_json()) == g


def test_grant_for_resolves_folders_and_hides_ooats_own_data(tmp_path, ooat_home, project):
    root, _ = project
    config = parse_config({"ledger": {"url": f"sqlite:///{(tmp_path / 'data' / 'ooat-ledger.sqlite').as_posix()}"},
                           "projects": {"bots": {"folders": [str(root)], "write": True, "deny": ["logs/**"],
                                                 "max_write_mb": 2}}})
    grant = grant_for(config, tmp_path / "ooat.toml", "bots", tmp_path / "journal")
    assert grant.folders == (("Bots", os.path.realpath(root)),) and grant.write is True
    assert grant.deny == ("logs/**",) and grant.max_write_bytes == 2 * 1024 * 1024
    for hidden in (tmp_path / "ooat.toml", tmp_path / "data" / "ooat-ledger.sqlite", tmp_path / "data" / "ooat-blobs",
                   ooat_home, tmp_path / "journal"):
        assert os.path.realpath(hidden) in grant.hidden
    assert grant.journal_dir == os.path.realpath(tmp_path / "journal")


def test_grant_for_refuses_a_missing_folder_and_a_journal_inside_a_project(tmp_path, project):
    root, _ = project
    config = parse_config({"projects": {"bots": {"folders": [str(root)]},
                                        "gone": {"folders": [str(tmp_path / "gone")]}}})
    with pytest.raises(WorkspaceUnavailable, match="gone"):
        grant_for(config, tmp_path / "ooat.toml", "gone", tmp_path / "journal")
    with pytest.raises(WorkspaceUnavailable, match="journal"):
        grant_for(config, tmp_path / "ooat.toml", "bots", root / "journal")


@pytest.mark.parametrize("path", ["Bots/.npmrc", "Bots/.pypirc", "Bots/.netrc", "Bots/.git-credentials",
                                  "Bots/site.PublishSettings", "Bots/.ssh/config", "Bots/.aws/credentials",
                                  "Bots/.azure/x.json", "Bots/.gnupg/pubring.kbx"])
def test_credential_files_and_folders_are_protected_too(project, path):
    assert refused(guard(project[0]), path) == "protected file"


@pytest.mark.parametrize("path", ["Bots/CLAUDE.md", "Bots/src/agents.md", "Bots/GEMINI.md", "Bots/.mcp.json",
                                  "Bots/.claude/settings.json", "Bots/.vscode/tasks.json",
                                  "Bots/.github/workflows/ci.yml", "Bots/.idea/workspace.xml"])
def test_files_that_development_tools_run_are_readable_but_never_writable(project, path):
    g = guard(project[0])
    assert g.resolve(path)[0] == path
    with pytest.raises(Refused) as info:
        g.resolve(path, writing=True)
    assert info.value.reason == "read only: development tools run this file"
    assert g.resolve("Bots/src/bot.py", writing=True)[0] == "Bots/src/bot.py"


def test_grant_for_hides_the_ledgers_sqlite_side_files(tmp_path, ooat_home, project):
    ledger = tmp_path / "data" / "ooat-ledger.sqlite"
    config = parse_config({"ledger": {"url": f"sqlite:///{ledger.as_posix()}"},
                           "projects": {"bots": {"folders": [str(project[0])]}}})
    grant = grant_for(config, tmp_path / "ooat.toml", "bots", tmp_path / "journal")
    for suffix in ("-wal", "-shm", "-journal"):
        assert os.path.realpath(f"{ledger}{suffix}") in grant.hidden

"""The workspace grant: what one model call may do on a project's folders (design 07 §4, ADR 0017)."""

import dataclasses
import json
import os
from dataclasses import dataclass
from pathlib import Path

from ..config import folder_name

# Never visible, whatever a project's deny says (design 07 §3): matched case-insensitively on every path segment.
PROTECTED_NAMES = (".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12", "*.kdbx", "id_rsa*", "id_ed25519*",
                   "id_ecdsa*", ".npmrc", ".pypirc", ".netrc", ".git-credentials", "*.publishsettings")
PROTECTED_FOLDERS = (".git", ".ssh", ".aws", ".azure", ".gnupg")
# Readable but never writable: files a development tool runs or obeys the next time the operator opens the folder
# (hooks, MCP servers, tasks, workflows, agent instructions), so a written one would be a command (ADR 0017 point 7).
READ_ONLY_NAMES = ("claude.md", "agents.md", "gemini.md", ".mcp.json")
READ_ONLY_FOLDERS = (".claude", ".vscode", ".github", ".idea")


class WorkspaceUnavailable(ValueError):
    """A project's folder is missing, or the grant would let the agent reach OOAT's own journal."""


@dataclass(frozen=True)
class WorkspaceGrant:
    project: str
    folders: tuple[tuple[str, str], ...]  # (name shown to the agent, real absolute path)
    write: bool
    deny: tuple[str, ...]  # the project's patterns; the never-visible lists always apply too
    hidden: tuple[str, ...]  # real paths of OOAT's own files and folders
    max_operations: int
    max_write_bytes: int
    journal_dir: str  # the runtime's folder for this task: the journal, the originals, the grant file

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self))

    @classmethod
    def from_json(cls, text: str) -> "WorkspaceGrant":
        data = json.loads(text)
        return cls(**{**data, "folders": tuple(tuple(f) for f in data["folders"]), "deny": tuple(data["deny"]),
                      "hidden": tuple(data["hidden"])})


def _ledger_paths(config) -> list[str]:
    location = config.ledger_url.removeprefix("sqlite:///")
    if location == config.ledger_url or location == ":memory:":
        return [config.blobs_dir] if config.blobs_dir else []
    sidecars = [location + suffix for suffix in ("-wal", "-shm", "-journal")]  # SQLite's own files beside it
    return [location, *sidecars, config.blobs_dir or str(Path(location).parent / "ooat-blobs")]


def grant_for(config, config_path, project: str, journal_dir) -> WorkspaceGrant:
    """The grant of one call on `project` (a key of config.projects; the caller checks it exists)."""
    from ..setup import data_folder  # setup imports the ledger; the MCP server never needs it

    settings = config.projects[project]
    folders = []
    for written in settings.folders:
        if not os.path.isdir(written):
            raise WorkspaceUnavailable(f"the folder {written} of project {project} is not available")
        folders.append((folder_name(written), os.path.realpath(written)))
    journal = os.path.realpath(journal_dir)
    for _, root in folders:
        try:
            inside = os.path.commonpath([os.path.normcase(journal), os.path.normcase(root)]) == os.path.normcase(root)
        except ValueError:
            inside = False
        if inside:
            raise WorkspaceUnavailable(f"the journal folder {journal} is inside a folder of project {project}")
    hidden = [os.path.realpath(p) for p in (config_path, data_folder(), *_ledger_paths(config))] + [journal]
    return WorkspaceGrant(project=project, folders=tuple(folders), write=settings.write, deny=settings.deny,
                          hidden=tuple(dict.fromkeys(hidden)), max_operations=settings.max_operations,
                          max_write_bytes=int(settings.max_write_mb * 1024 * 1024), journal_dir=journal)

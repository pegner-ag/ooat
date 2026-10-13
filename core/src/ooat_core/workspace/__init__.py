"""Project workspace (design 07, ADR 0017): OOAT's own file tools, confined to a project's folders, for one model
call. The grant says what the call may do, the guard checks every path, the tools journal every operation, and the
MCP server (`python -m ooat_core.workspace <grant.json>`) serves them to a connector's CLI."""

import json
import sys
from pathlib import Path

from .grant import (PROTECTED_FOLDERS, PROTECTED_NAMES, READ_ONLY_FOLDERS, READ_ONLY_NAMES, WorkspaceGrant,
                    WorkspaceUnavailable, grant_for)
from .guard import Refused

SERVER_NAME = "ooat_workspace"  # Claude Code calls the tools mcp__ooat_workspace__<tool>

__all__ = ["PROTECTED_FOLDERS", "PROTECTED_NAMES", "READ_ONLY_FOLDERS", "READ_ONLY_NAMES", "Refused", "SERVER_NAME",
           "WorkspaceGrant", "WorkspaceUnavailable", "grant_for", "mcp_config"]


def mcp_config(grant: WorkspaceGrant) -> str:
    """The MCP config a CLI connector gives its CLI: one stdio server, OOAT's. The grant goes in a file of the
    journal folder, never in argv."""
    settings = Path(grant.journal_dir) / "grant.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(grant.to_json(), encoding="utf-8")
    return json.dumps({"mcpServers": {SERVER_NAME: {
        "type": "stdio", "command": sys.executable, "args": ["-m", "ooat_core.workspace", str(settings)]}}})

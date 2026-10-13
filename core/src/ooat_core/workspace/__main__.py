"""`python -m ooat_core.workspace <grant.json>`: the MCP server a connector's CLI starts for one call."""

import sys
from pathlib import Path

from .grant import WorkspaceGrant
from .server import serve
from .tools import Workspace


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m ooat_core.workspace <grant.json>", file=sys.stderr)
        return 2
    grant = WorkspaceGrant.from_json(Path(argv[0]).read_text(encoding="utf-8"))
    # A pipe's default is the ANSI code page and \r\n on Windows; MCP is UTF-8 with \n.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    serve(Workspace(grant), sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())

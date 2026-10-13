"""The path guard of the workspace tools (design 07 §5). A path is checked as written before the disk is touched,
then resolved to its real path (symlinks, junctions and 8.3 short names followed) and checked again."""

import fnmatch
import os
import re
from pathlib import Path

from .grant import PROTECTED_FOLDERS, PROTECTED_NAMES, READ_ONLY_FOLDERS, READ_ONLY_NAMES, WorkspaceGrant

_DEVICE = re.compile(r"^(con|prn|aux|nul|conin\$|conout\$|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)
_DRIVE = re.compile(r"^[A-Za-z]:")


class Refused(Exception):
    """The answer to a path the agent may not use; the agent reads it and carries on."""

    def __init__(self, reason: str, path: str):
        super().__init__(f"refused: {reason}: {path}")
        self.reason = reason
        self.path = path


def pattern(glob: str) -> re.Pattern:
    """A deny or find pattern: `*` and `?` within a path segment, `**` across segments; case-insensitive."""
    glob, out, i = glob.replace("\\", "/").strip("/"), [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(out) + r"\Z", re.IGNORECASE | re.DOTALL)


def within(path: str, root: str) -> bool:
    path, root = os.path.normcase(path), os.path.normcase(root)
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # another drive
        return False


class Guard:
    def __init__(self, grant: WorkspaceGrant):
        self.grant = grant
        self._roots = {name.lower(): (name, root) for name, root in grant.folders}
        self._deny = [pattern(p) for p in grant.deny]

    def resolve(self, path, writing: bool = False) -> tuple[str, Path]:
        """(the path as the agent sees it, its real path), or Refused; `writing` also refuses read-only files."""
        if not isinstance(path, str) or not path.strip():
            raise Refused("no path given", str(path))
        text = path.replace("\\", "/")
        if text.startswith("/") or _DRIVE.match(text):
            raise Refused("absolute paths are not allowed; start with a folder's name", path)
        parts = [p for p in text.split("/") if p not in ("", ".")]
        if not parts:
            raise Refused("no path given", path)
        for part in parts:
            if part == "..":
                raise Refused("outside the project folders", path)
            if ":" in part:
                raise Refused("alternate data streams are not allowed", path)
            if _DEVICE.match(part):
                raise Refused("device names are not allowed", path)
            if part != part.rstrip(". "):
                raise Refused("a name may not end with a dot or a space", path)
        folder = self._roots.get(parts[0].lower())
        if folder is None:
            names = ", ".join(name for name, _ in self.grant.folders)
            raise Refused(f"unknown folder; the folders are {names}", path)
        name, root = folder
        real = os.path.realpath(os.path.join(root, *parts[1:]))
        if not within(real, root):
            raise Refused("outside the project folders", path)
        relative = os.path.relpath(real, root).replace(os.sep, "/")
        relative = "" if relative == "." else relative
        self._check(relative, real, path, writing)
        return (f"{name}/{relative}" if relative else name), Path(real)

    def _check(self, relative: str, real: str, path: str, writing: bool) -> None:
        segments = [s.lower() for s in relative.split("/") if s]
        if any(s in PROTECTED_FOLDERS or any(fnmatch.fnmatchcase(s, p) for p in PROTECTED_NAMES) for s in segments):
            raise Refused("protected file", path)
        prefixes = ["/".join(segments[:i]) for i in range(1, len(segments) + 1)]
        if any(deny.match(prefix) for deny in self._deny for prefix in prefixes):
            raise Refused("denied by the project's settings", path)
        if any(within(real, hidden) for hidden in self.grant.hidden):
            raise Refused("OOAT's own data", path)
        if writing and any(s in READ_ONLY_FOLDERS or s in READ_ONLY_NAMES for s in segments):
            raise Refused("read only: development tools run this file", path)

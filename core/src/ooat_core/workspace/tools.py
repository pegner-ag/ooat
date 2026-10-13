"""The six workspace tools (design 07 §5) and their journal: one JSON line per operation in the grant's journal
folder, read by the runtime after the call (§7). The tools never write the ledger and never touch a path the guard
refused. A write is journaled before the file is replaced, so a crash over-reports a change, never hides one."""

import contextlib
import difflib
import hashlib
import inspect
import json
import os
import re
import tempfile
import time
from pathlib import Path

from .grant import WorkspaceGrant
from .guard import Guard, Refused
from .guard import pattern as glob_pattern  # `pattern` is also an argument name of two tools

JOURNAL = "journal.jsonl"
STOP = "limit reached: stop now and summarise what you did and what remains"
MAX_READ_BYTES = 256 * 1024
MAX_FILE_BYTES = 1024 * 1024  # largest file written
MAX_TEXT_BYTES = 10 * 1024 * 1024  # largest file read
MAX_SEARCH_BYTES = 2 * 1024 * 1024  # larger files are skipped by search
MAX_FIND = 500
MAX_MATCHES = 200
MAX_LINE = 300
MAX_REGEX = 200  # a regular expression's length: Python's re has no timeout
SEARCH_SECONDS = 20  # a search returns what it found so far after this long
WRITE_TOOLS = ("edit_file", "write_file")


class ToolError(Exception):
    """An answer the agent reads: refused, not found, an ambiguous edit, the limit."""


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def is_text(data: bytes) -> bool:
    if b"\0" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def read_journal(journal_dir) -> list[dict]:
    """The journal's complete lines; a last line cut off by a crash is left out."""
    path = Path(journal_dir) / JOURNAL
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").split("\n")
    return [json.loads(line) for line in lines[:-1] if line.strip()]


def _line_counts(before: bytes | None, after: bytes) -> tuple[int, int]:
    old = before.decode("utf-8").splitlines() if before is not None else []
    new = after.decode("utf-8").splitlines()
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed


def _newlines(text: str, crlf: bool) -> str:
    text = text.replace("\r\n", "\n")
    return text.replace("\n", "\r\n") if crlf else text


def _atomic_write(path: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".ooat-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


class Workspace:
    def __init__(self, grant: WorkspaceGrant):
        self.grant = grant
        self.guard = Guard(grant)
        self._dir = Path(grant.journal_dir)
        (self._dir / "originals").mkdir(parents=True, exist_ok=True)
        journal = self._dir / JOURNAL
        data = journal.read_bytes() if journal.exists() else b""
        if data and not data.endswith(b"\n"):  # a line cut off by a crash: drop it, or the next line would join it
            journal.write_bytes(data[:data.rfind(b"\n") + 1])
        earlier = read_journal(self._dir)
        self._operations = max((e["n"] for e in earlier), default=0)
        failed = {(e["n"], e["tool"]) for e in earlier if e.get("failed")}
        self._written = sum(e.get("bytes", 0) for e in earlier if (e["n"], e["tool"]) not in failed)
        self._originals = {os.path.normcase(e["real"]): e["original"] for e in earlier if e.get("original")}
        self._stopped = False

    # The dispatcher ---------------------------------------------------------------------------------------------

    def call(self, tool: str, arguments: dict) -> str:
        """Run one tool. Every call counts as an operation; a ToolError is the agent's answer."""
        arguments = arguments if isinstance(arguments, dict) else {}
        path = arguments.get("path", arguments.get("pattern"))
        if self._stopped or self._operations >= self.grant.max_operations:
            if not self._stopped:
                self._stop("operations", tool, path, self._operations + 1)
            raise ToolError(STOP)
        self._operations += 1
        handler = getattr(self, f"_{tool}", None) if tool in TOOL_NAMES else None
        if handler is None:
            self._log(tool, path, error="unknown tool")
            raise ToolError(f"unknown tool: {tool}")
        try:
            inspect.signature(handler).bind(**arguments)
        except TypeError:
            self._log(tool, path, error="invalid arguments")
            raise ToolError(f"invalid arguments for {tool}") from None
        try:
            return handler(**arguments)
        except Refused as refusal:
            self._log(tool, refusal.path, refused=refusal.reason)
            raise ToolError(str(refusal)) from None
        except ToolError as answer:  # every operation leaves a line, so a second server counts it (design 07 §5)
            if str(answer) != STOP:  # the limit line is already written
                self._log(tool, path, error=str(answer)[:200])
            raise
        except OSError as error:
            self._log(tool, path, error=type(error).__name__)
            raise ToolError(f"could not access {path}: {error.strerror or type(error).__name__}") from None

    # Reading ----------------------------------------------------------------------------------------------------

    def _list_dir(self, path: str) -> str:
        shown, real = self.guard.resolve(path)
        if not real.is_dir():
            raise ToolError(f"not a folder: {shown}")
        lines = []
        for entry in sorted(real.iterdir(), key=lambda e: e.name.lower()):
            try:
                self.guard.resolve(f"{shown}/{entry.name}")
            except Refused:
                continue
            lines.append(f"{entry.name}/" if entry.is_dir() else f"{entry.name}  {entry.stat().st_size} bytes")
        self._log("list_dir", shown)
        return "\n".join(lines) or "(empty folder)"

    def _walk(self, regex=None):
        """(shown, real) of every visible file, in every folder; links are never followed."""
        for name, root in self.grant.folders:
            for current, folders, files in os.walk(root, followlinks=False):
                relative = os.path.relpath(current, root).replace(os.sep, "/")
                base = name if relative == "." else f"{name}/{relative}"
                kept = []
                for folder in sorted(folders, key=str.lower):
                    full = os.path.join(current, folder)
                    if os.path.islink(full) or os.path.isjunction(full):
                        continue
                    try:
                        self.guard.resolve(f"{base}/{folder}")
                    except Refused:
                        continue
                    kept.append(folder)
                folders[:] = kept
                for file in sorted(files, key=str.lower):
                    shown = f"{base}/{file}"
                    try:
                        _, real = self.guard.resolve(shown)
                    except Refused:
                        continue
                    if regex is None or regex.match(shown):
                        yield shown, real

    def _find_files(self, pattern: str) -> str:
        if not isinstance(pattern, str) or not pattern.strip():
            raise ToolError("give a pattern such as Folder/**/*.py")
        found = []
        for shown, _ in self._walk(glob_pattern(pattern)):
            if len(found) == MAX_FIND:
                found.append(f"(more than {MAX_FIND} files; narrow the pattern)")
                break
            found.append(shown)
        self._log("find_files", pattern)
        return "\n".join(found) or "(no files)"

    def _search(self, query: str, regex: bool = False, pattern: str | None = None) -> str:
        if not isinstance(query, str) or not query:
            raise ToolError("give a text to search for")
        if regex and len(query) > MAX_REGEX:
            raise ToolError(f"a regular expression has at most {MAX_REGEX} characters")
        try:
            matcher = re.compile(query if regex else re.escape(query))
        except re.error as error:
            raise ToolError(f"invalid regular expression: {error}") from None
        files = glob_pattern(pattern) if pattern else None
        matches, start = [], time.monotonic()
        for shown, real in self._walk(files):
            if time.monotonic() - start >= SEARCH_SECONDS:
                matches.append(f"(search stopped after {SEARCH_SECONDS} s; narrow the search)")
                break
            try:
                if real.stat().st_size > MAX_SEARCH_BYTES:
                    continue
                data = real.read_bytes()
            except OSError:  # locked by a running service, or gone during the walk
                continue
            if not is_text(data):
                continue
            for number, line in enumerate(data.decode("utf-8").splitlines(), 1):
                if matcher.search(line):
                    if len(matches) == MAX_MATCHES:
                        matches.append(f"(more than {MAX_MATCHES} matches; narrow the search)")
                        self._log("search", pattern or "**")
                        return "\n".join(matches)
                    matches.append(f"{shown}:{number}: {line[:MAX_LINE]}")
        self._log("search", pattern or "**")
        return "\n".join(matches) or "(no matches)"

    def _read_file(self, path: str, offset: int = 1, limit: int = 2000) -> str:
        shown, real = self.guard.resolve(path)
        if not real.is_file():
            raise ToolError(f"no such file: {shown}")
        if type(offset) is not int or type(limit) is not int or offset < 1 or limit < 1:
            raise ToolError("offset and limit are whole numbers from 1")
        if real.stat().st_size > MAX_TEXT_BYTES:
            raise Refused("larger than 10 MB", shown)
        data = real.read_bytes()
        if not is_text(data):
            raise Refused("not a text file", shown)
        lines = data.decode("utf-8").splitlines(keepends=True)
        chunk, size = [], 0
        for line in lines[offset - 1:offset - 1 + limit]:
            encoded = len(line.encode("utf-8"))
            if chunk and size + encoded > MAX_READ_BYTES:
                break
            chunk.append(line if encoded <= MAX_READ_BYTES else line[:MAX_READ_BYTES // 4] + " [line cut]\n")
            size += encoded
        last = offset - 1 + len(chunk)
        more = f"; read on with offset={last + 1}" if last < len(lines) else ""
        self._log("read_file", shown)
        return f"{shown}, lines {offset}-{last} of {len(lines)}{more}\n" + "".join(chunk)

    # Writing ----------------------------------------------------------------------------------------------------

    def _writable(self, path) -> tuple[str, Path]:
        if not self.grant.write:
            raise Refused("this project is read only", str(path))
        return self.guard.resolve(path, writing=True)

    def _edit_file(self, path: str, old: str, new: str) -> str:
        shown, real = self._writable(path)
        if not real.is_file():
            raise ToolError(f"no such file: {shown}; write_file creates files")
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise ToolError("old must be the exact text to replace and new its replacement")
        before = real.read_bytes()
        if len(before) > MAX_TEXT_BYTES or not is_text(before):
            raise Refused("not a text file", shown)
        text = before.decode("utf-8")
        crlf = "\r\n" in text
        old, new = _newlines(old, crlf), _newlines(new, crlf)
        count = text.count(old)
        if count != 1:
            hint = " (the file may have changed; read it again)" if count == 0 else ""
            raise ToolError(f"old occurs {count} times in {shown}; give text that occurs exactly once{hint}")
        self._write("edit_file", shown, real, before, text.replace(old, new, 1).encode("utf-8"))
        return f"edited {shown}"

    def _write_file(self, path: str, content: str) -> str:
        shown, real = self._writable(path)
        if not isinstance(content, str):
            raise ToolError("content must be the file's text")
        before = None
        if real.exists():
            if not real.is_file():
                raise ToolError(f"{shown} is a folder")
            before = real.read_bytes()
            if len(before) > MAX_TEXT_BYTES or not is_text(before):
                raise Refused("not a text file", shown)
            content = _newlines(content, "\r\n" in before.decode("utf-8"))
        self._write("write_file", shown, real, before, content.encode("utf-8"))
        return f"wrote {shown}"

    def _write(self, tool: str, shown: str, real: Path, before: bytes | None, after: bytes) -> None:
        if len(after) > MAX_FILE_BYTES:
            raise ToolError(f"{shown} would be larger than 1 MB")
        if self._written + len(after) > self.grant.max_write_bytes:
            self._stop("write_bytes", tool, shown, self._operations)
            raise ToolError(STOP)
        added, removed = _line_counts(before, after)
        entry = {"n": self._operations, "tool": tool, "path": shown, "real": str(real),
                 "before": sha256(before) if before is not None else None, "after": sha256(after),
                 "bytes": len(after), "added": added, "removed": removed}
        key = os.path.normcase(str(real))
        if before is not None and key not in self._originals:
            name = f"originals/{len(self._originals) + 1:04d}"
            (self._dir / name).write_bytes(before)
            self._originals[key] = entry["original"] = name
        self._append(entry)
        self._written += len(after)
        try:
            real.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(real, after)
        except OSError:
            self._written -= len(after)
            self._append({"n": self._operations, "tool": tool, "path": shown, "failed": True})
            raise

    # The journal ------------------------------------------------------------------------------------------------

    def _stop(self, kind: str, tool: str, path, operation: int) -> None:
        self._stopped = True
        self._append({"n": operation, "tool": tool, "path": path, "limit": kind})

    def _log(self, tool: str, path, **extra) -> None:
        self._append({"n": self._operations, "tool": tool, "path": path, **extra})

    def _append(self, entry: dict) -> None:
        with open(self._dir / JOURNAL, "a", encoding="utf-8", newline="\n") as journal:
            journal.write(json.dumps(entry, ensure_ascii=False) + "\n")


TOOL_NAMES = ("list_dir", "find_files", "search", "read_file", "edit_file", "write_file")

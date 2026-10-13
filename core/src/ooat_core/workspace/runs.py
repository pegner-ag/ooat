"""The runtime's side of a project workspace (design 07 §5–§8): the grant of each call, the per-project write lock,
the journal turned into WORKSPACE_USED with the originals and a diff as artifacts, OOAT's change list, and revert.
Only ooat-core writes the ledger; the MCP server writes only the journal. Imported by the runtime, never by the
MCP server's package."""

import dataclasses
import difflib
import os
import re
import time
from pathlib import Path

from ..ledger import new_event
from ..pii import raised_class
from ..runner_lock import RunnerLock
from .grant import WorkspaceGrant, WorkspaceUnavailable, grant_for
from .tools import read_journal, sha256

ACTOR = {"kind": "system", "id": "ooat-runtime"}
MAX_PATH = 300  # a path as the agent wrote it, cut for the ledger
LOCK_WAIT_S = 60  # a call waits this long for a revert to finish
WRITES = ("edit_file", "write_file")
# A long run of token characters with digits and mixed case, or a long hex run: written as [hidden], because the
# ledger is append-only and a path the agent wrote may carry a pasted secret (PR #45 review).
_RUN = re.compile(r"[A-Za-z0-9+=_-]{32,}")  # within one path segment
_HEX = frozenset("0123456789abcdefABCDEF")


class WorkspaceBusy(ValueError):
    """Another holder (a revert, or a call) is writing the project now."""


class JournalLost(ValueError):
    """The journal cannot be read: nothing can be assumed about what the agent did on disk."""


class AlreadyReverted(ValueError):
    """The task's changes were reverted already."""


WORKSPACE_PROBLEMS = (WorkspaceUnavailable, WorkspaceBusy, JournalLost)


def _secretish(run: str) -> bool:
    digits = any(c.isdigit() for c in run)
    mixed = any(c.isupper() for c in run) and any(c.islower() for c in run)
    return digits and (mixed or set(run) <= _HEX)


def _cut(path) -> str | None:
    if not isinstance(path, str):
        return None
    return _RUN.sub(lambda match: "[hidden]" if _secretish(match.group()) else match.group(), path)[:MAX_PATH]


def _classed(data_class: str, content: bytes) -> str:
    """File contents are scanned like any text OOAT stores: personal data raises the class (ADR 0011)."""
    return raised_class(data_class, content.decode("utf-8", "replace"))


class ProjectLock:
    """An OS file lock per project (the runner lock's pattern), so a revert never writes during a call."""

    def __init__(self, path: Path):
        self._lock = RunnerLock(path)

    def acquire(self, wait_s: float = 0.0) -> bool:
        deadline = time.monotonic() + wait_s
        while not self._lock.acquire():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)
        return True

    def release(self) -> None:
        self._lock.release()


class Workspaces:
    def __init__(self, config, config_path, root):
        self.config, self.config_path, self.root = config, config_path, Path(root)

    def project(self, slug: str | None):
        return self.config.projects.get(slug) if slug else None

    def grant(self, task: str, project: str, role: str = "worker", factor: int = 1) -> WorkspaceGrant:
        """The grant of one call: only the worker writes; a raised limit multiplies both limits for this task."""
        if project not in self.config.projects:
            raise WorkspaceUnavailable(f"project {project} is not in ooat.toml any more")
        grant = grant_for(self.config, self.config_path, project, self.root / task / role)
        return dataclasses.replace(grant, write=grant.write and role == "worker",
                                   max_operations=grant.max_operations * factor,
                                   max_write_bytes=grant.max_write_bytes * factor)

    def timeout_s(self, project: str) -> float:
        settings = self.config.projects.get(project)
        return settings.timeout_min * 60 if settings is not None else 600.0

    def lock(self, project: str) -> ProjectLock:
        self.root.mkdir(parents=True, exist_ok=True)
        return ProjectLock(self.root / f"{project}.lock")

    # The journal in the ledger ----------------------------------------------------------------------------------

    def record(self, ledger, artifacts, *, task: str, contract: str | None, role: str, grant: WorkspaceGrant,
               data_class: str) -> dict | None:
        """Append WORKSPACE_USED for the journal lines since the last event of this role; None when there are
        none. Each original is stored once, as the task's artifact; the diff covers the task so far."""
        try:
            lines = read_journal(grant.journal_dir)
        except (ValueError, OSError):  # damaged or unreadable: never guess what the agent did
            raise JournalLost("workspace journal lost") from None
        earlier = [e for e in ledger.events(task=task, types=["WORKSPACE_USED"]) if e["body"]["by"] == role]
        start = earlier[-1]["body"]["journal_lines"] if earlier else 0
        if len(lines) <= start:
            return None
        try:
            failed = {(e["n"], e["tool"]) for e in lines if e.get("failed")}
            read, changed, created, refused, staged, limit = {}, {}, {}, [], [], None
            for entry in lines[start:]:
                path, tool = _cut(entry.get("path")), str(entry.get("tool"))[:40]
                if entry.get("limit"):
                    limit = {"kind": entry["limit"], "operation": entry["n"], "tool": tool, "path": path}
                elif entry.get("refused"):
                    refused.append({"path": path, "tool": tool, "reason": str(entry["refused"])[:200]})
                elif entry.get("failed") or entry.get("error"):
                    continue
                elif tool == "read_file":
                    read[path] = read.get(path, 0) + 1
                elif tool in WRITES and (entry["n"], entry["tool"]) not in failed:
                    if entry["before"] is None or path in created:
                        item = created.setdefault(path, {"path": path, "after": entry["after"], "added": 0})
                        item["after"], item["added"] = entry["after"], item["added"] + entry["added"]
                        continue
                    item = changed.setdefault(path, {"path": path, "before": entry["before"],
                                                     "after": entry["after"], "added": 0, "removed": 0})
                    item["after"] = entry["after"]
                    item["added"], item["removed"] = item["added"] + entry["added"], item["removed"] + entry["removed"]
                    if entry.get("original") and "original" not in item:
                        content = (Path(grant.journal_dir) / entry["original"]).read_bytes()
                        if sha256(content) != entry["before"]:
                            raise JournalLost("workspace journal lost: a saved original does not match")
                        original = artifacts.stage(content, artifact_type="workspace_original",
                                                   data_class=_classed(data_class, content))
                        staged.append(original)
                        item["original"] = original.ref
            operations = max((e["n"] for e in lines if not e.get("limit")), default=0)
            written = sum(e.get("bytes", 0) for e in lines if (e["n"], e["tool"]) not in failed)
        except (KeyError, TypeError, OSError):
            raise JournalLost("workspace journal lost") from None
        body = {"project": grant.project, "by": role, "write": grant.write,
                "read": [{"path": p, "times": n} for p, n in read.items()], "changed": list(changed.values()),
                "created": list(created.values()), "refused": refused, "operations": operations,
                "written_bytes": written, "limit": limit, "journal_lines": len(lines)}
        if changed or created:
            diff = _diff(lines, grant, failed).encode("utf-8")
            if diff:
                artifact = artifacts.stage(diff, artifact_type="workspace_diff", data_class=_classed(data_class, diff))
                staged.append(artifact)
                body["diff"] = artifact.ref
        return ledger.append(new_event("WORKSPACE_USED", task=task, contract=contract, actor=ACTOR,
                                       refs=[a.ref for a in staged], body=body), staged)


def _diff(lines: list[dict], grant: WorkspaceGrant, failed: set) -> str:
    """A unified diff of every file the journal changed, from its saved original (empty when created) to now."""
    first = {}
    for entry in lines:
        if entry.get("tool") in WRITES and "after" in entry and (entry["n"], entry["tool"]) not in failed:
            first.setdefault(os.path.normcase(entry["real"]), entry)
    parts = []
    for entry in first.values():
        shown = _cut(entry["path"])
        try:
            before = b"" if entry["before"] is None else (Path(grant.journal_dir) / entry["original"]).read_bytes()
            now = Path(entry["real"]).read_bytes()
        except (KeyError, OSError):
            parts.append(f"# {shown}: not available for the diff\n")
            continue
        if now != before:
            parts.extend(difflib.unified_diff(before.decode("utf-8", "replace").splitlines(keepends=True),
                                              now.decode("utf-8", "replace").splitlines(keepends=True),
                                              fromfile=f"a/{shown}", tofile=f"b/{shown}"))
    return "".join(parts)


def change_section(events: list[dict]) -> str:
    """OOAT's own list of what the worker changed in the task so far: for the document, the critic and the
    operator, so a claim the agent makes can be compared with what OOAT saw (design 07 §7)."""
    files, refusals = {}, 0
    for event in events:
        if event["type"] != "WORKSPACE_USED" or event["body"]["by"] != "worker":
            continue
        refusals += len(event["body"]["refused"])
        for item in event["body"]["created"]:
            entry = files.setdefault(item["path"], ["created", 0, 0])
            entry[1] += item["added"]
        for item in event["body"]["changed"]:
            entry = files.setdefault(item["path"], ["changed", 0, 0])
            entry[1], entry[2] = entry[1] + item["added"], entry[2] + item["removed"]
    lines = ["## Files changed (recorded by OOAT)", ""]
    lines += [f"- `{path}`: created, +{added}" if kind == "created" else f"- `{path}`: changed, +{added} -{removed}"
              for path, (kind, added, removed) in files.items()] or ["- none"]
    if refusals:
        lines += ["", f"{refusals} operation{' was' if refusals == 1 else 's were'} refused by OOAT's path guard."]
    return "\n".join(lines)

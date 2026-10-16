"""The runtime's side of a project workspace (design 07 §5–§8): the grant of each call, the per-project write lock,
the journal turned into WORKSPACE_USED with the originals and a diff as artifacts, OOAT's change list, and revert.
Only ooat-core writes the ledger; the MCP server writes only the journal. Imported by the runtime, never by the
MCP server's package."""

import contextlib
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
from .guard import Guard, Refused
from .tools import _atomic_write, read_journal, sha256

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

    def answer_grant(self, conversation: str, step: str, project: str, max_operations: int) -> WorkspaceGrant:
        """A direct answer's grant (ADR 0018): read only, at most `max_operations`, its journal under the
        conversation, never a task's."""
        if project not in self.config.projects:
            raise WorkspaceUnavailable(f"project {project} is not in ooat.toml any more")
        grant = grant_for(self.config, self.config_path, project, self.root / conversation / step)
        return dataclasses.replace(grant, write=False, max_operations=max_operations)

    def timeout_s(self, project: str) -> float:
        settings = self.config.projects.get(project)
        return settings.timeout_min * 60 if settings is not None else 600.0

    def lock(self, project: str) -> ProjectLock:
        self.root.mkdir(parents=True, exist_ok=True)
        return ProjectLock(self.root / f"{project}.lock")

    # The journal in the ledger ----------------------------------------------------------------------------------

    def record(self, ledger, artifacts, *, task: str | None, contract: str | None, role: str, grant: WorkspaceGrant,
               data_class: str, conversation: str | None = None) -> dict | None:
        """Append WORKSPACE_USED for the journal lines since the last event of this role; None when there are
        none. Each original is stored once, as the task's artifact; the diff covers the task so far. A direct
        answer (ADR 0018) has no task: its event names the conversation, and its journal is its own."""
        try:
            lines = read_journal(grant.journal_dir)
        except (ValueError, OSError):  # damaged or unreadable: never guess what the agent did
            raise JournalLost("workspace journal lost") from None
        earlier = [] if conversation is not None else [
            e for e in ledger.events(task=task, types=["WORKSPACE_USED"]) if e["body"]["by"] == role]
        start = earlier[-1]["body"]["journal_lines"] if earlier else 0
        if len(lines) <= start:
            return None
        try:
            failed = {(e["n"], e["tool"]) for e in lines if e.get("failed")}
            # An original saved by a write that then failed belongs to the file's first write that worked.
            attached = {i["path"] for e in earlier for i in e["body"]["changed"] if i.get("original")}
            pending = {os.path.normcase(e["real"]): e["original"] for e in reversed(lines)
                       if e.get("original") and (e["n"], e["tool"]) in failed}
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
                    item = changed.get(path)
                    if item is None:
                        item = changed[path] = {"path": path, "before": entry["before"], "after": entry["after"],
                                                "added": 0, "removed": 0}
                    elif entry["before"] != item["after"]:  # someone else wrote the file between two writes
                        item["interrupted"] = True
                    item["after"] = entry["after"]
                    item["added"], item["removed"] = item["added"] + entry["added"], item["removed"] + entry["removed"]
                    name = entry.get("original")
                    if name is None and path not in attached:
                        name = pending.pop(os.path.normcase(entry["real"]), None)
                    if name and "original" not in item:
                        content = (Path(grant.journal_dir) / name).read_bytes()
                        if sha256(content) != entry["before"]:
                            if not entry.get("original"):  # the file changed between the failed write and this one
                                item["interrupted"] = True
                                continue
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
        if conversation is not None:
            body["conversation"] = conversation
        if changed or created:
            diff = _diff(lines, grant, failed).encode("utf-8")
            if diff:
                artifact = artifacts.stage(diff, artifact_type="workspace_diff", data_class=_classed(data_class, diff))
                staged.append(artifact)
                body["diff"] = artifact.ref
        return ledger.append(new_event("WORKSPACE_USED", task=task, contract=contract, actor=ACTOR,
                                       refs=[a.ref for a in staged], body=body), staged)

    # Revert -----------------------------------------------------------------------------------------------------

    def revert(self, ledger, artifacts, task: str, *, operator: str, channel: str | None = None) -> dict:
        """Write back each changed file's original where the file still is as the task left it (design 07 §7).
        A file changed since, or changed by someone else between the task's writes, is skipped (never
        overwritten); a file that cannot be written now is skipped too; created files are never deleted, only
        listed; every path goes through
        the guard of the project's current config (a project now read only can still be reverted by its
        operator). Runs once per task, under the project's lock; if the ledger refuses the event, the files are
        written back to what they were before the revert, so the disk never differs from what the ledger says."""
        used = [e["body"] for e in ledger.events(task=task, types=["WORKSPACE_USED"]) if e["body"]["by"] == "worker"]
        created = list(dict.fromkeys(i["path"] for body in used for i in body["created"]))
        files = {}
        for body in used:
            for item in body["changed"]:
                if item["path"] not in created:
                    entry = files.setdefault(item["path"], {"original": item.get("original"), "after": None,
                                                            "interrupted": False})
                    # Each write must start from what the task's previous write left: else someone else wrote it.
                    broken = entry["after"] is not None and item["before"] != entry["after"]
                    entry["interrupted"] = entry["interrupted"] or broken or bool(item.get("interrupted"))
                    entry["after"] = item["after"]
        if not files and not created:
            raise ValueError(f"task {task} changed no project files")
        project = used[0]["project"]
        lock = self.lock(project)
        if not lock.acquire():
            raise WorkspaceBusy(f"a task is writing project {project} now; revert after it")
        try:
            if ledger.events(task=task, types=["WORKSPACE_REVERTED"]):  # checked under the lock
                raise AlreadyReverted(f"the changes of task {task} were reverted already")
            guard = Guard(self.grant(task, project, role="revert"))
            restored, skipped, undo = [], [], []
            try:
                for path, entry in files.items():
                    try:
                        _, real = guard.resolve(path, writing=True)
                    except Refused as refusal:
                        skipped.append({"path": path, "reason": f"refused: {refusal.reason}"[:200]})
                        continue
                    try:
                        current = real.read_bytes()
                    except OSError:
                        skipped.append({"path": path, "reason": "not readable now"})
                        continue
                    if entry["interrupted"]:
                        skipped.append({"path": path, "reason": "changed by someone else during the task"})
                        continue
                    if sha256(current) != entry["after"]:
                        skipped.append({"path": path, "reason": "changed since the task"})
                        continue
                    if entry["original"] is None:
                        skipped.append({"path": path, "reason": "no saved original"})
                        continue
                    original = artifacts.read(entry["original"])
                    try:
                        _atomic_write(real, original)
                    except OSError:  # e.g. open in another process on Windows: the rest is still reverted
                        skipped.append({"path": path, "reason": "not writable now (open elsewhere?)"})
                        continue
                    undo.append((real, current))
                    restored.append({"path": path, "after": sha256(original)})
                body = {"project": project, "restored": restored, "skipped": skipped, "kept": created}
                if channel is not None:
                    body["channel"] = channel
                return ledger.append(new_event("WORKSPACE_REVERTED", task=task,
                                               actor={"kind": "hil", "id": operator}, body=body))
            except BaseException:
                for real, content in reversed(undo):  # every undo is tried, even when one fails
                    with contextlib.suppress(OSError):
                        _atomic_write(real, content)
                raise
        finally:
            lock.release()


def _diff(lines: list[dict], grant: WorkspaceGrant, failed: set) -> str:
    """A unified diff of every file the journal changed, from its saved original (empty when created) to now."""
    first, saved = {}, {}
    for entry in lines:
        if entry.get("original"):  # also the original of a write that failed
            saved.setdefault(os.path.normcase(entry["real"]), entry["original"])
        if entry.get("tool") in WRITES and "after" in entry and (entry["n"], entry["tool"]) not in failed:
            first.setdefault(os.path.normcase(entry["real"]), entry)
    parts = []
    for entry in first.values():
        shown = _cut(entry["path"])
        try:
            key = os.path.normcase(entry["real"])
            before = b"" if entry["before"] is None else (Path(grant.journal_dir) / saved[key]).read_bytes()
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

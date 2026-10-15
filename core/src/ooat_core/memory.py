"""Project memory and the operator's preferences (design 08 §6, §7; ADR 0018).

An item's text lives in its own file in the memory store beside the ledger, never in the ledger: MEMORY_NOTED,
MEMORY_EDITED and MEMORY_FORGOTTEN carry its id and the SHA-256 of its text, so forgetting deletes the text for real
and the ledger proves only that an item existed and was forgotten. A text that looks like a secret is never stored;
personal data raises the item's class (pii.py). The projection `items()` is recomputed from the events, like
state.py; an item whose file is missing reads as forgotten.
"""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .connector_admin import checked_operator
from .ids import new_id
from .ledger import Ledger, new_event
from .pii import ORDER, higher_class, raised_class

KINDS = ("preference", "fact", "glossary", "summary", "todo")
OPERATOR_SCOPE = "operator"  # the operator's preferences, given to the reception in every project
MAX_PREFERENCES = 20
MAX_TEXT = 2000
EVENTS = ["MEMORY_NOTED", "MEMORY_EDITED", "MEMORY_FORGOTTEN"]
_SCOPE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# Bounded repeats keep every pattern linear on long runs (.claude/lessons.md).
_SECRETS = (
    ("a private key", re.compile(r"-----BEGIN [A-Z ]{0,40}-----|-----BEGIN [A-Z ]{0,40}PRIVATE KEY")),
    ("a password in a connection string", re.compile(r"(?i)(?:^|;)[ \t]{0,3}(?:password|pwd)[ \t]{0,3}=[ \t]{0,3}"
                                                     r"[^;\s]{1,200}")),
    ("a password, key or token with its value", re.compile(
        r"(?i)\b(?:password|passwd|pwd|heslo|passphrase|secret|token|api[ _-]?key|apikey|access[ _-]?key"
        r"|client[ _-]?secret|private[ _-]?key)\b[ \t]{0,3}[:=][ \t]{0,3}\S{4,200}")),
    ("an access token", re.compile(r"(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{16,200}|ghp_[A-Za-z0-9]{20,200}"
                                   r"|github_pat_[A-Za-z0-9_]{20,200}|xox[abprs]-[A-Za-z0-9-]{10,200}"
                                   r"|AKIA[0-9A-Z]{16}|ooat_[A-Za-z0-9_-]{20,200})")),
)
_RUN = re.compile(r"[A-Za-z0-9+/=_-]{32,}")


class SecretRefused(ValueError):
    """The text looks like a secret; it was not stored. The message names the kind, never the text."""


class UnknownMemory(ValueError):
    """No such memory item, or it is forgotten."""


@dataclass(frozen=True)
class MemoryItem:
    id: str
    scope: str
    kind: str
    data_class: str
    source: str
    text: str
    pinned: bool
    done: bool
    noted: str  # when it was noted (UTC)
    conversation: str | None


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def looks_secret(text: str) -> str | None:
    """The kind of secret the text seems to hold, or None."""
    for kind, pattern in _SECRETS:
        if pattern.search(text):
            return kind
    for match in _RUN.finditer(text):
        run = match.group()
        if any(c.isdigit() for c in run) and any(c.isupper() for c in run) and any(c.islower() for c in run):
            return "a long key-like string"
    return None


def memory_folder(ledger_url: str) -> Path | None:
    """`ooat-memory` beside a file ledger; None for an in-memory ledger (it keeps no memory)."""
    location = ledger_url.removeprefix("sqlite:///")
    if location == ledger_url or location == ":memory:":
        return None
    return Path(location).parent / "ooat-memory"


class MemoryStore:
    """One UTF-8 file per item id. Only its owner may read the folder; on Windows it inherits the ACL of the folder
    beside the ledger, which OOAT does not change (as `ooat-login`)."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def _path(self, mem_id: str) -> Path:
        if not re.fullmatch(r"mem_[0-7][0-9A-HJKMNP-TV-Z]{25}", mem_id):
            raise UnknownMemory(f"not a memory id: {mem_id[:40]}")
        return self.folder / f"{mem_id}.txt"

    def write(self, mem_id: str, text: str) -> str:
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._path(mem_id)
        partial = path.with_suffix(".partial")
        partial.write_bytes(text.encode("utf-8"))
        os.replace(partial, path)
        return sha256_text(text)

    def read(self, mem_id: str) -> str | None:
        try:
            return self._path(mem_id).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def delete(self, mem_id: str) -> None:
        self._path(mem_id).unlink(missing_ok=True)


def _checked_text(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("a memory item needs a text")
    if len(text) > MAX_TEXT:
        raise ValueError(f"a memory item has at most {MAX_TEXT} characters")
    secret = looks_secret(text)
    if secret is not None:
        raise SecretRefused(f"not kept: it looks like {secret}; secrets belong in the secret store, never in memory")
    return text


def find(events: list[dict], mem_id: str) -> dict | None:
    """The MEMORY_NOTED of an item that is not forgotten, or None."""
    noted = next((e for e in events if e["type"] == "MEMORY_NOTED" and e["body"]["memory"] == mem_id), None)
    if noted is None or any(e["type"] == "MEMORY_FORGOTTEN" and e["body"]["memory"] == mem_id for e in events):
        return None
    return noted


def note(ledger: Ledger, store: MemoryStore, *, scope: str, kind: str, text: str, data_class: str, source: str,
         actor: dict, conversation: str | None = None, pinned: bool = False, channel: str | None = None) -> MemoryItem:
    """Store a new item: its text in the store, then MEMORY_NOTED. A text the ledger refuses to record is deleted
    again, so no text is kept without its event."""
    if kind not in KINDS:
        raise ValueError(f"a memory kind is one of {', '.join(KINDS)}")
    if not _SCOPE.match(scope):
        raise ValueError("a memory scope is a project slug or operator")
    text = _checked_text(text)
    events = ledger.events(types=EVENTS)
    if scope == OPERATOR_SCOPE and len(items(events, store, scope=scope, kinds=("preference",))) >= MAX_PREFERENCES:
        raise ValueError(f"the operator has {MAX_PREFERENCES} preferences already; forget one first")
    data_class = raised_class(data_class, text)
    mem_id = new_id("mem")
    digest = store.write(mem_id, text)
    body = {"memory": mem_id, "scope": scope, "kind": kind, "data_class": data_class, "source": source,
            "sha256": digest}
    if conversation is not None:
        body["conversation"] = conversation
    if pinned:
        body["pinned"] = True
    if channel is not None:
        body["channel"] = channel
    try:
        event = ledger.append(new_event("MEMORY_NOTED", task=None, actor=actor, body=body))
    except BaseException:
        store.delete(mem_id)
        raise
    return MemoryItem(mem_id, scope, kind, data_class, source, text, pinned, False, event["ts"], conversation)


def edit(ledger: Ledger, store: MemoryStore, mem_id: str, *, operator: str, channel: str, text: str | None = None,
         pinned: bool | None = None, done: bool | None = None) -> dict:
    """The operator changes an item's text, pins it, or marks an open point done; returns MEMORY_EDITED."""
    operator = checked_operator(operator)
    events = ledger.events(types=EVENTS)
    noted = find(events, mem_id)
    if noted is None or store.read(mem_id) is None:
        raise UnknownMemory(f"no memory item {mem_id}")
    if text is None and pinned is None and done is None:
        raise ValueError("give a text, pinned or done")
    if done is not None and noted["body"]["kind"] != "todo":
        raise ValueError("only an open point (todo) can be marked done")
    body = {"memory": mem_id, "channel": channel}
    if pinned is not None:
        body["pinned"] = pinned
    if done is not None:
        body["done"] = done
    before = None
    if text is not None:
        text = _checked_text(text)
        current = _data_class(events, noted)
        raised = raised_class(current, text)
        if raised != current:
            body["data_class"] = raised
        before = store.read(mem_id)
        body["sha256"] = store.write(mem_id, text)
    try:
        return ledger.append(new_event("MEMORY_EDITED", task=None, actor={"kind": "hil", "id": operator}, body=body))
    except BaseException:
        if before is not None:
            store.write(mem_id, before)
        raise


def forget(ledger: Ledger, store: MemoryStore, mem_id: str, *, operator: str, channel: str,
           reason: str | None = None) -> dict:
    """Delete the item's text, then record MEMORY_FORGOTTEN. Should the ledger refuse the event, the text is gone
    anyway and the item reads as forgotten: the person asked for it to go."""
    operator = checked_operator(operator)
    if find(ledger.events(types=EVENTS), mem_id) is None:
        raise UnknownMemory(f"no memory item {mem_id}")
    store.delete(mem_id)
    body = {"memory": mem_id, "channel": channel}
    if reason:
        body["reason"] = reason.strip()[:500]
    return ledger.append(new_event("MEMORY_FORGOTTEN", task=None, actor={"kind": "hil", "id": operator}, body=body))


def _data_class(events: list[dict], noted: dict) -> str:
    data_class = noted["body"]["data_class"]
    for event in events:
        if event["type"] == "MEMORY_EDITED" and event["body"]["memory"] == noted["body"]["memory"]:
            data_class = higher_class(data_class, event["body"].get("data_class", data_class))
    return data_class


def items(events: list[dict], store: MemoryStore | None, *, scope: str, cap: str | None = None,
          kinds: tuple[str, ...] = KINDS, include_done: bool = False) -> list[MemoryItem]:
    """The scope's items that are not forgotten and whose text is there, within the reader's cap: pinned first,
    then the newest."""
    if store is None:
        return []
    forgotten = {e["body"]["memory"] for e in events if e["type"] == "MEMORY_FORGOTTEN"}
    edits: dict[str, list[dict]] = {}
    for event in events:
        if event["type"] == "MEMORY_EDITED":
            edits.setdefault(event["body"]["memory"], []).append(event["body"])
    found = []
    for event in events:
        body = event["body"]
        if event["type"] != "MEMORY_NOTED" or body["scope"] != scope or body["kind"] not in kinds \
                or body["memory"] in forgotten:
            continue
        pinned, done = bool(body.get("pinned")), False
        data_class = body["data_class"]
        for change in edits.get(body["memory"], []):
            pinned = change.get("pinned", pinned)
            done = change.get("done", done)
            data_class = higher_class(data_class, change.get("data_class", data_class))
        if (done and not include_done) or (cap is not None and ORDER.index(data_class) > ORDER.index(cap)):
            continue
        text = store.read(body["memory"])
        if text is None:
            continue
        found.append(MemoryItem(body["memory"], scope, body["kind"], data_class, body["source"], text, pinned, done,
                                event["ts"], body.get("conversation")))
    found.sort(key=lambda item: item.id, reverse=True)
    return sorted(found, key=lambda item: not item.pinned)

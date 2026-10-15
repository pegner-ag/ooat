"""Conversations as projections over ledger events (design 08 §3, §4; ADR 0018).

A conversation belongs to one operator, one project and one channel. It is never stored: like state.py, everything
here is recomputed from CONVERSATION_MESSAGE, RECEPTION_DECIDED, CONVERSATION_REPORTED and CONVERSATION_CLOSED, so
a restarted process sees exactly what the ledger holds.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

TYPES = ("CONVERSATION_MESSAGE", "RECEPTION_DECIDED", "CONVERSATION_REPORTED", "CONVERSATION_CLOSED")
QUESTIONS = frozenset({"ask", "confirm"})
REPLACED = frozenset({"escalated", "retried"})  # a call whose decision the next call replaced


@dataclass(frozen=True)
class Conversation:
    id: str
    operator: str
    project: str
    channel: str
    started: str
    last_message: str  # UTC of its latest message or tap
    closed: str | None  # the reason it was closed, or None while open


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def conversations(events: list[dict]) -> dict[str, Conversation]:
    """Every conversation of the events, by id, in the order they started."""
    found: dict[str, Conversation] = {}
    for event in events:
        if event["type"] == "CONVERSATION_MESSAGE":
            body = event["body"]
            known = found.get(body["conversation"])
            if known is None:
                found[body["conversation"]] = Conversation(body["conversation"], event["actor"]["id"], body["project"],
                                                           body["channel"], event["ts"], event["ts"], None)
            else:
                found[known.id] = Conversation(known.id, known.operator, known.project, known.channel, known.started,
                                               event["ts"], known.closed)
        elif event["type"] == "CONVERSATION_CLOSED" and event["body"]["conversation"] in found:
            known = found[event["body"]["conversation"]]
            found[known.id] = Conversation(known.id, known.operator, known.project, known.channel, known.started,
                                           known.last_message, event["body"]["reason"])
    return found


def events_of(events: list[dict], conversation: str) -> list[dict]:
    """The conversation's own events, in ledger order."""
    return [e for e in events if e["type"] in TYPES and e["body"].get("conversation") == conversation]


def open_for(events: list[dict], *, operator: str, project: str, channel: str, now: datetime,
             silence_hours: float) -> Conversation | None:
    """The newest conversation of this operator, project and channel that is not closed and has had a message
    within the silence; None when a new one should start."""
    since = now - timedelta(hours=silence_hours)
    matching = [c for c in conversations(events).values()
                if (c.operator, c.project, c.channel) == (operator, project, channel) and c.closed is None
                and _utc(c.last_message) > since]
    return matching[-1] if matching else None


def silent(events: list[dict], now: datetime, silence_hours: float) -> list[Conversation]:
    """Open conversations without a message within the silence: they are due to be closed."""
    since = now - timedelta(hours=silence_hours)
    return [c for c in conversations(events).values() if c.closed is None and _utc(c.last_message) <= since]


def _decisions(own: list[dict]) -> list[dict]:
    """The reception's decisions a person saw as replies: not a replaced call, not a 'reading' notice."""
    return [e for e in own if e["type"] == "RECEPTION_DECIDED" and e["body"]["decision"] not in REPLACED
            and not e["body"].get("reading")]


def message_text(event: dict) -> str | None:
    """What a message says: its text, or the correction given with a Differently tap."""
    body = event["body"]
    return body.get("text") or (body.get("tap_text") if body.get("tap") == "differently" else None)


def undecided(own: list[dict]) -> list[dict]:
    """Messages with text that no decision has named yet, oldest first. A tap is decided when it is made, except a
    Differently with a correction, which is decided like a message."""
    named = {m for e in own if e["type"] == "RECEPTION_DECIDED" for m in e["body"]["messages"]}
    return [e for e in own if e["type"] == "CONVERSATION_MESSAGE" and message_text(e) and e["id"] not in named]


def questions_in_a_row(own: list[dict]) -> int:
    """How many of the latest decisions in a row asked the person something (design 08 §4 rule 1)."""
    count = 0
    for event in reversed(_decisions(own)):
        if event["body"]["decision"] not in QUESTIONS:
            break
        count += 1
    return count


def last_options(own: list[dict]) -> list[str]:
    """The numbered options of the newest reply or report; a newer reply without options closes them."""
    for event in reversed(own):
        if event["type"] == "CONVERSATION_REPORTED" or event in _decisions([event]):
            return list(event["body"].get("options", []))
    return []


def pending(own: list[dict]) -> dict | None:
    """What a Yes tap would start: the latest decision's `pending`, when that decision was a confirm."""
    decisions = _decisions(own)
    if not decisions or decisions[-1]["body"]["decision"] != "confirm":
        return None
    return decisions[-1]["body"].get("pending")


def last_decision(own: list[dict]) -> dict | None:
    decisions = _decisions(own)
    return decisions[-1] if decisions else None


def tasks_of(events: list[dict], conversation: str) -> list[str]:
    """Tasks the conversation's reception started, in the order they were submitted."""
    return [e["task"] for e in events if e["type"] == "TASK_SUBMITTED" and e["body"].get("conversation") == conversation]

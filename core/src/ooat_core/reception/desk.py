"""The reception's thread in `ooat serve` (design 08 §4 rule 10, §14; plan 08a task 7).

One thread, one queue of conversations, like the runner's. A conversation is decided once its newest undecided
message is `batch_seconds` old, so a burst of messages is one request. A task the runner closes is reported at once
(the runner calls `report_later`); every tick (60 s) the desk also writes any report missed across a restart, closes
silent conversations with their summary, and queues conversations whose messages are still undecided. The desk's
Reception, with its own ledger connection, is made and used in the desk's thread only.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime

from .. import conversations

log = logging.getLogger("ooat.serve")


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class Desk:
    def __init__(self, make_reception: Callable[[], object], *, clock: Callable[[], datetime], batch_seconds: float,
                 tick_seconds: float = 60.0):
        self._make, self.clock, self.batch_seconds, self.tick_seconds = make_reception, clock, batch_seconds, tick_seconds
        self._reception = None
        self._conversations: list[str] = []
        self._reports: list[str] = []
        self._changed = threading.Condition()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    # Called from any thread ---------------------------------------------------------------------------------------

    def enqueue(self, conversation: str) -> None:
        with self._changed:
            if conversation not in self._conversations:
                self._conversations.append(conversation)
            self._changed.notify()

    def report_later(self, task: str) -> None:
        with self._changed:
            if task not in self._reports:
                self._reports.append(task)
            self._changed.notify()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="ooat-reception", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        self._stopping.set()
        with self._changed:
            self._changed.notify()
        if self._thread is not None:
            self._thread.join(timeout)

    # Called in the desk's thread (or a test's) -------------------------------------------------------------------

    def reception(self):
        if self._reception is None:
            self._reception = self._make()
        return self._reception

    def due_in(self, conversation: str) -> float | None:
        """Seconds until the conversation is due; None when nothing in it waits."""
        reception = self.reception()
        own = conversations.events_of(reception.ledger.events(types=list(conversations.TYPES)), conversation)
        waiting = conversations.undecided(own)
        if not waiting:
            return None
        return self.batch_seconds - (self.clock() - _utc(waiting[-1]["ts"])).total_seconds()

    def run_due(self) -> list[str]:
        """Write queued reports, then decide every queued conversation whose quiet window has passed; returns the
        conversations decided. A conversation still waiting stays queued."""
        with self._changed:
            reports, self._reports = self._reports, []
            queued = list(self._conversations)
        for task in reports:
            self._safely(lambda: self.reception().report(task), task)
        decided = []
        for conversation in queued:
            due = self.due_in(conversation)
            if due is not None and due > 0:
                continue
            failed = False
            if due is not None:
                failed = not self._safely(lambda: self.reception().decide(conversation), conversation)
                decided.append(conversation)
            with self._changed:  # a failed decision waits for the next tick, never a busy retry
                if (failed or self.due_in(conversation) is None) and conversation in self._conversations:
                    self._conversations.remove(conversation)
        return decided

    def tick(self) -> None:
        """Missed reports, silent conversations, and conversations with undecided messages (after a restart)."""
        reception = self.reception()
        for task in reception.unreported():
            self.report_later(task)
        for conversation in reception.silent():
            if not conversations.undecided(conversations.events_of(reception.ledger.events(), conversation)):
                self._safely(lambda: reception.close(conversation, "silence"), conversation)
        events = reception.ledger.events(types=list(conversations.TYPES))
        for conversation in conversations.conversations(events):
            if conversations.undecided(conversations.events_of(events, conversation)):
                self.enqueue(conversation)

    def _safely(self, step, what: str) -> bool:
        try:
            step()
            return True
        except Exception as error:  # one conversation must not stop the desk; the message may hold its content
            log.warning("%s: reception step failed (%s %s)", what, type(error).__name__, getattr(error, "code", ""))
            return False

    def _next_wait(self) -> float:
        with self._changed:
            queued = list(self._conversations)
            if self._reports:
                return 0.0
        waits = [w for w in (self.due_in(c) for c in queued) if w is not None]
        return max(min(waits), 0.0) if waits else self.tick_seconds

    def _loop(self) -> None:
        next_tick = 0.0
        while not self._stopping.is_set():
            if time.monotonic() >= next_tick:
                self._safely(self.tick, "tick")
                next_tick = time.monotonic() + self.tick_seconds
            self._safely(self.run_due, "run")
            try:
                wait = min(self._next_wait(), max(next_tick - time.monotonic(), 0.0))
            except Exception:  # e.g. the ledger was busy: try again shortly
                wait = 1.0
            with self._changed:
                if not self._stopping.is_set():
                    self._changed.wait(wait if wait > 0 else 0.05)

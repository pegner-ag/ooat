"""The task runner of `ooat serve` (design 05 §7, ADR 0014).

One thread, one FIFO queue: spec §3 sets Solo to one task at a time. The API queues a task when it is submitted,
answered or cancelled; every tick (60 s) the runner applies defaults on silence and queues what can move without
the operator, and its first tick at start rebuilds the queue from the ledger, so tasks from `ooat task submit` and
tasks queued before a restart are picked up. A task paused by a provider failure is tried again after 60 s, then
after twice as long per further failure, at most every 30 minutes, so an outage does not spend the budget on
retries. The runner's Runtime, with its own ledger connection, is made and used in the runner's thread only.
"""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta

from .runtime import Runtime, _cancel

log = logging.getLogger("ooat.serve")
FIRST_RETRY_S, MAX_RETRY_S = 60, 1800


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def resume_after(events: list[dict]) -> datetime | None:
    """When a task paused by provider failures may be tried again; None when its last step did not fail."""
    failures, last = 0, None
    for event in events:
        body = event["body"]
        failed = (event["type"] == "RESULT" and body["outcome"] == "FAILED"
                  and body["error"]["code"] != "INVALID_OUTPUT") or (
            event["type"] == "DECISION" and event["actor"]["id"] == "ooat-runtime"
            and body["decision"].startswith("acceptance check paused")) or (
            event["type"] == "DECISION" and event["actor"]["id"] == "ooat-gate"
            and body["decision"].startswith("Gate stopped before deciding"))
        if failed:
            failures, last = failures + 1, event["ts"]
        elif event["type"] in ("RESULT", "GATE_PASSED", "GATE_FAILED", "HIL_RESPONSE"):
            failures = 0
    if not failures:
        return None
    return _utc(last) + timedelta(seconds=min(FIRST_RETRY_S * 2 ** (failures - 1), MAX_RETRY_S))


class Runner:
    def __init__(self, make_runtime: Callable[[], Runtime], *, clock: Callable[[], datetime],
                 tick_seconds: float = 60.0):
        self._make_runtime, self.clock, self.tick_seconds = make_runtime, clock, tick_seconds
        self._runtime: Runtime | None = None
        self._queue: deque[str] = deque()
        self._current: str | None = None
        self._again = False  # the running task was queued meanwhile, e.g. answered or cancelled: run it again
        self._changed = threading.Condition()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    # Called from any thread ---------------------------------------------------------------------------------------

    def enqueue(self, task: str) -> None:
        with self._changed:
            if task == self._current:
                self._again = True
            elif task not in self._queue:
                self._queue.append(task)
                self._changed.notify()

    def status(self) -> dict:
        with self._changed:
            return {"state": "running" if self._current else "idle", "task": self._current,
                    "queued": len(self._queue)}

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="ooat-runner", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        """Ask the thread to stop after the task in hand; a provider call in flight is not interrupted."""
        self._stopping.set()
        with self._changed:
            self._changed.notify()
        if self._thread is not None:
            self._thread.join(timeout)

    # Called in the runner's thread (or a test's) ----------------------------------------------------------------

    def runtime(self) -> Runtime:
        if self._runtime is None:
            self._runtime = self._make_runtime()
        return self._runtime

    def tick(self) -> None:
        """Apply defaults on silence and queue every task that can move, in the order it was submitted."""
        runtime, now = self.runtime(), self.clock()
        for task in runtime.runnable():  # applies expired defaults first
            events = runtime.ledger.events(task=task)
            due = resume_after(events)
            if due is None or due <= now or _cancel(events) is not None:  # a cancel does not wait for the pause
                self.enqueue(task)

    def run_next(self) -> str | None:
        """Run the oldest queued task as far as it goes; returns it, or None when the queue is empty."""
        with self._changed:
            if not self._queue:
                return None
            task = self._current = self._queue.popleft()
        try:
            outcome = self.runtime().run(task)
            log.info("%s: %s", task, outcome.state)
        except Exception as error:  # one task must not stop the runner; the message may hold task content
            log.warning("%s: not run (%s %s)", task, type(error).__name__, getattr(error, "code", ""))
        finally:
            with self._changed:
                self._current = None
                if self._again:
                    self._again = False
                    self._queue.append(task)
        return task

    def drain(self) -> list[str]:
        """Run queued tasks until none is left (tests and shutdown-free use)."""
        done = []
        while (task := self.run_next()) is not None:
            done.append(task)
        return done

    def _loop(self) -> None:
        next_tick = 0.0
        while not self._stopping.is_set():
            if time.monotonic() >= next_tick:
                try:
                    self.tick()
                except Exception as error:  # e.g. the ledger was busy: try again at the next tick
                    log.warning("tick failed (%s)", type(error).__name__)
                next_tick = time.monotonic() + self.tick_seconds
            if self.run_next() is None:
                with self._changed:
                    if not self._queue and not self._stopping.is_set():
                        self._changed.wait(max(next_tick - time.monotonic(), 0.0))

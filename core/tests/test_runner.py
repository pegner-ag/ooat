"""The runner of `ooat serve` and the runner lock (design 05 §7, §14)."""

import logging
import time
from datetime import datetime, timedelta, timezone

from runtime_fakes import ScriptedModel, acknowledge, decisions, routing_document
from test_runtime import NOW, Setup

from ooat_core.artifacts import ArtifactStore
from ooat_core.blobs import BlobStore
from ooat_core.config import parse_config
from ooat_core.connectors import ConnectorError
from ooat_core.connectors.registry import Registry
from ooat_core.credentials_env import SecretResolver
from ooat_core.gateway import Gateway
from ooat_core.ledger import Ledger
from ooat_core.routing import RoutingPolicy
from ooat_core.runner import Runner, resume_after
from ooat_core.runner_lock import RunnerLock, for_ledger
from ooat_core.runtime import Runtime
from ooat_core.state import task_state

CRITERIA = ["Shrnutí má nejvýše 300 slov."]


def runner_for(setup, tick_seconds=60.0):
    return Runner(lambda: setup.runtime, clock=lambda: setup.now, tick_seconds=tick_seconds)


def state(setup, task):
    return task_state(setup.ledger.events(task=task))


def test_the_first_tick_rebuilds_the_queue_from_the_ledger_in_submission_order(tmp_path):
    setup = Setup(tmp_path)
    first, second = setup.submit(), setup.submit()  # e.g. `ooat task submit` while the server was down
    waiting = setup.submit(acceptance=())
    setup.runtime.run(waiting)  # waits for a clarification: not runnable
    runner = runner_for(setup)
    runner.tick()
    assert runner.status() == {"state": "idle", "task": None, "queued": 2}
    assert runner.drain() == [first, second]
    assert state(setup, first) == state(setup, second) == "CLOSED_DONE" and state(setup, waiting) == "CLARIFYING"


def test_a_task_is_queued_once_however_often_it_is_enqueued(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit()
    runner = runner_for(setup)
    for _ in range(3):
        runner.enqueue(task)
    runner.tick()
    assert runner.drain() == [task]


def test_a_paused_task_is_tried_again_after_a_growing_pause(tmp_path):
    model = ScriptedModel(outages={("worker", 1): ConnectorError("UNAVAILABLE", "HTTP 529"),
                                   ("worker", 2): ConnectorError("UNAVAILABLE", "HTTP 529")})
    setup = Setup(tmp_path, model=model)
    start = setup.now = datetime.now(timezone.utc)  # the ledger stamps events with the real time
    task = setup.submit()
    runner = runner_for(setup)
    runner.enqueue(task)
    runner.drain()
    assert state(setup, task) == "RUNNING"  # paused by the provider
    runner.tick()
    assert runner.drain() == []  # not before 60 s
    setup.now = start + timedelta(seconds=65)
    runner.tick()
    # Failed again. The ledger stamped that failure with the real time, a moment after `start`: next try in 120 s.
    assert runner.drain() == [task] and state(setup, task) == "RUNNING"
    setup.now = start + timedelta(seconds=100)
    runner.tick()
    assert runner.drain() == []
    setup.now = start + timedelta(seconds=180)
    runner.tick()
    assert runner.drain() == [task] and state(setup, task) == "CLOSED_DONE"


def test_the_pause_doubles_per_failure_up_to_thirty_minutes():
    def failed(n):
        return {"type": "RESULT", "ts": "2026-10-02T12:00:00Z", "actor": {"id": "agt"},
                "body": {"outcome": "FAILED", "error": {"code": "TIMEOUT", "message": "x"}}}
    start = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    assert resume_after([]) is None
    assert resume_after([failed(1)]) == start + timedelta(seconds=60)
    assert resume_after([failed(n) for n in range(3)]) == start + timedelta(seconds=240)
    assert resume_after([failed(n) for n in range(12)]) == start + timedelta(minutes=30)
    invalid = {**failed(0), "body": {"outcome": "FAILED", "error": {"code": "INVALID_OUTPUT", "message": "x"}}}
    assert resume_after([invalid]) is None  # a malformed reply is an attempt, not an outage


def test_one_failing_task_does_not_stop_the_runner_and_its_content_stays_out_of_the_log(tmp_path, caplog,
                                                                                       monkeypatch):
    setup = Setup(tmp_path)
    broken, fine = setup.submit(), setup.submit()
    real_run = Runtime.run

    def refuse(self, task):
        if task == broken:
            raise ValueError("Shrň smlouvu pro jednatele: secret client text")
        return real_run(self, task)
    monkeypatch.setattr(Runtime, "run", refuse)
    runner = runner_for(setup)
    runner.tick()
    with caplog.at_level(logging.INFO, logger="ooat.serve"):
        assert runner.drain() == [broken, fine]
    assert state(setup, fine) == "CLOSED_DONE"
    assert "ValueError" in caplog.text and "secret client text" not in caplog.text


def file_runtime(path, model, jev):
    """A Runtime on a file ledger, made in the thread that calls it (SQLite connections stay in their thread)."""
    def make():
        ledger = Ledger.open(f"sqlite:///{path.as_posix()}")
        config = parse_config({})
        gateway = Gateway(ledger, Registry([model, jev]), RoutingPolicy(routing_document()), config,
                          SecretResolver(config, {}), clock=lambda: NOW)
        return Runtime(ledger, gateway, ArtifactStore(ledger, BlobStore(path.parent / "blobs")), clock=lambda: NOW)
    return make


def test_the_runner_thread_runs_what_the_api_queues_and_stops(tmp_path):
    path = tmp_path / "ledger.sqlite"
    model, jev = ScriptedModel(), decisions()
    intake = file_runtime(path, model, jev)()  # the API's own connection, in this thread
    for connector in (model, jev):
        acknowledge(intake.ledger, connector)
    runner = Runner(file_runtime(path, model, jev), clock=lambda: NOW, tick_seconds=3600)
    runner.start()
    task = intake.submit(operator="operator", goal="Shrň smlouvu.", acceptance=CRITERIA, channel="web")
    runner.enqueue(task)
    deadline = time.monotonic() + 30
    while task_state(intake.ledger.events(task=task)) != "CLOSED_DONE" and time.monotonic() < deadline:
        time.sleep(0.05)
    runner.stop()
    assert task_state(intake.ledger.events(task=task)) == "CLOSED_DONE"
    assert not runner._thread.is_alive()
    intake.ledger.close()


def test_the_runner_lock_is_held_by_one_holder_at_a_time(tmp_path):
    lock = for_ledger(f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}")
    assert lock.path.name == "ledger.sqlite.runner.lock"
    other = RunnerLock(lock.path)
    assert lock.acquire() and not other.acquire()
    lock.release()
    assert other.acquire()
    other.release()
    assert for_ledger("sqlite:///:memory:") is None


# Final review of plan 05a: retries and cancels the runner must not miss ------------------------------------------

def test_a_gate_stopped_by_a_quota_cool_down_waits_a_growing_pause(tmp_path):
    from ooat_core.ledger import new_event

    setup = Setup(tmp_path)
    start = setup.now = datetime.now(timezone.utc)
    task = setup.submit()
    resets = (start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")  # the worker's window is used up
    setup.ledger.append(new_event("QUOTA_WARNING", task=task, actor={"kind": "system", "id": "ooat-gate"}, body={
        "adapter": setup.model.manifest["id"], "utilisation": 1.0, "window_resets_at": resets}))
    runner = runner_for(setup)
    for tick in range(10):  # ten minutes of ticks
        setup.now = start + timedelta(seconds=61 * tick)
        runner.tick()
        runner.drain()
    paid = [e for e in setup.ledger.events(task=task, types=["DECISION"]) if e["actor"]["id"] == "ooat-gate"]
    assert state(setup, task) == "SUBMITTED" and 1 <= len(paid) <= 5  # 0, 60, 120, 240, 480 s: not every tick


class FailsAfterCancel(ScriptedModel):
    """The operator cancels, and the API queues the task, while the worker call is in flight; then it fails."""

    def __init__(self, cancel):
        super().__init__(outages={("worker", n): ConnectorError("UNAVAILABLE", "HTTP 529") for n in range(1, 9)})
        self.cancel = cancel

    def complete(self, request, secrets):
        if self.cancel is not None:
            cancel, self.cancel = self.cancel, None
            cancel()
        return super().complete(request, secrets)


def test_a_cancel_while_a_failing_call_is_in_flight_closes_the_task_at_once(tmp_path):
    def cancel():
        setup.runtime.cancel(task, operator="operator", channel="web")
        runner.enqueue(task)  # as the API does; the task is the one running

    setup = Setup(tmp_path, model=FailsAfterCancel(cancel))
    setup.now = datetime.now(timezone.utc)
    task = setup.submit()
    runner = runner_for(setup)
    runner.enqueue(task)
    runner.drain()
    assert state(setup, task) == "CANCELLED"
    assert "RESULT" in [e["type"] for e in setup.ledger.events(task=task)]  # the failed call's cost is recorded


def test_a_task_queued_while_it_runs_runs_again_after(tmp_path):
    class QueuedDuringTheCall(ScriptedModel):
        def complete(self, request, secrets):
            runner.enqueue(task)  # e.g. an answer arrives while the runner is in this task
            return super().complete(request, secrets)

    setup = Setup(tmp_path, model=QueuedDuringTheCall())
    task = setup.submit()
    runner = runner_for(setup)
    runner.enqueue(task)
    assert runner.drain() == [task, task]


def test_a_cancel_of_a_paused_task_is_not_held_back_by_its_pause(tmp_path):
    model = ScriptedModel(outages={("worker", n): ConnectorError("UNAVAILABLE", "HTTP 529") for n in range(1, 9)})
    setup = Setup(tmp_path, model=model)
    start = setup.now = datetime.now(timezone.utc)
    task = setup.submit()
    runner = runner_for(setup)
    for _ in range(5):
        runner.enqueue(task)
        runner.drain()  # five failures: the next try is 16 minutes away
    setup.runtime.cancel(task, operator="operator")  # e.g. `ooat` on another machine; nothing queued it
    setup.now = start + timedelta(seconds=61)
    runner.tick()
    runner.drain()
    assert state(setup, task) == "CANCELLED"

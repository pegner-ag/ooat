"""The reception desk: the quiet window, reports of finished tasks, summaries of silent conversations (design 08
§4 rule 8 and 10, §14; plan 08a task 7)."""

from datetime import datetime, timedelta, timezone

from reception_fakes import Desk, ReceptionModel, decision

from ooat_core import memory
from ooat_core.reception.desk import Desk as ReceptionDesk
from ooat_core.runner import Runner

REPORT = {"reply": "Hotovo: titulek je změněný. Stav: hotovo.", "options": ["Změnit i patičku", "Nic dalšího"]}


def front(tmp_path, replies=(), **options):
    """A reception on a fake clock that starts at the real time: the ledger stamps events with the real time."""
    front = Desk(tmp_path, replies, **options)
    front.now = datetime.now(timezone.utc)
    desk = ReceptionDesk(lambda: front.reception, clock=lambda: front.now, batch_seconds=8)
    return front, desk


def test_messages_wait_for_the_quiet_window(tmp_path):
    f, desk = front(tmp_path, [decision("answer", "Ano.")])
    conversation = f.say("Ahoj.")["body"]["conversation"]
    desk.enqueue(conversation)
    f.now += timedelta(seconds=5)
    assert desk.run_due() == [] and f.events("RECEPTION_DECIDED") == []
    f.now += timedelta(seconds=4)
    assert desk.run_due() == [conversation] and len(f.events("RECEPTION_DECIDED")) == 1


def test_a_burst_is_decided_once_when_enqueued_twice(tmp_path):
    f, desk = front(tmp_path, [decision("answer", "Ano.")])
    conversation = f.say("advanced-genetics.ru / G-AAAA")["body"]["conversation"]
    desk.enqueue(conversation)
    f.say("bh-obchodni.cz / G-BBBB")
    desk.enqueue(conversation)
    f.now += timedelta(seconds=9)
    desk.run_due()
    decided = f.events("RECEPTION_DECIDED")
    assert len(decided) == 1 and len(decided[0]["body"]["messages"]) == 2
    assert desk.run_due() == []


def test_a_message_arriving_during_a_decision_is_decided_next(tmp_path):
    f, desk = front(tmp_path)
    arrived = []

    def first_call(request):
        if not arrived:
            arrived.append(f.say("A ještě patičku."))
        return decision("answer", "Ano.")
    f.model.replies = [first_call]
    conversation = f.say("Změň titulek.")["body"]["conversation"]
    desk.enqueue(conversation)
    f.now += timedelta(seconds=9)
    desk.run_due()
    f.now += timedelta(seconds=9)
    desk.run_due()
    decided = [e["body"]["messages"] for e in f.events("RECEPTION_DECIDED")]
    messages = [e["id"] for e in f.events("CONVERSATION_MESSAGE")]
    assert decided == [[messages[0]], [messages[1]]]


def test_a_failed_decision_waits_for_the_next_tick(tmp_path):
    f, desk = front(tmp_path)
    conversation = f.say("Ahoj.")["body"]["conversation"]
    desk.enqueue(conversation)
    f.now += timedelta(seconds=9)

    def broken(_):
        raise RuntimeError("bug")
    f.reception.decide = broken
    desk.run_due()
    assert desk.run_due() == []  # not retried in a busy loop
    desk.tick()
    assert desk.run_due() == [conversation]  # the tick queued it again


def test_a_closed_conversation_task_gets_one_report_with_options(tmp_path):
    f, desk = front(tmp_path, [decision("task"), REPORT])
    task = f.ask("Změň titulek.")["body"]["task"]
    f.runtime.cancel(task, operator="operator")
    f.runtime.run(task)
    desk.report_later(task)
    desk.run_due()
    report = f.events("CONVERSATION_REPORTED")
    assert len(report) == 1 and report[0]["body"]["options"] == REPORT["options"]
    assert report[0]["body"]["reply"] == REPORT["reply"] and report[0]["cost"]["tier"] == "economy"
    desk.report_later(task)
    desk.tick()
    desk.run_due()
    assert len(f.events("CONVERSATION_REPORTED")) == 1


def test_a_report_the_model_cannot_write_is_oaats_own_line(tmp_path):
    f, desk = front(tmp_path, [decision("task"), "nonsense"])
    task = f.ask("Změň titulek.")["body"]["task"]
    f.runtime.cancel(task, operator="operator")
    f.runtime.run(task)
    assert f.reception.report(task)["body"]["reply"].startswith("Zrušeno")


def test_the_tick_writes_a_report_missed_across_a_restart(tmp_path):
    f, desk = front(tmp_path, [decision("task"), REPORT])
    task = f.ask("Změň titulek.")["body"]["task"]
    f.runtime.cancel(task, operator="operator")
    f.runtime.run(task)
    desk.tick()
    desk.run_due()
    assert len(f.events("CONVERSATION_REPORTED")) == 1


def test_the_runner_calls_back_when_a_task_closes(tmp_path):
    f, desk = front(tmp_path, [decision("task")])
    task = f.ask("Změň titulek.")["body"]["task"]
    f.runtime.cancel(task, operator="operator")
    closed = []
    runner = Runner(lambda: f.runtime, clock=lambda: f.now, on_closed=closed.append)
    runner.enqueue(task)
    runner.drain()
    assert closed == [task]


def test_a_silent_conversation_is_closed_with_a_summary(tmp_path):
    f, desk = front(tmp_path, [decision("answer", "Ceny jsou s DPH."), "Ptal se na ceny; odpověď: s DPH."])
    conversation = f.ask("Jsou ceny s DPH?")["body"]["conversation"]
    f.now += timedelta(hours=25)
    desk.tick()
    closed = f.events("CONVERSATION_CLOSED")[0]["body"]
    assert closed["reason"] == "silence" and closed["conversation"] == conversation
    summary = memory.items(f.ledger.events(), f.store, scope="docs", kinds=("summary",))
    assert [s.id for s in summary] == [closed["summary"]] and summary[0].text == "Ptal se na ceny; odpověď: s DPH."
    assert f.say("Nová věc.")["body"]["conversation"] != conversation


def test_a_silent_conversation_with_an_undecided_message_stays_open_until_decided(tmp_path):
    f, desk = front(tmp_path)
    conversation = f.say("Ahoj.")["body"]["conversation"]
    f.now += timedelta(hours=25)
    desk.tick()
    assert f.events("CONVERSATION_CLOSED") == []  # its message is queued instead


def test_closing_without_any_decision_writes_no_summary(tmp_path):
    f, desk = front(tmp_path)
    conversation = f.say("Ahoj.")["body"]["conversation"]
    closed = f.reception.close(conversation, "operator")["body"]
    assert closed["reason"] == "operator" and "summary" not in closed and f.model.calls == []
    assert f.reception.close(conversation) is None


def test_a_report_carries_the_tasks_class(tmp_path):
    f, desk = front(tmp_path, [decision("task"), REPORT])
    task = f.ask("Napiš panu Novákovi na jan.novak@example.cz.")["body"]["task"]
    f.runtime.cancel(task, operator="operator")
    f.runtime.run(task)
    assert f.reception.report(task)["body"]["data_class"] == "personal"


def test_the_desk_thread_decides_on_its_own(tmp_path):
    import time
    f = Desk(tmp_path, [decision("answer", "Ano.")])
    f.now = datetime.now(timezone.utc)
    desk = ReceptionDesk(f.fresh_reception, clock=lambda: datetime.now(timezone.utc), batch_seconds=0.2,
                         tick_seconds=60)
    desk.start()
    try:
        desk.enqueue(f.say("Ahoj.")["body"]["conversation"])
        deadline = time.monotonic() + 10
        while not f.events("RECEPTION_DECIDED"):
            assert time.monotonic() < deadline, "the desk never decided"
            time.sleep(0.05)
    finally:
        desk.stop()

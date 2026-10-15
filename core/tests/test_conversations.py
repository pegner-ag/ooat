"""Conversations as a projection over ledger events (design 08 §3, §4; plan 08a task 4)."""

from datetime import datetime, timedelta, timezone

from ooat_core import conversations
from ooat_core.ids import new_id

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def ts(hours_ago: float = 0.0) -> str:
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def message(cnv, hours_ago=0.0, operator="operator", project="docs", channel="web", text="Změň titulek.", **body):
    content = {"text": text} if "tap" not in body else {}
    return {"id": new_id("evt"), "ts": ts(hours_ago), "task": None, "actor": {"kind": "hil", "id": operator},
            "type": "CONVERSATION_MESSAGE", "refs": [], "body": {
                "conversation": cnv, "project": project, "channel": channel, "data_class": "internal",
                **content, **body}}


def decided(cnv, messages, decision="task", hours_ago=0.0, **body):
    return {"id": new_id("evt"), "ts": ts(hours_ago), "task": None,
            "actor": {"kind": "system", "id": "ooat-reception"}, "type": "RECEPTION_DECIDED", "refs": [],
            "body": {"conversation": cnv, "project": "docs", "messages": [m["id"] for m in messages],
                     "decision": decision, "options": [], "buttons": [], "context": [], "data_class": "internal",
                     **body}}


def reported(cnv, task, options, hours_ago=0.0):
    return {"id": new_id("evt"), "ts": ts(hours_ago), "task": None,
            "actor": {"kind": "system", "id": "ooat-reception"}, "type": "CONVERSATION_REPORTED", "refs": [],
            "body": {"conversation": cnv, "project": "docs", "task": task, "reply": "Hotovo.", "options": options,
                     "data_class": "internal"}}


def closed(cnv):
    return {"id": new_id("evt"), "ts": ts(), "task": None, "actor": {"kind": "system", "id": "ooat-reception"},
            "type": "CONVERSATION_CLOSED", "refs": [],
            "body": {"conversation": cnv, "project": "docs", "reason": "operator"}}


def find(events, **key):
    return conversations.open_for(events, **({"operator": "operator", "project": "docs", "channel": "web"} | key),
                                  now=NOW, silence_hours=24)


def test_a_conversation_is_found_by_operator_project_and_channel():
    cnv = new_id("cnv")
    events = [message(cnv, hours_ago=1)]
    found = find(events)
    assert found.id == cnv and found.operator == "operator" and found.closed is None
    assert find(events, channel="cli") is None
    assert find(events, project="shop") is None
    assert find(events, operator="someone else") is None


def test_after_the_silence_a_conversation_is_not_open_and_is_listed_as_silent():
    cnv = new_id("cnv")
    events = [message(cnv, hours_ago=25)]
    assert find(events) is None
    assert [c.id for c in conversations.silent(events, NOW, 24)] == [cnv]


def test_a_closed_conversation_is_never_open_nor_silent():
    cnv = new_id("cnv")
    events = [message(cnv, hours_ago=30), closed(cnv)]
    assert find(events) is None and conversations.silent(events, NOW, 24) == []
    assert conversations.conversations(events)[cnv].closed is not None


def test_the_newest_open_conversation_wins():
    older, newer = new_id("cnv"), new_id("cnv")
    events = [message(older, hours_ago=3), message(newer, hours_ago=2)]
    assert find(events).id == newer


def test_undecided_leaves_out_messages_a_decision_named_also_in_a_batch():
    cnv = new_id("cnv")
    first, second, third = message(cnv), message(cnv), message(cnv)
    events = [first, second, decided(cnv, [first, second]), third]
    assert [m["id"] for m in conversations.undecided(events)] == [third["id"]]


def test_a_tap_is_never_undecided():
    cnv = new_id("cnv")
    assert conversations.undecided([message(cnv, tap="yes")]) == []


def test_questions_in_a_row():
    cnv = new_id("cnv")
    a, b, c = message(cnv), message(cnv), message(cnv)
    asked = [a, decided(cnv, [a], "ask"), b, decided(cnv, [b], "confirm", goal="x")]
    assert conversations.questions_in_a_row(asked) == 2
    assert conversations.questions_in_a_row([*asked, c, decided(cnv, [c], "task")]) == 0
    assert conversations.questions_in_a_row([]) == 0


def test_escalated_and_reading_steps_do_not_count_as_questions():
    cnv = new_id("cnv")
    a = message(cnv)
    events = [a, decided(cnv, [a], "ask"), decided(cnv, [a], "escalated"), decided(cnv, [a], "ask")]
    assert conversations.questions_in_a_row(events) == 2


def test_last_options_come_from_the_newest_reply_or_report_with_options():
    cnv, task = new_id("cnv"), new_id("tsk")
    a = message(cnv)
    events = [a, decided(cnv, [a], "ask", options=["testdna.cz", "eurogeen.com"])]
    assert conversations.last_options(events) == ["testdna.cz", "eurogeen.com"]
    events.append(reported(cnv, task, ["Zkontrolovat i patičku", "Nasadit později"]))
    assert conversations.last_options(events) == ["Zkontrolovat i patičku", "Nasadit později"]
    events.append(decided(cnv, [message(cnv)], "answer"))  # a later reply without options: none are open
    assert conversations.last_options(events) == []


def test_pending_is_the_latest_confirm_until_another_decision():
    cnv = new_id("cnv")
    a, b = message(cnv), message(cnv)
    pending = {"goal": "Změnit titulek.", "acceptance": ["Titulek zní …"]}
    events = [a, decided(cnv, [a], "confirm", pending=pending)]
    assert conversations.pending(events) == pending
    assert conversations.pending([*events, b, decided(cnv, [b], "task")]) is None


def test_tasks_of_a_conversation():
    cnv, task = new_id("cnv"), new_id("tsk")
    events = [{"id": new_id("evt"), "ts": ts(), "task": task, "actor": {"kind": "hil", "id": "operator"},
               "type": "TASK_SUBMITTED", "refs": [], "body": {"goal": "x", "conversation": cnv}},
              {"id": new_id("evt"), "ts": ts(), "task": new_id("tsk"), "actor": {"kind": "hil", "id": "operator"},
               "type": "TASK_SUBMITTED", "refs": [], "body": {"goal": "y"}}]
    assert conversations.tasks_of(events, cnv) == [task]


def test_events_of_a_conversation_keep_their_order():
    cnv, other = new_id("cnv"), new_id("cnv")
    a, b = message(cnv), message(other)
    events = [a, b, decided(cnv, [a])]
    assert [e["type"] for e in conversations.events_of(events, cnv)] == ["CONVERSATION_MESSAGE", "RECEPTION_DECIDED"]

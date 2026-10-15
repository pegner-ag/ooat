"""The ledger events of conversations, the reception and memory (design 08 §7, ADR 0018), and the reception's
decision schema."""

import hashlib

import pytest

from ooat_core.ids import new_id
from ooat_core.ledger import DuplicateIntake, Ledger, new_event
from ooat_core.validation import SpecValidationError, validate

HUMAN = {"kind": "hil", "id": "operator"}
RECEPTION = {"kind": "system", "id": "ooat-reception"}
SHA = "sha256:" + hashlib.sha256(b"text").hexdigest()


@pytest.fixture
def ledger():
    ledger = Ledger.open("sqlite:///:memory:")
    yield ledger
    ledger.close()


def message(conversation, **body):
    return new_event("CONVERSATION_MESSAGE", task=None, actor=HUMAN, body={
        "conversation": conversation, "project": "docs", "channel": "web", "text": "Změň titulek.",
        "data_class": "internal", **body})


def test_every_new_event_type_is_appended(ledger):
    conversation, memory, task = new_id("cnv"), new_id("mem"), new_id("tsk")
    sent = ledger.append(message(conversation))
    ledger.append(new_event("RECEPTION_DECIDED", task=None, actor=RECEPTION, body={
        "conversation": conversation, "project": "docs", "messages": [sent["id"]], "decision": "task",
        "reply": "Dělám na tom: změním titulek.", "options": [], "buttons": ["differently"], "task": task,
        "record": {"engine": "prv.fake.api", "model": "fake-economy", "confidence": 0.9, "threshold": 0.7},
        "context": [memory], "data_class": "internal"}))
    ledger.append(new_event("CONVERSATION_REPORTED", task=None, actor=RECEPTION, body={
        "conversation": conversation, "project": "docs", "task": task, "reply": "Hotovo.",
        "options": ["Zkontrolovat i patičku"], "data_class": "internal"}))
    ledger.append(new_event("MEMORY_NOTED", task=None, actor=RECEPTION, body={
        "memory": memory, "scope": "docs", "kind": "todo", "data_class": "internal", "source": sent["id"],
        "sha256": SHA, "conversation": conversation}))
    ledger.append(new_event("MEMORY_EDITED", task=None, actor=HUMAN, body={
        "memory": memory, "done": True, "channel": "web"}))
    ledger.append(new_event("MEMORY_FORGOTTEN", task=None, actor=HUMAN, body={"memory": memory, "channel": "web"}))
    ledger.append(new_event("CONVERSATION_CLOSED", task=None, actor=RECEPTION, body={
        "conversation": conversation, "project": "docs", "reason": "silence"}))
    assert len(ledger.events()) == 7


def test_a_tap_is_a_message_without_text(ledger):
    ledger.append(new_event("CONVERSATION_MESSAGE", task=None, actor=HUMAN, body={
        "conversation": new_id("cnv"), "project": "docs", "channel": "web", "tap": "yes", "data_class": "internal"}))


def test_a_message_needs_text_or_a_tap(ledger):
    with pytest.raises(SpecValidationError):
        ledger.append(new_event("CONVERSATION_MESSAGE", task=None, actor=HUMAN, body={
            "conversation": new_id("cnv"), "project": "docs", "channel": "web", "data_class": "internal"}))


def test_a_message_belongs_to_no_task(ledger):
    event = message(new_id("cnv"))
    event["task"] = new_id("tsk")
    with pytest.raises(SpecValidationError):
        ledger.append(event)


def test_only_a_human_sends_a_message(ledger):
    event = message(new_id("cnv"))
    event["actor"] = RECEPTION
    with pytest.raises(SpecValidationError):
        ledger.append(event)


@pytest.mark.parametrize("kind", ["MEMORY_EDITED", "MEMORY_FORGOTTEN"])
def test_only_a_human_edits_or_forgets(ledger, kind):
    with pytest.raises(SpecValidationError):
        ledger.append(new_event(kind, task=None, actor=RECEPTION, body={"memory": new_id("mem"), "channel": "web"}))


def test_memory_events_never_carry_the_text(ledger):
    with pytest.raises(SpecValidationError):
        ledger.append(new_event("MEMORY_NOTED", task=None, actor=RECEPTION, body={
            "memory": new_id("mem"), "scope": "docs", "kind": "fact", "data_class": "internal",
            "source": new_id("evt"), "sha256": SHA, "text": "Ceny jsou s DPH."}))


def test_a_reception_workspace_use_needs_its_conversation(ledger):
    body = {"project": "docs", "by": "reception", "write": False, "read": [], "changed": [], "created": [],
            "refused": [], "operations": 1, "written_bytes": 0, "limit": None, "journal_lines": 1}
    actor = {"kind": "system", "id": "ooat-runtime"}
    with pytest.raises(SpecValidationError):
        ledger.append(new_event("WORKSPACE_USED", task=None, actor=actor, body=body))
    ledger.append(new_event("WORKSPACE_USED", task=None, actor=actor, body={**body, "conversation": new_id("cnv")}))


def test_a_quota_warning_of_a_reception_call_has_no_task(ledger):
    ledger.append(new_event("QUOTA_WARNING", task=None, actor={"kind": "system", "id": "ooat-gateway"},
                            body={"adapter": "prv.fake.api", "utilisation": 1.0}))


def test_a_task_names_its_conversation(ledger):
    ledger.append(new_event("TASK_SUBMITTED", task=new_id("tsk"), actor=HUMAN, body={
        "goal": "Změň titulek.", "conversation": new_id("cnv")}))


def test_a_repeated_message_on_its_channel_is_the_first_one(ledger):
    conversation = new_id("cnv")
    first = ledger.append(message(conversation, intake_key="chat:1"))
    with pytest.raises(DuplicateIntake) as repeated:
        ledger.append(message(conversation, intake_key="chat:1"))
    assert repeated.value.earlier["id"] == first["id"]
    assert repeated.value.task is None
    ledger.append(message(conversation, intake_key="chat:1", channel="cli"))  # another channel, another key


def test_a_task_and_a_message_may_share_a_key(ledger):
    ledger.append(message(new_id("cnv"), intake_key="chat:2"))
    ledger.append(new_event("TASK_SUBMITTED", task=new_id("tsk"), actor=HUMAN, body={
        "goal": "Změň titulek.", "channel": "web", "intake_key": "chat:2"}))


DECISIONS = [
    {"decision": "answer", "reply": "Ceny jsou s DPH.", "confidence": 0.9, "needs_files": False},
    {"decision": "task", "reply": "Dělám na tom.", "confidence": 0.9, "goal": "Změň titulek.",
     "acceptance": ["Titulek zní …"], "risk_hint": "R1"},
    {"decision": "confirm", "reply": "Rozumím tomu jako …", "confidence": 0.5, "goal": "Změň titulek."},
    {"decision": "ask", "reply": "Který web?", "confidence": 0.4, "options": ["testdna.cz", "eurogeen.com"]},
    {"decision": "continue_task", "reply": "Doplním to.", "confidence": 0.8, "task": new_id("tsk")},
    {"decision": "status", "reply": "Běží jeden úkol.", "confidence": 0.9},
    {"decision": "cancel", "reply": "Zastavuji.", "confidence": 0.9},
    {"decision": "command", "reply": "Push zatím neumím.", "confidence": 0.9},
    {"decision": "switch", "reply": "Přepínám.", "confidence": 0.9, "project": "e-vyroba"},
    {"decision": "forget", "reply": "Zapomenout?", "confidence": 0.9, "memory": new_id("mem")},
    {"decision": "answer", "reply": "Zapamatováno.", "confidence": 0.9,
     "memory_notes": [{"kind": "todo", "text": "Na konci projektu připomenout DNS."}]},
]


@pytest.mark.parametrize("decision", DECISIONS)
def test_reception_decisions_validate(decision):
    validate("reception", decision)


@pytest.mark.parametrize("decision", [
    {"decision": "task", "reply": "Dělám na tom.", "confidence": 0.9},
    {"decision": "continue_task", "reply": "Doplním to.", "confidence": 0.8},
    {"decision": "run", "reply": "?", "confidence": 0.8},
    {"decision": "answer", "reply": "Ok.", "confidence": 0.8,
     "memory_notes": [{"kind": "fact", "text": f"Fakt {n}"} for n in range(4)]},
    {"decision": "switch", "reply": "Přepínám.", "confidence": 0.9},
    {"decision": "answer", "reply": "Ok.", "confidence": 1.5},
])
def test_malformed_reception_decisions_are_refused(decision):
    with pytest.raises(SpecValidationError):
        validate("reception", decision)

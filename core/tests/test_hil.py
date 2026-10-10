"""The shared answer path, R3 on every channel, and who may write a human event (design 05 §6, ADR 0016)."""

import re
from datetime import timedelta
from pathlib import Path

import pytest
from test_runtime import NOW, Setup

import ooat_core
from ooat_core.hil import AlreadyAnswered, R3NeedsBoundIdentity, UnknownRequest, answer, open_requests
from ooat_core.ids import new_id
from ooat_core.ledger import new_event
from ooat_core.runtime import TaskClosed

TOKEN_CHANNEL = "token:tok_01J9ZQ80B0K3M5N7P9Q1R3S5T7"


def waiting(tmp_path):
    """A task waiting for a clarification, and its open request."""
    setup = Setup(tmp_path)
    task = setup.submit(acceptance=())
    return setup, task, setup.runtime.run(task).request


def r3_request(setup, task):
    return setup.ledger.append(new_event("HIL_REQUEST", task=task, actor={"kind": "system", "id": "ooat-runtime"},
                                         body={"question": "Odeslat nabídku klientovi?", "risk_class": "R3",
                                               "options": [{"id": "send", "label": "Odeslat", "cost_usd": 0.0},
                                                           {"id": "hold", "label": "Neodesílat", "cost_usd": 0.0,
                                                            "acts": False}],
                                               "recommended": "send", "default_on_silence": "hold",
                                               "deadline": "2026-10-03T12:00:00Z", "blocking": True,
                                               "evidence": []}))


def test_an_answer_records_the_operator_and_the_channel(tmp_path):
    setup, task, request = waiting(tmp_path)
    response = answer(setup.ledger, setup.runtime, request, operator=" operator ", text=" Nejvýše 300 slov. ",
                      channel=TOKEN_CHANNEL)
    assert response["actor"] == {"kind": "hil", "id": "operator"}
    assert response["body"] == {"request": request, "text": "Nejvýše 300 slov.", "channel": TOKEN_CHANNEL}
    assert open_requests(setup.ledger) == []


@pytest.mark.parametrize("channel", ["cli", "web", TOKEN_CHANNEL])
def test_an_r3_request_is_refused_on_every_channel(tmp_path, channel):
    setup, task, _ = waiting(tmp_path)
    request = r3_request(setup, task)
    for choice in ("send", "hold"):
        with pytest.raises(R3NeedsBoundIdentity):
            answer(setup.ledger, setup.runtime, request["id"], operator="operator", choice=choice, channel=channel)
    assert not any(e["body"]["request"] == request["id"] for e in setup.ledger.events(types=["HIL_RESPONSE"]))


def test_a_second_answer_and_a_late_answer_are_already_answered(tmp_path):
    setup, task, request = waiting(tmp_path)
    answer(setup.ledger, setup.runtime, request, operator="operator", choice="run_as_is", channel="web")
    with pytest.raises(AlreadyAnswered):
        answer(setup.ledger, setup.runtime, request, operator="second-operator", choice="do_not_run", channel="web")
    setup, task, request = waiting(tmp_path)
    setup.now = NOW + timedelta(hours=49)  # the default applies first
    with pytest.raises(AlreadyAnswered):
        answer(setup.ledger, setup.runtime, request, operator="operator", choice="run_as_is", channel="web")
    assert setup.last(task, "HIL_RESPONSE")["actor"]["id"] == "default-on-silence"


def test_mistakes_are_refused_before_anything_is_written(tmp_path):
    setup, task, request = waiting(tmp_path)
    with pytest.raises(UnknownRequest):
        answer(setup.ledger, setup.runtime, new_id("evt"), operator="operator", choice="clarify")
    with pytest.raises(ValueError, match="a choice, a text or both"):
        answer(setup.ledger, setup.runtime, request, operator="operator", text="  ")
    with pytest.raises(ValueError, match="reserved"):
        answer(setup.ledger, setup.runtime, request, operator="default-on-silence", choice="do_not_run")
    assert len(open_requests(setup.ledger)) == 1


def test_the_question_of_a_cancelled_task_is_neither_open_nor_answerable(tmp_path):
    setup, task, request = waiting(tmp_path)
    assert setup.runtime.cancel(task, operator="operator", channel="web")
    assert setup.runtime.run(task).state == "CANCELLED"
    assert open_requests(setup.ledger) == []
    with pytest.raises(TaskClosed):
        answer(setup.ledger, setup.runtime, request, operator="operator", choice="run_as_is")
    setup.now = NOW + timedelta(hours=49)
    assert setup.runtime.expire() == []  # no default is applied to a closed task


# Who may write a human event (design 05 §6) -------------------------------------------------------------------

HIL_ACTOR = re.compile(r"""["']kind["']\s*:\s*["']hil["']""")
# Runtime.submit, cancel and default-on-silence; rating; the answer path; connector state; operator tokens.
MAY_BUILD_A_HUMAN_ACTOR = {"runtime.py", "rating.py", "hil.py", "connector_admin.py", "tokens.py"}


def test_only_the_listed_modules_build_a_human_actor():
    source = Path(ooat_core.__file__).parent
    found = {path.relative_to(source).as_posix() for path in source.rglob("*.py")
             if HIL_ACTOR.search(path.read_text(encoding="utf-8"))}
    assert found <= MAY_BUILD_A_HUMAN_ACTOR, f"human actor outside the allow-list: {found - MAY_BUILD_A_HUMAN_ACTOR}"
    assert {"runtime.py", "rating.py", "hil.py", "connector_admin.py"} <= found  # the check finds what it guards


def test_no_answer_or_default_lands_on_a_closed_task_and_a_cancelled_question_is_gone(tmp_path):
    from ooat_core.validation import SpecValidationError

    setup, task, request = waiting(tmp_path)
    setup.runtime.cancel(task, operator="operator")
    assert open_requests(setup.ledger) == []  # cancelled: its question is no longer asked
    with pytest.raises(TaskClosed):
        answer(setup.ledger, setup.runtime, request, operator="operator", choice="run_as_is")
    setup.runtime.run(task)
    for actor, body in (({"kind": "hil", "id": "operator"}, {"request": request, "choice": "run_as_is"}),
                        ({"kind": "hil", "id": "default-on-silence"},
                         {"request": request, "choice": "do_not_run", "default_applied": True})):
        with pytest.raises(SpecValidationError, match="task is closed"):  # e.g. it closed after the caller read
            setup.ledger.append(new_event("HIL_RESPONSE", task=task, actor=actor, body=body))

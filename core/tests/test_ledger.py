import dataclasses

import pytest

from ooat_core.backends import LedgerIntegrityError
from ooat_core.ids import new_id
from ooat_core.ledger import DuplicateIntake, Ledger, StagedArtifact, _event_row, new_event
from ooat_core.validation import SpecValidationError

HIL = {"kind": "hil", "id": "operator"}


# Every ledger backend must pass this module. PostgreSQL and SQL Server URLs join this list (ADR 0008).
BACKEND_URLS = ["sqlite:///:memory:"]


@pytest.fixture(params=BACKEND_URLS)
def ledger(request):
    led = Ledger.open(request.param)
    yield led
    led.close()


def submitted(task):
    return new_event("TASK_SUBMITTED", task=task, actor=HIL, body={"goal": "Shrnout výroční zprávu."}, lang="cs")


def result(task, contract, refs):
    return new_event(
        "RESULT", task=task, contract=contract,
        actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
        body={"outcome": "DONE", "artifacts": list(refs)}, refs=refs,
        cost={"adapter": "prv.anthropic.subscription_cli", "tier": "workhorse", "quota_units": 1200,
              "usd": 0.05, "basis": "shadow"},
    )


def staged(ref):
    return StagedArtifact(ref=ref, type="summary", data_class="internal", untrusted=False,
                          sha256="0" * 64, uri="blob:" + "0" * 64)


def test_events_round_trip_in_append_order(ledger):
    task, ref = new_id("tsk"), new_id("art") + "@v1"
    appended = [ledger.append(submitted(task)), ledger.append(result(task, new_id("ctr"), [ref]), [staged(ref)])]
    ledger.append(submitted(new_id("tsk")))  # another task
    assert ledger.events(task=task) == appended
    assert ledger.events(types=["RESULT"]) == appended[1:]


def test_invalid_event_is_rejected_and_not_written(ledger):
    bad = submitted(new_id("tsk"))
    del bad["body"]["goal"]
    with pytest.raises(SpecValidationError, match="goal"):
        ledger.append(bad)
    assert ledger.events() == []


def test_artifact_is_recorded_with_its_event(ledger):
    ref = new_id("art") + "@v1"
    event = ledger.append(result(new_id("tsk"), new_id("ctr"), [ref]), [staged(ref)])
    record = ledger.artifact(ref)
    assert record["produced_by_event"] == event["id"]
    assert (record["version"], record["untrusted"], record["data_class"]) == (1, False, "internal")
    assert ledger.next_artifact_version(ref.split("@")[0]) == 2


def test_staged_artifact_must_be_referenced_by_its_event(ledger):
    ref, other = new_id("art") + "@v1", new_id("art") + "@v1"
    with pytest.raises(ValueError, match="referenced"):
        ledger.append(result(new_id("tsk"), new_id("ctr"), [other]), [staged(ref)])
    assert ledger.events() == []


def test_reference_to_an_unknown_artifact_is_rejected(ledger):
    ref = new_id("art") + "@v1"
    with pytest.raises(ValueError, match="unknown artifact"):
        ledger.append(result(new_id("tsk"), new_id("ctr"), [ref]))  # claims an output nobody stored
    assert ledger.events() == []


def test_reference_to_an_existing_artifact_needs_no_staging(ledger):
    task, ref = new_id("tsk"), new_id("art") + "@v1"
    ledger.append(result(task, new_id("ctr"), [ref]), [staged(ref)])
    ledger.append(result(task, new_id("ctr"), [ref]))
    assert len(ledger.events(task=task)) == 2


def test_non_finite_numbers_are_rejected(ledger):
    task, ref = new_id("tsk"), new_id("art") + "@v1"
    event = result(task, new_id("ctr"), [ref])
    event["cost"]["usd"] = float("nan")
    with pytest.raises(SpecValidationError, match="finite"):
        ledger.append(event, [staged(ref)])
    assert ledger.events() == []


def test_unknown_data_class_is_rejected_before_writing(ledger):
    ref = new_id("art") + "@v1"
    bad = dataclasses.replace(staged(ref), data_class="secret")
    with pytest.raises(ValueError, match="data class"):
        ledger.append(result(new_id("tsk"), new_id("ctr"), [ref]), [bad])
    assert ledger.events() == []


def test_backend_insert_is_atomic(ledger):
    orphan = {"id": new_id("art"), "version": 1, "type": "summary", "data_class": "public", "untrusted": 0,
              "sha256": "0" * 64, "uri": "blob:" + "0" * 64, "produced_by_event": new_id("evt")}
    with pytest.raises(LedgerIntegrityError):  # the event row is written first, then the orphan fails
        ledger.backend.insert(_event_row(submitted(new_id("tsk"))), [orphan])
    assert ledger.events() == []


def test_reopened_ledger_keeps_events_in_order(tmp_path):
    path, task = tmp_path / "ledger.sqlite", new_id("tsk")
    led = Ledger.open(f"sqlite:///{path}")
    appended = [led.append(submitted(task)) for _ in range(3)]
    led.close()
    led = Ledger.open(f"sqlite:///{path}")
    assert led.events(task=task) == appended
    led.close()


def test_unknown_or_planned_backends():
    with pytest.raises(ValueError):
        Ledger.open("oracle://db")
    with pytest.raises(ValueError):
        Ledger.open("ledger.sqlite")
    with pytest.raises(ValueError, match="path"):
        Ledger.open("sqlite://")  # would silently open a throwaway database
    for url in ("postgresql://host/ooat", "mssql://host/ooat"):
        with pytest.raises(NotImplementedError):
            Ledger.open(url)

    with pytest.raises(ValueError, match="query"):
        Ledger.open("sqlite:///ledger.sqlite?mode=ro")


def test_oversized_integers_are_rejected(ledger):
    ref = new_id("art") + "@v1"
    event = result(new_id("tsk"), new_id("ctr"), [ref])
    event["cost"]["tokens_in"] = 2**70
    with pytest.raises(SpecValidationError, match="tokens_in"):
        ledger.append(event, [staged(ref)])
    assert ledger.events() == []


def test_event_types_filter_must_not_be_a_string(ledger):
    with pytest.raises(TypeError):
        ledger.events(types="RESULT")


@pytest.mark.parametrize("field, value", [
    ("sha256", "not-a-digest"),
    ("uri", "file:///etc/passwd"),
    ("type", ""),
])
def test_malformed_staged_artifact_is_rejected(ledger, field, value):
    ref = new_id("art") + "@v1"
    bad = dataclasses.replace(staged(ref), **{field: value})
    with pytest.raises(ValueError):
        ledger.append(result(new_id("tsk"), new_id("ctr"), [ref]), [bad])
    assert ledger.events() == []


def test_artifact_version_gap_is_rejected(ledger):
    ref = new_id("art") + "@v7"
    with pytest.raises(ValueError, match="version"):
        ledger.append(result(new_id("tsk"), new_id("ctr"), [ref]), [staged(ref)])
    assert ledger.events() == []


def test_two_versions_of_one_artifact_in_one_event(ledger):
    art = new_id("art")
    refs = [f"{art}@v1", f"{art}@v2"]
    ledger.append(result(new_id("tsk"), new_id("ctr"), refs), [staged(r) for r in refs])
    assert ledger.next_artifact_version(art) == 3


SEND = {"id": "send", "label": "Odeslat", "cost_usd": 0.0, "acts": True}
HOLD = {"id": "hold", "label": "Neodesílat", "cost_usd": 0.0, "acts": False}


def hil_request(task, risk, default, options=(SEND, HOLD)):
    return new_event("HIL_REQUEST", task=task, actor={"kind": "system", "id": "ooat-core"}, body={
        "question": "Odeslat nabídku klientovi?", "risk_class": risk, "options": list(options),
        "recommended": options[0]["id"], "default_on_silence": default,
        "deadline": "2026-10-02T10:00:00Z", "blocking": True, "evidence": []})


def test_r3_request_must_default_to_not_acting(ledger):
    with pytest.raises(SpecValidationError, match="default_on_silence"):
        ledger.append(hil_request(new_id("tsk"), "R3", "send"))
    assert ledger.events() == []
    ledger.append(hil_request(new_id("tsk"), "R3", "hold"))


def test_request_must_name_its_own_options(ledger):
    with pytest.raises(SpecValidationError, match="default_on_silence"):
        ledger.append(hil_request(new_id("tsk"), "R1", "maybe"))
    bad = hil_request(new_id("tsk"), "R1", "hold")
    bad["body"]["recommended"] = "other"
    with pytest.raises(SpecValidationError, match="recommended"):
        ledger.append(bad)
    assert ledger.events() == []


def test_response_must_answer_an_open_request_of_its_task(ledger):
    task = new_id("tsk")
    request = ledger.append(hil_request(task, "R1", "hold"))

    def response(request_id, choice, on_task=task):
        return new_event("HIL_RESPONSE", task=on_task, actor=HIL, body={"request": request_id, "choice": choice})

    with pytest.raises(SpecValidationError, match="request"):
        ledger.append(response(new_id("evt"), "send"))
    with pytest.raises(SpecValidationError, match="request"):
        ledger.append(response(request["id"], "send", on_task=new_id("tsk")))
    with pytest.raises(SpecValidationError, match="choice"):
        ledger.append(response(request["id"], "maybe"))
    ledger.append(response(request["id"], "hold"))
    assert [e["type"] for e in ledger.events(task=task)] == ["HIL_REQUEST", "HIL_RESPONSE"]


def test_default_applied_response_must_record_the_requests_default(ledger):
    task = new_id("tsk")
    request = ledger.append(hil_request(task, "R3", "hold"))
    forged = new_event("HIL_RESPONSE", task=task, actor=HIL,
                       body={"request": request["id"], "choice": "send", "default_applied": True})
    with pytest.raises(SpecValidationError, match="default"):
        ledger.append(forged)
    ledger.append(new_event("HIL_RESPONSE", task=task, actor=HIL,
                            body={"request": request["id"], "choice": "hold", "default_applied": True}))


def test_request_is_answered_only_once(ledger):
    task = new_id("tsk")
    request = ledger.append(hil_request(task, "R1", "hold"))
    answer = {"request": request["id"], "choice": "hold"}
    ledger.append(new_event("HIL_RESPONSE", task=task, actor=HIL, body=answer))
    with pytest.raises(SpecValidationError, match="already answered"):
        ledger.append(new_event("HIL_RESPONSE", task=task, actor=HIL, body={**answer, "choice": "send"}))


def test_database_rejects_a_second_response_even_past_the_ledger_check(ledger):
    # Two processes can both pass Ledger's "already answered" check; the backend must still refuse the second.
    task = new_id("tsk")
    request = ledger.append(hil_request(task, "R3", "hold"))
    first = new_event("HIL_RESPONSE", task=task, actor=HIL, body={"request": request["id"], "choice": "send"})
    second = new_event("HIL_RESPONSE", task=task, actor=HIL, body={"request": request["id"], "choice": "hold"})
    ledger.backend.insert(_event_row(first), [])
    with pytest.raises(LedgerIntegrityError):
        ledger.backend.insert(_event_row(second), [])
    assert [e["id"] for e in ledger.events(types=["HIL_RESPONSE"])] == [first["id"]]


def test_r3_response_needs_an_explicit_choice(ledger):
    task = new_id("tsk")
    request = ledger.append(hil_request(task, "R3", "hold"))
    with pytest.raises(SpecValidationError, match="choice"):
        ledger.append(new_event("HIL_RESPONSE", task=task, actor=HIL,
                                body={"request": request["id"], "text": "Asi ano."}))


def submission(key, channel="web"):
    return new_event("TASK_SUBMITTED", task=new_id("tsk"), actor=HIL,
                     body={"goal": "Shrnout výroční zprávu.", "channel": channel, "intake_key": key})


def test_a_repeated_intake_key_on_its_channel_is_refused_and_names_the_first_task(ledger):
    first = ledger.append(submission("msg-7"))
    with pytest.raises(DuplicateIntake) as refused:
        ledger.append(submission("msg-7"))
    assert refused.value.task == first["task"]
    assert len(ledger.events(types=["TASK_SUBMITTED"])) == 1


def test_the_same_intake_key_on_another_channel_is_another_task(ledger):
    ledger.append(submission("msg-7"))
    ledger.append(submission("msg-7", channel="token:" + new_id("tok")))
    ledger.append(new_event("TASK_SUBMITTED", task=new_id("tsk"), actor=HIL, body={"goal": "Bez klíče."}))
    assert len(ledger.events(types=["TASK_SUBMITTED"])) == 3


def test_a_refused_event_inside_the_transaction_leaves_the_ledger_writable(ledger):
    task = new_id("tsk")
    request = ledger.append(hil_request(task, "R1", "hold"))
    answer = new_event("HIL_RESPONSE", task=task, actor=HIL, body={"request": request["id"], "choice": "maybe"})
    with pytest.raises(SpecValidationError):
        ledger.append(answer)  # refused inside the write transaction, which must be rolled back
    ledger.append(new_event("HIL_RESPONSE", task=task, actor=HIL, body={"request": request["id"], "choice": "hold"}))
    assert len(ledger.events(task=task)) == 2

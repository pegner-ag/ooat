import pytest

from ooat_core.backends import LedgerIntegrityError
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger, StagedArtifact, new_event
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


def test_event_and_artifacts_are_written_atomically(ledger):
    task, contract, ref = new_id("tsk"), new_id("ctr"), new_id("art") + "@v1"
    first = ledger.append(result(task, contract, [ref]), [staged(ref)])
    with pytest.raises(LedgerIntegrityError):  # the same artifact version again
        ledger.append(result(task, contract, [ref]), [staged(ref)])
    assert [e["id"] for e in ledger.events()] == [first["id"]]


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

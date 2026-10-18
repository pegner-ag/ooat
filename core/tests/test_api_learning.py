"""What it learns in the REST API (plan 09 task 5): counts for every reader, ids and notes only within the cap."""

from api_fakes import Served

from ooat_core.ids import new_id
from ooat_core.ledger import new_event
from ooat_core.rating import rate

HIL = {"kind": "hil", "id": "operator"}
SYSTEM = {"kind": "system", "id": "ooat-gate"}
KEYS = {"price_list", "thresholds", "reception", "memory", "attention"}


def rejected(served, data_class):
    """A task that ran one contract, closed done, rated rejected."""
    task, ctr = new_id("tsk"), new_id("ctr")
    with served.ledger() as ledger:
        ledger.append(new_event("TASK_SUBMITTED", task=task, actor=HIL, body={
            "goal": "Shrň smlouvu.", "project": "docs", "data_class": data_class}))
        ledger.append(new_event("CONTRACT_ISSUED", task=task, contract=ctr, actor=SYSTEM, body={"contract": {
            "id": ctr, "task": task, "capability": "cap.general.complete_task", "capability_version": "0.1.0",
            "agent": new_id("agt"), "role": "role.general.worker@0.1.0", "goal": "x", "inputs": [],
            "output_schema": "schemas/markdown_document.v1.json", "budget": {"max_usd": 5.0}}}))
        ledger.append(new_event("TASK_CLOSED", task=task, actor=SYSTEM, body={
            "state": "CLOSED_DONE", "summary": "x", "cost": {"contracts_usd": 0.0, "gate_usd": 0.0,
                                                           "orchestrator_usd": 0.0, "critic_usd": 0.0}}))
        rate(ledger, task, operator="operator", accepted=False, value_class="B", note="Moc dlouhé.")
    return task


def test_a_web_session_reads_what_it_learns(tmp_path):
    s = Served(tmp_path)
    task = rejected(s, "internal")
    found = s.client.get("/api/v1/learning", headers=s.login())
    assert found.status_code == 200, found.text
    body = found.json()
    assert set(body) == KEYS and body["attention"][0] == {"task": task, "state": "CLOSED_DONE", "why": "rejected",
                                                           "note": "Moc dlouhé."}


def test_a_token_without_read_is_refused(tmp_path):
    s = Served(tmp_path)
    assert s.client.get("/api/v1/learning", headers=s.token(scopes=("submit",))).status_code == 403


def test_an_internal_token_counts_a_personal_task_but_never_names_it(tmp_path):
    s = Served(tmp_path)
    rejected(s, "personal")
    body = s.client.get("/api/v1/learning", headers=s.token(cap="internal")).json()
    assert body["price_list"][0]["n"] == 1 and body["attention"] == []

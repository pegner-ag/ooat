"""Usage figures from the ledger (design 05 §8)."""

from datetime import datetime, timedelta, timezone

import pytest
from test_runtime import Setup

from ooat_core.ids import new_id
from ooat_core.rating import rate
from ooat_core.stats import role_of, usage

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def at(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def call(task, minutes_ago, usd, basis="exact", adapter="prv.fake.api", tier="workhorse", actor=None, body=None):
    return {"id": new_id("evt"), "ts": at(minutes_ago), "task": task, "type": "RESULT", "refs": [],
            "actor": actor or {"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
            "body": body or {"outcome": "DONE"},
            "cost": {"adapter": adapter, "tier": tier, "tokens_in": 1000, "tokens_out": 200, "usd": usd,
                     "basis": basis}}


def submitted(task, project, minutes_ago=60):
    return {"id": new_id("evt"), "ts": at(minutes_ago), "task": task, "type": "TASK_SUBMITTED", "refs": [],
            "actor": {"kind": "hil", "id": "operator"}, "body": {"goal": "x", "project": project}}


def test_cost_is_split_into_metered_and_subscription_shadow_by_connector():
    task = new_id("tsk")
    events = [submitted(task, "docs"), call(task, 30, 0.40, adapter="prv.anthropic.api"),
              call(task, 20, 2.70, basis="shadow", adapter="prv.anthropic.subscription_cli"),
              call(task, 10, 0.05, basis="estimated", adapter="prv.anthropic.api")]
    figures = usage(events, now=NOW, group="connector")
    assert figures["spend"] == {"metered_usd": pytest.approx(0.45), "shadow_usd": pytest.approx(2.70)}
    assert [(r["key"], r["calls"], r["tokens_in"]) for r in figures["groups"]] == [
        ("prv.anthropic.subscription_cli", 1, 1000), ("prv.anthropic.api", 2, 2000)]


def test_the_period_and_the_project_filter_the_events():
    one, two = new_id("tsk"), new_id("tsk")
    events = [submitted(one, "docs", 60 * 24 * 10), call(one, 60 * 24 * 9, 1.0),
              submitted(two, "sales"), call(two, 5, 0.5)]
    assert usage(events, now=NOW, period="7d")["spend"]["metered_usd"] == 0.5
    assert usage(events, now=NOW, period="30d")["spend"]["metered_usd"] == 1.5
    assert usage(events, now=NOW, period="all", project="docs")["spend"]["metered_usd"] == 1.0
    with pytest.raises(ValueError, match="period"):
        usage(events, now=NOW, period="week")


def test_a_project_is_named_only_when_one_of_its_tasks_is_within_the_readers_cap():
    secret, shared, other = new_id("tsk"), new_id("tsk"), new_id("tsk")
    events = [submitted(secret, "client-x"), call(secret, 5, 1.0), submitted(shared, "docs"), call(shared, 5, 0.5),
              submitted(other, "docs"), call(other, 5, 0.25)]
    figures = usage(events, now=NOW, group="project", above_cap=frozenset({secret, other}))
    assert {r["key"]: r["metered_usd"] for r in figures["groups"]} == {"(other)": 1.0, "docs": 0.75}


def test_hil_waiting_time_is_the_median_of_human_answers_and_defaults_are_counted():
    task = new_id("tsk")
    requests = [{"id": new_id("evt"), "ts": at(m), "task": task, "type": "HIL_REQUEST", "refs": [],
                 "actor": {"kind": "system", "id": "ooat-gate"}, "body": {}} for m in (100, 90, 80)]
    answers = [{"id": new_id("evt"), "ts": at(m), "task": task, "type": "HIL_RESPONSE", "refs": [],
                "actor": {"kind": "hil", "id": who}, "body": {"request": r["id"], **extra}}
               for r, m, who, extra in ((requests[0], 90, "operator", {}), (requests[1], 60, "operator", {}),
                                        (requests[2], 0, "default-on-silence", {"default_applied": True}))]
    figures = usage(requests + answers, now=NOW)["hil"]
    assert figures == {"questions": 3, "answered": 2, "defaults_applied": 1, "median_wait_minutes": 20.0}


def test_a_real_task_shows_the_worker_the_gate_and_the_checks_and_its_cost_per_accepted_task(tmp_path):
    setup = Setup(tmp_path)
    setup.now = datetime.now(timezone.utc)  # the ledger stamps the real time
    task = setup.submit(project="docs")
    setup.runtime.run(task)
    rate(setup.ledger, task, operator="operator", accepted=True, value_class="B")
    events = setup.ledger.events()
    figures = usage(events, now=setup.now + timedelta(minutes=1), group="role")
    assert {r["key"] for r in figures["groups"]} == {"role.general.worker", "gate", "acceptance"}
    closed = setup.last(task, "TASK_CLOSED")["body"]["cost"]
    assert figures["tasks"]["closed"] == figures["tasks"]["accepted"] == 1
    assert figures["tasks"]["cost_per_accepted_usd"] == pytest.approx(sum(closed.values()))
    assert figures["tasks"]["estimate_vs_actual"] is not None
    assert role_of({"actor": {"kind": "system", "id": "ooat-runtime"},
                    "body": {"gate": "gate.critic.check_criterion"}}) == "critic"

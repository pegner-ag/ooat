"""Contract costs observed in the ledger, and the prior before enough runs exist (plan 04d, spec §11)."""

import pytest

from ooat_core.estimate import MIN_RUNS, Priors, contract_costs, percentile, prior_usd
from ooat_core.ids import new_id

CC = "prv.anthropic.subscription_cli"


def contract(usd_parts, adapter=CC, tier="workhorse", closed=True, price_ver="0.1.0"):
    task, ctr = new_id("tsk"), new_id("ctr")
    events = []
    for kind, usd in usd_parts:
        events.append({"type": kind, "task": task, "contract": ctr, "body": {"outcome": "DONE"},
                       "actor": {"kind": "agent" if kind == "RESULT" else "system"},
                       "cost": {"adapter": adapter, "tier": tier, "usd": usd, "basis": "shadow",
                                "price_ver": price_ver}})
    if closed:
        events.append({"type": "TASK_CLOSED", "task": task, "body": {}})
    return events


def test_each_closed_contract_costs_the_sum_of_its_calls():
    events = contract([("RESULT", 0.20), ("GATE_FAILED", 0.0003), ("GATE_PASSED", 0.03)])
    assert contract_costs(events, CC, "workhorse") == [pytest.approx(0.2303)]


def test_failed_calls_count_with_their_charged_cost():
    events = contract([("RESULT", 0.10), ("RESULT", 0.10)])
    events[1]["body"]["outcome"] = "FAILED"
    events[1]["cost"] = {"adapter": CC, "tier": "workhorse", "usd": 0.04, "basis": "estimated", "price_ver": "0.1.0"}
    assert contract_costs(events, CC, "workhorse") == [pytest.approx(0.14)]


def test_an_abstained_run_counts_with_its_cost():
    events = contract([("ABSTAIN", 0.05)])
    assert contract_costs(events, CC, "workhorse") == [pytest.approx(0.05)]


def test_a_run_belongs_to_the_adapter_of_its_first_worker_call():
    events = contract([("RESULT", 0.10)], adapter="prv.openai.subscription_cli")
    events.insert(1, {**events[0], "type": "RESULT",
                      "cost": {**events[0]["cost"], "adapter": CC, "usd": 0.20}})  # a later attempt elsewhere
    assert contract_costs(events, "prv.openai.subscription_cli", "workhorse") == [pytest.approx(0.30)]
    assert contract_costs(events, CC, "workhorse") == []


def test_open_contracts_do_not_count():
    assert contract_costs(contract([("RESULT", 0.2)], closed=False), CC, "workhorse") == []


def test_runs_of_another_adapter_do_not_count():
    events = [e for _ in range(6) for e in contract([("RESULT", 0.5)], adapter="prv.openai.subscription_cli")]
    assert contract_costs(events, CC, "workhorse") == []


def test_only_the_last_fifty_runs_and_the_current_price_version_count():
    old = [e for _ in range(3) for e in contract([("RESULT", 9.0)], price_ver="0.0.9")]
    recent = [e for i in range(55) for e in contract([("RESULT", 0.01 * (i + 1))])]
    costs = contract_costs(old + recent, CC, "workhorse")
    assert len(costs) == 50 and min(costs) == pytest.approx(0.06) and max(costs) == pytest.approx(0.55)


def test_percentiles_use_the_nearest_rank():
    values = [0.0031, 0.0579, 0.0858, 0.2375, 0.4689, 0.5074]
    assert percentile(values, 0.5) == 0.0858 and percentile(values, 0.9) == 0.5074
    assert MIN_RUNS == 5


def test_the_prior_adds_the_critic_by_its_share_and_scales_by_the_retry_prior():
    priors = Priors(2000, 400, 500, retry_prior=0.25, critic_prior=0.5)
    assert prior_usd(0.10, 0.01, 0.04, priors, critic_certain=False) == pytest.approx((0.11 + 0.02) * 1.25)
    assert prior_usd(0.10, 0.01, 0.04, priors, critic_certain=True) == pytest.approx((0.11 + 0.04) * 1.25)


def test_a_run_without_a_price_version_never_drops_versioned_history():
    versioned = [e for _ in range(5) for e in contract([("RESULT", 0.2)])]
    unversioned = contract([("RESULT", 0.3)], price_ver=None)
    assert len(contract_costs(versioned + unversioned, CC, "workhorse")) == 6


def test_a_contract_without_a_costed_worker_call_is_not_a_run():
    events = contract([("GATE_PASSED", 0.01)])  # e.g. refused before the worker ran
    assert contract_costs(events, CC, "workhorse") == []

# Pre-start Estimate from Observed Runs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Gate's pre-start estimate follows spec §11: the cost of a contract is the p50 and p90 of the last 50
closed contracts on the worker's adapter; until five exist, a prior that counts the worker's attachments, the
critic and a second attempt.

**Architecture:** A pure module `estimate.py` sums the cost of each closed contract from the ledger (worker,
decision checks, critic, failed calls) and returns p50 / p90 per worker adapter. The Gate uses p50 as
`candidates[].model_usd` and for the value check, and p90 for the budget check, so a task is asked about its budget
before it runs rather than paused in the middle. Before five runs on the adapter the Gate prices one attempt from
priors and scales it by a retry prior. Owner decision 2026-10-09: option A (spec §11 as written).

**Tech Stack:** Python 3.12+, pytest; no new dependencies.

**Spec:** spec §11 "Price-list calibration" ("Cost: p50 and p90 over the last 50 runs, per adapter; history is
split when the model behind a tier changes"); spec §4 step B (priors in configuration); design 04 §4 (estimate,
budget and value checks), §5 (worker, acceptance, critic, two attempts); 03d item "The pre-start estimate ignores
attachments, the critic and a second attempt".

## Evidence (ledger of the working folder, 2026-10-09)

Closed contracts on `prv.anthropic.subscription_cli`, cost of worker + checks + critic per contract (USD), against
the Gate's estimate at the time:

| contract | task | estimate | actual |
|---|---|---|---|
| smoke test | summary | 0.020 | 0.0031 |
| s1 | ISO week | 0.021 | 0.0579 |
| s5 | variable symbol | 0.024 | 0.0858 |
| s2 | .resx checker | 0.021 | 0.2375 |
| s4 | planner tests | 0.021 | 0.4689 |
| s3 | export tests | 0.024 | 0.5074 |

p50 (nearest rank) = 0.0858, p90 = 0.5074. With them every contract's actual is at most p90, against today's
estimates 2.8 to 22 times too low. The prior path still matters for a new adapter or a fresh ledger.

## Global Constraints

- Only `ooat-core` writes to the ledger; `estimate.py` only reads events. Nothing is stored: `cost_card.observed`
  stays unwritten here (spec: written only by the runtime), the values are computed on each Gate run.
- Priors live in `GateSettings` (`ooat.toml [gate]`); a rate prior is a number from 0 to 1, a token prior a positive
  integer, both checked when the config is read.
- History is split per adapter and tier. The ledger's cost record has no model id yet, so "split when the model
  behind a tier changes" is approximated by the price version (`cost.price_ver`). `price_ver` is the version of the
  whole `routing.json`, so any price edit resets every adapter's history to the prior; record both limits in
  design 04 and the model id in 03d.
- No schema change; the estimate stays `candidates[].model_usd` (p50).
- English for code, docs and commits.

## Review Focus

1. A contract whose failed calls carry only an estimated cost → it still counts with that cost, nothing crashes
   (Task 1 test `test_failed_calls_count_with_their_charged_cost`).
2. Fewer than five runs on the routed adapter, but many on another → the prior applies; runs of another adapter
   never set this one's estimate (Task 1 test `test_runs_of_another_adapter_do_not_count`).
3. A fresh ledger → the prior estimate is never below today's formula, computed independently; without a decision
   route the critic counts in full (Task 2 tests `test_without_observations_the_estimate_is_never_below_the_old_one`,
   `test_without_a_decision_route_the_critic_is_certain`).
4. An attachment larger than the worker's 100,000-character cap counts only up to the cap (Task 2 test
   `test_an_attachment_counts_only_what_the_worker_receives`).
5. p90 above the budget, p50 below it → the budget question comes before the run, and its raise covers p90
   (Task 2 test `test_the_budget_check_uses_p90`).

---

### Task 1: Observed contract costs (`estimate.py`)

**Files:**
- Create: `core/src/ooat_core/estimate.py`
- Test: `core/tests/test_estimate.py`

**Interfaces:**
- Produces: `MIN_RUNS = 5`, `RUNS = 50`; `contract_costs(events: list[dict], adapter: str, tier: str) -> list[float]`
  (oldest first); `percentile(values: list[float], q: float) -> float` (nearest rank);
  `Priors(output_tokens: int, critic_output_tokens: int, fallback_tokens_per_question: int, retry_prior: float,
  critic_prior: float)`; `prior_usd(worker_usd: float, checks_usd: float, critic_usd: float, priors: Priors,
  critic_certain: bool) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
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
    ctr = events[0]["contract"]
    events.insert(1, {**events[0], "type": "RESULT",
                      "cost": {**events[0]["cost"], "adapter": CC, "usd": 0.20}})  # a later attempt elsewhere
    assert contract_costs(events, "prv.openai.subscription_cli", "workhorse") == [pytest.approx(0.30)]
    assert contract_costs(events, CC, "workhorse") == [] and ctr


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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest core/tests/test_estimate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ooat_core.estimate'`

- [ ] **Step 3: Implement**

```python
"""The cost of a contract as spec §11 measures it, and the prior used before enough runs exist (plan 04d).

Spec §11: "Cost: p50 and p90 over the last 50 runs, per adapter; history is split when the model behind a tier
changes." A run is a closed contract; its cost is every call charged to it (worker, decision checks, critic,
failed calls at their charged estimate). The ledger's cost records carry no model id, so a change of the price
version stands in for a model change.
"""

import math
from dataclasses import dataclass

MIN_RUNS = 5
RUNS = 50


def contract_costs(events: list[dict], adapter: str, tier: str) -> list[float]:
    """Cost of each closed contract whose worker ran on `adapter` at `tier`, oldest first, last RUNS only, all on
    the price version of the most recent one."""
    closed = {e["task"] for e in events if e["type"] == "TASK_CLOSED"}
    runs: dict[str, dict] = {}
    for event in events:
        ctr, cost = event.get("contract"), event.get("cost")
        if not ctr or not cost or event.get("task") not in closed:
            continue
        run = runs.setdefault(ctr, {"usd": 0.0, "worker": None})
        run["usd"] += cost.get("usd", 0.0)
        # the run belongs to the adapter of its first worker call (a RESULT or an ABSTAIN with a cost)
        if event["type"] in ("RESULT", "ABSTAIN") and run["worker"] is None:
            run["worker"] = (cost.get("adapter"), cost.get("tier"), cost.get("price_ver"))
    mine = [r for r in runs.values() if r["worker"] and r["worker"][:2] == (adapter, tier)]
    if not mine:
        return []
    current = mine[-1]["worker"][2]
    return [r["usd"] for r in mine if r["worker"][2] == current][-RUNS:]


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile: the smallest value with at least q of the values at or below it."""
    ordered = sorted(values)
    return ordered[max(math.ceil(q * len(ordered)), 1) - 1]


@dataclass(frozen=True)
class Priors:
    output_tokens: int  # the worker's deliverable
    critic_output_tokens: int
    fallback_tokens_per_question: int  # a text-model decision; the CLI does not enforce max_output_tokens
    retry_prior: float  # share of contracts needing a second attempt
    critic_prior: float  # share of contracts in which the critic runs


def prior_usd(worker_usd: float, checks_usd: float, critic_usd: float, priors: Priors, critic_certain: bool) -> float:
    """One attempt (worker, decision checks, the critic by its share) times the expected attempts. The critic is
    certain with an untrusted attachment, or when no decision route can check the criteria."""
    share = 1.0 if critic_certain else priors.critic_prior
    return (worker_usd + checks_usd + share * critic_usd) * (1 + priors.retry_prior)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest core/tests/test_estimate.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/estimate.py core/tests/test_estimate.py
git commit -m "feat(core): contract cost p50/p90 per adapter from the ledger, and the prior (plan 04d)"
```

---

### Task 2: The Gate estimates p50 / p90 and checks the budget against p90

**Files:**
- Modify: `core/src/ooat_core/gate.py` (`GateSettings`, `GateOutcome`, `Gate.__init__`, `Gate._estimate`, the
  budget check and question in `Gate.run`)
- Modify: `core/src/ooat_core/gateway.py` (`estimate_decision`)
- Modify: `core/src/ooat_core/config.py` (the four new `[gate]` keys with range checks)
- Modify: `core/src/ooat_core/runtime.py` (`Gate(...)` construction)
- Test: `core/tests/test_gate.py`, `core/tests/test_gateway_decide.py`, `core/tests/test_config.py`

**Interfaces:**
- Consumes: Task 1; `PREVIEW_CHARS`, `worker_system` from `worker.py`; `CRITIC_TIER`, `CRITIC_SYSTEM` from
  `acceptance.py`.
- Produces: `GateSettings.critic_output_tokens: int = 400`, `fallback_tokens_per_question: int = 500`,
  `retry_prior: float = 0.25`, `critic_prior: float = 0.5`; `GateOutcome.estimate_p90_usd: float | None = None`;
  `Gate(ledger, gateway, settings, clock, attachment_chars: Callable[[list[str]], int] | None = None)`;
  `Gate._estimate(task, state, criteria, data_class, narrowings=0, refs=()) -> tuple[float, float]` (p50, p90);
  `Gateway.estimate_decision(request, fallback_output_tokens: int | None = None) -> Estimate`.

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_gate.py` give `GateSetup.__init__` a keyword `attachment_chars=None`, pass it on
(`Gate(self.ledger, self.gateway, settings, clock=lambda: NOW, attachment_chars=attachment_chars)`), and add:

```python
    def submit_with_attachment(self, **extra):
        task = new_id("tsk")
        body = {"goal": "Shrň přiloženou smlouvu.", "acceptance": ["Shrnutí má nejvýše 300 slov."], **extra}
        self.ledger.append(new_event("TASK_SUBMITTED", task=task, actor=HIL, body=body,
                                     refs=["art_01J9ZQ6X9EK3M5N7P9Q1R3S5T7@v1"]))
        return task

    def closed_run(self, usd, adapter="prv.fake.api"):
        """A closed contract of `usd` on the worker's adapter, as the runtime would leave it in the ledger."""
        task, ctr = new_id("tsk"), new_id("ctr")
        self.ledger.append(new_event("TASK_SUBMITTED", task=task, actor=HIL, body={"goal": "x"}))
        self.ledger.append(new_event("CONTRACT_ISSUED", task=task, contract=ctr, actor=GATE, body={"contract": {
            "id": ctr, "task": task, "capability": "cap.general.complete_task", "capability_version": "0.1.0",
            "agent": new_id("agt"), "role": "role.general.worker@0.1.0", "goal": "x", "inputs": [],
            "output_schema": "schemas/markdown_document.v1.json", "acceptance": [], "budget": {"max_usd": 5.0},
            "deadline": "2026-10-03T12:00:00Z"}}))
        self.ledger.append(new_event("RESULT", task=task, contract=ctr,
                                     actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
                                     body={"outcome": "DONE", "artifacts": []},
                                     cost={"adapter": adapter, "tier": "workhorse", "tokens_in": 1, "tokens_cached": 0,
                                           "tokens_out": 1, "usd": usd, "basis": "exact", "price_ver": "0.1.0",
                                           "estimated_usd": usd}))
        self.ledger.append(new_event("TASK_CLOSED", task=task, actor=GATE, body={
            "state": "CLOSED_DONE", "summary": "x", "cost": {"contracts_usd": usd, "gate_usd": 0.0,
                                                             "orchestrator_usd": 0.0, "critic_usd": 0.0}}))
```

(If the ledger refuses one of these events, copy the event shapes from `core/tests/test_runtime.py`, where the
runtime writes them, and record the change as a ruling. If the attachment ref needs an artifact row, stage one
through an `ArtifactStore` as that file does.)

Append the tests:

```python
# Estimate from observed runs (plan 04d) ----------------------------------------------------------------------

from ooat_core.connectors import ModelRequest as _ModelRequest


def candidate_usd(setup, task):
    setup.gate.run(task)
    decided = setup.events(task, "TOPOLOGY_DECIDED")[-1]
    return next(c["model_usd"] for c in decided["body"]["candidates"] if "model_usd" in c)


def old_formula(setup, task, routed=True):
    """Today's estimate without the new code: the worker at 2,000 output tokens, plus the decision checks (about
    nothing on the fake engine), or plus the worker again when no decision route exists."""
    state = task_facts(setup.ledger.events(task=task)).state
    worker = setup.gateway.estimate(_ModelRequest(tier="workhorse", prompt=state, data_class="internal",
                                                  expected_output_tokens=2000, task=task)).usd
    return worker + (0.0 if routed else worker)


def test_without_observations_the_estimate_is_never_below_the_old_one():
    setup = GateSetup()
    task = setup.submit()
    assert candidate_usd(setup, task) >= old_formula(setup, task)


def test_without_a_decision_route_the_critic_is_certain(monkeypatch):
    routed, unrouted = GateSetup(), GateSetup()

    def no_route(*args, **kwargs):
        raise GatewayError("NOT_PERMITTED", "no decision route in this test")
    monkeypatch.setattr(unrouted.gateway, "estimate_decision", no_route)
    assert candidate_usd(unrouted, unrouted.submit()) > candidate_usd(routed, routed.submit())


def test_narrowing_scales_the_observed_estimate():
    setup = GateSetup()
    for usd in (0.10, 0.20, 0.30, 0.40, 0.50):
        setup.closed_run(usd)
    task = setup.submit(budget_usd=0.01)
    first = setup.gate.run(task)
    answer(setup, task, first.request, choice="narrow_scope", text="Jen první kapitola smlouvy.")
    second = setup.gate.run(task)
    assert second.estimate_usd == pytest.approx(first.estimate_usd / 2)


def test_narrowing_still_lowers_the_prior_estimate():
    setup = GateSetup()
    task = setup.submit(budget_usd=0.001)
    first = setup.gate.run(task)
    answer(setup, task, first.request, choice="narrow_scope", text="Jen první kapitola smlouvy.")
    second = setup.gate.run(task)
    assert second.estimate_usd < first.estimate_usd * 0.75


def test_an_untrusted_attachment_always_counts_the_critic():
    plain = GateSetup()
    attached = GateSetup(attachment_chars=lambda refs: 4_000 if refs else 0)
    assert candidate_usd(attached, attached.submit_with_attachment()) > candidate_usd(plain, plain.submit())


def test_an_attachment_counts_only_what_the_worker_receives():
    capped = GateSetup(attachment_chars=lambda refs: 100_000)
    huge = GateSetup(attachment_chars=lambda refs: 5_000_000)
    assert candidate_usd(huge, huge.submit_with_attachment()) == \
        pytest.approx(candidate_usd(capped, capped.submit_with_attachment()))


def test_four_runs_keep_the_prior_and_the_fifth_switches_to_observation():
    setup = GateSetup()
    for usd in (0.10, 0.20, 0.30, 0.40):
        setup.closed_run(usd)
    prior = candidate_usd(setup, setup.submit())
    setup.closed_run(0.50)
    assert prior != pytest.approx(0.30) and candidate_usd(setup, setup.submit()) == pytest.approx(0.30)


def test_from_five_runs_the_estimate_is_the_observed_p50():
    setup = GateSetup()
    for usd in (0.003, 0.058, 0.086, 0.238, 0.469, 0.507):
        setup.closed_run(usd)
    assert candidate_usd(setup, setup.submit()) == pytest.approx(0.086)


def test_the_budget_check_uses_p90():
    setup = GateSetup()
    for usd in (0.003, 0.058, 0.086, 0.238, 0.469, 0.507):
        setup.closed_run(usd)
    task = setup.submit(budget_usd=0.30)  # above p50, below p90
    outcome = setup.gate.run(task)
    assert outcome.action == "ask" and outcome.estimate_p90_usd == pytest.approx(0.507)
    raise_to = next(o for o in setup.events(task, "HIL_REQUEST")[0]["body"]["options"] if o["id"] == "raise_budget")
    assert raise_to["cost_usd"] >= 0.507
```

(`answer`, `task_facts`, `GateSettings`, `GatewayError`, `new_event`, `new_id`, `HIL`, `GATE`, `pytest` exist in
the file; add any that is missing. `GATE` is the Gate's actor dict used elsewhere in the tests.)

Append to `core/tests/test_gateway_decide.py` (its `Setup` and `economy()` exist):

```python
def test_a_fallback_decision_can_be_priced_at_its_observed_output():
    setup = Setup(economy())  # no decision connector: the economy text tier answers
    small = setup.gateway.estimate_decision(setup.request()).usd
    large = setup.gateway.estimate_decision(setup.request(), fallback_output_tokens=4000).usd
    assert large > small
```

Append to `core/tests/test_config.py` (use the file's way of parsing a TOML string; `parse_config` takes a dict):

```python
@pytest.mark.parametrize("gate, ok", [
    ({"retry_prior": 0.4, "critic_prior": 0, "critic_output_tokens": 300, "fallback_tokens_per_question": 600}, True),
    ({"retry_prior": 1.5}, False), ({"critic_prior": -0.1}, False), ({"critic_output_tokens": 0}, False),
    ({"fallback_tokens_per_question": 2.5}, False),
])
def test_estimate_priors_in_gate_are_range_checked(gate, ok):
    from ooat_core.gate import settings_from_config
    if ok:
        settings = settings_from_config(parse_config({"gate": gate}))
        assert settings.retry_prior == 0.4 and settings.critic_prior == 0
    else:
        with pytest.raises(ValueError):
            parse_config({"gate": gate})
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest core/tests/test_gate.py core/tests/test_gateway_decide.py core/tests/test_config.py -q`
Expected: the new tests FAIL (`attachment_chars`, `estimate_p90_usd`, `fallback_output_tokens` do not exist; the
new `[gate]` keys are refused as unknown).

- [ ] **Step 3: Implement**

`gateway.py`:

```python
    def estimate_decision(self, request: DecisionRequest, fallback_output_tokens: int | None = None) -> Estimate:
        """Expected cost of the decision on the engine decide() would use; no provider call. A text-model
        fallback is priced at `fallback_output_tokens` when the caller knows them (the CLI ignores the cap)."""
        check_questions(request.questions)
        expanded = self._expanded(request)
        try:
            return self._route(expanded, kind="decision").estimate
        except GatewayError:
            fallback = self._fallback_request(expanded)
            if fallback_output_tokens is not None:
                fallback = dataclasses.replace(fallback, expected_output_tokens=fallback_output_tokens)
            return self.estimate(fallback)
```

`config.py`: accept `critic_output_tokens`, `fallback_tokens_per_question` (positive integers, not bool) and
`retry_prior`, `critic_prior` (numbers from 0 to 1) in `[gate]`; refuse other values with a `ValueError` naming the
key.

`gate.py`, `GateSettings` (priors, not measurements):

```python
    critic_output_tokens: int = 400  # prior for the critic's JSON verdict
    fallback_tokens_per_question: int = 500  # prior for a text-model decision answer
    retry_prior: float = 0.25  # share of contracts needing a second attempt, until measured
    critic_prior: float = 0.5  # share of contracts in which the critic runs, until measured
```

`gate.py`, `GateOutcome`: add `estimate_p90_usd: float | None = None`, and set it wherever `estimate_usd` is set.

`gate.py`, the Gate:

```python
    def __init__(self, ledger: Ledger, gateway: Gateway, settings: GateSettings = GateSettings(),
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 attachment_chars: Callable[[list[str]], int] | None = None):
        self._ledger, self._gateway, self._settings, self._clock = ledger, gateway, settings, clock
        self._attachment_chars = attachment_chars or (lambda refs: 0)

    def _estimate(self, task, state, criteria, data_class, narrowings=0, refs=()) -> tuple[float, float]:
        """(p50, p90) of a contract (spec §11): observed on the worker's adapter from MIN_RUNS closed runs, else
        the prior of one attempt times the expected attempts. Raises GatewayError when no route is permitted."""
        s = self._settings
        tokens = max(s.expected_output_tokens // 2 ** narrowings, 100)
        chars = sum(min(self._attachment_chars([ref]), PREVIEW_CHARS) for ref in refs)  # what the worker receives
        worker = self._gateway.estimate(ModelRequest(
            tier=WORKER_TIER, prompt=state + "x" * chars, system=worker_system(), data_class=data_class,
            expected_output_tokens=tokens, task=task))
        observed = contract_costs(self._ledger.events(types=["RESULT", "ABSTAIN", "GATE_PASSED", "GATE_FAILED",
                                                             "DECISION", "TASK_CLOSED"]),
                                  worker.connector, WORKER_TIER)
        if len(observed) >= MIN_RUNS:  # a narrowed scope halves the observed cost, as it halves the prior's output
            scale = 0.5 ** narrowings
            return percentile(observed, 0.5) * scale, percentile(observed, 0.9) * scale
        checks = critic = 0.0
        routed = True
        if criteria:
            questions = {f"c{n}": DecisionQuestion("noul", f"Does the output meet: {c}") for n, c in
                         enumerate(criteria, 1)}
            try:
                checks = self._gateway.estimate_decision(
                    DecisionRequest("x" * (4 * tokens), questions, data_class, task=task),
                    fallback_output_tokens=s.fallback_tokens_per_question * len(questions)).usd
            except GatewayError:
                routed = False  # no decision route: the critic checks every criterion instead
            critic = self._gateway.estimate(ModelRequest(
                tier=CRITIC_TIER, prompt="x" * (4 * tokens) + " ".join(criteria), system=CRITIC_SYSTEM,
                data_class=data_class, expected_output_tokens=s.critic_output_tokens + 100 * len(criteria),
                task=task)).usd
        priors = Priors(tokens, s.critic_output_tokens, s.fallback_tokens_per_question, s.retry_prior, s.critic_prior)
        usd = prior_usd(worker.usd, checks, critic, priors, critic_certain=bool(refs) or not routed)
        return usd, usd
```

Each narrowing halves the observed p50 / p90, as it halves the prior's output: the observed runs were of
unnarrowed tasks, and falling back to the (too low) prior would let almost any narrowed task pass its budget check.

In `Gate.run`: unpack `estimate, estimate_p90 = self._estimate(..., refs=<the TASK_SUBMITTED event's refs>)`;
`model_usd` and the value check use `estimate` (p50); the budget check and the budget question use `estimate_p90`:
the question says "The estimated cost is up to {p90:.4f} USD (typical {p50:.4f} USD), above the task budget …", and
`raised = max(math.ceil(estimate_p90 * 120) / 100, 0.01)`. The "after 3 budget questions" close compares p90 as well.

Imports in `gate.py`: `from .estimate import MIN_RUNS, Priors, contract_costs, percentile, prior_usd`,
`from .worker import PREVIEW_CHARS, worker_system`, `from .acceptance import CRITIC_SYSTEM, CRITIC_TIER`. If an
import cycle appears, move the two critic constants into a small module both import, and record the ruling.

`runtime.py`: the Gate counts characters, as the worker receives text:
`self.gate = Gate(ledger, gateway, settings, clock, attachment_chars=lambda refs: sum(
len(self.artifacts.read(ref).decode("utf-8", errors="replace")) for ref in refs))`.

- [ ] **Step 4: Run gate, gateway, config and runtime tests**

Run: `python -m pytest core/tests/test_gate.py core/tests/test_gateway_decide.py core/tests/test_config.py core/tests/test_runtime.py core/tests/test_task_cli.py -q`
Expected: all pass. Tests that pin an estimate or a budget question (search `estimate_usd`, `model_usd`,
`budget_usd=0.0`, `Raise the budget` in `core/tests/`) may change; recompute each expected value from the formula,
not from the test output, and record each change as a ruling in the execution ledger.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/gate.py core/src/ooat_core/gateway.py core/src/ooat_core/config.py core/src/ooat_core/runtime.py core/tests/test_gate.py core/tests/test_gateway_decide.py core/tests/test_config.py core/tests/test_runtime.py core/tests/test_task_cli.py
git commit -m "feat(core): the Gate estimates contract p50/p90 per adapter and checks the budget against p90 (plan 04d)"
```

---

### Task 3: Check against the real ledger, docs

**Files:**
- Modify: `tasks/f1-skeleton/task-04-task-runtime/design.md` §4, `core/description.md`,
  `tasks/f1-skeleton/task-03d-gateway-hardening/task.md`

- [ ] **Step 1: Check on the operator's ledger (read-only, nothing is written)**

Run from the working folder, with the repository's virtual environment active:

```bash
python -c "from ooat_core.ledger import Ledger; from ooat_core.estimate import contract_costs, percentile; l = Ledger.open('sqlite:///ledger.sqlite'); c = contract_costs(l.events(), 'prv.anthropic.subscription_cli', 'workhorse'); print(len(c), percentile(c, 0.5), percentile(c, 0.9))"
```

Expected: `6 0.0858… 0.5074…` (the evidence table). Record the output in the execution ledger.

- [ ] **Step 2: Docs**
  - design 04 §4: the estimate is the p50 / p90 of the last 50 closed contracts on the worker's adapter and tier
    (spec §11); a contract's whole cost, abstentions and failed calls included, belongs to the adapter of its
    first worker call (a failover later in the contract does not move it), p50 for `model_usd` and the value check, p90 for the budget check and question; before 5 runs, or
    for a narrowed scope, the prior: worker (with the attachment text the worker receives, at most 100,000
    characters each) + decision checks + critic × its share (1 with an untrusted attachment or no decision route),
    times (1 + retry prior); priors in `[gate]`. The ledger has no model id per call, so the price version stands
    in for "the model behind a tier changed". The ledger is scanned on each Gate run: cheap for SQLite, a view for
    Postgres later.
  - `core/description.md`: add `estimate.py`.
  - 03d: tick "The pre-start estimate ignores attachments, the critic and a second attempt"; add "Record the model
    id in each cost record, so cost history splits exactly when the model behind a tier changes (spec §11)".

- [ ] **Step 3: Full suite and commit**

Run: `python -m pytest -q`
Expected: all pass

```bash
git add tasks/f1-skeleton/task-04-task-runtime/design.md core/description.md tasks/f1-skeleton/task-03d-gateway-hardening/task.md
git commit -m "docs: estimate from observed contract costs (plan 04d)"
```

# Pre-start Estimate from Observed Runs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Gate's pre-start estimate count what a T2 task really spends: the worker's real output size,
its attachments, the critic, a second attempt and the text-model fallback's long answers.

**Architecture:** A new pure module `estimate.py` reads priors from the operator's own ledger (median output
tokens of recent workers, critics and fallback decisions; the share of tasks that needed a second attempt or the
critic) and falls back to fixed priors until three tasks are observed. The Gate builds its estimate from these
priors and the attachment size; the gateway lets a caller state the expected output of a fallback decision.

**Tech Stack:** Python 3.12+, pytest; no new dependencies.

**Spec:** `tasks/f1-skeleton/task-04-task-runtime/design.md` §4 (pre-start estimate, budget and value checks) and
§5 (worker, acceptance, critic, two attempts); spec §4 step B ("priors belong in configuration, measurements
replace them"); 03d item "The pre-start estimate ignores attachments, the critic and a second attempt".

## Evidence (seed runs, 2026-10-07/08)

| task | estimate USD | actual USD | first worker output tokens | attempts | critic | fallback decisions |
|---|---|---|---|---|---|---|
| s1 | 0.021 | 0.058 | 3,472 | 1 | yes | no |
| s2 | 0.021 | 0.238 | 19,363 | 1 | yes | no |
| s3 | 0.024 | 0.552 | 19,186 | 2 | yes | yes (2,993 / 1,610 out) |
| s4 | 0.021 | 0.469 | 17,805 | 2 | yes | no |
| s5 | 0.024 | 0.106 | 5,303 | 1 | yes | yes (2,215 out) |

The output prior (2,000 tokens) is the main error; then the critic (0.014–0.032 USD), the second attempt, and the
fallback decision, whose `max_output_tokens` of about 400 the Claude Code CLI does not enforce. A leave-one-out
backtest of the design below gives actual/estimate between 0.16 and 2.1 (today 2.8 to 22).

## Global Constraints

- Only `ooat-core` writes to the ledger; `estimate.py` only reads events.
- Priors that are not measurements live in `GateSettings` (`ooat.toml [gate]`), never as facts in code comments.
- No schema change: the estimate stays `candidates[].model_usd` of `TOPOLOGY_DECIDED`.
- Prices stay in `catalog/routing.json`; the estimate goes through `Gateway.estimate()` / `estimate_decision()`.
- English for code, docs and commits.

## Review Focus

1. A fresh ledger with no observed task → the fixed priors apply and the estimate is no lower than today's
   (Task 2 test `test_without_observations_the_estimate_is_never_below_the_old_one`).
2. A ledger whose only worker results failed or abstained → they are not output observations
   (Task 1 test `test_only_delivered_documents_count_as_output`).
3. Narrowing the scope still lowers the estimate (Task 2 test `test_narrowing_still_halves_the_output_prior`).
4. An untrusted attachment makes the critic certain (critic share 1), whatever the history says
   (Task 2 test `test_an_untrusted_attachment_always_counts_the_critic`).
5. A task over budget under the new estimate gets the budget question before anything runs, not a pause
   mid-run (Task 2 test `test_a_large_expected_output_asks_for_budget_before_the_run`).

---

### Task 1: Observed priors (`estimate.py`)

**Files:**
- Create: `core/src/ooat_core/estimate.py`
- Test: `core/tests/test_estimate.py`

**Interfaces:**
- Produces: `Priors(output_tokens: int, critic_output_tokens: int, fallback_tokens_per_question: int,
  retry_rate: float, critic_rate: float, observed_tasks: int)`;
  `observed_priors(events: list[dict], defaults: Priors) -> Priors`;
  `expected_usd(worker_usd: float, checks_usd: float, critic_usd: float, priors: Priors, untrusted: bool) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
"""Estimate priors from the operator's own ledger (plan 04d)."""

import pytest

from ooat_core.estimate import Priors, expected_usd, observed_priors
from ooat_core.ids import new_id

DEFAULTS = Priors(output_tokens=2000, critic_output_tokens=400, fallback_tokens_per_question=500, retry_rate=0.25,
                  critic_rate=0.5, observed_tasks=0)


def task(out_tokens, attempts=1, critic=True, fallback_out=None, closed=True, outcome="DONE"):
    t = new_id("tsk")
    events = []
    for _ in range(attempts):
        events.append({"type": "RESULT", "task": t, "actor": {"kind": "agent"}, "body": {"outcome": outcome},
                       "cost": {"tier": "workhorse", "tokens_out": out_tokens}})
    if critic:
        events.append({"type": "GATE_PASSED", "task": t, "body": {"gate": "gate.critic.check_criterion"},
                       "cost": {"tier": "workhorse", "tokens_out": 380}})
    if fallback_out is not None:
        events.append({"type": "TOPOLOGY_DECIDED", "task": t, "body": {"decisions": [{}] * 9},
                       "cost": {"tier": "economy", "tokens_out": fallback_out}})
    if closed:
        events.append({"type": "TASK_CLOSED", "task": t, "body": {}})
    return events


def test_below_three_observed_tasks_the_defaults_hold():
    priors = observed_priors(task(19000) + task(18000), DEFAULTS)
    assert (priors.output_tokens, priors.retry_rate, priors.critic_rate, priors.observed_tasks) == (2000, 0.25, 0.5, 2)


def test_from_three_tasks_the_medians_and_shares_of_the_ledger_apply():
    events = task(3500) + task(19000, attempts=2) + task(18000, fallback_out=3600) + task(5300, critic=False)
    priors = observed_priors(events, DEFAULTS)
    assert priors.observed_tasks == 4
    assert priors.output_tokens == 11650  # median of the first delivered output of each task
    assert priors.retry_rate == 0.25 and priors.critic_rate == 0.75
    assert priors.critic_output_tokens == 380
    assert priors.fallback_tokens_per_question == 400  # 3600 tokens over 9 questions


def test_only_delivered_documents_count_as_output():
    events = task(50, outcome="FAILED") + task(60, outcome="FAILED") + task(70, outcome="FAILED")
    assert observed_priors(events, DEFAULTS).output_tokens == 2000


def test_open_tasks_are_not_observations():
    events = task(19000, closed=False) + task(18000, closed=False) + task(17000, closed=False)
    assert observed_priors(events, DEFAULTS).observed_tasks == 0


def test_the_expected_cost_adds_the_critic_by_its_share_and_scales_by_the_retry_rate():
    priors = DEFAULTS
    assert expected_usd(0.10, 0.01, 0.04, priors, untrusted=False) == pytest.approx((0.10 + 0.01 + 0.5 * 0.04) * 1.25)
    assert expected_usd(0.10, 0.01, 0.04, priors, untrusted=True) == pytest.approx((0.10 + 0.01 + 0.04) * 1.25)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest core/tests/test_estimate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ooat_core.estimate'`

- [ ] **Step 3: Implement**

```python
"""Priors for the Gate's pre-start estimate, read from the operator's own ledger (plan 04d; spec §4 step B).

Fixed priors (GateSettings) hold until MIN_OBSERVED tasks have closed; from then on the medians and shares of the
last RECENT closed tasks replace them, so the estimate follows what this operator's tasks really cost.
"""

from dataclasses import dataclass, replace
from statistics import median

MIN_OBSERVED = 3
RECENT = 20
CRITIC_GATE = "gate.critic.check_criterion"


@dataclass(frozen=True)
class Priors:
    output_tokens: int  # the worker's first delivered document
    critic_output_tokens: int
    fallback_tokens_per_question: int  # a text-model decision; the CLI does not enforce max_output_tokens
    retry_rate: float  # share of tasks that needed a second delivered document
    critic_rate: float  # share of tasks in which the critic ran
    observed_tasks: int


def observed_priors(events: list[dict], defaults: Priors) -> Priors:
    closed = [e["task"] for e in events if e["type"] == "TASK_CLOSED"]
    recent = list(dict.fromkeys(reversed(closed)))[:RECENT]  # newest first, each task once
    outputs, critic_out, fallback, retried, critic_ran = [], [], [], 0, 0
    observed = 0
    for task in recent:
        own = [e for e in events if e.get("task") == task]
        done = [e for e in own if e["type"] == "RESULT" and e["actor"]["kind"] == "agent"
                and e["body"]["outcome"] == "DONE" and "cost" in e]
        if not done:
            continue
        observed += 1
        outputs.append(done[0]["cost"]["tokens_out"])
        retried += len(done) > 1
        critics = [e for e in own if e["type"].startswith("GATE_") and e["body"].get("gate") == CRITIC_GATE]
        critic_ran += bool(critics)
        critic_out += [e["cost"]["tokens_out"] for e in critics if "cost" in e]
        for e in own:  # a decision answered by the text model instead of a decision connector
            questions = len(e["body"].get("decisions", [])) or len(e["body"].get("criteria", []))
            if e.get("cost", {}).get("tier") == "economy" and questions:
                fallback.append(e["cost"]["tokens_out"] // questions)
    if observed < MIN_OBSERVED:
        return replace(defaults, observed_tasks=observed)
    return Priors(output_tokens=int(median(outputs)),
                  critic_output_tokens=int(median(critic_out)) if critic_out else defaults.critic_output_tokens,
                  fallback_tokens_per_question=int(median(fallback)) if fallback
                  else defaults.fallback_tokens_per_question,
                  retry_rate=retried / observed, critic_rate=critic_ran / observed, observed_tasks=observed)


def expected_usd(worker_usd: float, checks_usd: float, critic_usd: float, priors: Priors, untrusted: bool) -> float:
    """One attempt (worker, decision checks, the critic by its share) times the expected number of attempts. An
    untrusted attachment sends every "met" answer to the critic, so it always runs then."""
    critic_share = 1.0 if untrusted else priors.critic_rate
    return (worker_usd + checks_usd + critic_share * critic_usd) * (1 + priors.retry_rate)
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest core/tests/test_estimate.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/estimate.py core/tests/test_estimate.py
git commit -m "feat(core): estimate priors from the operator's own ledger (plan 04d)"
```

---

### Task 2: The Gate's estimate uses the priors, the attachments and the critic

**Files:**
- Modify: `core/src/ooat_core/gate.py` (`GateSettings`, `Gate.__init__`, `Gate._estimate`)
- Modify: `core/src/ooat_core/gateway.py` (`estimate_decision`, `_fallback_request`)
- Modify: `core/src/ooat_core/runtime.py` (`Gate(...)` construction)
- Test: `core/tests/test_gate.py`, `core/tests/test_gateway_decide.py`

**Interfaces:**
- Consumes: `Priors`, `observed_priors`, `expected_usd` (Task 1).
- Produces: `GateSettings.critic_output_tokens: int = 400`, `fallback_tokens_per_question: int = 500`,
  `retry_prior: float = 0.25`, `critic_prior: float = 0.5`;
  `Gate(ledger, gateway, settings, clock, attachment_chars: Callable[[list[str]], int] | None = None)`;
  `Gateway.estimate_decision(request, fallback_output_tokens: int | None = None) -> Estimate`.

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_gate.py`, give `GateSetup.__init__` a new keyword `attachment_chars=None` and pass it on:
`self.gate = Gate(self.ledger, self.gateway, settings, clock=lambda: NOW, attachment_chars=attachment_chars)`.
Add a helper method to `GateSetup` that submits with one attachment ref (the Gate only needs its size through
`attachment_chars`, so no blob is stored):

```python
    def submit_with_attachment(self, **extra):
        task = new_id("tsk")
        body = {"goal": "Shrň přiloženou smlouvu.", "acceptance": ["Shrnutí má nejvýše 300 slov."], **extra}
        self.ledger.append(new_event("TASK_SUBMITTED", task=task, actor=HIL, body=body,
                                     refs=["art_01J9ZQ6X9EK3M5N7P9Q1R3S5T7@v1"]))
        return task
```

If `new_event` validates that refs exist as artifacts, stage one through an `ArtifactStore` instead, as
`core/tests/test_runtime.py` does, and record the change as a ruling.

Then append these tests (`answer`, `task_facts`, `GateSettings` are already imported in the file):

```python
# Estimate from observed runs (plan 04d) ----------------------------------------------------------------------

def estimate_of(setup, task):
    setup.gate.run(task)
    decided = setup.events(task, "TOPOLOGY_DECIDED")[-1]
    return next(c["model_usd"] for c in decided["body"]["candidates"] if "model_usd" in c)


def test_without_observations_the_estimate_is_never_below_the_old_one():
    setup = GateSetup()
    task = setup.submit()
    facts = task_facts(setup.ledger.events(task=task))
    old = setup.gate._estimate_parts(task, facts.state, facts.criteria, "internal")
    assert estimate_of(setup, task) >= old["worker"] + old["checks"]  # the old one-attempt formula


def test_narrowing_still_halves_the_output_prior():
    setup = GateSetup()
    task = setup.submit(budget_usd=0.001)
    first = setup.gate.run(task)
    answer(setup, task, first.request, choice="narrow_scope", text="Jen první kapitola smlouvy.")
    second = setup.gate.run(task)
    assert second.estimate_usd < first.estimate_usd * 0.75


def test_an_untrusted_attachment_always_counts_the_critic():
    plain = GateSetup()
    attached = GateSetup(attachment_chars=lambda refs: 40_000 if refs else 0)
    assert estimate_of(attached, attached.submit_with_attachment()) > estimate_of(plain, plain.submit())


def test_a_large_expected_output_asks_for_budget_before_the_run():
    setup = GateSetup(settings=GateSettings(expected_output_tokens=20_000))
    task = setup.submit(budget_usd=0.05)
    outcome = setup.gate.run(task)
    assert outcome.action == "ask"
    assert "raise_budget" in [o["id"] for o in setup.events(task, "HIL_REQUEST")[0]["body"]["options"]]
```

Append to `core/tests/test_gateway_decide.py` (its `Setup` and `economy()` helpers exist):

```python
def test_a_fallback_decision_can_be_priced_at_its_observed_output():
    setup = Setup(economy())  # no decision connector: the economy text tier answers
    small = setup.gateway.estimate_decision(setup.request()).usd
    large = setup.gateway.estimate_decision(setup.request(), fallback_output_tokens=4000).usd
    assert large > small
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest core/tests/test_gate.py core/tests/test_gateway_decide.py -q -k "observations or narrowing_still or untrusted_attachment_always or large_expected or observed_output"`
Expected: FAIL (`_estimate_parts`, `attachment_chars`, `fallback_output_tokens` do not exist)

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

`gate.py` — settings (new fields, defaults are priors, not measurements):

```python
    critic_output_tokens: int = 400  # prior for the critic's JSON verdict
    fallback_tokens_per_question: int = 500  # prior for a text-model decision answer
    retry_prior: float = 0.25  # share of tasks needing a second attempt, until measured
    critic_prior: float = 0.5  # share of tasks in which the critic runs, until measured
```

`gate.py` — constructor and estimate:

```python
    def __init__(self, ledger: Ledger, gateway: Gateway, settings: GateSettings = GateSettings(),
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 attachment_chars: Callable[[list[str]], int] | None = None):
        self._ledger, self._gateway, self._settings, self._clock = ledger, gateway, settings, clock
        self._attachment_chars = attachment_chars or (lambda refs: 0)

    def _priors(self) -> Priors:
        defaults = Priors(self._settings.expected_output_tokens, self._settings.critic_output_tokens,
                          self._settings.fallback_tokens_per_question, self._settings.retry_prior,
                          self._settings.critic_prior, 0)
        return observed_priors(self._ledger.events(types=["RESULT", "GATE_PASSED", "GATE_FAILED",
                                                          "TOPOLOGY_DECIDED", "TASK_CLOSED"]), defaults)

    def _estimate_parts(self, task, state, criteria, data_class, narrowings=0, refs=(), priors=None) -> dict:
        priors = priors or self._priors()
        tokens = max(priors.output_tokens // 2 ** narrowings, 100)
        attached = "x" * self._attachment_chars(list(refs))  # size only: the text never leaves through this
        worker = self._gateway.estimate(ModelRequest(tier=WORKER_TIER, prompt=state + attached + worker_system(),
                                                     data_class=data_class, expected_output_tokens=tokens, task=task))
        checks = critic = 0.0
        if criteria:
            questions = {f"c{n}": DecisionQuestion("noul", f"Does the output meet: {c}") for n, c in
                         enumerate(criteria, 1)}
            try:
                checks = self._gateway.estimate_decision(
                    DecisionRequest("x" * (4 * tokens), questions, data_class, task=task),
                    fallback_output_tokens=priors.fallback_tokens_per_question * len(questions)).usd
            except GatewayError:
                checks = 0.0  # no decision route: the critic checks every criterion instead
            critic = self._gateway.estimate(ModelRequest(
                tier=CRITIC_TIER, prompt="x" * (4 * tokens) + " ".join(criteria), data_class=data_class,
                expected_output_tokens=priors.critic_output_tokens, task=task)).usd
        return {"worker": worker.usd, "checks": checks, "critic": critic}

    def _estimate(self, task, state, criteria, data_class, narrowings=0, refs=()) -> float:
        """Worker, decision checks, the critic by its share, times the expected attempts (plan 04d)."""
        priors = self._priors()
        parts = self._estimate_parts(task, state, criteria, data_class, narrowings, refs, priors)
        return expected_usd(parts["worker"], parts["checks"], parts["critic"], priors, untrusted=bool(refs))
```

Imports in `gate.py`: `from .acceptance import CRITIC_TIER`, `from .estimate import Priors, expected_usd,
observed_priors`, `from .worker import worker_system` (check for an import cycle: if `acceptance` or `worker` import
`gate`, define `CRITIC_TIER = "workhorse"` locally with a comment pointing to `acceptance.CRITIC_TIER` and a test
that asserts both are equal). The call site in `Gate.run` passes `refs=submitted["refs"]` (the `TASK_SUBMITTED`
event's refs). When no decision route exists, the old code priced the critic as `worker.usd`; the new code prices
it explicitly, with share 1.0 because every criterion then goes to the critic: pass `untrusted=True` in that case.

`runtime.py`: `self.gate = Gate(ledger, gateway, settings, clock, attachment_chars=lambda refs: sum(
len(self.artifacts.read(ref)) for ref in refs))`.

- [ ] **Step 4: Run gate, gateway and runtime tests**

Run: `.venv\Scripts\python.exe -m pytest core/tests/test_gate.py core/tests/test_gateway_decide.py core/tests/test_runtime.py -q`
Expected: all pass. Existing tests that pin an estimate value (search `estimate_usd` and `model_usd` in
`core/tests/`) will change; update each expected number from the formula above, not from the test output, and
record each in the execution ledger as a ruling.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/gate.py core/src/ooat_core/gateway.py core/src/ooat_core/runtime.py core/tests/test_gate.py core/tests/test_gateway_decide.py core/tests/test_runtime.py
git commit -m "feat(core): the Gate's estimate counts output priors, attachments, the critic and a second attempt (plan 04d)"
```

---

### Task 3: Backtest on the seed runs, docs

**Files:**
- Test: `core/tests/test_estimate.py` (backtest)
- Modify: `tasks/f1-skeleton/task-04-task-runtime/design.md` §4, `core/description.md`,
  `tasks/f1-skeleton/task-03d-gateway-hardening/task.md`

- [ ] **Step 1: Write the backtest** (numbers from the evidence table; prices: workhorse 2 / 10, economy 1 / 5 USD
  per 1M tokens, as `claude-sonnet-5-5` and `claude-haiku-4-5-20251001` in `catalog/routing.json`)

```python
SEED = [  # first worker input, worker outputs per attempt, critic output, fallback outputs, actual USD minus Gate
    (3970, [3472], 872, [], 0.0580),
    (7461, [19363], 370, [], 0.2376),
    (5527, [19186, 18482], 382, [2993, 1610], 0.5074),
    (7375, [17805, 20166], 438, [], 0.4689),
    (1845, [5303], 392, [2215], 0.0857),
]


@pytest.mark.parametrize("index", range(5))
def test_leave_one_out_backtest_on_the_seed_runs(index):
    from statistics import median
    others = [s for i, s in enumerate(SEED) if i != index]
    win, outs, _, fallback, actual = SEED[index]
    out = median(o[1][0] for o in others)
    critic_out = median(o[2] for o in others)
    retry = sum(len(o[1]) > 1 for o in others) / len(others)
    worker = win * 2e-6 + out * 10e-6
    critic = (win + out) * 2e-6 + critic_out * 10e-6
    fallback_out = median([f for o in others for f in o[3]] or [400])
    checks = (win + out) * 1e-6 + fallback_out * 5e-6 if fallback else 0.0003
    estimate = expected_usd(worker, checks, critic,
                            Priors(int(out), int(critic_out), 500, retry, 1.0, 4), untrusted=True)
    assert actual / estimate <= 2.5  # never again underestimated 3 to 22 times
    assert actual / estimate >= 1 / 8  # an overestimate stays within reason
```

- [ ] **Step 2: Run it**

Run: `.venv\Scripts\python.exe -m pytest core/tests/test_estimate.py -q`
Expected: 10 passed (the backtest gives actual/estimate 0.16, 0.92, 2.1, 2.08, 0.22)

- [ ] **Step 3: Docs**
  - design 04 §4: the estimate is worker + decision checks + critic × critic share, × (1 + retry rate); priors from
    `[gate]` until three closed tasks, then medians and shares of the last 20 closed tasks; attachments count by size;
    a fallback decision is priced at its observed output per question.
  - `core/description.md`: add `estimate.py`.
  - 03d: tick "The pre-start estimate ignores attachments, the critic and a second attempt".

- [ ] **Step 4: Full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass

```bash
git add core/tests/test_estimate.py tasks/f1-skeleton/task-04-task-runtime/design.md core/description.md tasks/f1-skeleton/task-03d-gateway-hardening/task.md
git commit -m "test(core): estimate backtest on the seed runs; docs (plan 04d)"
```

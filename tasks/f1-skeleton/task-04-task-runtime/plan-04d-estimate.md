# Pre-start Estimate from Observed Runs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Gate's pre-start estimate count what a T2 task really spends: the worker's real output size,
its attachments, the critic, a second attempt and the text-model fallback's long answers.

**Architecture:** A new pure module `estimate.py` reads the operator's own ledger and blends fixed priors
(`[gate]`) with observations, the prior weighted as 5 observations (spec §11), per `task_type` when one has at
least three closed tasks, else over all tasks. The Gate builds its estimate from these priors and the attachment
size the worker will really receive. The gateway lets a caller state the expected output of a fallback decision.

**Tech Stack:** Python 3.12+, pytest; no new dependencies.

**Spec:** `tasks/f1-skeleton/task-04-task-runtime/design.md` §4 (pre-start estimate, budget and value checks) and
§5 (worker, acceptance, critic, two attempts); spec §4 step B (priors in configuration, posteriors per task class)
and §11 "Price-list calibration" (the prior counts as 5 observations); 03d item "The pre-start estimate ignores
attachments, the critic and a second attempt".

## Evidence (seed runs, 2026-10-07/08)

| task | estimate USD | actual USD | first worker output tokens | attempts | critic | fallback decision outputs |
|---|---|---|---|---|---|---|
| s1 | 0.021 | 0.058 | 3,472 | 1 | yes | — |
| s2 | 0.021 | 0.238 | 19,363 | 1 | yes | — |
| s3 | 0.024 | 0.552 | 19,186 | 2 | yes | 2,993 and 1,610 (5 criteria) |
| s4 | 0.021 | 0.469 | 17,805 | 2 | yes | — |
| s5 | 0.024 | 0.106 | 5,303 | 1 | yes | 2,215 (5 criteria) |

The output prior (2,000 tokens) is the main error. The critic (0.014–0.032 USD), the second attempt and the fallback
decision add to it; the Claude Code CLI does not enforce the fallback's `max_output_tokens` of about 400. A
leave-one-out backtest of this design gives actual/estimate 0.32–3.34 with the default prior of 2,000 tokens and
0.18–1.72 with a prior of 17,800 tokens set in the operator's `[gate]` (today: 2.8–22).

## Global Constraints

- Only `ooat-core` writes to the ledger; `estimate.py` only reads events.
- Priors that are not measurements live in `GateSettings` (`ooat.toml [gate]`), never as facts in code.
- The prior counts as `PRIOR_WEIGHT = 5` observations (spec §11).
- No schema change: the estimate stays `candidates[].model_usd` of `TOPOLOGY_DECIDED`.
- Prices stay in `catalog/routing.json`; the estimate goes through `Gateway.estimate()` / `estimate_decision()`.
- English for code, docs and commits.

## Review Focus

1. A fresh ledger → the estimate is never below today's formula, computed independently: worker at the prior plus
   the decision checks, or plus the worker again when no decision route exists (Task 2 test
   `test_without_observations_the_estimate_is_never_below_the_old_one`, with and without a decision route).
2. A failed critic or worker call has an estimated cost without `tokens_out` → it is not an observation and nothing
   crashes (Task 1 test `test_failed_calls_without_tokens_are_skipped`).
3. Narrowing the scope still lowers the estimate (Task 2 test `test_narrowing_still_halves_the_output_prior`).
4. An attachment larger than the worker's 100,000-character cap counts only up to the cap (Task 2 test
   `test_an_attachment_counts_only_what_the_worker_receives`).
5. A task over budget under the new estimate gets the budget question before anything runs (Task 2 test
   `test_a_large_expected_output_asks_for_budget_before_the_run`).

---

### Task 1: Blended priors (`estimate.py`)

**Files:**
- Create: `core/src/ooat_core/estimate.py`
- Test: `core/tests/test_estimate.py`

**Interfaces:**
- Produces: `Priors(output_tokens: int, critic_output_tokens: int, fallback_tokens_per_question: int,
  retry_rate: float, critic_rate: float, observed_tasks: int)`;
  `observed_priors(events: list[dict], defaults: Priors, task_type: str | None = None) -> Priors`;
  `expected_usd(worker_usd: float, checks_usd: float, critic_usd: float, priors: Priors, critic_certain: bool) -> float`;
  `PRIOR_WEIGHT = 5`, `MIN_CLASS = 3`, `RECENT = 20`.

- [ ] **Step 1: Write the failing tests**

```python
"""Estimate priors blended from the operator's own ledger (plan 04d)."""

import pytest

from ooat_core.estimate import Priors, expected_usd, observed_priors
from ooat_core.ids import new_id

DEFAULTS = Priors(output_tokens=2000, critic_output_tokens=400, fallback_tokens_per_question=500, retry_rate=0.25,
                  critic_rate=0.5, observed_tasks=0)


def task(out_tokens, attempts=1, critic=True, fallback_out=None, outcome="DONE", task_type=None, closed=True):
    t = new_id("tsk")
    body = {"goal": "x", **({"task_type": task_type} if task_type else {})}
    events = [{"type": "TASK_SUBMITTED", "task": t, "body": body}]
    for _ in range(attempts):
        events.append({"type": "RESULT", "task": t, "actor": {"kind": "agent"}, "body": {"outcome": outcome},
                       "cost": {"tier": "workhorse", "tokens_out": out_tokens, "basis": "shadow"}})
    if critic:
        events.append({"type": "GATE_PASSED", "task": t, "body": {"gate": "gate.critic.check_criterion"},
                       "cost": {"tier": "workhorse", "tokens_out": 380, "basis": "shadow"}})
    if fallback_out is not None:
        events.append({"type": "GATE_FAILED", "task": t, "body": {"gate": "gate.decision.check_criterion",
                                                                   "criteria": [{}] * 5},
                       "cost": {"tier": "economy", "tokens_out": fallback_out, "basis": "shadow"}})
    if closed:
        events.append({"type": "TASK_CLOSED", "task": t, "body": {}})
    return events


def test_with_no_closed_task_the_defaults_hold():
    assert observed_priors([], DEFAULTS) == DEFAULTS


def test_observations_are_blended_with_the_prior_weighted_as_five():
    events = task(3500) + task(19000, attempts=2) + task(18000, fallback_out=3000) + task(5300, critic=False)
    priors = observed_priors(events, DEFAULTS)
    assert priors.observed_tasks == 4
    assert priors.output_tokens == round((5 * 2000 + 4 * 11650) / 9)  # median 11,650 of the first outputs
    assert priors.retry_rate == pytest.approx((5 * 0.25 + 1) / 9)
    assert priors.critic_rate == pytest.approx((5 * 0.5 + 3) / 9)
    assert priors.critic_output_tokens == round((5 * 400 + 3 * 380) / 8)
    assert priors.fallback_tokens_per_question == round((5 * 500 + 1 * 600) / 6)  # 3,000 over 5 criteria


def test_failed_calls_without_tokens_are_skipped():
    events = task(19000) + task(18000) + task(17000)
    events.append({"type": "GATE_FAILED", "task": events[0]["task"], "body": {"gate": "gate.critic.check_criterion"},
                   "cost": {"tier": "workhorse", "usd": 0.02, "basis": "estimated"}})  # no tokens_out
    assert observed_priors(events, DEFAULTS).observed_tasks == 3


def test_only_delivered_documents_count_as_output():
    events = task(50, outcome="FAILED") + task(60, outcome="FAILED") + task(70, outcome="FAILED")
    assert observed_priors(events, DEFAULTS) == DEFAULTS


def test_open_tasks_are_not_observations():
    events = task(19000, closed=False) + task(18000, closed=False)
    assert observed_priors(events, DEFAULTS).observed_tasks == 0


def test_a_task_type_with_three_closed_tasks_uses_only_its_own():
    events = task(500, task_type="summary") * 1 + task(600, task_type="summary") + task(700, task_type="summary") \
        + task(19000) + task(18000)
    assert observed_priors(events, DEFAULTS, task_type="summary").output_tokens == round((5 * 2000 + 3 * 600) / 8)
    assert observed_priors(events, DEFAULTS, task_type="code").observed_tasks == 5  # too few of its own: all


def test_the_expected_cost_adds_the_critic_by_its_share_and_scales_by_the_retry_rate():
    assert expected_usd(0.10, 0.01, 0.04, DEFAULTS, critic_certain=False) == pytest.approx((0.11 + 0.5 * 0.04) * 1.25)
    assert expected_usd(0.10, 0.01, 0.04, DEFAULTS, critic_certain=True) == pytest.approx((0.11 + 0.04) * 1.25)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest core/tests/test_estimate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ooat_core.estimate'`

- [ ] **Step 3: Implement**

```python
"""Priors for the Gate's pre-start estimate, blended from the operator's own ledger (plan 04d).

Spec §11: a prior counts as PRIOR_WEIGHT observations, so measurements replace it gradually. Spec §4 step B: per
task class, here the submitted `task_type` once it has MIN_CLASS closed tasks, else all tasks. Only the last RECENT
closed tasks count, so the estimate follows how this operator's tasks cost now.
"""

from dataclasses import dataclass
from statistics import median

PRIOR_WEIGHT = 5
MIN_CLASS = 3
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


def _tokens(event: dict) -> int | None:
    cost = event.get("cost") or {}
    return cost.get("tokens_out") if cost.get("basis") != "estimated" else None  # a failed call has no tokens


def _blend(prior: float, observed: list[float]) -> float:
    return (PRIOR_WEIGHT * prior + len(observed) * median(observed)) / (PRIOR_WEIGHT + len(observed)) \
        if observed else prior


def _share(prior: float, hits: int, n: int) -> float:
    return (PRIOR_WEIGHT * prior + hits) / (PRIOR_WEIGHT + n)


def observed_priors(events: list[dict], defaults: Priors, task_type: str | None = None) -> Priors:
    by_task: dict[str, list[dict]] = {}
    for event in events:
        if event.get("task"):
            by_task.setdefault(event["task"], []).append(event)
    closed = [t for t, own in by_task.items() if any(e["type"] == "TASK_CLOSED" for e in own)]
    types = {t: next((e["body"].get("task_type") for e in by_task[t] if e["type"] == "TASK_SUBMITTED"), None)
             for t in closed}
    same = [t for t in closed if task_type is not None and types[t] == task_type]
    pool = (same if len(same) >= MIN_CLASS else closed)[-RECENT:]
    outputs, critic_out, fallback, retried, critic_ran, observed = [], [], [], 0, 0, 0
    for task in pool:
        own = by_task[task]
        done = [_tokens(e) for e in own if e["type"] == "RESULT" and e["actor"]["kind"] == "agent"
                and e["body"]["outcome"] == "DONE"]
        done = [t for t in done if t is not None]
        if not done:
            continue
        observed += 1
        outputs.append(done[0])
        retried += len(done) > 1
        critics = [e for e in own if e["type"].startswith("GATE_") and e["body"].get("gate") == CRITIC_GATE]
        critic_ran += bool(critics)
        critic_out += [t for t in map(_tokens, critics) if t is not None]
        for e in own:  # a decision the text model answered instead of a decision connector
            questions = len(e["body"].get("decisions", [])) or len(e["body"].get("criteria", []))
            tokens = _tokens(e)
            if (e.get("cost") or {}).get("tier") == "economy" and questions and tokens is not None:
                fallback.append(tokens / questions)
    if not observed:
        return defaults
    return Priors(output_tokens=round(_blend(defaults.output_tokens, outputs)),
                  critic_output_tokens=round(_blend(defaults.critic_output_tokens, critic_out)),
                  fallback_tokens_per_question=round(_blend(defaults.fallback_tokens_per_question, fallback)),
                  retry_rate=_share(defaults.retry_rate, retried, observed),
                  critic_rate=_share(defaults.critic_rate, critic_ran, observed), observed_tasks=observed)


def expected_usd(worker_usd: float, checks_usd: float, critic_usd: float, priors: Priors, critic_certain: bool) -> float:
    """One attempt (worker, decision checks, the critic by its share) times the expected number of attempts. The
    critic is certain with an untrusted attachment, or when no decision route can check the criteria."""
    share = 1.0 if critic_certain else priors.critic_rate
    return (worker_usd + checks_usd + share * critic_usd) * (1 + priors.retry_rate)
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest core/tests/test_estimate.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/estimate.py core/tests/test_estimate.py
git commit -m "feat(core): estimate priors blended from the operator's ledger (plan 04d)"
```

---

### Task 2: The Gate's estimate uses the priors, the attachments and the critic

**Files:**
- Modify: `core/src/ooat_core/gate.py` (`GateSettings`, `Gate.__init__`, `Gate._estimate`, the call in `Gate.run`)
- Modify: `core/src/ooat_core/gateway.py` (`estimate_decision`)
- Modify: `core/src/ooat_core/runtime.py` (`Gate(...)` construction)
- Modify: `core/src/ooat_core/config.py` (`_GATE_NUMBERS`: the four new `[gate]` keys)
- Test: `core/tests/test_gate.py`, `core/tests/test_gateway_decide.py`, `core/tests/test_config.py`

**Interfaces:**
- Consumes: `Priors`, `observed_priors`, `expected_usd` (Task 1); `PREVIEW_CHARS`, `worker_system` from `worker.py`.
- Produces: `GateSettings.critic_output_tokens: int = 400`, `fallback_tokens_per_question: int = 500`,
  `retry_prior: float = 0.25`, `critic_prior: float = 0.5`;
  `Gate(ledger, gateway, settings, clock, attachment_chars: Callable[[list[str]], int] | None = None)`;
  `Gate._estimate_parts(task, state, criteria, data_class, narrowings=0, refs=(), priors=None) -> dict` with keys
  `worker`, `checks`, `critic`, `routed` (bool: a decision route exists);
  `Gateway.estimate_decision(request, fallback_output_tokens: int | None = None) -> Estimate`.

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_gate.py` give `GateSetup.__init__` a keyword `attachment_chars=None` and pass it on:
`self.gate = Gate(self.ledger, self.gateway, settings, clock=lambda: NOW, attachment_chars=attachment_chars)`.
Add to `GateSetup`:

```python
    def submit_with_attachment(self, **extra):
        task = new_id("tsk")
        body = {"goal": "Shrň přiloženou smlouvu.", "acceptance": ["Shrnutí má nejvýše 300 slov."], **extra}
        self.ledger.append(new_event("TASK_SUBMITTED", task=task, actor=HIL, body=body,
                                     refs=["art_01J9ZQ6X9EK3M5N7P9Q1R3S5T7@v1"]))
        return task
```

(If `new_event` or the ledger refuses a ref without an artifact row, stage one through an `ArtifactStore` as
`core/tests/test_runtime.py` does, and record that as a ruling.)

Append:

```python
# Estimate from observed runs (plan 04d) ----------------------------------------------------------------------

from ooat_core.connectors import ModelRequest as _ModelRequest


def estimate_of(setup, task):
    setup.gate.run(task)
    decided = setup.events(task, "TOPOLOGY_DECIDED")[-1]
    return next(c["model_usd"] for c in decided["body"]["candidates"] if "model_usd" in c)


def old_formula(setup, task, routed=True):
    """Today's estimate, computed without the new code: worker at the 2,000-token prior, plus the decision checks,
    or plus the worker again when no decision route exists."""
    state = task_facts(setup.ledger.events(task=task)).state
    worker = setup.gateway.estimate(_ModelRequest(tier="workhorse", prompt=state, data_class="internal",
                                                  expected_output_tokens=2000, task=task)).usd
    return worker + (0.0 if routed else worker)


def test_without_observations_the_estimate_is_never_below_the_old_one():
    setup = GateSetup()
    task = setup.submit()
    assert estimate_of(setup, task) >= old_formula(setup, task)


def test_without_a_decision_route_the_estimate_is_never_below_the_old_one():
    setup = GateSetup(jev_error=ConnectorError("UNAVAILABLE", "HTTP 529"))
    setup.ledger.append(new_event("ADAPTER_DISABLED", task=None, actor=HIL, body={
        "adapter": setup.jev.manifest["id"], "operator": "Operator", "reason": "no decision route in this test"}))
    task = setup.submit()
    assert estimate_of(setup, task) >= old_formula(setup, task, routed=False)


def test_narrowing_still_halves_the_output_prior():
    setup = GateSetup()
    task = setup.submit(budget_usd=0.001)
    first = setup.gate.run(task)
    answer(setup, task, first.request, choice="narrow_scope", text="Jen první kapitola smlouvy.")
    second = setup.gate.run(task)
    assert second.estimate_usd < first.estimate_usd * 0.75


def test_an_untrusted_attachment_always_counts_the_critic():
    plain = GateSetup()
    attached = GateSetup(attachment_chars=lambda refs: 4_000 if refs else 0)
    assert estimate_of(attached, attached.submit_with_attachment()) > estimate_of(plain, plain.submit())


def test_an_attachment_counts_only_what_the_worker_receives():
    capped = GateSetup(attachment_chars=lambda refs: 100_000)
    huge = GateSetup(attachment_chars=lambda refs: 5_000_000)
    assert estimate_of(huge, huge.submit_with_attachment()) == \
        pytest.approx(estimate_of(capped, capped.submit_with_attachment()))


def test_a_large_expected_output_asks_for_budget_before_the_run():
    setup = GateSetup(settings=GateSettings(expected_output_tokens=20_000))
    task = setup.submit(budget_usd=0.05)
    outcome = setup.gate.run(task)
    assert outcome.action == "ask"
    assert "raise_budget" in [o["id"] for o in setup.events(task, "HIL_REQUEST")[0]["body"]["options"]]
```

(`ConnectorError`, `answer`, `task_facts`, `GateSettings`, `new_event`, `HIL`, `pytest` are already imported or
defined in the file; check and add what is missing.)

Append to `core/tests/test_gateway_decide.py` (its `Setup` and `economy()` helpers exist):

```python
def test_a_fallback_decision_can_be_priced_at_its_observed_output():
    setup = Setup(economy())  # no decision connector: the economy text tier answers
    small = setup.gateway.estimate_decision(setup.request()).usd
    large = setup.gateway.estimate_decision(setup.request(), fallback_output_tokens=4000).usd
    assert large > small
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest core/tests/test_gate.py core/tests/test_gateway_decide.py -q -k "never_below or narrowing_still or untrusted_attachment_always or only_what_the_worker or large_expected or observed_output"`
Expected: FAIL (`attachment_chars` and `fallback_output_tokens` do not exist; the critic is not counted)

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

`gate.py`, `GateSettings` (priors, not measurements):

```python
    critic_output_tokens: int = 400  # prior for the critic's JSON verdict
    fallback_tokens_per_question: int = 500  # prior for a text-model decision answer
    retry_prior: float = 0.25  # share of tasks needing a second attempt, until measured
    critic_prior: float = 0.5  # share of tasks in which the critic runs, until measured
```

`gate.py`, the Gate:

```python
    def __init__(self, ledger: Ledger, gateway: Gateway, settings: GateSettings = GateSettings(),
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 attachment_chars: Callable[[list[str]], int] | None = None):
        self._ledger, self._gateway, self._settings, self._clock = ledger, gateway, settings, clock
        self._attachment_chars = attachment_chars or (lambda refs: 0)

    def _priors(self, task_type: str | None) -> Priors:
        s = self._settings
        defaults = Priors(s.expected_output_tokens, s.critic_output_tokens, s.fallback_tokens_per_question,
                          s.retry_prior, s.critic_prior, 0)
        return observed_priors(self._ledger.events(types=["TASK_SUBMITTED", "RESULT", "GATE_PASSED",
                                                          "GATE_FAILED", "TOPOLOGY_DECIDED", "TASK_CLOSED"]),
                               defaults, task_type)

    def _estimate_parts(self, task, state, criteria, data_class, narrowings=0, refs=(), priors=None) -> dict:
        priors = priors or self._priors(None)
        tokens = max(priors.output_tokens // 2 ** narrowings, 100)
        chars = sum(min(self._attachment_chars([ref]), PREVIEW_CHARS) for ref in refs)  # what the worker receives
        worker = self._gateway.estimate(ModelRequest(
            tier=WORKER_TIER, prompt=state + "x" * chars, system=worker_system(), data_class=data_class,
            expected_output_tokens=tokens, task=task)).usd
        checks = critic = 0.0
        routed = True
        if criteria:
            questions = {f"c{n}": DecisionQuestion("noul", f"Does the output meet: {c}") for n, c in
                         enumerate(criteria, 1)}
            try:
                checks = self._gateway.estimate_decision(
                    DecisionRequest("x" * (4 * tokens), questions, data_class, task=task),
                    fallback_output_tokens=priors.fallback_tokens_per_question * len(questions)).usd
            except GatewayError:
                routed = False  # no decision route: the critic checks every criterion instead
            critic = self._gateway.estimate(ModelRequest(
                tier=CRITIC_TIER, prompt="x" * (4 * tokens) + " ".join(criteria), data_class=data_class,
                expected_output_tokens=priors.critic_output_tokens, task=task)).usd
        return {"worker": worker, "checks": checks, "critic": critic, "routed": routed}

    def _estimate(self, task, state, criteria, data_class, narrowings=0, refs=(), task_type=None) -> float:
        """Worker, decision checks, the critic by its share, times the expected attempts (plan 04d)."""
        priors = self._priors(task_type)
        parts = self._estimate_parts(task, state, criteria, data_class, narrowings, refs, priors)
        certain = bool(refs) or not parts["routed"]
        return expected_usd(parts["worker"], parts["checks"], parts["critic"], priors, critic_certain=certain)
```

The call site in `Gate.run` passes `refs=submitted["refs"]` and
`task_type=submitted["body"].get("task_type")`, where `submitted` is the task's `TASK_SUBMITTED` event (the
`facts.submitted` id identifies it). Imports: `from .estimate import Priors, expected_usd, observed_priors`,
`from .worker import PREVIEW_CHARS, worker_system`, and `CRITIC_TIER` from `acceptance`. If an import cycle appears
(`acceptance` or `worker` importing `gate`), define `CRITIC_TIER = "workhorse"` in `gate.py` with a test that it
equals `acceptance.CRITIC_TIER`, and record the ruling.

`config.py`: add `"critic_output_tokens", "fallback_tokens_per_question", "retry_prior", "critic_prior"` to
`_GATE_NUMBERS`, with a test in `core/tests/test_config.py` that `[gate] retry_prior = 0.4` parses into
`settings_from_config(config).retry_prior == 0.4` and an unknown `[gate]` key is still refused.

`runtime.py`: the Gate counts characters, as the worker receives text:
`self.gate = Gate(ledger, gateway, settings, clock, attachment_chars=lambda refs: sum(
len(self.artifacts.read(ref).decode("utf-8", errors="replace")) for ref in refs))`.

- [ ] **Step 4: Run gate, gateway and runtime tests**

Run: `.venv\Scripts\python.exe -m pytest core/tests/test_gate.py core/tests/test_gateway_decide.py core/tests/test_runtime.py core/tests/test_task_cli.py -q`
Expected: all pass. Existing tests that pin an estimate (search `estimate_usd`, `model_usd`, `budget_usd=0.0` in
`core/tests/`) may change; recompute each expected value from the formula, not from the test output, and record
each change as a ruling in the execution ledger.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/gate.py core/src/ooat_core/gateway.py core/src/ooat_core/runtime.py core/tests/test_gate.py core/tests/test_gateway_decide.py core/tests/test_runtime.py core/tests/test_task_cli.py
git commit -m "feat(core): the Gate's estimate counts blended output priors, attachments, the critic and a second attempt (plan 04d)"
```

---

### Task 3: Backtest through the real code, docs, operator prior

**Files:**
- Test: `core/tests/test_estimate.py` (backtest)
- Modify: `tasks/f1-skeleton/task-04-task-runtime/design.md` §4, `core/description.md`,
  `tasks/f1-skeleton/task-03d-gateway-hardening/task.md`

- [ ] **Step 1: Write the backtest** (it builds ledger-shaped events from the seed numbers and runs
  `observed_priors` and `expected_usd`; prices are workhorse 2 / 10 and economy 1 / 5 USD per 1M tokens, as
  `claude-sonnet-5-5` and `claude-haiku-4-5-20251001` in `catalog/routing.json`)

```python
SEED = [  # first worker input, worker outputs per attempt, critic output, fallback outputs (5 criteria), actual USD
    (3970, [3472], 872, [], 0.0580),
    (7461, [19363], 370, [], 0.2376),
    (5527, [19186, 18482], 382, [2993, 1610], 0.5074),
    (7375, [17805, 20166], 438, [], 0.4689),
    (1845, [5303], 392, [2215], 0.0857),
]


def seed_events(entries):
    events = []
    for _, outputs, critic_out, fallback, _ in entries:
        t = new_id("tsk")
        events.append({"type": "TASK_SUBMITTED", "task": t, "body": {"goal": "x"}})
        events += [{"type": "RESULT", "task": t, "actor": {"kind": "agent"}, "body": {"outcome": "DONE"},
                    "cost": {"tier": "workhorse", "tokens_out": o, "basis": "shadow"}} for o in outputs]
        events.append({"type": "GATE_PASSED", "task": t, "body": {"gate": "gate.critic.check_criterion"},
                       "cost": {"tier": "workhorse", "tokens_out": critic_out, "basis": "shadow"}})
        events += [{"type": "GATE_FAILED", "task": t, "body": {"gate": "gate.decision.check_criterion",
                                                                "criteria": [{}] * 5},
                    "cost": {"tier": "economy", "tokens_out": f, "basis": "shadow"}} for f in fallback]
        events.append({"type": "TASK_CLOSED", "task": t, "body": {}})
    return events


@pytest.mark.parametrize("prior_output, limit", [(2000, 3.5), (17800, 2.0)])
@pytest.mark.parametrize("index", range(5))
def test_leave_one_out_backtest_on_the_seed_runs(index, prior_output, limit):
    win, _, _, fallback, actual = SEED[index]
    defaults = Priors(prior_output, 400, 500, 0.25, 0.5, 0)
    priors = observed_priors(seed_events([s for i, s in enumerate(SEED) if i != index]), defaults)
    out = priors.output_tokens
    worker = win * 2e-6 + out * 10e-6
    critic = (win + out) * 2e-6 + priors.critic_output_tokens * 10e-6
    checks = ((win + out) * 1e-6 + priors.fallback_tokens_per_question * 5 * 5e-6) if fallback else 0.0003
    estimate = expected_usd(worker, checks, critic, priors, critic_certain=True)
    assert 1 / 8 <= actual / estimate <= limit  # today's estimates were 2.8 to 22 times too low
```

- [ ] **Step 2: Run it**

Run: `.venv\Scripts\python.exe -m pytest core/tests/test_estimate.py -q`
Expected: 17 passed. The hand computation gives actual/estimate 0.32, 1.6, 3.24, 3.34, 0.43 with the
2,000-token prior and 0.18, 0.81, 1.7, 1.72, 0.24 with 17,800. If the code's medians differ slightly (rounding),
the bounds still hold; if not, record a ruling with the measured values.

- [ ] **Step 3: Docs**
  - design 04 §4: the estimate is worker (with the attachment text the worker receives, at most 100,000 characters
    each) + decision checks + critic × its share (1 with an untrusted attachment or no decision route), times
    (1 + retry rate); the priors come from `[gate]` and are blended with the last 20 closed tasks, the prior weighted
    as 5 observations (spec §11), per `task_type` once it has 3 closed tasks; a fallback decision is priced at its
    observed output per question. The ledger is scanned on each Gate run: cheap for SQLite, a view for Postgres later.
  - `core/description.md`: add `estimate.py`.
  - 03d: tick "The pre-start estimate ignores attachments, the critic and a second attempt"; add "Hook approval
    fingerprints `hooks.json` only, not the scripts its commands call (Orca's `antigravity-hook.cmd`); a changed
    script runs without a new approval".

- [ ] **Step 4: Full suite and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass

```bash
git add core/tests/test_estimate.py tasks/f1-skeleton/task-04-task-runtime/design.md core/description.md tasks/f1-skeleton/task-03d-gateway-hardening/task.md
git commit -m "test(core): estimate backtest on the seed runs through observed_priors; docs (plan 04d)"
```

## After execution (operator, not code)

- In `C:\DATA_DEVELOPMENT\ooat-work\ooat.toml` add `[gate] expected_output_tokens = 17800`: the median first worker
  output of the five seed tasks, so the prior starts from this operator's measurement (backtest worst case 1.72×
  instead of 3.34×).

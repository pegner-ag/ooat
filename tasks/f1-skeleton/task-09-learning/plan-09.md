# Learning Loops (09) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OOAT learns from what the operator already does (ratings, taps, corrections) in four steps:
1. The **learning price list** is computed from the ledger. The Gate weighs each task by its chance of acceptance.
2. A **Differently** correction can become a memory item, with one tap.
3. A read-only **What it learns** section shows where OOAT fails.
4. Corrections and rejected tasks become **eval candidates**. The owner picks them. A measured run then guards every
   change of the reception.

Nothing changes OOAT by itself. Every new memory item needs the operator's tap. Every change of a prompt, card or
routing stays a pull request with an eval run (spec §9 Catalog governance).

**Architecture:**
- **New pure module `core/src/ooat_core/learning.py`.** It reads plain event dicts and stores nothing, like
  `thresholds.py` and `stats.py`. It computes:
  - `cost_card.observed` per capability × task type;
  - the acceptance probability the Gate uses;
  - the figures of the What it learns section.
- **The Gate** records `p_accept` and `eu_usd` on its candidate. Its "not worth its cost" rule compares the cost with
  the expected value.
- **The reception** may propose a `lesson` after a correction. A new tap `remember` stores it through `memory.note`.
  The web app and the chat bridge (SDK) label the new button.
- **New endpoint `GET /api/v1/learning`**, shown as a section of the Usage page.
- **`evals/candidates.py`** exports candidates from the ledger to a file outside the repository.
  `evals/reception/run.py` reads a folder of cases and can fail below a share.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest (`.venv/Scripts/python -m pytest -q -p no:cacheprovider`
from the repository root). The web app is plain JavaScript ES modules with JSDoc, checked by `npm run check` and
tested by `npm test` from `core/`, with no build step (ADR 0016). The SDK tests are in `sdk/python/tests`.

**Spec:** `spec/ooat-specification.md`:
- §1 point 5 (a learning price list);
- §6 (EU formula, step B);
- §9 Catalog governance;
- §11 Price-list calibration and Calibration set.

Also design 08 `tasks/f1-skeleton/task-08-reception/design.md` §4, §8, §11, ADR 0011 and ADR 0018.

## Global Constraints

- Only `ooat-core` writes to the ledger, and the ledger is append-only. `learning.py` only reads.
- `cost_card.observed` is never written by hand. In the repository, the card keeps `"observed": {"n": 0}`, and the
  values are computed (decision 1).
- Text above a reader's data class is never returned. Counts may be, but texts and task ids only within the cap
  (`views.within`).
- `actor.kind = hil` is built only in the allowed modules (`core/tests/test_hil.py`). The `remember` tap is handled
  in `reception/__init__.py`, which already builds the operator's actor for `todo`.
- Eval candidates are the owner's data. They never enter the repository until the owner has picked and sanitised
  them. The exporter refuses an output path inside the repository.
- No secrets anywhere: the exporter and the view never print a token, key or connector secret.
- No new dependency. Lines are at most 120 characters. Code, comments, docs and commits are in English, while Czech
  strings live in `cs.js` and `texts.py`.
- The working tree is CRLF. Use explicit git paths in every commit, never `git add -A`.

**Decisions this plan takes where the spec is silent** (for the owner's review):

1. **`cost_card.observed` is computed, not stored.** It is recomputed from the ledger on every read, as θ is
   (`thresholds.py`).
   - Writing it into `catalog/capabilities/*.json` would change a git-tracked file from the runtime. Every operator's
     values would then differ in the repository.
   - The card in the repository keeps `{"n": 0}`. `GET /api/v1/learning` returns the computed values.
   - `spec/README.md` ("changes only through `ooat-core`") holds as written.
2. **What counts in `p_accept` (spec §11, §8 abstention scoring).** It is counted per capability × task type, as a
   Beta distribution whose prior is the card's `prior.p_accept` weighted as 5 observations. Only rated tasks that ran
   a contract count:
   - a delivered task rated accepted counts as a success;
   - a delivered task rated rejected counts as a failure;
   - an abstained task rated rejected counts as a failure (a lazy abstention);
   - an abstained task rated accepted is not counted. A justified abstention is not scored as failure (spec §8).

   `p_abstain` is the share of closed runs that ended abstained. `p_silent` stays `null` until `DEFECT_FOUND`
   exists, which is outside this plan.
3. **The task type is `TASK_SUBMITTED.body.task_type`.** A task without one counts as `general`. In F1 every
   contract runs `cap.general.complete_task`, so in practice this is a single row per task type.
4. **The Gate weighs the value by `p_accept` (spec §6).**
   - The candidate records `p_accept` and, when the task has a value, `eu_usd = V × p_accept − model_usd`.
   - The rule that closes a task as "not worth its cost" fires when `eu_usd < 0`. Until now it fired when
     `model_usd > V`.
   - The HIL and silent-error terms of the formula are 0 in F1, because no HIL price or silent-error rate is
     measured yet.
   - With the card's prior of 0.7, a task is now closed when its cost exceeds 70 % of its value instead of 100 %.
     The default values (A 1,000, B 300, C 50 USD) are far above the cost of a T2 run, so in practice only tasks
     with a tiny explicit value are affected.
5. **A lesson is offered, never stored on its own.**
   - The reception's model may return `lesson: {kind, text, scope?}`, only when the batch it decides holds a
     Differently correction (a tap with `tap_text`). The code drops a lesson from any other batch, so the model's
     word alone never decides.
   - The lesson must be a lasting preference or fact in one short general sentence ("In this project, change only
     the visible text, never the code."), not the one-off change itself.
   - The reply gets a line "🧠 Zapamatovat si: …?" / "🧠 Remember: …?" and the button `remember`.
   - The tap stores it with `memory.note` as the operator's own item (actor `hil`, source the tap's message). A
     preference with `scope: operator` goes to the operator scope, and everything else to the project.
   - The cap of a token, the secret scan and the 20-preference limit apply as for any note.
   - The automatic `memory_notes` stay as they are. A lesson is never also a memory note.
6. **Spec changes (the owner's approval of this plan approves them):**
   - `spec/schemas/event.schema.json`: the tap pattern gains `remember`, and `body_reception_decided` gains `lesson`;
   - `spec/schemas/reception.schema.json`: the model's output gains `lesson`;
   - design 08 §8: the list of taps gains `remember`.

   No new event type is added.
7. **What it learns is a section of the Usage page, not a new page.** It is read through `GET /api/v1/learning`
   (scope `read`) over the whole ledger, without a period. It shows:
   1. the price list per capability × task type: n, p_accept with its prior, p_abstain;
   2. decision thresholds: per point, engine and model, the rated count, the share confirmed and θ. This covers both
      the Gate's and acceptance decisions and the reception;
   3. the reception's decisions by kind: how many, how many were followed by Differently, and for a task decision
      how many were cancelled within two minutes (`QUICK_CANCEL_S`, the same signals `reception_verdicts` uses);
   4. memory: notes stored by the reception and how many of them were forgotten later, and lessons offered and kept;
   5. the 10 latest tasks that need a look (rejected, or abstained and rated rejected), with their task ids and
      reasons, only within the reader's cap.

   Above the cap, only counts appear. It is the Exceptions view's learning half (spec §10). The rest of Exceptions
   is not part of this plan.
8. **The eval candidates are exported by a script the owner runs:**

   ```
   python evals/candidates.py --config ooat.toml --out <file outside the repository> [--max-class internal]
   ```

   It reads the ledger and writes one JSON file with two lists:
   - `reception`: a message that got a Differently, in the format of `evals/reception/run.py`, with `expected` left
     `null`, the reception's decision as `got`, the correction and the decision that followed;
   - `tasks`: a rejected task's goal, acceptance criteria and rating note, in the shape of
     `evals/calibration/seed/*.json` (without `attachments`).

   Texts above `--max-class` are left out and counted. The script writes nothing to the ledger, and it refuses an
   `--out` inside the repository. `load_cases` refuses a case whose `expected` is `null`, so a candidate can never be
   run by mistake before the owner has decided it.
9. **The regression run is the owner's, not CI's.**
   - The reception eval calls real connectors and costs money. CI holds no secrets (only the gateway does), so it
     cannot run it.
   - `run.py` gains `--cases <folder>` (every `*.json` in it) and `--min-expected <share>`, which exits with 1 below
     the share.
   - The owner's picked cases live in `evals/reception/cases/`. CI checks that every file there loads (a pytest
     test), and the README asks for a run with `--min-expected` before merging a change of the reception's prompt
     (spec §2 point 6: "no role or routing change goes live without an eval run").
   - This plan ships the folder with a `README.md` only. No case is invented.

## Review Focus

1. **An abstained task rated accepted** must leave `p_accept` unchanged. Test it in Task 1.
2. **The `remember` tap twice**: the second tap has no lesson on the last decision, so it is refused ("nothing to
   remember") and stores no second item. Test it in Task 3.
3. **A lesson above a token's cap, or a lesson that looks like a secret**: neither is offered, neither shows in the
   reply, and the tap stores nothing. Test it in Task 3.
4. **The learning view for a token capped at `internal`** shows counts of `personal` tasks but never their ids,
   goals or abstention reasons. Test it in Task 5.
5. **An `--out` inside the repository** (including `evals/` itself) is refused before anything is read. Test it in
   Task 6.

---

## File Structure

| File | Responsibility |
|---|---|
| `core/src/ooat_core/learning.py` (new) | `observed`, `p_accept`, `summary`: pure, over event dicts |
| `core/src/ooat_core/gate.py` | records `p_accept`/`eu_usd`; the value rule on EU |
| `core/src/ooat_core/reception/__init__.py`, `reception/model.py` | `lesson` kept only after a correction; tap `remember` |
| `spec/schemas/event.schema.json`, `spec/schemas/reception.schema.json` | `remember`, `lesson` |
| `core/src/ooat_core/conversation_endpoints.py`, `core/src/ooat_core/views.py` | tap pattern; `lesson` redacted above the cap |
| `core/src/ooat_core/endpoints.py` | `GET /api/v1/learning` |
| `core/src/ooat_core/web/app/conversation.js`, `views/usage.js`, `i18n/en.js`, `i18n/cs.js` | label `remember`; What it learns |
| `sdk/python/src/ooat_client/bridge.py`, `texts.py` | the chat button `remember` |
| `evals/candidates.py` (new), `evals/reception/run.py`, `evals/reception/cases/README.md` (new), `evals/reception/README.md` | candidates; regression run |
| `docs/description.md`, `tasks/f1-skeleton/README.md`, design 08 §8 | docs |

Tests: `core/tests/test_learning.py` (new), `core/tests/test_gate.py`, `core/tests/test_reception.py`,
`core/tests/test_api_conversations.py`, `core/tests/test_api_learning.py` (new), `core/tests/test_candidates.py`
(new), `core/tests/test_reception_eval.py`, `core/web-tests/conversation.test.mjs`,
`sdk/python/tests/test_ooat_bridge.py`.

---

### Task 1: The learning price list

**Files:**
- Create: `core/src/ooat_core/learning.py`
- Test: `core/tests/test_learning.py`

**Interfaces:**
- Produces:
  - `EVENTS: tuple[str, ...]`: the event types `observed` and `p_accept` need;
  - `GENERAL = "general"`;
  - `PRIOR_WEIGHT = 5`;
  - `@dataclass(frozen=True) class Observed: capability: str; task_type: str; n: int; accepted: int; prior: float;
    p_accept: float; runs: int; p_abstain: float | None` (with `p_silent` always `None`, as `as_dict()`);
  - `observed(events: Iterable[dict], priors: dict[str, float]) -> list[Observed]`, where `priors` maps a capability
    id to its card's `prior.p_accept`;
  - `p_accept(events: Iterable[dict], capability: str, task_type: str | None, prior: float) -> float`;
  - `card_prior(capability: str) -> float`, which reads `catalog.load_card("capabilities", capability)`, with 0.5
    when the card has no `prior.p_accept`.

- [ ] **Step 1: Write the failing tests**

```python
"""The learning price list from the ledger (spec §11 Price-list calibration; plan 09 decisions 1-3)."""

import pytest

from ooat_core.ids import new_id
from ooat_core.learning import GENERAL, card_prior, observed, p_accept

CAP = "cap.general.complete_task"


def run(state="CLOSED_DONE", accepted=None, task_type=None):
    """A task that ran one contract and closed; rated when `accepted` is given."""
    task, ctr = new_id("tsk"), new_id("ctr")
    body = {"goal": "x", **({"task_type": task_type} if task_type else {})}
    events = [{"id": new_id("evt"), "type": "TASK_SUBMITTED", "task": task, "ts": "2026-10-19T10:00:00Z",
               "body": body},
              {"id": new_id("evt"), "type": "CONTRACT_ISSUED", "task": task, "contract": ctr,
               "body": {"contract": {"id": ctr, "capability": CAP}}},
              {"id": new_id("evt"), "type": "TASK_CLOSED", "task": task, "body": {"state": state}}]
    if accepted is not None:
        events.append({"id": new_id("evt"), "type": "TASK_RATED", "task": task,
                       "body": {"accepted": accepted, "value_class": "B"}})
    return events


def test_without_ratings_p_accept_is_the_cards_prior():
    assert p_accept([], CAP, None, 0.7) == pytest.approx(0.7)


def test_each_rating_moves_the_beta_mean_weighted_against_five_prior_observations():
    events = run(accepted=True) + run(accepted=False) + run(accepted=False)
    # (0.7 * 5 + 1) / (5 + 3)
    assert p_accept(events, CAP, None, 0.7) == pytest.approx(4.5 / 8)


def test_a_justified_abstention_is_not_a_failure_and_a_lazy_one_is():
    justified = run("CLOSED_ABSTAINED", accepted=True)
    lazy = run("CLOSED_ABSTAINED", accepted=False)
    assert p_accept(justified, CAP, None, 0.7) == pytest.approx(0.7)
    assert p_accept(lazy, CAP, None, 0.7) == pytest.approx(3.5 / 6)


def test_unrated_runs_and_gate_closures_without_a_contract_count_only_where_they_belong():
    gate_closed = [e for e in run("CLOSED_ABSTAINED", accepted=False) if e["type"] != "CONTRACT_ISSUED"]
    events = run() + run("CLOSED_ABSTAINED") + gate_closed
    [row] = observed(events, {CAP: 0.7})
    assert (row.n, row.runs, row.p_abstain, row.p_accept) == (0, 2, 0.5, pytest.approx(0.7))


def test_task_types_are_separate_rows_and_a_task_without_one_is_general():
    events = run(accepted=True, task_type="copy") + run(accepted=False)
    rows = {r.task_type: r for r in observed(events, {CAP: 0.7})}
    assert set(rows) == {"copy", GENERAL} and rows["copy"].accepted == 1 and rows[GENERAL].accepted == 0
    assert p_accept(events, CAP, "copy", 0.7) == pytest.approx(4.5 / 6)


def test_the_cards_prior_is_read_from_the_catalog():
    assert card_prior(CAP) == pytest.approx(0.7)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider core/tests/test_learning.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'ooat_core.learning'`

- [ ] **Step 3: Write `learning.py`**

```python
"""What OOAT learns from the ledger (plan 09): the learning price list of spec §11 and the What it learns figures.

Nothing is stored. Like θ (thresholds.py), every figure is recomputed from the events on each read, so the card in
the repository keeps `"observed": {"n": 0}` and `cost_card.observed` changes only through ooat-core (plan 09
decision 1).
"""

from collections.abc import Iterable
from dataclasses import asdict, dataclass

from .catalog import load_card

EVENTS = ("TASK_SUBMITTED", "CONTRACT_ISSUED", "TASK_CLOSED", "TASK_RATED")
GENERAL = "general"  # the task type of a task submitted without one
PRIOR_WEIGHT = 5  # the card's prior counts as five observations (spec §11)
ABSTAINED = "CLOSED_ABSTAINED"


@dataclass(frozen=True)
class Observed:
    capability: str
    task_type: str
    n: int  # rated runs counted in p_accept
    accepted: int
    prior: float
    p_accept: float  # the Beta mean
    runs: int  # closed runs, rated or not
    p_abstain: float | None

    def as_dict(self) -> dict:
        return asdict(self) | {"p_silent": None}  # needs DEFECT_FOUND (spec §11), not recorded yet


def card_prior(capability: str) -> float:
    """The card's prior.p_accept; 0.5 when the card states none."""
    return load_card("capabilities", capability).get("cost_card", {}).get("prior", {}).get("p_accept", 0.5)


def _runs(events: Iterable[dict]) -> list[tuple[str, str, str, bool | None]]:
    """(capability, task type, closing state, accepted or None) of every closed task that ran a contract."""
    types, capability, closed, rated = {}, {}, {}, {}
    for event in events:
        task, body = event.get("task"), event["body"]
        if event["type"] == "TASK_SUBMITTED":
            types[task] = body.get("task_type") or GENERAL
        elif event["type"] == "CONTRACT_ISSUED":
            capability.setdefault(task, body["contract"]["capability"])
        elif event["type"] == "TASK_CLOSED":
            closed[task] = body["state"]
        elif event["type"] == "TASK_RATED":
            rated[task] = body["accepted"]
    return [(capability[t], types.get(t, GENERAL), state, rated.get(t)) for t, state in closed.items()
            if t in capability]


def _counted(state: str, accepted: bool | None) -> bool | None:
    """A success, a failure, or None when the run does not count (plan 09 decision 2): unrated, or an abstention the
    operator accepted as justified."""
    if accepted is None or (state == ABSTAINED and accepted):
        return None
    return accepted


def _beta_mean(successes: int, n: int, prior: float) -> float:
    return (prior * PRIOR_WEIGHT + successes) / (PRIOR_WEIGHT + n)


def p_accept(events: Iterable[dict], capability: str, task_type: str | None, prior: float) -> float:
    """The Beta mean of acceptance for one capability and task type."""
    wanted = task_type or GENERAL
    counted = [_counted(state, accepted) for cap, kind, state, accepted in _runs(events)
               if (cap, kind) == (capability, wanted)]
    counted = [c for c in counted if c is not None]
    return _beta_mean(sum(counted), len(counted), prior)


def observed(events: Iterable[dict], priors: dict[str, float]) -> list[Observed]:
    """One row per capability and task type that has closed runs, sorted by both."""
    groups: dict[tuple[str, str], list[tuple[str, bool | None]]] = {}
    for cap, kind, state, accepted in _runs(events):
        groups.setdefault((cap, kind), []).append((state, accepted))
    rows = []
    for (cap, kind), runs in sorted(groups.items()):
        counted = [c for c in (_counted(s, a) for s, a in runs) if c is not None]
        prior = priors.get(cap, 0.5)
        rows.append(Observed(cap, kind, len(counted), sum(counted), prior, _beta_mean(sum(counted), len(counted), prior),
                             len(runs), sum(s == ABSTAINED for s, _ in runs) / len(runs)))
    return rows
```

- [ ] **Step 4: Run them to see them pass**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider core/tests/test_learning.py`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/learning.py core/tests/test_learning.py
git commit -m "feat: the learning price list, p_accept per capability and task type from the ratings (09 task 1)"
```

### Task 2: The Gate weighs the value by p_accept

**Files:**
- Modify: `core/src/ooat_core/gate.py` (`Gate.run`, at the `candidates = [...]` line and the value check below it)
- Test: `core/tests/test_gate.py`

**Interfaces:**
- Consumes: `learning.EVENTS`, `learning.p_accept`, `learning.card_prior` (Task 1). The capability id is
  `"cap.general.complete_task"`. `gate.py` must not import `runtime.py`, which imports `gate.py`, so it uses the
  constant `WORKER_CAPABILITY = "cap.general.complete_task"` in `gate.py`, and `runtime.CAPABILITY` stays the single
  place the contract names it. Add a test that `gate.WORKER_CAPABILITY == runtime.CAPABILITY`.
- Produces: the T2 candidate `{"topology": "T2", "model_usd": e, "p_accept": p, "eu_usd": V*p - e}`, where `eu_usd`
  is present only when the task has a value.

- [ ] **Step 1: Write the failing tests** (append to the 04d section of `test_gate.py`)

```python
def test_the_candidate_records_p_accept_and_eu():
    setup = GateSetup()
    task = setup.submit(value={"usd": 100.0})
    setup.gate.run(task)
    [candidate] = setup.events(task, "TOPOLOGY_DECIDED")[-1]["body"]["candidates"]
    assert candidate["p_accept"] == pytest.approx(0.7)
    assert candidate["eu_usd"] == pytest.approx(100.0 * 0.7 - candidate["model_usd"])


def test_a_task_worth_less_than_its_cost_at_its_acceptance_is_closed():
    setup = GateSetup()
    for usd in (0.10, 0.10, 0.10, 0.10, 0.10):
        setup.closed_run(usd)
    task = setup.submit(value={"usd": 0.12})  # 0.12 > 0.10, but 0.7 * 0.12 = 0.084 < 0.10
    assert setup.gate.run(task).closed == "CLOSED_ABSTAINED"
    assert "expected value" in setup.events(task, "TASK_CLOSED")[0]["body"]["missing"]


def test_without_a_value_there_is_no_eu():
    setup = GateSetup()
    task = setup.submit()
    setup.gate.run(task)
    [candidate] = setup.events(task, "TOPOLOGY_DECIDED")[-1]["body"]["candidates"]
    assert "eu_usd" not in candidate and "p_accept" in candidate


def test_the_gate_names_the_capability_the_runtime_issues():
    from ooat_core import gate, runtime
    assert gate.WORKER_CAPABILITY == runtime.CAPABILITY
```

Also change the assertion of `test_a_task_that_costs_more_than_it_is_worth_is_closed_as_t0` from
`"exceeds the task value"` to `"expected value"`.

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider core/tests/test_gate.py -k "eu or worth or capability"`
Expected: FAIL (`KeyError: 'p_accept'`, the 0.12 task runs, `AttributeError: WORKER_CAPABILITY`)

- [ ] **Step 3: Implement**

In `gate.py`, add `from . import learning` to the imports. Below `ACTOR`, add:

```python
WORKER_CAPABILITY = "cap.general.complete_task"  # runtime.CAPABILITY; the runtime imports this module
```

Replace the two statements from `candidates = [{"topology": "T2", "model_usd": estimate}]` through the end of the
`if value is not None and estimate > value:` block with:

```python
        p = learning.p_accept(self._ledger.events(types=list(learning.EVENTS)), WORKER_CAPABILITY,
                              submitted["body"].get("task_type"), learning.card_prior(WORKER_CAPABILITY))
        candidate = {"topology": "T2", "model_usd": estimate, "p_accept": round(p, 4)}
        if value is not None:  # spec §6 with no HIL or silent-error term measured yet (plan 09 decision 4)
            candidate["eu_usd"] = value * p - estimate
        candidates = [candidate]
        if value is not None and candidate["eu_usd"] < 0:
            self._decided(task, "T0", rules, candidates, decided)
            missing = (f"the estimated cost {estimate:.4f} USD exceeds the task's expected value {value * p:.4f} USD "
                       f"(value {value:.2f} USD × acceptance {p:.2f})")
            return self._close(task, data_class, budget, "CLOSED_ABSTAINED", "Not run: not worth its cost.", missing,
                               estimate)
```

The two later `eliminated = [{"topology": "T2", "model_usd": estimate, ...}]` lists stay as they are.

- [ ] **Step 4: Run the Gate and runtime tests**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider core/tests/test_gate.py core/tests/test_runtime.py core/tests/test_stats.py`
Expected: all pass. `stats._tasks` reads `model_usd` from the candidates and is unaffected.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/gate.py core/tests/test_gate.py
git commit -m "feat: the Gate weighs a task's value by its observed acceptance, EU recorded on the candidate (09 task 2)"
```

### Task 3: A correction can become a memory item

**Files:**
- Modify: `spec/schemas/reception.schema.json` (property `lesson`), `spec/schemas/event.schema.json` (`$defs.tap`
  pattern, `body_reception_decided.properties.lesson`)
- Modify: `core/src/ooat_core/reception/model.py` (the system prompt: JSON keys and one rule)
- Modify: `core/src/ooat_core/reception/__init__.py` (`_act`, `_apply_tap`)
- Modify: `core/src/ooat_core/conversation_endpoints.py:29` (`TAP`), `core/src/ooat_core/views.py:174` (`_SAID`)
- Test: `core/tests/test_reception.py`, `core/tests/test_api_conversations.py`

**Interfaces:**
- Produces:
  - `RECEPTION_DECIDED.body.lesson = {"kind": "preference" | "fact" | "glossary", "text": str, "scope"?: "project" |
    "operator"}` and the button `"remember"`;
  - the tap `remember` answers with `{"decision": "answer", "memory": [id], "buttons": ["forget:<id>"]}`.

- [ ] **Step 1: Write the failing tests** (in `test_reception.py`, after
  `test_differently_with_a_correction_is_decided_like_a_message`)

```python
LESSON = {"kind": "preference", "text": "V tomto projektu měň jen viditelný text, nikdy kód."}


def corrected(desk, lesson=LESSON):
    """A confirm, then Differently with a correction, decided with a lesson."""
    desk.model.replies = [decision("confirm", "Mám začít?", confidence=0.5), decision("task", lesson=lesson)]
    body = desk.ask("Titulek.")["body"]
    desk.reception.tap(body["conversation"], "differently", operator="operator", channel="web",
                       text="Jen text titulku, kód nech být.")
    return desk.reception.decide(body["conversation"])["body"]


def test_after_a_correction_a_lesson_is_offered_and_stored_only_on_the_tap(tmp_path):
    desk = Desk(tmp_path)
    body = corrected(desk)
    assert body["lesson"] == LESSON and "remember" in body["buttons"] and LESSON["text"] in body["reply"]
    assert desk.events("MEMORY_NOTED") == []
    tapped = desk.reception.tap(body["conversation"], "remember", operator="operator", channel="web")
    noted = desk.events("MEMORY_NOTED")[0]
    assert noted["actor"] == {"kind": "hil", "id": "operator"} and noted["body"]["scope"] == "docs"
    assert tapped["decision"]["body"]["buttons"] == [f"forget:{noted['body']['memory']}"]
    with pytest.raises(ValueError, match="nothing to remember"):
        desk.reception.tap(body["conversation"], "remember", operator="operator", channel="web")
    assert len(desk.events("MEMORY_NOTED")) == 1


def test_a_lesson_without_a_correction_in_the_batch_is_dropped(tmp_path):
    desk = Desk(tmp_path, [decision("task", lesson=LESSON)])
    body = desk.ask("Změň titulek na Objednat.")["body"]
    assert "lesson" not in body and "remember" not in body["buttons"]


def test_an_operator_preference_goes_to_the_operator_scope(tmp_path):
    desk = Desk(tmp_path)
    body = corrected(desk, LESSON | {"scope": "operator"})
    desk.reception.tap(body["conversation"], "remember", operator="operator", channel="web")
    assert desk.events("MEMORY_NOTED")[0]["body"]["scope"] == memory.OPERATOR_SCOPE


def test_a_secret_lesson_is_never_offered_nor_stored(tmp_path):
    desk = Desk(tmp_path)
    body = corrected(desk, {"kind": "fact", "text": "heslo: Tajne123!"})
    assert "lesson" not in body and "Tajne123" not in body["reply"]
    with pytest.raises(ValueError, match="nothing to remember"):
        desk.reception.tap(body["conversation"], "remember", operator="operator", channel="web")
    assert desk.events("MEMORY_NOTED") == []


def test_a_lesson_above_the_tokens_cap_is_not_offered(tmp_path):
    from ooat_core import tokens
    from reception_fakes import NOW
    desk = Desk(tmp_path, [decision("confirm", "Mám začít?", confidence=0.5),
                           decision("task", lesson={"kind": "fact", "text": "Kontakt: jan.novak@example.cz"})])
    _, issued = tokens.issue(desk.ledger, operator="operator", name="telegram", scopes=["submit"],
                             max_data_class="internal", now=NOW)
    channel = f"token:{issued['body']['token']}"
    body = desk.ask("Titulek.", channel=channel)["body"]
    desk.reception.tap(body["conversation"], "differently", operator="operator", channel=channel, text="Jen text.")
    decided = desk.reception.decide(body["conversation"])["body"]
    assert "lesson" not in decided and "remember" not in decided["buttons"]
```

In `test_api_conversations.py`, add `"remember"` to the taps the endpoint accepts. Next to the existing test that
posts a `todo` tap, post `{"tap": "remember"}` on a conversation without a lesson and expect 400 with "nothing to
remember". Check how that test builds its conversation and reuse its helper.

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider core/tests/test_reception.py -k "lesson or remember"`
Expected: FAIL. The model's `lesson` key is refused by `reception.schema.json` (`Unusable`), or `unknown tap remember`.

- [ ] **Step 3: Schemas**

In `spec/schemas/reception.schema.json`, under `properties`, add:

```json
"lesson": {"type": "object", "required": ["kind", "text"], "additionalProperties": false, "properties": {
  "kind": {"enum": ["preference", "fact", "glossary"]},
  "text": {"type": "string", "minLength": 1, "maxLength": 300},
  "scope": {"enum": ["project", "operator"]}}}
```

In `spec/schemas/event.schema.json`:
- in `$defs.tap.pattern`, add `remember|` after `todo|`;
- in `$defs.body_reception_decided.properties`, add `"lesson"` with the same object as above, plus `"description":
  "Offered after a Differently correction; stored only by the remember tap (plan 09 decision 5)."`.

In `conversation_endpoints.py`, change `TAP` to:

```python
TAP = r"^(yes|differently|new_thing|make_task|todo|remember|(forget|done):mem_[0-7][0-9A-HJKMNP-TV-Z]{25})$"
```

In `views.py`, add `"lesson"` to `_SAID`, so a lesson above the reader's cap is stubbed like the reply.

- [ ] **Step 4: The prompt** (`reception/model.py`, the decision system prompt)

After the `"memory_notes"` rule, add:

```
- "lesson": only when the messages include a correction of your earlier reading (marked as Differently), and only
  when it shows something lasting about how this person or project wants work done: one short general sentence
  (kind preference, fact or glossary; scope "operator" for a preference about the person in every project). Never
  the one-off change itself, never personal data, never also a memory note. The person decides whether to keep it.
```

Add `lesson` to the line `JSON keys: ...` after `memory_notes [{kind, text, scope}]`, as `lesson {kind, text, scope}`.

Check how a Differently correction appears in the prompt. `conversations.message_text` returns the `tap_text`. If
the context does not mark it as a correction, prefix it there with `Differently: ` (in `reception/context.py`,
where the waiting messages are written into the prompt). Then assert the prefix in
`test_differently_with_a_correction_is_decided_like_a_message` (`"Differently: Myslím titulek v patičce."` in
`desk.model.calls[1].prompt`).

- [ ] **Step 5: `_act` keeps a lesson only after a correction, within the cap**

At the end of `_act`, before `return result`:

```python
        lesson = decision.get("lesson")
        corrected = any(m["body"].get("tap") == "differently" and m["body"].get("tap_text") for m in waiting)
        cap = self._channel_cap(waiting[-1]["body"]["channel"])
        if (lesson and corrected and self.store is not None and memory.looks_secret(lesson["text"]) is None
                and (cap is None or ORDER.index(raised_class(data_class, lesson["text"])) <= ORDER.index(cap))):
            result["lesson"] = lesson  # offered only: stored by the remember tap (plan 09 decision 5)
            result["reply"] = "\n\n".join([result["reply"], say(said, f"🧠 Zapamatovat si: {lesson['text']}?",
                                                                 f"🧠 Remember: {lesson['text']}?")])
            result["buttons"] = [*result["buttons"], "remember"][:12]
        return result
```

Check that `looks_secret` returns `None` for a clean text (`memory.py:68`). If it returns something else, adapt the
condition. A secret lesson is never offered. The tap's own `memory.note` still refuses a secret, as the second
guard.

- [ ] **Step 6: The tap**

In `_apply_tap`, before `elif tap.startswith(("forget:", "done:")):`, add:

```python
        elif tap == "remember":
            lesson = (last or {}).get("body", {}).get("lesson")
            if lesson is None or self.store is None:
                raise ValueError("there is nothing to remember")
            scope = memory.OPERATOR_SCOPE if lesson.get("scope") == "operator" and lesson["kind"] == "preference" \
                else found.project
            item = memory.note(self.ledger, self.store, scope=scope, kind=lesson["kind"], text=lesson["text"],
                               data_class=message["body"]["data_class"], source=message["id"],
                               actor={"kind": "hil", "id": operator}, conversation=found.id, channel=channel)
            decided |= {"decision": "answer", "memory": [item.id], "buttons": [f"forget:{item.id}"],
                        "reply": reply(f"🧠 Zapamatováno: {item.text}", f"🧠 Remembered: {item.text}")}
```

`last` is the newest non-replaced decision (`conversations.last_decision`). After the remember tap, it is the
"Remembered" decision, which has no lesson, so a second tap is refused.

- [ ] **Step 7: Run the reception, conversation API and HIL guard tests**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider core/tests/test_reception.py core/tests/test_api_conversations.py core/tests/test_conversation_events.py core/tests/test_hil.py core/tests/test_spec_examples.py`
Expected: all pass. If a test of the spec's valid examples lists the taps, add `remember` there as well.

- [ ] **Step 8: Commit**

```bash
git add spec/schemas/reception.schema.json spec/schemas/event.schema.json core/src/ooat_core/reception/model.py core/src/ooat_core/reception/__init__.py core/src/ooat_core/reception/context.py core/src/ooat_core/conversation_endpoints.py core/src/ooat_core/views.py core/tests/test_reception.py core/tests/test_api_conversations.py
git commit -m "feat: after a Differently correction the reception offers a lesson, stored by the remember tap (09 task 3)"
```

### Task 4: The button on the web and in the chat

**Files:**
- Modify: `core/src/ooat_core/web/app/conversation.js` (`LABELS`), `i18n/en.js`, `i18n/cs.js`
- Modify: `sdk/python/src/ooat_client/bridge.py:21` (`TAPS`), `sdk/python/src/ooat_client/texts.py` (`b_remember`,
  both languages), `sdk/python/src/ooat_client/client.py:225` (the docstring's list of taps)
- Test: `core/web-tests/conversation.test.mjs`, `sdk/python/tests/test_ooat_bridge.py`

**Interfaces:**
- Consumes: the button `"remember"` (Task 3).

- [ ] **Step 1: Write the failing tests**

In `conversation.test.mjs`, in the test "a tap is shown by its kind, …", add:

```js
  assert.equal(tapLabel("remember"), "conv.remember");
```

In `test_ooat_bridge.py`, next to `test_several_notes_get_numbered_forget_buttons`, add a test in the same style. A
posted decision with `"buttons": ["remember"]` shows one button labelled `Zapamatovat` (Czech texts) whose data is
`r:<conversation>`. Pressing it calls `client.tap(<conversation>, "remember")`. Use that test's stub client and
decision builder.

- [ ] **Step 2: Run them to see them fail**

Run: `cd core && npm test` and `.venv/Scripts/python -m pytest -q -p no:cacheprovider sdk/python/tests/test_ooat_bridge.py`
Expected: FAIL (`null` label; no button)

- [ ] **Step 3: Implement**

- `conversation.js` `LABELS`: add `remember: "conv.remember"`.
- `en.js`: `"conv.remember": "Remember"`; `cs.js`: `"conv.remember": "Zapamatovat"`.
- `bridge.py`: `TAPS = {"y": "yes", "d": "differently", "n": "new_thing", "t": "make_task", "o": "todo", "r": "remember"}`.
- `texts.py`: `"b_remember": "Remember"` (en) and `"b_remember": "Zapamatovat"` (cs), next to `b_todo`.
- `client.py:225`: the docstring lists `remember` after `todo`.

`views/conversation.js` needs no change: `remember` is not `forget` or `done`, so it is one of the conversation's
taps and is retired with them.

- [ ] **Step 4: Run all front-end and SDK checks**

Run: `cd core && npm run check && npm test`, then `.venv/Scripts/python -m pytest -q -p no:cacheprovider sdk/python/tests`
Expected: clean check, all pass.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/web/app/conversation.js core/src/ooat_core/web/app/i18n/en.js core/src/ooat_core/web/app/i18n/cs.js core/web-tests/conversation.test.mjs sdk/python/src/ooat_client/bridge.py sdk/python/src/ooat_client/texts.py sdk/python/src/ooat_client/client.py sdk/python/tests/test_ooat_bridge.py
git commit -m "feat: the Remember button on the web and in the chat bridge (09 task 4)"
```

### Task 5: What it learns

**Files:**
- Modify: `core/src/ooat_core/learning.py` (add `summary`)
- Modify: `core/src/ooat_core/endpoints.py` (route `GET /learning` in `resource_routes`, next to `/stats`)
- Modify: `core/src/ooat_core/web/app/views/usage.js`, `i18n/en.js`, `i18n/cs.js`
- Test: `core/tests/test_learning.py`, `core/tests/test_api_learning.py` (new)

**Interfaces:**
- Consumes: `observed`, `card_prior` (Task 1); `thresholds.rated_decisions`, `thresholds.reception_verdicts`,
  `thresholds.threshold`, `thresholds.reception_threshold`, `thresholds.QUICK_CANCEL_S`; `views.within`.
- Produces: `summary(events: list[dict], *, visible: Callable[[str], bool], reception_interim: float) -> dict`,
  where `visible(task)` says whether a task is within the reader's cap. It returns:

```python
{"price_list": [Observed.as_dict(), ...],
 "thresholds": [{"point": str, "engine": str, "model": str, "rated": int, "confirmed": int, "theta": float}, ...],
 "reception": [{"decision": str, "count": int, "differently": int, "cancelled": int}, ...],
 "memory": {"noted": int, "forgotten": int, "lessons_offered": int, "lessons_kept": int},
 "attention": [{"task": str, "state": str, "why": "rejected" | "lazy_abstention", "note": str | None}, ...]}
```

- [ ] **Step 1: Write the failing tests**

In `test_learning.py`:

```python
from ooat_core.learning import summary


def conversation(*steps):
    """Reception events of one conversation: ("decided", kind, extra) or ("tap", tap)."""
    cnv, events = new_id("cnv"), []
    for step in steps:
        if step[0] == "decided":
            events.append({"id": new_id("evt"), "type": "RECEPTION_DECIDED", "task": None, "ts": "2026-10-19T10:00:00Z",
                           "actor": {"kind": "system", "id": "ooat-reception"},
                           "body": {"conversation": cnv, "decision": step[1], **step[2]}})
        else:
            events.append({"id": new_id("evt"), "type": "CONVERSATION_MESSAGE", "task": None,
                           "ts": "2026-10-19T10:00:05Z", "actor": {"kind": "hil", "id": "operator"},
                           "body": {"conversation": cnv, "tap": step[1]}})
    return events


def test_reception_decisions_are_counted_with_the_differently_that_followed_them():
    events = conversation(("decided", "confirm", {}), ("tap", "differently"), ("decided", "task", {}),
                          ("decided", "escalated", {}), ("decided", "answer", {"lesson": {"kind": "fact", "text": "x"}}),
                          ("tap", "remember"))
    found = summary(events, visible=lambda task: True, reception_interim=0.8)
    rows = {r["decision"]: r for r in found["reception"]}
    assert rows["confirm"] == {"decision": "confirm", "count": 1, "differently": 1, "cancelled": 0}
    assert "escalated" not in rows  # a replaced call is not a decision the person saw
    assert found["memory"]["lessons_offered"] == 1 and found["memory"]["lessons_kept"] == 1


def test_a_rejected_task_needs_a_look_only_within_the_cap():
    shown, hidden = run(accepted=False), run(accepted=False)
    found = summary(shown + hidden, visible=lambda task: task == shown[0]["task"], reception_interim=0.8)
    assert [a["task"] for a in found["attention"]] == [shown[0]["task"]]
    assert found["price_list"][0]["n"] == 2  # counts include the task above the cap


def test_a_justified_abstention_does_not_need_a_look():
    found = summary(run("CLOSED_ABSTAINED", accepted=True), visible=lambda task: True, reception_interim=0.8)
    assert found["attention"] == []
```

`test_api_learning.py`: copy the server fixture of `test_api_conversations.py` (`served(tmp_path, ...)`). Then:
- a web session reads `GET /api/v1/learning` (200, keys `price_list`, `thresholds`, `reception`, `memory`,
  `attention`);
- a token without `read` gets 403;
- a token capped at `internal`, with one rejected `personal` task in the ledger, sees `price_list[0].n == 1` and
  `attention == []`.

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider core/tests/test_learning.py core/tests/test_api_learning.py`
Expected: FAIL (`ImportError: cannot import name 'summary'`, 404)

- [ ] **Step 3: Implement `summary`** (append to `learning.py`)

```python
from collections.abc import Callable

from .thresholds import (QUICK_CANCEL_S, RECEPTION_POINT, rated_decisions, reception_threshold, reception_verdicts,
                         threshold)

REPLACED = ("escalated", "retried")
ATTENTION = 10


def _thresholds(events: list[dict], reception_interim: float) -> list[dict]:
    rows: dict[tuple[str, str, str], list[bool]] = {}
    for rated in [*rated_decisions(events), *reception_verdicts(events)]:
        rows.setdefault((rated.point, rated.engine, rated.model), []).append(rated.correct)
    found = []
    for (point, engine, model), correct in sorted(rows.items()):
        theta = (reception_threshold(events, engine, model, reception_interim) if point == RECEPTION_POINT
                 else threshold(events, point, engine, model))
        found.append({"point": point, "engine": engine, "model": model, "rated": len(correct),
                      "confirmed": sum(correct), "theta": theta})
    return found


def _reception(events: list[dict]) -> tuple[list[dict], dict]:
    rows: dict[str, dict] = {}
    last: dict[str, dict] = {}  # conversation -> its newest decision the person saw
    cancelled = quick_cancels(events)
    offered = kept = 0
    for event in events:
        body = event["body"]
        if event["type"] == "RECEPTION_DECIDED" and body["decision"] not in REPLACED:
            row = rows.setdefault(body["decision"], {"decision": body["decision"], "count": 0, "differently": 0,
                                                     "cancelled": 0})
            row["count"] += 1
            row["cancelled"] += event["id"] in cancelled
            last[body["conversation"]] = row
            offered += "lesson" in body
        elif event["type"] == "CONVERSATION_MESSAGE" and body.get("tap") in ("differently", "remember"):
            if body["tap"] == "differently" and body["conversation"] in last:
                last.pop(body["conversation"])["differently"] += 1
            kept += body["tap"] == "remember"
    return sorted(rows.values(), key=lambda r: (-r["count"], r["decision"])), {"lessons_offered": offered,
                                                                              "lessons_kept": kept}
```

Import `quick_cancels` together with the other names from `.thresholds`. It is new: the quick-cancel rule moves out
of `reception_verdicts` into its own function, so both places use one definition. In `thresholds.py`:

```python
def quick_cancels(events: Iterable[dict]) -> set[str]:
    """Ids of the reception's task decisions whose task the operator cancelled within QUICK_CANCEL_S of its
    submission: the task was not what the person meant."""
    started, submitted, found = {}, {}, set()
    for event in events:
        body = event["body"]
        if (event["type"] == "RECEPTION_DECIDED" and body["decision"] in ("task", "continue_task")
                and body.get("task")):
            started[body["task"]] = event["id"]
        elif event["type"] == "TASK_SUBMITTED":
            submitted[event["task"]] = event["ts"]
        elif (event["type"] == "DECISION" and event["actor"]["kind"] == "hil" and event["task"] in started
              and body["decision"] == "cancel the task" and event["task"] in submitted
              and (_utc(event["ts"]) - _utc(submitted[event["task"]])).total_seconds() <= QUICK_CANCEL_S):
            found.add(started[event["task"]])
    return found
```

`reception_verdicts` keeps its own `started` map, which holds only decisions with a `record`, since only those can be
verdicts. Its `DECISION` branch is replaced by one step after its loop:

```python
    for decision_id in quick_cancels(events):
        decision = by_id.get(decision_id)  # by_id: the RECEPTION_DECIDED events with a record, built in the loop
        if decision is not None:
            verdicts[decision_id] = (decision, False)  # a quick cancel outweighs a later accepted rating
```

In the loop's `TASK_RATED` branch, `setdefault` stays. A cancel always comes before the rating, which follows the
close. The cancel now overrides the rating explicitly, which gives the same result. `core/tests/test_thresholds.py`
must pass unchanged. That is the check of the extraction.

Then the remaining parts:

```python
def _memory(events: list[dict]) -> dict:
    noted = {e["body"]["memory"] for e in events if e["type"] == "MEMORY_NOTED" and e["actor"]["kind"] == "system"}
    forgotten = {e["body"]["memory"] for e in events if e["type"] == "MEMORY_FORGOTTEN"} & noted
    return {"noted": len(noted), "forgotten": len(forgotten)}


def _attention(events: list[dict], visible: Callable[[str], bool]) -> list[dict]:
    closed = {e["task"]: e["body"]["state"] for e in events if e["type"] == "TASK_CLOSED"}
    found = []
    for event in events:
        if event["type"] != "TASK_RATED" or event["body"]["accepted"] or not visible(event["task"]):
            continue
        state = closed.get(event["task"], "")
        found.append({"task": event["task"], "state": state,
                      "why": "lazy_abstention" if state == ABSTAINED else "rejected", "note": event["body"].get("note")})
    return found[-ATTENTION:][::-1]


def summary(events: list[dict], *, visible: Callable[[str], bool], reception_interim: float) -> dict:
    """The What it learns figures (plan 09 decision 7). Counts cover every task; texts and ids only `visible` ones."""
    caps = {e["body"]["contract"]["capability"] for e in events if e["type"] == "CONTRACT_ISSUED"}
    reception, lessons = _reception(events)
    return {"price_list": [r.as_dict() for r in observed(events, {c: card_prior(c) for c in caps})],
            "thresholds": _thresholds(events, reception_interim), "reception": reception,
            "memory": _memory(events) | lessons, "attention": _attention(events, visible)}
```

The rating's `note` is the operator's own text, written for the task. It is shown only for a visible task.

- [ ] **Step 4: The endpoint** (in `resource_routes`, after `/stats`)

```python
    @api.get("/learning")
    def learning_view(request: Request, who: Principal = Depends(scope("read"))) -> dict:
        server = server_of(request)
        tasks = submitted_tasks(server)
        visible = {t for t, c in task_classes(server, tasks).items() if views.within(c, who.max_data_class)}
        return learning.summary(server.runtime().ledger.events(), visible=visible.__contains__,
                                reception_interim=server.config.reception.theta)
```

Add `from . import learning` to the imports of `endpoints.py`.

- [ ] **Step 5: The Usage page section**

In `usage.js`, after the existing figures in `draw()`, fetch `/learning` once (it has no period) and append an
`h("section", {}, h("h2", {}, t("learn.title")), ...)` holding:
- a table "price list" (capability, task type, n, p_accept as `percent`, prior as `percent`, p_abstain);
- a table "thresholds" (point, engine/model, rated, confirmed, θ);
- a table "reception" (decision via `t("learn.kind." + decision)` falling back to the raw kind, count, Differently,
  cancelled);
- one line of memory figures: `t("learn.memory", {...})`;
- a list "needs a look": each item links to `/tasks/<id>` (`data-route`) with `t("learn.why." + why)` and the note.

When a list is empty, show `t("learn.empty")`.

Build every element with `h()`. Add the keys `learn.*` to `en.js` and `cs.js` with the same keys in both:
- `learn.title`: "What it learns" / "Co se učí";
- `learn.priceList`, `learn.thresholds`, `learn.reception`, `learn.attention`;
- `learn.memory`: "Notes: {noted}, forgotten later {forgotten}; lessons offered {offered}, kept {kept}";
- `learn.why.rejected`, `learn.why.lazy_abstention`;
- `learn.empty`;
- the column headers.

- [ ] **Step 6: Run everything this task touches**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider core/tests/test_learning.py core/tests/test_api_learning.py core/tests/test_thresholds.py core/tests/test_web.py`, then `cd core && npm run check && npm test`
Expected: all pass, clean check.

- [ ] **Step 7: Look at it in the browser**

Start the throwaway server from the scratchpad (`serve08b.py` from 08b, port 8799) with a ledger holding two rated
tasks and a corrected conversation. Open `/usage` at phone width and desktop width, and check that the section
renders and that the task links open. Do not use the production server.

- [ ] **Step 8: Commit**

```bash
git add core/src/ooat_core/learning.py core/src/ooat_core/thresholds.py core/src/ooat_core/endpoints.py core/src/ooat_core/web/app/views/usage.js core/src/ooat_core/web/app/i18n/en.js core/src/ooat_core/web/app/i18n/cs.js core/tests/test_learning.py core/tests/test_api_learning.py
git commit -m "feat: What it learns on the Usage page - price list, thresholds, the reception's corrections, tasks to look at (09 task 5)"
```

### Task 6: Eval candidates and the regression run

**Files:**
- Create: `evals/candidates.py`, `evals/reception/cases/README.md`
- Modify: `evals/reception/run.py` (`--cases` file or folder, `--min-expected`), `evals/reception/README.md`
- Test: `core/tests/test_candidates.py` (new), `core/tests/test_reception_eval.py`

**Interfaces:**
- Produces:
  - `candidates.reception_candidates(events: list[dict], max_class: str) -> tuple[list[dict], int]`, which returns
    the cases and how many were left out above `max_class`;
  - `candidates.task_candidates(events: list[dict], max_class: str, artifact_class: Callable[[str], str]) ->
    tuple[list[dict], int]`;
  - `candidates.checked_out(path: Path, repo: Path) -> Path`, which raises `ValueError` inside the repository;
  - `run.load_folder(path: Path) -> list[dict]`;
  - `run.main` exits with 1 when `as_expected < --min-expected`.

- [ ] **Step 1: Write the failing tests** (`core/tests/test_candidates.py`)

Load `evals/candidates.py` the way `test_reception_eval.py` loads `run.py` (check its import lines and copy them).

```python
"""Eval candidates from the ledger (plan 09 decision 8)."""

import json
from pathlib import Path

import pytest

from ooat_core.ids import new_id

REPO = Path(__file__).resolve().parents[2]


def message(cnv, text=None, tap=None, tap_text=None, data_class="internal"):
    body = {"conversation": cnv, "project": "docs", "channel": "web", "data_class": data_class}
    body |= {k: v for k, v in (("text", text), ("tap", tap), ("tap_text", tap_text)) if v is not None}
    return {"id": new_id("evt"), "type": "CONVERSATION_MESSAGE", "task": None, "body": body}


def decided(cnv, message_ids, kind, reply="Mám začít?", options=(), data_class="internal"):
    return {"id": new_id("evt"), "type": "RECEPTION_DECIDED", "task": None, "body": {
        "conversation": cnv, "project": "docs", "messages": message_ids, "decision": kind, "reply": reply,
        "options": list(options), "buttons": [], "context": [], "data_class": data_class}}


def test_a_message_corrected_by_differently_is_a_case_with_expected_left_empty(candidates):
    cnv = new_id("cnv")
    first = message(cnv, text="Ahoj.")
    hello = decided(cnv, [first["id"]], "answer", reply="Dobrý den.")
    asked = message(cnv, text="Titulek.")
    confirm = decided(cnv, [asked["id"]], "confirm")
    tap = message(cnv, tap="differently", tap_text="Jen v patičce.")
    after = decided(cnv, [tap["id"]], "task", reply="Dělám na tom.")
    cases, left_out = candidates.reception_candidates([first, hello, asked, confirm, tap, after], "internal")
    assert left_out == 0
    assert cases == [{"text": "Titulek.", "expected": None, "got": "confirm", "correction": "Jen v patičce.",
                      "then": "task", "context": [{"person": "Ahoj.", "reception": "Dobrý den."}]}]


def test_a_case_above_the_max_class_is_left_out_and_counted(candidates):
    cnv = new_id("cnv")
    asked = message(cnv, text="Jan Novák", data_class="personal")
    events = [asked, decided(cnv, [asked["id"]], "confirm", data_class="personal"),
              message(cnv, tap="differently")]
    assert candidates.reception_candidates(events, "internal") == ([], 1)


def test_an_out_path_inside_the_repository_is_refused(candidates):
    for inside in (REPO / "evals" / "x.json", REPO / "x.json"):
        with pytest.raises(ValueError, match="outside the repository"):
            candidates.checked_out(inside, REPO)
    assert candidates.checked_out(REPO.parent / "x.json", REPO) == (REPO.parent / "x.json").resolve()


def test_a_rejected_task_is_a_task_candidate_without_attachments(candidates):
    task = new_id("tsk")
    events = [{"id": new_id("evt"), "type": "TASK_SUBMITTED", "task": task, "refs": [],
               "body": {"goal": "Shrň smlouvu.", "acceptance": ["Nejvýše 300 slov."], "data_class": "internal"}},
              {"id": new_id("evt"), "type": "TASK_CLOSED", "task": task, "body": {"state": "CLOSED_DONE"}},
              {"id": new_id("evt"), "type": "TASK_RATED", "task": task,
               "body": {"accepted": False, "value_class": "B", "note": "Moc dlouhé."}}]
    cases, left_out = candidates.task_candidates(events, "internal", artifact_class=lambda ref: "internal")
    assert left_out == 0
    assert cases == [{"task": task, "goal": "Shrň smlouvu.", "acceptance": ["Nejvýše 300 slov."],
                      "state": "CLOSED_DONE", "note": "Moc dlouhé.", "value_class": "B"}]
```

The `candidates` fixture loads the module, the same way the existing eval test loads `run.py`.

In `test_reception_eval.py`, add:

```python
def test_a_candidate_with_no_expected_decision_is_refused(run):
    with pytest.raises(ValueError, match="case 1: expected"):
        run.load_cases(json.dumps([{"text": "x", "expected": None}]))


def test_a_folder_of_cases_is_read_in_name_order(run, tmp_path):
    (tmp_path / "b.json").write_text(json.dumps([{"text": "b", "expected": "task"}]), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps([{"text": "a", "expected": "ask"}]), encoding="utf-8")
    assert [c["text"] for c in run.load_folder(tmp_path)] == ["a", "b"]


def test_the_committed_cases_load(run):
    folder = Path(run.__file__).parent / "cases"
    if any(folder.glob("*.json")):
        run.load_folder(folder)
```

Use the fixture name that `test_reception_eval.py` already uses for the loaded module.

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider core/tests/test_candidates.py core/tests/test_reception_eval.py`
Expected: FAIL (no `evals/candidates.py`; no `load_folder`)

- [ ] **Step 3: Write `evals/candidates.py`**

```python
"""Eval candidates from the operator's ledger (plan 09 decision 8).

    python evals/candidates.py --config ooat.toml --out ../reception-candidates.json [--max-class internal]

Two lists, for the owner to pick from and sanitise:
- reception: every message whose decision got a Differently, in the cases format of evals/reception/run.py with
  `expected` left empty (the owner writes it), the decision it got, the correction and the decision that followed;
- tasks: every task rated rejected, its goal, criteria, closing state and rating note (no attachments).

It reads the ledger and writes only `--out`, which must lie outside the repository: candidates are the operator's
data until the owner has picked them. Texts above `--max-class` are left out and counted.
"""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ORDER = ("public", "internal", "client_confidential", "personal", "special_category")
REPLACED = ("escalated", "retried")


def _within(data_class: str, cap: str) -> bool:
    return ORDER.index(data_class) <= ORDER.index(cap)


def checked_out(path: Path, repo: Path = REPO) -> Path:
    resolved = path.resolve()
    if resolved == repo or repo in resolved.parents:
        raise ValueError(f"write the candidates outside the repository ({repo})")
    return resolved


def _said(event: dict) -> str | None:
    body = event["body"]
    return body.get("text") or (body.get("tap_text") if body.get("tap") == "differently" else None)


def reception_candidates(events: list[dict], max_class: str) -> tuple[list[dict], int]:
    by_id = {e["id"]: e for e in events}
    turns: dict[str, list[dict]] = {}  # conversation -> its turns so far: {"person", "reception", "options"}
    shown: dict[str, dict] = {}  # conversation -> the newest decision the person saw
    open_case: dict[str, dict] = {}  # conversation -> a case waiting for the decision after its correction
    cases, left_out = [], 0
    for event in events:
        body, cnv = event["body"], event["body"].get("conversation")
        if event["type"] == "RECEPTION_DECIDED" and body["decision"] not in REPLACED:
            if cnv in open_case:
                open_case.pop(cnv)["then"] = body["decision"]
            person = " ".join(_said(by_id[m]) or "" for m in body["messages"] if m in by_id).strip()
            turns.setdefault(cnv, []).append({"person": person, "reception": body.get("reply"),
                                              "options": body.get("options", []), "_decided": event})
            shown[cnv] = event
        elif event["type"] == "CONVERSATION_MESSAGE" and body.get("tap") == "differently" and cnv in shown:
            wrong = shown.pop(cnv)
            classes = [wrong["body"]["data_class"], body["data_class"],
                       *(by_id[m]["body"]["data_class"] for m in wrong["body"]["messages"] if m in by_id)]
            history = turns[cnv]
            if not all(_within(c, max_class) for c in classes) or not isinstance(history[-1]["reception"], str):
                left_out += 1
                continue
            context = [{k: v for k, v in t.items() if k != "_decided" and (k != "options" or v)} for t in history[:-1]]
            case = {"text": history[-1]["person"], "expected": None, "got": wrong["body"]["decision"],
                    "correction": body.get("tap_text"), "then": None, "context": context}
            cases.append(case)
            open_case[cnv] = case
    return cases, left_out
```

Context turns above `max_class` would leak through `context`. Leave out a whole case when any earlier turn of its
conversation was above `max_class`: also collect the classes of `history[:-1]`'s decisions (`t["_decided"]`) into
`classes`. Then add a test for it: an earlier `personal` turn leaves the case out.

```python
def task_candidates(events: list[dict], max_class: str, artifact_class: Callable[[str], str]) -> tuple[list[dict], int]:
    submitted = {e["task"]: e for e in events if e["type"] == "TASK_SUBMITTED"}
    closed = {e["task"]: e["body"]["state"] for e in events if e["type"] == "TASK_CLOSED"}
    cases, left_out = [], 0
    for event in events:
        if event["type"] != "TASK_RATED" or event["body"]["accepted"] or event["task"] not in submitted:
            continue
        task = submitted[event["task"]]
        classes = [task["body"].get("data_class", "internal"), *(artifact_class(r) for r in task.get("refs", []))]
        if not all(_within(c, max_class) for c in classes):
            left_out += 1
            continue
        cases.append({"task": event["task"], "goal": task["body"]["goal"],
                      "acceptance": task["body"].get("acceptance", []), "state": closed.get(event["task"]),
                      "note": event["body"].get("note"), "value_class": event["body"]["value_class"]})
    return cases, left_out
```

A task's text can be raised above its declared class by the Gate. Use the class the server computes for it
(`views.task_class`, as `endpoints.task_classes` does) in `main`, instead of the declared class alone. Pass it in as
a `task_class(task) -> str` callable, and update the signature and the test accordingly. If `views.task_class`
needs settings, build them as `endpoints.task_classes` does.

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-class", default="internal", choices=ORDER)
    args = parser.parse_args(argv)
    out = checked_out(args.out)
    from ooat_core.config import load_config
    from ooat_core.ledger import Ledger
    config = load_config(args.config)
    ledger = Ledger.open(config.ledger_url)
    events = ledger.events()
    reception, left_reception = reception_candidates(events, args.max_class)
    tasks, left_tasks = task_candidates(events, args.max_class, lambda ref: ledger.artifact(ref)["data_class"])
    out.write_text(json.dumps({"reception": reception, "tasks": tasks}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"{len(reception)} reception and {len(tasks)} task candidates written to {out}; "
          f"{left_reception + left_tasks} left out above {args.max_class}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Check the real names before writing `main`:
- how `evals/reception/run.py` opens the config and the ledger (copy its imports and calls);
- `Ledger.open` with the config's ledger URL;
- `ledger.artifact(ref)["data_class"]`, as `endpoints.task_classes` uses it.

- [ ] **Step 4: `run.py`**

- `load_cases`: the `expected` check already refuses `None` (it is not in `DECISIONS`), and the test pins it.
- Add the following, and allow the extra keys `got`, `correction` and `then` in a case (ignored when running), so a
  picked candidate can be committed as it is once `expected` is written:

```python
def load_folder(path: Path) -> list[dict]:
    """Every case of the *.json files of a folder, in file-name order."""
    cases = []
    for file in sorted(path.glob("*.json")):
        try:
            cases += load_cases(file.read_text(encoding="utf-8"))
        except ValueError as error:
            raise ValueError(f"{file.name}: {error}") from None
    return cases
```

- In `main`, `--cases` takes a file or a folder (`load_folder` when `Path(args.cases).is_dir()`). Add
  `--min-expected` (float, default `None`). After printing the figures:
  `return 1 if args.min_expected is not None and figures["as_expected"] < args.min_expected else 0`. Read `main`
  first and keep its printing as it is.

- [ ] **Step 5: Docs of the eval folder**

`evals/reception/cases/README.md`:

```markdown
# The owner's reception cases

Cases picked by the owner from `evals/candidates.py` output, with anything sensitive removed and `expected` written.
Every `*.json` here is one list in the format of `../run.py`. CI checks that each file loads; it never runs them,
since a run calls real connectors.

Before merging a change of the reception's prompt or routing, run:

    python evals/reception/run.py --config ooat.toml --cases evals/reception/cases --min-expected 0.8

and put its three figures in the pull request.
```

In `evals/reception/README.md`, add a paragraph "Growing the set" with the two commands (candidates, then the folder
run) and the rule that candidates stay outside the repository until picked.

- [ ] **Step 6: Run the eval tests**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider core/tests/test_candidates.py core/tests/test_reception_eval.py`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add evals/candidates.py evals/reception/run.py evals/reception/README.md evals/reception/cases/README.md core/tests/test_candidates.py core/tests/test_reception_eval.py
git commit -m "feat: eval candidates from corrections and rejected tasks, a folder of picked cases with a minimum share (09 task 6)"
```

### Task 7: Docs

**Files:**
- Modify: `docs/description.md` (the reception, memory, web app and evals paragraphs), `tasks/f1-skeleton/README.md`
  (row 09), `tasks/f1-skeleton/task-08-reception/design.md` §8 (the tap `remember`)

- [ ] **Step 1:** In `docs/description.md`, describe as-is:
  - the learning price list (computed, never stored; it feeds the Gate's EU);
  - the lesson after a correction and the Remember tap;
  - What it learns on the Usage page;
  - `evals/candidates.py` and the cases folder.

  Keep the existing style: present tense, no history.
- [ ] **Step 2:** In `tasks/f1-skeleton/README.md`, add the row
  `| 09 | Learning loops: price list from ratings, lessons from corrections, What it learns, eval candidates — plan: task-09-learning/plan-09.md | 04, 08 | plan |`.
  Set the last column to `done` after the merge.
- [ ] **Step 3:** In design 08 §8, add `remember` to the list of taps, with one sentence: "offered after a Differently
  correction; stores the reception's lesson as the operator's memory item (plan 09)".
- [ ] **Step 4: Full verification**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider`, then `cd core && npm run check && npm test`
Expected: all pass (about 1,450 tests), clean check

- [ ] **Step 5: Commit**

```bash
git add docs/description.md tasks/f1-skeleton/README.md tasks/f1-skeleton/task-08-reception/design.md
git commit -m "docs: learning loops (09 task 7)"
```

## After the merge (owner's go only)

- Pull into production, then restart `OoatServe` and the bot (`TelegramClaudeBot`), which loads the SDK's new
  button. Both restarts need the owner's confirmation. The Scheduled Tasks keep LogonType Password.
- Test in Telegram:
  1. a vague message, then Differently with a correction that states a habit;
  2. the reply offers "🧠 Zapamatovat si: …?" and the button Zapamatovat;
  3. the item appears on the project's Memory page.
- The first candidates export is the owner's, to a path outside the repository.

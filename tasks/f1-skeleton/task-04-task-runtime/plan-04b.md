# Topology Gate T0–T2 (04b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decide for every submitted task whether it runs as T2 (one worker), needs the operator first (clarification or budget), or does not run at all (T0) — with the decision tier answering step A, thresholds calibrated from the operator's ratings, a local personal-data pre-scan in the gateway, and a cost estimate before anything runs.

**Architecture:** Three small modules and one gateway change. `pii.py` scans outgoing text for personal data with a checkable form; the gateway runs it in `_route()`, so every model and decision request is raised to `personal` before a connector is chosen. `thresholds.py` computes θ per decision point, engine and model version from decision records and `TASK_RATED` verdicts in the ledger. `gate.py` holds `Gate.run(task)`: it reads the task and the operator's earlier answers (`task_facts()`), asks one decision batch (A1 per criterion, A4, A5, A7, A10), acts only on answers at or above θ, estimates worker plus acceptance checks, and appends `TOPOLOGY_DECIDED` plus, when needed, a `HIL_REQUEST` or `TASK_CLOSED`. Nothing runs the worker yet (04c).

**Tech Stack:** Python 3.12+ standard library (`re`, `dataclasses`), pytest.

**Spec:** `tasks/f1-skeleton/task-04-task-runtime/design.md` §4 and §7; ADR 0011 (θ schedule, guardrails); ADR 0009 (CLARIFYING returns to SUBMITTED); spec §4 step A (rules A1–A10), §6 (decision points), §9 (data classes); plan 04a (decision layer, merged).

## Global Constraints

- `ooat-core` stays vendor-neutral; the Gate talks only to `Gateway` (no connector imports).
- Only `ooat-core` writes the ledger, append-only. Gate events use the actor `{"kind": "system", "id": "ooat-gate"}`; it never writes `actor.kind = hil`.
- The data class is never lowered below the declared one; the pre-scan and a confident A10 can only raise it (ADR 0011).
- A decision acts alone only when its confidence reaches θ: interim 0.8 for a decision connector, 1 for the text-model fallback, until 5 rated decisions exist for the key (point, engine, model version); then max(0.8, θ_computed) until 20 ratings; then θ_computed. θ_computed is the smallest θ on 0.50–0.99 (step 0.01) with at least 5 rated decisions at or above it and an error rate at most ε (R0 5 %, R1 2 %); none qualifies → 1. R2 and R3 never act alone (θ = 1).
- At most 3 clarifying questions per task (spec A1, ADR 0009); a clarifying answer returns the task to SUBMITTED.
- Every Gate `HIL_REQUEST` is blocking and defaults to `do_not_run` on silence.
- Value classes A = 1000, B = 300, C = 50 USD; `v_min` = 15 USD (A3); default task budget 2 USD; output prior 2,000 tokens; HIL deadline 24 h — all in `GateSettings`, read from `ooat.toml` in 04c.
- Every cost the Gate causes is in the ledger: the successful decision call on `TOPOLOGY_DECIDED.cost`, a charged failure on a `DECISION` event.
- Code, comments and docs in English; lines at most 120 characters.

**Decisions this plan takes within the design** (the owner may overrule them):
1. The budget question offers "raise the budget" and "do not run", not "narrow the scope": a GATED task has no path back to the Gate (ADR 0009 covers CLARIFYING only); the operator narrows by submitting a new task.
2. A10 is one choice question over the five data classes (the design listed a choice and a noul; the choice already answers both).
3. Route and value are checked before A1, so a task that can never run, or is not worth its cost, is closed without asking the operator anything.
4. A task without acceptance criteria asks the operator without calling any model; the operator's clarifications then become its criteria.
5. The estimate covers one attempt (worker plus acceptance checks); a retry in 04c is not included.
6. The pre-scan runs in the gateway for every request, also the worker's (review of PR #8: data classes are enforced in the gateway). With the reference `routing.json`, which requires a provider contract for `personal`, a task whose text contains an e-mail address, phone number or similar is therefore closed as "no permitted route" until the operator changes the policy or removes the data.

## Review Focus

1. A long attachment (100k characters) must be scanned in well under a second — `test_a_long_attachment_is_scanned_in_linear_time` (Task 1).
2. Ordinary business numbers (amounts, order numbers, dates) must not be taken for personal data — `test_ordinary_business_text_is_not_flagged` (Task 1).
3. A task that can never run must be closed without bothering the operator — `test_a_task_without_a_permitted_route_is_closed_without_running` (Task 3, order fixed in Task 4).
4. Silence on a Gate question must mean "do not run" — `test_do_not_run_or_silence_cancels_the_task` (Task 4).
5. A text model's self-stated confidence must never act alone before it is rated — `test_personal_data_found_by_the_pre_scan_raises_the_class_and_keeps_the_task_off_jev` (Tasks 3–4), `test_before_five_ratings_jev_uses_the_interim_threshold_and_the_fallback_never_acts_alone` (Task 2).
6. A failed decision tier must make the Gate ask, never guess — `test_a_failed_decision_tier_makes_the_gate_ask_instead_of_guessing` (Task 4).

---

## File Structure

```
core/src/ooat_core/pii.py              scan(), raised_class(), higher_class() (Task 1)
core/src/ooat_core/gateway.py          pre-scan before routing (Task 1)
core/src/ooat_core/thresholds.py       rated_decisions(), computed_threshold(), threshold() (Task 2)
core/src/ooat_core/gate.py             Gate.run(), GateSettings, GateOutcome (Task 3); task_facts(), clarification,
                                       budget question, gated_data_class() (Task 4)
core/tests/test_pii.py, test_gateway_decide.py, test_thresholds.py, test_gate.py
core/description.md, docs/description.md, README.md, .claude/lessons.md (Task 5)
```

How to apply a "replace" step: the old text occurs exactly once; replace it with the new text. Files may have CRLF line endings on Windows — match the text, not the line endings. Work on a branch `feat/topology-gate` from `main`; run commands from the repository root with the project virtual environment active.

---

### Task 1: Personal-data pre-scan in the gateway

**Files:**
- Create: `core/src/ooat_core/pii.py`
- Modify: `core/src/ooat_core/gateway.py`
- Test: `core/tests/test_pii.py`, `core/tests/test_gateway_decide.py`

**Interfaces:**
- Consumes: `Gateway._route()` (04a), `DecisionRequest`, `ModelRequest`.
- Produces (in `ooat_core.pii`): `scan(text) -> frozenset[str]` (subset of `email`, `phone`, `iban`, `card`, `birth_number`); `raised_class(declared, text) -> str`; `higher_class(a, b) -> str`; `ORDER` (classes from least to most sensitive). Gateway: every routed request whose outgoing text has a hit is routed as `personal` (unless declared higher), and the trace says `pre-scan found personal data: <declared> raised to personal`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_pii.py`:

````python
import time

import pytest

from ooat_core.pii import higher_class, raised_class, scan


@pytest.mark.parametrize("text, kind", [
    ("Pošlete to na jan.novak@example.cz, děkuji.", "email"),
    ("Volejte +420 777 123 456 po 16. hodině.", "phone"),
    ("Mobil 603123456.", "phone"),
    ("Účet CZ65 0800 0000 1920 0014 5399 u ČS.", "iban"),
    ("Karta 4111 1111 1111 1111, platnost 12/28.", "card"),
    ("Rodné číslo 780123/0008.", "birth_number"),
    ("Narozen 1950, RČ 505101/123.", "birth_number"),
    ("RČ 015203/0000 podle staršího pravidla.", "birth_number"),
])
def test_personal_data_with_a_checkable_form_is_found(text, kind):
    assert kind in scan(text)


@pytest.mark.parametrize("text", [
    "Obrat 1 200 000 Kč za rok 2025, marže 12 %.",
    "Objednávka 123456789 ze dne 12. 3. 2026.",
    "Účet CZ65 0800 0000 1920 0014 5398 (překlep v kontrolní číslici).",
    "Číslo 4111 1111 1111 1112 neprojde Luhnem.",
    "Testovací karta 0000 0000 0000 0000.",
    "Kód 785123/0003 nemá platnou kontrolu.",
    "Kód 781323/0008 má měsíc 13.",
    "Napiš shrnutí smlouvy pro jednatele, max. 1 strana.",
    "Write to us at support (at) example dot com.",
])
def test_ordinary_business_text_is_not_flagged(text):
    assert scan(text) == frozenset()


def test_the_class_is_raised_to_personal_and_never_lowered():
    text = "Kontakt: jan.novak@example.cz"
    assert raised_class("internal", text) == "personal"
    assert raised_class("public", text) == "personal"
    assert raised_class("special_category", text) == "special_category"
    assert raised_class("internal", "Bez osobních údajů.") == "internal"


def test_higher_class_orders_by_sensitivity():
    assert higher_class("internal", "personal") == "personal"
    assert higher_class("client_confidential", "public") == "client_confidential"


@pytest.mark.parametrize("filler", ["x", "1", "a.", "a@", "+4"])
def test_a_long_attachment_is_scanned_in_linear_time(filler):
    text = filler * 100_000 + " jan.novak@example.cz"
    started = time.monotonic()
    assert "email" in scan(text)
    assert time.monotonic() - started < 1.0
````

In `core/tests/test_gateway_decide.py`:

Replace:

````python
    setup = Setup(economy(reported_model=" "))
    with pytest.raises(GatewayError) as info:
        setup.gateway.decide(setup.request())
    assert info.value.code == "API_ERROR" and info.value.cost["adapter"] == "prv.fake.api"
````

with:

````python
    setup = Setup(economy(reported_model=" "))
    with pytest.raises(GatewayError) as info:
        setup.gateway.decide(setup.request())
    assert info.value.code == "API_ERROR" and info.value.cost["adapter"] == "prv.fake.api"


# Personal-data pre-scan (design 04 §4, ADR 0011) ----------------------------------------------------------------

def test_personal_data_in_an_internal_state_never_reaches_jev():
    jev = FakeDecisionConnector(answers=jev_answers)
    setup = Setup(jev)
    with pytest.raises(GatewayError) as info:
        setup.gateway.decide(setup.request(state="Shrň smlouvu, kontakt jan.novak@example.cz."))
    assert info.value.code == "NOT_PERMITTED" and jev.calls == []
    assert "pre-scan found personal data: internal raised to personal" in info.value.trace


def test_personal_data_in_a_question_is_found_too():
    jev = FakeDecisionConnector(answers=jev_answers)
    setup = Setup(jev)
    question = DecisionQuestion("noul", "Does the output mention +420 777 123 456?")
    with pytest.raises(GatewayError):
        setup.gateway.decide(setup.request(questions={"a1.1": question}))
    assert jev.calls == []


def test_a_model_request_with_personal_data_goes_only_where_personal_is_allowed():
    allowed = economy()
    setup = Setup(allowed, classes=("public", "internal"))
    request = ModelRequest(tier="economy", prompt="IBAN CZ65 0800 0000 1920 0014 5399", data_class="internal",
                           task=setup.task)
    with pytest.raises(GatewayError, match="NOT_PERMITTED"):
        setup.gateway.call(request)
    assert allowed.calls == []
````

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest core/tests/test_pii.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'ooat_core.pii'`.
Run: `python -m pytest core/tests/test_gateway_decide.py -q`
Expected: `3 failed, 26 passed` — the three pre-scan tests (`test_personal_data_in_an_internal_state_never_reaches_jev`, `test_personal_data_in_a_question_is_found_too`, `test_a_model_request_with_personal_data_goes_only_where_personal_is_allowed`).

- [ ] **Step 3: Write the scanner**

Create `core/src/ooat_core/pii.py`:

````python
"""Local pre-scan for personal data, before anything leaves the machine (design 04 §4, ADR 0011).

A hit raises a request's data class to `personal`; it never lowers one. The scan finds only what has a checkable
form: e-mail addresses, phone numbers, IBANs (mod 97), payment card numbers (Luhn) and Czech/Slovak birth numbers
written with a slash (date plus mod 11). Names and free-text health details are not found: that residual risk is
covered by the class the operator declares.
"""

import re

PERSONAL = "personal"
ORDER = ("public", "internal", "client_confidential", "personal", "special_category")

# Bounded repeats and a start-of-token lookbehind keep every pattern linear on long runs of letters or digits:
# an unbounded local part made a 100k-character attachment take minutes.
_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){0,8}"
                    r"\.[A-Za-z]{2,24}")
# +420/+421 numbers, or a Czech mobile (6xx/7xx) written as nine digits; amounts like 1 200 000 do not match.
_PHONE = re.compile(r"(?<![\d+])(?:\+42[01][ ]?\d{3}[ ]?\d{3}[ ]?\d{3}|[67]\d{2}[ ]?\d{3}[ ]?\d{3})(?!\d)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b")
_CARD = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
_BIRTH_NUMBER = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})/(\d{3,4})(?!\d)")


def _iban_ok(text: str) -> bool:
    compact = text.replace(" ", "")
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(char, 36)) for char in rearranged)
    return int(digits) % 97 == 1


def _luhn_ok(text: str) -> bool:
    digits = [int(char) for char in text if char.isdigit()]
    if len(set(digits)) == 1:  # 0000 0000 ... is a placeholder, not a card
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2:
            digit *= 2
            digit -= 9 if digit > 9 else 0
        total += digit
    return total % 10 == 0


def _birth_number_ok(match: re.Match) -> bool:
    year, month, day = (int(match.group(i)) for i in (1, 2, 3))
    suffix = match.group(4)
    month = month - 50 if month > 50 else month  # women
    month = month - 20 if month > 20 else month  # extended series since 2004
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return False
    if len(suffix) == 3:  # born before 1954: no check digit
        return year < 54
    digits = f"{match.group(1)}{match.group(2)}{match.group(3)}{suffix}"  # a string: 00.. years keep their zeros
    return int(digits) % 11 == 0 or (int(digits[:9]) % 11 == 10 and digits[9] == "0")


def scan(text: str) -> frozenset[str]:
    """The kinds of personal data found in the text: email, phone, iban, card, birth_number."""
    found = set()
    if _EMAIL.search(text):
        found.add("email")
    if _PHONE.search(text):
        found.add("phone")
    if any(_iban_ok(m.group(0)) for m in _IBAN.finditer(text)):
        found.add("iban")
    if any(_luhn_ok(m.group(0)) for m in _CARD.finditer(text)):
        found.add("card")
    if any(_birth_number_ok(m) for m in _BIRTH_NUMBER.finditer(text)):
        found.add("birth_number")
    return frozenset(found)


def raised_class(declared: str, text: str) -> str:
    """The declared class, raised to `personal` when the scan finds personal data; never lowered."""
    if ORDER.index(declared) < ORDER.index(PERSONAL) and scan(text):
        return PERSONAL
    return declared


def higher_class(first: str, second: str) -> str:
    return first if ORDER.index(first) >= ORDER.index(second) else second
````

- [ ] **Step 4: Run it before routing**

In `core/src/ooat_core/gateway.py`:

Replace:

````python
Model requests go to model connectors (`call`), typed decisions to decision connectors (`decide`, ADR 0011).
"""
````

with:

````python
Model requests go to model connectors (`call`), typed decisions to decision connectors (`decide`, ADR 0011).
Before routing, a local pre-scan raises the data class of any request that carries personal data (pii.py).
"""
````

Replace:

````python
from .ledger import DATA_CLASSES, Ledger, new_event
from .routing import Price, RoutingPolicy
````

with:

````python
from .ledger import DATA_CLASSES, Ledger, new_event
from .pii import raised_class
from .routing import Price, RoutingPolicy
````

Replace:

````python
        return self._resolver.get(connector_id)
````

with:

````python
        return self._resolver.get(connector_id)


def _outgoing_text(request: ModelRequest | DecisionRequest) -> str:
    """Everything a connector would send to the provider, for the personal-data pre-scan."""
    if isinstance(request, DecisionRequest):
        questions = {key: dataclasses.asdict(question) for key, question in request.questions.items()}
        return request.state + "\n" + json.dumps(questions, ensure_ascii=False)
    return request.system + "\n" + request.prompt
````

Replace:

````python
            raise ValueError(f"unknown data class: {request.data_class}")
        events = self._ledger.events(types=_STATE_EVENTS)
        acknowledged, cooldowns = acknowledgements(events), self._cooldowns(events)
        candidates, trace, cooling = [], [], set()
        for connector_id in self._registry.ids(kind):
````

with:

````python
            raise ValueError(f"unknown data class: {request.data_class}")
        candidates, trace, cooling = [], [], set()
        # The pre-scan runs before any connector is chosen, so a declared class can never send personal data
        # where the operator did not allow it. It only raises the class (design 04 §4, ADR 0011).
        effective = raised_class(request.data_class, _outgoing_text(request))
        if effective != request.data_class:
            trace.append(f"pre-scan found personal data: {request.data_class} raised to {effective}")
            request = dataclasses.replace(request, data_class=effective)
        events = self._ledger.events(types=_STATE_EVENTS)
        acknowledged, cooldowns = acknowledgements(events), self._cooldowns(events)
        for connector_id in self._registry.ids(kind):
````

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest core/tests/test_pii.py core/tests/test_gateway_decide.py -q` → Expected: `53 passed`.
Run: `python -m pytest -q` → Expected: `508 passed, 4 skipped`.

- [ ] **Step 6: Commit**

```bash
git add core/src/ooat_core/pii.py core/src/ooat_core/gateway.py core/tests/test_pii.py core/tests/test_gateway_decide.py
git commit -m "feat(core): local personal-data pre-scan raises the data class before routing"
```

---

### Task 2: Thresholds from ratings

**Files:**
- Create: `core/src/ooat_core/thresholds.py`
- Test: `core/tests/test_thresholds.py`

**Interfaces:**
- Consumes: event shapes of ADR 0011 (`TOPOLOGY_DECIDED.body.decisions[]`, `GATE_*.body.criteria[].decision`, `TASK_RATED.body.decisions[]`).
- Produces (in `ooat_core.thresholds`): `RatedDecision(point, engine, model, confidence, correct)`; `decision_point(event_type, question) -> str`; `rated_decisions(events) -> list[RatedDecision]`; `computed_threshold(rated, epsilon) -> float`; `threshold(events, point, engine, model, risk_class="R0", decision_engine=True) -> float`; constants `GATE_EVENTS`, `EPSILON`, `GRID`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_thresholds.py`:

````python
"""θ per decision point, engine and model version from ratings in the ledger (ADR 0011)."""

import pytest

from ooat_core.ids import new_id
from ooat_core.thresholds import RatedDecision, computed_threshold, rated_decisions, threshold

JEV, VERSION = "prv.typesafe.api", "jev-1.13.0"


def record(question, confidence, engine=JEV, model=VERSION):
    return {"question": question, "engine": engine, "model": model, "answer": 0.9, "confidence": confidence,
            "threshold": 0.8}


def gate_event(*records):
    return {"id": new_id("evt"), "type": "TOPOLOGY_DECIDED", "body": {"decisions": list(records)}}


def acceptance_event(*records):
    criteria = [{"id": r["question"].replace(".", "_"), "passed": True, "decision": r} for r in records]
    return {"id": new_id("evt"), "type": "GATE_PASSED", "body": {"criteria": criteria}}


def rating(event, question, verdict):
    item = {"event": event["id"], "question": question, "verdict": verdict}
    if verdict == "corrected":
        item["value"] = 0
    return {"id": new_id("evt"), "type": "TASK_RATED", "body": {"decisions": [item]}}


def history(point_question, outcomes, engine=JEV, model=VERSION, maker=gate_event):
    """Events for rated decisions: outcomes is a list of (confidence, correct)."""
    events = []
    for confidence, correct in outcomes:
        decided = maker(record(point_question, confidence, engine, model))
        events += [decided, rating(decided, point_question, "confirmed" if correct else "corrected")]
    return events


def test_before_five_ratings_jev_uses_the_interim_threshold_and_the_fallback_never_acts_alone():
    events = history("a1.1", [(0.95, True)] * 4)
    assert threshold(events, "a1", JEV, VERSION) == 0.8
    assert threshold(events, "a1", "prv.anthropic.api", "claude-haiku", decision_engine=False) == 1.0


def test_from_five_ratings_the_floor_of_0_8_holds_and_a_computed_value_can_raise_it():
    good = history("a1.1", [(0.6, True)] * 5)
    assert threshold(good, "a1", JEV, VERSION) == 0.8  # computed 0.5, floored
    risky = history("a1.1", [(0.85, False)] * 2 + [(0.95, True)] * 5)
    assert threshold(risky, "a1", JEV, VERSION) == 0.86


def test_from_twenty_ratings_the_computed_value_alone_applies():
    events = history("a5", [(0.6, True)] * 20)
    assert threshold(events, "a5", JEV, VERSION) == 0.5


def test_without_a_qualifying_threshold_nothing_acts_alone():
    events = history("a1.1", [(0.95, False)] * 6)
    assert threshold(events, "a1", JEV, VERSION) == 1.0


def test_keys_are_separate_by_point_engine_and_model_version():
    events = history("a1.1", [(0.6, True)] * 20) + history("a1.2", [(0.95, False)] * 20, model="jev-1.14.0")
    assert threshold(events, "a1", JEV, VERSION) == 0.5
    assert threshold(events, "a1", JEV, "jev-1.14.0") == 1.0
    assert threshold(events, "a4", JEV, VERSION) == 0.8  # not rated yet
    assert threshold(events, "acceptance", JEV, VERSION) == 0.8


def test_acceptance_decisions_are_rated_from_gate_events():
    events = history("c1", [(0.6, True)] * 20, maker=acceptance_event)
    assert threshold(events, "acceptance", JEV, VERSION) == 0.5
    assert {r.point for r in rated_decisions(events)} == {"acceptance"}


def test_r1_tolerates_fewer_errors_and_r2_never_acts_alone():
    events = history("a1.1", [(0.9, True)] * 19 + [(0.9, False)])  # 5 % errors
    assert threshold(events, "a1", JEV, VERSION, "R0") == 0.5
    assert threshold(events, "a1", JEV, VERSION, "R1") == 1.0
    assert threshold(events, "a1", JEV, VERSION, "R2") == 1.0


def test_a_later_rating_of_the_same_decision_replaces_the_earlier_one():
    decided = gate_event(record("a1.1", 0.9))
    events = [decided, rating(decided, "a1.1", "corrected"), rating(decided, "a1.1", "confirmed")]
    assert [r.correct for r in rated_decisions(events)] == [True]


def test_ratings_of_unknown_decisions_are_ignored():
    stray = {"id": new_id("evt"), "type": "TOPOLOGY_DECIDED", "body": {}}
    assert rated_decisions([rating(stray, "a1.1", "confirmed")]) == []


@pytest.mark.parametrize("outcomes, expected", [
    ([(0.7, True)] * 4, 1.0),  # support below 5
    ([(0.55, False)] + [(0.7, True)] * 5, 0.56),
])
def test_computed_threshold_needs_support_and_a_low_error_rate(outcomes, expected):
    rated = [RatedDecision("a1", JEV, VERSION, c, ok) for c, ok in outcomes]
    assert computed_threshold(rated, 0.05) == expected
````

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest core/tests/test_thresholds.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'ooat_core.thresholds'`.

- [ ] **Step 3: Write the module**

Create `core/src/ooat_core/thresholds.py`:

````python
"""Confidence thresholds θ per decision point, engine and model version (ADR 0011, spec §6).

A decision acts alone only when its confidence reaches θ. θ is computed from the operator's ratings in the ledger:
decision records live in TOPOLOGY_DECIDED (Gate) and GATE_PASSED / GATE_FAILED (acceptance), verdicts in
TASK_RATED. Nothing is stored; θ is recomputed from the events every time, so every new rating counts at once.
"""

from collections.abc import Iterable
from dataclasses import dataclass

INTERIM_DECISION_ENGINE = 0.8  # a decision connector (Jev) before 5 ratings
INTERIM_FALLBACK_ENGINE = 1.0  # a text model's self-stated probability never acts alone before it is rated
FLOOR = 0.8  # holds from 5 to 19 ratings
MIN_RATED = 5
FULL_HISTORY = 20
MIN_SUPPORT = 5  # rated decisions at or above a candidate θ
EPSILON = {"R0": 0.05, "R1": 0.02}  # tolerated error rate; R2 and R3 never act on a decision alone
GRID = [round(0.50 + step / 100, 2) for step in range(50)]  # 0.50 .. 0.99
GATE_EVENTS = ("GATE_PASSED", "GATE_FAILED")


@dataclass(frozen=True)
class RatedDecision:
    point: str  # "a1", "a4", "a5", "a7", "a10" or "acceptance"
    engine: str
    model: str
    confidence: float
    correct: bool


def decision_point(event_type: str, question: str) -> str:
    """Gate questions "a1.2", "a10" belong to their rule; every acceptance criterion to "acceptance"."""
    return "acceptance" if event_type in GATE_EVENTS else question.split(".")[0]


def _records(events: list[dict]) -> dict[tuple[str, str], tuple[str, dict]]:
    records = {}
    for event in events:
        if event["type"] == "TOPOLOGY_DECIDED":
            for record in event["body"].get("decisions", []):
                records[(event["id"], record["question"])] = (decision_point(event["type"], record["question"]), record)
        elif event["type"] in GATE_EVENTS:
            for criterion in event["body"].get("criteria", []):
                record = criterion.get("decision")
                if record is not None:
                    records[(event["id"], record["question"])] = ("acceptance", record)
    return records


def rated_decisions(events: Iterable[dict]) -> list[RatedDecision]:
    """Every decision record the operator rated; a later rating of the same record replaces an earlier one."""
    events = list(events)
    records = _records(events)
    verdicts = {}
    for event in events:
        if event["type"] == "TASK_RATED":
            for verdict in event["body"].get("decisions", []):
                verdicts[(verdict["event"], verdict["question"])] = verdict["verdict"]
    rated = []
    for key, verdict in verdicts.items():
        if key in records:
            point, record = records[key]
            rated.append(RatedDecision(point, record["engine"], record["model"], record["confidence"],
                                       verdict == "confirmed"))
    return rated


def computed_threshold(rated: list[RatedDecision], epsilon: float) -> float:
    """The smallest θ on the grid with at least MIN_SUPPORT rated decisions at or above it and an error rate
    of at most ε among them; 1 when none qualifies."""
    for theta in GRID:
        above = [r for r in rated if r.confidence >= theta]
        if len(above) >= MIN_SUPPORT and sum(not r.correct for r in above) / len(above) <= epsilon:
            return theta
    return 1.0


def threshold(events: Iterable[dict], point: str, engine: str, model: str, risk_class: str = "R0",
              decision_engine: bool = True) -> float:
    """θ for one key. `decision_engine` is False for the text-model fallback (ADR 0011)."""
    if risk_class not in EPSILON:
        return 1.0
    rated = [r for r in rated_decisions(events) if (r.point, r.engine, r.model) == (point, engine, model)]
    if len(rated) < MIN_RATED:
        return INTERIM_DECISION_ENGINE if decision_engine else INTERIM_FALLBACK_ENGINE
    computed = computed_threshold(rated, EPSILON[risk_class])
    return computed if len(rated) >= FULL_HISTORY else max(FLOOR, computed)
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest core/tests/test_thresholds.py -q` → Expected: `11 passed`.
Run: `python -m pytest -q` → Expected: `519 passed, 4 skipped`.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/thresholds.py core/tests/test_thresholds.py
git commit -m "feat(core): confidence thresholds per decision point, engine and model version"
```

---

### Task 3: Gate step A, data class and estimate

**Files:**
- Create: `core/src/ooat_core/gate.py`
- Test: `core/tests/test_gate.py`

**Interfaces:**
- Consumes: `Gateway.decide()`, `.estimate()`, `.estimate_decision()`, `GatewayError` (04a); `raised_class`, `higher_class` (Task 1); `threshold`, `decision_point`, `GATE_EVENTS` (Task 2); `task_state()`.
- Produces (in `ooat_core.gate`):
  - `GateSettings(value_usd={"A": 1000.0, "B": 300.0, "C": 50.0}, v_min_usd=15.0, default_budget_usd=2.0, expected_output_tokens=2000, hil_deadline_hours=24.0)`
  - `GateOutcome(action: "run" | "ask" | "closed", topology, data_class, budget_usd, estimate_usd=None, request=None, closed=None)`
  - `Gate(ledger, gateway, settings=GateSettings(), clock=...)`, `Gate.run(task) -> GateOutcome`; `ValueError` unless the task is SUBMITTED
  - `task_text(body, clarifications) -> str` (the text the Gate and the worker see), `gate_questions(criteria) -> dict`, `task_value_usd(body, settings)`
  - `ACTOR = {"kind": "system", "id": "ooat-gate"}`, `WORKER_TIER = "workhorse"`
  - Events: `TOPOLOGY_DECIDED` (refs the submission; `cost` of the decision call; `parameters.budget_usd`, `v_usd`; `decisions[]`); a charged decision failure → `DECISION` with its cost; a task that cannot or should not run → `TOPOLOGY_DECIDED` T0 + `TASK_CLOSED` `CLOSED_ABSTAINED` with `missing`.

In this task every criterion the tests use is confidently checkable; Task 4 adds what happens when one is not.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_gate.py`:

````python
"""Topology Gate for T0–T2 with fake connectors (design 04 §4, ADR 0011)."""

import json
from datetime import datetime, timezone

import pytest
from connector_fakes import FakeConnector, FakeDecisionConnector, fake_manifest

from ooat_core.config import parse_config
from ooat_core.connectors import ConnectorError, DecisionAnswer, jurisdiction_fingerprint
from ooat_core.connectors.registry import Registry
from ooat_core.credentials_env import SecretResolver
from ooat_core.gate import Gate, GateSettings
from ooat_core.gateway import Gateway
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger, new_event
from ooat_core.routing import RoutingPolicy
from ooat_core.state import task_state

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
HIL = {"kind": "hil", "id": "operator"}
POLICY = {
    "public": {"allowed": True}, "internal": {"allowed": True},
    "client_confidential": {"allowed": True, "require_no_training": True},
    "personal": {"allowed": True, "require_no_training": True, "require_known_region": True},
    "special_category": {"allowed": True, "require_verified_redaction": True},
}
ALL_BUT_SPECIAL = ("public", "internal", "client_confidential", "personal")


def price(adapter, model, usd_in, usd_out):
    return {"adapter": adapter, "model": model, "usd_per_mtok_in": usd_in, "usd_per_mtok_out": usd_out,
            "valid_from": "2026-01-01", "source": "https://fake.invalid/pricing"}


PRICES = [price("prv.fakejev.api", "fake-decision-1", 0.042, 0), price("prv.fake.api", "fake-model", 3, 15),
          price("prv.fake.api", "fake-economy", 1, 5)]


def confident(**overrides):
    """A decision engine that is sure every criterion is checkable, the task is one part, and the data internal."""
    def answers(request):
        given = {}
        for question_id, question in request.questions.items():
            if question.type == "noul":
                given[question_id] = DecisionAnswer("noul", 0.95, 0.95)
            elif question_id.startswith("a5"):
                given[question_id] = DecisionAnswer("choice", "one", 0.9)
            else:
                given[question_id] = DecisionAnswer("choice", "internal", 0.9)
        for question_id, answer in overrides.items():
            for key in (question_id, question_id + "~reversed"):
                if key in given:
                    given[key] = answer
        return given
    return answers


def fallback_reply(criteria=1):
    """What the economy text tier answers when it stands in for the decision tier."""
    reply = {f"a1.{n}": {"p_true": 0.9} for n in range(1, criteria + 1)}
    reply.update({"a4": {"p_true": 0.2}, "a7": {"p_true": 0.2},
                  "a5": {"probabilities": {"one": 1}}, "a5~reversed": {"probabilities": {"one": 1}},
                  "a10": {"probabilities": {"internal": 1}}, "a10~reversed": {"probabilities": {"internal": 1}}})
    return json.dumps(reply)


class GateSetup:
    def __init__(self, answers=None, jev_error=None, worker_text=None, settings=GateSettings()):
        self.ledger = Ledger.open("sqlite:///:memory:")
        self.jev = FakeDecisionConnector(answers=answers or confident(), error=jev_error)
        self.worker = FakeConnector(fake_manifest("prv.fake.api", "api",
                                                  tiers={"workhorse": "fake-model", "economy": "fake-economy"}),
                                    text=worker_text or fallback_reply())
        for connector, classes in ((self.jev, ("public", "internal")), (self.worker, ALL_BUT_SPECIAL)):
            self.ledger.append(new_event("ADAPTER_ACKNOWLEDGED", task=None, actor=HIL, body={
                "adapter": connector.manifest["id"], "manifest_version": connector.manifest["version"],
                "allowed_data_classes": list(classes), "operator": "Operator", "automation_confirmed": True,
                "jurisdiction_sha256": jurisdiction_fingerprint(connector.manifest)}))
        config = parse_config({})
        self.gateway = Gateway(self.ledger, Registry([self.jev, self.worker]),
                               RoutingPolicy({"version": "0.1.0", "prices": PRICES, "data_class_policy": POLICY}),
                               config, SecretResolver(config, {}), clock=lambda: NOW)
        self.gate = Gate(self.ledger, self.gateway, settings, clock=lambda: NOW)

    def submit(self, goal="Napiš shrnutí smlouvy pro jednatele.", acceptance=("Shrnutí má nejvýše 300 slov.",),
               **extra):
        task = new_id("tsk")
        body = {"goal": goal, "acceptance": list(acceptance), **extra}
        self.ledger.append(new_event("TASK_SUBMITTED", task=task, actor=HIL, body=body))
        return task

    def events(self, task, kind):
        return [e for e in self.ledger.events(task=task) if e["type"] == kind]


def test_a_clear_task_runs_as_t2_and_every_decision_is_recorded():
    setup = GateSetup()
    task = setup.submit()
    outcome = setup.gate.run(task)
    assert (outcome.action, outcome.topology, outcome.data_class, outcome.budget_usd) == ("run", "T2", "internal", 2.0)
    decided = setup.events(task, "TOPOLOGY_DECIDED")[0]
    assert decided["body"]["topology"] == "T2" and decided["body"]["rules_applied"] == []
    assert decided["body"]["candidates"] == [{"topology": "T2", "model_usd": outcome.estimate_usd}]
    assert decided["body"]["parameters"] == {"budget_usd": 2.0}
    records = {r["question"]: r for r in decided["body"]["decisions"]}
    assert set(records) == {"a1.1", "a4", "a5", "a7", "a10"}
    assert records["a1.1"] == {"question": "a1.1", "engine": "prv.fakejev.api", "model": "fake-decision-1",
                               "answer": 0.95, "confidence": 0.95, "threshold": 0.8}
    assert decided["cost"]["tier"] == "decision" and decided["refs"] == [setup.events(task, "TASK_SUBMITTED")[0]["id"]]
    assert task_state(setup.ledger.events(task=task)) == "GATED"


def test_the_estimate_covers_the_worker_and_the_acceptance_checks():
    setup = GateSetup()
    outcome = setup.gate.run(setup.submit())
    assert 2000 * 15 / 1e6 < outcome.estimate_usd < 0.04  # 2,000 workhorse output tokens dominate


def test_a_confident_a10_raises_the_class_and_never_lowers_it():
    raise_ = GateSetup(answers=confident(a10=DecisionAnswer("choice", "client_confidential", 0.95)))
    task = raise_.submit()
    outcome = raise_.gate.run(task)
    assert outcome.data_class == "client_confidential"
    assert raise_.events(task, "TOPOLOGY_DECIDED")[0]["body"]["rules_applied"] == ["A10"]
    lower = GateSetup(answers=confident(a10=DecisionAnswer("choice", "public", 0.99)))
    assert lower.gate.run(lower.submit()).data_class == "internal"


def test_an_unsure_a10_keeps_the_declared_class():
    setup = GateSetup(answers=confident(a10=DecisionAnswer("choice", "personal", 0.7)))
    assert setup.gate.run(setup.submit()).data_class == "internal"


def test_personal_data_found_by_the_pre_scan_raises_the_class_and_keeps_the_task_off_jev():
    setup = GateSetup()
    task = setup.submit(goal="Napiš odpověď panu Novákovi na jan.novak@example.cz.")
    outcome = setup.gate.run(task)
    assert outcome.data_class == "personal" and setup.jev.calls == []
    decided = setup.events(task, "TOPOLOGY_DECIDED")[0]["body"]
    assert decided["rules_applied"] == ["A10"]
    assert {r["engine"] for r in decided["decisions"]} == {"prv.fake.api"}
    assert {r["threshold"] for r in decided["decisions"]} == {1.0}  # the fallback is not rated yet


def test_a_task_without_a_permitted_route_is_closed_without_running():
    setup = GateSetup()
    task = setup.submit(data_class="special_category")
    outcome = setup.gate.run(task)
    assert (outcome.action, outcome.topology, outcome.closed) == ("closed", "T0", "CLOSED_ABSTAINED")
    closed = setup.events(task, "TASK_CLOSED")[0]["body"]
    assert "special_category" in closed["missing"] and closed["cost"]["contracts_usd"] == 0
    assert setup.events(task, "TOPOLOGY_DECIDED")[0]["body"]["topology"] == "T0"
    assert setup.worker.calls == [] and task_state(setup.ledger.events(task=task)) == "CLOSED_ABSTAINED"


def test_a_task_that_costs_more_than_it_is_worth_is_closed_as_t0():
    setup = GateSetup()
    task = setup.submit(value={"usd": 0.01})
    outcome = setup.gate.run(task)
    assert outcome.closed == "CLOSED_ABSTAINED" and outcome.estimate_usd > 0.01
    decided = setup.events(task, "TOPOLOGY_DECIDED")[0]["body"]
    assert decided["topology"] == "T0" and "A3" in decided["rules_applied"]
    assert decided["parameters"]["v_usd"] == 0.01
    assert "exceeds the task value" in setup.events(task, "TASK_CLOSED")[0]["body"]["missing"]


def test_value_classes_map_to_usd():
    setup = GateSetup(settings=GateSettings(value_usd={"A": 1000.0, "B": 300.0, "C": 0.001}))
    assert setup.gate.run(setup.submit(value={"class": "C"})).closed == "CLOSED_ABSTAINED"
    assert setup.gate.run(setup.submit(value={"class": "A"})).action == "run"


def test_charged_decision_failures_are_recorded_with_their_cost():
    setup = GateSetup(jev_error=ConnectorError("API_ERROR", "HTTP 500"), worker_text="Not JSON.")
    task = setup.submit()
    setup.gate.run(task)
    failures = setup.events(task, "DECISION")
    assert [f["cost"]["adapter"] for f in failures] == ["prv.fake.api", "prv.fakejev.api"]
    assert all(f["actor"] == {"kind": "system", "id": "ooat-gate"} for f in failures)


def test_the_gate_runs_only_on_a_submitted_task():
    setup = GateSetup()
    task = setup.submit()
    setup.gate.run(task)
    with pytest.raises(ValueError, match="not SUBMITTED"):
        setup.gate.run(task)
````

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest core/tests/test_gate.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'ooat_core.gate'`.

- [ ] **Step 3: Write the Gate**

Create `core/src/ooat_core/gate.py`:

````python
"""Topology Gate for T0–T2 (spec §4 step A; design 04 §4; ADR 0009, ADR 0011).

The Gate reads a SUBMITTED task from the ledger, asks the decision tier one batch of typed questions about it,
acts on the answers whose confidence reaches their threshold, estimates the cost before anything runs, and appends
TOPOLOGY_DECIDED. F1 knows T0 (no agent) and T2 (one worker); rules for teams (A4, A5, A7) are recorded only.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from .connectors import DecisionQuestion, DecisionRequest, ModelRequest
from .gateway import Gateway, GatewayError
from .ledger import Ledger, new_event
from .pii import higher_class, raised_class
from .state import task_state
from .thresholds import GATE_EVENTS, decision_point, threshold

ACTOR = {"kind": "system", "id": "ooat-gate"}
WORKER_TIER = "workhorse"
BRANCHES = {"one": "A single line of work", "two": "Two independent parts", "many": "Three or more independent parts"}
DATA_CLASSES = {
    "public": "Published or meant for publication",
    "internal": "Internal business information without personal data",
    "client_confidential": "A client's confidential information (contracts, finances, trade secrets)",
    "personal": "Data about an identifiable person (name with contact, ID number, account)",
    "special_category": "Health, genetic, biometric, religious, political or sexual-orientation data of a person",
}


@dataclass(frozen=True)
class GateSettings:
    value_usd: dict = field(default_factory=lambda: {"A": 1000.0, "B": 300.0, "C": 50.0})
    v_min_usd: float = 15.0  # rule A3
    default_budget_usd: float = 2.0
    expected_output_tokens: int = 2000  # prior for the worker's deliverable
    hil_deadline_hours: float = 24.0


@dataclass(frozen=True)
class GateOutcome:
    action: Literal["run", "ask", "closed"]
    topology: str
    data_class: str
    budget_usd: float
    estimate_usd: float | None = None
    request: str | None = None  # the HIL_REQUEST to answer when action == "ask"
    closed: str | None = None  # the TASK_CLOSED state when action == "closed"


def task_value_usd(body: dict, settings: GateSettings) -> float | None:
    value = body.get("value")
    if value is None:
        return None
    return value["usd"] if "usd" in value else settings.value_usd[value["class"]]


def task_text(body: dict, clarifications: list[str]) -> str:
    """The state the Gate and the worker see: goal, expected output, criteria, the operator's clarifications."""
    lines = [f"Goal: {body['goal']}"]
    if body.get("expected_output"):
        lines.append(f"Expected output: {body['expected_output']}")
    for number, criterion in enumerate(body.get("acceptance", []), 1):
        lines.append(f"Acceptance criterion {number}: {criterion}")
    for number, text in enumerate(clarifications, 1):
        lines.append(f"Clarification {number}: {text}")
    return "\n".join(lines)


def gate_questions(criteria: list[str]) -> dict[str, DecisionQuestion]:
    """One batch for step A: A1 per criterion, A4, A5, A7, A10 (design 04 §4)."""
    questions = {
        f"a1.{number}": DecisionQuestion(
            "noul", "Given the task and its clarifications, can this acceptance criterion be checked from the "
                    f"delivered output alone, without asking anyone? Criterion: {criterion}",
            {"true": "A reader of the output alone can tell whether it is met",
             "false": "It is vague, subjective, or needs information outside the output"})
        for number, criterion in enumerate(criteria, 1)
    }
    questions["a4"] = DecisionQuestion("noul", "Does each step of this task depend on the result of the previous one?")
    questions["a5"] = DecisionQuestion("choice", "How many independent parts could this task be split into?", BRANCHES)
    questions["a7"] = DecisionQuestion("noul", "Would separate parts all need the same large context or files?")
    questions["a10"] = DecisionQuestion("choice", "Which data class fits the most sensitive information in this task?",
                                        DATA_CLASSES)
    return questions


class Gate:
    def __init__(self, ledger: Ledger, gateway: Gateway, settings: GateSettings = GateSettings(),
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._ledger, self._gateway, self._settings, self._clock = ledger, gateway, settings, clock

    def run(self, task: str) -> GateOutcome:
        events = self._ledger.events(task=task)
        if task_state(events) != "SUBMITTED":
            raise ValueError(f"task {task} is not SUBMITTED")
        submitted = next(e for e in events if e["type"] == "TASK_SUBMITTED")
        body = submitted["body"]
        declared = body.get("data_class", "internal")
        budget = body.get("budget_usd", self._settings.default_budget_usd)
        value = task_value_usd(body, self._settings)
        criteria = list(body.get("acceptance", []))
        state = task_text(body, [])

        records, cost = self._ask(task, state, criteria, declared, body.get("risk_class", "R0"))
        answers = {r["question"]: r for r in records}
        data_class = raised_class(declared, state)
        a10 = answers.get("a10")
        if a10 is not None and a10["confidence"] >= a10["threshold"]:
            data_class = higher_class(data_class, a10["answer"])
        rules = ["A10"] if data_class != declared else []
        if value is not None and value < self._settings.v_min_usd:
            rules.append("A3")
        parameters = {"budget_usd": budget, **({"v_usd": value} if value is not None else {})}
        decided = {"records": records, "cost": cost, "parameters": parameters, "refs": [submitted["id"]]}

        try:
            estimate = self._estimate(task, state, criteria, data_class)
        except GatewayError as error:
            missing = f"no permitted route for {data_class} data: {error.message}"
            self._decided(task, "T0", rules, [{"topology": "T2", "eliminated_by": rules or ["A10"]}], decided)
            return self._close(task, data_class, budget, "CLOSED_ABSTAINED", "Not run: no permitted route.", missing)
        candidates = [{"topology": "T2", "model_usd": estimate}]
        if value is not None and estimate > value:
            self._decided(task, "T0", rules, candidates, decided)
            missing = f"the estimated cost {estimate:.4f} USD exceeds the task value {value:.2f} USD"
            return self._close(task, data_class, budget, "CLOSED_ABSTAINED", "Not run: not worth its cost.", missing,
                               estimate)
        self._decided(task, "T2", rules, candidates, decided)
        return GateOutcome("run", "T2", data_class, budget, estimate)

    # Step A ------------------------------------------------------------------------------------------------------

    def _ask(self, task, state, criteria, declared, risk_class):
        """Ask the batch; returns (decision records, cost of the successful call or None)."""
        try:
            result = self._gateway.decide(DecisionRequest(state, gate_questions(criteria), declared, task=task))
        except GatewayError as error:
            self._record_failures(task, error)
            return [], None
        self._record_failures(task, result.fallback_from)
        history = self._ledger.events(types=["TOPOLOGY_DECIDED", *GATE_EVENTS, "TASK_RATED"])
        records = []
        for question, answer in result.answers.items():
            theta = threshold(history, decision_point("TOPOLOGY_DECIDED", question), result.engine, result.model,
                              risk_class, decision_engine=result.fallback_from is None)
            records.append({"question": question, "engine": result.engine, "model": result.model,
                            "answer": answer.value, "confidence": answer.confidence, "threshold": theta})
        return records, result.cost

    def _record_failures(self, task, error: GatewayError | None) -> None:
        """A charged failure of the decision tier is recorded with its cost, so the Gate's cost stays complete."""
        while error is not None:
            if error.cost is not None:
                self._ledger.append(new_event("DECISION", task=task, actor=ACTOR, cost=error.cost, body={
                    "decision": f"Gate decision call failed ({error.code}); answered by the next engine or not at all.",
                    "rationale": error.message[:500] or error.code}))
            error = error.fallback_from

    # Cost before start -------------------------------------------------------------------------------------------

    def _estimate(self, task, state, criteria, data_class) -> float:
        """Worker plus acceptance checks, one attempt; raises GatewayError when no route is permitted."""
        tokens = self._settings.expected_output_tokens
        worker = self._gateway.estimate(ModelRequest(tier=WORKER_TIER, prompt=state, data_class=data_class,
                                                     expected_output_tokens=tokens, task=task))
        checks = 0.0
        if criteria:
            questions = {f"c{n}": DecisionQuestion("noul", f"Does the output meet: {c}") for n, c in
                         enumerate(criteria, 1)}
            try:  # the output's size is unknown before it exists: the prior stands in for it
                checks = self._gateway.estimate_decision(
                    DecisionRequest("x" * (4 * tokens), questions, data_class, task=task)).usd
            except GatewayError:
                checks = worker.usd  # no decision route: the critic on the worker's tier checks instead
        return worker.usd + checks

    # Events ------------------------------------------------------------------------------------------------------

    def _decided(self, task, topology, rules, candidates, decided) -> dict:
        body = {"topology": topology, "candidates": candidates, "rules_applied": rules,
                "parameters": decided["parameters"], "decisions": decided["records"]}
        return self._ledger.append(new_event("TOPOLOGY_DECIDED", task=task, actor=ACTOR, refs=decided["refs"],
                                             cost=decided["cost"], body=body))

    def _close(self, task, data_class, budget, state, summary, missing, estimate=None) -> GateOutcome:
        self._ledger.append(new_event("TASK_CLOSED", task=task, actor=ACTOR, body={
            "state": state, "summary": summary, "missing": missing,
            "cost": {"contracts_usd": 0.0, "gate_usd": self._gate_cost(task), "orchestrator_usd": 0.0,
                     "critic_usd": 0.0}}))
        return GateOutcome("closed", "T0", data_class, budget, estimate, closed=state)

    def _gate_cost(self, task) -> float:
        return sum(e.get("cost", {}).get("usd", 0.0) for e in self._ledger.events(task=task)
                   if e["actor"] == ACTOR)
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest core/tests/test_gate.py -q` → Expected: `10 passed`.
Run: `python -m pytest -q` → Expected: `529 passed, 4 skipped`.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/gate.py core/tests/test_gate.py
git commit -m "feat(core): Topology Gate step A with data-class decision and pre-start estimate"
```

---

### Task 4: Asking the operator — clarification and budget

**Files:**
- Modify: `core/src/ooat_core/gate.py`
- Test: `core/tests/test_gate.py`

**Interfaces:**
- Consumes: Task 3 `Gate`, `GateOutcome`, `task_text`; `HIL_REQUEST` / `HIL_RESPONSE` rules of the ledger; `task_state()` (ADR 0009).
- Produces (in `ooat_core.gate`):
  - `TaskFacts(submitted, state, criteria, declared, risk_class, budget_usd, value_usd, clarifications, run_as_is, refused)` and `task_facts(events, settings=GateSettings()) -> TaskFacts` — the runtime (04c) reads the granted budget and a refusal from it
  - `data_class_for(facts, records) -> str`, `gated_data_class(events, settings=GateSettings()) -> str` — the class the Gate decided, recomputed from its last `TOPOLOGY_DECIDED`
  - `unclear_criteria(criteria, records) -> list[str]`, `gate_questions(criteria, ask_a1=True)`, `MAX_CLARIFICATIONS = 3`, `CLARIFY_OPTIONS`
  - Clarifying `HIL_REQUEST`: options `clarify` (answer with text), `run_as_is`, `do_not_run` (`acts: false`); recommended `clarify`; default `do_not_run`. Budget `HIL_REQUEST`: options `raise_budget` (`cost_usd` = the raised budget, 120 % of the estimate) and `do_not_run`.
  - Order in `run()`: refusal → step A → route and value (close) → A1 (ask or close after 3) → budget (ask) → T2.

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_gate.py`:

Replace:

````python
from ooat_core.credentials_env import SecretResolver
from ooat_core.gate import Gate, GateSettings
from ooat_core.gateway import Gateway
````

with:

````python
from ooat_core.credentials_env import SecretResolver
from ooat_core.gate import Gate, GateSettings, gated_data_class, task_facts
from ooat_core.gateway import Gateway
````

Replace:

````python
    decided = setup.events(task, "TOPOLOGY_DECIDED")[0]["body"]
    assert decided["rules_applied"] == ["A10"]
    assert {r["engine"] for r in decided["decisions"]} == {"prv.fake.api"}
    assert {r["threshold"] for r in decided["decisions"]} == {1.0}  # the fallback is not rated yet
````

with:

````python
    decided = setup.events(task, "TOPOLOGY_DECIDED")[0]["body"]
    assert {r["engine"] for r in decided["decisions"]} == {"prv.fake.api"}
    assert {r["threshold"] for r in decided["decisions"]} == {1.0}  # the fallback is not rated yet
    # nothing the fallback says acts alone, so the operator confirms the criteria
    assert outcome.action == "ask" and decided["rules_applied"] == ["A1", "A10"]
````

Replace:

````python
        setup.gate.run(task)
````

with:

````python
        setup.gate.run(task)


# Asking the operator: clarification (A1, ADR 0009) and budget ----------------------------------------------------

def answer(setup, task, request, **body):
    setup.ledger.append(new_event("HIL_RESPONSE", task=task, actor=HIL, body={"request": request, **body}))


def test_a_task_without_criteria_asks_the_operator_before_any_model_is_called():
    setup = GateSetup()
    task = setup.submit(acceptance=())
    outcome = setup.gate.run(task)
    assert (outcome.action, outcome.topology) == ("ask", "T0") and setup.jev.calls == []
    decided = setup.events(task, "TOPOLOGY_DECIDED")[0]["body"]
    assert decided["rules_applied"] == ["A1"] and decided["candidates"][0]["eliminated_by"] == ["A1"]
    assert outcome.estimate_usd == decided["candidates"][0]["model_usd"]
    request = setup.events(task, "HIL_REQUEST")[0]
    assert request["id"] == outcome.request and "no acceptance criteria" in request["body"]["question"]
    assert [o["id"] for o in request["body"]["options"]] == ["clarify", "run_as_is", "do_not_run"]
    assert request["body"]["default_on_silence"] == "do_not_run" and request["body"]["blocking"] is True
    assert request["body"]["deadline"] == "2026-10-03T12:00:00Z"
    assert task_state(setup.ledger.events(task=task)) == "CLARIFYING"


@pytest.mark.parametrize("a1", [DecisionAnswer("noul", 0.2, 0.8), DecisionAnswer("noul", 0.9, 0.7)])
def test_a_criterion_that_is_not_confidently_checkable_is_sent_back_to_the_operator(a1):
    setup = GateSetup(answers=confident(**{"a1.1": a1}))
    task = setup.submit(acceptance=("Shrnutí je srozumitelné.",))
    outcome = setup.gate.run(task)
    assert outcome.action == "ask" and setup.worker.calls == []
    assert "Shrnutí je srozumitelné." in setup.events(task, "HIL_REQUEST")[0]["body"]["question"]


def test_a_clarification_goes_back_to_the_gate_with_the_answer_in_the_task_text():
    def answers(request):
        checkable = "Clarification 1:" in request.state
        return confident(**{"a1.1": DecisionAnswer("noul", 0.95 if checkable else 0.2, 0.95)})(request)

    setup = GateSetup(answers=answers)
    task = setup.submit(acceptance=("Shrnutí je srozumitelné.",))
    first = setup.gate.run(task)
    answer(setup, task, first.request, text="Srozumitelné = bez právních termínů, nejvýše 300 slov.")
    assert task_state(setup.ledger.events(task=task)) == "SUBMITTED"
    second = setup.gate.run(task)
    assert second.action == "run"
    assert "Clarification 1: Srozumitelné = bez právních termínů" in setup.jev.calls[1].state


def test_without_criteria_the_clarifications_become_the_criteria():
    setup = GateSetup()
    task = setup.submit(acceptance=())
    first = setup.gate.run(task)
    answer(setup, task, first.request, choice="clarify", text="Výstup je tabulka s 10 řádky.")
    assert setup.gate.run(task).action == "run"
    assert "a1.1" in setup.jev.calls[0].questions


def test_run_as_is_skips_the_criteria_questions():
    setup = GateSetup(answers=confident(**{"a1.1": DecisionAnswer("noul", 0.1, 0.9)}))
    task = setup.submit()
    first = setup.gate.run(task)
    answer(setup, task, first.request, choice="run_as_is")
    assert setup.gate.run(task).action == "run"
    assert not any(q.startswith("a1.") for q in setup.jev.calls[1].questions)


@pytest.mark.parametrize("response", [{"choice": "do_not_run"}, {"choice": "do_not_run", "default_applied": True}])
def test_do_not_run_or_silence_cancels_the_task(response):
    setup = GateSetup()
    task = setup.submit(acceptance=())
    first = setup.gate.run(task)
    answer(setup, task, first.request, **response)
    outcome = setup.gate.run(task)
    assert outcome.closed == "CANCELLED" and task_state(setup.ledger.events(task=task)) == "CANCELLED"
    assert setup.jev.calls == []


def test_after_three_clarifications_an_unclear_task_is_closed():
    setup = GateSetup(answers=confident(**{"a1.1": DecisionAnswer("noul", 0.1, 0.9)}))
    task = setup.submit(acceptance=("Je to dobré.",))
    for round_ in range(3):
        outcome = setup.gate.run(task)
        assert outcome.action == "ask"
        answer(setup, task, outcome.request, text=f"Pokus {round_ + 1}.")
    outcome = setup.gate.run(task)
    assert outcome.closed == "CLOSED_ABSTAINED"
    missing = setup.events(task, "TASK_CLOSED")[0]["body"]["missing"]
    assert "after 3 clarifications" in missing and "Je to dobré." in missing
    assert len(setup.events(task, "HIL_REQUEST")) == 3


def test_a_failed_decision_tier_makes_the_gate_ask_instead_of_guessing():
    setup = GateSetup(jev_error=ConnectorError("UNAVAILABLE", "HTTP 529"), worker_text="Not JSON.")
    task = setup.submit()
    assert setup.gate.run(task).action == "ask"


def test_an_estimate_above_the_budget_asks_to_raise_it():
    setup = GateSetup()
    task = setup.submit(budget_usd=0.001)
    outcome = setup.gate.run(task)
    assert (outcome.action, outcome.topology) == ("ask", "T2") and outcome.estimate_usd > 0.001
    request = setup.events(task, "HIL_REQUEST")[0]["body"]
    raise_option = request["options"][0]
    assert raise_option["id"] == "raise_budget" and raise_option["cost_usd"] >= outcome.estimate_usd
    assert request["default_on_silence"] == "do_not_run"
    assert task_state(setup.ledger.events(task=task)) == "HIL_WAIT"
    answer(setup, task, outcome.request, choice="raise_budget")
    events = setup.ledger.events(task=task)
    assert task_state(events) == "GATED" and task_facts(events).budget_usd == raise_option["cost_usd"]


def test_refusing_the_budget_is_visible_to_the_runtime():
    setup = GateSetup()
    task = setup.submit(budget_usd=0.001)
    outcome = setup.gate.run(task)
    answer(setup, task, outcome.request, choice="do_not_run")
    assert task_facts(setup.ledger.events(task=task)).refused


def test_the_runtime_recomputes_the_class_the_gate_decided():
    setup = GateSetup(answers=confident(a10=DecisionAnswer("choice", "client_confidential", 0.95)))
    task = setup.submit()
    outcome = setup.gate.run(task)
    assert gated_data_class(setup.ledger.events(task=task)) == outcome.data_class == "client_confidential"
````

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest core/tests/test_gate.py -q`
Expected: collection error — `ImportError: cannot import name 'gated_data_class' from 'ooat_core.gate'`.

- [ ] **Step 3: Read answers back, ask the operator, keep the order**

In `core/src/ooat_core/gate.py`:

Replace:

````python
acts on the answers whose confidence reaches their threshold, estimates the cost before anything runs, and appends
TOPOLOGY_DECIDED. F1 knows T0 (no agent) and T2 (one worker); rules for teams (A4, A5, A7) are recorded only.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
````

with:

````python
acts on the answers whose confidence reaches their threshold, estimates the cost before anything runs, and appends
TOPOLOGY_DECIDED. F1 knows T0 (no agent) and T2 (one worker); rules for teams (A4, A5, A7) are recorded only.
When the criteria cannot be checked or the estimate exceeds the budget, the Gate asks the operator (HIL_REQUEST);
the answers are read back from the ledger by task_facts(), which the task runtime (04c) uses too.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal
````

Replace:

````python
ACTOR = {"kind": "system", "id": "ooat-gate"}
WORKER_TIER = "workhorse"
BRANCHES = {"one": "A single line of work", "two": "Two independent parts", "many": "Three or more independent parts"}
DATA_CLASSES = {
````

with:

````python
ACTOR = {"kind": "system", "id": "ooat-gate"}
WORKER_TIER = "workhorse"
MAX_CLARIFICATIONS = 3  # spec rule A1, ADR 0009
BRANCHES = {"one": "A single line of work", "two": "Two independent parts", "many": "Three or more independent parts"}
DATA_CLASSES = {
````

Replace:

````python
    "special_category": "Health, genetic, biometric, religious, political or sexual-orientation data of a person",
}
````

with:

````python
    "special_category": "Health, genetic, biometric, religious, political or sexual-orientation data of a person",
}
CLARIFY_OPTIONS = [
    {"id": "clarify", "label": "Clarify: answer with text", "cost_usd": 0.0},
    {"id": "run_as_is", "label": "Run as it is", "cost_usd": 0.0},
    {"id": "do_not_run", "label": "Do not run", "cost_usd": 0.0, "acts": False},
]
````

Replace:

````python


def task_value_usd(body: dict, settings: GateSettings) -> float | None:
    value = body.get("value")
````

with:

````python


@dataclass(frozen=True)
class TaskFacts:
    """What the ledger says about a task so far, for the Gate and the task runtime."""
    submitted: str  # id of TASK_SUBMITTED
    state: str  # the text the Gate and the worker see
    criteria: list[str]  # the acceptance criteria, or the clarifications when the task had none
    declared: str  # the data class the operator declared
    risk_class: str
    budget_usd: float  # submitted or default, raised when the operator chose so
    value_usd: float | None
    clarifications: int  # clarifying questions the Gate has asked
    run_as_is: bool  # the operator chose to run although the criteria are not checkable
    refused: bool  # the operator chose not to run, or let a Gate question expire


def task_value_usd(body: dict, settings: GateSettings) -> float | None:
    value = body.get("value")
````

Replace:

````python


def gate_questions(criteria: list[str]) -> dict[str, DecisionQuestion]:
    """One batch for step A: A1 per criterion, A4, A5, A7, A10 (design 04 §4)."""
    questions = {
````

with:

````python


def _offers(event: dict, option: str) -> bool:
    return event["type"] == "HIL_REQUEST" and event["actor"] == ACTOR and \
        any(o["id"] == option for o in event["body"]["options"])


def task_facts(events: list[dict], settings: GateSettings = GateSettings()) -> TaskFacts:
    """Read a task's submission and the operator's answers to the Gate's questions from its events."""
    submitted = next(e for e in events if e["type"] == "TASK_SUBMITTED")
    body = submitted["body"]
    requests = {e["id"]: e for e in events if _offers(e, "clarify") or _offers(e, "raise_budget")}
    texts, budget, run_as_is, refused = [], body.get("budget_usd", settings.default_budget_usd), False, False
    for event in events:
        if event["type"] != "HIL_RESPONSE" or event["body"]["request"] not in requests:
            continue
        answer, request = event["body"], requests[event["body"]["request"]]
        choice = answer.get("choice")
        if answer.get("text") and choice in (None, "clarify"):
            texts.append(answer["text"])
        if choice == "raise_budget":
            budget = next(o["cost_usd"] for o in request["body"]["options"] if o["id"] == "raise_budget")
        run_as_is = run_as_is or choice == "run_as_is"
        refused = choice == "do_not_run" or answer.get("default_applied", False)
    criteria = list(body.get("acceptance", [])) or texts
    return TaskFacts(submitted["id"], task_text(body, texts), criteria, body.get("data_class", "internal"),
                     body.get("risk_class", "R0"), budget, task_value_usd(body, settings),
                     sum(_offers(e, "clarify") for e in events), run_as_is, refused)


def data_class_for(facts: TaskFacts, records: list[dict]) -> str:
    """The declared class, raised by the pre-scan and by a confident A10 answer; never lowered (ADR 0011)."""
    data_class = raised_class(facts.declared, facts.state)
    a10 = next((r for r in records if r["question"] == "a10"), None)
    if a10 is not None and a10["confidence"] >= a10["threshold"]:
        data_class = higher_class(data_class, a10["answer"])
    return data_class


def gated_data_class(events: list[dict], settings: GateSettings = GateSettings()) -> str:
    """The data class the Gate decided for the task, recomputed from its last TOPOLOGY_DECIDED."""
    decided = [e for e in events if e["type"] == "TOPOLOGY_DECIDED"]
    records = decided[-1]["body"].get("decisions", []) if decided else []
    return data_class_for(task_facts(events, settings), records)


def unclear_criteria(criteria: list[str], records: list[dict]) -> list[str]:
    """Criteria not confidently checkable: an answer below θ is not a pass, a missing answer neither."""
    answers = {r["question"]: r for r in records}
    unclear = []
    for number, criterion in enumerate(criteria, 1):
        record = answers.get(f"a1.{number}")
        if record is None or record["confidence"] < record["threshold"] or record["answer"] < 0.5:
            unclear.append(criterion)
    return unclear


def gate_questions(criteria: list[str], ask_a1: bool = True) -> dict[str, DecisionQuestion]:
    """One batch for step A: A1 per criterion, A4, A5, A7, A10 (design 04 §4)."""
    questions = {
````

Replace:

````python
            {"true": "A reader of the output alone can tell whether it is met",
             "false": "It is vague, subjective, or needs information outside the output"})
        for number, criterion in enumerate(criteria, 1)
    }
    questions["a4"] = DecisionQuestion("noul", "Does each step of this task depend on the result of the previous one?")
````

with:

````python
            {"true": "A reader of the output alone can tell whether it is met",
             "false": "It is vague, subjective, or needs information outside the output"})
        for number, criterion in enumerate(criteria, 1) if ask_a1
    }
    questions["a4"] = DecisionQuestion("noul", "Does each step of this task depend on the result of the previous one?")
````

Replace:

````python
        if task_state(events) != "SUBMITTED":
            raise ValueError(f"task {task} is not SUBMITTED")
        submitted = next(e for e in events if e["type"] == "TASK_SUBMITTED")
        body = submitted["body"]
        declared = body.get("data_class", "internal")
        budget = body.get("budget_usd", self._settings.default_budget_usd)
        value = task_value_usd(body, self._settings)
        criteria = list(body.get("acceptance", []))
        state = task_text(body, [])

        records, cost = self._ask(task, state, criteria, declared, body.get("risk_class", "R0"))
        answers = {r["question"]: r for r in records}
        data_class = raised_class(declared, state)
        a10 = answers.get("a10")
        if a10 is not None and a10["confidence"] >= a10["threshold"]:
            data_class = higher_class(data_class, a10["answer"])
        rules = ["A10"] if data_class != declared else []
        if value is not None and value < self._settings.v_min_usd:
            rules.append("A3")
        parameters = {"budget_usd": budget, **({"v_usd": value} if value is not None else {})}
        decided = {"records": records, "cost": cost, "parameters": parameters, "refs": [submitted["id"]]}

        try:
            estimate = self._estimate(task, state, criteria, data_class)
        except GatewayError as error:
            missing = f"no permitted route for {data_class} data: {error.message}"
````

with:

````python
        if task_state(events) != "SUBMITTED":
            raise ValueError(f"task {task} is not SUBMITTED")
        facts = task_facts(events, self._settings)
        if facts.refused:
            return self._close(task, facts.declared, facts.budget_usd, "CANCELLED",
                               "The operator chose not to run the task.")
        criteria, budget, value = facts.criteria, facts.budget_usd, facts.value_usd
        records, cost = [], None
        if criteria or facts.run_as_is:  # without any criterion the Gate asks the operator first (design 04 §4)
            records, cost = self._ask(task, facts.state, criteria, facts.declared, facts.risk_class,
                                      ask_a1=not facts.run_as_is)
        data_class = data_class_for(facts, records)
        rules = ["A10"] if data_class != facts.declared else []
        if value is not None and value < self._settings.v_min_usd:
            rules.append("A3")
        parameters = {"budget_usd": budget, **({"v_usd": value} if value is not None else {})}
        decided = {"records": records, "cost": cost, "parameters": parameters, "refs": [facts.submitted]}

        # A task that can never run, or is not worth its cost, is closed before the operator is asked anything.
        try:
            estimate = self._estimate(task, facts.state, criteria, data_class)
        except GatewayError as error:
            missing = f"no permitted route for {data_class} data: {error.message}"
````

Replace:

````python
            return self._close(task, data_class, budget, "CLOSED_ABSTAINED", "Not run: not worth its cost.", missing,
                               estimate)
        self._decided(task, "T2", rules, candidates, decided)
        return GateOutcome("run", "T2", data_class, budget, estimate)

    # Step A ------------------------------------------------------------------------------------------------------

    def _ask(self, task, state, criteria, declared, risk_class):
        """Ask the batch; returns (decision records, cost of the successful call or None)."""
        try:
            result = self._gateway.decide(DecisionRequest(state, gate_questions(criteria), declared, task=task))
        except GatewayError as error:
            self._record_failures(task, error)
````

with:

````python
            return self._close(task, data_class, budget, "CLOSED_ABSTAINED", "Not run: not worth its cost.", missing,
                               estimate)

        unclear = [] if facts.run_as_is else (unclear_criteria(criteria, records) if criteria else None)
        if unclear is None or unclear:
            eliminated = [{"topology": "T2", "model_usd": estimate, "eliminated_by": ["A1"]}]
            self._decided(task, "T0", ["A1", *rules], eliminated, decided)
            if facts.clarifications >= MAX_CLARIFICATIONS:
                missing = (f"after {MAX_CLARIFICATIONS} clarifications these acceptance criteria are still not "
                           f"checkable: " + ("none were given" if unclear is None else "; ".join(unclear)))
                return self._close(task, data_class, budget, "CLOSED_ABSTAINED", "Not run: unclear criteria.",
                                   missing, estimate)
            request = self._hil(task, _clarifying_question(unclear), CLARIFY_OPTIONS, "clarify", facts.submitted)
            return GateOutcome("ask", "T0", data_class, budget, estimate, request=request["id"])

        self._decided(task, "T2", rules, candidates, decided)
        if estimate > budget:
            raised = max(round(estimate * 1.2, 2), 0.01)  # a margin over the prior, which is no measurement yet
            question = (f"The estimated cost {estimate:.4f} USD exceeds the task budget {budget:.2f} USD. Raise the "
                        f"budget to {raised:.2f} USD, or do not run the task.")
            options = [{"id": "raise_budget", "label": f"Raise the budget to {raised:.2f} USD", "cost_usd": raised},
                       {"id": "do_not_run", "label": "Do not run", "cost_usd": 0.0, "acts": False}]
            request = self._hil(task, question, options, "raise_budget", facts.submitted)
            return GateOutcome("ask", "T2", data_class, budget, estimate, request=request["id"])
        return GateOutcome("run", "T2", data_class, budget, estimate)

    # Step A ------------------------------------------------------------------------------------------------------

    def _ask(self, task, state, criteria, declared, risk_class, ask_a1=True):
        """Ask the batch; returns (decision records, cost of the successful call or None)."""
        try:
            result = self._gateway.decide(DecisionRequest(state, gate_questions(criteria, ask_a1), declared,
                                                          task=task))
        except GatewayError as error:
            self._record_failures(task, error)
````

Replace:

````python
                                             cost=decided["cost"], body=body))

    def _close(self, task, data_class, budget, state, summary, missing, estimate=None) -> GateOutcome:
        self._ledger.append(new_event("TASK_CLOSED", task=task, actor=ACTOR, body={
            "state": state, "summary": summary, "missing": missing,
            "cost": {"contracts_usd": 0.0, "gate_usd": self._gate_cost(task), "orchestrator_usd": 0.0,
                     "critic_usd": 0.0}}))
        return GateOutcome("closed", "T0", data_class, budget, estimate, closed=state)
````

with:

````python
                                             cost=decided["cost"], body=body))

    def _hil(self, task, question, options, recommended, submitted) -> dict:
        deadline = (self._clock() + timedelta(hours=self._settings.hil_deadline_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return self._ledger.append(new_event("HIL_REQUEST", task=task, actor=ACTOR, refs=[submitted], body={
            "question": question, "options": options, "recommended": recommended, "default_on_silence": "do_not_run",
            "deadline": deadline, "blocking": True, "evidence": [submitted]}))

    def _close(self, task, data_class, budget, state, summary, missing=None, estimate=None) -> GateOutcome:
        body = {"state": state, "summary": summary,
                "cost": {"contracts_usd": 0.0, "gate_usd": self._gate_cost(task), "orchestrator_usd": 0.0,
                         "critic_usd": 0.0}}
        if missing is not None:
            body["missing"] = missing
        self._ledger.append(new_event("TASK_CLOSED", task=task, actor=ACTOR, body=body))
        return GateOutcome("closed", "T0", data_class, budget, estimate, closed=state)
````

Replace:

````python
        return sum(e.get("cost", {}).get("usd", 0.0) for e in self._ledger.events(task=task)
                   if e["actor"] == ACTOR)
````

with:

````python
        return sum(e.get("cost", {}).get("usd", 0.0) for e in self._ledger.events(task=task)
                   if e["actor"] == ACTOR)


def _clarifying_question(unclear: list[str] | None) -> str:
    if unclear is None:
        return ("The task has no acceptance criteria, so nobody could tell when it is done. Reply with the criteria "
                "as text, run it as it is, or do not run it.")
    listed = "; ".join(f"{n}) {c}" for n, c in enumerate(unclear, 1))
    return (f"These acceptance criteria cannot be checked from the output alone: {listed}. Reply with a "
            "clarification as text, run it as it is, or do not run it.")
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest core/tests/test_gate.py -q` → Expected: `23 passed`.
Run: `python -m pytest -q` → Expected: `542 passed, 4 skipped`.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/gate.py core/tests/test_gate.py
git commit -m "feat(core): the Gate asks the operator to clarify criteria or raise the budget"
```

---

### Task 5: Documentation

**Files:**
- Modify: `core/description.md`, `docs/description.md`, `README.md`, `.claude/lessons.md`

- [ ] **Step 1: Update the As-is docs**

In `core/description.md`:

Replace:

````markdown
metering, typed decisions with a text-model fallback), the connector contract used by the packages in
`adapters/`, and the `ooat connectors` operator command. Gate, workers and API are not implemented yet.
````

with:

````markdown
metering, typed decisions with a text-model fallback), the connector contract used by the packages in
`adapters/`, the `ooat connectors` operator command, and the Topology Gate for T0–T2. Workers, task commands
and API are not implemented yet.
````

Replace:

````markdown
  `merged_answers()`, and the text-model fallback `fallback_prompt()` / `parse_fallback()` (ADR 0011)
- `config.py` — `load_config()` for `ooat.toml`: ledger URL, per-tier pins, connector settings; no secrets,
````

with:

````markdown
  `merged_answers()`, and the text-model fallback `fallback_prompt()` / `parse_fallback()` (ADR 0011)
- `pii.py` — `scan()` / `raised_class()`: local pre-scan for e-mail, phone, IBAN, card and birth numbers; the
  gateway runs it before routing and raises the data class to `personal` on a hit, never lowering it
- `thresholds.py` — `threshold()`: θ per decision point, engine and model version from TASK_RATED verdicts on
  decision records (interim 0.8 for a decision connector, 1 for the text fallback; floor 0.8 until 20 ratings)
- `gate.py` — `Gate.run(task)`: step A as one decision batch (A1 per criterion, A4, A5, A7, A10), data class
  raised by pre-scan and a confident A10, estimate of worker plus acceptance checks, then T0 (closed: no permitted
  route, not worth its value, unclear after 3 clarifications, cancelled), a clarifying or budget `HIL_REQUEST`,
  or T2. `task_facts()` and `gated_data_class()` read the task and the operator's answers back for the runtime
- `config.py` — `load_config()` for `ooat.toml`: ledger URL, per-tier pins, connector settings; no secrets,
````

Replace:

````markdown
`Ledger.open(url)`, `new_event()`, `ArtifactStore`, `BlobStore`, `task_state()`, `contract_state()`, `validate()`,
`Gateway`, `Registry.discover()`, `load_config()`, `load_routing()`, `SecretResolver`, `connector_admin`, the `ooat`
console script.
````

with:

````markdown
`Ledger.open(url)`, `new_event()`, `ArtifactStore`, `BlobStore`, `task_state()`, `contract_state()`, `validate()`,
`Gateway`, `Gate`, `task_facts()`, `threshold()`, `Registry.discover()`, `load_config()`, `load_routing()`,
`SecretResolver`, `connector_admin`, the `ooat` console script.
````

In `docs/description.md`:

Replace:

````markdown
the starter catalog holds role families and capability names only; `ooat-core` has the ledger foundation
and the provider gateway with model and decision connectors (no Gate, workers or API yet).
````

with:

````markdown
the starter catalog holds role families and capability names only; `ooat-core` has the ledger foundation
the provider gateway with model and decision connectors, and the Topology Gate for T0–T2 (no workers, task
commands or API yet).
````

In `README.md`:

Replace:

````markdown
Early F1 (spec draft v0.1): JSON Schemas, the starter catalog taxonomy, the ledger, the provider gateway with
three model connectors and one decision connector (Jev), and the `ooat connectors` command exist; the task
runtime (Gate, workers) does not yet.
Decision records are in `docs/adr/`.
````

with:

````markdown
Early F1 (spec draft v0.1): JSON Schemas, the starter catalog taxonomy, the ledger, the provider gateway with
three model connectors and one decision connector (Jev), the `ooat connectors` command and the Topology Gate
for T0–T2 exist; workers and the task commands do not yet.
Decision records are in `docs/adr/`.
````

In `.claude/lessons.md`:

Replace:

````markdown
  so `routing.json` prices both names and decisions record the version. Docs: https://docs.typesafe.ai/llms.txt
````

with:

````markdown
  so `routing.json` prices both names and decisions record the version. Docs: https://docs.typesafe.ai/llms.txt
- Regexes that scan task text (pii.py) must stay linear: an unbounded `[...]+@` local part backtracked from every
  position, so a 100k-character attachment took minutes. Bound repeats and start tokens with a lookbehind; the
  test `test_a_long_attachment_is_scanned_in_linear_time` guards it.
````

- [ ] **Step 2: Check the docs match the code**

Run: `python -m pytest -q` → Expected: `542 passed, 4 skipped`.
Run: `git grep -n "Topology Gate for T0" -- README.md docs/description.md core/description.md` → Expected: one line in each file.

- [ ] **Step 3: Commit**

```bash
git add core/description.md docs/description.md README.md .claude/lessons.md
git commit -m "docs: Topology Gate T0-T2, pre-scan and thresholds"
```

---

## After the last task

- Next: plan 04c (task runtime and commands) consumes `Gate.run()`, `GateOutcome`, `task_facts()`, `gated_data_class()`, `task_text()`, `threshold()` and reads `GateSettings` from `ooat.toml`.

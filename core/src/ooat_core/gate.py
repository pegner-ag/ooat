"""Topology Gate for T0–T2 (spec §4 step A; design 04 §4; ADR 0009, ADR 0011).

The Gate reads a SUBMITTED task from the ledger, asks the decision tier one batch of typed questions about it,
acts on the answers whose confidence reaches their threshold, estimates the cost before anything runs, and appends
TOPOLOGY_DECIDED. F1 knows T0 (no agent) and T2 (one worker); rules for teams (A4, A5, A7) are recorded only.
When the criteria cannot be checked or the estimate exceeds the budget, the Gate asks the operator (HIL_REQUEST);
the answers are read back from the ledger by task_facts(), which the task runtime (04c) uses too. A clarification
returns the task to SUBMITTED (ADR 0009); narrowing the scope returns a GATED task to the Gate (ADR 0009 amendment).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from .connectors import DecisionQuestion, DecisionRequest, ModelRequest
from .gateway import Gateway, GatewayError
from .ledger import Ledger, new_event
from .pii import higher_class, raised_class
from .state import task_state
from .thresholds import GATE_EVENTS, acts_alone, decision_point, threshold

ACTOR = {"kind": "system", "id": "ooat-gate"}
WORKER_TIER = "workhorse"
# A task that does not state its risk class is judged by the stricter R1 tolerance, never the laxer R0
# (ADR 0011: below θ the safer outcome applies).
DEFAULT_RISK_CLASS = "R1"
MAX_CLARIFICATIONS = 3  # spec rule A1, ADR 0009
MAX_BUDGET_QUESTIONS = 3  # narrowing the scope may loop; the same limit as clarifications
BRANCHES = {"one": "A single line of work", "two": "Two independent parts", "many": "Three or more independent parts"}
DATA_CLASSES = {
    "public": "Published or meant for publication",
    "internal": "Internal business information without personal data",
    "client_confidential": "A client's confidential information (contracts, finances, trade secrets)",
    "personal": "Data about an identifiable person (name with contact, ID number, account)",
    "special_category": "Health, genetic, biometric, religious, political or sexual-orientation data of a person",
}
CLARIFY_OPTIONS = [
    {"id": "clarify", "label": "Clarify: answer with text", "cost_usd": 0.0},
    {"id": "run_as_is", "label": "Run as it is", "cost_usd": 0.0},
    {"id": "do_not_run", "label": "Do not run", "cost_usd": 0.0, "acts": False},
]


@dataclass(frozen=True)
class GateSettings:
    value_usd: dict = field(default_factory=lambda: {"A": 1000.0, "B": 300.0, "C": 50.0})
    v_min_usd: float = 15.0  # rule A3
    default_budget_usd: float = 2.0
    expected_output_tokens: int = 2000  # prior for the worker's deliverable
    hil_deadline_hours: float = 48.0  # spec §8: CLARIFYING closes after 48 h without an answer


@dataclass(frozen=True)
class GateOutcome:
    action: Literal["run", "ask", "closed"]
    topology: str
    data_class: str
    budget_usd: float
    estimate_usd: float | None = None
    request: str | None = None  # the HIL_REQUEST to answer when action == "ask"
    closed: str | None = None  # the TASK_CLOSED state when action == "closed"


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
    expired: bool  # ... by letting it expire (default applied), not by choosing
    budget_questions: int  # budget questions the Gate has asked
    narrowed: bool  # the operator narrowed the scope and the Gate has not decided again since
    narrowings: int  # how often the scope was narrowed; each halves the output prior of the estimate
    decided: list  # decision records of every earlier TOPOLOGY_DECIDED: a raised class survives later rounds


def task_value_usd(body: dict, settings: GateSettings) -> float | None:
    value = body.get("value")
    if value is None:
        return None
    return value["usd"] if "usd" in value else settings.value_usd[value["class"]]


def task_text(body: dict, clarifications: list[str], narrowings: list[str] = ()) -> str:
    """The state the Gate and the worker see: goal, expected output, criteria, the operator's clarifications and
    narrowings of the scope."""
    lines = [f"Goal: {body['goal']}"]
    if body.get("expected_output"):
        lines.append(f"Expected output: {body['expected_output']}")
    for number, criterion in enumerate(body.get("acceptance", []), 1):
        lines.append(f"Acceptance criterion {number}: {criterion}")
    for number, text in enumerate(clarifications, 1):
        lines.append(f"Clarification {number}: {text}")
    for number, text in enumerate(narrowings, 1):
        lines.append(f"Narrowed scope {number}: {text}")
    return "\n".join(lines)


def _offers(event: dict, option: str) -> bool:
    return event["type"] == "HIL_REQUEST" and event["actor"] == ACTOR and \
        any(o["id"] == option for o in event["body"]["options"])


def task_facts(events: list[dict], settings: GateSettings = GateSettings()) -> TaskFacts:
    """Read a task's submission and the operator's answers to the Gate's questions from its events."""
    submitted = next(e for e in events if e["type"] == "TASK_SUBMITTED")
    body = submitted["body"]
    requests = {e["id"]: e for e in events if _offers(e, "clarify") or _offers(e, "raise_budget")}
    texts, narrowings, budget = [], [], body.get("budget_usd", settings.default_budget_usd)
    run_as_is = refused = expired = narrowed = False
    decided = []
    for event in events:
        if event["type"] == "TOPOLOGY_DECIDED":
            narrowed = False  # the Gate has decided on the narrowed scope
            decided += event["body"].get("decisions", [])
        if event["type"] != "HIL_RESPONSE" or event["body"]["request"] not in requests:
            continue
        answer, request = event["body"], requests[event["body"]["request"]]
        choice = answer.get("choice")
        if choice is None and _offers(request, "raise_budget"):
            choice = "narrow_scope"  # the question asks for the narrowed scope as text
        if choice == "narrow_scope":
            narrowings += [answer["text"]] if answer.get("text") else []
            narrowed = True
        elif answer.get("text") and choice in (None, "clarify"):
            texts.append(answer["text"])
        if choice == "raise_budget":
            budget = next(o["cost_usd"] for o in request["body"]["options"] if o["id"] == "raise_budget")
        run_as_is = run_as_is or choice == "run_as_is"
        expired = answer.get("default_applied", False)
        refused = choice == "do_not_run" or expired
    criteria = list(body.get("acceptance", [])) or texts
    return TaskFacts(submitted["id"], task_text(body, texts, narrowings), criteria, body.get("data_class", "internal"),
                     body.get("risk_class", DEFAULT_RISK_CLASS), budget, task_value_usd(body, settings),
                     sum(_offers(e, "clarify") for e in events), run_as_is, refused, expired,
                     sum(_offers(e, "raise_budget") for e in events), narrowed, len(narrowings), decided)


def data_class_for(facts: TaskFacts, records: list[dict] = ()) -> str:
    """The declared class, raised by the pre-scan and by every confident A10 answer of this and earlier rounds;
    never lowered (ADR 0011)."""
    data_class = raised_class(facts.declared, facts.state)
    for record in [*facts.decided, *records]:
        if record["question"] == "a10" and acts_alone(record["confidence"], record["threshold"]):
            data_class = higher_class(data_class, record["answer"])
    return data_class


def gated_data_class(events: list[dict], settings: GateSettings = GateSettings()) -> str:
    """The data class the Gate decided for the task, recomputed from all its TOPOLOGY_DECIDED events."""
    return data_class_for(task_facts(events, settings))


def unclear_criteria(criteria: list[str], records: list[dict]) -> list[str]:
    """Criteria not confidently checkable: an answer below θ is not a pass, a missing answer neither."""
    answers = {r["question"]: r for r in records}
    unclear = []
    for number, criterion in enumerate(criteria, 1):
        record = answers.get(f"a1.{number}")
        if record is None or not acts_alone(record["confidence"], record["threshold"]) or record["answer"] < 0.5:
            unclear.append(criterion)
    return unclear


def gate_questions(criteria: list[str], ask_a1: bool = True) -> dict[str, DecisionQuestion]:
    """One batch for step A: A1 per criterion, A4, A5, A7, A10 (design 04 §4)."""
    questions = {
        f"a1.{number}": DecisionQuestion(
            "noul", "Given the task and its clarifications, can this acceptance criterion be checked from the "
                    f"delivered output alone, without asking anyone? Criterion: {criterion}",
            {"true": "A reader of the output alone can tell whether it is met",
             "false": "It is vague, subjective, or needs information outside the output"})
        for number, criterion in enumerate(criteria, 1) if ask_a1
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
        facts = task_facts(events, self._settings)
        state = task_state(events)
        if state != "SUBMITTED" and not (state == "GATED" and facts.narrowed):
            raise ValueError(f"task {task} is not SUBMITTED, nor GATED with a narrowed scope")
        if facts.expired:  # spec §8: no answer in time closes the task as abstained
            return self._close(task, facts.declared, facts.budget_usd, "CLOSED_ABSTAINED",
                               "Not run: the Gate's question was not answered in time.",
                               "an answer to the Gate's question before its deadline")
        if facts.refused:
            return self._close(task, facts.declared, facts.budget_usd, "CANCELLED",
                               "The operator chose not to run the task.")
        criteria, budget, value = facts.criteria, facts.budget_usd, facts.value_usd
        records, cost, asked = [], None, bool(criteria or facts.run_as_is)
        if asked:  # without any criterion the Gate asks the operator first (design 04 §4)
            records, cost = self._ask(task, facts.state, criteria, data_class_for(facts), facts.risk_class,
                                      ask_a1=not facts.run_as_is)
        data_class = data_class_for(facts, records)
        rules = ["A10"] if data_class != facts.declared else []
        if value is not None and value < self._settings.v_min_usd:
            rules.append("A3")
        parameters = {"budget_usd": budget, **({"v_usd": value} if value is not None else {})}
        decided = {"records": records, "cost": cost, "parameters": parameters, "refs": [facts.submitted]}

        # A task that can never run, or is not worth its cost, is closed before the operator is asked anything.
        try:
            estimate = self._estimate(task, facts.state, criteria, data_class, facts.narrowings)
        except GatewayError as error:
            if error.code != "NOT_PERMITTED":  # a quota cool-down passes: the task stays SUBMITTED for a retry
                if cost is not None:
                    self._ledger.append(new_event("DECISION", task=task, actor=ACTOR, cost=cost, body={
                        "decision": f"Gate stopped before deciding ({error.code}); it runs again later.",
                        "rationale": error.message[:500] or error.code}))
                raise
            missing = f"no permitted route for {data_class} data: {error.message}"
            self._decided(task, "T0", rules, [{"topology": "T2", "eliminated_by": rules or ["A10"]}], decided)
            return self._close(task, data_class, budget, "CLOSED_ABSTAINED", "Not run: no permitted route.", missing)
        candidates = [{"topology": "T2", "model_usd": estimate}]
        if value is not None and estimate > value:
            self._decided(task, "T0", rules, candidates, decided)
            missing = f"the estimated cost {estimate:.4f} USD exceeds the task value {value:.2f} USD"
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
            failed = asked and not records  # the decision tier did not answer at all
            request = self._hil(task, _clarifying_question(unclear, failed), CLARIFY_OPTIONS, "clarify",
                                facts.submitted)
            return GateOutcome("ask", "T0", data_class, budget, estimate, request=request["id"])

        if estimate > budget and facts.budget_questions >= MAX_BUDGET_QUESTIONS:
            self._decided(task, "T0", rules, candidates, decided)
            missing = (f"after {MAX_BUDGET_QUESTIONS} budget questions the estimated cost {estimate:.4f} USD still "
                       f"exceeds the budget {budget:.2f} USD")
            return self._close(task, data_class, budget, "CLOSED_ABSTAINED", "Not run: over budget.", missing,
                               estimate)
        self._decided(task, "T2", rules, candidates, decided)
        if estimate > budget:
            # a margin over the prior, which is no measurement yet; whole cents, never below the estimate
            raised = max(math.ceil(estimate * 120) / 100, 0.01)
            question = (f"The estimated cost {estimate:.4f} USD exceeds the task budget {budget:.2f} USD. Raise the "
                        f"budget to {raised:.2f} USD, narrow the scope (answer with text), or do not run the task.")
            options = [{"id": "raise_budget", "label": f"Raise the budget to {raised:.2f} USD", "cost_usd": raised},
                       {"id": "narrow_scope", "label": "Narrow the scope: answer with text", "cost_usd": 0.0},
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

    def _estimate(self, task, state, criteria, data_class, narrowings=0) -> float:
        """Worker plus acceptance checks, one attempt; raises GatewayError when no route is permitted.

        The output prior dominates the estimate, so each narrowing of the scope halves it (at least 100 tokens);
        otherwise narrowing could never bring a task under its budget.
        """
        tokens = max(self._settings.expected_output_tokens // 2 ** narrowings, 100)
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

    def _gate_cost(self, task) -> float:
        return sum(e.get("cost", {}).get("usd", 0.0) for e in self._ledger.events(task=task)
                   if e["actor"] == ACTOR)


def _clarifying_question(unclear: list[str] | None, failed: bool = False) -> str:
    if failed:
        listed = "; ".join(f"{n}) {c}" for n, c in enumerate(unclear, 1))
        return (f"The acceptance criteria could not be checked automatically (the decision tier did not answer): "
                f"{listed}. Reply with a clarification as text, run it as it is, or do not run it.")
    if unclear is None:
        return ("The task has no acceptance criteria, so nobody could tell when it is done. Reply with the criteria "
                "as text, run it as it is, or do not run it.")
    listed = "; ".join(f"{n}) {c}" for n, c in enumerate(unclear, 1))
    return (f"These acceptance criteria cannot be checked from the output alone: {listed}. Reply with a "
            "clarification as text, run it as it is, or do not run it.")

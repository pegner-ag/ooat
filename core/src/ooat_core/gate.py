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
# A task that does not state its risk class is judged by the stricter R1 tolerance, never the laxer R0
# (ADR 0011: below θ the safer outcome applies).
DEFAULT_RISK_CLASS = "R1"
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

        records, cost = self._ask(task, state, criteria, declared, body.get("risk_class", DEFAULT_RISK_CLASS))
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

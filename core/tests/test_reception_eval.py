"""The eval runner for the reception's message set (plan 08a task 11)."""

import importlib.util
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[2] / "evals" / "reception" / "run.py"
spec = importlib.util.spec_from_file_location("reception_eval", RUNNER)
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def test_the_figures():
    cases = [{"text": "a", "expected": "answer"}, {"text": "b", "expected": "task"}, {"text": "c", "expected": "ask"},
             {"text": "d", "expected": "task"}]
    got = {"a": ("answer", 0.01), "b": ("confirm", 0.02), "c": ("ask", 0.01), "d": ("task", 0.04)}
    result = run.evaluate(cases, lambda case: got[case["text"]])
    assert result["as_expected"] == 0.75 and result["without_question"] == 0.5
    assert result["mean_usd"] == pytest.approx(0.02)


def test_a_bad_case_is_named_by_its_number():
    with pytest.raises(ValueError, match="case 2: expected"):
        run.load_cases('[{"text": "a", "expected": "answer"}, {"text": "b"}]')
    with pytest.raises(ValueError, match="case 1: it needs a text"):
        run.load_cases('[{"expected": "answer"}]')


def test_the_example_set_is_valid():
    cases = run.load_cases((RUNNER.parent / "example.json").read_text(encoding="utf-8"))
    assert {c["expected"] for c in cases} >= {"answer", "task", "ask", "continue_task", "status", "cancel", "command"}


def test_the_runner_decides_in_a_scratch_ledger(tmp_path):
    from reception_fakes import ReceptionModel, decision
    from runtime_fakes import acknowledge, decisions, routing_document

    from ooat_core.config import parse_config
    from ooat_core.connectors.registry import Registry
    from ooat_core.ledger import Ledger
    from ooat_core.routing import RoutingPolicy

    url = f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}"
    model, jev = ReceptionModel([decision("status", "Běží.")]), decisions()
    ledger = Ledger.open(url)
    for connector in (model, jev):
        acknowledge(ledger, connector)
    before = len(ledger.events())
    ledger.close()
    reception = run._reception(parse_config({"ledger": {"url": url}}), None, Registry([model, jev]),
                               RoutingPolicy(routing_document()))
    decide = run._decider(reception, "docs")
    got, usd = decide({"text": "Už je to hotové?", "expected": "status",
                       "context": [{"person": "Najdi ceny.", "reception": "Dělám na tom."}]})
    assert got == "status" and usd > 0
    assert "Person: Najdi ceny." in model.calls[0].prompt
    ledger = Ledger.open(url)
    assert len(ledger.events()) == before  # nothing written to the operator's ledger
    ledger.close()

"""The eval runner for the reception's message set (plan 08a task 11)."""

import importlib.util
import json
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


def test_a_candidate_with_no_expected_decision_is_refused():
    with pytest.raises(ValueError, match="case 1: expected"):
        run.load_cases(json.dumps([{"text": "x", "expected": None}]))


def test_a_picked_candidate_keeps_its_extra_keys():
    assert run.load_cases(json.dumps([{"text": "x", "expected": "task", "got": "confirm", "correction": "y",
                                       "then": "task"}]))[0]["got"] == "confirm"


def test_a_folder_of_cases_is_read_in_name_order(tmp_path):
    (tmp_path / "b.json").write_text(json.dumps([{"text": "b", "expected": "task"}]), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps([{"text": "a", "expected": "ask"}]), encoding="utf-8")
    assert [c["text"] for c in run.load_folder(tmp_path)] == ["a", "b"]


def test_a_bad_file_in_the_folder_is_named(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps([{"text": "a"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="a.json: case 1"):
        run.load_folder(tmp_path)


def test_the_committed_cases_load():
    folder = RUNNER.parent / "cases"
    if any(folder.glob("*.json")):
        run.load_folder(folder)


def test_a_run_below_the_minimum_share_falls_short():
    assert run.short_of({"as_expected": 0.75}, 0.8) and not run.short_of({"as_expected": 0.8}, 0.8)
    assert not run.short_of({"as_expected": 0.1}, None)

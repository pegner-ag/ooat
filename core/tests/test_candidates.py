"""Eval candidates from the ledger (plan 09 decision 8)."""

from pathlib import Path

import importlib.util

import pytest

from ooat_core.ids import new_id

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def candidates():
    spec = importlib.util.spec_from_file_location("eval_candidates", REPO / "evals" / "candidates.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    cases, left_out = candidates.task_candidates(events, "internal", task_class=lambda task: "internal")
    assert left_out == 0
    assert cases == [{"task": task, "goal": "Shrň smlouvu.", "acceptance": ["Nejvýše 300 slov."],
                      "state": "CLOSED_DONE", "note": "Moc dlouhé.", "value_class": "B"}]


def test_a_case_whose_earlier_turn_was_above_the_max_class_is_left_out(candidates):
    cnv = new_id("cnv")
    first = message(cnv, text="Jan Novák, 760101/0018", data_class="personal")
    earlier = decided(cnv, [first["id"]], "answer", reply="Rozumím.", data_class="personal")
    asked = message(cnv, text="Titulek.")
    events = [first, earlier, asked, decided(cnv, [asked["id"]], "confirm"), message(cnv, tap="differently")]
    assert candidates.reception_candidates(events, "internal") == ([], 1)


def test_a_rejected_task_above_the_max_class_is_left_out(candidates):
    task = new_id("tsk")
    events = [{"id": new_id("evt"), "type": "TASK_SUBMITTED", "task": task, "refs": [], "body": {"goal": "x"}},
              {"id": new_id("evt"), "type": "TASK_RATED", "task": task,
               "body": {"accepted": False, "value_class": "C"}}]
    assert candidates.task_candidates(events, "internal", task_class=lambda t: "personal") == ([], 1)


def test_main_writes_both_lists_outside_the_repository(candidates, tmp_path):
    import io
    import json
    ledger = (tmp_path / "ledger.sqlite").as_posix()
    (tmp_path / "ooat.toml").write_text(f'[ledger]\nurl = "sqlite:///{ledger}"\n', encoding="utf-8")
    out, printed = tmp_path / "candidates.json", io.StringIO()
    assert candidates.main(["--config", str(tmp_path / "ooat.toml"), "--out", str(out)], stdout=printed) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"reception": [], "tasks": []}
    assert "0 reception and 0 task candidates" in printed.getvalue()
    with pytest.raises(ValueError, match="outside the repository"):
        candidates.main(["--config", str(tmp_path / "ooat.toml"), "--out", str(REPO / "evals" / "x.json")])
    assert not (REPO / "evals" / "x.json").exists()


def test_a_rating_note_with_personal_data_raises_the_task_above_the_max_class(candidates):
    task = new_id("tsk")
    events = [{"id": new_id("evt"), "type": "TASK_SUBMITTED", "task": task, "refs": [], "body": {"goal": "x"}},
              {"id": new_id("evt"), "type": "TASK_RATED", "task": task,
               "body": {"accepted": False, "value_class": "C", "note": "Volal jan.novak@example.cz"}}]
    assert candidates.task_candidates(events, "internal", task_class=lambda t: "internal") == ([], 1)

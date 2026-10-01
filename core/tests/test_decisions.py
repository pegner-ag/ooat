import math

import pytest

from ooat_core.connectors import DecisionAnswer, DecisionQuestion
from ooat_core.decisions import REVERSED, checked_answers, check_questions, merged_answers, with_reversed_choices

NOUL = DecisionQuestion("noul", "Is the acceptance criterion checkable from the output alone?")
CHOICE = DecisionQuestion("choice", "How many independent branches?", {"one": "1", "two": "2", "many": "3+"})
SCORE = DecisionQuestion("score", "How decomposable?", ["not", "partly", "fully"])


def test_well_formed_questions_pass():
    check_questions({"a1.1": NOUL, "a5": CHOICE, "a7": SCORE,
                     "a10": DecisionQuestion("noul", "Personal data?", {"true": "yes", "false": "no"})})


@pytest.mark.parametrize("questions, message", [
    ({}, "at least one question"),
    ({"A1": NOUL}, "question id"),
    ({"a1~reversed": NOUL}, "question id"),
    ({"a1": DecisionQuestion("rank", "x")}, "type"),
    ({"a1": DecisionQuestion("noul", " ")}, "instructions"),
    ({"a1": DecisionQuestion("noul", "x", {"yes": "y"})}, "noul criteria"),
    ({"a1": DecisionQuestion("choice", "x", {"only": "1"})}, "2 to 255 options"),
    ({"a1": DecisionQuestion("choice", "x", {f"o{i}": "d" for i in range(256)})}, "2 to 255 options"),
    ({"a1": DecisionQuestion("choice", "x", ["a", "b"])}, "2 to 255 options"),
    ({"a1": DecisionQuestion("choice", "x", {"a": "", "b": "d"})}, "description"),
    ({"a1": DecisionQuestion("score", "x", ["only"])}, "2 to 10 levels"),
    ({"a1": DecisionQuestion("score", "x", [str(i) for i in range(11)])}, "2 to 10 levels"),
])
def test_malformed_questions_are_refused(questions, message):
    with pytest.raises(ValueError, match=message):
        check_questions(questions)


def test_choice_questions_get_a_reversed_twin_and_others_do_not():
    expanded = with_reversed_choices({"a1": NOUL, "a5": CHOICE})
    assert list(expanded) == ["a1", "a5", "a5" + REVERSED]
    assert list(expanded["a5" + REVERSED].criteria) == ["many", "two", "one"]
    assert expanded["a5" + REVERSED].criteria["many"] == "3+"


def answer(type_, value, confidence, probabilities=None):
    return DecisionAnswer(type_, value, confidence, probabilities)


def test_answers_that_fit_their_questions_are_kept():
    questions = {"a1": NOUL, "a5": CHOICE, "a7": SCORE}
    answers = {"a1": answer("noul", 0.9, 0.9), "a5": answer("choice", "two", 0.7, {"one": 0.2, "two": 0.7}),
               "a7": answer("score", 1.4, 0.6, {"0": 0.1, "1": 0.4, "2": 0.5}), "extra": answer("noul", 1, 1)}
    assert set(checked_answers(questions, answers)) == {"a1", "a5", "a7"}


@pytest.mark.parametrize("bad, message", [
    ({}, "no answer"),
    ({"a5": answer("noul", 0.5, 0.5)}, "type"),
    ({"a5": answer("choice", "seven", 0.9)}, "not one of the options"),
    ({"a5": answer("choice", "two", 1.5)}, "confidence"),
    ({"a5": answer("choice", "two", math.nan)}, "confidence"),
    ({"a5": answer("choice", "two", 0.9, {"two": -0.1})}, "probabilities"),
    ({"a5": answer("choice", "two", 0.9, {"seven": 0.9})}, "probabilities"),
])
def test_answers_that_do_not_fit_are_refused(bad, message):
    with pytest.raises(ValueError, match=message):
        checked_answers({"a5": CHOICE}, bad)


@pytest.mark.parametrize("question, bad", [
    (NOUL, answer("noul", 1.2, 1.0)),
    (NOUL, answer("noul", True, 1.0)),
    (SCORE, answer("score", 2.5, 0.5)),
    (SCORE, answer("score", "1", 0.5)),
])
def test_values_out_of_range_are_refused(question, bad):
    with pytest.raises(ValueError, match="value"):
        checked_answers({"q": question}, {"q": bad})


def test_merging_keeps_the_lower_confidence_when_both_orders_agree():
    answers = {"a5": answer("choice", "two", 0.9, {"two": 0.9}), "a5" + REVERSED: answer("choice", "two", 0.7)}
    merged = merged_answers({"a5": CHOICE}, answers)
    assert list(merged) == ["a5"] and merged["a5"].value == "two" and merged["a5"].confidence == 0.7
    assert merged["a5"].probabilities == {"two": 0.9}


def test_merging_sets_confidence_to_zero_when_the_orders_disagree():
    answers = {"a5": answer("choice", "two", 0.95), "a5" + REVERSED: answer("choice", "one", 0.95)}
    assert merged_answers({"a5": CHOICE}, answers)["a5"].confidence == 0

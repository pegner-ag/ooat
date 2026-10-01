"""Typed decision questions: shape checks, the order-swap check and answer checks (spec §5, §6; ADR 0011).

Answers come from a connector or a text model and are untrusted: every answer is checked against its question
before the runtime may act on it.
"""

import math
import re

from .connectors import DecisionAnswer, DecisionQuestion

QUESTION_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
# Suffix of the reversed twin of a choice question; "~" cannot occur in a question id, so twins never collide.
REVERSED = "~reversed"
MAX_OPTIONS = 255  # Jev's documented limit per choice question
MAX_LEVELS = 10


def _text(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def check_questions(questions: dict[str, DecisionQuestion]) -> None:
    """Raise ValueError unless every question is well formed."""
    if not questions:
        raise ValueError("a decision request needs at least one question")
    for question_id, question in questions.items():
        where = f"question {question_id!r}"
        if not isinstance(question_id, str) or not QUESTION_ID.match(question_id):
            raise ValueError(f"{where}: question id must match {QUESTION_ID.pattern}")
        if question.type not in ("noul", "choice", "score"):
            raise ValueError(f"{where}: unknown type {question.type!r}")
        if not _text(question.instructions):
            raise ValueError(f"{where}: instructions are empty")
        criteria = question.criteria
        if question.type == "noul":
            if criteria is not None and (not isinstance(criteria, dict) or set(criteria) != {"true", "false"}
                                         or not all(_text(v) for v in criteria.values())):
                raise ValueError(f"{where}: noul criteria are None or {{'true': ..., 'false': ...}}")
        elif question.type == "choice":
            if not isinstance(criteria, dict) or not 2 <= len(criteria) <= MAX_OPTIONS:
                raise ValueError(f"{where}: a choice needs 2 to {MAX_OPTIONS} options as {{option: description}}")
            if not all(_text(k) and _text(v) for k, v in criteria.items()):
                raise ValueError(f"{where}: every option needs a name and a description")
        elif not isinstance(criteria, list) or not 2 <= len(criteria) <= MAX_LEVELS or not all(map(_text, criteria)):
            raise ValueError(f"{where}: a score needs 2 to {MAX_LEVELS} levels as a list of descriptions")


def with_reversed_choices(questions: dict[str, DecisionQuestion]) -> dict[str, DecisionQuestion]:
    """Add a twin with the reversed option order for every choice question (order-swap check, spec §6)."""
    expanded = dict(questions)
    for question_id, question in questions.items():
        if question.type == "choice":
            reversed_criteria = dict(reversed(list(question.criteria.items())))
            expanded[question_id + REVERSED] = DecisionQuestion("choice", question.instructions, reversed_criteria)
    return expanded


def _probability(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def _check_answer(question: DecisionQuestion, answer: DecisionAnswer, where: str) -> None:
    if answer.type != question.type:
        raise ValueError(f"{where}: answer type {answer.type!r} does not match question type {question.type!r}")
    if not _probability(answer.confidence):
        raise ValueError(f"{where}: confidence must be a number from 0 to 1")
    if question.type == "noul":
        if not _probability(answer.value):
            raise ValueError(f"{where}: a noul value must be a number from 0 to 1")
        allowed = {"true", "false"}
    elif question.type == "choice":
        if answer.value not in question.criteria:
            raise ValueError(f"{where}: {answer.value!r} is not one of the options")
        allowed = set(question.criteria)
    else:
        top = len(question.criteria) - 1
        if not (type(answer.value) in (int, float) and math.isfinite(answer.value) and 0 <= answer.value <= top):
            raise ValueError(f"{where}: a score value must be a number from 0 to {top}")
        allowed = {str(level) for level in range(top + 1)}
    if answer.probabilities is not None:
        if not isinstance(answer.probabilities, dict) or not set(answer.probabilities) <= allowed \
                or not all(_probability(p) for p in answer.probabilities.values()):
            raise ValueError(f"{where}: probabilities must map known options or levels to numbers from 0 to 1")


def checked_answers(questions: dict[str, DecisionQuestion], answers: dict) -> dict[str, DecisionAnswer]:
    """The answers to these questions, each checked against its question; ValueError if one is missing or unfit."""
    checked = {}
    for question_id, question in questions.items():
        answer = answers.get(question_id)
        if not isinstance(answer, DecisionAnswer):
            raise ValueError(f"question {question_id!r}: no answer")
        _check_answer(question, answer, f"question {question_id!r}")
        checked[question_id] = answer
    return checked


def merged_answers(questions: dict[str, DecisionQuestion],
                   answers: dict[str, DecisionAnswer]) -> dict[str, DecisionAnswer]:
    """Fold each reversed twin into its question: the lower confidence counts, disagreement means confidence 0."""
    merged = {}
    for question_id in questions:
        answer, twin = answers[question_id], answers.get(question_id + REVERSED)
        if twin is not None:
            confidence = min(answer.confidence, twin.confidence) if twin.value == answer.value else 0.0
            answer = DecisionAnswer(answer.type, answer.value, confidence, answer.probabilities)
        merged[question_id] = answer
    return merged

"""
`public()` and `correct_responses()` (docs/public-form.md): the cases of
`examples/public.yaml`, whose header describes the format, and a property
over the valid corpus.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml

from mdq import errors, load
from mdq.models import BaseQuestion, EssayQuestion, FillInQuestion
from _corpus import EXAMPLES_ROOT, VALID_EXAMS_DIR, VALID_PARSED

CASES: list[dict[str, Any]] = yaml.safe_load(
    (EXAMPLES_ROOT / "public.yaml").read_text(encoding="utf-8")
)["cases"]


def _question(data: object) -> BaseQuestion[Any]:
    loaded = load(data)
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    assert isinstance(loaded.document, BaseQuestion)
    return loaded.document


def _json(value: object) -> object:
    """`value` after a JSON round trip: it must hold only plain JSON values."""
    return json.loads(json.dumps(value))


def test_there_are_public_cases() -> None:
    assert CASES


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_public_form_case(case: dict[str, Any]) -> None:
    question = _question(case["question"])
    if "error" in case:
        error = getattr(errors, case["error"])
        with pytest.raises(error):
            question.public()
        return
    assert _json(question.public()) == case["public"]
    assert _json(question.correct_responses()) == case["correctResponses"]


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if "error" not in case and case["question"]["type"] != "essay"],
    ids=lambda case: case["name"],
)
def test_case_correct_responses_score_one(case: dict[str, Any]) -> None:
    question = _question(case["question"])
    for response in _full_responses(question):
        assert question.score_response(response).score == 1


#: Keys that are private at any depth of a public form.
PRIVATE_KEYS = frozenset(
    {
        "comment", "feedback", "incorrectFeedback", "score", "correct", "marker",
        "answer", "tolerance", "accept", "reject", "answerKey", "extra", "lines",
        "meta", "author",
    }
)  # fmt: skip

#: Lint codes of a question whose correct responses may not score 1: an
#: earlier pattern or section shadows them, or the answer is outside its
#: domain.
SHADOWING_CODES = frozenset(
    {
        "accept-reject-overlap",
        "duplicate-alternative-lines",
        "answer-outside-domain",
    }
)


def _valid_questions() -> list[tuple[str, BaseQuestion[Any]]]:
    questions = []
    for path in VALID_PARSED:
        if path.is_relative_to(VALID_EXAMS_DIR):
            continue
        document = load(path).document
        if isinstance(document, BaseQuestion):
            name = path.relative_to(EXAMPLES_ROOT).as_posix()
            questions.append((name, document.with_ids()))
    return questions


VALID_QUESTIONS = _valid_questions()


#: Lists whose entries keep their `feedback`: the pre-validation patterns
#: show it to the student before the submission.
PATTERN_LISTS = frozenset({"preAccept", "preReject"})


def _keys(value: object) -> set[str]:
    """
    Every mapping key of `value`, at any depth, but the `feedback` of a
    pre-validation pattern.
    """
    if isinstance(value, dict):
        keys = set(value)
        for key, item in value.items():
            if key in PATTERN_LISTS:
                keys |= set().union(*(set(e) - {"feedback"} for e in item if isinstance(e, dict)))
            else:
                keys |= _keys(item)
        return keys
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value))
    return set()


def _full_responses(question: BaseQuestion[Any]) -> list[object]:
    """
    The correct responses as full responses. Fill-in: one response, with
    the first correct response of each blank; none if a blank has none.
    """
    responses = question.correct_responses()
    if isinstance(question, FillInQuestion):
        assert isinstance(responses, dict)
        if not all(responses.values()):
            return []
        return [{blank: values[0] for blank, values in responses.items()}]
    assert isinstance(responses, list)
    return responses


@pytest.mark.parametrize(
    "question", [q for _, q in VALID_QUESTIONS], ids=[n for n, _ in VALID_QUESTIONS]
)
def test_valid_corpus_public_form_has_no_private_key(question: BaseQuestion[Any]) -> None:
    public = question.public()
    assert _json(public) == public
    assert not _keys(public) & PRIVATE_KEYS


SCORED_QUESTIONS = [
    (name, question)
    for name, question in VALID_QUESTIONS
    if not isinstance(question, EssayQuestion)
    and not {d.code for d in question.lint()} & SHADOWING_CODES
]


@pytest.mark.parametrize(
    "question", [q for _, q in SCORED_QUESTIONS], ids=[n for n, _ in SCORED_QUESTIONS]
)
def test_valid_corpus_correct_responses_score_one(question: BaseQuestion[Any]) -> None:
    for response in _full_responses(question):
        assert question.score_response(response).score == 1

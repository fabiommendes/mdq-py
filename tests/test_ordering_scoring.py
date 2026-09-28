"""
`OrderingQuestion.score_response`, plus `grades_indentation`,
`comparison_key` and the module-level `coerce_ordering_lines`.

Reuses the local hypothesis strategies from `tests/test_ordering_models.py`
rather than redefining them.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest
import yaml
from hypothesis import assume, given
from hypothesis import strategies as st

from mdq import types as t
from mdq.errors import NotAutoGradable, ResponseError
from mdq.models import (
    OrderingLine,
    OrderingQuestion,
    QuestionRoot,
    QuestionScore,
    coerce_ordering_lines,
)
from _corpus import relative_id
from test_ordering_models import MINIMAL, ORDERING_FIXTURES, ordering_questions


def as_response(lines: Iterable[OrderingLine]) -> list[t.OrderingLineDict]:
    """Turn model-side `[level, text]` tuples into a JSON-shaped response."""
    return [[level, text] for level, text in lines]


def load_fixture(name: str) -> OrderingQuestion:
    path = next(p for p in ORDERING_FIXTURES if p.name == name)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    question = QuestionRoot.model_validate(document).root
    assert isinstance(question, OrderingQuestion)
    return question


#
# Properties
#
@given(ordering_questions())
def test_the_answer_key_always_scores_one(question: OrderingQuestion) -> None:
    result = question.score_response(as_response(question.lines))
    assert result == QuestionScore(score=1.0)


@given(ordering_questions(), st.integers(min_value=0))
def test_skip_blanks_ignores_an_inserted_blank_line(
    question: OrderingQuestion, position: int
) -> None:
    question = question.model_copy(update={"normalizations": ["skip-blanks"]})
    index = position % (len(question.lines) + 1)
    response = (
        as_response(question.lines[:index])
        + [[0, ""]]
        + as_response(question.lines[index:])
    )
    result = question.score_response(response)
    assert result.score == 1.0


@given(ordering_questions(), st.integers(min_value=0, max_value=9))
def test_ungraded_levels_can_be_remapped_freely(
    question: OrderingQuestion, shift: int
) -> None:
    assume(not question.grades_indentation())
    response: t.OrderingResponse = [
        [level + shift, text] for level, text in question.lines
    ]
    result = question.score_response(response)
    assert result.score == 1.0


@given(
    ordering_questions(),
    st.lists(
        st.tuples(st.integers(min_value=0, max_value=3), st.text(max_size=3)),
        max_size=5,
    ),
)
def test_score_is_always_binary(
    question: OrderingQuestion, response: list[tuple[int, str]]
) -> None:
    question = question.model_copy(update={"unmatched": "incorrect"})
    result = question.score_response(as_response(response))
    assert result.score in (0.0, 1.0)


#
# Fixtures
#
@pytest.mark.parametrize(
    "path", ORDERING_FIXTURES, ids=[relative_id(p) for p in ORDERING_FIXTURES]
)
def test_the_answer_key_scores_one_with_no_feedback_for_every_fixture(
    path: Path,
) -> None:
    question = load_fixture(path.name)
    result = question.score_response(as_response(question.lines))
    assert result == QuestionScore(score=1.0)


def test_an_accepted_alternative_scores_one_with_its_feedback() -> None:
    question = load_fixture("accept-alternative.yaml")
    alternative = question.accept[0]
    result = question.score_response(as_response(alternative.lines))
    assert result.score == 1.0
    assert result.feedback == [alternative.feedback]


@pytest.mark.parametrize("name", ["reject-feedback.yaml", "full-metadata.yaml"])
def test_a_rejected_alternative_scores_zero_with_its_feedback_but_not_its_comment(
    name: str,
) -> None:
    question = load_fixture(name)
    alternative = question.reject[0]
    result = question.score_response(as_response(alternative.lines))
    assert result.score == 0.0
    assert result.feedback == [alternative.feedback]
    assert alternative.comment not in result.feedback


def test_unmatched_incorrect_scores_zero_with_no_feedback() -> None:
    question = load_fixture("unmatched-incorrect.yaml")
    response = as_response(reversed(question.lines))
    result = question.score_response(response)
    assert result == QuestionScore(score=0.0)


def test_unmatched_manual_raises_not_auto_gradable() -> None:
    question = load_fixture("fibonacci.yaml")
    assert question.unmatched == "manual"
    response = as_response(reversed(question.lines))
    with pytest.raises(NotAutoGradable):
        question.score_response(response)


def test_skip_blanks_still_scores_one_with_the_blank_line_removed() -> None:
    question = load_fixture("skip-blanks.yaml")
    response = [line for line in as_response(question.lines) if line[1] != ""]
    result = question.score_response(response)
    assert result.score == 1.0


def test_skip_blanks_still_scores_one_with_extra_blank_lines_inserted() -> None:
    question = load_fixture("skip-blanks.yaml")
    base = as_response(question.lines)
    response: t.OrderingResponse = [[0, ""], *base[:2], [0, ""], *base[2:], [0, ""]]
    result = question.score_response(response)
    assert result.score == 1.0


def test_lenient_indentation_still_scores_one_when_reindented() -> None:
    question = load_fixture("lenient-indentation.yaml")
    response: t.OrderingResponse = [[level + 3, text] for level, text in question.lines]
    result = question.score_response(response)
    assert result.score == 1.0


def test_strict_indentation_a_changed_level_is_a_non_match() -> None:
    question = load_fixture("strict-indentation.yaml")
    question = question.model_copy(update={"unmatched": "incorrect"})
    level, text = question.lines[0]
    response: t.OrderingResponse = [[level + 1, text], *as_response(question.lines[1:])]
    result = question.score_response(response)
    assert result.score == 0.0


def test_json_shaped_and_tuple_shaped_responses_score_the_same() -> None:
    question = load_fixture("fibonacci.yaml")
    as_lists = as_response(question.lines)
    # `score_response` is typed for the JSON-shaped list form, but must accept
    # the model's own tuple form too -- `coerce_ordering_lines` only cares
    # that each entry unpacks into an (int, str) pair.
    as_tuples = list(question.lines)
    assert question.score_response(as_lists) == question.score_response(as_tuples)


#
# Edge cases
#
def test_empty_response_is_unmatched() -> None:
    assert MINIMAL.unmatched == "manual"
    with pytest.raises(NotAutoGradable):
        MINIMAL.score_response([])


def test_a_duplicated_line_is_a_non_match() -> None:
    question = MINIMAL.model_copy(update={"unmatched": "incorrect"})
    response = as_response(question.lines) + [as_response(question.lines)[-1]]
    result = question.score_response(response)
    assert result.score == 0.0


def test_a_response_holding_an_extra_distractor_is_a_non_match() -> None:
    question = load_fixture("extra-distractors.yaml")
    question = question.model_copy(update={"unmatched": "incorrect"})
    response = as_response(question.lines) + as_response(question.extra[:1])
    result = question.score_response(response)
    assert result.score == 0.0


@pytest.mark.parametrize(
    "entry",
    [
        [0, "a", "extra"],
        ["not-an-int", "a"],
        [0, 123],
    ],
    ids=["three-element", "non-int-level", "non-str-text"],
)
def test_coerce_ordering_lines_rejects_malformed_entries(entry: list[object]) -> None:
    with pytest.raises(ResponseError):
        coerce_ordering_lines([entry])  # type: ignore[list-item]


def test_score_response_rejects_a_malformed_response() -> None:
    with pytest.raises(ResponseError):
        MINIMAL.score_response([[0, "a", "extra"]])  # type: ignore[list-item]


def test_manual_vs_incorrect_on_the_same_unmatched_response() -> None:
    manual = MINIMAL
    incorrect = MINIMAL.model_copy(update={"unmatched": "incorrect"})
    response = as_response(reversed(MINIMAL.lines))

    with pytest.raises(NotAutoGradable):
        manual.score_response(response)

    assert incorrect.score_response(response) == QuestionScore(score=0.0)

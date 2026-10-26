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
from mdq.errors import ResponseError
from mdq.models import (
    OrderingLine,
    OrderingQuestion,
    QuestionRoot,
    QuestionScore,
)
from mdq.models._ordering import coerce_ordering_lines
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
    # Under "fixed" the student cannot change levels (ResponseError).
    assume(question.indentation != "fixed")
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
    try:
        result = question.score_response(as_response(response))
    except ResponseError:
        return  # a line outside the pool is malformed, not scored
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


#
# ordering.md, "Indentation": `fixed` compares levels; only `dedent` flattens.
#
def _mean_question(**fields: object) -> OrderingQuestion:
    return OrderingQuestion(
        stem="Ordene.",
        content="code",
        lines=[
            (0, "total = 0"),
            (0, "for x in values:"),
            (1, "total += x"),
            (0, "mean = total / len(values)"),
        ],
        extra=[(1, "mean = total / len(values)")],
        **fields,
    )


def test_fixed_grades_indentation_levels() -> None:
    assert _mean_question().grades_indentation()
    assert _mean_question(indentation="strict").grades_indentation()
    assert not _mean_question(indentation="lenient").grades_indentation()
    assert not _mean_question(normalizations=["dedent"]).grades_indentation()


#
# Outline levels of a text response (ordering.md, "Response")
#
def make_text_question(**update: object) -> OrderingQuestion:
    base = {
        "type": "ordering",
        "content": "text",
        "stem": "Order me",
        "lines": [[0, "a"], [1, "b"], [2, "c"], [0, "d"]],
        "extra": [[2, "e"]],
        "unmatched": "incorrect",
    }
    return OrderingQuestion.model_validate({**base, **update})


@pytest.mark.parametrize("indentation", ["lenient", "strict"])
def test_a_text_response_starting_below_level_zero_is_malformed(
    indentation: str,
) -> None:
    question = make_text_question(indentation=indentation)
    with pytest.raises(ResponseError, match="first line"):
        question.score_response([[2, "c"], [0, "d"]])


@pytest.mark.parametrize("indentation", ["lenient", "strict"])
def test_a_text_response_with_a_level_jump_is_malformed(indentation: str) -> None:
    question = make_text_question(indentation=indentation)
    with pytest.raises(ResponseError, match="level 2"):
        question.score_response([[0, "a"], [2, "c"]])

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


def test_a_duplicated_line_beyond_the_pool_is_malformed() -> None:
    question = MINIMAL.model_copy(update={"unmatched": "incorrect"})
    response = as_response(question.lines) + [as_response(question.lines)[-1]]
    with pytest.raises(ResponseError):
        question.score_response(response)


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


def test_fixed_distractor_differing_only_by_level_is_a_non_match() -> None:
    question = _mean_question(unmatched="incorrect")
    key = [[level, text] for level, text in question.lines]
    assert question.score_response(key).score == 1.0
    with_distractor = key[:3] + [[1, "mean = total / len(values)"]]
    assert question.score_response(with_distractor).score == 0.0


def test_explicit_dedent_under_fixed_flattens_levels() -> None:
    question = _mean_question(unmatched="incorrect", normalizations=["dedent"])
    with_distractor = [
        [0, "total = 0"],
        [0, "for x in values:"],
        [1, "total += x"],
        [1, "mean = total / len(values)"],
    ]
    assert question.score_response(with_distractor).score == 1.0


def test_corpus_extra_distractors_rejects_the_level_only_distractor() -> None:
    from pathlib import Path as _Path

    import mdq as _mdq

    path = (
        _Path(__file__).resolve().parents[2]
        / "examples/valid/ordering/extra-distractors.mdq.md"
    )
    question = _mdq.load(path).document
    key = [[level, text] for level, text in question.lines]
    assert question.score_response(key).score == 1.0
    swapped = key[:-1] + [[1, key[-1][1]]]
    with pytest.raises(NotAutoGradable):
        question.score_response(swapped)


#
# Response validation against the presented pool (ordering.md, "Response")
#
def make_question(**update: object) -> OrderingQuestion:
    base = {
        "type": "ordering",
        # Code content: levels are free, a `text` response must be an outline.
        "content": "code",
        "stem": "Order me",
        "lines": [[0, "a"], [1, "b"], [1, "b"], [0, "c"]],
        "extra": [[0, "d"], [2, "c"]],
        "unmatched": "incorrect",
    }
    return OrderingQuestion.model_validate({**base, **update})


def test_a_response_with_a_foreign_line_is_malformed() -> None:
    with pytest.raises(ResponseError):
        make_question().score_response([[0, "a"], [0, "zzz"]])


def test_a_response_with_too_many_copies_is_malformed() -> None:
    with pytest.raises(ResponseError):
        make_question().score_response([[0, "a"], [0, "a"]])


def test_a_response_may_use_the_copies_the_pool_offers() -> None:
    result = make_question().score_response([[1, "b"], [1, "b"], [0, "d"]])
    assert result.score == 0.0


def test_a_response_leaving_lines_out_is_graded_normally() -> None:
    result = make_question().score_response([[0, "a"]])
    assert result.score == 0.0


def test_fixed_rejects_a_changed_level() -> None:
    with pytest.raises(ResponseError):
        make_question().score_response([[1, "a"]])


def test_fixed_pool_includes_the_extra_lines_at_their_own_level() -> None:
    question = make_question()
    assert question.score_response([[2, "c"]]).score == 0.0
    with pytest.raises(ResponseError):
        question.score_response([[1, "c"]])


@pytest.mark.parametrize("indentation", ["lenient", "strict"])
def test_lenient_and_strict_compare_the_pool_by_text(indentation: str) -> None:
    question = make_question(indentation=indentation)
    # level 5 was never authored, but the student may change levels
    assert question.score_response([[5, "a"], [3, "c"]]).score == 0.0
    with pytest.raises(ResponseError):
        question.score_response([[0, "c"], [0, "c"], [0, "c"]])
    with pytest.raises(ResponseError):
        question.score_response([[0, "zzz"]])


def test_skip_blanks_leaves_blank_lines_out_of_the_pool_check() -> None:
    question = make_question(normalizations=["skip-blanks"])
    assert question.score_response([[0, ""], [0, "a"]]).score == 0.0


def test_the_first_matching_answer_wins_in_document_order() -> None:
    lines = [[0, "a"], [0, "b"]]
    alternative = {"lines": [[0, "b"], [0, "a"]]}
    question = OrderingQuestion.model_validate(
        {
            "type": "ordering",
            "content": "text",
            "stem": "Order me",
            "lines": lines,
            "accept": [
                {**alternative, "feedback": "first"},
                {**alternative, "feedback": "second"},
            ],
        }
    )
    result = question.score_response([[0, "b"], [0, "a"]])
    assert result == QuestionScore(score=1.0, feedback=["first"])
    # the answer key comes before every section
    repeated = question.model_copy(
        update={"accept": [{"lines": lines, "feedback": "late"}]}
    )
    assert repeated.score_response(lines) == QuestionScore(score=1.0)


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


def test_a_text_response_that_is_an_outline_is_graded() -> None:
    question = make_text_question()
    assert (
        question.score_response([[0, "a"], [1, "b"], [2, "c"], [0, "d"]]).score == 1.0
    )


def test_a_text_response_starting_below_level_zero_is_malformed() -> None:
    with pytest.raises(ResponseError, match="first line"):
        make_text_question().score_response([[2, "c"], [0, "d"]])


def test_a_text_response_with_a_level_jump_is_malformed() -> None:
    with pytest.raises(ResponseError, match="level 2"):
        make_text_question().score_response([[0, "a"], [2, "c"]])


def test_an_extra_line_alone_at_its_level_is_malformed_in_a_text_response() -> None:
    with pytest.raises(ResponseError):
        make_text_question().score_response([[2, "e"]])


def test_a_code_response_may_jump_levels() -> None:
    question = make_text_question(content="code")
    assert question.score_response([[0, "a"], [2, "c"]]).score == 0.0

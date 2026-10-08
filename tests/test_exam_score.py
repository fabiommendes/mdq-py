"""
exam.md, "Exam score", and responses.md, "Responses to an exam": the
weighted mean of the question scores after `penalty`, with skipped and
pending questions, as an `ExamScore`.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

import mdq
from mdq import errors, models
from mdq.models import ExamScore, QuestionScore


def _mc(qid: str, weight: float = 1.0) -> dict[str, Any]:
    return {
        "id": qid,
        "type": "multiple-choice",
        "stem": f"Pergunta {qid}",
        "weight": weight,
        "choices": [
            {"id": "a", "text": "certa", "score": 1},
            {"id": "b", "text": "errada", "score": -0.5},
            {"id": "c", "text": "neutra", "score": 0},
        ],
    }


def _exam(*questions: dict[str, Any], **fields: Any) -> models.Exam:
    return mdq.load(
        {"type": "exam", "title": "Prova", "questions": list(questions), **fields},
        kind="exam",
    ).document


ESSAY = {"id": "e", "type": "essay", "stem": "Disserte.", "weight": 1}


def test_all_correct_scores_one() -> None:
    result = _exam(_mc("q1"), _mc("q2")).score_responses({"q1": "a", "q2": "a"})
    assert isinstance(result, ExamScore)
    assert result.score == 1.0
    assert result.provisional == 1.0
    assert result.pending == () and result.skipped == ()
    assert result.total_weight == 2.0
    assert result.penalty == "none"


def test_weighted_mean() -> None:
    result = _exam(_mc("q1", 3), _mc("q2", 1)).score_responses({"q1": "a", "q2": "c"})
    assert result.score == pytest.approx(0.75)
    assert result.total_weight == 4.0


def test_question_scores_are_reported_by_id() -> None:
    result = _exam(_mc("q1"), _mc("q2")).score_responses({"q1": "a", "q2": "b"})
    assert result.questions["q1"] == QuestionScore(score=1.0)
    assert result.questions["q2"] == QuestionScore(score=-0.5)


@pytest.mark.parametrize(
    ("penalty", "expected"),
    [("none", 0.5), ("capped", 0.25), ("full", 0.25)],
)
def test_penalty_per_question(penalty: str, expected: float) -> None:
    exam = _exam(_mc("q1"), _mc("q2"), penalty=penalty)
    result = exam.score_responses({"q1": "a", "q2": "b"})
    assert result.score == pytest.approx(expected)
    assert result.penalty == penalty


@pytest.mark.parametrize(
    ("penalty", "expected"), [("none", 0.0), ("capped", 0.0), ("full", -0.5)]
)
def test_penalty_floors_the_total(penalty: str, expected: float) -> None:
    exam = _exam(_mc("q1"), penalty=penalty)
    assert exam.score_responses({"q1": "b"}).score == pytest.approx(expected)


def test_skipped_questions_score_zero_and_keep_their_weight() -> None:
    exam = _exam(_mc("q1"), _mc("q2"), _mc("q3"))
    result = exam.score_responses({"q1": "a", "q2": None})
    assert result.score == pytest.approx(1 / 3)
    assert result.skipped == ("q2", "q3")
    assert result.questions["q2"] == QuestionScore(score=0.0)
    assert result.questions["q3"] == QuestionScore(score=0.0)


def test_zero_total_weight_scores_zero() -> None:
    result = _exam(_mc("q1", 0), _mc("q2", 0)).score_responses({"q1": "a", "q2": "a"})
    assert result.score == 0.0
    assert result.total_weight == 0.0


def test_empty_exam_scores_zero() -> None:
    result = _exam().score_responses({})
    assert result.score == 0.0 and result.questions == {}


def test_pending_response_leaves_the_exam_pending() -> None:
    exam = _exam(_mc("q1"), ESSAY, _mc("q2"))
    result = exam.score_responses({"q1": "a", "e": "Um texto.", "q2": "c"})
    assert result.score is None
    assert result.pending == ("e",)
    assert result.questions["e"] is None
    assert result.provisional == pytest.approx(0.5)
    assert result.total_weight == 3.0


def test_skipped_essay_is_skipped_not_pending() -> None:
    result = _exam(_mc("q1"), ESSAY).score_responses({"q1": "a"})
    assert result.score == pytest.approx(0.5)
    assert result.pending == () and result.skipped == ("e",)


def test_only_pending_questions_give_provisional_zero() -> None:
    result = _exam(ESSAY).score_responses({"e": "Um texto."})
    assert result.score is None and result.provisional == 0.0


def test_result_is_frozen() -> None:
    result = _exam(_mc("q1")).score_responses({"q1": "a"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.score = 0.0  # type: ignore[misc]


def test_unknown_key_is_a_response_error() -> None:
    with pytest.raises(errors.ResponseError):
        _exam(_mc("q1")).score_responses({"q1": "a", "zz": "a"})


def test_bad_response_is_a_response_error() -> None:
    with pytest.raises(errors.ResponseError):
        _exam(_mc("q1")).score_responses({"q1": "zz"})


def test_unresolved_include_is_an_error() -> None:
    exam = _exam(_mc("q1"), {"include": "other"})
    with pytest.raises(errors.UnresolvedInclude):
        exam.score_responses({"q1": "a"})


def test_question_without_id_is_an_error() -> None:
    question = {k: v for k, v in _mc("q1").items() if k != "id"}
    with pytest.raises(errors.MissingIdError):
        _exam(question).score_responses({})

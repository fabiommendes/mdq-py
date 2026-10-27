"""
exam.md, "Exam score", and responses.md, "Responses to an exam": the
`ExamScore` result and the errors of `Exam.score_responses`. The weighted
mean, the penalty, and the skipped and pending questions are in
`examples/grading/exam.yaml`.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

import mdq
from mdq import errors, models
from mdq.models import ExamScore


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


def test_result_is_an_exam_score() -> None:
    result = _exam(_mc("q1")).score_responses({"q1": "a"})
    assert isinstance(result, ExamScore)


def test_result_is_frozen() -> None:
    result = _exam(_mc("q1")).score_responses({"q1": "a"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.score = 0.0  # type: ignore[misc]


def test_unresolved_include_is_an_error() -> None:
    exam = _exam(_mc("q1"), {"include": "other"})
    with pytest.raises(errors.UnresolvedInclude):
        exam.score_responses({"q1": "a"})


def test_question_without_id_is_an_error() -> None:
    question = {k: v for k, v in _mc("q1").items() if k != "id"}
    with pytest.raises(errors.MissingIdError):
        _exam(question).score_responses({})

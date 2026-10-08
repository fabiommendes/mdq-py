"""
`QuestionScore`, what one response to one question was worth -- the
return type of every `score_response()`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import Field

from ..types import PenaltyPolicy
from ._base import MdqModel

__all__ = ["ExamScore", "QuestionScore"]


class QuestionScore(MdqModel):
    """
    What one response to one question was worth.

    `score` is the raw value, in [-1, 1], with no exam policy applied.
    """

    score: float = Field(ge=-1, le=1)

    #: Feedback triggered by this response, in the order the choices
    #: appear in the document. What triggers it depends on the question
    #: type: the picked choice in multiple-choice, wrongly judged
    #: choices in multiple-selection, wrongly judged or unjudged
    #: statements in true-false. A skipped question triggers none.
    feedback: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ExamScore:
    """
    What one attempt at an exam was worth (exam.md, "Exam score").

    `score` is the weighted mean of the question scores after `penalty`,
    or None while a response is pending. `provisional` is the same mean
    over the settled questions only, so it equals `score` when nothing is
    pending. `questions` maps every question id of the exam to its
    `QuestionScore`, or to None when its response is pending; a skipped
    question (no response, or `null`) scores 0 with no feedback.
    """

    score: float | None
    provisional: float
    questions: Mapping[str, QuestionScore | None]
    pending: tuple[str, ...]
    skipped: tuple[str, ...]
    total_weight: float
    penalty: PenaltyPolicy

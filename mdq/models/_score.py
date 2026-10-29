"""
`QuestionScore`, what one response to one question was worth -- the
return type of every `score_response()` -- and `BlankScore`, what one
blank of a fill-in response was worth.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import Field

from ..types import PenaltyPolicy
from ._base import MdqModel

__all__ = ["BlankScore", "ExamScore", "QuestionScore"]


class BlankScore(MdqModel):
    """
    What the response to one blank of a fill-in question was worth
    (fill-in.md, "Blank scores").

    `score` is the one the question's strategy gives the blank, before
    the strategy combines the blanks. `feedback` is the feedback of this
    blank only.
    """

    score: float = Field(ge=-1, le=1)
    feedback: list[str] = Field(default_factory=list)


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

    #: The score of each blank of a fill-in question, keyed by blank id,
    #: with that blank's own feedback (fill-in.md, "Blank scores"). The
    #: blank score is the one the question's strategy gives it, before the
    #: strategy combines the blanks: an empty blank scores 0 with no
    #: feedback. `None` marks a pending blank. Only fill-in sets this
    #: field; it is `None` for every other question type.
    blanks: dict[str, BlankScore | None] | None = None


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

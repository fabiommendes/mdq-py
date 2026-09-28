"""
`QuestionScore`, what one response to one question was worth -- the
return type of every `score_response()`.
"""

from __future__ import annotations

from pydantic import Field

from ._base import MdqModel

__all__ = ["QuestionScore"]


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

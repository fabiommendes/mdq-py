"""numeric.md, "Feedback": the `incorrectFeedback` of a numeric question."""

from __future__ import annotations

from mdq import models

FEEDBACK = "Not quite. The Pico da Neblina is in the Serra do Imeri."


def test_the_feedback_is_written_back_to_the_frontmatter() -> None:
    question = models.NumericQuestion(
        stem="Altitude of the Pico da Neblina?",
        answer=2995,
        tolerance=models.Tolerance(absolute=5),
        incorrect_feedback=FEEDBACK,
    )
    assert question.frontmatter()["incorrectFeedback"] == FEEDBACK
    question = models.NumericQuestion(
        stem="Altitude of the Pico da Neblina?",
        answer=2995,
        tolerance=models.Tolerance(absolute=5),
    )
    assert "incorrectFeedback" not in question.frontmatter()

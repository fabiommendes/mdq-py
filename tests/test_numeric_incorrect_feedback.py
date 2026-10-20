"""numeric.md, "Feedback": the `incorrectFeedback` of a numeric question."""

from __future__ import annotations

import pytest

import mdq
from mdq import models
from mdq.errors import ResponseError

FEEDBACK = "Not quite. The Pico da Neblina is in the Serra do Imeri."


def _question(**fields: object) -> models.NumericQuestion:
    return models.NumericQuestion(
        stem="Altitude of the Pico da Neblina?",
        answer=2995,
        tolerance=models.Tolerance(absolute=5),
        **fields,  # type: ignore[arg-type]
    )


def test_an_incorrect_response_shows_the_feedback() -> None:
    assert _question(incorrect_feedback=FEEDBACK).score_response(3001).feedback == [FEEDBACK]


def test_a_correct_response_shows_no_feedback() -> None:
    question = _question(incorrect_feedback=FEEDBACK)
    assert question.score_response(2995).feedback == []
    assert question.score_response(3000).feedback == []


def test_a_malformed_response_is_rejected_without_feedback() -> None:
    question = _question(incorrect_feedback=FEEDBACK)
    with pytest.raises(ResponseError):
        question.score_response("abc")
    with pytest.raises(ResponseError):
        question.score_response(2999.5)  # not whole, and the domain is integer


def test_no_declared_feedback_shows_none() -> None:
    assert _question().score_response(3001).feedback == []


def test_the_frontmatter_key_is_a_field_of_the_question() -> None:
    source = (
        f"---\nincorrectFeedback: {FEEDBACK}\n---\n\n"
        "Altitude of the Pico da Neblina?\n\n[numeric]: 2995 +- 5\n"
    )
    loaded = mdq.load(source, format="mdq")
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    assert loaded.document.incorrect_feedback == FEEDBACK
    assert loaded.document.score_response(3001).feedback == [FEEDBACK]


def test_the_feedback_is_written_back_to_the_frontmatter() -> None:
    assert _question(incorrect_feedback=FEEDBACK).frontmatter()["incorrectFeedback"] == FEEDBACK
    assert "incorrectFeedback" not in _question().frontmatter()


@pytest.mark.parametrize("text", ["", "   "])
def test_a_blank_feedback_is_a_blank_text_error(text: str) -> None:
    doc = {
        "type": "numeric",
        "stem": "Altitude of the Pico da Neblina?",
        "answer": 2995,
        "incorrectFeedback": text,
    }
    codes = [(d.code, d.severity, d.path) for d in mdq.load(doc).diagnostics]
    assert ("blank-text", "error", ("incorrectFeedback",)) in codes

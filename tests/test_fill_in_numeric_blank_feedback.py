"""fill-in.md, "Feedback": the `incorrectFeedback` of a numeric blank."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import mdq
from mdq import models

FEEDBACK = "The Pico da Neblina is in the Serra do Imeri."
STEM = "The Pico da Neblina is [^neblina] meters high, and the Bandeira [^bandeira]."


def _load(front: str):
    source = (
        f"---\n{front}\n---\n\n{STEM}\n\n"
        "[^neblina/numeric(m)]: 2995 +- 5\n\n"
        "[^bandeira/numeric(m)]: 2892 +- 5\n"
    )
    return mdq.load(source, format="mdq")


def _errors(loaded) -> list[tuple[str, tuple]]:
    return [(d.code, d.path) for d in loaded.diagnostics if d.severity == "error"]


def test_the_map_sets_the_field_of_the_numeric_blank() -> None:
    loaded = _load(f"incorrectFeedback:\n  neblina: {FEEDBACK}")
    assert _errors(loaded) == []
    neblina, bandeira = loaded.document.blanks
    assert neblina.incorrect_feedback == FEEDBACK
    assert bandeira.incorrect_feedback is None


def test_an_incorrect_response_shows_the_feedback_of_its_blank() -> None:
    question = _load(f"incorrectFeedback:\n  neblina: {FEEDBACK}").document
    score = question.score_response({"neblina": 3100, "bandeira": 2892})
    assert score.feedback == [FEEDBACK]


def test_a_correct_response_shows_no_feedback() -> None:
    question = _load(f"incorrectFeedback:\n  neblina: {FEEDBACK}").document
    assert question.score_response({"neblina": 2995, "bandeira": 2892}).feedback == []


def test_a_skipped_blank_shows_no_feedback() -> None:
    question = _load(f"incorrectFeedback:\n  neblina: {FEEDBACK}").document
    assert question.score_response({"bandeira": 2892}).feedback == []


def test_a_malformed_response_is_rejected() -> None:
    question = _load(f"incorrectFeedback:\n  neblina: {FEEDBACK}").document
    with pytest.raises(mdq.errors.ResponseError):
        question.score_response({"neblina": "abc", "bandeira": 2892})


def test_the_feedback_of_every_blank_is_collected_in_blank_order() -> None:
    question = _load("incorrectFeedback:\n  bandeira: Too low.\n  neblina: Too high.").document
    score = question.score_response({"neblina": 1, "bandeira": 1})
    assert score.feedback == ["Too high.", "Too low."]


def test_an_unknown_key_is_undefined() -> None:
    loaded = _load("incorrectFeedback:\n  altura: x")
    assert _errors(loaded) == [("undefined-blank", ("incorrectFeedback", "altura"))]


def test_the_field_is_written_back_to_the_frontmatter() -> None:
    question = _load(f"incorrectFeedback:\n  neblina: {FEEDBACK}").document
    assert question.frontmatter()["incorrectFeedback"] == {"neblina": FEEDBACK}


def test_a_blank_text_is_an_error_of_the_blank() -> None:
    with pytest.raises(ValidationError, match="blank-text"):
        models.NumericBlank(id="a", answer=1, incorrect_feedback="  ")


def test_a_choice_blank_still_rejects_the_map_entry() -> None:
    source = (
        "---\nincorrectFeedback:\n  city: x\n---\n\nThe city is [^city].\n\n"
        "[^city]:\n* [*] Santos\n* [ ] Manaus\n"
    )
    loaded = mdq.load(source, format="mdq")
    assert [d.code for d in loaded.diagnostics if d.severity == "error"] == ["schema-error"]

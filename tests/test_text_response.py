"""
The response to a short answer or essay question is a string (docs/responses.md,
"Short answer and essay"). Any other value is a `ResponseError`; an empty
string, or one of only spaces, is graded like any other response.
"""

from __future__ import annotations

from typing import Any

import pytest

from mdq import models
from mdq.errors import NotAutoGradable, ResponseError

NOT_TEXT: list[Any] = [1960, 1960.0, True, ["Brasília"], {"capital": "Brasília"}, None]


def short_answer(**fields: Any) -> models.ShortAnswerQuestion:
    return models.ShortAnswerQuestion(
        stem="Qual é a capital do Brasil?", accept=["Brasília"], **fields
    )


@pytest.mark.parametrize("response", NOT_TEXT)
def test_short_answer_rejects_a_response_that_is_not_a_string(response: Any) -> None:
    with pytest.raises(ResponseError):
        short_answer().score_response(response)


@pytest.mark.parametrize("response", NOT_TEXT[:-1])
def test_essay_rejects_a_response_that_is_not_a_string(response: Any) -> None:
    essay = models.EssayQuestion(stem="Explique a fotossíntese.")
    with pytest.raises(ResponseError):
        essay.score_response(response)


def test_essay_with_a_string_is_pending() -> None:
    essay = models.EssayQuestion(stem="Explique a fotossíntese.")
    with pytest.raises(NotAutoGradable):
        essay.score_response("")


@pytest.mark.parametrize("response", ["", "   ", "\n"])
def test_empty_response_is_graded(response: str) -> None:
    assert short_answer().score_response(response).score == 0.0


@pytest.mark.parametrize("response", ["", "   "])
def test_empty_response_is_pending_when_unmatched_is_manual(response: str) -> None:
    with pytest.raises(NotAutoGradable):
        short_answer(unmatched="manual").score_response(response)


def test_regex_can_accept_an_empty_response() -> None:
    question = models.ShortAnswerQuestion(stem="Diga algo.", accept=["/.*/"])
    assert question.score_response("").score == 1.0


def fill_in() -> models.FillInQuestion:
    return models.FillInQuestion(
        stem="A capital do Brasil é [^capital].",
        blanks=[models.ShortAnswerBlank(id="capital", accept=["Brasília"])],
    )


@pytest.mark.parametrize("response", NOT_TEXT[:-1])
def test_short_answer_blank_rejects_a_response_that_is_not_a_string(
    response: Any,
) -> None:
    with pytest.raises(ResponseError):
        fill_in().score_response({"capital": response})


@pytest.mark.parametrize("response", ["", "   "])
def test_short_answer_blank_grades_an_empty_response(response: str) -> None:
    assert fill_in().score_response({"capital": response}).score == 0.0


def test_short_answer_blank_null_is_a_skip() -> None:
    assert fill_in().score_response({"capital": None}).score == 0.0

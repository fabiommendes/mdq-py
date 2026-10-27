"""
numeric.md, "Body": the hints of rejected spellings, the speed of the limits
of an exponent and the places a tolerance gives to a model. The codes and the
scores of the limits are in `examples/invalid/` and
`examples/grading/numeric.yaml`.
"""

from __future__ import annotations

import time

import pytest

import mdq
from mdq import models
from mdq._parser import parse_question
from mdq.errors import ParseError, ResponseError


def _parse(body: str) -> dict:
    return parse_question(f"Stem.\n\n{body}\n")


@pytest.mark.parametrize(
    ("body", "hint"),
    [
        ("[numeric]: −5", 'use "-"'),
        ("[numeric]: 3.14 ± 0.1", 'use "+-"'),
        ("[numeric]: 3,14", 'use "." as the decimal separator'),
        ("[numeric]: 1 000", "remove the digit group separator"),
    ],
)
def test_rejected_spellings_suggest_the_right_one(body: str, hint: str) -> None:
    with pytest.raises(ParseError, match="malformed numeric body") as info:
        _parse(body)
    assert hint in str(info.value)


def test_model_places_use_the_tolerance_exponent() -> None:
    question = models.NumericQuestion(
        stem="x", answer="5.89e-7", tolerance=models.Tolerance(absolute=1e-09)
    )
    assert question.effective_decimal_places == 9
    question = models.NumericQuestion(
        stem="x", answer="5", tolerance=models.Tolerance(absolute=1.5e-07)
    )
    assert question.effective_decimal_places == 8


@pytest.mark.parametrize("body", ["1e999999999", "1e-999999999", "1e99999999999999999999"])
def test_huge_exponent_ends_fast_with_an_error(body: str) -> None:
    start = time.monotonic()
    with pytest.raises(ParseError):
        _parse(f"[numeric]: {body}")
    result = mdq.load(f"Stem.\n\n[numeric]: {body}\n", format="mdq")
    assert result.document is None
    assert time.monotonic() - start < 1


@pytest.mark.parametrize("answer", ["1e400", "-1e400", "1e-400", "1e1000", "1e999999999"])
def test_string_answer_out_of_range_ends_fast(answer: str) -> None:
    start = time.monotonic()
    result = mdq.load({"type": "numeric", "stem": "x", "answer": answer})
    assert result.document is None
    assert time.monotonic() - start < 1


@pytest.mark.parametrize(
    "response", ["1e400", "-1e400", "1e-400", "1e1000", "1e999999999", 10**400]
)
def test_response_out_of_range_ends_fast(response: str | int) -> None:
    question = models.NumericQuestion(stem="x", answer="1")
    start = time.monotonic()
    with pytest.raises(ResponseError):
        question.score_response(response)
    assert time.monotonic() - start < 1

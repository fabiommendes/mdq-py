"""numeric.md, "Body": the hints of rejected spellings, and the limits of an exponent."""

from __future__ import annotations

import time

import pytest

import mdq
from mdq import models
from mdq._parser import parse_question
from mdq.errors import ParseError, ResponseError
from mdq.models._numeric import numeric_value


def _parse(body: str) -> dict:
    return parse_question(f"Stem.\n\n{body}\n")


@pytest.mark.parametrize(
    ("body", "hint"),
    [
        ("[numeric]: −5", 'use "-"'),
        ("[numeric]: 5 +- −1", 'use "-"'),
        ("[numeric]: 3.14 ± 0.1", 'use "+-"'),
        ("[numeric]: 3,14", 'use "." as the decimal separator'),
        ("[numeric]: 1,000.5", 'use "." as the decimal separator'),
        ("[numeric]: 1 000", "remove the digit group separator"),
        ("[numeric]: 1 000", "remove the digit group separator"),
        ("[numeric]: 3.14 +- 0,1", 'use "." as the decimal separator'),
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


def test_a_markdown_exponent_round_trips_by_value() -> None:
    # The renderer writes plain notation, so the answer may come back as a
    # string, but it is the same exact value.
    source = "---\nid: q\n---\n\nStem.\n\n[numeric(kg)]: 5.972e24 +- 1%\n"
    loaded = mdq.load(source, format="mdq")
    again = mdq.load(loaded.document.render(), format="mdq")
    assert numeric_value(again.document.answer) == numeric_value(loaded.document.answer)
    assert again.document.tolerance == loaded.document.tolerance
    assert again.document.decimal_places == loaded.document.decimal_places


# numeric.md, "Answer representation": the value must fit a double.
_OUT_OF_RANGE = [
    "1e400",
    "-1e400",
    "1.8e308",
    "1e-400",
    "9.1e-400",
    "1" + "0" * 400,
    "1/" + "1" + "0" * 400,
    "1" + "0" * 400 + "/3",
]


@pytest.mark.parametrize("value", _OUT_OF_RANGE)
def test_body_value_out_of_range_is_a_parse_error(value: str) -> None:
    with pytest.raises(ParseError, match="range of a double"):
        _parse(f"[numeric]: {value}")


@pytest.mark.parametrize("tolerance", ["1e400", "1e-400", "1e400%"])
def test_body_tolerance_out_of_range_is_a_parse_error(tolerance: str) -> None:
    with pytest.raises(ParseError, match="range of a double"):
        _parse(f"[numeric]: 5 +- {tolerance}")


@pytest.mark.parametrize("body", ["1e999999999", "1e-999999999", "1e99999999999999999999"])
def test_huge_exponent_ends_fast_with_an_error(body: str) -> None:
    start = time.monotonic()
    with pytest.raises(ParseError):
        _parse(f"[numeric]: {body}")
    result = mdq.load(f"Stem.\n\n[numeric]: {body}\n", format="mdq")
    assert result.document is None
    assert time.monotonic() - start < 1


@pytest.mark.parametrize("answer", ["1e400", "-1e400", "1e-400", "1e1000", "1e999999999"])
def test_string_answer_out_of_range_is_malformed(answer: str) -> None:
    start = time.monotonic()
    result = mdq.load({"type": "numeric", "stem": "x", "answer": answer})
    assert [d.code for d in result.diagnostics if d.severity == "error"] == [
        "malformed-numeric-answer"
    ]
    assert time.monotonic() - start < 1


def test_integer_answer_beyond_a_double_is_malformed() -> None:
    result = mdq.load({"type": "numeric", "stem": "x", "answer": 10**400})
    assert "malformed-numeric-answer" in [d.code for d in result.diagnostics]


@pytest.mark.parametrize(
    "response", ["1e400", "-1e400", "1e-400", "1e1000", "1e999999999", 10**400]
)
def test_response_out_of_range_is_malformed(response: str | int) -> None:
    question = models.NumericQuestion(stem="x", answer="1")
    start = time.monotonic()
    with pytest.raises(ResponseError):
        question.score_response(response)
    assert time.monotonic() - start < 1


def test_blank_value_out_of_range_is_a_parse_error() -> None:
    with pytest.raises(ParseError, match="range of a double"):
        parse_question("It is [^v].\n\n[^v/numeric]: 1e400\n")

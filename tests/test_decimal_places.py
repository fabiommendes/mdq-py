"""
numeric.md, "Decimal places": `decimalPlaces` is the precision of the
comparison. It is inferred from the digits written in the value and in the
absolute tolerance, and the response and the answer are rounded to it, half
away from zero, before the tolerance test.
"""

from __future__ import annotations

from typing import Any

import pytest

import mdq
from mdq import models
from mdq._parser import parse_question
from mdq.models._numeric import infer_decimal_places, numeric_matches

INFERENCE = [
    ("2.50 +- 0.01", 2),
    ("0 +- 0.01", 2),
    ("3.14 +- 0.1", 2),
    ("1.5 +- 1", 1),
    ("3.14 +- 5% +- 0.1", 2),
    ("-273.15 +- 0.01", 2),
    ("2.5", 1),
    ("42 +- 5%", None),
    ("42 +- 5", None),
    ("1/3 +- 1", None),
]


@pytest.mark.parametrize(("body", "places"), INFERENCE, ids=[b for b, _ in INFERENCE])
def test_parser_infers_decimal_places(body: str, places: int | None) -> None:
    doc = parse_question(f"Quanto?\n\n[numeric]: {body}\n")
    assert doc.get("decimalPlaces") == places


@pytest.mark.parametrize(("body", "places"), INFERENCE, ids=[b for b, _ in INFERENCE])
def test_parser_infers_decimal_places_of_a_blank(body: str, places: int | None) -> None:
    doc = parse_question(f"Quanto mede [^x]?\n\n[^x/numeric]: {body}\n")
    assert doc["blanks"][0].get("decimalPlaces") == places


def test_frontmatter_decimal_places_wins_over_inference() -> None:
    doc = parse_question(
        "---\ndecimalPlaces: 4\n---\n\nQuanto?\n\n[numeric]: 2.50 +- 0.01\n"
    )
    assert doc["decimalPlaces"] == 4


@pytest.mark.parametrize(
    ("answer", "absolute", "places"),
    [
        ("2.50", 0.01, 2),
        (0, 0.01, 2),
        (3.14, 0.1, 2),
        (1.5, 1, 1),
        (2.5, None, 1),
        (7, None, 0),
    ],
)
def test_infer_decimal_places_helper(answer: Any, absolute: Any, places: int) -> None:
    tolerance = models.Tolerance(absolute=absolute) if absolute is not None else None
    assert infer_decimal_places(answer, tolerance) == places


def _numeric(**fields: Any) -> models.NumericQuestion:
    return mdq.load(
        {"type": "numeric", "stem": "Quanto?", **fields}, kind="question"
    ).document


def test_effective_decimal_places() -> None:
    assert (
        _numeric(answer=2.5, tolerance={"absolute": 0.01}).effective_decimal_places == 2
    )
    assert _numeric(answer=2.5, decimalPlaces=3).effective_decimal_places == 3
    assert (
        _numeric(answer=0, tolerance={"absolute": 0.01}).effective_decimal_places == 2
    )
    assert _numeric(answer=42).effective_decimal_places is None
    assert _numeric(answer="1/3").effective_decimal_places is None
    assert _numeric(answer=42, decimalPlaces=2).effective_decimal_places == 2


@pytest.mark.parametrize(
    ("response", "correct"),
    [
        (2.5, True),
        (2.505, True),
        (2.5049, True),
        (2.51, True),
        (2.515, False),
        (2.49, True),
        (2.4849, False),
    ],
)
def test_response_is_rounded_before_the_tolerance_test(
    response: float, correct: bool
) -> None:
    question = _numeric(answer=2.5, tolerance={"absolute": 0.01}, decimalPlaces=2)
    assert question.score_response(response).score == (1.0 if correct else 0.0)


@pytest.mark.parametrize(
    ("answer", "response"), [(2.68, 2.675), (-2.68, -2.675), (0.13, 0.125)]
)
def test_rounding_is_half_away_from_zero_in_decimal_arithmetic(
    answer: float, response: float
) -> None:
    question = _numeric(answer=answer, decimalPlaces=2)
    assert question.score_response(response).score == 1.0


def test_string_response_is_rounded_too() -> None:
    question = _numeric(answer=2.68, decimalPlaces=2)
    assert question.score_response("2.675").score == 1.0


def test_answer_is_rounded_too() -> None:
    question = _numeric(answer=3.14159, decimalPlaces=2)
    assert question.score_response(3.14).score == 1.0
    assert question.score_response(3.15).score == 0.0


def test_without_decimal_places_the_comparison_is_exact() -> None:
    # `42` is an integer question, so a decimal response is malformed
    # rather than wrong; the exact comparison shows on a fraction.
    assert _numeric(answer=42).score_response(43).score == 0.0
    assert _numeric(answer="1/3").score_response("1/3").score == 1.0
    assert _numeric(answer="1/3").score_response("0.3333").score == 0.0


def test_numeric_matches_accepts_decimal_places() -> None:
    # 2.5049 rounds to 2.50 at two places; unrounded it is 0.0049 away.
    tolerance = models.Tolerance(absolute=0.004)
    assert numeric_matches(2.5, 2.5049, tolerance, decimal_places=2)
    assert not numeric_matches(2.5, 2.5049, tolerance)


def test_fill_in_numeric_blank_rounds_with_its_own_places() -> None:
    question = mdq.load(
        "Quanto custa [^price]?\n\n[^price/numeric(R$)]: 2.50 +- 0.01\n",
        kind="question",
    ).document
    assert question.blanks[0].effective_decimal_places == 2
    assert question.score_response({"price": 2.505}).score == 1.0
    assert question.score_response({"price": 2.515}).score == 0.0

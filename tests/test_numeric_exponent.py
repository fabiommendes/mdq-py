"""numeric.md, "Body": scientific notation in a number, and the rejected spellings."""

from __future__ import annotations

import time
from fractions import Fraction

import pytest

import mdq
from mdq import models
from mdq._parser import parse_numeric_string, parse_question
from mdq.errors import ParseError, ResponseError
from mdq.models._numeric import numeric_value


def _parse(body: str) -> dict:
    return parse_question(f"Stem.\n\n{body}\n")


@pytest.mark.parametrize(
    ("body", "answer", "domain", "places"),
    [
        ("[numeric]: 6.022e23", 6.022e23, "decimal", 0),
        ("[numeric]: 1E-3", 0.001, "decimal", 3),
        ("[numeric]: 2.5e+4", 25000.0, "decimal", 0),
        ("[numeric]: 1e05", 100000.0, "decimal", 0),
        ("[numeric]: 1.5e-3", 0.0015, "decimal", 4),
        ("[numeric]: -1.5e-3", -0.0015, "decimal", 4),
        ("[numeric]: +1e3", 1000.0, "decimal", 0),
        ("[numeric]: 10e2", 1000.0, "decimal", 0),
        ("[numeric]: 1.50e3", "1.50e3", "decimal", 0),
        ("[numeric]: 1.50e1", "1.50e1", "decimal", 1),
        ("[numeric]: 1.7e308", 1.7e308, "decimal", 0),
        ("[numeric]: 5e-324", 5e-324, "decimal", 324),
        ("[numeric]: 0e0", 0.0, "decimal", 0),
    ],
)
def test_body_value_with_an_exponent(body: str, answer: object, domain: str, places: int) -> None:
    doc = _parse(body)
    assert doc["answer"] == answer
    assert type(doc["answer"]) is type(answer)
    assert doc["domain"] == domain
    assert doc["decimalPlaces"] == places


def test_exponent_in_both_tolerances() -> None:
    doc = _parse("[numeric(1/mol)]: 6.022e23 +- 0.001e23 +- 1E-2%")
    assert doc["tolerance"] == {"absolute": 1e20, "relative": 1e-4}
    assert doc["unit"] == "1/mol"


def test_exponent_in_the_tolerance_makes_the_domain_decimal_and_sets_the_places() -> None:
    doc = _parse("[numeric]: 5 +- 1e-3")
    assert doc["domain"] == "decimal"
    assert doc["decimalPlaces"] == 3
    # An exponent in the relative tolerance takes no part in the domain.
    assert _parse("[numeric]: 5 +- 1e-3%")["domain"] == "integer"


def test_a_numeric_blank_takes_the_exponent() -> None:
    doc = parse_question("The mass is [^m].\n\n[^m/numeric(kg)]: 5.972e24 +- 1%\n")
    blank = doc["blanks"][0]
    assert blank["answer"] == 5.972e24
    assert blank["domain"] == "decimal"
    assert blank["decimalPlaces"] == 0


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


@pytest.mark.parametrize(
    "body",
    [
        "[numeric]: 6.022e",
        "[numeric]: 6.022e+",
        "[numeric]: e3",
        "[numeric]: 1e3/2",
        "[numeric]: 1/2e3",
        "[numeric]: 1e3.5",
        "[numeric]: 1e 3",
        "[numeric]: 1 e3",
        "[numeric]: 007e3",
        "[numeric]: 1e3 +- 0.5e",
    ],
)
def test_malformed_exponents_are_parse_errors(body: str) -> None:
    with pytest.raises(ParseError):
        _parse(body)


@pytest.mark.parametrize(
    ("text", "value", "is_fraction"),
    [
        ("6.022e23", Fraction(6022 * 10**20), False),
        ("1E-3", Fraction(1, 1000), False),
        ("-2.5e+4", Fraction(-25000), False),
        ("1e05", Fraction(100000), False),
        ("+1.5e-3", Fraction(3, 2000), False),
        ("3/4", Fraction(3, 4), True),
    ],
)
def test_parse_numeric_string_reads_the_exponent(
    text: str, value: Fraction, is_fraction: bool
) -> None:
    assert parse_numeric_string(text) == (value, is_fraction)


@pytest.mark.parametrize("text", ["1e", "e3", "1e+", "1/2e3", "1e3/2", "1,5e3", " 1e3", "1e3 ", "1e 3"])
def test_parse_numeric_string_rejects_a_malformed_exponent(text: str) -> None:
    with pytest.raises(ParseError):
        parse_numeric_string(text)


@pytest.mark.parametrize(
    ("answer", "domain", "places"),
    [
        ("6.022e23", "decimal", 0),
        ("1E-3", "decimal", 3),
        ("1e3", "decimal", 0),
        ("1.5e-3", "decimal", 4),
        (1.5e-07, "decimal", 8),
        (1e-07, "decimal", 7),
        (1e22, "integer", 0),
        (6.022e23, "integer", 0),
    ],
)
def test_model_infers_domain_and_places(answer: object, domain: str, places: int) -> None:
    question = models.NumericQuestion(stem="x", answer=answer)  # type: ignore[arg-type]
    assert question.effective_domain == domain
    expected = places if domain == "decimal" else None
    assert question.effective_decimal_places == expected


def test_model_places_use_the_tolerance_exponent() -> None:
    question = models.NumericQuestion(
        stem="x", answer="5.89e-7", tolerance=models.Tolerance(absolute=1e-09)
    )
    assert question.effective_decimal_places == 9
    question = models.NumericQuestion(
        stem="x", answer="5", tolerance=models.Tolerance(absolute=1.5e-07)
    )
    assert question.effective_decimal_places == 8


@pytest.mark.parametrize("answer", ["6.022e23", "1E-3", "1e+3", "-2.5e05"])
def test_the_model_accepts_a_string_answer_with_an_exponent(answer: str) -> None:
    models.NumericQuestion(stem="x", answer=answer)
    models.NumericBlank(id="a", answer=answer)


@pytest.mark.parametrize("answer", ["1e", "1/2e3", "1e3/2", "1,5e3", "1 e3", "e3"])
def test_the_model_rejects_a_malformed_exponent_string(answer: str) -> None:
    with pytest.raises(ValueError, match="malformed-numeric-answer|not a valid numeric answer"):
        models.NumericQuestion(stem="x", answer=answer)


def test_the_schema_agrees_with_the_model() -> None:
    def codes(answer: str) -> list[str]:
        loaded = mdq.load(
            {"type": "numeric", "stem": "x", "answer": answer}, format="dict"
        )
        return [d.code for d in loaded.diagnostics if d.severity == "error"]

    assert codes("6.022e23") == []
    assert codes("1/2e3") != []
    assert codes("1e") != []


def test_scoring_with_an_exponent_is_exact() -> None:
    question = models.NumericQuestion(
        stem="x", answer="6.022e23", tolerance=models.Tolerance(absolute=1e20)
    )
    assert question.score_response("6.023e23").score == 1
    assert question.score_response(6.021e23).score == 1
    assert question.score_response("6.0231e23").score == 0
    assert question.score_response("6.022e23").score == 1
    with pytest.raises(ResponseError):
        question.score_response("6,022e23")


def test_a_negative_exponent_adds_places_to_the_rounding() -> None:
    question = models.NumericQuestion(stem="x", answer="5.89e-7")
    assert question.score_response("5.8949e-7").score == 1
    assert question.score_response("5.895e-7").score == 0


def test_integer_domain_judges_the_exponent_by_value() -> None:
    question = models.NumericQuestion(stem="x", answer=1000, domain="integer")
    assert question.score_response("1e3").score == 1
    with pytest.raises(ResponseError):
        question.score_response("1e-3")


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


@pytest.mark.parametrize("body", ["1e1000", "1e-1000", "1e+0001", "1 +- 1e1000"])
def test_body_exponent_of_four_digits_is_a_parse_error(body: str) -> None:
    with pytest.raises(ParseError):
        _parse(f"[numeric]: {body}")


@pytest.mark.parametrize("body", ["1e999999999", "1e-999999999", "1e99999999999999999999"])
def test_huge_exponent_ends_fast_with_an_error(body: str) -> None:
    start = time.monotonic()
    with pytest.raises(ParseError):
        _parse(f"[numeric]: {body}")
    result = mdq.load(f"Stem.\n\n[numeric]: {body}\n", format="mdq")
    assert result.document is None
    assert time.monotonic() - start < 1


def test_blank_value_out_of_range_is_a_parse_error() -> None:
    with pytest.raises(ParseError, match="range of a double"):
        parse_question("It is [^v].\n\n[^v/numeric]: 1e400\n")


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


@pytest.mark.parametrize("answer", ["1.7e308", "5e-324", "0e400", "0e-99"])
def test_string_answer_inside_the_range_is_valid(answer: str) -> None:
    result = mdq.load({"type": "numeric", "stem": "x", "answer": answer})
    assert result.document is not None


@pytest.mark.parametrize(
    "response", ["1e400", "-1e400", "1e-400", "1e1000", "1e999999999", 10**400]
)
def test_response_out_of_range_is_malformed(response: str | int) -> None:
    question = models.NumericQuestion(stem="x", answer="1")
    start = time.monotonic()
    with pytest.raises(ResponseError):
        question.score_response(response)
    assert time.monotonic() - start < 1


def test_response_near_the_largest_double_is_valid() -> None:
    question = models.NumericQuestion(stem="x", answer="1.7e308", domain="decimal")
    assert question.score_response("1.7e308").score == 1.0
    assert question.score_response("5e-324").score == 0.0

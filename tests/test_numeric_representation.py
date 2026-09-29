"""
numeric.md, "Answer representation": how a numeric body's value is
represented once parsed, and how the models, lint, scoring and rendering
treat each representation.

* An integer is an `int` inside the 32-bit signed range, a string outside.
* A fraction is always a string.
* A decimal is a float only if the float reproduces the written digits
  exactly; otherwise (too many digits, or a trailing zero) a string.
* `domain` does not depend on the representation.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given

from mdq import load, models
from mdq.hypothesis.documents import numeric_answers
from mdq._parser import parse_question


def _question(body: str) -> dict:
    return dict(parse_question(f"Quanto vale?\n\n[numeric]: {body}\n"))


def _blank(body: str) -> dict:
    doc = parse_question(f"O valor é [^v].\n\n[^v/numeric]: {body}\n")
    return dict(doc["blanks"][0])  # type: ignore[typeddict-item]


def _codes(doc: dict | str) -> list[str]:
    source = doc if isinstance(doc, dict) else f"Quanto vale?\n\n[numeric]: {doc}\n"
    return [d.code for d in load(source, format="mdq" if isinstance(doc, str) else None).diagnostics]


# ---------------------------------------------------------------------
# Parser output
# ---------------------------------------------------------------------

CASES = [
    # Integers: an `int` inside the 32-bit signed range, a string outside.
    ("42", 42, "integer"),
    ("-1", -1, "integer"),
    ("+7", 7, "integer"),
    ("-0", 0, "integer"),
    ("2147483647", 2147483647, "integer"),
    ("-2147483648", -2147483648, "integer"),
    ("2147483648", "2147483648", "integer"),
    ("-2147483649", "-2147483649", "integer"),
    ("+390000000000", "390000000000", "integer"),
    # Fractions: always a string, whatever their value.
    ("1/3", "1/3", "fraction"),
    ("-1/3", "-1/3", "fraction"),
    ("+3/4", "3/4", "fraction"),
    ("4/2", "4/2", "fraction"),
    # Decimals: a float only if it gives back the same digits.
    ("0.25", 0.25, "decimal"),
    ("0.1", 0.1, "decimal"),
    ("-273.15", -273.15, "decimal"),
    ("+3.14", 3.14, "decimal"),
    ("3000000000.5", 3000000000.5, "decimal"),
    ("2.0", "2.0", "decimal"),
    ("2.50", "2.50", "decimal"),
    ("-0.0", "-0.0", "decimal"),
    ("3.14159265358979323846", "3.14159265358979323846", "decimal"),
    ("0." + "0" * 400 + "1", "0." + "0" * 400 + "1", "decimal"),
]


@pytest.mark.parametrize(("body", "answer", "domain"), CASES)
def test_parser_answer_representation(body: str, answer: object, domain: str) -> None:
    doc = _question(body)
    assert doc["answer"] == answer
    assert type(doc["answer"]) is type(answer)
    assert doc["domain"] == domain


@pytest.mark.parametrize(("body", "answer", "domain"), CASES)
def test_numeric_blank_answer_representation(body: str, answer: object, domain: str) -> None:
    blank = _blank(body)
    assert blank["answer"] == answer
    assert type(blank["answer"]) is type(answer)
    assert blank["domain"] == domain


def test_string_decimal_keeps_its_decimal_places() -> None:
    doc = _question("2.50 +- 0.05")
    assert doc["answer"] == "2.50"
    assert doc["decimalPlaces"] == 2


def test_absolute_tolerance_still_widens_the_domain_of_a_string_answer() -> None:
    assert _question("1/3 +- 0.01")["domain"] == "decimal"
    assert _question("390000000000 +- 0.5")["domain"] == "decimal"


# ---------------------------------------------------------------------
# Models keep the representation
# ---------------------------------------------------------------------


@pytest.mark.parametrize("answer", [42, -1, 3000000000])
def test_model_keeps_an_integer_answer_integral(answer: int) -> None:
    question = load({"type": "numeric", "stem": "x", "answer": answer}).validate()
    assert type(question.answer) is int
    assert type(question.to_dict()["answer"]) is int


def test_numeric_blank_keeps_an_integer_answer_integral() -> None:
    doc = {
        "type": "fill-in",
        "stem": "O Brasil tem [^n] estados.",
        "blanks": [{"id": "n", "type": "numeric", "answer": 26}],
    }
    question = load(doc).validate()
    assert type(question.blanks[0].answer) is int


@pytest.mark.parametrize("answer", [True, False])
def test_model_rejects_a_boolean_answer(answer: bool) -> None:
    loaded = load({"type": "numeric", "stem": "x", "answer": answer})
    assert loaded.document is None


# ---------------------------------------------------------------------
# Lint: `domain` is unaffected by the representation
# ---------------------------------------------------------------------


@pytest.mark.parametrize("body", ["2.0 +- 0.1", "4/2 +- 1", "2147483648 +- 1", "1/3 +- 1"])
def test_parsed_domain_never_mismatches_its_own_answer(body: str) -> None:
    assert "domain-mismatch" not in _codes(body)


@pytest.mark.parametrize("body", ["2.0", "2.50", "4/2", "1/3"])
def test_string_decimal_or_fraction_without_tolerance_is_reported(body: str) -> None:
    assert "missing-tolerance" in _codes(body)


def test_integer_beyond_int32_is_not_missing_a_tolerance() -> None:
    assert "missing-tolerance" not in _codes("390000000000")


def test_dict_document_fraction_as_a_float_is_a_mismatch() -> None:
    # numeric.md: with `domain: fraction`, a JSON/YAML/dict answer SHOULD
    # be a fraction string or an integer; `0.25` is a decimal.
    doc = {"type": "numeric", "stem": "x", "answer": 0.25, "domain": "fraction"}
    assert "domain-mismatch" in _codes(doc)


def test_dict_document_string_decimal_is_not_a_fraction() -> None:
    doc = {"type": "numeric", "stem": "x", "answer": "0.25", "domain": "fraction"}
    assert "domain-mismatch" in _codes(doc)


def test_string_zero_with_relative_tolerance_is_reported() -> None:
    assert "relative-tolerance-around-zero" in _codes("0/5 +- 5%")


# ---------------------------------------------------------------------
# Scoring is exact
# ---------------------------------------------------------------------


def test_scoring_a_large_integer_answer_is_exact() -> None:
    question = models.NumericQuestion(stem="x", answer="3000000000000000000001")
    assert question.score_response(3000000000000000000001).score == 1.0
    assert question.score_response(3000000000000000000000).score == 0.0


def test_scoring_a_long_decimal_answer_is_exact() -> None:
    question = models.NumericQuestion(stem="x", answer="3.14159265358979323846")
    assert question.score_response(Fraction("3.14159265358979323846")).score == 1.0
    assert question.score_response(3.141592653589793).score == 0.0


def test_scoring_compares_floats_by_their_decimal_digits() -> None:
    # |0.4 - 0.3| is 0.1 exactly, although not in binary floating point.
    question = models.NumericQuestion(
        stem="x", answer=0.3, tolerance=models.Tolerance(absolute=0.1)
    )
    assert question.score_response(0.4).score == 1.0
    assert question.score_response(0.2).score == 1.0
    assert question.score_response(0.41).score == 0.0


def test_scoring_a_fraction_answer_needs_the_exact_value() -> None:
    question = models.NumericQuestion(stem="x", answer="1/3")
    assert question.score_response(Fraction(1, 3)).score == 1.0
    assert question.score_response(0.3333333333333333).score == 0.0


def test_scoring_a_string_decimal_answer_accepts_a_float_response() -> None:
    question = models.NumericQuestion(stem="x", answer="2.50")
    assert question.score_response(2.5).score == 1.0


# ---------------------------------------------------------------------
# Rendering writes the numeric body grammar
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "text"),
    [
        (42, "42"),
        (3000000000, "3000000000"),
        ("1/3", "1/3"),
        ("2.50", "2.50"),
        (0.25, "0.25"),
        (-273.15, "-273.15"),
        (1e-05, "0.00001"),
        (1e16, "10000000000000000.0"),
        (2.0, "2.0"),
    ],
)
def test_render_numeric_answer(answer: float | str, text: str) -> None:
    question = models.NumericQuestion(stem="x", answer=answer)
    assert question.render().endswith(f"[numeric]: {text}")


def test_render_relative_tolerance_without_float_noise() -> None:
    # 0.07 * 100 is 7.000000000000001 in binary floating point.
    question = models.NumericQuestion(
        stem="x", answer=42, tolerance=models.Tolerance(relative=0.07)
    )
    assert question.render().endswith("[numeric]: 42 +- 7.0%")


def test_render_small_absolute_tolerance_in_plain_notation() -> None:
    question = models.NumericQuestion(
        stem="x", answer="1/3", tolerance=models.Tolerance(absolute=1e-05)
    )
    assert question.render().endswith("[numeric]: 1/3 +- 0.00001")


@pytest.mark.parametrize("body", [body for body, _, _ in CASES])
def test_parse_render_parse_keeps_the_answer(body: str) -> None:
    first = load(f"Quanto vale?\n\n[numeric]: {body}\n", format="mdq").validate()
    second = load(first.render(), format="mdq").validate()
    assert second.answer == first.answer
    assert type(second.answer) is type(first.answer)


@given(numeric_answers())
def test_generated_answers_survive_a_render_parse_round_trip(answer: int | float | str) -> None:
    question = models.NumericQuestion(stem="Quanto vale?", answer=answer)
    parsed = load(question.render(), format="mdq").validate()
    assert parsed.answer == answer
    assert type(parsed.answer) is type(answer)


# ---------------------------------------------------------------------
# Importers give an answer the representation the parser would
# ---------------------------------------------------------------------


def _moodle_numerical(text: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<quiz>\n"
        '  <question type="numerical">\n'
        "    <name><text>Pico da Neblina</text></name>\n"
        '    <questiontext format="markdown"><text>'
        "<![CDATA[Qual a altitude do Pico da Neblina, em metros?]]>"
        "</text></questiontext>\n"
        '    <answer fraction="100" format="markdown">\n'
        f"      <text>{text}</text>\n"
        "    </answer>\n"
        "  </question>\n"
        "</quiz>\n"
    )


@pytest.mark.parametrize(
    ("text", "answer"),
    [("2995", 2995), ("2995.30", "2995.30"), ("0.25", 0.25), ("3000000000", "3000000000"), ("1e-5", 1e-5)],
)
def test_moodle_xml_import_follows_the_answer_representation(text: str, answer: object) -> None:
    from mdq.convert import import_question

    question = import_question(_moodle_numerical(text), format="moodle-xml")
    assert question.answer == answer  # type: ignore[union-attr]
    assert type(question.answer) is type(answer)  # type: ignore[union-attr]


@pytest.mark.parametrize(("spec", "answer"), [("2995", 2995), ("0.25", 0.25), ("1..2", 1.5)])
def test_gift_import_follows_the_answer_representation(spec: str, answer: object) -> None:
    from mdq.convert import import_question

    question = import_question(f"Qual a altitude do Pico da Neblina? {{#{spec}}}", format="gift")
    assert question.answer == answer  # type: ignore[union-attr]
    assert type(question.answer) is type(answer)  # type: ignore[union-attr]

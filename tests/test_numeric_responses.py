"""
numeric.md and responses.md, "Numeric": exact arithmetic, inference from
YAML/JSON values, finite numbers, the responses each domain takes and the
unit of a response. The shared vectors are in `examples/grading/numeric.yaml`.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import pytest

import mdq
from mdq.errors import ResponseError


def _question(**fields: Any) -> Any:
    loaded = mdq.load({"type": "numeric", "stem": "x", **fields}, kind="question")
    return loaded.document


def test_whole_float_is_an_integer_with_no_places() -> None:
    question = _question(answer=4.0)
    assert question.effective_domain == "integer"
    assert _question(answer=4.0, domain="decimal").effective_decimal_places == 0
    assert _question(answer=3.14).effective_decimal_places == 2
    assert _question(answer=8, tolerance={"absolute": 1.0}).effective_domain == "integer"


def test_markdown_decimal_keeps_its_places() -> None:
    question = mdq.load("What?\n\n[numeric]: 4.0\n", kind="question").document
    assert question.effective_domain == "decimal"
    assert question.effective_decimal_places == 1


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_answer_is_malformed(bad: float) -> None:
    loaded = mdq.load({"type": "numeric", "stem": "x", "answer": bad}, kind="question")
    assert [(d.code, d.path) for d in loaded.diagnostics if d.severity == "error"] == [
        ("malformed-numeric-answer", ("answer",))
    ]


@pytest.mark.parametrize("field", ["absolute", "relative"])
@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
def test_non_finite_tolerance_is_malformed(field: str, bad: float) -> None:
    doc = {"type": "numeric", "stem": "x", "answer": 1, "tolerance": {field: bad}}
    loaded = mdq.load(doc, kind="question")
    assert [(d.code, d.path) for d in loaded.diagnostics if d.severity == "error"] == [
        ("malformed-numeric-answer", ("tolerance", field))
    ]


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), True, {"value": {"value": 1}}, [1]])
def test_other_malformed_responses(bad: Any) -> None:
    for domain in ("integer", "fraction", "decimal"):
        with pytest.raises(ResponseError):
            _question(answer=1, domain=domain).score_response(bad)


def test_fraction_object_follows_the_string_form() -> None:
    decimal = _question(answer="0.5", domain="decimal")
    assert decimal.score_response(Fraction(1, 2)).score == 1
    with pytest.raises(ResponseError):
        decimal.score_response(Fraction(1, 3))
    assert _question(answer="1/3").score_response(Fraction(1, 3)).score == 1


def test_unit_in_the_tag_is_source_text() -> None:
    for tag, unit in [("m\\*s", "m\\*s"), ("`m`", "`m`")]:
        question = mdq.load(f"What?\n\n[numeric({tag})]: 42\n", kind="question").document
        assert question.unit == unit


def test_unit_of_a_numeric_blank() -> None:
    doc = {
        "type": "fill-in",
        "stem": "The Amazon is [^length] long.",
        "blanks": [{"id": "length", "type": "numeric", "answer": 6400, "unit": "km"}],
    }
    question = mdq.load(doc, kind="question").document
    assert question.score_response({"length": {"value": 6400, "unit": "km"}}).score == 1
    with pytest.raises(ResponseError):
        question.score_response({"length": {"value": 6400, "unit": "m"}})
    with pytest.raises(ResponseError):
        question.score_response({"length": "1/3x"})


def test_unit_mapping_shapes() -> None:
    question = _question(answer=1, unit="g")
    assert question.score_response({"value": 1, "unit": None}).score == 1
    with pytest.raises(ResponseError):
        question.score_response({"value": 1, "units": "g"})
    with pytest.raises(ResponseError):
        question.score_response({"value": 1, "unit": 3})

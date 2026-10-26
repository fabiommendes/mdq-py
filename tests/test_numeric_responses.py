"""
numeric.md and responses.md, "Numeric": exact arithmetic, inference from
malformed responses, the responses each domain takes and the
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


@pytest.mark.parametrize("bad", [{"value": {"value": 1}}, [1]])
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

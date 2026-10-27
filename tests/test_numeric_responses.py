"""
numeric.md and responses.md, "Numeric": a `Fraction` object as a response.
The string forms, the malformed shapes and the units are in
`examples/grading/numeric.yaml` and `fill-in.yaml`.
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


def test_fraction_object_follows_the_string_form() -> None:
    decimal = _question(answer="0.5", domain="decimal")
    assert decimal.score_response(Fraction(1, 2)).score == 1
    with pytest.raises(ResponseError):
        decimal.score_response(Fraction(1, 3))
    assert _question(answer="1/3").score_response(Fraction(1, 3)).score == 1

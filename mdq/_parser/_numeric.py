"""
The `sign? value abstol? reltol?` numeric-body grammar
(docs/question-types/numeric.md), shared by a numeric question's own
body (`[numeric]: ...`) and a numeric fill-in blank (`[^id/numeric]:
...`) -- both hand their tag's `rest` text to `_parse_numeric_expression`
and merge the result into their own document/blank dict.
"""

from __future__ import annotations

import re
from typing import Required, TypedDict

from ..errors import ParseError
from ..types import NumericDomain, ToleranceDict

#: numeric.md's `INTEGER`/`DECIMAL` terminals: no leading zeros (`007`,
#: `00.5` are not valid), a lone `0` is the one way to write zero. Shared
#: by the value, a fraction's numerator/denominator, and both
#: tolerances -- the grammar names one `INTEGER`/`DECIMAL` for all of
#: them.
_INTEGER = r"(?:0|[1-9][0-9]*)"
_DECIMAL = rf"{_INTEGER}\.[0-9]+"
_FRACTION = rf"{_INTEGER}/{_INTEGER}"
_VALUE = rf"(?:{_FRACTION}|{_DECIMAL}|{_INTEGER})"
_TOLERANCE_NUM = rf"(?:{_DECIMAL}|{_INTEGER})"

NUM_VALUE_RE = re.compile(
    rf"^(?P<sign>[+-])?(?P<value>{_VALUE})"
    rf"(?P<tolerances>(?:\s*\+-\s*{_TOLERANCE_NUM}%?)*)\s*$"
)
TOL_TERM_RE = re.compile(rf"\+-\s*(?P<num>{_TOLERANCE_NUM})(?P<pct>%)?")

#: The bare `sign? value` grammar (numeric.md) -- no tolerance terms.
#: Used to validate an `answer` written as a `str` directly in a
#: dict/YAML/JSON document (`mdq.models._numeric`, `mdq.models.
#: _fill_in`); the Markdown surface syntax never produces this shape on
#: its own, since `_parse_numeric_expression` below always turns a body
#: fraction into a `float`.
VALUE_RE = re.compile(rf"^(?P<sign>[+-])?(?P<value>{_VALUE})$")


class _NumericExpr(TypedDict, total=False):
    """
    The fields `_parse_numeric_expression` fills in.

    A fragment of `NumericQuestionDict`/`NumericBlankDict` -- everything
    but the `type` (and, for a blank, `id`) the caller already knows and
    adds itself.
    """

    answer: Required[float]
    domain: NumericDomain
    decimalPlaces: int
    tolerance: ToleranceDict


def _parse_numeric_expression(expr: str) -> _NumericExpr:
    """
    Parse the value/tolerance grammar from docs/question-types/numeric.md
    (`sign? value abstol? reltol?`, order-independent in practice -- see
    numeric/tolerances.mdq.md, which writes the relative tolerance
    first).
    """

    m = NUM_VALUE_RE.match(expr.strip())
    if not m:
        raise ParseError(f"malformed numeric body: {expr!r}")

    sign = -1 if m.group("sign") == "-" else 1
    value_str = m.group("value")

    result: _NumericExpr
    if "/" in value_str:
        num, den = value_str.split("/")
        if int(den) == 0:
            raise ParseError(f"zero denominator in numeric body: {expr!r}")
        result = {"answer": sign * (int(num) / int(den)), "domain": "fraction"}
    elif "." in value_str:
        result = {
            "answer": sign * float(value_str),
            "domain": "decimal",
            "decimalPlaces": len(value_str.split(".", 1)[1]),
        }
    else:
        result = {"answer": sign * int(value_str), "domain": "integer"}

    tolerance: ToleranceDict = {}
    for tol_match in TOL_TERM_RE.finditer(m.group("tolerances")):
        num = float(tol_match.group("num"))
        if tol_match.group("pct"):
            tolerance["relative"] = num / 100
        else:
            tolerance["absolute"] = num
    if tolerance:
        result["tolerance"] = tolerance

    return result


def parse_numeric_value(text: str) -> float:
    """
    Parse a bare `sign? value` (numeric.md's grammar for a numeric
    body's value, with no tolerance terms) -- what a string `answer`
    (numeric.md, "Answer representation") must look like.

    Raises:
        ParseError: `text` does not match the grammar, or is a fraction
            with a zero denominator.
    """
    m = VALUE_RE.match(text.strip())
    if not m:
        raise ParseError(f"malformed numeric value: {text!r}")

    sign = -1 if m.group("sign") == "-" else 1
    value_str = m.group("value")
    if "/" in value_str:
        num, den = value_str.split("/")
        if int(den) == 0:
            raise ParseError(f"zero denominator in numeric value: {text!r}")
        return sign * (int(num) / int(den))
    return sign * float(value_str)

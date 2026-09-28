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

NUM_VALUE_RE = re.compile(
    r"^(?P<sign>[+-])?(?P<value>\d+/\d+|\d+\.\d+|\d+)"
    r"(?P<tolerances>(?:\s*\+-\s*\d+(?:\.\d+)?%?)*)\s*$"
)
TOL_TERM_RE = re.compile(r"\+-\s*(?P<num>\d+(?:\.\d+)?)(?P<pct>%)?")


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

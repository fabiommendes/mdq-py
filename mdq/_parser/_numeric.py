"""
The `sign? value abstol? reltol?` numeric-body grammar
(docs/question-types/numeric.md), shared by a numeric question's own
body (`[numeric]: ...`) and a numeric fill-in blank (`[^id/numeric]:
...`) -- both hand their tag's `rest` text to `_parse_numeric_expression`
and merge the result into their own document/blank dict.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal
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
    rf"(?P<tolerances>(?:[ \t]*\+-[ \t]*{_TOLERANCE_NUM}%?)*)[ \t]*$"
)
TOL_TERM_RE = re.compile(rf"\+-[ \t]*(?P<num>{_TOLERANCE_NUM})(?P<pct>%)?")

#: The bare `sign? value` grammar (numeric.md) -- no tolerance terms.
#: Used to validate an `answer` written as a `str` (`mdq.models.
#: _numeric`, `mdq.models._fill_in`), whether a dict/YAML/JSON document
#: wrote it or `_parse_numeric_expression` below kept it as one.
VALUE_RE = re.compile(rf"^(?P<sign>[+-])?(?P<value>{_VALUE})$")

#: numeric.md, "Answer representation": an integer outside the 32-bit
#: signed range stays a string.
_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1


class _NumericExpr(TypedDict, total=False):
    """
    The fields `_parse_numeric_expression` fills in.

    A fragment of `NumericQuestionDict`/`NumericBlankDict` -- everything
    but the `type` (and, for a blank, `id`) the caller already knows and
    adds itself.
    """

    answer: Required[int | float | str]
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

    m = NUM_VALUE_RE.match(expr.strip(" \t"))
    if not m:
        raise ParseError(f"malformed numeric body: {expr!r}")

    sign = m.group("sign") or ""
    value_str = m.group("value")

    if "/" in value_str and int(value_str.split("/")[1]) == 0:
        raise ParseError(f"zero denominator in numeric body: {expr!r}")
    answer = _answer_value(sign, value_str)

    result: _NumericExpr
    if "/" in value_str:
        result = {"answer": answer, "domain": "fraction"}
    elif "." in value_str:
        result = {
            "answer": answer,
            "domain": "decimal",
            "decimalPlaces": len(value_str.split(".", 1)[1]),
        }
    else:
        result = {"answer": answer, "domain": "integer"}

    tolerance: ToleranceDict = {}
    absolute_is_decimal = False
    for tol_match in TOL_TERM_RE.finditer(m.group("tolerances")):
        num = float(tol_match.group("num"))
        if tol_match.group("pct"):
            tolerance["relative"] = num / 100
        else:
            tolerance["absolute"] = num
            absolute_is_decimal = "." in tol_match.group("num")
    if tolerance:
        result["tolerance"] = tolerance
    # numeric.md, "Number type/domain": an absolute tolerance written as a
    # decimal makes the domain decimal, whatever the value's own form.
    if absolute_is_decimal:
        result["domain"] = "decimal"

    return result


def _answer_value(sign: str, value: str) -> int | float | str:
    """
    numeric.md, "Answer representation": the JSON value of a numeric
    body's `sign? value`. A `+` sign is dropped, since it adds nothing.

    * An integer is an `int` if it fits the 32-bit signed range, a
      string otherwise.
    * A fraction is always a string: most have no exact float.
    * A decimal is a `float` only if the float gives back the written
      digits: its shortest repr is the same decimal, and the written
      value does not end in a zero, which records a significant digit
      the float drops (`2.50`). Otherwise it is a string.
    """
    text = "-" + value if sign == "-" else value
    if "/" in value:
        return text
    if "." in value:
        number = float(text)
        if not value.endswith("0") and math.isfinite(number):
            if Decimal(repr(number)) == Decimal(text):
                return number
        return text
    integer = int(text)
    if _INT32_MIN <= integer <= _INT32_MAX:
        return integer
    return text


def parse_numeric_answer(text: str) -> int | float | str:
    """
    Parse a bare `sign? value` (numeric.md's grammar for a numeric
    body's value, with no tolerance terms) into the representation a
    numeric body's value gets (numeric.md, "Answer representation"; see
    `_answer_value`). The importers use it, so an imported answer reads
    the same as one written in Markdown.

    Raises:
        ParseError: `text` does not match the grammar, or is a fraction
            with a zero denominator.
    """
    m = VALUE_RE.match(text.strip(" \t"))
    if not m:
        raise ParseError(f"malformed numeric value: {text!r}")
    value = m.group("value")
    if "/" in value and int(value.split("/")[1]) == 0:
        raise ParseError(f"zero denominator in numeric value: {text!r}")
    return _answer_value(m.group("sign") or "", value)


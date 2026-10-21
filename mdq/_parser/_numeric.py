"""
The `sign? numeric_value abstol? reltol?` numeric-body grammar
(docs/question-types/numeric.md), shared by a numeric question's own
body (`[numeric]: ...`) and a numeric fill-in blank (`[^id/numeric]:
...`) -- both hand their tag's `rest` text to `_parse_numeric_expression`
and merge the result into their own document/blank dict.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal
from fractions import Fraction
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
#: numeric.md's `number`: an `INTEGER` or `DECIMAL` with an optional
#: `EXPONENT`, at most 3 digits. A fraction takes none.
_NUMBER = rf"(?:{_DECIMAL}|{_INTEGER})(?:[eE][+-]?[0-9]{{1,3}})?"
_VALUE = rf"(?:{_FRACTION}|{_NUMBER})"
_TOLERANCE_NUM = _NUMBER

NUM_VALUE_RE = re.compile(
    rf"^(?P<sign>[+-])?(?P<value>{_VALUE})"
    rf"(?P<tolerances>(?:[ \t]*\+-[ \t]*{_TOLERANCE_NUM}%?)*)[ \t]*$"
)
TOL_TERM_RE = re.compile(rf"\+-[ \t]*(?P<num>{_TOLERANCE_NUM})(?P<pct>%)?")

#: Spellings that numeric.md, "Body", rejects on purpose, each with the
#: hint a `ParseError` gives. Checked in order.
_REJECTED_SPELLINGS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile("\u2212"), 'use "-" (U+002D) as the minus sign'),
    (re.compile("\u00b1"), 'use "+-" for a tolerance'),
    (re.compile("[0-9],[0-9]"), 'use "." as the decimal separator'),
    (
        re.compile("[0-9][ \t\u00a0\u2009\u202f]+[0-9]"),
        "remove the digit group separator",
    ),
)

#: The bare `sign? numeric_value` grammar (numeric.md) -- no tolerance terms.
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
    #: The decimal places written in the value and the absolute tolerance,
    #: whichever is larger (numeric.md, "Decimal places"). Always present;
    #: the caller keeps it only when the question's domain is `decimal`.
    decimalPlaces: int
    tolerance: ToleranceDict


def _check_double_range(value: str, text: str) -> None:
    """
    numeric.md, "Answer representation": the runtimes read a number as a
    double before the exact arithmetic, so a `value` whose modulus is
    above the largest finite double, or that is not zero but rounds to
    0, is malformed. A fraction is checked as its numerator and its
    denominator. The check runs before any `Fraction` exists, so a huge
    exponent never reaches the exact arithmetic.

    Raises:
        ParseError: `value` is out of the range of a double. `text` is
            the source text, for the message.
    """
    for part in value.split("/"):
        as_double = float(part)
        mantissa = part.lower().split("e", 1)[0]
        if math.isinf(as_double) or (as_double == 0 and mantissa.strip("0.")):
            raise ParseError(f"number out of the range of a double: {text!r}")


def _parse_numeric_expression(expr: str) -> _NumericExpr:
    """
    Parse the value/tolerance grammar from docs/question-types/numeric.md:
    `sign? numeric_value`, then at most one absolute and one relative tolerance,
    in either order (numeric/tolerances.mdq.md writes the relative one
    first).

    Raises:
        ParseError: the text does not match the grammar, the fraction has
            a zero denominator, a number is out of the range of a double,
            or a tolerance kind is written twice.
    """

    m = NUM_VALUE_RE.match(expr.strip(" \t"))
    if not m:
        raise ParseError(f"malformed numeric body: {expr!r}{_spelling_hint(expr)}")

    sign = m.group("sign") or ""
    value_str = m.group("value")

    if "/" in value_str and not value_str.split("/")[1].strip("0"):
        raise ParseError(f"zero denominator in numeric body: {expr!r}")
    _check_double_range(value_str, expr)
    answer = _answer_value(sign, value_str)

    result: _NumericExpr
    if "/" in value_str:
        result = {"answer": answer, "domain": "fraction"}
    elif _is_decimal_spelling(value_str):
        result = {"answer": answer, "domain": "decimal"}
    else:
        result = {"answer": answer, "domain": "integer"}

    tolerance: ToleranceDict = {}
    absolute_is_decimal = False
    absolute_places = 0
    for tol_match in TOL_TERM_RE.finditer(m.group("tolerances")):
        _check_double_range(tol_match.group("num"), expr)
        num = float(tol_match.group("num"))
        kind = "relative" if tol_match.group("pct") else "absolute"
        if kind in tolerance:
            raise ParseError(f"a numeric body takes one {kind} tolerance: {expr!r}")
        if kind == "relative":
            tolerance["relative"] = num / 100
        else:
            tolerance["absolute"] = num
            absolute_is_decimal = _is_decimal_spelling(tol_match.group("num"))
            absolute_places = _written_places(tol_match.group("num"))
    if tolerance:
        result["tolerance"] = tolerance
    # numeric.md, "Number type/domain": an absolute tolerance written as a
    # decimal makes the domain decimal, whatever the value's own form.
    if absolute_is_decimal:
        result["domain"] = "decimal"
    # numeric.md, "Decimal places": the places written in the value and in
    # the absolute tolerance, whichever is larger.
    value_places = _written_places(value_str)
    result["decimalPlaces"] = max(value_places, absolute_places)

    return result


def _spelling_hint(text: str) -> str:
    """The `; hint` suffix for a rejected spelling in `text`, or `""`."""
    for pattern, hint in _REJECTED_SPELLINGS:
        if pattern.search(text):
            return f"; {hint}"
    return ""


def _is_decimal_spelling(number: str) -> bool:
    """
    numeric.md, "Number type/domain": a `number` is `decimal` if it has a
    decimal point or an exponent.
    """
    return "." in number or "e" in number or "E" in number


def _written_places(number: str) -> int:
    """
    numeric.md, "Decimal places": `max(0, d - e)` for a `number` with `d`
    digits after the decimal point and the exponent `e` (0 if absent).
    """
    mantissa, _, exponent = number.lower().partition("e")
    digits = len(mantissa.split(".", 1)[1]) if "." in mantissa else 0
    return max(0, digits - int(exponent or 0))


def _answer_value(sign: str, value: str) -> int | float | str:
    """
    numeric.md, "Answer representation": the JSON value of a numeric
    body's `sign? numeric_value`. A `+` sign is dropped, since it adds nothing.

    * An integer is an `int` if it fits the 32-bit signed range, a
      string otherwise.
    * A fraction is always a string: most have no exact float.
    * A decimal, or a number with an exponent, is a `float` only if the
      float gives back the written digits: its shortest repr is the same
      decimal, and the mantissa does not end in a zero after the point, which
      records a significant digit the float drops (`2.50`, `1.50e3`). Otherwise it
      is a string.
    """
    text = "-" + value if sign == "-" else value
    if "/" in value:
        return text
    if _is_decimal_spelling(value):
        number = float(text)
        mantissa = value.lower().split("e", 1)[0]
        # Only a zero after the point is a recorded significant digit.
        records_digit = "." in mantissa and mantissa.endswith("0")
        if not records_digit and math.isfinite(number):
            if Decimal(repr(number)) == Decimal(text):
                return number
        return text
    integer = int(text)
    if _INT32_MIN <= integer <= _INT32_MAX:
        return integer
    return text


def parse_numeric_answer(text: str) -> int | float | str:
    """
    Parse a bare `sign? numeric_value` (numeric.md's grammar for a numeric
    body's value, with no tolerance terms) into the representation a
    numeric body's value gets (numeric.md, "Answer representation"; see
    `_answer_value`). The importers use it, so an imported answer reads
    the same as one written in Markdown.

    Raises:
        ParseError: `text` does not match the grammar, is a fraction
            with a zero denominator, or is out of the range of a double.
    """
    m = VALUE_RE.match(text.strip(" \t"))
    if not m:
        raise ParseError(f"malformed numeric value: {text!r}")
    value = m.group("value")
    if "/" in value and not value.split("/")[1].strip("0"):
        raise ParseError(f"zero denominator in numeric value: {text!r}")
    _check_double_range(value, text)
    return _answer_value(m.group("sign") or "", value)



def parse_numeric_string(text: str) -> tuple[Fraction, bool]:
    """
    Read a response string as the exact rational it spells, and report
    whether it is written as a fraction (responses.md, "Numeric").

    The string is exactly `sign? numeric_value`: not trimmed, no comma, no inner
    space. A `number` MAY have an exponent (`"6.022e23"`).

    Raises:
        ParseError: `text` does not match the grammar, is a fraction
            with a zero denominator, or is out of the range of a double.
    """
    m = VALUE_RE.fullmatch(text)
    if not m:
        raise ParseError(f"malformed numeric value: {text!r}")
    value = m.group("value")
    if "/" in value and not value.split("/")[1].strip("0"):
        raise ParseError(f"zero denominator in numeric value: {text!r}")
    _check_double_range(value, text)
    return Fraction(text), "/" in value

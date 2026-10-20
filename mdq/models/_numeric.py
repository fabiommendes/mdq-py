"""
Numeric questions: `Tolerance`, `NumericQuestion`, and the
value/tolerance-matching helpers a numeric fill-in blank
(`mdq.models._fill_in`) reuses as-is.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Any, Iterable, Literal

from pydantic import Field, StrictFloat, StrictInt, field_validator
from pydantic_core import PydanticCustomError

from .. import _parser, types as t
from .._diagnostics import Diagnostic
from .._markdown import UNICODE_SPACE
from ..errors import ParseError, ResponseError
from ..types import NumericDomain
from . import _lint
from ._base import BaseQuestion, FreeText, MdqModel
from ._score import QuestionScore

__all__ = ["Tolerance", "NumericQuestion"]

#: The `UNIT` terminal of docs/references/grammar.md: non-empty, no
#: `UNICODE_SPACE`, no parentheses or brackets. Mirrors the `unit`
#: pattern in `schema/numeric.yaml`.
_UNIT_PATTERN = rf"^[^()\[\]{UNICODE_SPACE}]+$"

#: numeric.md, "Answer representation": a number, or a string in the
#: `sign? value` grammar that keeps a value no float holds exactly
#: ("1/3", "2.50", "3000000000"). Strict, so an `int` stays an `int`
#: (it is not widened to a `float`) and a `bool` is not a number.
NumericAnswer = StrictInt | StrictFloat | str


def _validate_numeric_answer(value: NumericAnswer) -> NumericAnswer:
    """
    numeric.md, "Answer representation": a string `answer` MUST be a
    valid `sign? value` (an `INTEGER` or `DECIMAL` with an optional
    exponent, or a fraction with a nonzero denominator) -- the same grammar a numeric body's value
    follows. A JSON/YAML number MUST be finite: `.inf` and `.nan` are
    rejected.

    Reuses `mdq._parser.parse_numeric_answer` instead of a second regex.
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise PydanticCustomError(
            "malformed-numeric-answer",
            f"{value!r} is not a finite number",
        )
    if isinstance(value, int) and _int_beyond_double(value):
        raise PydanticCustomError(
            "malformed-numeric-answer",
            "the integer is out of the range of a double",
        )
    if isinstance(value, str):
        try:
            _parser.parse_numeric_answer(value)
        except ParseError as exc:
            raise PydanticCustomError(
                "malformed-numeric-answer",
                f"{value!r} is not a valid numeric answer: {exc}",
            ) from exc
    return value


def _int_beyond_double(value: int) -> bool:
    """True if the modulus of `value` is above the largest finite double."""
    try:
        float(value)
    except OverflowError:
        return True
    return False


class Tolerance(MdqModel):
    """A distance from the answer, so neither bound is negative (schema)."""

    absolute: Annotated[float, Field(ge=0)] | None = None
    relative: Annotated[float, Field(ge=0)] | None = None

    @field_validator("absolute", "relative", mode="before")
    @classmethod
    def check_finite(cls, value: Any) -> Any:
        """numeric.md, "Answer representation": a tolerance is finite."""
        if isinstance(value, float) and not math.isfinite(value):
            raise PydanticCustomError(
                "malformed-numeric-answer",
                f"{value!r} is not a finite number",
            )
        return value



class NumericQuestion(BaseQuestion[t.NumericResponse]):
    #: The correct value. See `NumericAnswer`.
    answer: NumericAnswer
    type: Literal["numeric"] = "numeric"
    unit: Annotated[str, Field(pattern=_UNIT_PATTERN)] | None = None
    domain: NumericDomain | None = None
    decimal_places: int | None = Field(default=None, ge=0)
    tolerance: Tolerance | None = None

    #: Feedback for an incorrect response (numeric.md, "Feedback").
    incorrect_feedback: FreeText | None = None

    @field_validator("answer")
    @classmethod
    def check_answer_grammar(cls, value: NumericAnswer) -> NumericAnswer:
        return _validate_numeric_answer(value)

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(
            _lint.check_numeric(
                answer=self.answer,
                domain=self.domain,
                decimal_places=self.decimal_places,
                tolerance=self.tolerance,
                path=(),
            )
        )
        return diagnostics

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.domain is not None:
            data["domain"] = self.domain
        if self.decimal_places is not None:
            data["decimalPlaces"] = self.decimal_places
        if self.incorrect_feedback is not None:
            data["incorrectFeedback"] = self.incorrect_feedback
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        yield render_numeric_tag(
            self.answer,
            unit=self.unit,
            tolerance=self.tolerance,
        )

    @property
    def effective_decimal_places(self) -> int | None:
        """
        The precision of the comparison (numeric.md, "Decimal places"):
        `decimal_places` when given; else, for a `decimal` domain
        (declared or inferred), `infer_decimal_places`; else None.
        """
        if self.decimal_places is not None:
            return self.decimal_places
        if _lint._effective_numeric_domain(self.answer, self.domain, self.tolerance) == "decimal":
            return infer_decimal_places(self.answer, self.tolerance)
        return None

    def score_response(self, response: t.NumericResponse) -> QuestionScore:
        """
        Score 1 if `response`, rounded to `effective_decimal_places`, is
        within tolerance of `answer`, else 0. An incorrect response gets
        `incorrect_feedback`, if set (numeric.md, "Feedback").

        Raises:
            ResponseError: `response` isn't a valid number, is a value the
                question's domain cannot represent, or has a unit other than
                the question's (responses.md, "Numeric").
        """
        correct = numeric_matches(
            self.answer,
            response,
            self.tolerance,
            self.effective_decimal_places,
            domain=self.effective_domain,
            unit=self.unit,
        )
        feedback = [] if correct or not self.incorrect_feedback else [self.incorrect_feedback]
        return QuestionScore(score=1.0 if correct else 0.0, feedback=feedback)

    @property
    def effective_domain(self) -> NumericDomain:
        """
        The declared `domain`, else the one inferred from `answer` and the
        absolute tolerance (numeric.md, "Number type/domain").
        """
        return _lint._effective_numeric_domain(self.answer, self.domain, self.tolerance)



#
# Utilities
#

def numeric_value(value: NumericAnswer | Fraction) -> Fraction:
    """
    Convert a numeric answer, response or tolerance to an exact rational.

    A string is read as the decimal or fraction it spells ("3.14",
    "1/3"). A float is read as its shortest repr, i.e. the decimal it
    was written as: `0.1` is 1/10, not the nearest binary fraction.

    Raises:
        ValueError: `value` isn't a valid finite number.
    """
    if isinstance(value, float):
        return Fraction(repr(value))
    return Fraction(value)


def infer_decimal_places(answer: NumericAnswer, tolerance: Tolerance | None) -> int:
    """
    The `decimalPlaces` a `decimal` question gets when the frontmatter
    gives none (numeric.md, "Decimal places"): the larger of the number
    of decimal places written in `answer` and in `tolerance.absolute`. An
    integer has 0; a string answer counts its written digits (`"2.50"`
    is 2); a float counts the digits of its shortest repr, but a float
    of whole value has 0 (`4.0`), as the JS number `4.0` is `4`. An
    exponent moves the point: `"1.5e-3"` has 4 places, `"6.022e23"` has 0.
    """
    places = _written_places(answer)
    if tolerance is not None and tolerance.absolute is not None:
        places = max(places, _written_places(tolerance.absolute))
    return places


def _written_places(value: NumericAnswer) -> int:
    """
    The decimal places of `value` (numeric.md, "Decimal places"): the digits
    after the point less the exponent, never below 0.
    """
    if isinstance(value, str):
        mantissa, _, written_exponent = value.lower().partition("e")
        digits = len(mantissa.split(".", 1)[1]) if "." in mantissa else 0
        return max(0, digits - int(written_exponent or 0))
    if isinstance(value, float):
        if value.is_integer():
            return 0
        exponent = Decimal(repr(value)).as_tuple().exponent
        return max(0, -exponent) if isinstance(exponent, int) else 0
    return 0


def _round_half_up(value: Fraction, places: int) -> Fraction:
    """Round `value` to `places` decimals, half away from zero (exact)."""
    scale = 10**places
    scaled = abs(value) * scale
    rounded = (scaled.numerator * 2 + scaled.denominator) // (scaled.denominator * 2)
    return Fraction(rounded if value >= 0 else -rounded, scale)


def _response_value(
    response: t.NumericResponse,
    *,
    domain: NumericDomain | None,
    unit: str | None,
) -> Fraction:
    """
    Read a response as an exact rational and check it against the
    question's `domain` and `unit` (responses.md, "Numeric").

    Raises:
        ResponseError: the response is malformed.
    """
    original = response
    if isinstance(response, Mapping):
        extra = set(response) - {"value", "unit"}
        if "value" not in response or extra:
            raise ResponseError(
                f"{original!r} must be a mapping with 'value' and, optionally, 'unit'"
            )
        _check_response_unit(response.get("unit"), unit)
        response = response["value"]
        if isinstance(response, Mapping):
            raise ResponseError(f"{original!r} is not a valid numeric response")

    from_fraction_form = False
    if isinstance(response, bool):
        raise ResponseError(f"{response!r} is not a valid numeric response")
    if isinstance(response, str):
        try:
            value, from_fraction_form = _parser.parse_numeric_string(response)
        except ParseError as exc:
            raise ResponseError(f"{response!r} is not a valid numeric response") from exc
    elif isinstance(response, float):
        if not math.isfinite(response):
            raise ResponseError(f"{response!r} is not a finite number")
        value = numeric_value(response)
    elif isinstance(response, int) and _int_beyond_double(response):
        raise ResponseError("the integer is out of the range of a double")
    elif isinstance(response, int | Fraction):
        value = Fraction(response)
        # A `Fraction` object has no written form: it is a fraction only
        # if no finite decimal spells it.
        from_fraction_form = not _is_terminating(value)
    else:
        raise ResponseError(f"{response!r} is not a valid numeric response")

    if domain == "integer" and value.denominator != 1:
        raise ResponseError(
            f"{response!r} is not an integer, which the question's domain requires"
        )
    if domain == "decimal" and from_fraction_form:
        raise ResponseError(
            f"{response!r} is a fraction, which a decimal question does not take"
        )
    return value


def _is_terminating(value: Fraction) -> bool:
    """True if a finite decimal spells `value` (the denominator is 2^a 5^b)."""
    denominator = value.denominator
    for prime in (2, 5):
        while denominator % prime == 0:
            denominator //= prime
    return denominator == 1


def _check_response_unit(response_unit: object, unit: str | None) -> None:
    """
    responses.md, "Numeric": the unit of a response is absent or equal to
    the declared one (exact string after NFC); any other is malformed.
    """
    if response_unit is None:
        return
    if not isinstance(response_unit, str):
        raise ResponseError(f"the unit {response_unit!r} is not a string")
    if unit is None:
        raise ResponseError(
            f"the response has the unit {response_unit!r}, but the question declares none"
        )
    if unicodedata.normalize("NFC", response_unit) != unicodedata.normalize("NFC", unit):
        raise ResponseError(
            f"the response has the unit {response_unit!r}, but the question declares {unit!r}"
        )


def numeric_matches(
    answer: NumericAnswer,
    response: t.NumericResponse,
    tolerance: Tolerance | None,
    decimal_places: int | None = None,
    *,
    domain: NumericDomain | None = None,
    unit: str | None = None,
) -> bool:
    """
    Report whether `response` is within `answer`'s tolerance.

    With neither tolerance set, the match must be exact. With both set,
    either one passing is enough. The comparison is exact (see
    `numeric_value`), so a string answer keeps the precision it was
    written with. With `decimal_places`, the response and the answer are
    first rounded to that many places, half away from zero, in decimal
    arithmetic (numeric.md, "Decimal places"). The relative tolerance
    uses the answer before the rounding, and no tolerance is rounded
    (numeric.md, "Tolerances"). With `domain`, a value it cannot
    represent is malformed (responses.md, "Numeric"). `unit` is the
    question's declared unit: a response in another unit is malformed.

    Raises:
        ResponseError: `response` isn't a valid number, `domain` cannot
            represent it, or its unit is not `unit`.
    """
    value = _response_value(response, domain=domain, unit=unit)
    exact_answer = numeric_value(answer)
    target = exact_answer
    if decimal_places is not None:
        value = _round_half_up(value, decimal_places)
        target = _round_half_up(target, decimal_places)
    distance = abs(value - target)

    if tolerance is None or (tolerance.absolute is None and tolerance.relative is None):
        return distance == 0
    if tolerance.absolute is not None and distance <= numeric_value(tolerance.absolute):
        return True
    if (
        tolerance.relative is not None
        and distance <= abs(exact_answer) * numeric_value(tolerance.relative)
    ):
        return True
    return False


def render_numeric_tag(
    answer: NumericAnswer,
    *,
    tag: str = "[numeric]",
    unit: str | None = None,
    tolerance: Tolerance | None = None,
) -> str:
    """Return a numeric answer tag in the parser's accepted syntax."""
    if unit is not None:
        tag = f"{tag[:-1]}({unit})]"

    terms = [answer if isinstance(answer, str) else _format_number(answer)]
    if tolerance is not None:
        if tolerance.absolute is not None:
            terms.append(f"+- {_format_number(tolerance.absolute)}")
        if tolerance.relative is not None:
            percent = Decimal(repr(tolerance.relative)) * 100
            terms.append(f"+- {_format_number(float(percent))}%")
    return f"{tag}: {' '.join(terms)}"


def _format_number(value: int | float) -> str:
    """
    Write a number in the `number` grammar of numeric.md:
    plain notation, never an exponent (`1e-05` is `0.00001`). A float
    keeps its `.0` when whole, so it reads back as a decimal.
    """
    if isinstance(value, int):
        return str(value)
    text = repr(value)
    if "e" not in text:
        return text
    text = format(Decimal(text), "f")
    return text if "." in text else f"{text}.0"

"""
Numeric questions: `Tolerance`, `NumericQuestion`, and the
value/tolerance-matching helpers a numeric fill-in blank
(`mdq.models._fill_in`) reuses as-is.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Any, Iterable, Literal

from pydantic import Field, StrictFloat, StrictInt, field_validator
from pydantic_core import PydanticCustomError

from .. import _parser, types as t
from .._diagnostics import Diagnostic
from ..errors import ParseError, ResponseError
from ..types import NumericDomain
from . import _lint
from ._base import BaseQuestion, MdqModel
from ._score import QuestionScore

__all__ = ["Tolerance", "NumericQuestion"]

#: numeric.md, "Unit conversion": non-empty, no whitespace, no parentheses
#: or brackets. Mirrors the `unit` pattern in `schema/numeric.yaml`.
_UNIT_PATTERN = r"^[^\s()\[\]]+$"

#: numeric.md, "Answer representation": a number, or a string in the
#: `sign? value` grammar that keeps a value no float holds exactly
#: ("1/3", "2.50", "3000000000"). Strict, so an `int` stays an `int`
#: (it is not widened to a `float`) and a `bool` is not a number.
NumericAnswer = StrictInt | StrictFloat | str


def _validate_numeric_answer(value: NumericAnswer) -> NumericAnswer:
    """
    numeric.md, "Answer representation": a string `answer` MUST be a
    valid `sign? value` (an `INTEGER`, `DECIMAL`, or a fraction with a
    nonzero denominator) -- the same grammar a numeric body's value
    follows. A JSON/YAML number needs no check; it is already one.

    Reuses `mdq._parser.parse_numeric_answer` instead of a second regex.
    """
    if isinstance(value, str):
        try:
            _parser.parse_numeric_answer(value)
        except ParseError as exc:
            raise PydanticCustomError(
                "malformed-numeric-answer",
                f"{value!r} is not a valid numeric answer: {exc}",
            ) from exc
    return value


class Tolerance(MdqModel):
    absolute: float | None = None
    relative: float | None = None




class NumericQuestion(BaseQuestion[t.NumericResponse]):
    #: The correct value. See `NumericAnswer`.
    answer: NumericAnswer
    type: Literal["numeric"] = "numeric"
    unit: Annotated[str, Field(pattern=_UNIT_PATTERN)] | None = None
    domain: NumericDomain | None = None
    decimal_places: int | None = Field(default=None, ge=0)
    tolerance: Tolerance | None = None

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
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        yield render_numeric_tag(
            self.answer,
            unit=self.unit,
            tolerance=self.tolerance,
        )

    def score_response(self, response: t.NumericResponse) -> QuestionScore:
        """
        Score 1 if `response` is within tolerance of `answer`, else 0.

        Raises:
            ResponseError: `response` isn't a valid number.
        """
        correct = numeric_matches(self.answer, response, self.tolerance)
        return QuestionScore(score=1.0 if correct else 0.0)



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


def numeric_matches(
    answer: NumericAnswer, response: t.NumericResponse, tolerance: Tolerance | None
) -> bool:
    """
    Report whether `response` is within `answer`'s tolerance.

    With neither tolerance set, the match must be exact. With both set,
    either one passing is enough. The comparison is exact (see
    `numeric_value`), so a string answer keeps the precision it was
    written with.

    Raises:
        ResponseError: `response` isn't a valid number.
    """
    try:
        value = numeric_value(response)
    except (ValueError, ZeroDivisionError) as exc:
        raise ResponseError(f"{response!r} is not a valid numeric response") from exc
    target = numeric_value(answer)
    distance = abs(value - target)

    if tolerance is None or (tolerance.absolute is None and tolerance.relative is None):
        return distance == 0
    if tolerance.absolute is not None and distance <= numeric_value(tolerance.absolute):
        return True
    if (
        tolerance.relative is not None
        and distance <= abs(target) * numeric_value(tolerance.relative)
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
    Write a number in the `INTEGER`/`DECIMAL` grammar of numeric.md:
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

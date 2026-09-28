"""
Numeric questions: `Tolerance`, `NumericQuestion`, and the
value/tolerance-matching helpers a numeric fill-in blank
(`mdq.models._fill_in`) reuses as-is.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Iterable, Literal

from pydantic import Field

from .. import types as t
from .._diagnostics import Diagnostic
from ..errors import ResponseError
from ..types import NumericDomain
from . import _lint
from ._base import BaseQuestion, MdqModel
from ._score import QuestionScore

__all__ = ["Tolerance", "NumericQuestion"]


class Tolerance(MdqModel):
    absolute: float | None = None
    relative: float | None = None




class NumericQuestion(BaseQuestion[t.NumericResponse]):
    #: The correct value. A `str` carries an exact rational ("1/3"),
    #: which no float can represent.
    answer: float | str
    type: Literal["numeric"] = "numeric"
    unit: str | None = None
    domain: NumericDomain | None = None
    decimal_places: int | None = Field(default=None, ge=0)
    tolerance: Tolerance | None = None

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

def numeric_value(value: float | int | str | Fraction) -> float:
    """
    Convert a numeric value to a float.

    Args:
        value: a number, or a decimal/rational string (e.g. "3.14", "1/3").

    Raises:
        ValueError: `value` isn't a valid number.
    """
    if isinstance(value, str):
        value = Fraction(value)
    return float(value)


def numeric_matches(
    answer: float | str, response: t.NumericResponse, tolerance: Tolerance | None
) -> bool:
    """
    Report whether `response` is within `answer`'s tolerance.

    With neither tolerance set, the match must be exact. With both set,
    either one passing is enough.

    Raises:
        ResponseError: `response` isn't a valid number.
    """
    try:
        target = numeric_value(answer)
        value = numeric_value(response)
    except (ValueError, ZeroDivisionError) as exc:
        raise ResponseError(f"{response!r} is not a valid numeric response") from exc

    if tolerance is None or (tolerance.absolute is None and tolerance.relative is None):
        return value == target
    if tolerance.absolute is not None and abs(value - target) <= tolerance.absolute:
        return True
    if (
        tolerance.relative is not None
        and abs(value - target) <= abs(target) * tolerance.relative
    ):
        return True
    return False


def render_numeric_tag(
    answer: float | str,
    *,
    tag: str = "[numeric]",
    unit: str | None = None,
    tolerance: Tolerance | None = None,
) -> str:
    """Return a numeric answer tag in the parser's accepted syntax."""
    if unit is not None:
        tag = f"{tag[:-1]}({unit})]"

    terms = [str(answer)]
    if tolerance is not None:
        if tolerance.absolute is not None:
            terms.append(f"+- {tolerance.absolute}")
        if tolerance.relative is not None:
            terms.append(f"+- {tolerance.relative * 100}%")
    return f"{tag}: {' '.join(terms)}"



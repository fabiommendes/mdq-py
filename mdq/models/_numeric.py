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
from typing import Annotated, Any, Iterable, Iterator, Literal, Self, TypeGuard

from pydantic import AfterValidator, Field, StrictFloat, StrictInt, field_validator, model_validator
from pydantic_core import PydanticCustomError

from .. import _parser, types as t
from .._diagnostics import Diagnostic
from .._markdown import UNICODE_SPACE, has_visible_character
from ..errors import ParseError, ResponseError
from ..types import NumericDomain
from ._base import BaseQuestion, FreeText, MdqModel
from ._lint_codes import diag
from ._score import QuestionScore

__all__ = ["Tolerance", "NumericKey", "NumericQuestion"]

#: The `UNIT` terminal of docs/references/grammar.md: non-empty, no
#: `UNICODE_SPACE`, no parentheses or brackets. Mirrors the `unit`
#: pattern in `schema/numeric.yaml`.
_UNIT_PATTERN = rf"^[^()\[\]{UNICODE_SPACE}]+$"


def _validate_unit(value: str) -> str:
    """numeric.md, "Unit conversion": a unit needs a visible character."""
    if not has_visible_character(value):
        raise PydanticCustomError(
            "blank-text",
            "'unit' is defined but has no visible characters",
        )
    return value


#: A unit: the schema pattern plus at least one visible character
#: (`blank-text`).
Unit = Annotated[str, Field(pattern=_UNIT_PATTERN), AfterValidator(_validate_unit)]

#: numeric.md, "Answer representation": a number, or a string in the
#: `sign? numeric_value` grammar that keeps a value no float holds exactly
#: ("1/3", "2.50", "3000000000"). Strict, so an `int` stays an `int`
#: (it is not widened to a `float`) and a `bool` is not a number.
NumericAnswer = StrictInt | StrictFloat | str


def _validate_numeric_answer(value: NumericAnswer) -> NumericAnswer:
    """
    numeric.md, "Answer representation": a string `answer` MUST be a
    valid `sign? numeric_value` (an `INTEGER` or `DECIMAL` with an optional
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


def check_decimal_places_given(
    answer: NumericAnswer,
    domain: NumericDomain | None,
    decimal_places: int | None,
    tolerance: Tolerance | None,
) -> None:
    """
    numeric.md, "Decimal places": a fraction answer has no decimal places
    of its own. When the domain is `decimal` and `decimal_places` is not
    given, the absolute tolerance must give them: a missing tolerance, or
    one with 0 places, gives none.

    Raises:
        PydanticCustomError: `missing-decimal-places`.
    """
    if (
        decimal_places is None
        and is_fraction_answer(answer)
        and effective_numeric_domain(answer, domain, tolerance) == "decimal"
        and infer_decimal_places(answer, tolerance) == 0
    ):
        raise PydanticCustomError(
            "missing-decimal-places",
            f"the answer {answer!r} is a fraction in a decimal domain, and "
            f"nothing gives its decimal places; declare 'decimalPlaces' or "
            f"a decimal absolute tolerance",
        )


class Tolerance(MdqModel):
    """A distance from the answer, so neither bound is negative (schema)."""

    absolute: Annotated[float, Field(ge=0)] | None = None
    relative: Annotated[float, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def check_not_empty(self) -> Self:
        """numeric.md, "Tolerances": a tolerance has at least one field."""
        if self.absolute is None and self.relative is None:
            raise PydanticCustomError(
                "schema-error", "a tolerance must have 'absolute' or 'relative'"
            )
        return self

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



class NumericKey(MdqModel):
    """
    The answer key of a numeric question or of a numeric fill-in blank:
    the answer and everything that decides which responses match it.
    """

    #: The correct value. See `NumericAnswer`.
    answer: NumericAnswer
    #: Redeclared by each subclass with its `Literal`; declared here so the
    #: field keeps its place in the serialization order.
    type: str
    unit: Unit | None = None
    domain: NumericDomain | None = None
    decimal_places: int | None = Field(default=None, ge=0)
    tolerance: Tolerance | None = None

    #: Feedback for an incorrect response (numeric.md, "Feedback").
    incorrect_feedback: FreeText | None = None

    @field_validator("answer")
    @classmethod
    def check_answer_grammar(cls, value: NumericAnswer) -> NumericAnswer:
        return _validate_numeric_answer(value)

    @model_validator(mode="after")
    def check_decimal_places(self) -> Self:
        """numeric.md, "Decimal places" (`missing-decimal-places`)."""
        check_decimal_places_given(
            self.answer, self.domain, self.decimal_places, self.tolerance
        )
        return self

    @property
    def effective_domain(self) -> NumericDomain:
        """
        The declared `domain`, else the one inferred from `answer` and the
        absolute tolerance (numeric.md, "Number type/domain").
        """
        return effective_numeric_domain(self.answer, self.domain, self.tolerance)

    @property
    def effective_decimal_places(self) -> int | None:
        """
        The precision of the comparison (numeric.md, "Decimal places"):
        `decimal_places` when given; else, for a `decimal` domain
        (declared or inferred), `infer_decimal_places`; else None.
        """
        if self.decimal_places is not None:
            return self.decimal_places
        if self.effective_domain == "decimal":
            return infer_decimal_places(self.answer, self.tolerance)
        return None

    def lint_key(self, path: tuple[str | int, ...]) -> list[Diagnostic]:
        """Lint the key, which sits at `path` of the document."""
        return list(
            check_numeric(
                answer=self.answer,
                domain=self.domain,
                decimal_places=self.decimal_places,
                tolerance=self.tolerance,
                path=path,
            )
        )

    def score_numeric(self, response: t.NumericResponse) -> QuestionScore:
        """
        Score 1 if `response`, rounded to `effective_decimal_places`, is
        within tolerance of `answer`, else 0. An incorrect response gets
        `incorrect_feedback`, if set (numeric.md, "Feedback").

        Raises:
            ResponseError: `response` isn't a valid number, is a value the
                domain cannot represent, or has a unit other than the
                key's (responses.md, "Numeric").
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


class NumericQuestion(NumericKey, BaseQuestion[t.NumericResponse]):
    type: Literal["numeric"] = "numeric"

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(self.lint_key(()))
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

    def _parse_response(self, response: object) -> t.NumericResponse:
        """
        Raises:
            ResponseError: `response` is not a number, a numeric string or
                a `{value, unit}` mapping.
        """
        if not is_numeric_response(response):
            raise ResponseError(f"{response!r} is not a valid numeric response")
        return response

    def _score(self, response: t.NumericResponse) -> QuestionScore:
        """See `NumericKey.score_numeric`."""
        return self.score_numeric(response)


#
# Utilities
#

def is_numeric_response(response: object) -> TypeGuard[t.NumericResponse]:
    """
    Whether `response` has the shape of a numeric response (responses.md,
    "Numeric"). Its value, domain and unit are checked while scoring.
    """
    return isinstance(response, int | float | Fraction | str | Mapping)


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
    A fraction answer has no places of its own: only the tolerance gives
    them, and 0 when it gives none (`missing-decimal-places` reports it).
    """
    places = 0 if is_fraction_answer(answer) else _written_places(answer)
    if tolerance is not None and tolerance.absolute is not None:
        places = max(places, _written_places(tolerance.absolute))
    return places


def is_fraction_answer(answer: NumericAnswer) -> bool:
    """Whether `answer` is a fraction string such as `"1/3"`."""
    return isinstance(answer, str) and "/" in answer


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

    if tolerance is None:
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


_DOMAIN_RANK: dict[str, int] = {"integer": 0, "fraction": 1, "decimal": 2}


def effective_numeric_domain(
    answer: int | float | str,
    domain: NumericDomain | None,
    tolerance: Tolerance | None,
) -> "NumericDomain":
    """
    The declared `domain`, else the one inferred from the answer and the
    absolute tolerance (numeric.md, "Number type/domain": the wider of
    the two).
    """
    if domain is not None:
        return domain
    inferred = infer_numeric_domain(answer)
    if tolerance is not None and tolerance.absolute is not None:
        tolerance_domain = infer_numeric_domain(tolerance.absolute)
        if _DOMAIN_RANK[tolerance_domain] > _DOMAIN_RANK[inferred]:
            return tolerance_domain
    return inferred


def infer_numeric_domain(answer: int | float | str) -> "NumericDomain":
    """
    numeric.md, "Number type/domain": infer the domain an `answer` is
    written in, ranking integer < fraction < decimal. A `str` answer
    holds a `/` (a fraction) or a `.` or an exponent (a decimal) or
    neither (an integer); a number is an integer when it has no fractional part,
    decimal otherwise. The parser keeps a whole decimal such as `2.0`
    as a string, so a whole number here was not written as a decimal
    in Markdown.
    """
    if isinstance(answer, str):
        text = answer.strip()
        if "/" in text:
            return "fraction"
        if "." in text or "e" in text or "E" in text:
            return "decimal"
        return "integer"
    return "integer" if float(answer) == int(answer) else "decimal"


def check_numeric(
    *,
    answer: int | float | str,
    domain: NumericDomain | None,
    decimal_places: int | None,
    tolerance: Tolerance | None,
    path: tuple[str | int, ...],
) -> Iterator[Diagnostic]:
    """
    numeric.md: the domain is inferred from the answer's representation
    when not declared, so a declared domain that contradicts the answer
    is a mistake; and a relative tolerance around zero can never widen
    the accepted range.
    """
    effective_domain = effective_numeric_domain(answer, domain, tolerance)
    # A string answer is already grammar-validated, so `Fraction` accepts it.
    value: Fraction | float = Fraction(answer) if isinstance(answer, str) else answer
    # numeric.md, "Additional Rules": under `integer` the answer must be
    # whole; under `fraction` it must be whole or a fraction string.
    is_fraction_string = isinstance(answer, str) and "/" in answer
    if (domain == "integer" or (domain == "fraction" and not is_fraction_string)) and (
        value != int(value)
    ):
        yield diag(
            code="answer-outside-domain",
            path=path + ("answer",),
            message=(
                f"domain is {domain!r} but the answer {answer!r} is not "
                + (
                    "a whole number"
                    if domain == "integer"
                    else "a whole number or a fraction"
                )
            ),
        )

    if (
        domain in ("integer", "fraction")
        and tolerance is not None
        and tolerance.absolute is not None
        and infer_numeric_domain(tolerance.absolute) == "decimal"
    ):
        yield diag(
            code="domain-mismatch",
            path=path + ("domain",),
            message=(
                f"domain is {domain!r}, but the absolute tolerance "
                f"{tolerance.absolute!r} is a decimal"
            ),
        )

    if tolerance is None and effective_domain == "decimal":
        yield diag(
            code="missing-tolerance",
            path=path + ("tolerance",),
            message=(
                f"the answer {answer!r} is in a decimal domain, but "
                f"no tolerance is given; an exact comparison rarely "
                f"matches a typed response"
            ),
        )

    if tolerance is not None:
        relative = tolerance.relative
        if relative is not None and relative > 0 and value == 0:
            yield diag(
                code="relative-tolerance-around-zero",
                path=path + ("tolerance", "relative"),
                message=(
                    "a relative tolerance is computed as answer x "
                    "relative, which is 0 when the answer is 0; only an "
                    "exact 0 would be accepted"
                ),
            )

        if relative is not None and relative > 1:
            yield diag(
                code="relative-tolerance-over-one",
                path=path + ("tolerance", "relative"),
                message=(
                    f"a relative tolerance of {relative!r} is "
                    f"{relative * 100:g}%: a tolerance above 100% accepts "
                    f"responses of the opposite sign to the answer"
                ),
            )

    if decimal_places is not None and effective_domain != "decimal":
        source = "" if domain is not None else " (inferred from the answer)"
        yield diag(
            code="ignored-decimal-places",
            path=path + ("decimalPlaces",),
            message=(
                f"'decimalPlaces' is ignored when domain is "
                f"{effective_domain!r}{source}"
            ),
        )

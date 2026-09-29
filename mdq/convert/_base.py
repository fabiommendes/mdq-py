from __future__ import annotations

import importlib
from decimal import Decimal
from fractions import Fraction
from typing import Any, ClassVar, Literal

from .. import _parser
from ..errors import ParseError
from ..models import Question, Tolerance
from ..types import QuestionType

#: Every format `mdq.convert` can import from and export to.
FORMATS: tuple[str, ...] = ("aiken", "gift", "moodle-xml")

#: A format name maps to its converter, either already instantiated or as
#: a lazy `"module:ClassName"` reference -- `load_converter` imports it on
#: first use, so importing `mdq.convert` never imports every converter.
CONVERSION_REGISTRY: dict[str, "ConversionBase | str"] = {
    "aiken": "mdq.convert._aiken:Aiken",
    "gift": "mdq.convert._gift:Gift",
    "moodle-xml": "mdq.convert._moodle_xml:MoodleXml",
}


#: The stem of a true/false question built from a group of statements that
#: share no leading paragraph. MDQ requires a stem with a visible character
#: (docs/question-types/base.md, "Additional Rules").
TRUE_FALSE_FALLBACK_STEM = "Mark each statement as true or false."


def mdq_numeric_answer(text: str) -> int | float | str:
    """
    Return a numeric `answer` for the number an external format wrote as
    `text`, in the representation the Markdown parser would give it
    (numeric.md, "Answer representation"): `"42"` is `42`, `"2.50"` is
    `"2.50"`. Text outside MDQ's grammar (`"1e-5"`) becomes a `float`.

    Raises:
        ValueError: `text` is not a number at all.
    """
    try:
        return _parser.parse_numeric_answer(text)
    except ParseError:
        return float(text)


_MOODLE_POSITIVE_GRADES = tuple(
    Fraction(p, q)
    for p, q in [
        (1, 1), (9, 10), (5, 6), (4, 5), (3, 4), (7, 10), (2, 3), (3, 5),
        (1, 2), (2, 5), (1, 3), (3, 10), (1, 4), (1, 5), (1, 6), (1, 7),
        (1, 8), (1, 9), (1, 10), (1, 20),
    ]
)

#: The grades Moodle accepts for an answer, from -1 to 1:
#: `question_bank::fraction_options_full()` in question/engine/bank.php.
#: The Moodle XML and GIFT importers reject a question with any other
#: grade (or, if asked to, move it to the nearest one). Embedded answers
#: (Cloze) do not check their grades against this list.
MOODLE_GRADES: tuple[Fraction, ...] = (
    (Fraction(0),) + _MOODLE_POSITIVE_GRADES + tuple(-g for g in _MOODLE_POSITIVE_GRADES)
)

#: How far a grade may be from a listed one and still match it, as a
#: fraction of full credit: `match_grade_options` in lib/questionlib.php.
MOODLE_GRADE_TOLERANCE = 0.00001


def moodle_grade(score: float) -> Fraction | None:
    """The grade in `MOODLE_GRADES` that `score` (a fraction of full credit) matches, if any."""
    for grade in MOODLE_GRADES:
        if abs(score - grade) < MOODLE_GRADE_TOLERANCE:
            return grade
    return None


def moodle_score(score: float, *, format: str) -> float:
    """
    Return the exact grade in `MOODLE_GRADES` that `score` (a fraction
    of full credit) matches.

    Raises:
        ValueError: `score` is not one of `MOODLE_GRADES`, so Moodle
            would reject the question or change the score.
    """
    grade = moodle_grade(score)
    if grade is None:
        percents = ", ".join(format_moodle_percent(g) for g in _MOODLE_POSITIVE_GRADES)
        raise ValueError(
            f"cannot convert to {format}: the score {score!r} is not a grade "
            f"Moodle accepts ({percents}, 0, or a negative of these, in percent)"
        )
    return float(grade)


def moodle_percent(score: float, *, format: str) -> float:
    """
    Return the percentage Moodle writes for the grade `score`: 5/6 is
    `83.33333`, 1/7 is `14.28571`.

    Raises:
        ValueError: see `moodle_score`.
    """
    grade = moodle_grade(moodle_score(score, format=format))
    assert grade is not None
    return float(format_moodle_percent(grade))


def format_moodle_percent(grade: Fraction) -> str:
    """`grade` in percent, rounded to 5 decimal places like Moodle does."""
    percent = round(Decimal(grade.numerator * 100) / Decimal(grade.denominator), 5)
    return format(percent.normalize(), "f")


def score_from_moodle_percent(percent: float) -> float:
    """
    Return the score for a Moodle percentage. A percentage that matches
    a listed grade becomes that exact grade (`83.33333` is 5/6); any
    other is kept as written.
    """
    score = percent / 100
    grade = moodle_grade(score)
    return score if grade is None else float(grade)


def float_answer(
    answer: int | float | str, tolerance: Tolerance | None, *, format: str
) -> float:
    """
    Return a numeric answer as the float an external format stores.

    Raises:
        ValueError: the float is not the exact answer ("1/3") and there is
            no tolerance, so the external format would compare responses
            with a different number than MDQ does.
    """
    if isinstance(answer, float):
        return answer
    number = float(Fraction(answer))
    has_tolerance = tolerance is not None and bool(tolerance.absolute or tolerance.relative)
    if not has_tolerance and Fraction(repr(number)) != Fraction(answer):
        raise ValueError(
            f"cannot convert to {format}: the answer {answer!r} has no exact "
            f"floating-point value, and without a tolerance {format} would "
            f"only accept {number!r}"
        )
    return number


class ConversionBase[Q]:
    """
    Base class for conversion types.
    """

    supports: ClassVar[dict[QuestionType, Literal["import", "export", "both"]]]

    def to_mdq(self, external: Q, /) -> Question:
        """
        Import question to a MDQ representation.
        """
        raise NotImplementedError

    def from_mdq(self, mdq: Question, /) -> Q:
        """
        Convert MDQ question to the external question format
        """
        raise NotImplementedError

    def render(self, external: Q, /) -> str:
        """
        Render the external format as a string.
        """
        return str(external)

    def parse(self, source: str, /) -> Q:
        """
        Parse source code in the external format into the internal
        representation.
        """
        raise NotImplementedError


def load_converter(format: str) -> ConversionBase[Any]:
    """
    Load a conversion instance from the registry.
    """
    format = format.lower()
    try:
        converter = CONVERSION_REGISTRY[format]
    except KeyError:
        raise ValueError(f"Unknown format: {format}")

    if isinstance(converter, str):
        mod_name, cls_name = converter.split(":")
        mod = importlib.import_module(mod_name)
        converter_cls = getattr(mod, cls_name)
        if not (
            isinstance(converter_cls, type) and issubclass(converter_cls, ConversionBase)
        ):
            msg = f"invalid registry: {format} is not a valid converter"
            raise RuntimeError(msg)
        converter = converter_cls()
        CONVERSION_REGISTRY[format] = converter

    return converter


def import_question(source: str, /, *, format: str) -> Question:
    """
    Load a question in the given format from source.

    Args:
        source: Source code from the external question.
        format: The external question format.
    """

    converter = load_converter(format)
    external = converter.parse(source)
    return converter.to_mdq(external)


def export_question(question: Question, /, *, format: str):
    """
    Convert a mdq question to a different format.

    Renders the resulting source code.

    Args:
        source: Source code from the external question.
        format: The external question format.
    """
    converter = load_converter(format)
    if question.type not in converter.supports:
        msg = f"{format!r} does not support {question.type!r} questions"
        raise TypeError(msg)
    external = converter.from_mdq(question)
    return converter.render(external)

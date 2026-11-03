"""
The Moodle question model, shared by GIFT, Moodle XML and Aiken: grades,
true or false groups, answer keys, general feedback and tolerances.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from .. import _parser
from .._exact import exact_literal, exact_span
from .._markdown import has_visible_character, starts_block
from ..errors import ParseError
from ..models import (
    AnswerPattern,
    ChoiceBlank,
    MultipleChoiceQuestion,
    Question,
    ShortAnswerQuestion,
    Tolerance,
    TrueFalseQuestion,
)
from ._base import Report
from ._common import common_prefix, format_num, join_blocks

#: The stem of a true or false question built from a group of statements that
#: share no leading paragraph. MDQ requires a stem with a visible character
#: (docs/question-types/base.md, "Additional Rules").
TRUE_FALSE_FALLBACK_STEM = "Mark each statement as true or false."


def true_false_group_stem(question: TrueFalseQuestion) -> str:
    """
    The text every statement of an exported true or false group starts with:
    the question stem, plus the epilogue. The fallback stem stands for "no
    shared text", so it round-trips.
    """
    stem = None if question.stem == TRUE_FALSE_FALLBACK_STEM else question.stem
    return join_blocks(stem, question.epilogue)


def split_true_false_group(texts: list[str]) -> tuple[str, list[str]]:
    """
    Split the texts of an imported true or false group into the shared stem
    and the statements: the stem is what comes before the last blank line of
    the common prefix. Without one, the stem is `TRUE_FALSE_FALLBACK_STEM`.
    """
    prefix = common_prefix(texts)
    split = prefix.rfind("\n\n")
    if split == -1:
        return TRUE_FALSE_FALLBACK_STEM, texts
    boundary = split + 2
    return prefix[:split].strip(), [text[boundary:] for text in texts]


def absolute_tolerance(absolute: float | None) -> Tolerance | None:
    """The `Tolerance` for an imported absolute tolerance, `None` if there is none (or zero)."""
    return Tolerance(absolute=absolute) if absolute else None


def blank_choice_scores(blank: ChoiceBlank) -> list[float]:
    """
    The score of each choice in a blank. An unmarked choice inside a blank
    keeps `score = None`, which MDQ reads as zero credit; only top-level
    choices are strict.
    """
    return [choice.score or 0.0 for choice in blank.choices]


def mdq_numeric_answer(text: str, report: Report) -> int | float | str:
    """
    Return a numeric `answer` for the number an external format wrote as
    `text`, in the representation the Markdown parser would give it
    (numeric.md, "Answer representation"): `"42"` is `42`, `"2.50"` is
    `"2.50"`. Text outside MDQ's grammar (`"1e-5"`) becomes a `float`.

    Raises:
        ConversionError: `text` is not a number at all.
    """
    try:
        return _parser.parse_numeric_answer(text)
    except ParseError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    report.error("not-a-number", f"cannot convert: the numeric answer {text!r} is not a number")


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


def effective_scores(question: MultipleChoiceQuestion) -> list[float]:
    """
    The score each choice is graded with: its own `score`, or the one the
    grading strategy gives a choice that declares none
    (multiple-choice.md, "Grading"). A format that stores a grade per
    choice exports this, since it is what the student gets.
    """
    unspecified = question.unspecified_score()
    return [c.score if c.score is not None else unspecified for c in question.choices]


def moodle_score(score: float, report: Report) -> float:
    """
    Return the exact grade in `MOODLE_GRADES` that `score` (a fraction
    of full credit) matches.

    Raises:
        ConversionError: `score` is not one of `MOODLE_GRADES`, so Moodle
            would reject the question or change the score.
    """
    grade = moodle_grade(score)
    if grade is None:
        percents = ", ".join(format_moodle_percent(g) for g in _MOODLE_POSITIVE_GRADES)
        report.error(
            "score-rounded",
            f"cannot convert to {report.format}: the score {score!r} is not a grade "
            f"Moodle accepts ({percents}, 0, or a negative of these, in percent)"
        )
    return float(grade)


def moodle_percent(score: float, report: Report) -> float:
    """
    Return the percentage Moodle writes for the grade `score`: 5/6 is
    `83.33333`, 1/7 is `14.28571`.

    Raises:
        ConversionError: see `moodle_score`.
    """
    grade = moodle_grade(moodle_score(score, report))
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
    answer: int | float | str, tolerance: Tolerance | None, report: Report
) -> float:
    """
    Return a numeric answer as the float an external format stores.

    Raises:
        ConversionError: the float is not the exact answer ("1/3") and there is
            no tolerance, so the external format would compare responses
            with a different number than MDQ does.
    """
    if isinstance(answer, float):
        return answer
    number = float(Fraction(answer))
    has_tolerance = tolerance is not None and bool(tolerance.absolute or tolerance.relative)
    if not has_tolerance and Fraction(repr(number)) != Fraction(answer):
        report.error(
            "inexact-answer",
            f"cannot convert to {report.format}: the answer {answer!r} has no exact "
            f"floating-point value, and without a tolerance {report.format} would "
            f"only accept {number!r}"
        )
    return number


def require_automatic(question: ShortAnswerQuestion, report: Report) -> None:
    """
    Raise if `question` leaves some responses to the instructor: external
    formats grade every response themselves and cannot express a pending one.

    Raises:
        ConversionError: the question is not `automatic`.
    """
    if question.automation != "automatic":
        report.error(
            "manual-grading-dropped",
            f"cannot convert to {report.format}: the question has `unmatched` "
            "manual (no accept pattern, or declared), and the format cannot "
            "leave a response for the instructor to grade"
        )


@dataclass(frozen=True)
class ExportedAnswer:
    """One literal answer of a short answer, as an external format stores it."""

    text: str
    #: `1.0` for an `accept` pattern, `0.0` for a `reject` pattern.
    credit: float
    feedback: str | None = None


def literal_text(rule: AnswerPattern, report: Report) -> str:
    r"""
    Return the text an external format stores for a literal pattern: a plain
    literal as it is, a backtick-enclosed literal without its backticks.

    Every `*` is escaped with a backslash, which Moodle reads as a literal
    asterisk, so a lone `*` is not Moodle's "any other answer". A backslash
    before a `*` is kept: Moodle stores `2\\*3` and matches the literal `2\*3`.

    Raises:
        ConversionError: `rule` is a regex, which an external format cannot express.
    """
    pattern = rule.pattern.strip(" \t\r\n")
    if pattern.startswith("/"):
        report.error(
            "regex-dropped",
            f"cannot convert to {report.format}: the pattern {pattern!r} is a "
            "regex, and only literal answers are supported"
        )
    content = exact_literal(pattern)
    text = pattern if content is None else content
    return text.replace("*", "\\*")


def literal_answers(accept: list[AnswerPattern] | None, report: Report) -> list[str]:
    """
    Return the texts an external format stores for a short answer's
    `accept` list (see `literal_text`).

    Raises:
        ConversionError: `accept` is missing or empty, or holds a regex, which
            an external format cannot express.
    """
    if not accept:
        report.error(
            "no-accept",
            f"cannot convert to {report.format}: a short answer needs an `accept` list"
        )
    return [literal_text(rule, report) for rule in accept]


def exported_short_answers(
    accept: list[AnswerPattern] | None,
    reject: list[AnswerPattern] | None,
    report: Report,
) -> list[ExportedAnswer]:
    """
    Return the answers an external format stores for a short answer: each
    `accept` literal worth full credit, then each `reject` literal worth
    none, all with their feedback.

    Raises:
        ConversionError: `accept` is missing or empty, or a pattern is a regex.
    """
    literal_answers(accept, report)
    return [
        ExportedAnswer(literal_text(rule, report), credit, rule.feedback)
        for credit, rules in ((1.0, accept), (0.0, reject))
        for rule in rules or []
    ]


#: A line ending and the indentation of the next line, which a pattern string
#: replaces with one space (patterns.md, "Continuation lines").
_LINE_BREAK_RE = re.compile(r"(?:\r\n|\r|\n)[ \t]*")


def literal_pattern(text: str) -> AnswerPattern:
    """
    Return the `accept` entry for an answer an external format wrote as
    `text`. A text the pattern mini-language would read as something else
    (a regex, a backtick span or the start of a markdown block such as `*`,
    `# x` or `> x`) is enclosed in backticks.

    A pattern string has no line ending, so each line ending in `text`,
    with the indentation of the next line, becomes one space, as in the
    continuation lines of a body block.
    """
    stripped = text.strip(" \t\r\n")
    multiline = _LINE_BREAK_RE.search(stripped) is not None
    if multiline:
        stripped = _LINE_BREAK_RE.sub(" ", stripped)
    if stripped.startswith(("/", "`")) or starts_block(stripped):
        return AnswerPattern(pattern=exact_span(stripped))
    return AnswerPattern(pattern=stripped if multiline else text)


#: The `meta` key that holds the general feedback of an imported question
#: (GIFT `####`, Moodle `<generalfeedback>`). It is defined by the
#: converters, not by the MDQ specification.
GENERAL_FEEDBACK_KEY = "generalFeedback"

def general_feedback_meta(*feedbacks: str | None) -> dict[str, object] | None:
    """
    Return the `meta` of an imported question that carries `feedbacks`, the
    general feedback of the question (of each statement, for a true or false
    group: the distinct ones are joined by a blank line). `None` if all are
    empty.
    """
    texts = list(
        dict.fromkeys(f.strip() for f in feedbacks if f and has_visible_character(f))
    )
    return {GENERAL_FEEDBACK_KEY: "\n\n".join(texts)} if texts else None


def exported_general_feedback(question: Question, report: Report) -> str | None:
    """
    Return the general feedback to write for `question`: `meta.generalFeedback`,
    or `None` if the question has none.

    Raises:
        ConversionError: the value is not a string with a visible character.
    """
    if not question.meta or GENERAL_FEEDBACK_KEY not in question.meta:
        return None
    value = question.meta[GENERAL_FEEDBACK_KEY]
    if not isinstance(value, str) or not has_visible_character(value):
        report.error(
            "general-feedback-dropped",
            f"cannot convert to {report.format}: `meta.{GENERAL_FEEDBACK_KEY}` must be "
            f"a string with a visible character, got {value!r}"
        )
    return value


@dataclass(frozen=True)
class ImportedAnswer:
    """One answer of an external short answer or numeric question."""

    text: str
    #: The fraction of full credit: `1.0` is 100%.
    credit: float
    feedback: str | None = None
    #: Absolute tolerance, numeric answers only.
    tolerance: float | None = None


@dataclass(frozen=True)
class ShortAnswerKey:
    """The `accept`, `reject` and `incorrectFeedback` of an imported short answer."""

    accept: list[AnswerPattern]
    reject: list[AnswerPattern] | None
    incorrect_feedback: str | None


@dataclass(frozen=True)
class NumericAnswerKey:
    """The `answer`, `tolerance` and `incorrectFeedback` of an imported numeric answer."""

    answer: int | float | str
    tolerance: Tolerance | None
    incorrect_feedback: str | None


def _credit_kind(answer: ImportedAnswer, report: Report, what: str) -> Literal["full", "none"]:
    """
    Classify the credit of `answer` as full (100%) or none (0%).

    Raises:
        ConversionError: the credit is partial (or negative): the grading of
            `what` is binary.
    """
    if abs(answer.credit - 1) < MOODLE_GRADE_TOLERANCE:
        return "full"
    if abs(answer.credit) < MOODLE_GRADE_TOLERANCE:
        return "none"
    report.error(
        "partial-credit-dropped",
        f"cannot convert from {report.format}: the answer {answer.text!r} has partial "
        f"credit ({format_num(answer.credit * 100)}%), and {what} grading is "
        "binary: an answer is worth 100% or 0%"
    )


#: An asterisk without a backslash before it: a wildcard in Moodle.
_WILDCARD_RE = re.compile(r"(?<!\\)\*")


def _is_wildcard(text: str) -> bool:
    """Whether `text` is Moodle's lone `*` ("any other answer")."""
    return text.strip(" \t\r\n") == "*"


def short_answer_key(
    answers: Sequence[ImportedAnswer], report: Report, any_answer: bool = False
) -> ShortAnswerKey:
    """
    Split the answers of an imported short answer by credit: 100% is
    `accept`, 0% is `reject` (both with their feedback). With `any_answer`, a
    lone `*` is Moodle's "any other answer": at 100% it is the regex `/.*/`,
    at 0% its feedback is the `incorrectFeedback`. Without it, a lone `*` is
    a literal like any other text.

    Raises:
        ConversionError: an answer has partial credit, or a `*` wildcard inside
            its text, which MDQ patterns would read as a literal `*`.
    """
    accept: list[AnswerPattern] = []
    reject: list[AnswerPattern] = []
    incorrect_feedback: str | None = None
    for answer in answers:
        kind = _credit_kind(answer, report, what="short-answer")
        if any_answer and _is_wildcard(answer.text):
            if kind == "full":
                accept.append(AnswerPattern(pattern="/.*/", feedback=answer.feedback))
            elif answer.feedback:
                incorrect_feedback = answer.feedback
            continue
        if not _is_wildcard(answer.text) and _WILDCARD_RE.search(answer.text):
            report.error(
                "wildcard-to-regex",
                f"cannot convert from {report.format}: the answer {answer.text!r} has a "
                "`*` wildcard, which MDQ literal patterns do not support"
            )
        literal = literal_pattern(answer.text.replace("\\*", "*"))
        entry = AnswerPattern(pattern=literal.pattern, feedback=answer.feedback)
        (accept if kind == "full" else reject).append(entry)
    return ShortAnswerKey(accept, reject or None, incorrect_feedback)


def numeric_answer_key(answers: Sequence[ImportedAnswer], report: Report) -> NumericAnswerKey:
    """
    Pick the numeric key among the imported answers: the answer worth 100%.
    A 0% answer is dropped, except a lone `*` ("any other answer") with
    feedback, which is the `incorrectFeedback`. A second 100% answer is
    dropped if it has the same value and tolerance as the first.

    Raises:
        ConversionError: an answer has partial credit, there is no 100% answer or
            two different ones, or a `*` has credit.
    """
    key: ImportedAnswer | None = None
    incorrect_feedback: str | None = None
    for answer in answers:
        kind = _credit_kind(answer, report, what="numeric")
        if _is_wildcard(answer.text):
            if kind == "full":
                report.error(
                    "answer-dropped",
                    f"cannot convert from {report.format}: a numeric `*` answer worth "
                    "100% accepts any number, which MDQ cannot express"
                )
            if answer.feedback:
                incorrect_feedback = answer.feedback
        elif kind == "full":
            if key is None:
                key = answer
            elif (float(key.text), key.tolerance or 0.0) != (
                float(answer.text),
                answer.tolerance or 0.0,
            ):
                report.error(
                    "answer-dropped",
                    f"cannot convert from {report.format}: more than one different "
                    "answer is worth 100%, and a numeric question has one answer"
                )
    if key is None:
        report.error(
            "no-full-credit",
            f"cannot convert from {report.format}: no numeric answer is worth full credit"
        )
    return NumericAnswerKey(
        mdq_numeric_answer(key.text, report), absolute_tolerance(key.tolerance), incorrect_feedback
    )

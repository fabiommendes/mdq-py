from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any, ClassVar, Literal

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
from ..types import QuestionType
from ._common import common_prefix, format_num, join_blocks

type Format = Literal["aiken", "gift", "moodle-xml"]

#: Every format `mdq.convert` can import from and export to.
FORMATS: tuple[Format, ...] = ("aiken", "gift", "moodle-xml")


#: The stem of a true/false question built from a group of statements that
#: share no leading paragraph. MDQ requires a stem with a visible character
#: (docs/question-types/base.md, "Additional Rules").
TRUE_FALSE_FALLBACK_STEM = "Mark each statement as true or false."


def true_false_group_stem(question: TrueFalseQuestion) -> str:
    """
    The text every statement of an exported true/false group starts with:
    the question stem, plus the epilogue. The fallback stem stands for "no
    shared text", so it round-trips.
    """
    stem = None if question.stem == TRUE_FALSE_FALLBACK_STEM else question.stem
    return join_blocks(stem, question.epilogue)


def split_true_false_group(texts: list[str]) -> tuple[str, list[str]]:
    """
    Split the texts of an imported true/false group into the shared stem
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


def effective_scores(question: MultipleChoiceQuestion) -> list[float]:
    """
    The score each choice is graded with: its own `score`, or the one the
    grading strategy gives a choice that declares none
    (multiple-choice.md, "Grading"). A format that stores a grade per
    choice exports this, since it is what the student gets.
    """
    unspecified = question.unspecified_score()
    return [c.score if c.score is not None else unspecified for c in question.choices]


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


def require_automatic(question: ShortAnswerQuestion, *, format: str) -> None:
    """
    Raise if `question` leaves some responses to the instructor: external
    formats grade every response themselves and cannot express a pending one.

    Raises:
        ValueError: the question is not `automatic`.
    """
    if question.automation != "automatic":
        raise ValueError(
            f"cannot convert to {format}: the question has `unmatched` "
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


def literal_text(rule: AnswerPattern, *, format: str) -> str:
    """
    Return the text an external format stores for a literal pattern: a plain
    literal as it is, a backtick-enclosed literal without its backticks.

    Raises:
        ValueError: `rule` is a regex, or a literal with a `*` inside its text,
            which Moodle reads as a wildcard: an external format cannot express them.
    """
    pattern = rule.pattern.strip(" \t\r\n")
    if pattern.startswith("/"):
        raise ValueError(
            f"cannot convert to {format}: the pattern {pattern!r} is a "
            "regex, and only literal answers are supported"
        )
    content = exact_literal(pattern)
    text = pattern if content is None else content
    if "*" in text and text.strip(" \t\r\n") != "*":
        raise ValueError(
            f"cannot convert to {format}: the literal {text!r} has a `*`, "
            f"which {format} reads as a wildcard"
        )
    return text


def literal_answers(accept: list[AnswerPattern] | None, *, format: str) -> list[str]:
    """
    Return the texts an external format stores for a short answer's
    `accept` list (see `literal_text`).

    Raises:
        ValueError: `accept` is missing or empty, or holds a regex, which
            an external format cannot express.
    """
    if not accept:
        raise ValueError(
            f"cannot convert to {format}: a short answer needs an `accept` list"
        )
    return [literal_text(rule, format=format) for rule in accept]


def exported_short_answers(
    accept: list[AnswerPattern] | None,
    reject: list[AnswerPattern] | None,
    *,
    format: str,
) -> list[ExportedAnswer]:
    """
    Return the answers an external format stores for a short answer: each
    `accept` literal worth full credit, then each `reject` literal worth
    none, all with their feedback.

    Raises:
        ValueError: `accept` is missing or empty, or a pattern is a regex.
    """
    literal_answers(accept, format=format)
    return [
        ExportedAnswer(literal_text(rule, format=format), credit, rule.feedback)
        for credit, rules in ((1.0, accept), (0.0, reject))
        for rule in rules or []
    ]


#: A line ending and the indentation of the next line, which a pattern string
#: replaces with one space (patterns.md, "Continuation lines").
_LINE_BREAK_RE = re.compile(r"(?:\r\n|\r|\n)[ \t]*")


def literal_pattern(text: str, *, format: str) -> AnswerPattern:
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

_PLAIN_FORMATS = frozenset({"plain", "plain_text"})
_MARKDOWN_SPECIALS_RE = re.compile(r"[\\`*_\[\]<>&~]")
#: A character that starts a block at the beginning of a line: `#`, `-`, `1.`, ...
_LINE_START_SPECIAL_RE = re.compile(r"^( {0,3})(?:([#+\-=])|(\d+)([.)]))")


def _escape_line_start(match: re.Match[str]) -> str:
    """Escape the character of a line start that `_LINE_START_SPECIAL_RE` matched."""
    indent, mark, digits, delimiter = match.groups()
    if mark:
        return f"{indent}\\{mark}"
    return f"{indent}{digits}\\{delimiter}"


def plain_text_to_markdown(text: str) -> str:
    r"""
    Return the Markdown that renders as the plain text `text`: the
    punctuation with a Markdown meaning is backslash-escaped (`*`, `_`,
    `[`, `<`, `&`, a leading `#` or `1.`, ...) and each line break inside a
    paragraph becomes a hard break (a trailing backslash).
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    escaped = [_MARKDOWN_SPECIALS_RE.sub(lambda m: "\\" + m.group(), line) for line in lines]
    escaped = [
        _LINE_START_SPECIAL_RE.sub(_escape_line_start, line) for line in escaped
    ]
    for i in range(len(escaped) - 1):
        if lines[i].strip() and lines[i + 1].strip():
            escaped[i] += "\\"
    return "\n".join(escaped)


def mdq_text(text: str, text_format: str) -> str:
    """
    Return the MDQ text for a `text` an external format wrote in
    `text_format`: `plain` and `plain_text` are escaped
    (`plain_text_to_markdown`); `html` (CommonMark carries raw HTML),
    auto-format (`moodle`, `moodle_auto_format`) and `markdown` are copied
    as they are.
    """
    return plain_text_to_markdown(text) if text_format in _PLAIN_FORMATS else text


def general_feedback_meta(*feedbacks: str | None) -> dict[str, object] | None:
    """
    Return the `meta` of an imported question that carries `feedbacks`, the
    general feedback of the question (of each statement, for a true/false
    group: the distinct ones are joined by a blank line). `None` if all are
    empty.
    """
    texts = list(
        dict.fromkeys(f.strip() for f in feedbacks if f and has_visible_character(f))
    )
    return {GENERAL_FEEDBACK_KEY: "\n\n".join(texts)} if texts else None


def exported_general_feedback(question: Question, *, format: str) -> str | None:
    """
    Return the general feedback to write for `question`: `meta.generalFeedback`,
    or `None` if the question has none.

    Raises:
        ValueError: the value is not a string with a visible character.
    """
    if not question.meta or GENERAL_FEEDBACK_KEY not in question.meta:
        return None
    value = question.meta[GENERAL_FEEDBACK_KEY]
    if not isinstance(value, str) or not has_visible_character(value):
        raise ValueError(
            f"cannot convert to {format}: `meta.{GENERAL_FEEDBACK_KEY}` must be "
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


def _credit_kind(answer: ImportedAnswer, *, format: str, what: str) -> Literal["full", "none"]:
    """
    Classify the credit of `answer` as full (100%) or none (0%).

    Raises:
        ValueError: the credit is partial (or negative): the grading of
            `what` is binary.
    """
    if abs(answer.credit - 1) < MOODLE_GRADE_TOLERANCE:
        return "full"
    if abs(answer.credit) < MOODLE_GRADE_TOLERANCE:
        return "none"
    raise ValueError(
        f"cannot convert from {format}: the answer {answer.text!r} has partial "
        f"credit ({format_num(answer.credit * 100)}%), and {what} grading is "
        "binary: an answer is worth 100% or 0%"
    )


def _is_wildcard(text: str) -> bool:
    """Whether `text` is Moodle's lone `*` ("any other answer")."""
    return text.strip(" \t\r\n") == "*"


def short_answer_key(
    answers: Sequence[ImportedAnswer], *, format: str, any_answer: bool = False
) -> ShortAnswerKey:
    """
    Split the answers of an imported short answer by credit: 100% is
    `accept`, 0% is `reject` (both with their feedback). With `any_answer`, a
    lone `*` is Moodle's "any other answer": at 100% it is the regex `/.*/`,
    at 0% its feedback is the `incorrectFeedback`. Without it, a lone `*` is
    a literal like any other text.

    Raises:
        ValueError: an answer has partial credit, or a `*` wildcard inside
            its text, which MDQ patterns would read as a literal `*`.
    """
    accept: list[AnswerPattern] = []
    reject: list[AnswerPattern] = []
    incorrect_feedback: str | None = None
    for answer in answers:
        kind = _credit_kind(answer, format=format, what="short-answer")
        if any_answer and _is_wildcard(answer.text):
            if kind == "full":
                accept.append(AnswerPattern(pattern="/.*/", feedback=answer.feedback))
            elif answer.feedback:
                incorrect_feedback = answer.feedback
            continue
        if "*" in answer.text and not _is_wildcard(answer.text):
            raise ValueError(
                f"cannot convert from {format}: the answer {answer.text!r} has a "
                "`*` wildcard, which MDQ literal patterns do not support"
            )
        literal = literal_pattern(answer.text, format=format)
        entry = AnswerPattern(pattern=literal.pattern, feedback=answer.feedback)
        (accept if kind == "full" else reject).append(entry)
    return ShortAnswerKey(accept, reject or None, incorrect_feedback)


def numeric_answer_key(answers: Sequence[ImportedAnswer], *, format: str) -> NumericAnswerKey:
    """
    Pick the numeric key among the imported answers: the answer worth 100%.
    A 0% answer is dropped, except a lone `*` ("any other answer") with
    feedback, which is the `incorrectFeedback`. A second 100% answer is
    dropped if it has the same value and tolerance as the first.

    Raises:
        ValueError: an answer has partial credit, there is no 100% answer or
            two different ones, or a `*` has credit.
    """
    key: ImportedAnswer | None = None
    incorrect_feedback: str | None = None
    for answer in answers:
        kind = _credit_kind(answer, format=format, what="numeric")
        if _is_wildcard(answer.text):
            if kind == "full":
                raise ValueError(
                    f"cannot convert from {format}: a numeric `*` answer worth "
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
                raise ValueError(
                    f"cannot convert from {format}: more than one different "
                    "answer is worth 100%, and a numeric question has one answer"
                )
    if key is None:
        raise ValueError(
            f"cannot convert from {format}: no numeric answer is worth full credit"
        )
    return NumericAnswerKey(
        mdq_numeric_answer(key.text), absolute_tolerance(key.tolerance), incorrect_feedback
    )


class ConversionBase[Q](ABC):
    """
    Base class for conversion types.
    """

    #: The question types the format imports and exports.
    supports: ClassVar[frozenset[QuestionType]]

    @abstractmethod
    def to_mdq(self, external: Q, /) -> Question:
        """
        Import question to a MDQ representation.
        """

    @abstractmethod
    def from_mdq(self, mdq: Question, /) -> Q:
        """
        Convert MDQ question to the external question format
        """

    def render(self, external: Q, /) -> str:
        """
        Render the external format as a string.
        """
        return str(external)

    @abstractmethod
    def parse(self, source: str, /) -> Q:
        """
        Parse source code in the external format into the internal
        representation.
        """


def load_converter(format: str) -> ConversionBase[Any]:
    """
    Return the converter of `format` (case-insensitive).

    A converter module is imported on first use, so importing `mdq.convert`
    never imports every converter. `Any` stands for the external type of
    the converter, which depends on the format.

    Raises:
        ValueError: `format` is not one of `FORMATS`.
    """
    format = format.lower()
    match format:
        case "aiken":
            from ._aiken import Aiken

            return Aiken()
        case "gift":
            from ._gift import Gift

            return Gift()
        case "moodle-xml":
            from ._moodle_xml import MoodleXml

            return MoodleXml()
        case _:
            raise ValueError(f"Unknown format: {format}")


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


def export_question(question: Question, /, *, format: str) -> str:
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

"""
The Moodle question model, shared by GIFT, Moodle XML and Aiken: grades,
true or false groups, answer keys, general feedback and tolerances.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel

from .. import _parser
from .._exact import exact_literal, exact_span
from .._markdown import has_visible_character, starts_block
from ..errors import ParseError
from ..models import (
    AnswerPattern,
    ChoiceBlank,
    MultipleChoiceQuestion,
    Question,
    Tolerance,
    TrueFalseQuestion,
)
from ..types import Automation, Diacritics
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


def nearest_grade(score: float) -> Fraction:
    """The grade in `MOODLE_GRADES` closest to `score`; a tie goes to the one closer to 0."""
    return min(MOODLE_GRADES, key=lambda grade: (abs(score - grade), abs(grade)))


def moodle_score(score: float, report: Report, path: tuple[str | int, ...] = ()) -> float:
    """
    Return the exact grade in `MOODLE_GRADES` that `score` (a fraction
    of full credit) matches. A score that matches none is rounded to the
    nearest grade, which Moodle would otherwise reject or change, and
    reported as `score-rounded` at `path`.
    """
    grade = moodle_grade(score)
    if grade is None:
        grade = nearest_grade(score)
        report.warning(
            "score-rounded",
            f"the score {score!r} is not a grade Moodle accepts; {report.format} gets "
            f"{format_moodle_percent(grade)}% instead of {format_num(score * 100)}%",
            path,
        )
    return float(grade)


def moodle_percent(score: float, report: Report, path: tuple[str | int, ...] = ()) -> float:
    """
    Return the percentage Moodle writes for the grade `score`: 5/6 is
    `83.33333`, 1/7 is `14.28571`. See `moodle_score` for a score that is
    not a grade.
    """
    grade = moodle_grade(moodle_score(score, report, path))
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
    answer: int | float | str,
    tolerance: Tolerance | None,
    report: Report,
    path: tuple[str | int, ...] = ("answer",),
) -> float:
    """
    Return a numeric answer as the float an external format stores. If the
    float is not the exact answer ("1/3") and there is no tolerance, the
    external format compares responses with a different number than MDQ
    does: that is reported as `inexact-answer` at `path`.
    """
    if isinstance(answer, float):
        return answer
    number = float(Fraction(answer))
    has_tolerance = tolerance is not None and bool(tolerance.absolute or tolerance.relative)
    if not has_tolerance and Fraction(repr(number)) != Fraction(answer):
        report.warning(
            "inexact-answer",
            f"the answer {answer!r} has no exact floating-point value, and without a "
            f"tolerance {report.format} accepts only {number!r}; add a tolerance",
            path,
        )
    return number


def require_automatic(
    automation: Automation, report: Report, path: tuple[str | int, ...] = ("unmatched",)
) -> None:
    """
    Report `manual-grading-dropped` if `automation` leaves some responses to the
    instructor: external formats grade every response themselves and cannot
    express a pending one, so a response that matches no pattern gets 0.
    """
    if automation != "automatic":
        report.warning(
            "manual-grading-dropped",
            f"the question has `unmatched` manual (no accept pattern, or declared); "
            f"{report.format} cannot leave a response for the instructor to grade, "
            "so a response that matches no pattern gets 0",
            path,
        )


@dataclass(frozen=True)
class ExportedAnswer:
    """One literal answer of a short answer, as an external format stores it."""

    text: str
    #: `1.0` for an `accept` pattern, `0.0` for a `reject` pattern.
    credit: float
    feedback: str | None = None
    #: The path of the pattern in the MDQ question, relative to the question or blank.
    path: tuple[str | int, ...] = ()


def literal_text(rule: AnswerPattern, report: Report, path: tuple[str | int, ...] = ()) -> str | None:
    r"""
    Return the text an external format stores for a literal pattern: a plain
    literal as it is, a backtick-enclosed literal without its backticks.

    Every `*` is escaped with a backslash, which Moodle reads as a literal
    asterisk, so a lone `*` is not Moodle's "any other answer". A backslash
    before a `*` is kept: Moodle stores `2\\*3` and matches the literal `2\*3`.

    A regex cannot be expressed: `regex-dropped` is reported at `path`, and
    the result is `None`.
    """
    pattern = rule.pattern.strip(" \t\r\n")
    if pattern.startswith("/"):
        report.warning(
            "regex-dropped",
            f"the pattern {pattern!r} is a regex, and {report.format} stores only literal "
            "answers: it is dropped" + (" with its feedback" if rule.feedback else ""),
            path,
        )
        return None
    content = exact_literal(pattern)
    text = pattern if content is None else content
    return text.replace("*", "\\*")


def has_diacritic(text: str) -> bool:
    """Whether `text` has a letter with a diacritic (a nonspacing mark after NFD)."""
    return any(unicodedata.category(c) == "Mn" for c in unicodedata.normalize("NFD", text))


def exported_short_answers(
    accept: list[AnswerPattern] | None,
    reject: list[AnswerPattern] | None,
    report: Report,
    diacritics: Diacritics = "fold",
) -> list[ExportedAnswer]:
    """
    Return the answers an external format stores for a short answer: each
    `accept` literal worth full credit, then each `reject` literal worth
    none, all with their feedback. A regex is dropped (`regex-dropped`). With
    `diacritics` `"fold"`, an inexact literal with a diacritic is reported
    (`diacritics-not-folded`): Moodle compares diacritics.

    Raises:
        ConversionError: `accept` is missing, or no literal is left in it
            (`no-accept`): no response could be correct.
    """
    if not accept:
        report.error(
            "no-accept",
            f"cannot convert to {report.format}: a short answer needs an `accept` list",
            ("accept",),
        )
    answers: list[ExportedAnswer] = []
    for credit, field_name, rules in ((1.0, "accept", accept), (0.0, "reject", reject)):
        for index, rule in enumerate(rules or []):
            path = (field_name, index)
            text = literal_text(rule, report, path)
            if text is None:
                continue
            if (
                diacritics == "fold"
                and exact_literal(rule.pattern.strip(" \t\r\n")) is None
                and has_diacritic(text)
            ):
                report.warning(
                    "diacritics-not-folded",
                    f"the answer {text!r} has a diacritic, and {report.format} compares "
                    "diacritics: a response without it is wrong",
                    path,
                )
            answers.append(ExportedAnswer(text, credit, rule.feedback, path))
    if not any(answer.credit == 1.0 for answer in answers):
        report.error(
            "no-accept",
            f"cannot convert to {report.format}: no literal `accept` answer is left, "
            "so no response could be correct",
            ("accept",),
        )
    return answers


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
    or `None` if the question has none. A value that is not a string with a
    visible character is dropped (`general-feedback-dropped`).
    """
    if not question.meta or GENERAL_FEEDBACK_KEY not in question.meta:
        return None
    value = question.meta[GENERAL_FEEDBACK_KEY]
    if not isinstance(value, str) or not has_visible_character(value):
        report.warning(
            "general-feedback-dropped",
            f"`meta.{GENERAL_FEEDBACK_KEY}` must be a string with a visible character, "
            f"got {value!r}: {report.format} drops it",
            ("meta", GENERAL_FEEDBACK_KEY),
        )
        return None
    return value


#: The fields that are only notes for other instructors or identifiers of the
#: question bank: dropping them does not change what the student sees or
#: how the response is graded.
_METADATA_FIELDS = frozenset({"comment", "author", "uuid", "locale"})


def _report_dropped(
    model: BaseModel,
    report: Report,
    fields: frozenset[str],
    path: tuple[str | int, ...],
) -> None:
    """Report each field of `fields` that `model` sets to a non-default value."""
    for name, info in type(model).model_fields.items():
        if name not in fields or getattr(model, name) == info.get_default(call_default_factory=True):
            continue
        alias = info.alias or name
        if name in _METADATA_FIELDS:
            report.info(
                "metadata-dropped", f"{report.format} has no place for `{alias}`: it is dropped",
                path + (alias,),
            )
        else:
            report.warning(
                "field-dropped", f"{report.format} has no place for `{alias}`: it is dropped",
                path + (alias,),
            )


def report_dropped_fields(
    question: Question,
    report: Report,
    fields: frozenset[str],
    *,
    children: frozenset[str] = frozenset({"comment"}),
    blank_fields: frozenset[str] | None = None,
    meta_keys: bool = True,
) -> None:
    """
    Report each field with a non-default value that the target format has no
    place for: `field-dropped` if it changes what the student sees or how the
    response is graded, `metadata-dropped` for `comment`, `author`, `uuid`,
    `locale` and the `meta` keys other than `generalFeedback`. One diagnostic
    per field, at its path.

    Args:
        question: The question to export.
        report: Where to report.
        fields: The attributes of the question (and of its blanks, see
            `blank_fields`) the format drops.
        children: The attributes of choices, statements and patterns the
            format drops.
        blank_fields: The attributes of the blanks of a fill-in question the
            format drops. `fields` if `None`.
        meta_keys: Report each `meta` key other than `generalFeedback`.
    """
    _report_dropped(question, report, fields, ())
    if meta_keys and question.meta:
        for key in question.meta:
            if key != GENERAL_FEEDBACK_KEY:
                report.info(
                    "metadata-dropped",
                    f"{report.format} has no place for `meta.{key}`: it is dropped",
                    ("meta", key),
                )

    def report_children(owner: BaseModel, path: tuple[str | int, ...]) -> None:
        for attribute in ("choices", "accept", "reject"):
            for index, child in enumerate(getattr(owner, attribute, None) or []):
                if isinstance(child, BaseModel):
                    _report_dropped(child, report, children, path + (attribute, index))

    report_children(question, ())
    for index, blank in enumerate(getattr(question, "blanks", [])):
        path: tuple[str | int, ...] = ("blanks", index)
        # The `id` of a blank is not data the format drops: the stem refers to it.
        blank_set = (fields if blank_fields is None else blank_fields) - {"id"}
        _report_dropped(blank, report, blank_set, path)
        report_children(blank, path)


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


def _credit_kind(answer: ImportedAnswer) -> Literal["full", "none", "partial"]:
    """Classify the credit of `answer` as full (100%), none (0%) or partial (anything else)."""
    if abs(answer.credit - 1) < MOODLE_GRADE_TOLERANCE:
        return "full"
    if abs(answer.credit) < MOODLE_GRADE_TOLERANCE:
        return "none"
    return "partial"


def _partial_credit(answer: ImportedAnswer) -> str:
    """The credit of a partial `answer`, in percent, as the messages write it."""
    return f"{format_num(round(answer.credit * 100, 5))}%"


#: An asterisk without a backslash before it: a wildcard in Moodle.
_WILDCARD_RE = re.compile(r"(?<!\\)\*")

#: A character that a regex of MDQ reads as syntax.
_REGEX_SPECIAL_RE = re.compile(r"[\\^$.|?*+()\[\]{}/]")


def _is_wildcard(text: str) -> bool:
    """Whether `text` is Moodle's lone `*` ("any other answer")."""
    return text.strip(" \t\r\n") == "*"


def wildcard_pattern(text: str, case_sensitive: bool = False) -> str:
    r"""
    The MDQ regex that matches the whole response as Moodle's wildcard does:
    each `*` without a backslash is any text, every other character is
    literal (`\*` is an asterisk). It ignores case unless `case_sensitive`.
    """
    parts = _WILDCARD_RE.split(text)
    body = r"[\s\S]*".join(
        _REGEX_SPECIAL_RE.sub(lambda m: "\\" + m.group(), part.replace("\\*", "*"))
        for part in parts
    )
    return f"/{body}/" + ("" if case_sensitive else "i")


def short_answer_key(
    answers: Sequence[ImportedAnswer], report: Report, case_sensitive: bool = False
) -> ShortAnswerKey:
    """
    Split the answers of an imported short answer by credit: 100% is
    `accept`, 0% is `reject` (both with their feedback). A lone `*` is
    Moodle's "any other answer": at 100% it is the regex `/.*/`, at 0% its
    feedback is the `incorrectFeedback`.

    An answer with partial or negative credit goes to `reject`, worth 0
    (`partial-credit-dropped`): it never gets more credit than the source.
    A `*` inside the text is a wildcard, written as an MDQ regex
    (`wildcard-to-regex`), which ignores case unless `case_sensitive`.
    """
    accept: list[AnswerPattern] = []
    reject: list[AnswerPattern] = []
    incorrect_feedback: str | None = None
    for answer in answers:
        kind = _credit_kind(answer)
        if kind == "partial":
            report.warning(
                "partial-credit-dropped",
                f"the answer {answer.text!r} has partial credit ({_partial_credit(answer)}), "
                "and short-answer grading is binary: it is a `reject` answer worth 0",
                ("reject", len(reject)),
            )
            kind = "none"
        if _is_wildcard(answer.text):
            if kind == "full":
                accept.append(AnswerPattern(pattern="/.*/", feedback=answer.feedback))
            elif answer.feedback:
                incorrect_feedback = answer.feedback
            continue
        target = accept if kind == "full" else reject
        if _WILDCARD_RE.search(answer.text):
            pattern = wildcard_pattern(answer.text, case_sensitive)
            report.warning(
                "wildcard-to-regex",
                f"the answer {answer.text!r} has a `*` wildcard: it is the regex {pattern}",
                ("accept" if kind == "full" else "reject", len(target)),
            )
        else:
            pattern = literal_pattern(answer.text.replace("\\*", "*")).pattern
        target.append(AnswerPattern(pattern=pattern, feedback=answer.feedback))
    return ShortAnswerKey(accept, reject or None, incorrect_feedback)


def _number(text: str) -> float | str:
    """`text` as a number, or as it is if it is not one."""
    try:
        return float(text)
    except ValueError:
        return text


def numeric_answer_key(answers: Sequence[ImportedAnswer], report: Report) -> NumericAnswerKey:
    """
    Pick the numeric key among the imported answers: the answer worth 100%.
    A lone `*` ("any other answer") at 0% with feedback is the
    `incorrectFeedback`. Everything else is dropped, with a warning: a 0%
    answer, a second 100% answer, a `*` at 100% (`answer-dropped`), an
    answer with partial credit and the feedback of the key
    (`partial-credit-dropped`, `feedback-dropped`). Without a 100% answer,
    the answer with the highest positive credit becomes the key
    (`partial-credit-dropped`).

    Raises:
        ConversionError: no answer has positive credit (`no-full-credit`).
    """
    path = ("answer",)
    key: ImportedAnswer | None = None
    partial: list[ImportedAnswer] = []
    incorrect_feedback: str | None = None
    for answer in answers:
        kind = _credit_kind(answer)
        if _is_wildcard(answer.text):
            if kind == "full":
                report.warning(
                    "answer-dropped",
                    "a numeric `*` answer worth 100% accepts any number, which MDQ "
                    "cannot express: it is dropped",
                    path,
                )
            elif kind == "partial":
                report.warning(
                    "partial-credit-dropped",
                    f"the numeric `*` answer has partial credit ({_partial_credit(answer)}), "
                    "and numeric grading is binary: it is dropped",
                    path,
                )
            elif answer.feedback:
                incorrect_feedback = answer.feedback
        elif kind == "partial":
            partial.append(answer)
        elif kind == "none":
            report.warning(
                "answer-dropped",
                f"the numeric answer {answer.text!r} worth 0% is dropped"
                + (" with its feedback" if answer.feedback else ""),
                path,
            )
        elif key is None:
            key = answer
        else:
            same = (_number(key.text), key.tolerance or 0.0) == (
                _number(answer.text),
                answer.tolerance or 0.0,
            )
            report.warning(
                "answer-dropped",
                f"the numeric answer {answer.text!r} worth 100% is dropped: "
                + (
                    "it repeats the first one"
                    if same
                    else "a numeric question has one answer, the first one"
                ),
                path,
            )
    positive = [answer for answer in partial if answer.credit > 0]
    if key is None and positive:
        key = max(positive, key=lambda answer: answer.credit)
        partial.remove(key)
        report.warning(
            "partial-credit-dropped",
            f"no numeric answer is worth 100%: the answer {key.text!r} "
            f"({_partial_credit(key)}) is the answer of the question",
            path,
        )
    for answer in partial:
        report.warning(
            "partial-credit-dropped",
            f"the numeric answer {answer.text!r} has partial credit "
            f"({_partial_credit(answer)}), and numeric grading is binary: it is dropped",
            path,
        )
    if key is None:
        report.error(
            "no-full-credit",
            f"cannot convert from {report.format}: no numeric answer has positive credit",
            path,
        )
    if key.feedback:
        report.warning(
            "feedback-dropped",
            f"the feedback of the numeric answer {key.text!r} is dropped: a numeric "
            "question has no feedback for its answer",
            path,
        )
    return NumericAnswerKey(
        mdq_numeric_answer(key.text, report), absolute_tolerance(key.tolerance), incorrect_feedback
    )

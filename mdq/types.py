"""
Type aliases shared across the package.

The document tree itself is modelled with Pydantic in `mdq.models`; this
module holds the aliases that are not models -- the question type
discriminator, and the shapes a student's response may take.
"""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from typing import Any, Literal, Required, TypedDict, get_args

QuestionType = Literal[
    "multiple-choice",
    "multiple-selection",
    "true-false",
    "numeric",
    "short-answer",
    "essay",
    "fill-in",
    "ordering",
]

#: How a question with several parts reduces them to one score.
#: `symmetric` may go below zero; `partial` stays within [0, 1] while
#: still awarding credit for parts; `all-or-nothing` returns 1 or 0.
#: `partial` names a range, not one formula -- each question type
#: defines its own (see docs/adr/0002-partial-names-a-range-not-an-algorithm.md).
GradingStrategy = Literal["symmetric", "partial", "all-or-nothing"]

#: The question types that choose a grading strategy. The other types
#: grade by a fixed rule and take no `grading` field. On these types,
#: `grading` is `None` when the question declares none, so the exam's
#: `grading` applies to it, and `symmetric` applies when neither does.
#: An explicit `symmetric` is kept, since the exam cannot override it.
GradedQuestionType = Literal[
    "multiple-choice",
    "multiple-selection",
    "true-false",
    "fill-in",
]

#: An exam's grading strategy: one for every question it holds, or one
#: per question type. Types missing from the mapping grade as
#: `symmetric`, and a question that declares its own `grading` ignores
#: the exam's.
ExamGrading = GradingStrategy | dict[GradedQuestionType, GradingStrategy]

#: How inexact literals treat diacritics: `fold` strips them before
#: comparing, `keep` preserves them. Regexes, exact literals and the `*`
#: wildcard ignore it (docs/question-types/short-answer.md § Diacritics).
Diacritics = Literal["fold", "keep"]


QUESTION_TYPES = set(get_args(QuestionType))


#
# JSON-document dicts
#
# These TypedDicts mirror the shapes in `schema/*.yaml` -- one per
# question type, plus the shared pieces (`choices`, `blanks`,
# `tolerance`) they are assembled from. They describe the dict
# `mdq._parser` builds, before `mdq.loading` ever turns it into a
# Pydantic model (`mdq.models` mirrors the same schemas again, as typed
# attributes for a *validated* document). Internal to the parser --
# nothing outside it re-exports these. Field names are the schema's own
# JSON names -- camelCase, not the models' aliased snake_case -- since
# this is the JSON shape itself.
#
# Per the schemas' `unevaluatedProperties: false`, a value of one of
# these types never carries a field outside what its own TypedDict
# declares.
#
# Ordered broadest first: the exam and question document shapes, then
# the per-type question dicts they are discriminated into, then the
# smaller pieces (choices, blanks) those are assembled from.
#
class ExamDict(TypedDict, total=False):
    """schema/exam.yaml"""

    type: Literal["exam"]
    id: str
    uuid: str
    title: str
    description: str
    course: str
    author: str
    locale: str
    instructions: str
    tags: list[str]
    meta: dict[str, Any]
    penalty: PenaltyPolicy
    grading: ExamGrading
    start: str
    duration: str
    questions: Required[list[ExamEntryDict]]


class IncludeDict(TypedDict):
    """
    A reference to an out-of-line question -- schema/exam.yaml#/$defs/Include.
    """

    include: str


#: A query for out-of-line questions -- schema/exam.yaml#/$defs/IncludeAll.
#: Declared with the functional syntax, since `include-all` is not a valid
#: Python identifier.
IncludeAllDict = TypedDict(
    "IncludeAllDict", {"include-all": Required[str], "max": int}, total=False
)


#: One block of an exam's `questions` array -- schema/exam.yaml#/$defs/Entry.
type ExamEntryDict = IncludeDict | IncludeAllDict | QuestionDict

#: Any question document, discriminated by `type` -- the dict shape
#: `mdq._parser.parse_question` returns.
type QuestionDict = (
    MultipleChoiceQuestionDict
    | MultipleSelectionQuestionDict
    | TrueFalseQuestionDict
    | NumericQuestionDict
    | ShortAnswerQuestionDict
    | EssayQuestionDict
    | FillInQuestionDict
    | OrderingQuestionDict
)


class QuestionBaseDict(TypedDict, total=False):
    """
    Fields common to every question type -- schema/question-base.yaml.
    """

    id: str
    uuid: str
    title: str
    author: str
    stem: Required[str]
    preamble: str
    epilogue: str
    comment: str
    locale: str
    tags: list[str]
    meta: dict[str, Any]


class MultipleChoiceQuestionDict(QuestionBaseDict, total=False):
    """schema/multiple-choice.yaml"""

    type: Required[Literal["multiple-choice"]]
    choices: Required[list[ScoredChoiceDict]]
    shuffle: bool
    grading: GradingStrategy


class MultipleSelectionQuestionDict(QuestionBaseDict, total=False):
    """schema/multiple-selection.yaml"""

    type: Required[Literal["multiple-selection"]]
    choices: Required[list[BooleanChoiceDict]]
    shuffle: bool
    grading: GradingStrategy


class TrueFalseQuestionDict(QuestionBaseDict, total=False):
    """schema/true-false.yaml"""

    type: Required[Literal["true-false"]]
    choices: Required[list[StatementDict]]
    shuffle: bool
    grading: GradingStrategy


class NumericQuestionDict(QuestionBaseDict, total=False):
    """schema/numeric.yaml"""

    type: Required[Literal["numeric"]]
    answer: Required[float]
    unit: str
    domain: NumericDomain
    decimalPlaces: int
    tolerance: ToleranceDict


class PatternDict(TypedDict, total=False):
    """schema/short-answer.yaml#/$defs/pattern"""

    pattern: Required[str]
    feedback: str
    comment: str


#: An accept/reject entry: a bare pattern string, or the object form.
type PatternEntry = str | PatternDict


class ShortAnswerQuestionDict(QuestionBaseDict, total=False):
    """schema/short-answer.yaml"""

    type: Required[Literal["short-answer"]]
    oneOf: list[str]
    regex: str
    openEnded: bool
    accept: list[PatternEntry]
    reject: list[PatternEntry]
    preAccept: list[PatternEntry]
    preReject: list[PatternEntry]
    diacritics: Diacritics


class EssayQuestionDict(QuestionBaseDict, total=False):
    """schema/essay.yaml"""

    type: Required[Literal["essay"]]
    input: EssayInput
    highlight: str
    answerKey: str


class FillInQuestionDict(QuestionBaseDict, total=False):
    """schema/fill-in.yaml"""

    type: Required[Literal["fill-in"]]
    blanks: Required[list[BlankDict]]
    shuffle: bool
    grading: GradingStrategy
    diacritics: Diacritics


#: schema/fill-in.yaml#/$defs/Blank -- discriminated by `type`.
type BlankDict = ChoiceBlankDict | ShortAnswerBlankDict | NumericBlankDict


class ChoiceBlankDict(TypedDict, total=False):
    """A fill-in blank graded like multiple-choice -- schema/fill-in.yaml#/$defs/ChoiceBlank."""

    id: Required[str]
    type: Required[Literal["multiple-choice"]]
    choices: Required[list[ScoredChoiceDict]]


class ShortAnswerBlankDict(TypedDict, total=False):
    """schema/fill-in.yaml#/$defs/ShortAnswerBlank"""

    id: Required[str]
    type: Required[Literal["short-answer"]]
    oneOf: list[str]
    regex: str
    accept: list[PatternEntry]
    reject: list[PatternEntry]
    preAccept: list[PatternEntry]
    preReject: list[PatternEntry]


class NumericBlankDict(TypedDict, total=False):
    """schema/fill-in.yaml#/$defs/NumericBlank"""

    id: Required[str]
    type: Required[Literal["numeric"]]
    answer: Required[float]
    unit: str
    domain: NumericDomain
    decimalPlaces: int
    tolerance: ToleranceDict


class OrderingQuestionDict(QuestionBaseDict, total=False):
    """schema/ordering.yaml"""

    type: Required[Literal["ordering"]]
    lines: Required[list[OrderingLineDict]]
    extra: list[OrderingLineDict]
    accept: list[OrderingAlternativeDict]
    reject: list[OrderingAlternativeDict]
    content: OrderingContent
    highlight: str
    indentation: Indentation
    unmatched: Unmatched
    normalizations: list[Normalization]


class OrderingAlternativeDict(TypedDict, total=False):
    """An accepted or rejected ordering -- schema/ordering.yaml#/$defs/Alternative."""

    lines: Required[list[OrderingLineDict]]
    feedback: str
    comment: str


#: One line as an `[indentation level, text]` pair --
#: schema/ordering.yaml#/$defs/Line. The document shape is a two-element
#: array; `mdq.models.OrderingLine` holds the same pair as a tuple.
type OrderingLineDict = list[int | str]


class ScoredChoiceDict(TypedDict, total=False):
    """A multiple-choice option -- schema/multiple-choice.yaml#/$defs/Choice."""

    id: str
    text: Required[str]
    score: float
    feedback: str
    comment: str


class BooleanChoiceDict(TypedDict, total=False):
    """A multiple-selection option -- schema/multiple-selection.yaml#/$defs/Choice."""

    id: str
    text: Required[str]
    correct: bool
    feedback: str
    comment: str


class StatementDict(TypedDict, total=False):
    """A true/false statement -- schema/true-false.yaml#/$defs/Choice."""

    id: str
    text: Required[str]
    correct: bool
    marker: str
    feedback: str
    comment: str


class ToleranceDict(TypedDict, total=False):
    """schema/numeric.yaml#/$defs/Tolerance"""

    absolute: float
    relative: float


#: schema/numeric.yaml and schema/fill-in.yaml#/$defs/NumericBlank.
NumericDomain = Literal["integer", "decimal", "fraction"]

#: schema/essay.yaml.
EssayInput = Literal["code", "text", "plain"]

#: How an ordering question's lines are written and presented: `code` for
#: a fenced code block, `text` for an unordered list.
OrderingContent = Literal["code", "text"]

#: Whether the student may re-indent an ordering question's lines, and
#: whether that indentation counts when grading. `lenient` implies the
#: `dedent` normalization.
Indentation = Literal["fixed", "lenient", "strict"]

#: What becomes of an ordering response that matches no answer key:
#: `manual` leaves it for a human, `incorrect` scores it 0.
Unmatched = Literal["manual", "incorrect"]

#: A transformation applied to both sides of every ordering comparison --
#: the response and each answer key alike -- before they are matched.
Normalization = Literal["dedent", "skip-blanks"]

#: An exam's policy for whether a negative question score survives.
#: Questions never clamp their own score -- this is the only place
#: clamping happens (see
#: docs/adr/0001-score-scale-and-exam-level-clamping.md).
PenaltyPolicy = Literal["none", "capped", "full"]


#
# Responses
#
# A response is what a student marked. It is never a document: there is
# no response schema and no Markdown surface for it (see
# docs/adr/0003-no-response-document.md), so these aliases are the whole
# specification of the shape grading accepts.
#
# Several aliases below collapse to the same runtime type -- `str` serves
# both a chosen choice id and an essay. They are kept apart because they
# document which question type produces which, which is the part a
# reader needs.
#
# Ordered broadest first: a whole exam's responses, then a single
# question's response, then the per-type shapes it may take.
#

#: Every response in one exam attempt, keyed by question id. A question
#: absent from the mapping is skipped; a key naming no question in the
#: exam is a `ResponseError`.
type ExamResponses = dict[str, QuestionResponse]

#: Any response to a single question. `None` means the question was
#: skipped: it scores 0 without its grading formula running, so it
#: produces no feedback either.
type QuestionResponse = (
    MultipleChoiceResponse
    | MultipleSelectionResponse
    | TextResponse
    | NumericResponse
    | FillInResponse
    | TrueFalseResponse
    | OrderingResponse
    | None
)

#: multiple-choice: the id of the choice the student picked.
type MultipleChoiceResponse = str

#: multiple-selection: the set of choice ids the student marked.
#: A missing key means the student did not mark that choice.
type MultipleSelectionResponse = set[str]

#: true-false: the student's choice, `True` or `False`. Explicit skips are
#: `None`.
type TrueFalseResponse = dict[str, bool | None]

#: short-answer and essay: the text the student wrote, before
#: normalisation.
type TextResponse = str

#: numeric: the value the student entered.
type NumericResponse = int | float | Fraction

#: fill-in: each blank's response, keyed by blank id, taking whatever
#: that blank's own type takes.
type FillInResponse = dict[str, QuestionResponse]

#: ordering: the lines the student submitted, in the order they submitted
#: them, each an `[indentation level, text]` pair. The lines carry no id:
#: they are compared by content. A pair may arrive as the JSON array it
#: was serialized as, or already as the tuple the models hold.
type OrderingResponse = Sequence[OrderingLineDict | tuple[int, str]]

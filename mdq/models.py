"""
Pydantic models for the MDQ document tree and for grading results.

These models are the public shape of a *validated* document. The
pipeline is markdown -> json -> json validated against `schema/` ->
model, so a model is what "parse, don't validate" hands back: by the
time one exists, the document is known to be well formed.

Two rules govern this module:

1. The models mirror the JSON schemas in `schema/` and in most cases should not
   be stricter than them. A few exceptions are rules that are obligatory in the
   question specification but cannot be enforced by the JSON schema. Things like
   "all keys in a list of objects must be unique".

2. Field names are the schema's names in snake_case, with the camelCase
   spelling kept as an alias, so a model round-trips to the document it
   came from.

Nothing here is implemented yet: the fields are the design.

This module imports `mdq.parser` -- a new direction of coupling for the
model layer, which otherwise knows nothing about how Markdown gets
parsed. It is deliberate: `normalize_paragraphs`/`normalize_intro` need
to canonicalize `preamble`/`stem`/`epilogue` into the exact fixed point
a render-then-parse round trip produces, and the only way to guarantee
that without a second, drifting copy of the parser's reconstruction
rules is to call the parser itself (`parser.reconstruct_blocks`).
`mdq.parser` has no reciprocal dependency on this module (it hands back
plain dicts), so this stays one-directional.
"""

from __future__ import annotations

import re
import unicodedata
import weakref
from datetime import date, datetime, timedelta
from fractions import Fraction
from typing import Annotated, Any, Iterable, Literal, Mapping, Self, Sequence

import opt
import pydantic_core
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    RootModel,
    model_validator,
)
from pydantic.alias_generators import to_camel
from pydantic_core import InitErrorDetails, PydanticCustomError

from . import parser, render, schedule, slugify
from . import types as t
from .errors import NotAutoGradable, ResponseError
from .regex import RegexPattern
from .regex import normalize_text as strip_accents

__all__ = [
    "MdqModel",
    "Tolerance",
    "ScoredChoice",
    "BooleanChoice",
    "Statement",
    "BaseQuestion",
    "MultipleChoiceQuestion",
    "MultipleSelectionQuestion",
    "TrueFalseQuestion",
    "NumericQuestion",
    "ShortAnswerQuestion",
    "AnswerPattern",
    "EssayQuestion",
    "ChoiceBlank",
    "ShortAnswerBlank",
    "NumericBlank",
    "Blank",
    "FillInQuestion",
    "OrderingLine",
    "OrderingAlternative",
    "OrderingQuestion",
    "Question",
    "QuestionRoot",
    "Exam",
    "QuestionScore",
    "ExamScore",
    "GradingStrategy",
    "GradedQuestionType",
    "ExamGrading",
    "Diacritics",
    "PenaltyPolicy",
    "ExamStart",
    "ExamDuration",
    "NumericDomain",
    "EssayInput",
    "OrderingContent",
    "Indentation",
    "Unmatched",
    "Normalization",
    "coerce_ordering_lines",
    "first_feedback",
    "render_pattern_block",
    "normalize_paragraphs",
    "normalize_intro",
    "remove_trailing_ws",
]


class MdqModel(BaseModel):
    """
    Base configuration shared by every model in the document tree.

    `extra="forbid"` mirrors the schemas' `unevaluatedProperties: false`
    -- equal strictness, not more.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    def __str__(self) -> str:
        """
        Return a Markdown representation of the model.

        The `**kwargs` are passed to `mdq.render.render()`.
        """
        return self.render()

    def to_dict(self, by_alias: bool = True) -> dict:
        """
        Return a dict representation of the model that is compatible with the
        JSON schema and the original document.
        """
        data = self.model_dump(
            by_alias=by_alias,
            exclude_none=True,
            exclude_defaults=True,
        )
        # `type` is a defaulted Literal on every discriminated model, so
        # `exclude_defaults` drops it -- on `self` and on every nested
        # model `model_dump` recurses into (a question inside an exam,
        # say). It is the one default worth keeping: without it the dict
        # no longer says which schema it validates against, and no
        # discriminated union can read it back.
        _reinject_type_discriminators(self, data)
        if "type" in type(self).model_fields:
            data = {"type": getattr(self, "type"), **data}
        return data

    def _render_lines(self) -> Iterable[str]:
        """
        Used by subclasses to implement `render_lines()`.

        Must return a generator yielding a Markdown representation of the model
        as an iterable of lines. The final rendering is the concatenation
        of these lines with newlines in between.
        """
        raise NotImplementedError("Subclasses must implement _render_lines()")

    def render(self) -> str:
        """
        Return a Markdown representation of the model.

        The `**kwargs` are passed to `mdq.render.render()`.
        """
        return "\n".join(self._render_lines())


#
# Unique ids: shared machinery for the four "duplicate" rules
# (dev/specs/to-do/unique-ids.md). These used to be `warning`-level lint
# checks in `mdq.linter`; they are model validators now, so a violation
# is an `error` that stops `load` from returning a document at all.
#

#: Runs of whitespace outside a code span. Splitting on backticks first
#: keeps `foo bar` and `foo  bar` distinct while still collapsing plain
#: prose -- the same normalization `mdq.linter` used to apply under the
#: name `_visual_key`, moved here so the models can use it too.
_CODE_SPAN_RE = re.compile(r"(`+[^`]*`+)")
_WHITESPACE_RE = re.compile(r"\s+")


def _visual_key(text: str) -> str:
    """
    Normalize `text` the way a Markdown renderer would, for comparing
    choice texts as a reader would see them once rendered: whitespace
    runs collapse to a single space in prose, but not inside code spans.
    """
    parts = _CODE_SPAN_RE.split(text)
    # Odd indices are the captured code spans; leave those untouched.
    normalized = [
        part if index % 2 else _WHITESPACE_RE.sub(" ", part)
        for index, part in enumerate(parts)
    ]
    return unicodedata.normalize("NFC", "".join(normalized)).strip()


def _raise_unique_id_error(
    model_name: str,
    code: str,
    message: str,
    loc: tuple[str | int, ...],
    input_value: Any,
) -> None:
    """
    Raise a pydantic `ValidationError` whose one error carries `code` as
    its `type` (so `mdq.loading` recovers it as the diagnostic `code`)
    and `loc` as its location, regardless of where in the model tree
    this runs -- `loc` is relative to whatever model raises, and
    pydantic prepends the path down to it (occasionally with a
    discriminated union's tag in between).
    """
    error = InitErrorDetails(
        type=PydanticCustomError(code, message), loc=loc, input=input_value
    )
    raise pydantic_core.ValidationError.from_exception_data(model_name, [error])


def _check_unique_choices(model_name: str, choices: Sequence[Any]) -> None:
    """
    Enforce `duplicate-choice-id` and `duplicate-choice-text` over one
    list of choices -- a question's own `choices`, or one fill-in choice
    blank's.

    Ids are compared as-is; texts are compared with `_visual_key`, so
    two texts that only differ in incidental whitespace collide too
    (multiple-choice.md, "Choices").
    """
    seen_ids: dict[str, int] = {}
    seen_visuals: dict[str, int] = {}

    for index, choice in enumerate(choices):
        choice_id = choice.id
        if choice_id is not None:
            first_index = seen_ids.get(choice_id)
            if first_index is not None:
                _raise_unique_id_error(
                    model_name,
                    "duplicate-choice-id",
                    f"choice id {choice_id!r} is already used by choices[{first_index}]",
                    ("choices", index, "id"),
                    choice_id,
                )
            seen_ids[choice_id] = index

        visual = _visual_key(choice.text)
        first_index = seen_visuals.get(visual)
        if first_index is not None:
            _raise_unique_id_error(
                model_name,
                "duplicate-choice-text",
                f"choice text {choice.text!r} is already used by choices[{first_index}]",
                ("choices", index, "text"),
                choice.text,
            )
        seen_visuals[visual] = index


#
# Shared vocabulary
#

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

#: An exam's policy for whether a negative question score survives.
#: Questions never clamp their own score -- this is the only place
#: clamping happens (see
#: docs/adr/0001-score-scale-and-exam-level-clamping.md).
PenaltyPolicy = Literal["none", "capped", "full"]

#: When an exam begins: a date, or a date-time that may carry a UTC
#: offset. Serialized in canonical ISO 8601 form.
ExamStart = Annotated[
    datetime | date,
    BeforeValidator(schedule.parse_start),
    PlainSerializer(schedule.format_start),
]

#: How long an exam lasts. Serialized as a canonical ISO 8601 duration.
ExamDuration = Annotated[
    timedelta,
    BeforeValidator(schedule.parse_duration),
    PlainSerializer(schedule.format_duration),
]

NumericDomain = Literal["integer", "decimal", "fraction"]

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


class Tolerance(MdqModel):
    absolute: float | None = None
    relative: float | None = None


class ScoredChoice(MdqModel):
    """
    A multiple-choice option, or a choice inside a fill-in choice blank.

    `score` is bounded to [-1, 1]: 1 is correct, 0 incorrect, and a
    negative value penalises picking it.
    """

    id: str | None = None
    text: str
    score: Annotated[float | None, Field(default=None, ge=-1, le=1)] = None
    feedback: str | None = None
    comment: str | None = None


class BooleanChoice(MdqModel):
    """
    A multiple-selection option: the key says whether it belongs in the
    answer, and there is no per-choice score.
    """

    id: str | None = None
    text: str
    correct: bool = False
    feedback: str | None = None
    comment: str | None = None


class Statement(MdqModel):
    """
    One true/false statement. Structurally a `BooleanChoice` plus the
    marker that spelled it in the Markdown source.
    """

    id: str | None = None
    text: str
    correct: bool = False
    marker: Annotated[str | None, Field(default=None, min_length=1, max_length=1)] = None
    feedback: str | None = None
    comment: str | None = None


#
# `with_ids()`: deriving ids (dev/specs/to-do/derived-ids.md)
#


def _with_choice_ids[C: (ScoredChoice, BooleanChoice, Statement)](
    choices: Sequence[C],
) -> list[C]:
    """
    Return `choices` with a derived id filled in wherever one is missing.

    A choice that already has an id keeps it. Every derived id avoids
    every id already in use, explicit or derived, so the result never
    collides (`mdq.slugify.loose`). Returns a new list; a choice that
    already has an id is returned as-is.
    """
    missing = [choice for choice in choices if choice.id is None]
    if not missing:
        return list(choices)

    forbid = {choice.id for choice in choices if choice.id is not None}
    derived = slugify.loose(
        frozenset(choice.text for choice in missing), forbid=frozenset(forbid)
    )
    return [
        choice
        if choice.id is not None
        else choice.model_copy(update={"id": derived[choice.text]})
        for choice in choices
    ]


def _implicit_question_id(index: int) -> str:
    """
    The implicit id a question at 0-based `index` would get: `q1` for the
    first block, `q2` for the second, and so on -- counting every block
    in the exam, includes included (exam.md, "Question ids").
    """
    return f"q{index + 1}"


#
# Questions
#
class BaseQuestion[R](MdqModel):
    """
    Fields every question type carries.

    `id` is optional here and required for grading: a document that
    lacks one is valid but not *addressable*, and the system using the
    library is expected to supply it.
    """

    id: str | None = None
    uuid: str | None = None
    title: str | None = None
    author: str | None = None
    stem: str
    preamble: str | None = None
    epilogue: str | None = None
    comment: str | None = None
    locale: str | None = None
    meta: dict[str, object] | None = None
    tags: list[str] = Field(default_factory=list)
    _exam: Annotated[weakref.ref[Exam] | None, Field(default=None, exclude=True)] = None

    @property
    def exam(self) -> Exam | None:
        if self._exam is not None:
            return self._exam()
        return None

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        copy = super().model_copy(update=update, deep=deep)
        copy._exam = None  # unbind the copy from the exam.
        return copy

    def __eq__(self, other: object) -> bool:
        # `_exam` is a back-reference, not part of the question's value.
        # Pydantic compares private attributes, and a weakref compares its
        # referents, so including it would compare the owning exams, whose
        # questions point back to them -- infinite recursion.
        if not isinstance(other, BaseQuestion):
            return NotImplemented
        return type(self) is type(other) and self.__dict__ == other.__dict__

    #: How much this question counts towards its exam. An exam entry may
    #: override it, and resolution applies that override here, so the
    #: value on a resolved question is always the winning one.
    weight: Annotated[float, Field(ge=0)] = 1.0

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        """
        Return a dict representation of the model that is compatible with the
        frontmatter of the original document.
        """

        data: dict[str, Any] = {
            "id": self.id,
            "uuid": self.uuid,
            "title": self.title,
            "author": self.author,
            "locale": self.locale,
            "meta": self.meta,
        }
        if skip_defaults:
            data = clear_nones(data)
        if self.weight != 1.0 or not skip_defaults:
            data["weight"] = self.weight
        if self.tags != [] or not skip_defaults:
            data["tags"] = self.tags
        return data

    def _render_lines(self) -> Iterable[str]:
        frontmatter = self.frontmatter(skip_defaults=True)

        id = self.id
        skip_frontmatter = (
            frontmatter.keys() == {"id"}
            and can_inline_id(self.preamble, self.stem)
            and not self.comment
        )
        if not skip_frontmatter:
            id = None
            yield from render.yield_frontmatter(frontmatter, self.comment)
            yield ""

        yield from render.yield_introduction(self, id=id)
        yield from self._render_body()
        yield from render.yield_conclusion(self, skip_line=True)

    def _render_body(self) -> Iterable[str]:
        """
        model's body as an iterable of lines.
        """
        raise NotImplementedError("Subclasses must implement _render_body()")

    def normalize(self) -> Self:
        """
        Return a copy of the model with normalized fields.

        Two models that normalize to the same model should have the same
        markdown representation. Treat it as a canonical form for the model,
        useful for comparing two elements.
        """
        copy = self.model_copy()
        copy._normalize()
        return copy

    def _normalize(self) -> None:
        """
        Normalize *inplace*.

        Runs `mdq.parser`'s Markdown parser over `preamble`/`stem`/
        `epilogue` (via `normalize_intro`/`normalize_paragraphs`) to
        canonicalize them, so this is no longer a handful of cheap
        string operations -- fine at this project's scale, but worth
        knowing if it ever shows up in a profile.
        """
        # `preamble`/`epilogue`/`comment` are rendered as the mere
        # presence of raw lines (prose blocks, `#`-comment lines) with
        # no field marker of their own, so an empty string and no value
        # at all render identically and a parse can only ever produce
        # the latter. Collapsing an all-whitespace value to None here
        # keeps normalization a fixed point of that round trip.
        self.preamble, self.stem = normalize_intro(self.preamble, self.stem)
        self.epilogue = opt.map(normalize_paragraphs, self.epilogue) or None
        self.comment = opt.map(remove_trailing_ws, self.comment) or None
        self.tags = [tag.strip() for tag in self.tags if tag.strip()]
        self.author = opt.map(str.strip, self.author)

    def score_response(self, response: R) -> QuestionScore:
        """
        Return the score for one response to this question.
        """
        raise NotImplementedError("Subclasses must implement score_response()")

    def with_ids(self) -> Self:
        """
        Return a copy of this question with a derived id filled in for
        every choice that has none of its own (dev/specs/to-do/derived-ids.md).

        A question type with no choices (essay, numeric, short answer,
        ordering) has nothing to derive, so this returns a plain copy.
        Never changes `self`, never touches an id already written, and
        running it twice gives the same result as running it once.
        """
        return self.model_copy()


class MultipleChoiceQuestion(BaseQuestion[t.MultipleChoiceResponse]):
    choices: Annotated[list[ScoredChoice], Field(min_length=2)]
    type: Literal["multiple-choice"] = "multiple-choice"
    shuffle: bool | None = None
    grading: GradingStrategy | None = None

    @model_validator(mode="after")
    def check_choices_are_unique(self) -> Self:
        """
        multiple-choice.md, "Choices": ids and texts must each be
        unique (`duplicate-choice-id`, `duplicate-choice-text`).
        """
        _check_unique_choices(type(self).__name__, self.choices)
        return self

    def with_ids(self) -> Self:
        """See `BaseQuestion.with_ids`."""
        return self.model_copy(update={"choices": _with_choice_ids(self.choices)})

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.shuffle is not None:
            data["shuffle"] = self.shuffle
        if self.grading is not None:
            data["grading"] = self.grading
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        for choice in self.choices:
            score = choice.score
            if score == 1.0:
                mark = "*"
            elif score == 0.0 or score is None:
                mark = " "
            else:
                mark = f"{score * 100}%"

            yield from render.yield_choice(choice, mark=mark)

    def score_response(self, response: t.MultipleChoiceResponse) -> QuestionScore:
        """
        Score the response by its picked choice's `score`, falling back to
        `unspecified_score` for a choice that declares none.

        Raises:
            ResponseError: `response` names no choice.
        """
        choice = next((c for c in self.choices if c.id == response), None)
        if choice is None:
            raise ResponseError(f"Response id {response!r} not found in choices")
        score = choice.score if choice.score is not None else self.unspecified_score()
        feedback = [choice.feedback] if choice.feedback else []
        return QuestionScore(score=score, feedback=feedback)

    def unspecified_score(self) -> float:
        """
        The score a choice that declares none is graded with.

        `"partial"` and `"all-or-nothing"` treat it as zero. `"symmetric"`
        spreads the negative of the declared scores evenly over the choices
        that declare none, so picking at random averages zero, then clamps
        the result to [-1, 0].
        """
        if self.grading not in (None, "symmetric"):
            return 0.0

        declared = [c.score for c in self.choices if c.score is not None]
        missing = len(self.choices) - len(declared)
        if not missing:
            return 0.0
        return max(-1.0, min(0.0, -sum(declared) / missing))


class MultipleSelectionQuestion(BaseQuestion[t.MultipleSelectionResponse]):
    choices: Annotated[list[BooleanChoice], Field(min_length=2)]
    type: Literal["multiple-selection"] = "multiple-selection"
    shuffle: bool | None = None
    grading: GradingStrategy | None = None

    @model_validator(mode="after")
    def check_choices_are_unique(self) -> Self:
        """
        multiple-choice.md, "Choices" (shared by multiple-selection): ids
        and texts must each be unique (`duplicate-choice-id`,
        `duplicate-choice-text`).
        """
        _check_unique_choices(type(self).__name__, self.choices)
        return self

    def with_ids(self) -> Self:
        """See `BaseQuestion.with_ids`."""
        return self.model_copy(update={"choices": _with_choice_ids(self.choices)})

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.shuffle is not None:
            data["shuffle"] = self.shuffle
        if self.grading is not None:
            data["grading"] = self.grading
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        for choice in self.choices:
            mark = "x" if choice.correct else " "
            yield from render.yield_choice(choice, mark=mark)

    def score_response(self, response: t.MultipleSelectionResponse) -> QuestionScore:
        """
        Score marked choices against their `correct` flags.

        A choice not in `response` asserts false, on par with one
        explicitly marked false. `"symmetric"` awards +-1/n per choice for
        each correct/incorrect judgement; `"partial"` is the same count
        but only over correctly-judged choices, so it never goes negative
        without needing a floor; `"all-or-nothing"` requires every choice
        judged correctly.
        """
        n = len(self.choices)
        marks = [(choice, choice.id in response) for choice in self.choices]
        judged_correctly = sum(1 for choice, mark in marks if mark == choice.correct)

        if self.grading == "all-or-nothing":
            score = 1.0 if judged_correctly == n else 0.0
        elif self.grading == "partial":
            score = judged_correctly / n
        else:
            score = (2 * judged_correctly - n) / n

        feedback = [
            choice.feedback
            for choice, mark in marks
            if mark != choice.correct and choice.feedback
        ]
        return QuestionScore(score=score, feedback=feedback)


class TrueFalseQuestion(BaseQuestion[t.TrueFalseResponse]):
    choices: Annotated[list[Statement], Field(min_length=2)]
    type: Literal["true-false"] = "true-false"
    shuffle: bool | None = None
    grading: GradingStrategy | None = None

    @model_validator(mode="after")
    def check_choices_are_unique(self) -> Self:
        """
        multiple-choice.md, "Choices" (shared by true-false): ids and
        texts must each be unique (`duplicate-choice-id`,
        `duplicate-choice-text`).
        """
        _check_unique_choices(type(self).__name__, self.choices)
        return self

    def with_ids(self) -> Self:
        """See `BaseQuestion.with_ids`."""
        return self.model_copy(update={"choices": _with_choice_ids(self.choices)})

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.shuffle is not None:
            data["shuffle"] = self.shuffle
        if self.grading is not None:
            data["grading"] = self.grading
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        for choice in self.choices:
            # Use locale to choose better markings?
            mark = "T" if choice.correct else "F"
            if choice.marker:
                mark = choice.marker
            yield from render.yield_choice(choice, mark=mark)

    def score_response(self, response: t.TrueFalseResponse) -> QuestionScore:
        """
        Score judged statements against their `correct` flags.

        `"partial"` is correct-count over total; `"symmetric"` also
        subtracts incorrect judgements; `"all-or-nothing"` zeroes out on
        any incorrect judgement, but still awards correct-count over total
        for a response that is merely incomplete. A statement missing from
        `response` counts as an abstention, like an explicit `None`.
        """
        n = len(self.choices)
        marks = [
            (statement, lookup(response, statement.id, None))
            for statement in self.choices
        ]
        correct = sum(1 for statement, mark in marks if mark == statement.correct)
        incorrect = sum(
            1
            for statement, mark in marks
            if mark is not None and mark != statement.correct
        )

        if self.grading == "all-or-nothing":
            score = 0.0 if incorrect else correct / n
        elif self.grading == "partial":
            score = correct / n
        else:
            score = (correct - incorrect) / n

        feedback = [
            statement.feedback
            for statement, mark in marks
            if mark != statement.correct and statement.feedback
        ]
        return QuestionScore(score=score, feedback=feedback)


class NumericQuestion(BaseQuestion[t.NumericResponse]):
    #: The correct value. A `str` carries an exact rational ("1/3"),
    #: which no float can represent.
    answer: float | str
    type: Literal["numeric"] = "numeric"
    unit: str | None = None
    domain: NumericDomain | None = None
    decimal_places: int | None = Field(default=None, ge=0)
    tolerance: Tolerance | None = None

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


class AnswerPattern(MdqModel):
    """
    One entry of an `accept`/`reject`/`preAccept`/`preReject` list.

    A bare string in the document is shorthand for a pattern with no
    feedback and no comment, so both spellings load into this model.
    """

    #: A regex when delimited by `/`, a lone `*` for the wildcard, and a
    #: plain literal otherwise. Not compiled here: an uncompilable regex
    #: must still load, so the linter can report `invalid-regex` on it.
    pattern: Annotated[str, Field(min_length=1, pattern=r"\S")]
    feedback: str | None = None
    comment: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_string(cls, value: Any) -> Any:
        """Expand the bare-string shorthand into the object form."""
        return {"pattern": value} if isinstance(value, str) else value

    def matches(self, response: str, *, diacritics: Diacritics = "fold") -> bool:
        """
        Report whether `response` satisfies this pattern.

        A backtick-enclosed literal is compared verbatim (only its ends
        trimmed); a bare literal is compared after normalization, which
        `diacritics` tunes: `"fold"` strips diacritics as it always did,
        `"keep"` leaves them so `Maceió` rejects `Maceio`; a regex sees
        the raw response and lets its own flags decide -- normalizing
        first would make a case-sensitive regex impossible, and neither
        it nor the backtick/`*` forms consult `diacritics` at all.
        """
        pattern = self.pattern.strip()
        if pattern == "*":
            return True
        if pattern.startswith("/"):
            return RegexPattern(pattern).match(response)
        if pattern.startswith("`") and pattern.endswith("`") and len(pattern) >= 2:
            return response.strip() == pattern[1:-1].strip()
        return normalize_text(response, diacritics=diacritics) == normalize_text(
            pattern, diacritics=diacritics
        )


class ShortAnswerQuestion(BaseQuestion[t.TextResponse]):
    type: Literal["short-answer"] = "short-answer"
    one_of: list[str] | None = None
    regex: str | None = None

    #: Grading rules. `accept` decides the score and wins over `reject`
    #: when both match; `reject` only attaches feedback to answers known
    #: to be wrong.
    accept: list[AnswerPattern] | None = None
    reject: list[AnswerPattern] | None = None

    #: Pre-submission validators. A system warns the student before
    #: accepting the answer; grading ignores them entirely.
    pre_accept: list[AnswerPattern] | None = None
    pre_reject: list[AnswerPattern] | None = None

    #: When true the question has no machine-checkable key and is graded
    #: by hand, so `oneOf`, `regex`, `accept` and `reject` must all be
    #: absent.
    open_ended: bool = False

    #: How inexact literals treat diacritics, in every pattern list.
    diacritics: Diacritics = "fold"

    @model_validator(mode="after")
    def check_open_ended_has_no_answer_key(self) -> Self:
        """
        `openEnded` means there is nothing to grade against
        (short-answer.md), so it contradicts any of the fields that
        would otherwise supply one.

        Raises:
            ValueError: `open_ended` is set alongside `one_of`, `regex`,
                `accept` or `reject`.
        """
        if self.open_ended and (
            self.one_of is not None
            or self.regex is not None
            or self.accept is not None
            or self.reject is not None
        ):
            raise ValueError(
                "openEnded has no answer key: it must not be combined with "
                "oneOf, regex, accept or reject"
            )
        return self

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.open_ended:
            data["openEnded"] = True
        if self.diacritics != "fold":
            data["diacritics"] = self.diacritics
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        tag = "[short-answer]"
        if self.accept is not None or self.reject is not None:
            yield from render_pattern_block("accept", self.accept)
            yield from render_pattern_block("reject", self.reject)
        elif self.regex is not None:
            yield f"{tag}: /{self.regex}/"
        elif self.one_of is None:
            yield f"{tag}:"
        elif len(self.one_of) == 1:
            yield f"{tag}: {self.one_of[0]}"
        else:
            yield f"{tag}:"
            for answer in self.one_of:
                yield f"* {answer}"

    def effective_accept(self) -> list[AnswerPattern]:
        """
        Return the accept list grading uses, desugaring the legacy fields.

        `accept` wins when set. Otherwise `regex` -- which still takes
        precedence over `one_of` -- becomes a single delimited pattern.
        """
        if self.accept is not None:
            return self.accept
        if self.regex is not None:
            return [AnswerPattern(pattern=f"/{self.regex}/")]
        return [AnswerPattern(pattern=answer) for answer in self.one_of or []]

    def score_response(self, response: t.TextResponse) -> QuestionScore:
        """
        Score 1 if `response` matches an accept pattern, else 0.

        Raises:
            NotAutoGradable: the question has no answer key. A question
                carrying only `reject` lands here too: with nothing to
                accept it could never mark an answer correct.
        """
        accept = self.effective_accept()
        if self.open_ended or not accept:
            raise NotAutoGradable(
                "short-answer question has no machine-checkable answer key"
            )
        correct = any(
            rule.matches(response, diacritics=self.diacritics) for rule in accept
        )
        deciding = accept if correct else (self.reject or [])
        return QuestionScore(
            score=1.0 if correct else 0.0,
            feedback=first_feedback(deciding, response, diacritics=self.diacritics),
        )


class EssayQuestion(BaseQuestion[t.TextResponse]):
    type: Literal["essay"] = "essay"
    input: EssayInput = "text"
    highlight: str | None = None

    #: A model answer for the human grading this. Carrying one does not
    #: make the question auto-gradable.
    answer_key: str | None = None

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.input != "text":
            data["input"] = self.input
        if self.highlight is not None:
            data["highlight"] = self.highlight
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        yield "[essay]"

    def score_response(self, response: t.TextResponse) -> QuestionScore:
        """
        Never gradable automatically.

        Raises:
            NotAutoGradable: always.
        """
        raise NotAutoGradable("essay questions require manual grading")

    def _render_lines(self) -> Iterable[str]:
        yield from super()._render_lines()
        if self.answer_key is not None:
            yield ""
            yield "## [answer-key]"
            yield ""
            yield self.answer_key


class ChoiceBlank(MdqModel):
    id: str
    type: Literal["multiple-choice"] = "multiple-choice"
    choices: list[ScoredChoice]

    @model_validator(mode="after")
    def check_choices_are_unique(self) -> Self:
        """
        multiple-choice.md, "Choices" (shared by a fill-in choice
        blank): ids and texts must each be unique (`duplicate-choice-id`,
        `duplicate-choice-text`).
        """
        _check_unique_choices(type(self).__name__, self.choices)
        return self


class ShortAnswerBlank(MdqModel):
    id: str
    type: Literal["short-answer"] = "short-answer"
    one_of: list[str] | None = None
    regex: str | None = None
    accept: list[AnswerPattern] | None = None
    reject: list[AnswerPattern] | None = None
    pre_accept: list[AnswerPattern] | None = None
    pre_reject: list[AnswerPattern] | None = None


class NumericBlank(MdqModel):
    id: str
    type: Literal["numeric"] = "numeric"
    answer: float | str
    unit: str | None = None
    domain: NumericDomain | None = None
    decimal_places: Annotated[int | None, Field(ge=0)] = None
    tolerance: Tolerance | None = None


Blank = Annotated[
    ChoiceBlank | ShortAnswerBlank | NumericBlank,
    Field(discriminator="type"),
]


class FillInQuestion(BaseQuestion[t.FillInResponse]):
    blanks: list[Blank]
    type: Literal["fill-in"] = "fill-in"
    shuffle: bool | None = None
    grading: GradingStrategy | None = None

    #: How inexact literals treat diacritics, in every short answer blank.
    diacritics: Diacritics = "fold"

    @model_validator(mode="after")
    def check_blanks_have_unique_ids(self) -> Self:
        """
        fill-in.md: two blanks sharing an id make the stem's `[^id]`
        marker ambiguous (`duplicate-blank-id`).
        """
        seen: dict[str, int] = {}
        for index, blank in enumerate(self.blanks):
            first_index = seen.get(blank.id)
            if first_index is not None:
                _raise_unique_id_error(
                    type(self).__name__,
                    "duplicate-blank-id",
                    (
                        f"blank id {blank.id!r} is already used by "
                        f"blanks[{first_index}]; the stem's [^{blank.id}] "
                        f"marker is ambiguous"
                    ),
                    ("blanks", index, "id"),
                    blank.id,
                )
            seen[blank.id] = index
        return self

    def with_ids(self) -> Self:
        """
        See `BaseQuestion.with_ids`.

        Only a `ChoiceBlank`'s own choices get a derived id -- a blank's
        `id` is required already (it names the `[^id]` marker in the
        stem), and short-answer/numeric blanks have no choices at all.
        """
        new_blanks = [
            blank.model_copy(update={"choices": _with_choice_ids(blank.choices)})
            if isinstance(blank, ChoiceBlank)
            else blank
            for blank in self.blanks
        ]
        return self.model_copy(update={"blanks": new_blanks})

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.shuffle is not None:
            data["shuffle"] = self.shuffle
        if self.grading is not None:
            data["grading"] = self.grading
        if self.diacritics != "fold":
            data["diacritics"] = self.diacritics
        return data

    def _render_body(self) -> Iterable[str]:
        for blank in self.blanks:
            yield ""
            if isinstance(blank, ChoiceBlank):
                yield f"[^{blank.id}]:"
                for choice in blank.choices:
                    score = choice.score
                    if score == 1.0:
                        mark = "*"
                    elif score in (0.0, None):
                        mark = " "
                    else:
                        mark = f"{score * 100}%"
                    yield from render.yield_choice(choice, mark=mark)
            elif isinstance(blank, ShortAnswerBlank):
                tag = f"^{blank.id}/short-answer"
                if blank.regex is not None:
                    yield f"[{tag}]: /{blank.regex}/"
                elif blank.one_of:
                    yield f"[{tag}]: {blank.one_of[0]}"
                if blank.accept is not None or blank.reject is not None:
                    if blank.regex is not None or blank.one_of:
                        yield ""
                    yield from render_pattern_block("accept", blank.accept, tag)
                    yield from render_pattern_block("reject", blank.reject, tag)
            else:
                yield render_numeric_tag(
                    blank.answer,
                    tag=f"[^{blank.id}/numeric]",
                    unit=blank.unit,
                    tolerance=blank.tolerance,
                )

    def score_response(self, response: t.FillInResponse) -> QuestionScore:
        """
        Score each blank independently and combine by `grading`.

        Raises:
            ResponseError: a blank's response doesn't match its type.
        """
        scores: list[float] = []
        feedback: list[str] = []

        for blank in self.blanks:
            sub_response = response.get(blank.id)
            if isinstance(blank, ChoiceBlank):
                if sub_response is None:
                    scores.append(0.0)
                    continue
                choice = next((c for c in blank.choices if c.id == sub_response), None)
                if choice is None:
                    raise ResponseError(
                        f"Response id {sub_response!r} not found in blank {blank.id!r}"
                    )
                scores.append(choice.score or 0.0)
                if choice.feedback:
                    feedback.append(choice.feedback)
            elif isinstance(blank, ShortAnswerBlank):
                if sub_response is None:
                    scores.append(0.0)
                    continue
                if not isinstance(sub_response, str):
                    raise ResponseError(
                        f"Response {sub_response!r} to blank {blank.id!r} is not text"
                    )
                correct = short_answer_matches(
                    sub_response,
                    one_of=blank.one_of,
                    regex=blank.regex,
                    accept=blank.accept,
                    diacritics=self.diacritics,
                )
                scores.append(1.0 if correct else 0.0)
            else:
                if sub_response is None:
                    scores.append(0.0)
                    continue
                if not isinstance(sub_response, int | float | Fraction):
                    raise ResponseError(
                        f"Response {sub_response!r} to blank {blank.id!r} is not numeric"
                    )
                correct = numeric_matches(blank.answer, sub_response, blank.tolerance)
                scores.append(1.0 if correct else 0.0)

        mean = sum(scores) / len(scores)

        if self.grading == "all-or-nothing":
            score = 1.0 if all(s == 1.0 for s in scores) else 0.0
        elif self.grading == "partial":
            score = max(0.0, mean)
        else:
            score = mean

        return QuestionScore(score=score, feedback=feedback)


#
# Ordering
#
#: One line of an ordering question, as an `[indentation level, text]`
#: pair. The level counts indentation units, not spaces, and the text
#: carries no leading indentation of its own.
OrderingLine = tuple[Annotated[int, Field(ge=0)], str]


class OrderingAlternative(MdqModel):
    """
    One accepted or rejected ordering of a question's lines, with the
    feedback shown to the student whose response matched it.
    """

    lines: list[OrderingLine]
    feedback: str | None = None
    comment: str | None = None


class OrderingQuestion(BaseQuestion[t.OrderingResponse]):
    """
    A question asking the student to sort a list of lines.

    `lines` is the answer key, always authored in the correct order; the
    student is always shown it shuffled, together with `extra`.
    """

    type: Literal["ordering"] = "ordering"
    lines: Annotated[list[OrderingLine], Field(min_length=2)]
    extra: list[OrderingLine] = Field(default_factory=list)
    accept: list[OrderingAlternative] = Field(default_factory=list)
    reject: list[OrderingAlternative] = Field(default_factory=list)
    content: OrderingContent = "text"
    highlight: str | None = None
    indentation: Indentation = "fixed"
    unmatched: Unmatched = "manual"
    normalizations: list[Normalization] = Field(default_factory=list)

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.indentation != "fixed":
            data["indentation"] = self.indentation
        if self.unmatched != "manual":
            data["unmatched"] = self.unmatched
        if self.normalizations:
            data["normalizations"] = self.normalizations
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        yield "[ordering]"
        yield from render.yield_ordering_content(self.lines, self.content, self.highlight)
        if self.extra:
            yield from render.yield_ordering_section(
                "extra", self.extra, self.content, self.highlight
            )
        for alt in self.accept:
            yield from render.yield_ordering_section(
                "accept", alt.lines, self.content, self.highlight, alt.feedback, alt.comment
            )
        for alt in self.reject:
            yield from render.yield_ordering_section(
                "reject", alt.lines, self.content, self.highlight, alt.feedback, alt.comment
            )

    @model_validator(mode="after")
    def check_accept_and_reject_disjoint(self) -> Self:
        """
        A question MUST NOT declare the same lines as both accepted and
        rejected (ordering.md#additional-rules).

        Raises:
            ValueError: some `accept` entry holds the same lines as some
                `reject` entry.
        """
        reject_lines = {tuple(alt.lines) for alt in self.reject}
        for alt in self.accept:
            if tuple(alt.lines) in reject_lines:
                raise ValueError(
                    "the same lines must not be declared in both accept and reject"
                )
        return self

    def effective_normalizations(self) -> set[Normalization]:
        """
        The normalizations grading actually applies, including the
        `dedent` that `indentation: lenient` implies.
        """
        normalizations = set(self.normalizations)
        if self.indentation == "lenient":
            normalizations.add("dedent")
        return normalizations

    def grades_indentation(self) -> bool:
        """
        Whether a line's indentation level takes part in the comparison.

        Only `"strict"` without an effective `dedent` compares levels:
        `dedent` flattens every level to 0, and `"lenient"` implies it.
        """
        return self.indentation == "strict" and "dedent" not in (
            self.effective_normalizations()
        )

    def comparison_key(self, lines: Iterable[OrderingLine]) -> tuple[OrderingLine, ...]:
        """
        The form `lines` takes when compared: this question's
        normalizations applied, and every level flattened to 0 unless
        indentation is graded.
        """
        graded = self.grades_indentation()
        skip_blanks = "skip-blanks" in self.effective_normalizations()
        key = []
        for level, text in lines:
            if skip_blanks and text.strip() == "":
                continue
            key.append((level if graded else 0, text))
        return tuple(key)

    def score_response(self, response: t.OrderingResponse) -> QuestionScore:
        """
        Score 1 for the answer key or an accepted ordering, 0 for a
        rejected one, and otherwise whatever `unmatched` dictates.

        Raises:
            ResponseError: `response` is not a sequence of
                `[indentation level, text]` pairs.
            NotAutoGradable: nothing matched and `unmatched` is
                "manual", so the response is for a human to score.
        """
        key = self.comparison_key(coerce_ordering_lines(response))

        if key == self.comparison_key(self.lines):
            return QuestionScore(score=1.0)

        for alt in self.accept:
            if key == self.comparison_key(alt.lines):
                feedback = [alt.feedback] if alt.feedback else []
                return QuestionScore(score=1.0, feedback=feedback)

        for alt in self.reject:
            if key == self.comparison_key(alt.lines):
                feedback = [alt.feedback] if alt.feedback else []
                return QuestionScore(score=0.0, feedback=feedback)

        if self.unmatched == "incorrect":
            return QuestionScore(score=0.0)
        raise NotAutoGradable(
            "ordering response matched no answer key and requires manual grading"
        )


Question = Annotated[
    MultipleChoiceQuestion
    | MultipleSelectionQuestion
    | TrueFalseQuestion
    | NumericQuestion
    | ShortAnswerQuestion
    | EssayQuestion
    | FillInQuestion
    | OrderingQuestion,
    Field(discriminator="type"),
]


class QuestionRoot(RootModel):
    root: Question


#
# Exams
#
class Exam(MdqModel):
    """
    A resolved exam.
    """

    type: Literal["exam"] = "exam"
    id: str | None = None
    uuid: str | None = None
    title: str | None = None
    description: Annotated[str | None, Field(default=None, min_length=1)] = None
    course: str | None = None
    author: str | None = None
    locale: str | None = None
    instructions: str | None = None
    tags: list[str] | None = None
    meta: dict[str, object] | None = None
    penalty: PenaltyPolicy = "none"
    grading: ExamGrading = "symmetric"
    start: ExamStart | None = None
    duration: ExamDuration | None = None
    questions: list[Question]

    @model_validator(mode="after")
    def check_questions_have_unique_ids(self) -> Self:
        """
        exam.md, "Question ids": declared ids MUST be unique within the
        exam, once includes are resolved -- and none of them may equal
        the implicit, position-based id (`q1`, `q2`, ...) another
        question would get. Neither the parser nor this model fills
        implicit ids in; `with_ids()` does that once the exam already
        validated (dev/specs/to-do/derived-ids.md). This validator only
        computes them, to catch the collision early. A question with
        neither a declared id nor a colliding implicit one does not
        participate: there is nothing to collide.
        """
        seen: dict[str, int] = {}
        for index, question in enumerate(self.questions):
            question_id = question.id
            if question_id is None:
                continue
            first_index = seen.get(question_id)
            if first_index is not None:
                _raise_unique_id_error(
                    type(self).__name__,
                    "duplicate-question-id",
                    (
                        f"question id {question_id!r} is already used by "
                        f"questions[{first_index}]"
                    ),
                    ("questions", index),
                    question_id,
                )
            seen[question_id] = index

        for index, question in enumerate(self.questions):
            if question.id is not None:
                continue
            implicit_id = _implicit_question_id(index)
            colliding_index = seen.get(implicit_id)
            if colliding_index is not None:
                _raise_unique_id_error(
                    type(self).__name__,
                    "duplicate-question-id",
                    (
                        f"question id {implicit_id!r}, the implicit id "
                        f"questions[{index}] would get, is already used by "
                        f"questions[{colliding_index}]"
                    ),
                    ("questions", index),
                    implicit_id,
                )
        return self

    def with_ids(self) -> Self:
        """
        Return a copy of this exam in which every question -- and every
        one of its choices -- has an id, so a response can name what it
        refers to (GLOSSARY.md, "Addressable").

        A question with no explicit id gets the implicit one for its
        position, `q<position>`, counting every block in the exam,
        includes included (exam.md, "Question ids"); an explicit id is
        never touched. Every question then runs its own `with_ids()`, so
        its choices get theirs too. Never changes `self`, and running it
        twice gives the same result as running it once.
        """
        new_questions = [
            question.with_ids()
            if question.id is not None
            else question.with_ids().model_copy(
                update={"id": _implicit_question_id(index)}
            )
            for index, question in enumerate(self.questions)
        ]
        return self.model_copy(update={"questions": new_questions})

    def model_post_init(self, __ctx):
        for i, question in enumerate(self.questions):
            if question.exam is not None:
                raise ValueError(f"Question at index {i} already belongs to an exam")

        for question in self.questions:
            question._exam = weakref.ref(self)

    def add_question(self, question: Question, position: int | None = None):
        """
        Add a question to the exam at `position`, or at the end if
        `position` is `None`.

        Question cannot be bound to another exam.
        """
        if question.exam not in (self, None):
            raise ValueError("Question already belongs to another exam")
        if position is None:
            self.questions.append(question)
        else:
            self.questions.insert(position, question)
        question._exam = weakref.ref(self)


#
# Grading results
#
class QuestionScore(MdqModel):
    """
    What one response to one question was worth.

    `score` is the raw value, in [-1, 1], with no exam policy applied.
    """

    score: float = Field(ge=-1, le=1)

    #: Feedback triggered by this response, in the order the choices
    #: appear in the document. What triggers it depends on the question
    #: type: the picked choice in multiple-choice, wrongly judged
    #: choices in multiple-selection, wrongly judged or unjudged
    #: statements in true-false. A skipped question triggers none.
    feedback: list[str] = Field(default_factory=list)


class ExamScore(MdqModel):
    """
    What a whole exam attempt was worth.

    Covers auto-gradable questions only. `score` is the weighted mean of
    their scores after the exam's `penalty` policy is applied, and is
    `None` when nothing was auto-gradable -- an exam of essays, or one
    where every weight is zero. `None` is not a zero: it means no
    auto-grade exists.
    """

    score: float | None = Field(default=None, ge=-1, le=1)

    #: Weight of the questions that `score` covers, and of the whole
    #: exam. Two absolute values rather than a fraction, so "0.8 over
    #: 70% of the exam" needs no guessing about the denominator.
    graded_weight: float = Field(ge=0)
    total_weight: float = Field(ge=0)

    #: Ids of the questions awaiting a human grader. These are absent
    #: from `questions`; the union of the two is the exam.
    pending: list[str] = Field(default_factory=list)

    #: Per-question results, keyed by question id, for the auto-gradable
    #: questions only.
    questions: dict[str, QuestionScore] = Field(default_factory=dict)


#
# Utilities
#
def _reinject_type_discriminators(model: BaseModel, data: dict[str, Any]) -> None:
    """
    Walk `model` and its already-dumped `data` in lockstep, re-adding the
    `type` discriminator `exclude_defaults` stripped from any nested
    `MdqModel` (a question inside an exam, a blank inside a fill-in).

    `model_dump`'s recursion applies `exclude_defaults` at every level, not
    just the top one `MdqModel.to_dict` patches up by hand, so a nested
    discriminated model loses `type` the same way the top-level one would
    without that patch. Mutates `data` in place; `model` itself is read-only.
    """
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        key = field.alias or name
        if key not in data:
            continue
        if isinstance(value, MdqModel):
            nested_data = data[key]
            _reinject_type_discriminators(value, nested_data)
            if "type" in type(value).model_fields and "type" not in nested_data:
                nested_data["type"] = getattr(value, "type")
        elif isinstance(value, list):
            for item, nested_data in zip(value, data[key], strict=False):
                if not isinstance(item, MdqModel):
                    continue
                _reinject_type_discriminators(item, nested_data)
                if "type" in type(item).model_fields and "type" not in nested_data:
                    nested_data["type"] = getattr(item, "type")


def clear_nones(d: dict[str, Any]) -> dict[str, Any]:
    """
    Return a copy of `d` with all `None` values removed.
    """
    return {k: v for k, v in d.items() if v is not None}


def lookup[V](response: dict[str, V], key: str | None, default: V) -> V:
    """Look up `key` in `response`, returning `default` if `key` is `None`."""
    if key is None:
        return default
    return response.get(key, default)


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


def normalize_text(value: str, *, diacritics: Diacritics = "fold") -> str:
    """
    Fold case and collapse whitespace to single spaces, for the plain
    literal comparison in `AnswerPattern.matches`.

    `diacritics="fold"` also strips diacritics (NFKC then accent
    stripping); `"keep"` only applies NFKC, so an NFD and an NFC
    spelling of the same accented text still compare equal.
    """
    value = unicodedata.normalize("NFKC", value)
    if diacritics == "fold":
        value = strip_accents(value)
    return re.sub(r"\s+", " ", value).casefold().strip()


def render_pattern_block(
    variant: str, patterns: list[AnswerPattern] | None, tag: str = "short-answer"
) -> Iterable[str]:
    """
    Render one `accept` or `reject` pattern block.

    `tag` names the owning construct: the default renders a standalone
    question's `[short-answer/accept]`, while a fill-in blank passes
    `^<id>/short-answer` to render `[^<id>/short-answer/accept]`.
    """
    if patterns is None:
        return
    yield f"[{tag}/{variant}]:"
    for rule in patterns:
        yield f"* {rule.pattern}"
        if rule.feedback is not None:
            yield f"  > {rule.feedback}"
        if rule.comment is not None:
            yield f"  ! {rule.comment}"
    yield ""


def coerce_ordering_lines(lines: t.OrderingResponse) -> list[OrderingLine]:
    """
    Read a JSON-shaped ordering response as `[level, text]` pairs.

    Raises:
        ResponseError: some entry is not an `[int, str]` pair.
    """
    result = []
    for entry in lines:
        if not isinstance(entry, list | tuple) or len(entry) != 2:
            raise ResponseError(f"Line {entry!r} is not a [level, text] pair")
        level, text = entry
        if isinstance(level, bool) or not isinstance(level, int) or level < 0:
            raise ResponseError(f"Line level {level!r} is not a non-negative int")
        if not isinstance(text, str):
            raise ResponseError(f"Line text {text!r} is not a string")
        result.append((level, text))
    return result


def first_feedback(
    patterns: list[AnswerPattern], response: str, *, diacritics: Diacritics = "fold"
) -> list[str]:
    """
    Return the feedback of the first matching pattern that defines one.

    "First that matches AND carries feedback" is not the same as "first
    that matches": an earlier match with no message is passed over.
    `diacritics` is forwarded to each pattern's `matches`.
    """
    for rule in patterns:
        if rule.feedback is not None and rule.matches(response, diacritics=diacritics):
            return [rule.feedback]
    return []


def short_answer_matches(
    response: str,
    *,
    one_of: list[str] | None,
    regex: str | None,
    accept: list[AnswerPattern] | None = None,
    diacritics: Diacritics = "fold",
) -> bool:
    """
    Report whether `response` matches `accept`, `regex` or `one_of`.

    `accept` wins over both legacy fields, and `regex` over `one_of`.
    Matching is always a full match, never a search. `diacritics`
    applies to the plain-literal patterns in `accept`/`one_of`.
    """
    if accept is None:
        if regex is not None:
            accept = [AnswerPattern(pattern=f"/{regex}/")]
        else:
            accept = [AnswerPattern(pattern=answer) for answer in one_of or []]
    return any(rule.matches(response, diacritics=diacritics) for rule in accept)


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


def can_inline_id(preamble: str | None, stem: str) -> bool:
    """
    Report whether an inline `[id]` prefix would parse back correctly.

    See the comment in `BaseQuestion._render_lines` for why: it only
    round-trips when the block receiving the prefix -- the *first* block
    of the combined preamble+stem sequence, per `MDQParser.split_intro`
    -- is a plain paragraph. That is the preamble's own first block when
    there is a preamble; otherwise it's the stem's first block, which is
    not guaranteed to be a paragraph either -- a `stem` may legally span
    more than one Markdown block (see `normalize_intro`) unless the
    caller already normalized the model.
    """
    combined = f"{preamble}\n\n{stem}" if preamble else stem
    blocks = parser.reconstruct_blocks(combined.strip())
    return bool(blocks) and blocks[0][0] == "paragraph"


def normalize_paragraphs(src: str) -> str:
    """
    Normalize a string that is a Markdown paragraph or series of
    paragraphs.

    This is used to normalize the `preamble` and `epilogue` fields of
    questions, which are Markdown blocks but not full documents. Naively
    splitting on blank lines and stripping each chunk is not enough: a
    plain paragraph's soft-wrapped lines collapse to a single space once
    a render/parse round trip touches them (`MDQParser.raw_text`), while
    a list, blockquote, heading or code block survives byte-for-byte.
    `parser.reconstruct_blocks` applies the parser's own rule for each
    block instead of guessing, so this function is a fixed point of
    render-then-parse: normalizing again after a round trip is a no-op.
    """
    return "\n\n".join(text for _, text in parser.reconstruct_blocks(src))


def normalize_intro(preamble: str | None, stem: str) -> tuple[str | None, str]:
    """
    Normalize a question's `preamble` and `stem` fields together.

    `MDQParser.split_intro` does not care which field a block came from:
    it always assigns the *last* intro block to the stem and everything
    before it to the preamble. A `stem` spanning more than one Markdown
    block is legal per the schema (`schema/question-base.yaml`'s `stem`
    is just a non-empty string; `docs/question-types/generic.md` only
    *recommends* -- "SHOULD" -- a single paragraph), so it does not
    stay put on a render/parse round trip: every block but the last
    migrates into the preamble. Normalizing has to do the same to stay a
    fixed point of that round trip -- keeping only the first block
    (dropping the rest) or only the last would both be lossy, and either
    way would put the surviving block in the wrong field. Reconstructing
    `preamble` and `stem` together, rather than field by field, is what
    makes that possible.
    """
    combined = f"{preamble}\n\n{stem}" if preamble else stem
    blocks = parser.reconstruct_blocks(combined.strip())
    if not blocks:
        return None, stem.strip()
    new_stem = blocks[-1][1]
    new_preamble = "\n\n".join(text for _, text in blocks[:-1]) or None
    return new_preamble, new_stem


def remove_trailing_ws(src: str) -> str:
    """
    Remove trailing whitespace from each line in a string.
    """
    return "\n".join(line.rstrip() for line in src.split("\n"))

"""
Choice-based questions: multiple-choice, multiple-selection and
true-false, and their shared choice types (`ScoredChoice`,
`BooleanChoice`, `Statement`).

`mdq.models._fill_in` reuses `ScoredChoice` and `_with_choice_ids` for a
multiple-choice fill-in blank -- the one place a choice shape crosses
into another question family.
"""

from __future__ import annotations

from typing import Annotated, Any, Iterable, Literal, Self, Sequence

from pydantic import Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from .. import types as t
from .._diagnostics import Diagnostic
from .._letters import is_letter, normalize_value
from ..errors import ResponseError
from ..types import (
    GradingStrategy,
    MultipleChoiceGrading,
    MultipleChoiceQuestionGrading,
    MultipleSelectionGrading,
    MultipleSelectionQuestionGrading,
    QuestionGrading,
    QuestionShuffle,
    TrueFalseGrading,
)
from . import _lint, _render, _slugify
from ._base import (
    MdqModel,
    BaseQuestion,
    FreeText,
    SlugId,
    _check_unique_choices,
    _raise_unique_id_error,
)
from ._score import QuestionScore

__all__ = [
    "ScoredChoice",
    "BooleanChoice",
    "Statement",
    "MultipleChoiceQuestion",
    "MultipleSelectionQuestion",
    "TrueFalseQuestion",
]



def effective_grading(value: QuestionGrading) -> GradingStrategy:
    """Read `inherit` as the default strategy, `symmetric`."""
    return "symmetric" if value == "inherit" else value


def effective_shuffle(value: QuestionShuffle) -> bool:
    """Read `inherit` as the default, `False`."""
    return False if value == "inherit" else value


def write_shuffle_and_grading(
    data: dict[str, Any], shuffle: QuestionShuffle, grading: QuestionGrading
) -> None:
    """Add `shuffle` and `grading` to frontmatter `data`, unless they inherit."""
    if shuffle != "inherit":
        data["shuffle"] = shuffle
    if grading != "inherit":
        data["grading"] = grading


class ScoredChoice(MdqModel):
    """
    A multiple-choice option, or a choice inside a fill-in choice blank.

    `score` is bounded to [-1, 1]: 1 is correct, 0 incorrect, and a
    negative value penalises picking it.
    """

    id: SlugId | None = None
    text: FreeText
    score: Annotated[float | None, Field(default=None, ge=-1, le=1)] = None
    feedback: FreeText | None = None
    comment: FreeText | None = None


class BooleanChoice(MdqModel):
    """
    A multiple-selection option: the key says whether it belongs in the
    answer, and there is no per-choice score.
    """

    id: SlugId | None = None
    text: FreeText
    correct: bool
    feedback: FreeText | None = None
    comment: FreeText | None = None


class Statement(MdqModel):
    """
    One true/false statement. Structurally a `BooleanChoice` plus the
    marker that spelled it in the Markdown source.
    """

    id: SlugId | None = None
    text: FreeText
    correct: bool
    marker: str | None = None
    feedback: FreeText | None = None
    comment: FreeText | None = None

    @field_validator("marker")
    @classmethod
    def check_marker(cls, value: str | None) -> str | None:
        """
        true-false.md, "Additional Rules": a marker is a single letter:
        its normalized value is one code point in `LETTER`
        (`malformed-true-false-marker`). `X`/`x`, also in a compatibility
        form such as `Ｘ`, marks a selected multiple-selection choice and
        never means true or false (`reserved-true-false-marker`).
        """
        if value is None:
            return value
        if not is_letter(normalize_value(value)):
            raise PydanticCustomError(
                "malformed-true-false-marker",
                f"{value!r} is not a true/false marker: a marker is a single letter",
            )
        if normalize_value(value) == "x":
            raise PydanticCustomError(
                "reserved-true-false-marker",
                f"{value!r} marks a selected multiple-selection choice "
                f"and has no true/false meaning",
            )
        return value


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
    collides (`mdq.models._slugify.loose`). Returns a new list; a choice that
    already has an id is returned as-is.
    """
    missing = [choice for choice in choices if choice.id is None]
    if not missing:
        return list(choices)

    forbid = {choice.id for choice in choices if choice.id is not None}
    derived = _slugify.loose(
        frozenset(choice.text for choice in missing), forbid=frozenset(forbid)
    )
    return [
        choice
        if choice.id is not None
        else choice.model_copy(update={"id": derived[choice.text]})
        for choice in choices
    ]



def unspecified_choice_score(choices: Sequence[ScoredChoice], *, symmetric: bool) -> float:
    """
    The score of a picked choice that declares none (multiple-choice.md,
    "Grading"). It is 0 under `partial`. Under `symmetric` it spreads the
    negative of the declared scores evenly over the choices that declare
    none, clamped to [-1, 0]. A fill-in choice blank uses it too.
    """
    if not symmetric:
        return 0.0
    declared = [c.score for c in choices if c.score is not None]
    missing = len(choices) - len(declared)
    if not missing:
        return 0.0
    return max(-1.0, min(0.0, -sum(declared) / missing))


class MultipleChoiceQuestion(BaseQuestion[t.MultipleChoiceResponse]):
    choices: Annotated[list[ScoredChoice], Field(min_length=2)]
    type: Literal["multiple-choice"] = "multiple-choice"
    shuffle: QuestionShuffle = "inherit"
    grading: MultipleChoiceQuestionGrading = "inherit"

    def effective_grading(self) -> MultipleChoiceGrading:
        """The question's `grading`, with `inherit` read as `symmetric`."""
        return "symmetric" if self.grading == "inherit" else self.grading

    def effective_shuffle(self) -> bool:
        """The question's `shuffle`, with `inherit` read as `False`."""
        return effective_shuffle(self.shuffle)

    @model_validator(mode="after")
    def check_choices_are_unique(self) -> Self:
        """
        multiple-choice.md, "Choices": no choice's `text` may be empty
        (`blank-text`), and ids and texts must each be unique
        (`duplicate-choice-id`, `duplicate-choice-text`).
        """
        _check_unique_choices(type(self).__name__, self.choices)
        return self

    def with_ids(self) -> Self:
        """See `BaseQuestion.with_ids`."""
        return self.model_copy(update={"choices": _with_choice_ids(self.choices)})

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(_lint.check_choice_ids_defined(self.choices, ("choices",)))
        diagnostics.extend(_lint.check_choices_visually_identical(self.choices, ("choices",)))
        diagnostics.extend(_lint.check_multiple_choice_answers(self.choices, ("choices",)))
        return diagnostics

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        write_shuffle_and_grading(data, self.shuffle, self.grading)
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        for choice in self.choices:
            yield from _render.yield_choice(choice, mark=_render.score_mark(choice.score))

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

        `"partial"` treats it as zero. `"symmetric"`
        spreads the negative of the declared scores evenly over the choices
        that declare none, so picking at random averages zero, then clamps
        the result to [-1, 0].
        """
        return unspecified_choice_score(
            self.choices, symmetric=self.effective_grading() == "symmetric"
        )


class MultipleSelectionQuestion(BaseQuestion[t.MultipleSelectionResponse]):
    choices: Annotated[list[BooleanChoice], Field(min_length=2)]
    type: Literal["multiple-selection"] = "multiple-selection"
    shuffle: QuestionShuffle = "inherit"
    grading: MultipleSelectionQuestionGrading = "inherit"

    def effective_grading(self) -> MultipleSelectionGrading:
        """The question's `grading`, with `inherit` read as `symmetric`."""
        return "symmetric" if self.grading == "inherit" else self.grading

    def effective_shuffle(self) -> bool:
        """The question's `shuffle`, with `inherit` read as `False`."""
        return effective_shuffle(self.shuffle)

    @model_validator(mode="after")
    def check_choices_are_unique(self) -> Self:
        """
        multiple-choice.md, "Choices" (shared by multiple-selection): no
        choice's `text` may be empty (`blank-text`), and ids and
        texts must each be unique (`duplicate-choice-id`,
        `duplicate-choice-text`).
        """
        _check_unique_choices(type(self).__name__, self.choices)
        return self

    def with_ids(self) -> Self:
        """See `BaseQuestion.with_ids`."""
        return self.model_copy(update={"choices": _with_choice_ids(self.choices)})

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(_lint.check_choice_ids_defined(self.choices, ("choices",)))
        diagnostics.extend(_lint.check_choices_visually_identical(self.choices, ("choices",)))
        diagnostics.extend(_lint.check_multiple_selection_answers(self.choices, ("choices",)))
        return diagnostics

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        write_shuffle_and_grading(data, self.shuffle, self.grading)
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        for choice in self.choices:
            mark = "x" if choice.correct else " "
            yield from _render.yield_choice(choice, mark=mark)

    def score_response(self, response: t.MultipleSelectionResponse) -> QuestionScore:
        """
        Score marked choices against their `correct` flags.

        `response` is the set of ticked choice ids; a choice not in it
        asserts false. `"symmetric"` awards +-1/n per choice for
        each correct/incorrect judgement; `"partial"` is the same count
        but only over correctly-judged choices, so it never goes negative
        without needing a floor; `"all-or-nothing"` requires every choice
        judged correctly.

        Raises:
            ResponseError: an element of `response` is not a string, or
                names no choice of the question.
        """
        known = {choice.id for choice in self.choices}
        for tick in response:
            if not isinstance(tick, str):
                raise ResponseError(f"Ticked id {tick!r} is not a string")
        unknown = sorted(tick for tick in response if tick not in known)
        if unknown:
            raise ResponseError(f"Ticked ids {unknown!r} not found in choices")
        n = len(self.choices)
        marks = [(choice, choice.id in response) for choice in self.choices]
        judged_correctly = sum(1 for choice, mark in marks if mark == choice.correct)

        if self.effective_grading() == "all-or-nothing":
            score = 1.0 if judged_correctly == n else 0.0
        elif self.effective_grading() == "partial":
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
    shuffle: QuestionShuffle = "inherit"
    grading: QuestionGrading = "inherit"

    def effective_grading(self) -> TrueFalseGrading:
        """The question's `grading`, with `inherit` read as `symmetric`."""
        return effective_grading(self.grading)

    def effective_shuffle(self) -> bool:
        """The question's `shuffle`, with `inherit` read as `False`."""
        return effective_shuffle(self.shuffle)

    @model_validator(mode="after")
    def check_choices_are_unique(self) -> Self:
        """
        multiple-choice.md, "Choices" (shared by true-false): no choice's
        `text` may be empty (`blank-text`), and ids and texts must
        each be unique (`duplicate-choice-id`, `duplicate-choice-text`).
        """
        _check_unique_choices(type(self).__name__, self.choices)
        return self

    @model_validator(mode="after")
    def check_markers_agree_with_correct(self) -> Self:
        """
        true-false.md:64-66,210: a marker's category (TRUE/FALSE/
        WARNING, see `mdq._lint.TRUE_MARKERS`/`FALSE_MARKERS`) must
        agree with `correct`. A FALSE-category marker disagrees with
        `correct: true`; a TRUE- or WARNING-category marker --
        WARNING letters also represent true, per the spec's "Body"
        section -- disagrees with `correct: false`. A WARNING marker
        paired with `correct: true` still SHOULD warn
        (`mdq._lint.check_true_false_markers`).
        The reserved `X`/`x` marker is rejected at the field level, so it
        never reaches here.
        """
        for index, choice in enumerate(self.choices):
            marker = choice.marker
            if marker is None:
                continue
            # FALSE-category means false; everything else (TRUE or
            # WARNING) reads as true.
            expected_correct = normalize_value(marker) not in _lint.FALSE_MARKERS
            disagrees = choice.correct != expected_correct
            if disagrees:
                _raise_unique_id_error(
                    type(self).__name__,
                    "true-false-marker-disagrees-with-correct",
                    (
                        f"marker {marker!r} disagrees with correct="
                        f"{choice.correct!r} for choices[{index}]"
                    ),
                    ("choices", index, "marker"),
                    marker,
                )
        return self

    def with_ids(self) -> Self:
        """See `BaseQuestion.with_ids`."""
        return self.model_copy(update={"choices": _with_choice_ids(self.choices)})

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(_lint.check_choice_ids_defined(self.choices, ("choices",)))
        diagnostics.extend(_lint.check_choices_visually_identical(self.choices, ("choices",)))
        diagnostics.extend(_lint.check_true_false_markers(self.choices, self.locale))
        diagnostics.extend(_lint.check_true_false_uniform_answers(self.choices))
        diagnostics.extend(_lint.check_true_false_marker_nfkc(self.choices))
        return diagnostics

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        write_shuffle_and_grading(data, self.shuffle, self.grading)
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        for choice in self.choices:
            # A statement without `marker` is written as `T` or `F`.
            mark = "T" if choice.correct else "F"
            if choice.marker:
                mark = choice.marker
            yield from _render.yield_choice(choice, mark=mark)

    def score_response(self, response: t.TrueFalseResponse) -> QuestionScore:
        """
        Score judged statements against their `correct` flags.

        `"partial"` is correct-count over total; `"symmetric"` also
        subtracts incorrect judgements; `"no-mistakes"` zeroes out on any
        incorrect judgement, but still awards correct-count over total for
        a response that is merely incomplete; `"all-or-nothing"` is 1 only
        when every statement is judged correctly. A statement missing from
        `response` counts as an abstention, like an explicit `None`.

        Raises:
            ResponseError: a key of `response` names no statement, or a
                value is neither a boolean nor `None` (responses.md,
                "True/false").
        """
        known = {statement.id for statement in self.choices}
        unknown = sorted(key for key in response if key not in known)
        if unknown:
            raise ResponseError(f"Statement ids {unknown!r} not found in choices")
        for key, value in response.items():
            if value is not None and not isinstance(value, bool):
                raise ResponseError(
                    f"Response for statement {key!r} must be a boolean or null,"
                    f" got {value!r}"
                )
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

        if self.effective_grading() == "all-or-nothing":
            score = 1.0 if correct == n else 0.0
        elif self.effective_grading() == "no-mistakes":
            score = 0.0 if incorrect else correct / n
        elif self.effective_grading() == "partial":
            score = correct / n
        else:
            score = (correct - incorrect) / n

        feedback = [
            statement.feedback
            for statement, mark in marks
            if mark != statement.correct and statement.feedback
        ]
        return QuestionScore(score=score, feedback=feedback)




#
# Utilities
#

def lookup[V](response: dict[str, V], key: str | None, default: V) -> V:
    """Look up `key` in `response`, returning `default` if `key` is `None`."""
    if key is None:
        return default
    return response.get(key, default)



"""
Choice-based questions: multiple-choice, multiple-selection and
true-false, and their shared choice types (`ScoredChoice`,
`BooleanChoice`, `Statement`).

`mdq.models._fill_in` reuses `ScoredChoice` and `_with_choice_ids` for a
multiple-choice fill-in blank -- the one place a choice shape crosses
into another question family.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import (
    Annotated,
    Any,
    Iterable,
    Iterator,
    Literal,
    Self,
    Sequence,
    assert_never,
)

from pydantic import Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from .. import types as t
from .._diagnostics import Diagnostic
from .._letters import (
    FALSE_LETTERS,
    LOCALE_ROWS,
    TRUE_LETTERS,
    is_letter,
    nfkc,
    normalize_value,
)
from ..errors import ResponseError
from ..types import (
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
from ._lint_codes import diag
from ._score import QuestionScore

__all__ = [
    "ScoredChoice",
    "BooleanChoice",
    "Statement",
    "MultipleChoiceQuestion",
    "MultipleSelectionQuestion",
    "TrueFalseQuestion",
]



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
        its normalized value is one code point in `LETTER`, with no
        whitespace around it as written (`malformed-true-false-marker`). `X`/`x`, also in a compatibility
        form such as `Ｘ`, marks a selected multiple-selection choice and
        never means true or false (`reserved-true-false-marker`).
        """
        if value is None:
            return value
        if not is_letter(normalize_value(value)) or value != value.strip():
            raise PydanticCustomError(
                "malformed-true-false-marker",
                f"{value!r} is not a true/false marker: a marker is a single "
                "letter, with no whitespace around it",
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


class ChoiceQuestion[R, C: (ScoredChoice, BooleanChoice, Statement)](BaseQuestion[R]):
    """
    What multiple-choice, multiple-selection and true-false share: a list
    of choices that must be unique, and the `shuffle` and `grading`
    settings. Each subclass narrows `grading` to the strategies it supports.
    """

    choices: Annotated[list[C], Field(min_length=2)]
    #: Redeclared by each subclass with its `Literal`; declared here so the
    #: field keeps its place in the serialization order.
    type: str
    shuffle: QuestionShuffle = "inherit"
    grading: QuestionGrading = "inherit"

    def effective_shuffle(self) -> bool:
        """The question's `shuffle`, with `inherit` read as `False`."""
        return False if self.shuffle == "inherit" else self.shuffle

    @model_validator(mode="after")
    def check_choices_are_unique(self) -> Self:
        """
        multiple-choice.md, "Choices" (shared by multiple-selection and
        true-false): no choice's `text` may be empty (`blank-text`), and
        ids and texts must each be unique (`duplicate-choice-id`,
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
        diagnostics.extend(check_choice_ids_defined(self.choices, ("choices",)))
        diagnostics.extend(check_choices_visually_identical(self.choices, ("choices",)))
        return diagnostics

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        write_shuffle_and_grading(data, self.shuffle, self.grading)
        return data

    @abstractmethod
    def _mark(self, choice: C) -> str:
        """The mark written before `choice` in the Markdown source."""

    def _render_body(self) -> Iterable[str]:
        yield ""
        for choice in self.choices:
            yield from _render.yield_choice(choice, mark=self._mark(choice))


class MultipleChoiceQuestion(ChoiceQuestion[t.MultipleChoiceResponse, ScoredChoice]):
    type: Literal["multiple-choice"] = "multiple-choice"
    grading: MultipleChoiceQuestionGrading = "inherit"

    def effective_grading(self) -> MultipleChoiceGrading:
        """The question's `grading`, with `inherit` read as `symmetric`."""
        return "symmetric" if self.grading == "inherit" else self.grading

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(check_multiple_choice_answers(self.choices, ("choices",)))
        return diagnostics

    def _mark(self, choice: ScoredChoice) -> str:
        return _render.score_mark(choice.score)

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


class MultipleSelectionQuestion(ChoiceQuestion[t.MultipleSelectionResponse, BooleanChoice]):
    type: Literal["multiple-selection"] = "multiple-selection"
    grading: MultipleSelectionQuestionGrading = "inherit"

    def effective_grading(self) -> MultipleSelectionGrading:
        """The question's `grading`, with `inherit` read as `symmetric`."""
        return "symmetric" if self.grading == "inherit" else self.grading

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(check_multiple_selection_answers(self.choices, ("choices",)))
        return diagnostics

    def _mark(self, choice: BooleanChoice) -> str:
        return "x" if choice.correct else " "

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

        grading = self.effective_grading()
        match grading:
            case "all-or-nothing":
                score = 1.0 if judged_correctly == n else 0.0
            case "partial":
                score = judged_correctly / n
            case "symmetric":
                score = (2 * judged_correctly - n) / n
            case _:
                assert_never(grading)

        feedback = [
            choice.feedback
            for choice, mark in marks
            if mark != choice.correct and choice.feedback
        ]
        return QuestionScore(score=score, feedback=feedback)


class TrueFalseQuestion(ChoiceQuestion[t.TrueFalseResponse, Statement]):
    type: Literal["true-false"] = "true-false"

    def effective_grading(self) -> TrueFalseGrading:
        """The question's `grading`, with `inherit` read as `symmetric`."""
        return "symmetric" if self.grading == "inherit" else self.grading

    @model_validator(mode="after")
    def check_markers_agree_with_correct(self) -> Self:
        """
        true-false.md:64-66,210: a marker's category (TRUE/FALSE/
        WARNING, see `mdq._letters.TRUE_LETTERS`/`FALSE_LETTERS`) must
        agree with `correct`. A FALSE-category marker disagrees with
        `correct: true`; a TRUE- or WARNING-category marker --
        WARNING letters also represent true, per the spec's "Body"
        section -- disagrees with `correct: false`. A WARNING marker
        paired with `correct: true` still SHOULD warn
        (`check_true_false_markers`).
        The reserved `X`/`x` marker is rejected at the field level, so it
        never reaches here.
        """
        for index, choice in enumerate(self.choices):
            marker = choice.marker
            if marker is None:
                continue
            # FALSE-category means false; everything else (TRUE or
            # WARNING) reads as true.
            expected_correct = normalize_value(marker) not in FALSE_LETTERS
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

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(check_true_false_markers(self.choices, self.locale))
        diagnostics.extend(check_true_false_uniform_answers(self.choices))
        diagnostics.extend(check_true_false_marker_nfkc(self.choices))
        return diagnostics

    def _mark(self, choice: Statement) -> str:
        # A statement without `marker` is written as `T` or `F`.
        return choice.marker or ("T" if choice.correct else "F")

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
            (statement, response.get(statement.id) if statement.id is not None else None)
            for statement in self.choices
        ]
        correct = sum(1 for statement, mark in marks if mark == statement.correct)
        incorrect = sum(
            1
            for statement, mark in marks
            if mark is not None and mark != statement.correct
        )

        grading = self.effective_grading()
        match grading:
            case "all-or-nothing":
                score = 1.0 if correct == n else 0.0
            case "no-mistakes":
                score = 0.0 if incorrect else correct / n
            case "partial":
                score = correct / n
            case "symmetric":
                score = (correct - incorrect) / n
            case _:
                assert_never(grading)

        feedback = [
            statement.feedback
            for statement, mark in marks
            if mark != statement.correct and statement.feedback
        ]
        return QuestionScore(score=score, feedback=feedback)


def check_choice_ids_defined(
    choices: Sequence[ScoredChoice | BooleanChoice | Statement],
    path: tuple[str | int, ...],
) -> Iterator[Diagnostic]:
    """
    multiple-choice.md, "Choices": a choice SHOULD declare its own `id`
    rather than rely on one derived from its text -- a derived id is
    only as stable as the slugifier that produced it.
    """
    for index, choice in enumerate(choices):
        if choice.id is None:
            yield diag(
                code="missing-choice-id",
                path=path + (index, "id"),
                message=(
                    "choice has no explicit id; one will be derived from its text"
                ),
            )


def check_choices_visually_identical(
    choices: Sequence[ScoredChoice | BooleanChoice | Statement],
    path: tuple[str | int, ...],
) -> Iterator[Diagnostic]:
    """
    multiple-choice.md, "Choices": two choices whose text renders alike
    but is written differently in source are indistinguishable to a
    reader -- the same comparison
    `check_ordering_visually_identical_lines` applies to ordering lines.
    """
    seen: dict[str, int] = {}
    for index, choice in enumerate(choices):
        key = _lint.render_visual_key(choice.text)
        first_index = seen.setdefault(key, index)
        # An exact repeat is a `duplicate-choice-text` model error, so a
        # choice that renders like an earlier one is written differently.
        if first_index == index:
            continue
        yield diag(
            code="visually-identical-choices",
            path=path + (index, "text"),
            message=(
                f"choice text renders the same as choices[{first_index}] "
                f"but is written differently in source"
            ),
        )


def check_multiple_choice_answers(
    choices: Sequence[ScoredChoice],
    path: tuple[str | int, ...],
) -> Iterator[Diagnostic]:
    """
    multiple-choice.md: a question MAY mark any number of choices as
    correct, and typically marks exactly one -- more than one is unusual
    enough to flag (`many-correct-choices`, `info`), but
    not a mistake. No correct choice at all more likely is one.

    Also used, via `mdq.models._fill_in.FillInQuestion.lint`, for a
    fill-in choice blank -- graded like multiple-choice, so the same
    rules apply (fill-in.md, "Additional Rules").
    """
    correct = [
        index for index, choice in enumerate(choices) if (choice.score or 0) >= 1
    ]

    if not correct:
        yield diag(
            code="no-correct-choice",
            path=path,
            message="no choice has a score >= 1; the question has no correct answer",
        )

    if len(correct) > 1:
        listed = ", ".join(str(index) for index in correct)
        yield diag(
            code="many-correct-choices",
            path=path,
            message=(
                f"choices {listed} all have a score >= 1; a question MAY "
                f"mark any number of choices as correct, but the student "
                f"still picks a single one"
            ),
        )

    if len(correct) == len(choices):
        yield diag(
            code="all-choices-correct",
            path=path,
            message="every choice has a score >= 1; the question has no wrong answer",
        )


def check_multiple_selection_answers(
    choices: Sequence[BooleanChoice],
    path: tuple[str | int, ...],
) -> Iterator[Diagnostic]:
    """
    multiple-selection.md: a well-formed question mixes correct and
    incorrect choices -- one with none correct has nothing to select,
    and one where every choice is correct has nothing to leave unchecked.
    """
    correct = [index for index, choice in enumerate(choices) if choice.correct]

    if not correct:
        yield diag(
            code="no-correct-choice",
            path=path,
            message="no choice is correct; the question has nothing to select",
        )
    elif len(correct) == len(choices):
        yield diag(
            code="all-choices-correct",
            path=path,
            message="every choice is correct; the question has nothing to leave unchecked",
        )


def check_true_false_markers(
    choices: Sequence[Statement],
    locale: str | None,
) -> Iterator[Diagnostic]:
    """
    true-false.md, "Locale": the marker rules, in this order, on the
    normalized value.

    1. A false friend of the locale row: only `false-friend-true-false-marker`.
    2. A letter the row accepts (even a WARNING letter): no warning.
    3. A WARNING letter: only `unlisted-true-false-marker`.
    4. A locale without a row: no locale warning.
    5. Any other TRUE or FALSE letter: `locale-mismatched-true-false-marker`.

    The reserved `X`/`x` marker is rejected at the model layer
    (`reserved-true-false-marker`), so it never reaches here.
    """
    row = LOCALE_ROWS.get(_lint.language_subtag(locale))

    for index, choice in enumerate(choices):
        marker = choice.marker
        if marker is None:
            continue

        value = normalize_value(marker)
        path = ("choices", index, "marker")
        if row is not None and value in row.false_friends:
            yield diag(
                code="false-friend-true-false-marker",
                path=path,
                message=(
                    f"{marker!r} reads as true (see true-false.md), but "
                    f"it can mean false in the language of locale "
                    f"{locale!r}; if this choice was meant to be false, "
                    f"use 'F' instead"
                ),
            )
        elif row is not None and (value in row.true or value in row.false):
            continue
        elif value not in TRUE_LETTERS and value not in FALSE_LETTERS:
            yield diag(
                code="unlisted-true-false-marker",
                path=path,
                message=(
                    f"{marker!r} is in neither the true nor the false "
                    f"marker list: it reads as true"
                ),
            )
        elif row is not None:
            yield diag(
                code="locale-mismatched-true-false-marker",
                path=path,
                message=(
                    f"{marker!r} does not fit locale {locale!r}: use "
                    f"'T'/'F' or a letter of the locale table"
                ),
            )


def check_true_false_marker_nfkc(
    choices: Sequence[Statement],
) -> Iterator[Diagnostic]:
    """
    true-false.md, "Additional Rules": a marker that is not its own NFKC
    form (`non-nfkc-true-false-marker`, info), for example U+FF26
    FULLWIDTH LATIN CAPITAL LETTER F or U+212B ANGSTROM SIGN. The letter
    is valid and keeps its written form in `marker`, but it is read as
    its NFKC form, and it renders differently than intended.
    """
    for index, choice in enumerate(choices):
        marker = choice.marker
        if marker is None:
            continue
        form = nfkc(marker)
        if form != marker:
            yield diag(
                code="non-nfkc-true-false-marker",
                path=("choices", index, "marker"),
                message=(f"{marker!r} is not its own NFKC form; read as {form!r}"),
            )


def check_true_false_uniform_answers(
    choices: Sequence[Statement],
) -> Iterator[Diagnostic]:
    """
    true-false.md:218: a question whose statements are all true or all
    false is usually an authoring mistake -- a well-formed question
    presents a mix for the student to judge.
    """
    if not choices:
        return
    values = {choice.correct for choice in choices}
    if len(values) > 1:
        return
    yield diag(
        code="uniform-true-false-answers",
        path=("choices",),
        message=(
            f"every statement is {'true' if choices[0].correct else 'false'}; "
            f"a true/false question should mix true and false statements"
        ),
    )

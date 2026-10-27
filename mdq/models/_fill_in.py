"""
Fill-in-the-blank questions: the three blank shapes (`ChoiceBlank`,
`ShortAnswerBlank`, `NumericBlank`) and `FillInQuestion` itself, which
scores each blank with the same logic its standalone question type uses
(`mdq.models._choice._with_choice_ids`, `mdq.models._text.
render_short_answer_patterns`, `mdq.models._numeric.
numeric_matches`/`render_numeric_tag`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Annotated, Any, Final, Iterable, Literal, Self, cast, assert_never

from pydantic import Field, field_validator, model_validator

from .. import _markdown, types as t
from .._diagnostics import Diagnostic
from ..errors import NotAutoGradable, ResponseError
from ..types import (
    Automation,
    Diacritics,
    GradingStrategy,
    NumericDomain,
    QuestionGrading,
    QuestionShuffle,
    Unmatched,
)
from . import _lint, _render
from ._base import (
    SlugId,
    FreeText,
    MdqModel,
    BaseQuestion,
    _check_unique_choices,
    _raise_unique_id_error,
)
from ._choice import (
    ScoredChoice,
    _with_choice_ids,
    unspecified_choice_score,
    write_shuffle_and_grading,
)
from ._numeric import (
    Unit,
    NumericAnswer,
    Tolerance,
    check_decimal_places_given,
    infer_decimal_places,
    _validate_numeric_answer,
    numeric_matches,
    render_numeric_tag,
)
from ._score import QuestionScore
from ._text import (
    PatternList,
    _pattern_entry,
    default_unmatched,
    first_feedback,
    prevalidate_response,
    render_short_answer_patterns,
    settle_response,
    short_answer_automation,
)

__all__ = ["ChoiceBlank", "ShortAnswerBlank", "NumericBlank", "Blank", "FillInQuestion"]


@dataclass(frozen=True)
class BlankScore:
    """The score of one answered blank, with the feedback it earned."""

    score: float
    feedback: list[str] = field(default_factory=list)


#: The score of a short answer blank that matches no pattern when `unmatched`
#: is `manual`: the instructor scores it.
PENDING: Final = "pending"

type ModelPath = tuple[str | int, ...]


class BlankBase(MdqModel, ABC):
    """
    What `FillInQuestion` asks of every blank. Each blank is graded like
    the question type it names.
    """

    id: SlugId

    @abstractmethod
    def lint(self, path: ModelPath, *, unmatched: Unmatched | None) -> list[Diagnostic]:
        """Lint diagnostics of this blank, which sits at `path` of the question."""

    @abstractmethod
    def render_lines(self) -> Iterable[str]:
        """The Markdown lines that define this blank under the stem."""

    def automation(self, unmatched: Unmatched | None) -> Automation:
        """
        The automation of this blank under the question's `unmatched`
        (fill-in.md, "Automation"). Choice and numeric blanks are always
        automatic.
        """
        return "automatic"

    def with_ids(self) -> Self:
        """This blank with the ids it derives; only choice blanks derive any."""
        return self

    @abstractmethod
    def score(
        self,
        response: object,
        *,
        symmetric: bool,
        diacritics: Diacritics,
        unmatched: Unmatched | None,
    ) -> BlankScore | Literal["pending"]:
        """
        Score a response that is not `None`. `"pending"` means the
        instructor has to score it.

        Raises:
            ResponseError: the response doesn't match the blank's type.
        """


class ChoiceBlank(BlankBase):
    id: SlugId
    type: Literal["multiple-choice"] = "multiple-choice"
    choices: Annotated[list[ScoredChoice], Field(min_length=2)]

    @model_validator(mode="after")
    def check_choices_are_unique(self) -> Self:
        """
        multiple-choice.md, "Choices" (shared by a fill-in choice
        blank): no choice's `text` may be blank (`blank-text`),
        and ids and texts must each be unique (`duplicate-choice-id`,
        `duplicate-choice-text`).
        """
        _check_unique_choices(type(self).__name__, self.choices)
        return self

    def lint(self, path: ModelPath, *, unmatched: Unmatched | None) -> list[Diagnostic]:
        choices_path = path + ("choices",)
        return [
            *_lint.check_multiple_choice_answers(self.choices, choices_path),
            *_lint.check_choice_ids_defined(self.choices, choices_path),
            *_lint.check_choices_visually_identical(self.choices, choices_path),
        ]

    def render_lines(self) -> Iterable[str]:
        yield f"[^{self.id}]:"
        for choice in self.choices:
            yield from _render.yield_choice(choice, mark=_render.score_mark(choice.score))

    def with_ids(self) -> Self:
        return self.model_copy(update={"choices": _with_choice_ids(self.choices)})

    def score(
        self,
        response: object,
        *,
        symmetric: bool,
        diacritics: Diacritics,
        unmatched: Unmatched | None,
    ) -> BlankScore:
        choice = next((c for c in self.choices if c.id == response), None)
        if choice is None:
            raise ResponseError(
                f"Response id {response!r} not found in blank {self.id!r}"
            )
        score = (
            choice.score
            if choice.score is not None
            else unspecified_choice_score(self.choices, symmetric=symmetric)
        )
        return BlankScore(score, [choice.feedback] if choice.feedback else [])


class ShortAnswerBlank(BlankBase):
    id: SlugId
    type: Literal["short-answer"] = "short-answer"
    accept: PatternList | None = None
    reject: PatternList | None = None
    pre_accept: PatternList | None = None
    pre_reject: PatternList | None = None

    #: Feedback for an incorrect response that no pattern gave feedback to
    #: (short-answer.md, "Feedback"; fill-in.md, "Frontmatter").
    incorrect_feedback: FreeText | None = None

    def prevalidate(
        self, response: str, *, diacritics: Diacritics = "fold"
    ) -> tuple[bool, str | None]:
        """
        Pre-validate a response to this blank by the rules of a short answer
        question (short-answer.md, "Pre-validation"). `diacritics` is the one
        of the fill-in question. Returns `(valid, feedback)`.
        """
        return prevalidate_response(
            self.pre_accept, self.pre_reject, response, diacritics=diacritics
        )

    def effective_unmatched(self, unmatched: Unmatched | None) -> Unmatched:
        """
        The `unmatched` of the fill-in question, or this blank's default
        when the question declares none: `"incorrect"` when the blank has
        at least one `accept` pattern, `"manual"` otherwise (fill-in.md,
        "Frontmatter").
        """
        return default_unmatched(unmatched, self.accept)

    def automation(self, unmatched: Unmatched | None) -> Automation:
        """
        The automation of this blank under the question's `unmatched`, by
        the rules of a short answer question (fill-in.md, "Automation").
        """
        return short_answer_automation(
            self.effective_unmatched(unmatched), self.accept, self.reject
        )

    def lint(self, path: ModelPath, *, unmatched: Unmatched | None) -> list[Diagnostic]:
        return [
            *_lint.check_short_answer(
                accept=self.accept,
                reject=self.reject,
                pre_accept=self.pre_accept,
                pre_reject=self.pre_reject,
                path=path,
            ),
            *_lint.check_no_correct_answer(
                accept=self.accept,
                unmatched=self.effective_unmatched(unmatched),
                path=path,
            ),
        ]

    def render_lines(self) -> Iterable[str]:
        tag = f"^{self.id}/short-answer"
        yield from render_short_answer_patterns(self.accept, self.reject, tag)

    def score(
        self,
        response: object,
        *,
        symmetric: bool,
        diacritics: Diacritics,
        unmatched: Unmatched | None,
    ) -> BlankScore | Literal["pending"]:
        if not isinstance(response, str):
            raise ResponseError(
                f"Response {response!r} to blank {self.id!r} is not text"
            )
        outcome = settle_response(
            self.accept,
            self.reject,
            response,
            unmatched=self.effective_unmatched(unmatched),
            diacritics=diacritics,
        )
        if outcome == "pending":
            return PENDING
        feedback = first_feedback(
            (self.accept if outcome == "correct" else self.reject) or [],
            response,
            diacritics=diacritics,
        )
        if outcome == "incorrect" and not feedback and self.incorrect_feedback:
            feedback = [self.incorrect_feedback]
        return BlankScore(1.0 if outcome == "correct" else 0.0, feedback)


class NumericBlank(BlankBase):
    id: SlugId
    type: Literal["numeric"] = "numeric"
    answer: NumericAnswer
    unit: Unit | None = None
    domain: NumericDomain | None = None
    decimal_places: Annotated[int | None, Field(ge=0)] = None
    tolerance: Tolerance | None = None

    #: Feedback for an incorrect response (numeric.md, "Feedback";
    #: fill-in.md, "Feedback").
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
        """As `NumericQuestion.effective_domain`, for this blank."""
        return _lint._effective_numeric_domain(self.answer, self.domain, self.tolerance)

    @property
    def effective_decimal_places(self) -> int | None:
        """As `NumericQuestion.effective_decimal_places`, for this blank."""
        if self.decimal_places is not None:
            return self.decimal_places
        if self.effective_domain == "decimal":
            return infer_decimal_places(self.answer, self.tolerance)
        return None

    def lint(self, path: ModelPath, *, unmatched: Unmatched | None) -> list[Diagnostic]:
        return _lint.check_numeric(
            answer=self.answer,
            domain=self.domain,
            decimal_places=self.decimal_places,
            tolerance=self.tolerance,
            path=path,
        )

    def render_lines(self) -> Iterable[str]:
        yield render_numeric_tag(
            self.answer,
            tag=f"[^{self.id}/numeric]",
            unit=self.unit,
            tolerance=self.tolerance,
        )

    def score(
        self,
        response: object,
        *,
        symmetric: bool,
        diacritics: Diacritics,
        unmatched: Unmatched | None,
    ) -> BlankScore:
        if not isinstance(response, int | float | Fraction | str | Mapping):
            raise ResponseError(
                f"Response {response!r} to blank {self.id!r} is not numeric"
            )
        correct = numeric_matches(
            self.answer,
            cast(t.NumericResponse, response),
            self.tolerance,
            self.effective_decimal_places,
            domain=self.effective_domain,
            unit=self.unit,
        )
        feedback = [] if correct or not self.incorrect_feedback else [self.incorrect_feedback]
        return BlankScore(1.0 if correct else 0.0, feedback)


Blank = Annotated[
    ChoiceBlank | ShortAnswerBlank | NumericBlank,
    Field(discriminator="type"),
]




class FillInQuestion(BaseQuestion[t.FillInResponse]):
    blanks: Annotated[list[Blank], Field(min_length=1)]
    type: Literal["fill-in"] = "fill-in"
    shuffle: QuestionShuffle = "inherit"
    grading: QuestionGrading = "inherit"

    def effective_grading(self) -> GradingStrategy:
        """The question's `grading`, with `inherit` read as `symmetric`."""
        return "symmetric" if self.grading == "inherit" else self.grading

    def effective_shuffle(self) -> bool:
        """The question's `shuffle`, with `inherit` read as `False`."""
        return False if self.shuffle == "inherit" else self.shuffle

    #: How inexact literals treat diacritics, in every short answer blank.
    diacritics: Diacritics = "fold"

    #: What becomes of a short answer blank's response that matches no
    #: pattern, for every short answer blank (fill-in.md, "Frontmatter").
    #: `None` leaves each blank to its own default.
    unmatched: Unmatched | None = None

    @property
    def automation(self) -> Automation:
        """
        `automatic` if every blank is automatic, `manual` if every blank is
        manual, `semi-automatic` otherwise (fill-in.md, "Automation").
        Choice and numeric blanks are always automatic.
        """
        levels = {blank.automation(self.unmatched) for blank in self.blanks}
        if levels == {"automatic"}:
            return "automatic"
        if levels == {"manual"}:
            return "manual"
        return "semi-automatic"

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

    @model_validator(mode="after")
    def check_blank_markers(self) -> Self:
        """
        fill-in.md, "Additional Rules": every `[^id]` marker in the stem
        names a declared blank (`undefined-blank`), and every declared
        blank is referenced by one (`unreferenced-blank`).
        """
        referenced = [name for name, _ in _markdown.find_blank_markers(self.stem)]
        declared = {blank.id for blank in self.blanks}

        for name in dict.fromkeys(referenced):
            if name not in declared:
                hint = ""
                variants = sorted(d for d in declared if d.lower() == name.lower())
                if variants:
                    hint = (
                        f"; blank ids are case-sensitive, did you mean "
                        f"[^{variants[0]}]?"
                    )
                _raise_unique_id_error(
                    type(self).__name__,
                    "undefined-blank",
                    f"the stem references [^{name}] but no blank with that "
                    f"id is defined{hint}",
                    ("stem",),
                    self.stem,
                )

        seen_markers = set(referenced)
        for index, blank in enumerate(self.blanks):
            if blank.id not in seen_markers:
                _raise_unique_id_error(
                    type(self).__name__,
                    "unreferenced-blank",
                    f"blank {blank.id!r} is never referenced by a "
                    f"[^{blank.id}] marker in the stem",
                    ("blanks", index, "id"),
                    blank.id,
                )
        return self

    @model_validator(mode="after")
    def check_blank_markers_are_in_plain_text(self) -> Self:
        """
        fill-in.md, "Where blanks may appear": a `[^id]` marker may only
        appear in a plain text run of a paragraph -- not in a heading,
        list item, table cell or blockquote, nor inside emphasis, a
        strong span, link text or image alt text. Code is literal text.
        """
        misplaced = _markdown.find_misplaced_blank_markers(self.stem)
        if misplaced:
            _raise_unique_id_error(
                type(self).__name__,
                "misplaced-blank",
                (
                    f"[^{misplaced[0]}] must appear in a plain text run of "
                    f"the stem, not inside a heading, list, table, quote, emphasis, or a link"
                ),
                ("stem",),
                self.stem,
            )
        return self

    @model_validator(mode="after")
    def check_blank_references_are_unique(self) -> Self:
        """
        fill-in.md, "Blank definitions": each blank id appears at most
        once in the stem (`duplicate-blank-reference`).
        """
        seen: set[str] = set()
        for name, _ in _markdown.find_blank_markers(self.stem):
            if name in seen:
                _raise_unique_id_error(
                    type(self).__name__,
                    "duplicate-blank-reference",
                    (
                        f"the stem references [^{name}] more than once; "
                        f"each blank id may appear only once in the stem"
                    ),
                    ("stem",),
                    self.stem,
                )
            seen.add(name)
        return self

    def with_ids(self) -> Self:
        """
        See `BaseQuestion.with_ids`.

        Only a `ChoiceBlank`'s own choices get a derived id -- a blank's
        `id` is required already (it names the `[^id]` marker in the
        stem), and short-answer/numeric blanks have no choices at all.
        """
        blanks = [blank.with_ids() for blank in self.blanks]
        return self.model_copy(update={"blanks": blanks})

    def lint(self) -> list[Diagnostic]:
        """
        See `BaseQuestion.lint`.

        Each blank is graded like the question type it names, so it
        inherits that type's checks, with the path pointing into the
        blank.
        """
        diagnostics = super().lint()
        diagnostics.extend(_lint.check_case_variant_blank_ids([b.id for b in self.blanks]))
        for index, blank in enumerate(self.blanks):
            diagnostics.extend(blank.lint(("blanks", index), unmatched=self.unmatched))
        return diagnostics

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        write_shuffle_and_grading(data, self.shuffle, self.grading)
        if self.diacritics != "fold":
            data["diacritics"] = self.diacritics
        if self.unmatched is not None:
            data["unmatched"] = self.unmatched
        # fill-in.md, "Frontmatter": maps from blank id to pattern list.
        for key, attr in (("preAccept", "pre_accept"), ("preReject", "pre_reject")):
            lists = {
                blank.id: [_pattern_entry(p) for p in patterns]
                for blank in self.blanks
                if isinstance(blank, ShortAnswerBlank)
                and (patterns := getattr(blank, attr)) is not None
            }
            if lists:
                data[key] = lists
        texts = {
            blank.id: blank.incorrect_feedback
            for blank in self.blanks
            if isinstance(blank, ShortAnswerBlank | NumericBlank)
            and blank.incorrect_feedback is not None
        }
        if texts:
            data["incorrectFeedback"] = texts
        # fill-in.md, "Frontmatter": maps from blank id to the `domain` and
        # `decimalPlaces` of a numeric blank.
        for key, attr in (("domain", "domain"), ("decimalPlaces", "decimal_places")):
            values = {
                blank.id: getattr(blank, attr)
                for blank in self.blanks
                if isinstance(blank, NumericBlank) and getattr(blank, attr) is not None
            }
            if values:
                data[key] = values
        return data

    def _render_body(self) -> Iterable[str]:
        for blank in self.blanks:
            yield ""
            yield from blank.render_lines()

    def score_response(self, response: t.FillInResponse) -> QuestionScore:
        """
        Score each blank independently and combine by `grading`.

        A blank with no key, or a `None` value, is empty and scores 0
        (fill-in.md, "Grading"); `{}` is a response with every blank empty.

        Raises:
            ResponseError: a key of `response` names no blank, or a blank's
                response doesn't match its type.
            NotAutoGradable: a short answer blank response is pending.
        """
        known = {blank.id for blank in self.blanks}
        unknown = sorted(key for key in response if key not in known)
        if unknown:
            raise ResponseError(f"Blank ids {unknown!r} not found in the question")
        symmetric = self.effective_grading() == "symmetric"
        scores: list[float] = []
        feedback: list[str] = []
        pending: list[str] = []

        for blank in self.blanks:
            sub_response = response.get(blank.id)
            if sub_response is None:
                scores.append(0.0)
                continue
            result = blank.score(
                sub_response,
                symmetric=symmetric,
                diacritics=self.diacritics,
                unmatched=self.unmatched,
            )
            if not isinstance(result, BlankScore):
                # The instructor scores a pending blank; the question
                # stays pending, but the other blanks are still checked.
                pending.append(blank.id)
                continue
            scores.append(result.score)
            feedback.extend(result.feedback)
        if pending:
            raise NotAutoGradable(
                f"the response to blank {pending[0]!r} is pending: it matches "
                "no pattern and 'unmatched' is 'manual'"
            )

        mean = sum(scores) / len(scores)

        grading = self.effective_grading()
        match grading:
            case "all-or-nothing":
                score = 1.0 if all(s == 1.0 for s in scores) else 0.0
            case "no-mistakes":
                # An empty blank scores 0 but is no mistake: only a filled
                # blank below 1 zeroes the question.
                mistaken = any(
                    score < 1.0 and response.get(blank.id) is not None
                    for blank, score in zip(self.blanks, scores, strict=True)
                )
                score = 0.0 if mistaken else mean
            case "partial":
                score = max(0.0, mean)
            case "symmetric":
                score = mean
            case _:
                assert_never(grading)

        return QuestionScore(score=score, feedback=feedback)

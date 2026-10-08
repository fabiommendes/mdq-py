"""
Fill-in-the-blank questions: the three blank shapes (`ChoiceBlank`,
`ShortAnswerBlank`, `NumericBlank`) and `FillInQuestion` itself, which
scores each blank with the same logic its standalone question type uses
(`mdq.models._choice._with_choice_ids`, `mdq.models._text.
render_short_answer_patterns`, `mdq.models._numeric.
numeric_matches`/`render_numeric_tag`).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Annotated, Any, Iterable, Literal, Self

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
    MdqModel,
    BaseQuestion,
    _BLANK_MARKER_RE,
    _check_choices_have_text,
    _check_unique_choices,
    _raise_unique_id_error,
)
from ._choice import (
    ScoredChoice,
    _with_choice_ids,
    effective_grading,
    effective_shuffle,
    write_shuffle_and_grading,
)
from ._numeric import (
    _UNIT_PATTERN,
    NumericAnswer,
    Tolerance,
    infer_decimal_places,
    _validate_numeric_answer,
    numeric_matches,
    render_numeric_tag,
)
from ._score import QuestionScore
from ._text import (
    AnswerPattern,
    _pattern_entry,
    default_unmatched,
    first_feedback,
    render_short_answer_patterns,
    settle_response,
    short_answer_automation,
)

__all__ = ["ChoiceBlank", "ShortAnswerBlank", "NumericBlank", "Blank", "FillInQuestion"]


class ChoiceBlank(MdqModel):
    id: SlugId
    type: Literal["multiple-choice"] = "multiple-choice"
    choices: list[ScoredChoice]

    @model_validator(mode="after")
    def check_choices_are_unique(self) -> Self:
        """
        multiple-choice.md, "Choices" (shared by a fill-in choice
        blank): no choice's `text` may be empty (`blank-choice-text`),
        and ids and texts must each be unique (`duplicate-choice-id`,
        `duplicate-choice-text`).
        """
        _check_choices_have_text(type(self).__name__, self.choices)
        _check_unique_choices(type(self).__name__, self.choices)
        return self


class ShortAnswerBlank(MdqModel):
    id: SlugId
    type: Literal["short-answer"] = "short-answer"
    accept: list[AnswerPattern] | None = None
    reject: list[AnswerPattern] | None = None
    pre_accept: list[AnswerPattern] | None = None
    pre_reject: list[AnswerPattern] | None = None

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


class NumericBlank(MdqModel):
    id: SlugId
    type: Literal["numeric"] = "numeric"
    answer: NumericAnswer
    unit: Annotated[str, Field(pattern=_UNIT_PATTERN)] | None = None
    domain: NumericDomain | None = None
    decimal_places: Annotated[int | None, Field(ge=0)] = None
    tolerance: Tolerance | None = None

    @field_validator("answer")
    @classmethod
    def check_answer_grammar(cls, value: NumericAnswer) -> NumericAnswer:
        return _validate_numeric_answer(value)

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


Blank = Annotated[
    ChoiceBlank | ShortAnswerBlank | NumericBlank,
    Field(discriminator="type"),
]




class FillInQuestion(BaseQuestion[t.FillInResponse]):
    blanks: list[Blank]
    type: Literal["fill-in"] = "fill-in"
    shuffle: QuestionShuffle = "inherit"
    grading: QuestionGrading = "inherit"

    def effective_grading(self) -> GradingStrategy:
        """The question's `grading`, with `inherit` read as `symmetric`."""
        return effective_grading(self.grading)

    def effective_shuffle(self) -> bool:
        """The question's `shuffle`, with `inherit` read as `False`."""
        return effective_shuffle(self.shuffle)

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
        levels = {
            blank.automation(self.unmatched)
            if isinstance(blank, ShortAnswerBlank)
            else "automatic"
            for blank in self.blanks
        }
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
        referenced = [
            marker.split("/", 1)[0].strip()
            for marker in _BLANK_MARKER_RE.findall(self.stem)
        ]
        declared = {blank.id for blank in self.blanks}

        for name in dict.fromkeys(referenced):
            if name not in declared:
                _raise_unique_id_error(
                    type(self).__name__,
                    "undefined-blank",
                    f"the stem references [^{name}] but no blank with that "
                    f"id is defined",
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
        fill-in.md:301: a `[^id]` marker may only appear in a plain text
        run of a paragraph -- not inside emphasis, a strong span, a
        link, or a code span, where a student would not read it as the
        blank it names.
        """
        misplaced = _markdown.find_misplaced_blank_markers(self.stem)
        if misplaced:
            _raise_unique_id_error(
                type(self).__name__,
                "misplaced-blank",
                (
                    f"[^{misplaced[0]}] must appear in a plain text run of "
                    f"the stem, not inside emphasis, a link, or a code span"
                ),
                ("stem",),
                self.stem,
            )
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

    def lint(self) -> list[Diagnostic]:
        """
        See `BaseQuestion.lint`.

        Each blank is graded like the question type it names, so it
        inherits that type's checks, with the path pointing into the
        blank.
        """
        diagnostics = super().lint()
        for index, blank in enumerate(self.blanks):
            path: tuple[str | int, ...] = ("blanks", index)
            if isinstance(blank, ChoiceBlank):
                choices_path = path + ("choices",)
                diagnostics.extend(_lint.check_multiple_choice_answers(blank.choices, choices_path))
                diagnostics.extend(
                    _lint.check_choice_feedback_and_comment(blank.choices, choices_path)
                )
                diagnostics.extend(_lint.check_choice_ids_defined(blank.choices, choices_path))
                diagnostics.extend(
                    _lint.check_choices_visually_identical(blank.choices, choices_path)
                )
            elif isinstance(blank, ShortAnswerBlank):
                diagnostics.extend(
                    _lint.check_short_answer(
                        accept=blank.accept,
                        reject=blank.reject,
                        pre_accept=blank.pre_accept,
                        pre_reject=blank.pre_reject,
                        path=path,
                    )
                )
                diagnostics.extend(
                    _lint.check_no_correct_answer(
                        accept=blank.accept,
                        unmatched=blank.effective_unmatched(self.unmatched),
                        path=path,
                    )
                )
            else:
                diagnostics.extend(
                    _lint.check_numeric(
                        answer=blank.answer,
                        domain=blank.domain,
                        decimal_places=blank.decimal_places,
                        tolerance=blank.tolerance,
                        path=path,
                    )
                )
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
        return data

    def _render_body(self) -> Iterable[str]:
        for blank in self.blanks:
            yield ""
            if isinstance(blank, ChoiceBlank):
                yield f"[^{blank.id}]:"
                for choice in blank.choices:
                    mark = _render.score_mark(choice.score)
                    yield from _render.yield_choice(choice, mark=mark)
            elif isinstance(blank, ShortAnswerBlank):
                tag = f"^{blank.id}/short-answer"
                yield from render_short_answer_patterns(blank.accept, blank.reject, tag)
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
                outcome = settle_response(
                    blank.accept,
                    blank.reject,
                    sub_response,
                    unmatched=blank.effective_unmatched(self.unmatched),
                    diacritics=self.diacritics,
                )
                if outcome == "pending":
                    raise NotAutoGradable(
                        f"the response to blank {blank.id!r} is pending: it matches "
                        "no pattern and 'unmatched' is 'manual'"
                    )
                scores.append(1.0 if outcome == "correct" else 0.0)
                feedback.extend(
                    first_feedback(
                        (blank.accept if outcome == "correct" else blank.reject) or [],
                        sub_response,
                        diacritics=self.diacritics,
                    )
                )
            else:
                if sub_response is None:
                    scores.append(0.0)
                    continue
                if not isinstance(sub_response, int | float | Fraction | str):
                    raise ResponseError(
                        f"Response {sub_response!r} to blank {blank.id!r} is not numeric"
                    )
                correct = numeric_matches(
                    blank.answer,
                    sub_response,
                    blank.tolerance,
                    blank.effective_decimal_places,
                    domain=blank.effective_domain,
                )
                scores.append(1.0 if correct else 0.0)

        mean = sum(scores) / len(scores)

        if self.effective_grading() == "all-or-nothing":
            score = 1.0 if all(s == 1.0 for s in scores) else 0.0
        elif self.effective_grading() == "partial":
            score = max(0.0, mean)
        else:
            score = mean

        return QuestionScore(score=score, feedback=feedback)

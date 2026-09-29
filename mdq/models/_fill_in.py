"""
Fill-in-the-blank questions: the three blank shapes (`ChoiceBlank`,
`ShortAnswerBlank`, `NumericBlank`) and `FillInQuestion` itself, which
scores each blank with the same logic its standalone question type uses
(`mdq.models._choice._with_choice_ids`, `mdq.models._text.
short_answer_matches`/`render_pattern_block`, `mdq.models._numeric.
numeric_matches`/`render_numeric_tag`).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Annotated, Any, Iterable, Literal, Self

from pydantic import Field, field_validator, model_validator

from .. import _markdown, types as t
from .._diagnostics import Diagnostic
from ..errors import ResponseError
from ..types import Diacritics, GradingStrategy, NumericDomain
from . import _lint, _render
from ._base import (
    MdqModel,
    BaseQuestion,
    _BLANK_MARKER_RE,
    _check_choices_have_text,
    _check_unique_choices,
    _raise_unique_id_error,
    _validate_mdq_regex,
)
from ._choice import ScoredChoice, _with_choice_ids
from ._numeric import Tolerance, numeric_matches, render_numeric_tag
from ._score import QuestionScore
from ._text import AnswerPattern, render_pattern_block, short_answer_matches

__all__ = ["ChoiceBlank", "ShortAnswerBlank", "NumericBlank", "Blank", "FillInQuestion"]


class ChoiceBlank(MdqModel):
    id: str
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
    id: str
    type: Literal["short-answer"] = "short-answer"
    one_of: list[str] | None = None
    regex: str | None = None
    accept: list[AnswerPattern] | None = None
    reject: list[AnswerPattern] | None = None
    pre_accept: list[AnswerPattern] | None = None
    pre_reject: list[AnswerPattern] | None = None

    @field_validator("regex")
    @classmethod
    def check_regex_compiles(cls, value: str | None) -> str | None:
        return _validate_mdq_regex(value)


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
                diagnostics.extend(
                    _lint.check_multiple_choice_answers(blank.choices, path + ("choices",))
                )
            elif isinstance(blank, ShortAnswerBlank):
                diagnostics.extend(
                    _lint.check_short_answer(
                        regex=blank.regex,
                        one_of=blank.one_of,
                        accept=blank.accept,
                        reject=blank.reject,
                        open_ended=False,
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
                    yield from _render.yield_choice(choice, mark=mark)
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

"""
Ordering questions: `OrderingAlternative` (one `accept`/`reject` entry)
and `OrderingQuestion` itself.
"""

from __future__ import annotations

from typing import Annotated, Any, Iterable, Literal, Self

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from .. import types as t
from .._diagnostics import Diagnostic
from ..errors import NotAutoGradable, ResponseError
from ..types import Indentation, Normalization, OrderingContent, Unmatched
from . import _lint, _render
from ._base import BaseQuestion, MdqModel
from ._score import QuestionScore

__all__ = ["OrderingLine", "OrderingAlternative", "OrderingQuestion"]


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

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(_lint.check_ordering_highlight(self))
        diagnostics.extend(_lint.check_ordering_duplicate_alternatives(self))
        diagnostics.extend(_lint.check_ordering_accept_repeats_answer_key(self))
        diagnostics.extend(_lint.check_ordering_redundant_strict_indentation(self))
        diagnostics.extend(_lint.check_ordering_blank_lines(self))
        diagnostics.extend(_lint.check_ordering_reject_without_feedback(self))
        diagnostics.extend(_lint.check_ordering_visually_identical_lines(self))
        return diagnostics

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
        yield from _render.yield_ordering_content(self.lines, self.content, self.highlight)
        if self.extra:
            yield from _render.yield_ordering_section(
                "extra", self.extra, self.content, self.highlight
            )
        for alt in self.accept:
            yield from _render.yield_ordering_section(
                "accept", alt.lines, self.content, self.highlight, alt.feedback, alt.comment
            )
        for alt in self.reject:
            yield from _render.yield_ordering_section(
                "reject", alt.lines, self.content, self.highlight, alt.feedback, alt.comment
            )

    @model_validator(mode="after")
    def check_accept_and_reject_disjoint(self) -> Self:
        """
        A question MUST NOT declare the same lines as both accepted and
        rejected (ordering.md#additional-rules).

        Raises:
            PydanticCustomError: `accept-reject-overlap` -- some `accept`
                entry holds the same lines as some `reject` entry.
        """
        reject_lines = {tuple(alt.lines) for alt in self.reject}
        for alt in self.accept:
            if tuple(alt.lines) in reject_lines:
                raise PydanticCustomError(
                    "accept-reject-overlap",
                    "the same lines must not be declared in both accept and reject",
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

#
# Utilities
#

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



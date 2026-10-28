"""
Ordering questions: `OrderingAlternative` (one `accept`/`reject` entry)
and `OrderingQuestion` itself.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Annotated, Any, ClassVar, Iterable, Iterator, Literal, Self

from pydantic import (
    AfterValidator,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .._diagnostics import Diagnostic
from ..errors import NotAutoGradable, ResponseError
from ..types import Automation, Indentation, Normalization, OrderingContent, Unmatched
from . import _lint, _render
from ._base import (
    BaseQuestion,
    FreeText,
    MdqModel,
    raise_model_error,
    strip_optional_text,
)
from ._lint_codes import diag
from ._score import QuestionScore

__all__ = ["OrderingLine", "OrderingAlternative", "OrderingQuestion"]


#
# Ordering
#
#: The text of a line: no leading or trailing space or tab and no line
#: break. The empty text of a blank line is allowed (schema `pattern`).
LineText = Annotated[
    str, StringConstraints(pattern=r"^(?:[^ \t\r\n](?:[^\r\n]*[^ \t\r\n])?)?$")
]



def _check_blank_line_is_level_zero(line: tuple[int, str]) -> tuple[int, str]:
    """
    A blank line is at level 0 (ordering.md, "Whitespace"): the schema
    requires `level: 0` when the text is empty.

    Raises:
        ValueError: a line with empty text has a level above 0.
    """
    level, text = line
    if text == "" and level != 0:
        raise ValueError("a blank line must be at level 0")
    return line


#: One line of an ordering question, as an `[indentation level, text]`
#: pair. The level counts indentation units, not spaces, and the text
#: carries no leading indentation of its own. A blank line is at level 0.
OrderingLine = Annotated[
    tuple[Annotated[int, Field(ge=0)], LineText],
    AfterValidator(_check_blank_line_is_level_zero),
]


class OrderingAlternative(MdqModel):
    """
    One accepted or rejected ordering of a question's lines, with the
    feedback shown to the student whose response matched it.
    """

    #: At least one line (schema `minItems: 1`).
    lines: Annotated[list[OrderingLine], Field(min_length=1)]
    feedback: FreeText | None = None
    comment: FreeText | None = None


def _trimmed_alternative(rule: OrderingAlternative) -> OrderingAlternative:
    """`rule` without the whitespace the parser trims around its feedback and comment."""
    return rule.model_copy(
        update={
            "feedback": strip_optional_text(rule.feedback),
            "comment": strip_optional_text(rule.comment),
        }
    )


class OrderingQuestion(BaseQuestion[list[OrderingLine]]):
    """
    A question asking the student to sort a list of lines.

    `lines` is the answer key, always authored in the correct order; the
    student is always shown it shuffled, together with `extra`.
    """

    type: Literal["ordering"] = "ordering"
    lines: Annotated[list[OrderingLine], Field(min_length=2)]
    extra: list[OrderingLine] = Field(default_factory=list, min_length=1)
    accept: list[OrderingAlternative] = Field(default_factory=list, min_length=1)
    reject: list[OrderingAlternative] = Field(default_factory=list, min_length=1)
    content: OrderingContent
    highlight: Annotated[str | None, Field(default=None, min_length=1)] = None
    indentation: Indentation = "fixed"
    unmatched: Unmatched = "incorrect"
    #: Feedback for an incorrect response that no `reject` section gave
    #: feedback to (ordering.md, "Feedback").
    incorrect_feedback: FreeText | None = None
    normalizations: list[Normalization] = Field(default_factory=list)

    def _normalize(self) -> None:
        super()._normalize()
        self.accept = [_trimmed_alternative(rule) for rule in self.accept]
        self.reject = [_trimmed_alternative(rule) for rule in self.reject]

    @property
    def automation(self) -> Automation:
        """
        `automatic` under `unmatched: incorrect` (the default),
        `semi-automatic` under `unmatched: manual` (ordering.md,
        "Automation").
        """
        return "automatic" if self.unmatched == "incorrect" else "semi-automatic"

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(_lint.check_code_highlight(self.content, self.highlight))
        diagnostics.extend(check_ordering_duplicate_alternatives(self))
        diagnostics.extend(check_ordering_accept_repeats_answer_key(self))
        diagnostics.extend(check_ordering_unreachable_reject(self))
        diagnostics.extend(check_ordering_redundant_strict_indentation(self))
        diagnostics.extend(check_ordering_blank_lines(self))
        diagnostics.extend(check_ordering_reject_without_feedback(self))
        diagnostics.extend(check_ordering_visually_identical_lines(self))
        return diagnostics

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.indentation != "fixed":
            data["indentation"] = self.indentation
        if self.unmatched != "incorrect":
            data["unmatched"] = self.unmatched
        if self.incorrect_feedback is not None:
            data["incorrectFeedback"] = self.incorrect_feedback
        if self.normalizations:
            data["normalizations"] = self.normalizations
        return data

    _PUBLIC_KEYS: ClassVar[tuple[str, ...]] = (
        *BaseQuestion._PUBLIC_KEYS,
        "content", "highlight", "indentation", "normalizations",
    )  # fmt: skip

    def _public_body(self) -> dict[str, Any]:
        """
        `unmatched`, always present, like in a short answer question.
        `pool`: the `lines` and the `extra` lines together, as
        `[level, text]` pairs, sorted by text (code point order), then by
        level, so the order tells nothing about the answer (ordering.md,
        "Presentation"). The host still shuffles them. Under `"fixed"` a
        line keeps its authored level; under `"lenient"` and `"strict"`
        the student sets the levels, so every level is 0. The texts are
        verbatim: blank lines and repeated lines stay.

        `maxLevel`, only under `"lenient"` and `"strict"`: the highest
        authored level of any line in `lines`, `extra`, `accept` and
        `reject`, plus 1 (public-form.md, "Ordering"). It is a
        presentation limit only and does not change grading.
        """
        fixed = self.indentation == "fixed"
        pool = sorted(
            ((level if fixed else 0, text) for level, text in [*self.lines, *self.extra]),
            key=lambda line: (line[1], line[0]),
        )
        body: dict[str, Any] = {
            "unmatched": self.unmatched,
            "pool": [[level, text] for level, text in pool],
        }
        if not fixed:
            sections = [self.lines, self.extra]
            sections.extend(alt.lines for alt in [*self.accept, *self.reject])
            body["maxLevel"] = 1 + max(level for lines in sections for level, _ in lines)
        return body

    def correct_responses(self) -> list[list[list[int | str]]]:
        """
        See `BaseQuestion.correct_responses`: the `lines` block, then the
        lines of each `accept` entry, in document order, as `[level, text]`
        pairs with the authored levels.
        """
        blocks = [self.lines, *(alt.lines for alt in self.accept)]
        return [[[level, text] for level, text in block] for block in blocks]

    def _render_body(self) -> Iterable[str]:
        yield ""
        yield "[ordering]:"
        yield from _render.yield_ordering_content(
            self.lines, self.content, self.highlight
        )

    def _render_lines(self) -> Iterable[str]:
        # The sections come after the epilogue (ordering.md, "Body").
        yield from super()._render_lines()
        if self.extra:
            yield from _render.yield_ordering_section(
                "extra", self.extra, self.content, self.highlight
            )
        for alt in self.accept:
            yield from _render.yield_ordering_section(
                "accept",
                alt.lines,
                self.content,
                self.highlight,
                alt.feedback,
                alt.comment,
            )
        for alt in self.reject:
            yield from _render.yield_ordering_section(
                "reject",
                alt.lines,
                self.content,
                self.highlight,
                alt.feedback,
                alt.comment,
            )

    @field_validator("highlight")
    @classmethod
    def check_highlight_needs_code(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        """
        Raises:
            ValueError: `highlight` is set but `content` is not "code" (the
                `if`/`then` of the schema), which `load` reports as
                `schema-error`.
        """
        if value is not None and info.data.get("content") != "code":
            raise ValueError("highlight is only allowed when content is 'code'")
        return value

    @field_validator("normalizations")
    @classmethod
    def check_normalizations_unique(
        cls, value: list[Normalization]
    ) -> list[Normalization]:
        """
        Raises:
            ValueError: an entry repeats (JSON Schema `uniqueItems`), which
                `load` reports as `schema-error`.
        """
        if len(set(value)) != len(value):
            raise ValueError("normalizations must not repeat an entry")
        return value

    @model_validator(mode="after")
    def check_text_lines_not_empty(self) -> Self:
        """
        With `content: text`, no line has empty text: only a code block
        holds a blank line (ordering.md#whitespace).

        Raises:
            ValidationError: a line of a text question is empty
                (`empty-ordering-line`).
        """
        if self.content != "text":
            return self
        blocks = [self.lines, self.extra]
        blocks += [alt.lines for alt in (*self.accept, *self.reject)]
        if any(text == "" for block in blocks for _, text in block):
            raise_model_error(
                type(self).__name__,
                "empty-ordering-line",
                "a line of a text ordering question must not be empty",
                (),
                self.lines,
            )
        return self

    @model_validator(mode="after")
    def check_answers_not_empty(self) -> Self:
        """
        The `lines` block and every `accept` entry MUST hold at least one
        line after normalization: under `skip-blanks`, a block of blank
        lines is empty. An empty `reject` entry stays valid, since it can
        give feedback to an empty submission (ordering.md#additional-rules).

        Raises:
            PydanticCustomError: `empty-ordering-answer` -- the `lines`
                block or some `accept` entry is empty after normalization.
        """
        if not self.comparison_key(self.lines):
            raise_model_error(
                type(self).__name__,
                "empty-ordering-answer",
                "the lines block is empty after normalization",
                ("lines",),
                self.lines,
            )
        for index, alt in enumerate(self.accept):
            if not self.comparison_key(alt.lines):
                raise_model_error(
                    type(self).__name__,
                    "empty-ordering-answer",
                    "an accept entry is empty after normalization",
                    ("accept", index),
                    alt.lines,
                )
        return self

    @model_validator(mode="after")
    def check_accept_and_reject_disjoint(self) -> Self:
        """
        A question MUST NOT declare the same lines as both accepted and
        rejected, once fully normalized (ordering.md#additional-rules).
        The answer key is an accepted answer, so a `reject` entry that
        equals it is an overlap too.

        Raises:
            PydanticCustomError: `accept-reject-overlap` -- some `accept`
                entry, or the `lines` block, holds the same lines as
                some `reject` entry.
        """
        reject_keys = {self.comparison_key(alt.lines) for alt in self.reject}
        for index, alt in enumerate(self.accept):
            if self.comparison_key(alt.lines) in reject_keys:
                raise_model_error(
                    type(self).__name__,
                    "accept-reject-overlap",
                    "the same lines must not be declared in both accept and reject",
                    ("accept", index),
                    alt.lines,
                )
        answer_key = self.comparison_key(self.lines)
        for index, alt in enumerate(self.reject):
            if self.comparison_key(alt.lines) == answer_key:
                raise_model_error(
                    type(self).__name__,
                    "accept-reject-overlap",
                    "a reject entry must not hold the same lines as the answer key",
                    ("reject", index),
                    alt.lines,
                )
        return self

    @model_validator(mode="after")
    def check_accept_within_answer_key(self) -> Self:
        """
        The lines of an `accept` entry MUST be a sub-multiset of the
        `lines` block, identifying lines as `identity_key` does: it may leave lines out,
        but it may not hold a distractor, a foreign line or more copies
        of a line than the answer key has (ordering.md#additional-rules).

        Raises:
            PydanticCustomError: `accept-outside-answer-key` -- some
                `accept` entry holds a line the answer key lacks.
        """
        available = Counter(self.identity_key(self.lines))
        for index, alt in enumerate(self.accept):
            if Counter(self.identity_key(alt.lines)) - available:
                raise_model_error(
                    type(self).__name__,
                    "accept-outside-answer-key",
                    "an accept entry must not hold a line the answer key lacks",
                    ("accept", index),
                    alt.lines,
                )
        return self

    @model_validator(mode="after")
    def check_text_outline_levels(self) -> Self:
        """
        With `content: text`, the `lines` block and every `accept` and
        `reject` entry MUST be a valid outline: the first line is at
        level 0 and no line is more than one level deeper than the one
        before it. `extra` is exempt, since it is a pool of loose lines
        (ordering.md#additional-rules). Code content is not checked.

        Raises:
            PydanticCustomError: `invalid-outline-level` -- some block
                breaks the rule.
        """
        if self.content != "text":
            return self
        blocks: list[tuple[tuple[str | int, ...], list[OrderingLine]]] = [
            (("lines",), self.lines)
        ]
        blocks += [(("accept", i, "lines"), a.lines) for i, a in enumerate(self.accept)]
        blocks += [(("reject", i, "lines"), a.lines) for i, a in enumerate(self.reject)]
        for loc, block in blocks:
            problem = outline_problem(block)
            if problem is not None:
                raise_model_error(
                    type(self).__name__, "invalid-outline-level", problem, loc, block
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
        Whether a line's indentation level takes part in the comparison
        (ordering.md, "Indentation" and "Grading").

        Levels identify a line under `"fixed"` (the authored level, which
        the student cannot change) and under `"strict"`. Only `dedent`
        removes them, listed in `normalizations` or implied by
        `"lenient"`: it flattens every level to 0.
        """
        return "dedent" not in self.effective_normalizations()

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

    def identity_key(self, lines: Iterable[OrderingLine]) -> tuple[OrderingLine, ...]:
        """
        The form `lines` takes when checking which pool lines they use
        (ordering.md, "Response"): the one definition of line identity.

        Under `"fixed"` a line is the pair of level and text. Under
        `"lenient"` and `"strict"` the student sets the levels, so only
        the text identifies a line and every level is flattened to 0.
        With `skip-blanks`, blank lines are left out.
        """
        skip_blanks = "skip-blanks" in self.effective_normalizations()
        by_text = self.indentation != "fixed"
        return tuple(
            (0, text) if by_text else (level, text)
            for level, text in lines
            if not (skip_blanks and text.strip() == "")
        )

    def check_response_lines(self, lines: Iterable[OrderingLine]) -> None:
        """
        Check that `lines` can come from this question's presented pool:
        the `lines` and `extra` blocks together (ordering.md, "Response").

        Under `"fixed"` a line is identified by level and text, so a line
        at a level other than the authored one is not in the pool. Under
        `"lenient"` and `"strict"` the student may change levels, so only
        the text identifies a line. With `skip-blanks`, blank lines are
        left out on both sides. Leaving pool lines out is valid.

        With `content: text` under `"lenient"` and `"strict"`, the
        response must also be a valid outline (`outline_problem`). Under
        `"fixed"` the student cannot change levels, so an invalid outline
        is a wrong answer: it is graded and matches no declared answer.

        Raises:
            ResponseError: a line is not in the pool, a line is used
                more times than the pool offers it, or (under `"lenient"`
                and `"strict"`) a text response is not a valid outline.
        """
        lines = list(lines)
        if self.content == "text" and self.indentation != "fixed":
            problem = outline_problem(lines)
            if problem is not None:
                raise ResponseError(problem)

        pool = Counter(self.identity_key([*self.lines, *self.extra]))
        for line in self.identity_key(lines):
            if pool[line] <= 0:
                raise ResponseError(
                    f"Line {list(line)!r} is not in the pool, or is used more "
                    "often than the question offers it"
                )
            pool[line] -= 1

    def _incorrect(self) -> list[str]:
        """`incorrect_feedback` as a feedback list, empty when unset."""
        return [self.incorrect_feedback] if self.incorrect_feedback else []

    def _parse_response(self, response: object) -> list[OrderingLine]:
        """
        Raises:
            ResponseError: `response` is not a list of
                `[indentation level, text]` pairs (a string and a mapping
                are not), or holds a line the
                question did not present (`check_response_lines`).
        """
        if isinstance(response, (str, Mapping)) or not isinstance(response, Iterable):
            raise ResponseError(
                f"An ordering response must be a sequence of [level, text] pairs, "
                f"found {type(response).__name__}"
            )
        lines = coerce_ordering_lines(response)
        self.check_response_lines(lines)
        return lines

    def _score(self, response: list[OrderingLine]) -> QuestionScore:
        """
        Score 1 for the answer key or an accepted ordering, 0 for a
        rejected one, and otherwise whatever `unmatched` dictates. When
        several declared answers match, the first in document order
        wins: the `lines` block, then the `accept` entries, then the
        `reject` entries (an accepted and a rejected answer cannot match
        the same response, since they never hold the same lines).

        Raises:
            NotAutoGradable: nothing matched and `unmatched` is
                "manual", so the response is for a human to score.
        """
        key = self.comparison_key(response)

        if key == self.comparison_key(self.lines):
            return QuestionScore(score=1.0)

        for alt in self.accept:
            if key == self.comparison_key(alt.lines):
                feedback = [alt.feedback] if alt.feedback else []
                return QuestionScore(score=1.0, feedback=feedback)

        for alt in self.reject:
            if key == self.comparison_key(alt.lines):
                feedback = [alt.feedback] if alt.feedback else self._incorrect()
                return QuestionScore(score=0.0, feedback=feedback)

        if self.unmatched == "incorrect":
            return QuestionScore(score=0.0, feedback=self._incorrect())
        raise NotAutoGradable(
            "ordering response matched no answer key and requires manual grading"
        )


#
# Utilities
#


def outline_problem(lines: Iterable[OrderingLine]) -> str | None:
    """
    Why `lines` is not a valid outline, or `None` when it is: the first
    line must be at level 0 and each level is at most one more than the
    level before it.
    """
    previous = -1
    for index, (level, text) in enumerate(lines):
        if level > previous + 1:
            where = "the first line" if index == 0 else f"line {index}"
            return (
                f"{where} {[level, text]!r} is at level {level}, but the "
                f"deepest level allowed there is {previous + 1}"
            )
        previous = level
    return None


def coerce_ordering_lines(lines: Iterable[object]) -> list[OrderingLine]:
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


def check_ordering_duplicate_alternatives(
    question: OrderingQuestion,
) -> Iterator[Diagnostic]:
    """
    ordering.md#acceptedrejected-answers: a question SHOULD NOT declare
    two `accept` sections, or two `reject` sections, whose lines are the
    same once fully normalized -- every entry of `normalizations`, plus
    whatever `indentation` implies. An accept/reject pair is a model
    error (`accept-reject-overlap`) and never reaches this check.
    """
    for section in ("accept", "reject"):
        seen: dict[tuple[Any, ...], tuple[str, int]] = {}
        for index, alt in enumerate(getattr(question, section)):
            key = question.comparison_key(alt.lines)
            first = seen.get(key)
            if first is not None:
                first_section, first_index = first
                yield diag(
                    code="duplicate-alternative-lines",
                    path=(section, index, "lines"),
                    message=(
                        f"{section}[{index}] holds the same lines as "
                        f"{first_section}[{first_index}], once fully "
                        f"normalized"
                    ),
                )
            else:
                seen[key] = (section, index)


def check_ordering_accept_repeats_answer_key(
    question: OrderingQuestion,
) -> Iterator[Diagnostic]:
    """ordering.md#acceptedrejected-answers: `accept` SHOULD NOT repeat `lines`."""
    answer_key = question.comparison_key(question.lines)
    for index, alt in enumerate(question.accept):
        if question.comparison_key(alt.lines) == answer_key:
            yield diag(
                code="accept-repeats-answer-key",
                path=("accept", index, "lines"),
                message=(
                    f"accept[{index}] repeats the [ordering] block's own "
                    f"lines, once fully normalized"
                ),
            )


def check_ordering_unreachable_reject(
    question: OrderingQuestion,
) -> Iterator[Diagnostic]:
    """
    ordering.md#acceptedrejected-answers: a `reject` entry that uses a
    line, or more copies of a line, than the presented pool (`lines`
    plus `extra`) offers can never match a response. Lines are identified
    as in `OrderingQuestion.identity_key`.
    """
    pool = Counter(question.identity_key(question.lines))
    pool.update(question.identity_key(question.extra))
    for index, alt in enumerate(question.reject):
        if Counter(question.identity_key(alt.lines)) - pool:
            yield diag(
                code="unreachable-alternative",
                path=("reject", index, "lines"),
                message=(
                    f"reject[{index}] uses a line, or more copies of a "
                    f"line, than the lines and extra blocks offer, so no "
                    f"response can match it"
                ),
            )


def check_ordering_redundant_strict_indentation(
    question: OrderingQuestion,
) -> Iterator[Diagnostic]:
    """
    ordering.md#indentation[^8]: `dedent` flattens every line to level 0,
    so `indentation: "strict"` has nothing left to compare.
    `indentation: "lenient"` implies `dedent` and therefore never
    combines with `"strict"` in the first place, so only an explicit
    `dedent` in `normalizations` can trigger this.
    """
    if question.indentation != "strict":
        return
    if "dedent" not in question.effective_normalizations():
        return
    yield diag(
        code="redundant-strict-indentation",
        path=("indentation",),
        message=(
            "indentation is 'strict' but 'dedent' is normalized, which "
            "flattens every line to level 0, so there is nothing left "
            "for 'strict' to compare"
        ),
    )


def check_ordering_blank_lines(
    question: OrderingQuestion,
) -> Iterator[Diagnostic]:
    """
    ordering.md#additional-rules: a blank `lines`/`extra` entry should
    only appear when `skip-blanks` is normalized -- otherwise it counts
    when comparing a response.
    """
    if "skip-blanks" in question.effective_normalizations():
        return

    for field_name in ("lines", "extra"):
        for index, (_, text) in enumerate(getattr(question, field_name)):
            if text.strip() == "":
                yield diag(
                    code="blank-ordering-line",
                    path=(field_name, index),
                    message=(
                        "line is blank, and 'skip-blanks' is not "
                        "normalized, so it counts when comparing a "
                        "response"
                    ),
                )


def check_ordering_reject_without_feedback(
    question: OrderingQuestion,
) -> Iterator[Diagnostic]:
    """ordering.md#feedback: a `reject` section SHOULD declare feedback."""
    for index, alt in enumerate(question.reject):
        if alt.feedback is None:
            yield diag(
                code="reject-without-feedback",
                path=("reject", index),
                message=(
                    f"reject[{index}] declares no feedback, so it explains "
                    f"nothing to the student"
                ),
            )


def check_ordering_visually_identical_lines(
    question: OrderingQuestion,
) -> Iterator[Diagnostic]:
    """
    ordering.md#body: two `lines`/`extra` entries at the same
    indentation level should not render alike while differing in their
    raw markdown source -- a student ordering the rendered text cannot
    tell such a pair apart. Only meaningful for `content: "text"`: a
    code block's content is shown verbatim, never rendered.
    """
    if question.content != "text":
        return

    seen: dict[tuple[int, str], tuple[str, int, str]] = {}
    for field_name in ("lines", "extra"):
        for index, (level, text) in enumerate(getattr(question, field_name)):
            key = (level, _lint.render_visual_key(text))
            first = seen.get(key)
            if first is None:
                seen[key] = (field_name, index, text)
                continue

            first_field, first_index, first_text = first
            if text == first_text:
                continue  # an intentional repeat, not a same-render pair.
            yield diag(
                code="visually-identical-lines",
                path=(field_name, index),
                message=(
                    f"line renders the same as {first_field}[{first_index}] "
                    f"but is written differently in source; a student "
                    f"ordering the rendered text cannot tell them apart"
                ),
            )

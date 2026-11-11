"""
Code questions (docs/question-types/code.md): `TestSource`, `RubricItem`,
`FullRubricItem` and `CodeQuestion`.

MDQ never runs code and does not read the content of a test source, except
its annotations. A runner outside MDQ produces a `RunnerReport`, and the
question turns the report and the scores of the instructor into a score.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from functools import cached_property
from typing import Annotated, Any, ClassVar, Literal, Self, cast

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError

from .. import _parser
from .. import types as t
from .._diagnostics import Diagnostic
from .._markdown import UNICODE_SPACE, strip_bom
from ..errors import NotAutoGradable, ReportError, UnresolvedTestSource
from ..types import Automation
from . import _lint, _render
from ._base import (
    BaseQuestion,
    FreeText,
    MdqModel,
    ModelErrorCode,
    raise_model_error,
    raise_model_errors,
)
from ._lint_codes import diag
from ._report import ReportCase, RunnerReport
from ._score import QuestionScore
from ._text import parse_text_response

__all__ = ["CodeQuestion", "FullRubricItem", "RubricItem", "TestSource"]

#: A rubric value: a JSON number, never a `bool`.
Number = (
    Annotated[int, Field(strict=True)]
    | Annotated[float, Field(strict=True, allow_inf_nan=False)]
)

#: `origin` of the schema, the `ORIGIN` terminal of code.md: a relative path
#: with no scheme, query, fragment or line break, and an extension.
_ORIGIN_RE = re.compile(
    r"(?![A-Za-z][A-Za-z0-9+.-]*:)(?!/)[^?#\r\n]*[.][^.\\/?#\r\n]+"
)
#: `format` of the schema: the first word of an info string, which has no
#: space and no backtick.
_FORMAT_RE = re.compile(rf"[^{UNICODE_SPACE}`]+")
#: `language` of the schema: at least one character that is not a Unicode space.
_VISIBLE_LANGUAGE_RE = re.compile(rf"[^{UNICODE_SPACE}]")
#: `file` of the schema: a plain name.
_FILE_RE = re.compile(rf"(?!\.\.?\Z)(?![{UNICODE_SPACE}]+\Z)[^/\\]+")


class TestSource(MdqModel):
    """
    One test source: a fenced block of `## [tests]` or a file that a link of
    the section points to (code.md, "Test sources").

    A linked source has an `origin` and no `text` until `CodeQuestion.resolve`
    fills it: it is **unresolved**. A fenced source has `text` and no
    `origin`. Once resolved, a linked source keeps its `origin`.
    """

    #: Not a test class, whatever the name says.
    __test__: ClassVar[bool] = False

    #: The test format: the first word of the info string of a fence, or the
    #: extension of a linked file. The case is kept.
    format: str
    #: The code text. A fenced block has one line ending after each line.
    text: str | None = None
    origin: Annotated[str, Field(min_length=1)] | None = None

    @field_validator("format")
    @classmethod
    def check_format_is_a_word(cls, value: str) -> str:
        """code.md, "Test format": not empty, no Unicode space, no backtick."""
        if not _FORMAT_RE.fullmatch(value):
            raise PydanticCustomError(
                "schema-error",
                "the format must be a word that is not empty, with no space and no backtick",
            )
        return value

    @field_validator("origin")
    @classmethod
    def check_origin_is_relative(cls, value: str | None) -> str | None:
        """
        code.md, "Test sources": no scheme, no `/` at the start, no `?`, no
        `#`, no line break, and an extension.
        """
        if value is not None and not _ORIGIN_RE.fullmatch(value):
            raise PydanticCustomError(
                "schema-error",
                "the origin must be a relative path with no scheme, query, fragment or "
                "line break, and a file name with an extension",
            )
        return value

    @model_validator(mode="after")
    def check_format_is_the_extension_of_the_origin(self) -> Self:
        """code.md, "Test format": the format of a linked file is its extension."""
        if self.origin is not None:
            extension = self.origin.rsplit(".", 1)[1]
            if self.format != extension:
                raise_model_error(
                    type(self).__name__,
                    "test-format-disagrees-with-origin",
                    f"the format {self.format!r} is not the extension {extension!r} of "
                    f"the origin {self.origin!r}",
                    ("format",),
                    self.format,
                )
        return self

    @model_validator(mode="after")
    def check_has_text_or_origin(self) -> Self:
        """The `anyOf` of the schema: a source has a `text` or an `origin`."""
        if self.text is None and self.origin is None:
            raise PydanticCustomError(
                "schema-error", "a test source must have a `text` or an `origin`"
            )
        return self

    @model_validator(mode="after")
    def check_annotations(self) -> Self:
        """
        code.md, "Annotations": the annotations of the text follow the rubric
        item syntax. A source with no text is not checked: the check runs
        when it is resolved.
        """
        if self.text is None:
            return self
        problems = self.annotations.problems
        if problems:
            raise_model_errors(
                type(self).__name__,
                [(p.code, f"line {p.line}: {p.message}", ("text",)) for p in problems],
                self.text,
            )
        return self

    @property
    def resolved(self) -> bool:
        """Whether the source has its `text`."""
        return self.text is not None

    @cached_property
    def annotations(self) -> _parser.Annotations:
        """
        The annotations of the text, with their regions.

        Raises:
            UnresolvedTestSource: the source has no text.
        """
        if self.text is None:
            raise UnresolvedTestSource(
                f"the test source {self.origin!r} is not resolved: it has no text"
            )
        return _parser.scan_annotations(self.text)

    @property
    def line_count(self) -> int:
        """
        The number of lines of the text, as the runner counts them. A final
        line ending does not start another line.

        Raises:
            UnresolvedTestSource: the source has no text.
        """
        return len(self.annotations.lines)


class RubricItem(MdqModel):
    """
    A manual item of `## [rubric]`: the instructor applies it. It has the
    shape of a choice, with `value` and `binding` in place of the verdict.
    """

    #: Relative points. Absent means 1.
    value: Number | None = None
    binding: Literal["manual"]
    #: The criterion, as Markdown.
    text: FreeText
    feedback: FreeText | None = None
    comment: FreeText | None = None

    @model_validator(mode="after")
    def check_criterion_start(self) -> Self:
        """
        rubric.md, "Criterion": a criterion does not start with `{`, `>`, a
        `!` not followed by `[`, or a `[` that does not start a link. The
        path is the item, in every form of the document.
        """
        try:
            _parser.check_criterion_start(self.text.lstrip(" \t"))
        except _parser.RubricSyntaxError as exc:
            raise_model_error(type(self).__name__, "invalid-rubric-item", str(exc), (), self.text)
        return self

    @property
    def points(self) -> int | float:
        """The value of the item: 1 when it has none."""
        return 1 if self.value is None else self.value


@dataclass(frozen=True)
class FullRubricItem:
    """
    One item of the full rubric (code.md, "Full rubric"): derived from the
    test sources and the `rubric`, never a field of the document.

    Attributes:
        value: The value, always present.
        binding: `tests` or `manual`.
        text: The criterion. `None` in an implicit item.
        feedback: The feedback, if any.
        comment: The comment, if any.
        source: An item of tests: the index of the test source.
        line: An item of tests: the line of its annotation. `None` in an
            implicit item.
        public: An item of tests: `{public}` or `{example}`.
        example: An item of tests: `{example}`.
    """

    value: int | float
    binding: Literal["tests", "manual"]
    text: str | None = None
    feedback: str | None = None
    comment: str | None = None
    source: int | None = None
    line: int | None = None
    public: bool = False
    example: bool = False


class CodeQuestion(BaseQuestion[str]):
    """
    A question whose student submits one source file.

    Test sources and a rubric score the submission. A runner executes the test
    cases (`score_response` takes its `RunnerReport`), and the instructor
    applies the manual items of `rubric`.
    """

    type: Literal["code"] = "code"
    language: Annotated[str, Field(min_length=1)] | None = None
    file: Annotated[str, Field(min_length=1)] | None = None
    tests: Annotated[list[TestSource], Field(min_length=1)] | None = None
    rubric: Annotated[list[RubricItem], Field(min_length=1)] | None = None
    #: The starting code, as Markdown: exactly one fenced code block.
    template: FreeText | None = None
    #: A model answer, as Markdown. The first fenced code block is the
    #: reference solution.
    answer_key: FreeText | None = None

    @field_validator("language")
    @classmethod
    def check_language_is_visible(cls, value: str | None) -> str | None:
        """code.md, "Frontmatter": not only Unicode spaces."""
        if value is not None and not _VISIBLE_LANGUAGE_RE.search(value):
            raise PydanticCustomError(
                "schema-error", "the language must have a character that is not a space"
            )
        return value

    @field_validator("file")
    @classmethod
    def check_file_is_a_plain_name(cls, value: str | None) -> str | None:
        """code.md, "Frontmatter": no `/`, no `\\`, not `.` or `..`, not only spaces."""
        if value is not None and not _FILE_RE.fullmatch(value):
            raise PydanticCustomError(
                "schema-error",
                "the file must be a plain name: not `.` or `..`, not only spaces, "
                "with no `/` and no `\\`",
            )
        return value

    @model_validator(mode="after")
    def check_template_is_one_fenced_block(self) -> Self:
        """code.md, "Template": in every form, exactly one fenced code block."""
        if self.template is None:
            return self
        kinds = [kind for kind, _ in _parser.reconstruct_blocks(self.template)]
        if kinds != ["fence"] or _parser.has_unclosed_fence(self.template):
            raise_model_error(
                type(self).__name__,
                "forbidden-block-element",
                "'template' must be exactly one fenced code block, with its closing fence",
                ("template",),
                self.template,
            )
        return self

    @model_validator(mode="after")
    def check_answer_key_has_no_forbidden_heading(self) -> Self:
        """code.md, "Answer key": the rules of the essay answer key."""
        if self.answer_key:
            for description in _parser.find_answer_key_forbidden_elements(self.answer_key):
                raise_model_error(
                    type(self).__name__,
                    "forbidden-block-element",
                    f"'answerKey' holds {description}, which code.md's "
                    f"\"Answer key\" does not allow",
                    ("answerKey",),
                    self.answer_key,
                )
        return self

    #
    # Derived values
    #
    @property
    def reference_solution(self) -> str | None:
        """
        The code text of the first fenced block that is a direct child of
        the `answerKey`, or `None` (code.md, "Answer key").
        """
        return None if self.answer_key is None else _parser.first_fenced_code(self.answer_key)

    @property
    def resolved(self) -> bool:
        """Whether every test source has its `text`."""
        return all(source.resolved for source in self.tests or [])

    def _require_resolved(self) -> None:
        """
        Raises:
            UnresolvedTestSource: a test source has no text.
        """
        for index, source in enumerate(self.tests or []):
            if not source.resolved:
                raise UnresolvedTestSource(
                    f"tests[{index}] ({source.origin!r}) is not resolved: call "
                    "`resolve` with the text of its file"
                )

    def full_rubric(self) -> list[FullRubricItem]:
        """
        Every item of the question: the items of the test sources, in the
        order of the sources and then of the lines, with the implicit item of
        each source that has no annotation, and then the items of `rubric`.

        Raises:
            UnresolvedTestSource: a test source has no text.
        """
        self._require_resolved()
        items: list[FullRubricItem] = []
        for index, source in enumerate(self.tests or []):
            scan = source.annotations
            if not scan.annotated:
                items.append(FullRubricItem(1, "tests", source=index))
                continue
            items.extend(
                FullRubricItem(
                    1 if note.value is None else note.value,
                    "tests",
                    note.text,
                    note.feedback,
                    note.comment,
                    index,
                    note.line,
                    note.public,
                    note.example,
                )
                for note in scan.items
            )
        items.extend(
            FullRubricItem(item.points, "manual", item.text, item.feedback, item.comment)
            for item in self.rubric or []
        )
        return items

    @property
    def automation(self) -> Automation:
        """
        `manual` with no test source, `automatic` with tests and no manual
        item that counts, `semi-automatic` with both (code.md,
        "Automation"). It does not need the text of a source.
        """
        if not self.tests:
            return "manual"
        if any(item.points != 0 for item in self.rubric or []):
            return "semi-automatic"
        return "automatic"

    def resolve(self, texts: Mapping[str, str]) -> Self:
        """
        Return a copy in which each linked test source whose `origin` is a key
        of `texts` has its `text` (code.md, "JSON form").

        A key fills every source with that origin, and a key that no source
        uses is ignored. A source whose origin is not a key stays unresolved,
        with no error: a second call with a larger map fills the rest. The
        origin is an opaque key, compared as a string. A leading byte order
        mark (U+FEFF) of a text is removed before the lines are counted. A
        source that already has a text is not touched.

        Raises:
            pydantic.ValidationError: a text breaks the rules of the
                annotations (`invalid-rubric-item`, `blank-text`). The `loc`
                of each error is `("tests", i, "text")`.
        """
        if not self.tests:
            return self.model_copy()
        sources: list[TestSource] = []
        for index, source in enumerate(self.tests):
            origin = source.origin
            if source.text is None and origin is not None and origin in texts:
                try:
                    source = TestSource(
                        format=source.format, origin=origin, text=strip_bom(texts[origin])
                    )
                except ValidationError as exc:
                    raise_model_errors(
                        type(self).__name__,
                        [
                            (
                                # `TestSource` raises only model error codes.
                                cast(ModelErrorCode, error["type"]),
                                error["msg"],
                                ("tests", index, *error["loc"]),
                            )
                            for error in exc.errors()
                        ],
                        texts[origin],
                    )
            sources.append(source)
        return self.model_copy(update={"tests": sources})

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(
            _lint.check_unsafe_thematic_break(self.answer_key, ("answerKey",))
        )
        if self.resolved:
            rubric = self.full_rubric()
            if rubric and not any(item.value > 0 for item in rubric):
                diagnostics.append(
                    diag(
                        code="rubric-without-positive-item",
                        path=(),
                        message=(
                            "the sum of the positive values of the rubric is 0, so "
                            "the question can never score above 0"
                        ),
                    )
                )
        return diagnostics

    #
    # Serialization
    #
    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.language is not None:
            data["language"] = self.language
        if self.file is not None:
            data["file"] = self.file
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        yield "[code]"

    def _render_lines(self) -> Iterable[str]:
        yield from super()._render_lines()
        if self.template is not None:
            yield ""
            yield "## [template]"
            yield ""
            yield self.template
        if self.tests:
            yield ""
            yield "## [tests]"
            for source in self.tests:
                yield ""
                yield from _render_source(source)
        if self.rubric:
            yield ""
            yield "## [rubric]"
            yield ""
            for item in self.rubric:
                yield from _render_rubric_item(item)
        if self.answer_key is not None:
            yield ""
            yield "## [answer-key]"
            yield ""
            yield self.answer_key

    #
    # Public form
    #
    _PUBLIC_KEYS: ClassVar[tuple[str, ...]] = (
        *BaseQuestion._PUBLIC_KEYS, "language", "file", "template",
    )  # fmt: skip

    def public_tests(self) -> list[dict[str, Any]]:
        """
        The public regions that have a text: one entry for each, in the order
        of the test sources and then of the lines (public-form.md, "Public
        tests"). Each entry has `format`, `text`, `firstLine` and `example`.

        Raises:
            UnresolvedTestSource: a test source has no text.
        """
        self._require_resolved()
        entries: list[dict[str, Any]] = []
        for source in self.tests or []:
            scan = source.annotations
            for note in scan.items:
                shown = scan.public_text(note) if note.public else None
                if shown is not None:
                    text, first_line = shown
                    entries.append(
                        {
                            "format": source.format,
                            "text": text,
                            "firstLine": first_line,
                            "example": note.example,
                        }
                    )
        return entries

    def _public_body(self) -> dict[str, Any]:
        tests = self.public_tests()
        return {"publicTests": tests} if tests else {}

    def correct_responses(self) -> list[t.TextResponse]:
        """
        See `BaseQuestion.correct_responses`: the reference solution, or
        nothing when the question has none. It passes every test case, but a
        manual item of the rubric still waits for the instructor, so it does
        not score 1 by itself.
        """
        solution = self.reference_solution
        return [] if solution is None else [solution]

    #
    # Grading
    #
    def _parse_response(self, response: object) -> t.TextResponse:
        """
        Raises:
            ResponseError: `response` is not a string.
        """
        return parse_text_response(response)

    def score_response(
        self,
        response: object,
        *,
        report: RunnerReport | Mapping[str, Any] | None = None,
        manual: Sequence[float | None] | None = None,
        instructor: float | None = None,
    ) -> QuestionScore:
        """
        Return the score of `response`, computed from the runner `report` and
        the scores of the instructor (code.md, "Grading").

        The checks run in this order: the response, the test sources, the
        scores of the instructor, the report and then whether the response is
        pending.

        Args:
            response: The content of the submitted file.
            report: The report of the runner for `response`, as a
                `RunnerReport` or as the JSON mapping it comes from. Missing
                when the question has no test source.
            manual: The score in [0, 1] of each item of `rubric`, by
                position, `None` for an item with no score yet.
            instructor: The score in [0, 1] of the whole response. Only a
                question with no rubric item at all takes it.

        Raises:
            ResponseError: `response` is not a string.
            UnresolvedTestSource: a test source has no text.
            ValueError: `manual` or `instructor` does not fit the question: a
                list of another length than `rubric`, a score outside
                [0, 1], or `instructor` for a question that has a rubric item.
                This is a mistake of the host, not a `GradingError`.
            ReportError: the report does not follow the schema, does not fit
                the question, or is missing while there is a test source.
            NotAutoGradable: the response is pending: the status of the
                report is `runner-error`, a manual item that counts has no
                score, or the question has no rubric item and `instructor`
                is missing.
        """
        parsed = self._parse_response(response)
        return self._grade(parsed, report, manual, instructor)

    def _score(self, response: t.TextResponse) -> QuestionScore:
        """Grade with no report and no score of the instructor."""
        return self._grade(response, None, None, None)

    def _grade(
        self,
        response: t.TextResponse,
        report: RunnerReport | Mapping[str, Any] | None,
        manual: Sequence[float | None] | None,
        instructor: float | None,
    ) -> QuestionScore:
        self._require_resolved()
        rubric = self.rubric or []
        has_items = bool(self.tests) or bool(rubric)
        _check_manual(manual, instructor, len(rubric), has_items)
        parsed = self._check_report(report)

        if parsed is not None and parsed.status == "runner-error":
            raise NotAutoGradable(
                "the runner failed (status `runner-error`): the response is "
                "pending, never 0"
            )
        scores = list(manual) if manual is not None else [None] * len(rubric)
        for item, score in zip(rubric, scores, strict=True):
            if item.points != 0 and score is None:
                raise NotAutoGradable(
                    f"the manual item {item.text!r} has no score of the instructor"
                )
        if not has_items:
            if instructor is None:
                raise NotAutoGradable("the instructor has not scored the response")
            return QuestionScore(score=float(instructor))

        credit = Fraction(0)
        discount = Fraction(0)
        positive = Fraction(0)
        build_error = parsed is not None and parsed.status == "build-error"
        cases = [] if parsed is None or build_error else parsed.cases
        for index, source in enumerate(self.tests or []):
            scan = source.annotations
            owned = [case for case in cases if case.source == index]
            groups: list[tuple[Fraction, list[ReportCase]]]
            if not scan.annotated:
                groups = [(Fraction(1), owned)]
            else:
                groups = [
                    (
                        _exact(1 if note.value is None else note.value),
                        [c for c in owned if note.line <= c.line <= note.end],
                    )
                    for note in scan.items
                ]
            for value, group in groups:
                if value > 0:
                    positive += value
                    if group:
                        credit += value * sum(c.passed for c in group) / len(group)
                elif value < 0:
                    if build_error:
                        discount += -value
                    elif group:
                        failed = sum(not c.passed for c in group)
                        discount += -value * failed / len(group)
        for item, score in zip(rubric, scores, strict=True):
            points = _exact(item.points)
            earned = _exact(score or 0)
            if points > 0:
                positive += points
                credit += points * earned
            elif points < 0:
                discount += -points * earned
        if positive == 0:
            return QuestionScore(score=0.0)
        return QuestionScore(score=float(max(Fraction(-1), (credit - discount) / positive)))

    def _check_report(
        self, report: RunnerReport | Mapping[str, Any] | None
    ) -> RunnerReport | None:
        """
        The report as a `RunnerReport`, checked against the question
        (runner-report.md, "Errors").

        Raises:
            ReportError: the report is invalid or does not fit the question.
        """
        if report is None:
            if self.tests:
                raise ReportError("the question has a test source and no runner report")
            return None
        if isinstance(report, RunnerReport):
            parsed = report
        else:
            try:
                parsed = RunnerReport.model_validate(report, by_alias=True, by_name=False)
            except ValidationError as exc:
                raise ReportError(f"the runner report is not valid: {exc}") from exc
        if parsed.status != "completed":
            return parsed
        tests = self.tests or []
        for case in parsed.cases:
            if case.source >= len(tests):
                raise ReportError(
                    f"a case has the source {case.source}, but the question has "
                    f"{len(tests)} test source(s)"
                )
            if case.line > tests[case.source].line_count:
                raise ReportError(
                    f"a case has the line {case.line}, after the last line of "
                    f"tests[{case.source}]"
                )
        return parsed


def _check_manual(
    manual: Sequence[float | None] | None,
    instructor: float | None,
    rubric_size: int,
    has_items: bool,
) -> None:
    """
    Raises:
        ValueError: the scores of the instructor do not fit the question
            (responses.md, "Code").
    """
    if manual is not None:
        if len(manual) != rubric_size:
            raise ValueError(
                f"{len(manual)} manual score(s) for {rubric_size} item(s) of `rubric`"
            )
        for score in manual:
            if score is not None and not _is_unit_score(score):
                raise ValueError(f"the manual score {score!r} is not a number in [0, 1]")
    if instructor is not None:
        if has_items:
            raise ValueError(
                "one score for the whole response is only for a question with no "
                "rubric item: score the manual items instead"
            )
        if not _is_unit_score(instructor):
            raise ValueError(f"the score {instructor!r} is not a number in [0, 1]")


def _exact(value: int | float) -> Fraction:
    """
    The exact value of the decimal text of a number (`0.1` is 1/10, not the
    nearest double), so the score has one rounding, at the end.
    """
    return Fraction(repr(value))


def _is_unit_score(value: object) -> bool:
    """Whether `value` is a number in [0, 1]. A `bool` is not a number here."""
    return isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= 1


#
# Rendering
#
def _fence_for(text: str) -> str:
    """A backtick fence longer than any run of backticks that starts a line of `text`."""
    longest = max(
        (len(m.group(0)) for m in re.finditer(r"(?m)^[ ]{0,3}`+", text)), default=0
    )
    return "`" * max(3, longest + 1)


def _escape_link_text(text: str) -> str:
    return re.sub(r"([\\\[\]`*_<>&])", r"\\\1", text)


def _render_source(source: TestSource) -> Iterable[str]:
    """A test source as Markdown: a link for a linked source, else a fence."""
    if source.origin is not None:
        origin = source.origin
        if re.search(r"[ ()<>\\&]", origin):
            origin = "<" + re.sub(r"([\\<>&])", r"\\\1", origin) + ">"
        yield f"[{_escape_link_text(source.origin)}]({origin})"
        return
    text = source.text or ""
    fence = _fence_for(text)
    # The info string reads backslash escapes and entities back.
    yield f"{fence}{re.sub(r'([\\&])', r'\\\1', source.format)}"
    if text:
        yield text.removesuffix("\n")
    yield fence


def _decimal(value: int | float) -> str:
    """The plain decimal text of a number, with no exponent (`1e-07` is `0.0000001`)."""
    return format(Decimal(repr(value)), "f")


def _render_rubric_item(item: RubricItem) -> Iterable[str]:
    """An item of `## [rubric]` as a list item."""
    value = ""
    if item.value is not None:
        sign = "-" if item.value < 0 else "+"
        value = f"[{sign}{_decimal(abs(item.value))}] "
    yield from _render.yield_item(f"{value}{{manual}} ", item.text, item.feedback, item.comment)

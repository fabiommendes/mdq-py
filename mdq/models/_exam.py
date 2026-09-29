"""
Exams: the `Question`/`ExamEntry` unions, `Include`/`IncludeAll`,
`Exam` itself, and `QuestionRoot` (the document-root wrapper `mdq.load`
validates a bare question against).

`ExamStart`/`ExamDuration` are `Exam.start`/`.duration`'s field types --
`Annotated` wrappers around `mdq._schedule`'s parse/format pair, not
Literal aliases, so they stay here rather than in `mdq.types` and are
not part of the package's re-exported surface.
"""

from __future__ import annotations

import random
import re
import weakref
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Iterable, Literal, Mapping, Self, Sequence

from pydantic import (
    BeforeValidator,
    Discriminator,
    Field,
    PlainSerializer,
    RootModel,
    Tag,
    field_validator,
    model_validator,
)

from .. import _parser, _schedule
from .._diagnostics import Diagnostic
from ..errors import UnresolvedInclude
from .._banks import QuestionBank
from ..types import ExamGrading, PenaltyPolicy
from . import _lint, _render
from ._base import (
    BaseQuestion,
    MdqModel,
    _raise_unique_id_error,
    _validate_locale,
    _validate_uuid,
)
from ._choice import MultipleChoiceQuestion, MultipleSelectionQuestion, TrueFalseQuestion
from ._fill_in import FillInQuestion
from ._numeric import NumericQuestion
from ._ordering import OrderingQuestion
from ._query import QuerySyntaxError, parse_query
from ._text import EssayQuestion, ShortAnswerQuestion

__all__ = [
    "Question",
    "QuestionRoot",
    "Include",
    "IncludeAll",
    "ExamEntry",
    "Select",
    "select_random",
    "Exam",
]


#: When an exam begins: a date, or a date-time that may carry a UTC
#: offset. Serialized in canonical ISO 8601 form.
ExamStart = Annotated[
    datetime | date,
    BeforeValidator(_schedule.parse_start),
    PlainSerializer(_schedule.format_start),
]

#: How long an exam lasts. Serialized as a canonical ISO 8601 duration.
ExamDuration = Annotated[
    timedelta,
    BeforeValidator(_schedule.parse_duration),
    PlainSerializer(_schedule.format_duration),
]


def _implicit_question_id(index: int) -> str:
    """
    The implicit id a question at 0-based `index` would get: `q1` for the
    first block, `q2` for the second, and so on -- counting every block
    in the exam, includes included (exam.md, "Question ids").
    """
    return f"q{index + 1}"


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
def _check_no_extra_include_fields(model: MdqModel) -> None:
    """
    exam.md, "Question and include blocks": an include block holds
    exactly one of `include`/`include-all` (plus `max` for the latter).
    No other field is allowed, in the Markdown path (where
    `mdq._parser._exam` keeps whatever the block's frontmatter wrote,
    instead of dropping it) or the dict/YAML one (which lands here
    directly) -- both report the same `unknown-include-field` error.
    """
    extra = model.model_extra or {}
    if not extra:
        return
    key = next(iter(extra))
    _raise_unique_id_error(
        type(model).__name__,
        "unknown-include-field",
        f"{key!r} is not a field an include block accepts",
        (key,),
        extra[key],
    )


class Include(MdqModel):
    """
    A reference to one question stored outside the exam, by its id --
    schema/exam.yaml#/$defs/Include.
    """

    #: `extra="allow"` (instead of the base `"forbid"`) lets an unknown
    #: field reach `check_no_extra_fields` below, so it can be reported
    #: as `unknown-include-field` rather than pydantic's generic
    #: `extra_forbidden`.
    model_config = MdqModel.model_config | {"extra": "allow"}

    include: str

    @model_validator(mode="after")
    def check_no_extra_fields(self) -> Self:
        _check_no_extra_include_fields(self)
        return self


class IncludeAll(MdqModel):
    """
    A query for questions stored outside the exam --
    schema/exam.yaml#/$defs/IncludeAll.
    """

    model_config = MdqModel.model_config | {"extra": "allow"}

    include_all: Annotated[str, Field(alias="include-all", min_length=1)]
    max: Annotated[int | None, Field(default=None, ge=1, strict=True)] = None

    @model_validator(mode="after")
    def check_no_extra_fields(self) -> Self:
        _check_no_extra_include_fields(self)
        return self


def _entry_kind(value: Any) -> str:
    """The tag of `ExamEntry` that `value` validates against."""
    if isinstance(value, Include):
        return "include"
    if isinstance(value, IncludeAll):
        return "include-all"
    if isinstance(value, Mapping) and "type" not in value:
        if "include-all" in value or "include_all" in value:
            return "include-all"
        if "include" in value:
            return "include"
    return "question"


#: One entry of an exam's `questions`: a question written inline, or an
#: include block that `Exam.resolve` replaces -- schema/exam.yaml#/$defs/Entry.
ExamEntry = Annotated[
    Annotated[Question, Tag("question")]
    | Annotated[Include, Tag("include")]
    | Annotated[IncludeAll, Tag("include-all")],
    Discriminator(_entry_kind),
]

#: Chooses which questions an `include-all` block adds. It receives the
#: ids that match the query and are not in the exam yet, sorted, and the
#: block's `max`. It returns the chosen ids, in the order the exam shows
#: them: at most `max` of them, all taken from the candidates.
type Select = Callable[[list[str], int | None], Sequence[str]]

def select_random(candidates: list[str], max: int | None) -> list[str]:
    """
    The default `Select`: every candidate when there is no `max`, or a
    random sample of `max` of them otherwise. The result keeps the order
    of `candidates`.
    """
    if max is None or max >= len(candidates):
        return list(candidates)
    chosen = set(random.sample(candidates, max))
    return [candidate for candidate in candidates if candidate in chosen]


class Exam(MdqModel):
    """
    An exam. Its include blocks stay unresolved until `resolve()`.
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
    questions: list[ExamEntry]

    @field_validator("locale")
    @classmethod
    def check_locale_is_well_formed(cls, value: str | None) -> str | None:
        """exam.md's "Additional Rules" imports the base `locale` rule (`malformed-locale`)."""
        return _validate_locale(value)

    @field_validator("uuid")
    @classmethod
    def check_uuid_is_well_formed(cls, value: str | None) -> str | None:
        """exam.md's "Additional Rules" imports the base `uuid` rule (`malformed-uuid`)."""
        return _validate_uuid(value)

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

        Before `resolve()`, an `include` counts with the id it references.
        An `include-all` adds questions that are not known yet, so the
        implicit ids after it are not checked.
        """
        seen: dict[str, int] = {}
        for index, entry in enumerate(self.questions):
            if isinstance(entry, IncludeAll):
                continue
            question_id = entry.include if isinstance(entry, Include) else entry.id
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

        for index, entry in enumerate(self.questions):
            if isinstance(entry, IncludeAll):
                break
            if isinstance(entry, Include) or entry.id is not None:
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

    def resolve(
        self,
        bank: QuestionBank,
        *,
        select: Select | None = None,
        warnings: list[Diagnostic] | None = None,
    ) -> Exam:
        """
        Return a copy of this exam in which every `include` and
        `include-all` block is replaced by the questions it selects from
        `bank` (exam.md, "Include" and "Include all").

        An `include-all` never adds a question that the exam already
        contains: the target of an `include`, a declared inline id, or a
        question an earlier `include-all` added. `select` then chooses
        among the remaining matches; it defaults to `select_random`. A
        query that does not follow the recommended language adds no
        questions. Included questions inherit `locale` and `author` from
        the exam.

        Args:
            bank: Where the included questions come from.
            select: Chooses the questions of each `include-all` block.
            warnings: When given, an `empty-include-all` `Diagnostic` is
                appended for every `include-all` block that adds nothing.

        Raises:
            IncludeNotFound: `bank` cannot load an included question.
            ValueError: `select` returns an id that is not a candidate,
                or more than `max` ids.
            pydantic.ValidationError: an included question is invalid,
                or the resolved exam has duplicate question ids.
        """
        select = select or select_random
        taken = {
            entry.include if isinstance(entry, Include) else entry.id
            for entry in self.questions
            if not isinstance(entry, IncludeAll)
        }
        questions: list[dict[str, Any]] = []
        for index, entry in enumerate(self.questions):
            if isinstance(entry, Include):
                questions.append(self._load_included(bank, entry.include))
            elif isinstance(entry, IncludeAll):
                candidates = sorted(_query_ids(bank, entry.include_all) - taken)
                chosen = list(select(candidates, entry.max))
                _check_selection(chosen, candidates, entry.max)
                taken.update(chosen)
                if not chosen and warnings is not None:
                    warnings.append(
                        Diagnostic(
                            severity="warning",
                            code="empty-include-all",
                            path=("questions", index),
                            message=(
                                f"the query {entry.include_all!r} adds no "
                                "question to the exam"
                            ),
                        )
                    )
                questions.extend(self._load_included(bank, qid) for qid in chosen)
            else:
                questions.append(entry.to_dict())

        data = self.to_dict()
        data["questions"] = questions
        return type(self).model_validate(data)

    def _load_included(self, bank: QuestionBank, question_id: str) -> dict[str, Any]:
        source = bank.load(question_id)
        if isinstance(source, str):
            question: dict[str, Any] = dict(_parser.parse_question(source))
        else:
            question = dict(source)
        # An included question already has an identity, so it keeps its
        # own id -- falling back to the id it was found by.
        question.setdefault("id", question_id)
        for field in _parser.INHERITED_FIELDS:
            value = getattr(self, field)
            if field not in question and value is not None:
                question[field] = value
        return question

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

        Raises:
            UnresolvedInclude: the exam has an `include-all` block, so
                the positions after it are not known. Call `resolve()`
                first.
        """
        if any(isinstance(entry, IncludeAll) for entry in self.questions):
            raise UnresolvedInclude(
                "the positions after an 'include-all' block are only known "
                "after resolve()"
            )
        new_questions: list[Question | Include | IncludeAll] = []
        for index, entry in enumerate(self.questions):
            if isinstance(entry, (Include, IncludeAll)):
                new_questions.append(entry)
            elif entry.id is not None:
                new_questions.append(entry.with_ids())
            else:
                new_questions.append(
                    entry.with_ids().model_copy(update={"id": _implicit_question_id(index)})
                )
        return self.model_copy(update={"questions": new_questions})

    def lint(self) -> list[Diagnostic]:
        """
        Run the exam-level lint rules, then each question's own `lint()`,
        with `("questions", i)` prepended to that question's diagnostics
        (dev/specs/to-do/lint-on-models.md).

        exam.md, "Additional Rules" imports the base rules for `id`,
        `uuid`, `locale` and `title` (base.md, "Additional Rules") into
        the exam frontmatter -- `author`, `tags` and the rest are not
        listed there, so they stay question-only.
        """
        diagnostics = _lint.check_exam_without_questions(self.questions, ("questions",))
        diagnostics.extend(_lint.check_id_is_url_safe(self.id))
        diagnostics.extend(_lint.check_id_and_title_defined(self.id, self.title))
        diagnostics.extend(_lint.check_uuid_version_and_variant(self.uuid))
        diagnostics.extend(_lint.check_locale_language_subtag(self.locale))
        diagnostics.extend(_lint.check_blank_text_field(self.title, "title"))
        after_include_all = False
        for index, entry in enumerate(self.questions):
            path: tuple[str | int, ...] = ("questions", index)
            if isinstance(entry, IncludeAll):
                after_include_all = True
                diagnostics.extend(
                    _lint.check_include_query(entry.include_all, path + ("include-all",))
                )
            elif not isinstance(entry, Include):
                if after_include_all and entry.id is None:
                    diagnostics.extend(_lint.check_undeclared_id_after_include_all(path))
                diagnostics.extend(
                    replace(d, path=path + d.path) for d in entry.lint()
                )
        return diagnostics

    def _render_lines(self) -> Iterable[str]:
        """
        Render the exam as MDQ Markdown (docs/exam.md): frontmatter, H1
        title, instructions, then one block per entry.

        The H1 carries `[id] title` when both fit there exactly. Otherwise
        the frontmatter carries them, because it takes precedence over the
        H1 when the exam is parsed again.
        """
        frontmatter = self.to_dict()
        for key in ("type", "id", "title", "instructions", "questions"):
            frontmatter.pop(key, None)

        heading: list[str] = []
        if self.id is not None and re.fullmatch(_parser.SLUG_BODY_RE, self.id):
            heading.append(f"[{self.id}]")
        elif self.id is not None:
            frontmatter["id"] = self.id

        title = self.title
        title_fits = (
            title is not None
            and title == title.strip()
            and len(title.splitlines()) == 1
            and (heading or not _parser.SLUG_PREFIX_RE.match(title))
        )
        if title_fits:
            heading.append(str(title))
        else:
            # Also written when `title` is None: the H1 below then holds a
            # placeholder, and `title: null` keeps it out of the model.
            frontmatter["title"] = title
            if not heading:
                lines = (title or "").strip().splitlines()
                placeholder = lines[0] if lines else ""
                if not placeholder or _parser.SLUG_PREFIX_RE.match(placeholder):
                    placeholder = "Exam"
                heading.append(placeholder)

        if frontmatter:
            yield from _render.yield_frontmatter(frontmatter)
            yield ""
        yield "# " + " ".join(heading)
        if self.instructions:
            yield ""
            yield self.instructions
        for entry in self.questions:
            yield ""
            yield from self._render_entry(entry)

    def _render_entry(self, entry: Question | Include | IncludeAll) -> Iterable[str]:
        if isinstance(entry, (Include, IncludeAll)):
            yield from _render.yield_frontmatter(entry.to_dict())
            return
        # A question inherits these fields from the exam, so repeating the
        # exam's value in the question's frontmatter is redundant.
        inherited = {
            field: None
            for field in _parser.INHERITED_FIELDS
            if getattr(entry, field) is not None
            and getattr(entry, field) == getattr(self, field)
        }
        yield _parser.SEPARATOR
        yield ""
        yield entry.model_copy(update=inherited).render()

    def model_post_init(self, __ctx):
        questions = [q for q in self.questions if isinstance(q, BaseQuestion)]
        for i, question in enumerate(questions):
            if question.exam is not None:
                raise ValueError(f"Question at index {i} already belongs to an exam")

        for question in questions:
            question._exam = weakref.ref(self)



#
# Utilities
#

def _query_ids(bank: QuestionBank, query: str) -> set[str]:
    """The ids `query` selects from `bank`; none if it cannot be read."""
    try:
        return parse_query(query).select(bank)
    except QuerySyntaxError:
        # Reported by `Exam.lint` as `nonstandard-include-query`.
        return set()


def _check_selection(chosen: list[str], candidates: list[str], max: int | None) -> None:
    unknown = set(chosen) - set(candidates)
    if unknown:
        raise ValueError(f"select() returned ids that are not candidates: {sorted(unknown)}")
    if len(set(chosen)) != len(chosen):
        raise ValueError("select() returned the same id twice")
    if max is not None and len(chosen) > max:
        raise ValueError(f"select() returned {len(chosen)} ids, but max is {max}")


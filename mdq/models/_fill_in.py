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
from typing import (
    Annotated,
    Any,
    ClassVar,
    Final,
    Iterable,
    Iterator,
    Literal,
    Self,
    Sequence,
    assert_never,
)

from pydantic import Field, model_validator

from .. import _markdown
from .._diagnostics import Diagnostic
from ..errors import NotAutoGradable, ResponseError
from ..types import (
    Automation,
    Diacritics,
    GradingStrategy,
    QuestionGrading,
    QuestionShuffle,
    Unmatched,
)
from . import _render
from ._base import (
    SlugId,
    FreeText,
    MdqModel,
    BaseQuestion,
    _check_unique_choices,
    raise_model_error,
)
from ._choice import (
    ScoredChoice,
    check_choice_ids_defined,
    check_choices_visually_identical,
    check_multiple_choice_answers,
    correct_choice_ids,
    public_choices,
    _with_choice_ids,
    strip_choice_texts,
    unspecified_choice_score,
    write_shuffle_and_grading,
)
from ._numeric import NumericAnswer, NumericKey, is_numeric_response, render_numeric_tag
from ._lint_codes import diag
from ._score import QuestionScore
from ._text import (
    PatternKey,
    _pattern_entry,
    default_unmatched,
    prevalidate_response,
    render_short_answer_patterns,
    short_answer_automation,
)

__all__ = ["ChoiceBlank", "ShortAnswerBlank", "NumericBlank", "Blank", "FillInQuestion"]


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
    #: Redeclared by each subclass with its `Literal`; declared here so the
    #: field keeps its place in the serialization order.
    type: str

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

    def normalized(self) -> Self:
        """
        A copy of this blank in the form a render/parse round trip gives
        (see `BaseQuestion.normalize`).
        """
        return self

    @abstractmethod
    def public(self, *, unmatched: Unmatched | None) -> dict[str, Any]:
        """
        The public form of this blank, inside `FillInQuestion.public`.
        `unmatched` is the one of the fill-in question. The values are
        plain JSON values, so `Any`.

        Raises:
            MissingIdError: a choice of a choice blank has no id.
        """

    @abstractmethod
    def correct_responses(self, *, diacritics: Diacritics) -> list[Any]:
        """
        The responses to this blank that score 1, inside
        `FillInQuestion.correct_responses`. `diacritics` is the one of the
        fill-in question. The values are plain JSON values, so `Any`.

        Raises:
            MissingIdError: a correct choice of a choice blank has no id.
        """

    @abstractmethod
    def score(
        self,
        response: object,
        *,
        symmetric: bool,
        diacritics: Diacritics,
        unmatched: Unmatched | None,
    ) -> QuestionScore | Literal["pending"]:
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

    def normalized(self) -> Self:
        return self.model_copy(update={"choices": strip_choice_texts(self.choices)})

    def lint(self, path: ModelPath, *, unmatched: Unmatched | None) -> list[Diagnostic]:
        choices_path = path + ("choices",)
        return [
            *check_multiple_choice_answers(self.choices, choices_path),
            *check_choice_ids_defined(self.choices, choices_path),
            *check_choices_visually_identical(self.choices, choices_path),
        ]

    def render_lines(self) -> Iterable[str]:
        yield f"[^{self.id}]:"
        for choice in self.choices:
            yield from _render.yield_choice(choice, mark=_render.score_mark(choice.score))

    def with_ids(self) -> Self:
        return self.model_copy(update={"choices": _with_choice_ids(self.choices)})

    def public(self, *, unmatched: Unmatched | None) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "choices": public_choices(self.choices)}

    def correct_responses(self, *, diacritics: Diacritics) -> list[str]:
        """
        The ids of the choices whose effective score is 1, as in a
        multiple-choice question. A choice that declares no score gets
        at most 0 under any grading, so the grading does not matter here.
        """
        return correct_choice_ids(self.choices, symmetric=False)

    def score(
        self,
        response: object,
        *,
        symmetric: bool,
        diacritics: Diacritics,
        unmatched: Unmatched | None,
    ) -> QuestionScore:
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
        return QuestionScore(score=score, feedback=[choice.feedback] if choice.feedback else [])


class ShortAnswerBlank(PatternKey, BlankBase):
    type: Literal["short-answer"] = "short-answer"

    def normalized(self) -> Self:
        copy = self.model_copy()
        copy._normalize_key()
        return copy

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
        return self.lint_key(
            path, unmatched=self.effective_unmatched(unmatched), unmatched_path=path
        )

    def public(self, *, unmatched: Unmatched | None) -> dict[str, Any]:
        """
        Also the effective `unmatched` of the blank, always present: its
        default depends on `accept`, which is private.
        """
        return {
            "id": self.id,
            "type": self.type,
            **self.public_key(),
            "unmatched": self.effective_unmatched(unmatched),
        }

    def correct_responses(self, *, diacritics: Diacritics) -> list[str]:
        """The `accept` literals, as in a short answer question."""
        return self.literal_responses(diacritics=diacritics)

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
    ) -> QuestionScore | Literal["pending"]:
        if not isinstance(response, str):
            raise ResponseError(
                f"Response {response!r} to blank {self.id!r} is not text"
            )
        score = self.score_text(
            response,
            unmatched=self.effective_unmatched(unmatched),
            diacritics=diacritics,
            incorrect_feedback=self.incorrect_feedback,
        )
        return PENDING if score is None else score


class NumericBlank(NumericKey, BlankBase):
    type: Literal["numeric"] = "numeric"

    def normalized(self) -> Self:
        copy = self.model_copy()
        copy._normalize_key()
        return copy

    def lint(self, path: ModelPath, *, unmatched: Unmatched | None) -> list[Diagnostic]:
        return self.lint_key(path)

    def public(self, *, unmatched: Unmatched | None) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, **self.public_key()}

    def correct_responses(self, *, diacritics: Diacritics) -> list[NumericAnswer]:
        """The `answer`, as in a numeric question (`NumericKey.correct_answer`)."""
        return [self.correct_answer()]

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
    ) -> QuestionScore:
        if not is_numeric_response(response):
            raise ResponseError(
                f"Response {response!r} to blank {self.id!r} is not numeric"
            )
        return self.score_numeric(response)


Blank = Annotated[
    ChoiceBlank | ShortAnswerBlank | NumericBlank,
    Field(discriminator="type"),
]




class FillInQuestion(BaseQuestion[Mapping[str, object]]):
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

    def _normalize(self) -> None:
        super()._normalize()
        self.blanks = [blank.normalized() for blank in self.blanks]

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
                raise_model_error(
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
                raise_model_error(
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
                raise_model_error(
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
            raise_model_error(
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
                raise_model_error(
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

    _PUBLIC_KEYS: ClassVar[tuple[str, ...]] = (
        *BaseQuestion._PUBLIC_KEYS, "shuffle", "grading", "diacritics",
    )  # fmt: skip

    def _public_body(self) -> dict[str, Any]:
        """
        The public blanks. The question `unmatched` is not copied: each
        short answer blank holds its effective value instead.
        """
        return {"blanks": [blank.public(unmatched=self.unmatched) for blank in self.blanks]}

    def correct_responses(self) -> dict[str, list[Any]]:
        """
        See `BaseQuestion.correct_responses`. The one exception to the
        list: a map from blank id to the responses of that blank that
        score 1, since a list of full responses would hold every
        combination. A full response that scores 1 takes one response per
        blank. The values are plain JSON values, so `Any`.
        """
        return {
            blank.id: blank.correct_responses(diacritics=self.diacritics)
            for blank in self.blanks
        }

    def lint(self) -> list[Diagnostic]:
        """
        See `BaseQuestion.lint`.

        Each blank is graded like the question type it names, so it
        inherits that type's checks, with the path pointing into the
        blank.
        """
        diagnostics = super().lint()
        diagnostics.extend(check_case_variant_blank_ids([b.id for b in self.blanks]))
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

    def _parse_response(self, response: object) -> Mapping[str, object]:
        """
        Raises:
            ResponseError: `response` is not a mapping, or a key of it
                names no blank.
        """
        not_a_mapping = ResponseError(
            f"A fill-in response must be a mapping of blank ids, found "
            f"{type(response).__name__}"
        )
        if not isinstance(response, Iterable):
            raise not_a_mapping
        known = {blank.id for blank in self.blanks}
        unknown = sorted(key for key in response if key not in known)
        if unknown:
            raise ResponseError(f"Blank ids {unknown!r} not found in the question")
        if not isinstance(response, Mapping):
            raise not_a_mapping
        return response

    def score_blanks(self, response: object) -> dict[str, QuestionScore | None]:
        """
        Return the score of each blank, keyed by blank id, in the order of
        the blank definitions (fill-in.md, "Blank scores").

        Each blank is scored as the question's strategy scores it, before
        the strategy combines the blanks. An empty blank (no key, or a
        `None` value) scores 0 with no feedback. A pending blank maps to
        `None`. Unlike `score_response()`, a pending blank does not raise:
        a review screen can show the settled blanks of a pending question.

        Raises:
            ResponseError: `response` is not a valid response to this
                question (responses.md, "Fill in the blanks").
        """
        return self._score_blanks(self._parse_response(response))

    def _score_blanks(
        self, response: Mapping[str, object]
    ) -> dict[str, QuestionScore | None]:
        symmetric = self.effective_grading() == "symmetric"
        scores: dict[str, QuestionScore | None] = {}
        for blank in self.blanks:
            sub_response = response.get(blank.id)
            if sub_response is None:
                scores[blank.id] = QuestionScore(score=0.0)
                continue
            result = blank.score(
                sub_response,
                symmetric=symmetric,
                diacritics=self.diacritics,
                unmatched=self.unmatched,
            )
            # The instructor scores a pending blank; the other blanks are
            # still checked, so a malformed one raises.
            scores[blank.id] = result if isinstance(result, QuestionScore) else None
        return scores

    def _score(self, response: Mapping[str, object]) -> QuestionScore:
        """
        Score each blank independently and combine by `grading`.

        A blank with no key, or a `None` value, is empty and scores 0
        (fill-in.md, "Grading"); `{}` is a response with every blank empty.

        Raises:
            ResponseError: a blank's response doesn't match its type.
            NotAutoGradable: a short answer blank response is pending.
        """
        return self._combine(response, self._score_blanks(response), {})

    def combine(self, response: object, manual: Mapping[str, float]) -> QuestionScore:
        """
        Score `response` with the instructor's score of each pending blank
        (fill-in.md, "Blank scores"; responses.md, "Pending").

        `manual` maps the id of each pending blank to the score the
        instructor gives it, in [0, 1]. The question's strategy combines
        those scores with the other blank scores as `score_response()`
        does. A pending blank is filled, so under `no-mistakes` an
        instructor score below 1 is a mistake. In the result, a pending
        blank has the instructor's score and no feedback; the feedback of
        the settled blanks is shown, since the response is now settled.

        Raises:
            ResponseError: `response` is not a valid response to this
                question (responses.md, "Fill in the blanks").
            ValueError: a key of `manual` is not the id of a pending blank,
                or a value is outside [0, 1]. This is an error of the host,
                so it is not a `GradingError`.
            NotAutoGradable: a pending blank has no entry in `manual`.
        """
        parsed = self._parse_response(response)
        return self._combine(parsed, self._score_blanks(parsed), manual)

    def _combine(
        self,
        response: Mapping[str, object],
        blanks: dict[str, QuestionScore | None],
        manual: Mapping[str, float],
    ) -> QuestionScore:
        """
        Combine the blank scores by `grading`, with the score of each
        pending blank taken from `manual`.

        Raises:
            ValueError: `manual` has a key that is not a pending blank, or
                a value outside [0, 1].
            NotAutoGradable: a pending blank has no entry in `manual`.
        """
        for blank_id, value in manual.items():
            if blank_id not in blanks:
                raise ValueError(f"manual score for {blank_id!r}, which is not a blank")
            if blanks[blank_id] is not None:
                raise ValueError(
                    f"manual score for blank {blank_id!r}, which is not pending"
                )
            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"manual score {value!r} for blank {blank_id!r} is outside [0, 1]"
                )
        pending = [
            blank_id
            for blank_id, result in blanks.items()
            if result is None and blank_id not in manual
        ]
        if pending:
            raise NotAutoGradable(
                f"the response to blank {pending[0]!r} is pending: it matches "
                "no pattern and 'unmatched' is 'manual'"
            )
        settled = {
            blank_id: QuestionScore(score=manual[blank_id]) if result is None else result
            for blank_id, result in blanks.items()
        }
        scores = [result.score for result in settled.values()]
        feedback = [text for result in settled.values() for text in result.feedback]
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

        return QuestionScore(score=score, feedback=feedback, blanks=dict(settled))


def check_case_variant_blank_ids(blank_ids: Sequence[str]) -> Iterator[Diagnostic]:
    """
    fill-in.md, "Blank definitions": blank ids are compared exactly, so two
    ids that differ only in ASCII case are two blanks. CommonMark would
    merge them, so warn (`case-variant-blank-id`).
    """
    first_by_folded: dict[str, str] = {}
    for index, blank_id in enumerate(blank_ids):
        folded = blank_id.lower()
        first = first_by_folded.setdefault(folded, blank_id)
        if first != blank_id:
            yield diag(
                code="case-variant-blank-id",
                path=("blanks", index, "id"),
                message=(
                    f"blank id {blank_id!r} differs from {first!r} only in "
                    f"case; blank ids are case-sensitive, but CommonMark "
                    f"labels are not"
                ),
            )

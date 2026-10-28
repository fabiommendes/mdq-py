"""
Text-answer questions: `AnswerPattern` (the `accept`/`reject` entry
shape), `ShortAnswerQuestion` and `EssayQuestion`.

The pattern-matching helpers (`normalize_text`,
`render_short_answer_patterns`, `first_feedback`) are reused verbatim by a
short-answer fill-in blank in `mdq.models._fill_in`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import cached_property
from importlib import resources
from typing import Annotated, Any, Iterable, Iterator, Literal, Self

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_core import PydanticCustomError

from .. import _parser
from .. import types as t
from .._exact import exact_literal
from .._markdown import UNICODE_SPACE, has_visible_character, starts_block
from .._diagnostics import Diagnostic
from ..errors import NotAutoGradable, ResponseError
from ..types import Automation, Diacritics, EssayContent, Unmatched
from . import _lint
from ._base import (
    _ASCII_WS,
    BaseQuestion,
    FreeText,
    MdqModel,
    raise_model_error,
    strip_optional_text,
)
from ._lint_codes import diag
from ._regex import (
    IGNORED_FLAGS,
    InvalidRegexError,
    RegexPattern,
    escaped_code_points,
    parse_regex,
)
from ._regex import normalize_text as _strip_marks
from ._score import QuestionScore

__all__ = ["AnswerPattern", "ShortAnswerQuestion", "EssayQuestion"]


class AnswerPattern(MdqModel):
    """
    One entry of an `accept`/`reject`/`preAccept`/`preReject` list.

    A bare string in the document is shorthand for a pattern with no
    feedback and no comment, so both spellings load into this model.
    """

    #: A regex when delimited by `/`, an exact literal when enclosed in
    #: backticks, and an inexact plain literal otherwise. The pattern
    #: mirrors `patternString` in schema/short-answer.yaml: a pattern that
    #: opens with a backtick is a complete code span (`exact_literal`,
    #: short-answer.md, "Content"). A pattern with no visible character is
    #: `blank-text` (`check_pattern_has_visible_character`).
    pattern: Annotated[str, Field(min_length=1)]
    feedback: FreeText | None = None
    comment: FreeText | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_string(cls, value: Any) -> Any:
        """Expand the bare-string shorthand into the object form."""
        return {"pattern": value} if isinstance(value, str) else value

    @field_validator("pattern")
    @classmethod
    def check_pattern_string(cls, value: str) -> str:
        """
        patterns.md, "Pattern string": a pattern string has no line ending,
        and one that opens with a backtick is a complete exact literal.
        The schema checks the shape only: it cannot match the N of the
        opening and of the closing run.
        """
        if "\r" in value or "\n" in value:
            if value.strip(" \t\r\n").startswith("`"):
                raise PydanticCustomError(
                    "schema-error",
                    "an exact literal cannot open at the end of a line, and "
                    "its closing run cannot start a line",
                )
            raise PydanticCustomError(
                "schema-error", "a pattern string cannot contain a line ending"
            )
        if value.strip(" \t").startswith("`") and exact_literal(value) is None:
            raise PydanticCustomError(
                "schema-error",
                "a pattern that opens with a backtick must be a complete exact "
                "literal: a run of the same number of backticks closes it, "
                "and nothing follows the closing run",
            )
        if starts_block(value):
            text = value.strip(" \t")
            raise_model_error(
                "AnswerPattern",
                "block-start-pattern",
                "an inexact pattern cannot start a markdown block (a block "
                "quote, heading, list, fence, HTML block or thematic break): "
                f"write an exact literal, `` `{text}` ``, or a regex",
                (),
                value,
            )
        return value

    @cached_property
    def kind(self) -> Literal["regex", "exact", "inexact"]:
        """
        How `pattern` is read: a regex when it starts with `/` after
        stripping spaces and tabs (short-answer.md, "Pattern lines"), an
        exact literal when it is a complete code span, inexact otherwise.
        """
        text = self.pattern.strip(" \t")
        if text.startswith("/"):
            return "regex"
        return "exact" if exact_literal(text) is not None else "inexact"

    @cached_property
    def exact_content(self) -> str | None:
        """The text between the backticks of an exact literal, else None."""
        return exact_literal(self.pattern.strip(" \t"))

    @cached_property
    def regex(self) -> RegexPattern:
        """
        The compiled regex of a `regex` pattern.

        Raises:
            InvalidRegexError: the regex does not compile.
        """
        return RegexPattern(self.pattern)

    @model_validator(mode="after")
    def check_pattern_has_visible_character(self) -> Self:
        """
        patterns.md, "Pattern string": a pattern string must have a
        visible character (`blank-text`). For an exact literal, the text
        between the backticks is checked, so `` ` ` `` is blank.

        Like `check_pattern_compiles`, the diagnostic points at the list
        entry, not at `pattern`.
        """
        text = self.pattern.strip(" \t")
        if self.exact_content is not None:
            text = self.exact_content
        if not has_visible_character(text):
            raise_model_error(
                type(self).__name__,
                "blank-text",
                "pattern has no visible character",
                (),
                self.pattern,
            )
        return self

    @model_validator(mode="after")
    def check_pattern_compiles(self) -> Self:
        """
        short-answer.md, "Additional Rules": a `/`-delimited pattern
        must compile as an MDQ regex (`invalid-regex`).

        Only the pattern itself is checked here, not the field: `loc`
        stays at this model's own root, so the diagnostic points at the
        list entry (`accept[0]`), not `accept[0].pattern`.
        """
        if self.kind == "regex":
            try:
                self.regex
            except InvalidRegexError as exc:
                raise_model_error(
                    type(self).__name__,
                    "invalid-regex",
                    f"regex does not compile: {exc}",
                    (),
                    self.pattern,
                )
        return self

    def matches(self, response: str, *, diacritics: Diacritics = "fold") -> bool:
        """
        Report whether `response` satisfies this pattern.

        A backtick-enclosed literal is compared code point for code point
        after two steps, in order, on the response and on the pattern
        content: NFC (not NFKC), then removal of `UNICODE_SPACE` code
        points from both ends (patterns.md, "Exact literals"). `diacritics`
        does not affect it; a bare literal is compared after normalization, which
        `diacritics` tunes: `"fold"` strips diacritics as it always did,
        `"keep"` leaves them so `Maceió` rejects `Maceio`; a regex sees
        the response in NFC with the `UNICODE_SPACE` ends removed, and
        lets its own flags decide the rest (patterns.md, "Regex"). Neither
        the regex nor the backtick form consults `diacritics`.
        """
        if self.kind == "regex":
            return self.regex.match(response)
        if self.exact_content is not None:
            return _exact_form(response) == _exact_form(self.exact_content)
        return normalize_text(response, diacritics=diacritics) == normalize_text(
            self.pattern.strip(" \t"), diacritics=diacritics
        )




def parse_text_response(response: object) -> str:
    """
    Return `response` if it is a string (responses.md, "Short answer and
    essay"). A number is not converted: `1.0` and `1` would become
    different texts.

    Raises:
        ResponseError: `response` is not a string.
    """
    if not isinstance(response, str):
        raise ResponseError(
            f"A text response must be a string, found {type(response).__name__}"
        )
    return response


#: A pattern list holds at least one entry (schema `patternList`, `minItems: 1`).
PatternList = Annotated[list[AnswerPattern], Field(min_length=1)]


class PatternKey(MdqModel):
    """
    The answer key of a short answer question or of a short answer fill-in
    blank: the pattern lists that decide a response.
    """

    #: Redeclared by each subclass with its `Literal`; declared here so the
    #: field keeps its place in the serialization order.
    type: str
    #: Grading rules. `accept` decides the score and wins over `reject`
    #: when both match; `reject` only attaches feedback to answers known
    #: to be wrong.
    accept: PatternList | None = None
    reject: PatternList | None = None

    #: Pre-submission validators. A system warns the student before
    #: accepting the answer; grading ignores them entirely.
    pre_accept: PatternList | None = None
    pre_reject: PatternList | None = None

    def _normalize_key(self) -> None:
        """
        Trim the `accept` and `reject` entries the way the parser does,
        *inplace*. The `preAccept` and `preReject` entries stay as written.
        """
        if self.accept is not None:
            self.accept = [_trimmed_pattern(rule) for rule in self.accept]
        if self.reject is not None:
            self.reject = [_trimmed_pattern(rule) for rule in self.reject]

    def lint_key(
        self,
        path: tuple[str | int, ...],
        *,
        unmatched: Unmatched,
        unmatched_path: tuple[str | int, ...],
    ) -> list[Diagnostic]:
        """
        Lint the key, which sits at `path` of the document. `unmatched` is
        the effective one, declared at `unmatched_path`.
        """
        return [
            *check_short_answer(
                accept=self.accept,
                reject=self.reject,
                pre_accept=self.pre_accept,
                pre_reject=self.pre_reject,
                path=path,
            ),
            *check_no_correct_answer(
                accept=self.accept,
                unmatched=unmatched,
                path=unmatched_path,
            ),
        ]

    def score_text(
        self,
        response: str,
        *,
        unmatched: Unmatched,
        diacritics: Diacritics,
        incorrect_feedback: str | None,
    ) -> QuestionScore | None:
        """
        Score the response by the three rules of short-answer.md,
        "Grading": an `accept` match scores 1, a `reject` match scores 0,
        and otherwise `unmatched` decides. `None` means pending: the
        response matches no pattern and `unmatched` is `"manual"`.

        An incorrect response with no pattern feedback gets
        `incorrect_feedback`, if set.
        """
        outcome = settle_response(
            self.accept,
            self.reject,
            response,
            unmatched=unmatched,
            diacritics=diacritics,
        )
        if outcome == "pending":
            return None
        feedback = first_feedback(
            (self.accept if outcome == "correct" else self.reject) or [],
            response,
            diacritics=diacritics,
        )
        if outcome == "incorrect" and not feedback and incorrect_feedback:
            feedback = [incorrect_feedback]
        return QuestionScore(
            score=1.0 if outcome == "correct" else 0.0, feedback=feedback
        )


class ShortAnswerQuestion(PatternKey, BaseQuestion[t.TextResponse]):
    type: Literal["short-answer"] = "short-answer"

    #: How inexact literals treat diacritics, in every pattern list.
    diacritics: Diacritics = "fold"

    #: What becomes of a response that matches no pattern (short-answer.md,
    #: "Grading"). `None` means the default, see `effective_unmatched`.
    unmatched: Unmatched | None = None

    #: Feedback for an incorrect response that no pattern gave feedback to
    #: (short-answer.md, "Feedback").
    incorrect_feedback: FreeText | None = None

    def _normalize(self) -> None:
        super()._normalize()
        self._normalize_key()

    @property
    def effective_unmatched(self) -> Unmatched:
        """
        `unmatched` as declared, or its default: `"incorrect"` when the
        question has at least one `accept` pattern, `"manual"` otherwise.
        """
        return default_unmatched(self.unmatched, self.accept)

    @property
    def automation(self) -> Automation:
        """See `BaseQuestion.automation` (short-answer.md, "Automation")."""
        return short_answer_automation(
            self.effective_unmatched, self.accept, self.reject
        )

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(
            self.lint_key(
                (), unmatched=self.effective_unmatched, unmatched_path=("unmatched",)
            )
        )
        return diagnostics

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.unmatched is not None:
            data["unmatched"] = self.unmatched
        if self.incorrect_feedback is not None:
            data["incorrectFeedback"] = self.incorrect_feedback
        if self.diacritics != "fold":
            data["diacritics"] = self.diacritics
        # short-answer.md, frontmatter table: `preAccept`/`preReject` are
        # frontmatter-only, so they have no body block.
        if self.pre_accept is not None:
            data["preAccept"] = [_pattern_entry(p) for p in self.pre_accept]
        if self.pre_reject is not None:
            data["preReject"] = [_pattern_entry(p) for p in self.pre_reject]
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        yield from render_short_answer_patterns(self.accept, self.reject)

    def prevalidate(self, response: str) -> tuple[bool, str | None]:
        """
        Pre-validate a submission (short-answer.md, "Pre-validation").

        Returns:
            `(valid, feedback)`: `feedback` is the pattern feedback shown for
            an invalid submission, `None` when the submission is valid or no
            pattern has feedback. Grading never calls this.
        """
        return prevalidate_response(
            self.pre_accept, self.pre_reject, response, diacritics=self.diacritics
        )

    def effective_accept(self) -> list[AnswerPattern]:
        """Return the accept list grading uses: `accept`, or empty when unset."""
        return self.accept or []

    def _parse_response(self, response: object) -> t.TextResponse:
        """
        Raises:
            ResponseError: `response` is not a string (responses.md, "Short
                answer and essay"). An empty string is graded like any other.
        """
        return parse_text_response(response)

    def _score(self, response: t.TextResponse) -> QuestionScore:
        """
        Score the response by the three rules of short-answer.md,
        "Grading": an `accept` match scores 1, a `reject` match scores 0,
        and otherwise `effective_unmatched` decides.

        An incorrect response with no pattern feedback gets
        `incorrect_feedback`, if set.

        Raises:
            NotAutoGradable: the response matches no pattern and
                `effective_unmatched` is `"manual"`: it is pending.
        """
        score = self.score_text(
            response,
            unmatched=self.effective_unmatched,
            diacritics=self.diacritics,
            incorrect_feedback=self.incorrect_feedback,
        )
        if score is None:
            raise NotAutoGradable(
                "the response matches no pattern and 'unmatched' is 'manual'"
            )
        return score


class EssayQuestion(BaseQuestion[t.TextResponse]):
    type: Literal["essay"] = "essay"
    content: EssayContent = "text"
    highlight: Annotated[str | None, Field(default=None, min_length=1)] = None

    #: A model answer for the human grading this. Carrying one does not
    #: make the question auto-gradable.
    answer_key: FreeText | None = None

    @field_validator("highlight")
    @classmethod
    def check_highlight_needs_code(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        """
        Raises:
            ValueError: `highlight` is set but `content` is not "code"
                (the `if`/`then` of the schema), which `load` reports as
                `schema-error`.
        """
        if value is not None and info.data.get("content", "text") != "code":
            raise ValueError("highlight is only allowed when content is 'code'")
        return value

    @model_validator(mode="after")
    def check_answer_key_has_no_h1(self) -> Self:
        """essay.md, "Answer key": the section holds any block except an H1."""
        if self.answer_key:
            for description in _parser.find_answer_key_forbidden_elements(
                self.answer_key
            ):
                raise_model_error(
                    type(self).__name__,
                    "forbidden-block-element",
                    f"'answerKey' holds {description}, which essay.md's "
                    f"\"Answer key\" does not allow",
                    ("answerKey",),
                    self.answer_key,
                )
        return self

    @property
    def automation(self) -> Automation:
        """Always `manual` (essay.md)."""
        return "manual"

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(_lint.check_code_highlight(self.content, self.highlight))
        diagnostics.extend(check_missing_answer_key(self.answer_key))
        diagnostics.extend(
            _lint.check_unsafe_thematic_break(self.answer_key, ("answerKey",))
        )
        return diagnostics

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.content != "text":
            data["content"] = self.content
        if self.highlight is not None:
            data["highlight"] = self.highlight
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        yield "[essay]"

    def _parse_response(self, response: object) -> t.TextResponse:
        """
        Raises:
            ResponseError: `response` is not a string.
        """
        return parse_text_response(response)

    def _score(self, response: t.TextResponse) -> QuestionScore:
        """
        Never gradable automatically.

        Raises:
            NotAutoGradable: always.
        """
        raise NotAutoGradable("essay questions require manual grading")

    def _render_lines(self) -> Iterable[str]:
        yield from super()._render_lines()
        if self.answer_key is not None:
            yield ""
            yield "## [answer-key]"
            yield ""
            yield self.answer_key



#
# Utilities
#

def _load_inexact_tables() -> tuple[
    list[tuple[int, int]], dict[int, str], dict[int, str], dict[int, str]
]:
    """Load `inexact-tables.json` and build the translate tables once."""
    raw = json.loads(
        resources.files("mdq").joinpath("inexact-tables.json").read_text("utf-8")
    )

    def table(name: str) -> dict[int, str]:
        return {ord(key): value for key, value in raw[name].items()}

    ranges = [(first, last) for first, last in raw["ignorable"]]
    return ranges, table("letters"), table("punctuation"), table("caseFolding")


_IGNORABLE, _LETTERS, _PUNCTUATION, _CASE_FOLDING = _load_inexact_tables()
_IGNORABLE_TABLE = {
    cp: None for first, last in _IGNORABLE for cp in range(first, last + 1)
}
_SPACE_RUN = re.compile(f"[{UNICODE_SPACE}]+")
_SPACE_ENDS = re.compile(f"^[{UNICODE_SPACE}]+|[{UNICODE_SPACE}]+$")


def _trim_space(value: str) -> str:
    """Remove `UNICODE_SPACE` code points from both ends of `value`."""
    return _SPACE_ENDS.sub("", value)


def default_unmatched(
    unmatched: Unmatched | None, accept: list[AnswerPattern] | None
) -> Unmatched:
    """
    The declared `unmatched`, or its default (short-answer.md, "Grading"):
    `"incorrect"` with at least one `accept` pattern, `"manual"` without.
    """
    if unmatched is not None:
        return unmatched
    return "incorrect" if accept else "manual"


def short_answer_automation(
    unmatched: Unmatched,
    accept: list[AnswerPattern] | None,
    reject: list[AnswerPattern] | None,
) -> Automation:
    """
    The automation of a short answer (short-answer.md, "Automation").
    `unmatched` is the effective value; `preAccept` and `preReject` do
    not count.
    """
    if unmatched == "incorrect":
        return "automatic"
    return "semi-automatic" if accept or reject else "manual"


def settle_response(
    accept: list[AnswerPattern] | None,
    reject: list[AnswerPattern] | None,
    response: str,
    *,
    unmatched: Unmatched,
    diacritics: Diacritics = "fold",
) -> Literal["correct", "incorrect", "pending"]:
    """
    Apply the three grading rules of short-answer.md in order: an `accept`
    match is correct, a `reject` match is incorrect, and otherwise
    `unmatched` decides (`"manual"` leaves the response pending).
    """
    if any(rule.matches(response, diacritics=diacritics) for rule in accept or []):
        return "correct"
    if any(rule.matches(response, diacritics=diacritics) for rule in reject or []):
        return "incorrect"
    return "incorrect" if unmatched == "incorrect" else "pending"


def prevalidate_response(
    pre_accept: list[AnswerPattern] | None,
    pre_reject: list[AnswerPattern] | None,
    response: str,
    *,
    diacritics: Diacritics = "fold",
) -> tuple[bool, str | None]:
    """
    Apply the pre-validation rules of short-answer.md. A response is invalid
    when it matches a `preReject` pattern, or when `preAccept` is declared and
    it matches none of its patterns. The feedback of an invalid response is,
    in order: the first matching `preReject` pattern with feedback; else, if
    no `preAccept` pattern matches, the first `preAccept` pattern with
    feedback. Otherwise `None`.
    """
    if any(r.matches(response, diacritics=diacritics) for r in pre_reject or []):
        feedback = first_feedback(pre_reject or [], response, diacritics=diacritics)
        return False, feedback[0] if feedback else None
    if pre_accept and not any(
        r.matches(response, diacritics=diacritics) for r in pre_accept
    ):
        hints = [r.feedback for r in pre_accept if r.feedback is not None]
        return False, hints[0] if hints else None
    return True, None


def _trimmed_pattern(rule: AnswerPattern) -> AnswerPattern:
    """`rule` without the ASCII whitespace the parser trims around its texts."""
    return rule.model_copy(
        update={
            "pattern": rule.pattern.strip(_ASCII_WS),
            "feedback": strip_optional_text(rule.feedback),
            "comment": strip_optional_text(rule.comment),
        }
    )


def _pattern_entry(rule: AnswerPattern) -> str | dict[str, str]:
    """
    Return the document form of a pattern list entry: a plain string when
    only the pattern is set, else a mapping with the keys that are set.
    """
    if rule.feedback is None and rule.comment is None:
        return rule.pattern
    entry = {"pattern": rule.pattern}
    if rule.feedback is not None:
        entry["feedback"] = rule.feedback
    if rule.comment is not None:
        entry["comment"] = rule.comment
    return entry


def _exact_form(value: str) -> str:
    """NFC, then trim `UNICODE_SPACE` from both ends (patterns.md, "Exact literals")."""
    return _trim_space(unicodedata.normalize("NFC", value))


def normalize_text(value: str, *, diacritics: Diacritics = "fold") -> str:
    """
    Normalize `value` for the inexact literal comparison of
    `AnswerPattern.matches` (patterns.md, "Inexact literals").

    Steps, in order: NFKC; remove the ignorable code points; if
    `diacritics == "fold"`, NFD, remove the `nonspacing` table, NFC and replace the
    `letters` table; replace the `punctuation` table; replace the
    `caseFolding` table and NFC; collapse each run of `UNICODE_SPACE`
    to one U+0020 and trim U+0020 from the ends. The tables come from
    `inexact-tables.json`, not from `str.casefold()`.
    """
    value = unicodedata.normalize("NFKC", value).translate(_IGNORABLE_TABLE)
    if diacritics == "fold":
        value = _strip_marks(value).translate(_LETTERS)
    value = value.translate(_PUNCTUATION)
    value = unicodedata.normalize("NFC", value.translate(_CASE_FOLDING))
    return _SPACE_RUN.sub(" ", value).strip(" ")


def render_short_answer_patterns(
    accept: list[AnswerPattern] | None,
    reject: list[AnswerPattern] | None,
    tag: str = "short-answer",
) -> Iterable[str]:
    """
    Render the answer key of a short answer.

    `accept` is the `[<tag>]` block: a lone pattern with no feedback and
    no comment, and no `reject`, goes on the tag line, anything else is a list below it.
    `reject` is always a `[<tag>/reject]` list. `[<tag>/accept]` is never
    written. A question with no `accept` renders `[<tag>]` without a colon,
    followed by the reject block if any. `tag`
    names the owning construct: a fill-in blank passes `^<id>/short-answer`.
    """
    if accept is None:
        # The grammar requires the accept block, even with no pattern.
        yield f"[{tag}]"
        if reject is not None:
            yield ""
            yield from render_pattern_list(f"[{tag}/reject]:", reject)
        return
    if accept is not None:
        lone = (
            len(accept) == 1
            and accept[0].feedback is None
            and accept[0].comment is None
            and reject is None
        )
        if lone:
            yield f"[{tag}]: {accept[0].pattern}"
        else:
            yield from render_pattern_list(f"[{tag}]:", accept)
        if reject is not None:
            yield ""
    if reject is not None:
        yield from render_pattern_list(f"[{tag}/reject]:", reject)


def render_pattern_list(tag_line: str, patterns: list[AnswerPattern]) -> Iterable[str]:
    """Render a tag line followed by its pattern list, with feedback and comments."""
    yield tag_line
    for rule in patterns:
        yield f"* {rule.pattern}"
        if rule.feedback is not None:
            yield f"  > {rule.feedback}"
        if rule.comment is not None:
            yield f"  ! {rule.comment}"


def first_feedback(
    patterns: list[AnswerPattern], response: str, *, diacritics: Diacritics = "fold"
) -> list[str]:
    """
    Return the feedback of the first matching pattern that defines one.

    "First that matches AND carries feedback" is not the same as "first
    that matches": an earlier match with no message is passed over.
    `diacritics` is forwarded to each pattern's `matches`.
    """
    for rule in patterns:
        if rule.feedback is not None and rule.matches(response, diacritics=diacritics):
            return [rule.feedback]
    return []


def check_missing_answer_key(answer_key: str | None) -> Iterator[Diagnostic]:
    """essay.md:91: `answerKey` SHOULD be defined, for a human grader's benefit."""
    if answer_key is not None:
        return
    yield diag(
        code="missing-answer-key",
        path=("answerKey",),
        message="'answerKey' is not defined",
    )


def check_short_answer(
    *,
    accept: list[AnswerPattern] | None,
    reject: list[AnswerPattern] | None = None,
    pre_accept: list[AnswerPattern] | None = None,
    pre_reject: list[AnswerPattern] | None = None,
    path: tuple[str | int, ...],
) -> Iterator[Diagnostic]:
    """
    short-answer.md, "Additional Rules": the regex lints
    (`redundant-regex-anchor`, `ignored-regex-flag`,
    `unmatchable-regex-escape`) over the four
    pattern lists.

    Diagnostics use the frontmatter key: `path + ("preAccept", index)`.

    Whether every `/`-delimited pattern in `accept`/`reject`/
    `preAccept`/`preReject` compiles is a model error
    (`invalid-regex` -- dev/specs/to-do/lint-on-models.md), not checked
    here.
    """
    yield from _check_pattern_list(accept, "accept", path=path)
    yield from _check_pattern_list(pre_accept, "preAccept", path=path)
    yield from _check_pattern_list(reject, "reject", path=path)
    yield from _check_pattern_list(pre_reject, "preReject", path=path)


def check_no_correct_answer(
    *,
    accept: list[AnswerPattern] | None,
    unmatched: str,
    path: tuple[str | int, ...],
) -> Iterator[Diagnostic]:
    """
    short-answer.md, "Additional Rules": `unmatched` is `"incorrect"`
    but there is no `accept` pattern, so no response can be correct
    (`no-correct-answer`). `unmatched` is the effective value.
    """
    if unmatched != "incorrect" or accept:
        return
    yield diag(
        code="no-correct-answer",
        path=path,
        message=(
            "'unmatched' is 'incorrect' but no 'accept' pattern is given: "
            "no response can be correct"
        ),
    )


def _check_pattern_list(
    patterns: list[AnswerPattern] | None,
    key: str,
    *,
    path: tuple[str | int, ...],
) -> Iterator[Diagnostic]:
    """Lints one pattern list, named by its frontmatter `key`: the regex lints of every entry."""
    for index, pattern in enumerate(patterns or []):
        if pattern.kind != "regex":
            continue
        try:
            body, raw_flags = parse_regex(pattern.pattern)
        except InvalidRegexError:
            continue
        item_path = path + (key, index)
        yield from _check_redundant_regex_anchor(body, raw_flags, item_path)
        yield from _check_ignored_regex_flags(raw_flags, item_path)
        yield from _check_unmatchable_regex_escape(body, raw_flags, item_path)


def _check_redundant_regex_anchor(
    body: str, raw_flags: str, path: tuple[str | int, ...]
) -> Iterator[Diagnostic]:
    """
    short-answer.md, "Regex flags": a leading `^` is implicit unless the
    `f` flag is set, and a trailing `$` is implicit unless `f` or `b` is
    set. A `$` preceded by an odd number of backslashes is a literal.
    """
    leading = body.startswith("^") and "f" not in raw_flags
    trailing = False
    if body.endswith("$") and not {"f", "b"} & set(raw_flags):
        backslashes = len(body) - 1 - len(body[:-1].rstrip("\\"))
        trailing = backslashes % 2 == 0
    if not (leading or trailing):
        return
    yield diag(
        code="redundant-regex-anchor",
        path=path,
        message=(
            "matching is already anchored here, so a leading '^' or "
            "trailing '$' is redundant"
        ),
    )


def _check_ignored_regex_flags(
    raw_flags: str, path: tuple[str | int, ...]
) -> Iterator[Diagnostic]:
    """
    short-answer.md:385: `m`, `g`, `s`, `u`, `v`, `y` and `d` are accepted
    for compatibility but have no effect (see [regex flags](regex-flags)).
    """
    ignored = sorted(set(raw_flags) & IGNORED_FLAGS)
    if not ignored:
        return
    flags_text = ", ".join(repr(flag) for flag in ignored)
    yield diag(
        code="ignored-regex-flag",
        path=path,
        message=f"flag(s) {flags_text} are accepted but have no effect on matching",
    )


def _check_unmatchable_regex_escape(
    body: str, raw_flags: str, path: tuple[str | int, ...]
) -> Iterator[Diagnostic]:
    """
    patterns.md, "Regex flags": under `n`, an escape that denotes a code
    point is never stripped. If the strip changes that code point, the
    stripped response cannot contain it. One diagnostic per pattern.
    """
    if "n" not in raw_flags:
        return
    if not any(_stripped_by_n(code_point) for code_point in escaped_code_points(body)):
        return
    yield diag(
        code="unmatchable-regex-escape",
        path=path,
        message=(
            "the 'n' flag strips diacritics from the response, so an escape "
            "for a code point that the strip changes cannot match"
        ),
    )


def _stripped_by_n(code_point: int) -> bool:
    """True if the `n` strip changes the code point."""
    char = chr(code_point)
    return _strip_marks(char) != char

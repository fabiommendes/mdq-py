"""
Text-answer questions: `AnswerPattern` (the `accept`/`reject` entry
shape), `ShortAnswerQuestion` and `EssayQuestion`.

The pattern-matching helpers (`normalize_text`, `short_answer_matches`,
`render_pattern_block`, `first_feedback`) are reused verbatim by a
short-answer fill-in blank in `mdq.models._fill_in`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Any, Iterable, Literal, Self

from pydantic import Field, field_validator, model_validator

from .. import types as t
from .._diagnostics import Diagnostic
from ..errors import NotAutoGradable
from ..types import Diacritics, EssayInput
from . import _lint
from ._base import BaseQuestion, MdqModel, _raise_unique_id_error, _validate_mdq_regex
from ._regex import InvalidRegexError, RegexPattern
from ._regex import normalize_text as strip_accents
from ._score import QuestionScore

__all__ = ["AnswerPattern", "ShortAnswerQuestion", "EssayQuestion"]


class AnswerPattern(MdqModel):
    """
    One entry of an `accept`/`reject`/`preAccept`/`preReject` list.

    A bare string in the document is shorthand for a pattern with no
    feedback and no comment, so both spellings load into this model.
    """

    #: A regex when delimited by `/`, a lone `*` for the wildcard, and a
    #: plain literal otherwise.
    pattern: Annotated[str, Field(min_length=1, pattern=r"\S")]
    feedback: str | None = None
    comment: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_string(cls, value: Any) -> Any:
        """Expand the bare-string shorthand into the object form."""
        return {"pattern": value} if isinstance(value, str) else value

    @model_validator(mode="after")
    def check_pattern_compiles(self) -> Self:
        """
        short-answer.md, "Additional Rules": a `/`-delimited pattern
        must compile as an MDQ regex (`invalid-regex`).

        Only the pattern itself is checked here, not the field: `loc`
        stays at this model's own root, so the diagnostic points at the
        list entry (`accept[0]`), not `accept[0].pattern`.
        """
        if self.pattern.strip().startswith("/"):
            try:
                RegexPattern(self.pattern)
            except InvalidRegexError as exc:
                _raise_unique_id_error(
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

        A backtick-enclosed literal is compared verbatim (only its ends
        trimmed); a bare literal is compared after normalization, which
        `diacritics` tunes: `"fold"` strips diacritics as it always did,
        `"keep"` leaves them so `Maceió` rejects `Maceio`; a regex sees
        the raw response and lets its own flags decide -- normalizing
        first would make a case-sensitive regex impossible, and neither
        it nor the backtick/`*` forms consult `diacritics` at all.
        """
        pattern = self.pattern.strip()
        if pattern == "*":
            return True
        if pattern.startswith("/"):
            return RegexPattern(pattern).match(response)
        if pattern.startswith("`") and pattern.endswith("`") and len(pattern) >= 2:
            return response.strip() == pattern[1:-1].strip()
        return normalize_text(response, diacritics=diacritics) == normalize_text(
            pattern, diacritics=diacritics
        )




class ShortAnswerQuestion(BaseQuestion[t.TextResponse]):
    type: Literal["short-answer"] = "short-answer"
    one_of: list[str] | None = None
    regex: str | None = None

    #: Grading rules. `accept` decides the score and wins over `reject`
    #: when both match; `reject` only attaches feedback to answers known
    #: to be wrong.
    accept: list[AnswerPattern] | None = None
    reject: list[AnswerPattern] | None = None

    #: Pre-submission validators. A system warns the student before
    #: accepting the answer; grading ignores them entirely.
    pre_accept: list[AnswerPattern] | None = None
    pre_reject: list[AnswerPattern] | None = None

    #: When true the question has no machine-checkable key and is graded
    #: by hand, so `oneOf`, `regex`, `accept` and `reject` must all be
    #: absent.
    open_ended: bool = False

    #: How inexact literals treat diacritics, in every pattern list.
    diacritics: Diacritics = "fold"

    @field_validator("regex")
    @classmethod
    def check_regex_compiles(cls, value: str | None) -> str | None:
        return _validate_mdq_regex(value)

    @model_validator(mode="after")
    def check_open_ended_has_no_answer_key(self) -> Self:
        """
        `openEnded` means there is nothing to grade against
        (short-answer.md), so it contradicts any of the fields that
        would otherwise supply one.

        Raises:
            ValueError: `open_ended` is set alongside `one_of`, `regex`,
                `accept` or `reject`.
        """
        if self.open_ended and (
            self.one_of is not None
            or self.regex is not None
            or self.accept is not None
            or self.reject is not None
        ):
            raise ValueError(
                "openEnded has no answer key: it must not be combined with "
                "oneOf, regex, accept or reject"
            )
        return self

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(
            _lint.check_short_answer(
                regex=self.regex,
                one_of=self.one_of,
                accept=self.accept,
                reject=self.reject,
                open_ended=self.open_ended,
                path=(),
            )
        )
        return diagnostics

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.open_ended:
            data["openEnded"] = True
        if self.diacritics != "fold":
            data["diacritics"] = self.diacritics
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        tag = "[short-answer]"
        if self.accept is not None or self.reject is not None:
            yield from render_pattern_block("accept", self.accept)
            yield from render_pattern_block("reject", self.reject)
        elif self.regex is not None:
            yield f"{tag}: /{self.regex}/"
        elif self.one_of is None:
            yield f"{tag}:"
        elif len(self.one_of) == 1:
            yield f"{tag}: {self.one_of[0]}"
        else:
            yield f"{tag}:"
            for answer in self.one_of:
                yield f"* {answer}"

    def effective_accept(self) -> list[AnswerPattern]:
        """
        Return the accept list grading uses, desugaring the legacy fields.

        `accept` wins when set. Otherwise `regex` -- which still takes
        precedence over `one_of` -- becomes a single delimited pattern.
        """
        if self.accept is not None:
            return self.accept
        if self.regex is not None:
            return [AnswerPattern(pattern=f"/{self.regex}/")]
        return [AnswerPattern(pattern=answer) for answer in self.one_of or []]

    def score_response(self, response: t.TextResponse) -> QuestionScore:
        """
        Score 1 if `response` matches an accept pattern, else 0.

        Raises:
            NotAutoGradable: the question has no answer key. A question
                carrying only `reject` lands here too: with nothing to
                accept it could never mark an answer correct.
        """
        accept = self.effective_accept()
        if self.open_ended or not accept:
            raise NotAutoGradable(
                "short-answer question has no machine-checkable answer key"
            )
        correct = any(
            rule.matches(response, diacritics=self.diacritics) for rule in accept
        )
        deciding = accept if correct else (self.reject or [])
        return QuestionScore(
            score=1.0 if correct else 0.0,
            feedback=first_feedback(deciding, response, diacritics=self.diacritics),
        )




class EssayQuestion(BaseQuestion[t.TextResponse]):
    type: Literal["essay"] = "essay"
    input: EssayInput = "text"
    highlight: str | None = None

    #: A model answer for the human grading this. Carrying one does not
    #: make the question auto-gradable.
    answer_key: str | None = None

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(_lint.check_essay_highlight(self.input, self.highlight))
        diagnostics.extend(_lint.check_blank_text_field(self.answer_key, "answerKey"))
        diagnostics.extend(_lint.check_missing_answer_key(self.answer_key))
        return diagnostics

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.input != "text":
            data["input"] = self.input
        if self.highlight is not None:
            data["highlight"] = self.highlight
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        yield "[essay]"

    def score_response(self, response: t.TextResponse) -> QuestionScore:
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

def normalize_text(value: str, *, diacritics: Diacritics = "fold") -> str:
    """
    Fold case and collapse whitespace to single spaces, for the plain
    literal comparison in `AnswerPattern.matches`.

    `diacritics="fold"` also strips diacritics (NFKC then accent
    stripping); `"keep"` only applies NFKC, so an NFD and an NFC
    spelling of the same accented text still compare equal.
    """
    value = unicodedata.normalize("NFKC", value)
    if diacritics == "fold":
        value = strip_accents(value)
    return re.sub(r"\s+", " ", value).casefold().strip()


def render_pattern_block(
    variant: str, patterns: list[AnswerPattern] | None, tag: str = "short-answer"
) -> Iterable[str]:
    """
    Render one `accept` or `reject` pattern block.

    `tag` names the owning construct: the default renders a standalone
    question's `[short-answer/accept]`, while a fill-in blank passes
    `^<id>/short-answer` to render `[^<id>/short-answer/accept]`.
    """
    if patterns is None:
        return
    yield f"[{tag}/{variant}]:"
    for rule in patterns:
        yield f"* {rule.pattern}"
        if rule.feedback is not None:
            yield f"  > {rule.feedback}"
        if rule.comment is not None:
            yield f"  ! {rule.comment}"
    yield ""


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


def short_answer_matches(
    response: str,
    *,
    one_of: list[str] | None,
    regex: str | None,
    accept: list[AnswerPattern] | None = None,
    diacritics: Diacritics = "fold",
) -> bool:
    """
    Report whether `response` matches `accept`, `regex` or `one_of`.

    `accept` wins over both legacy fields, and `regex` over `one_of`.
    Matching is always a full match, never a search. `diacritics`
    applies to the plain-literal patterns in `accept`/`one_of`.
    """
    if accept is None:
        if regex is not None:
            accept = [AnswerPattern(pattern=f"/{regex}/")]
        else:
            accept = [AnswerPattern(pattern=answer) for answer in one_of or []]
    return any(rule.matches(response, diacritics=diacritics) for rule in accept)



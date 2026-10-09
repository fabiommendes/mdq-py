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
from importlib import resources
from typing import Annotated, Any, Iterable, Literal, Self

from pydantic import Field, model_validator

from .. import types as t
from .._markdown import UNICODE_SPACE
from .._diagnostics import Diagnostic
from ..errors import NotAutoGradable
from ..types import Automation, Diacritics, EssayInput, Unmatched
from . import _lint
from ._base import BaseQuestion, MdqModel, _raise_unique_id_error
from ._regex import InvalidRegexError, RegexPattern
from ._score import QuestionScore

__all__ = ["AnswerPattern", "ShortAnswerQuestion", "EssayQuestion"]


PATTERN_STRING_RE = r"^(?:`[^`\n]+`[ \t]*|[^`\s][\s\S]*|\s+[^`\s][\s\S]*)$"


class AnswerPattern(MdqModel):
    """
    One entry of an `accept`/`reject`/`preAccept`/`preReject` list.

    A bare string in the document is shorthand for a pattern with no
    feedback and no comment, so both spellings load into this model.
    """

    #: A regex when delimited by `/`, an exact literal when enclosed in
    #: backticks, and an inexact plain literal otherwise. The pattern
    #: mirrors `patternString` in schema/short-answer.yaml: at least one
    #: visible character, and a pattern that opens with a backtick is a
    #: complete backtick-enclosed span (short-answer.md, "Content").
    pattern: Annotated[str, Field(min_length=1, pattern=PATTERN_STRING_RE)]
    feedback: Annotated[str | None, Field(default=None, min_length=1)] = None
    comment: Annotated[str | None, Field(default=None, min_length=1)] = None

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
        # short-answer.md, "Pattern lines": the pattern is a regex if it
        # starts with `/` after stripping spaces and tabs.
        if self.pattern.strip(" \t\r\n").startswith("/"):
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

        A backtick-enclosed literal is compared code point for code point
        after two steps, in order, on the response and on the pattern
        content: NFC (not NFKC), then removal of `UNICODE_SPACE` code
        points from both ends (patterns.md, "Exact literals"). `diacritics`
        does not affect it; a bare literal is compared after normalization, which
        `diacritics` tunes: `"fold"` strips diacritics as it always did,
        `"keep"` leaves them so `Maceió` rejects `Maceio`; a regex sees
        the raw response and lets its own flags decide -- normalizing
        first would make a case-sensitive regex impossible, and neither
        it nor the backtick form consult `diacritics` at all.
        """
        pattern = self.pattern.strip(" \t\r\n")
        if pattern.startswith("/"):
            return RegexPattern(pattern).match(response)
        if pattern.startswith("`") and pattern.endswith("`") and len(pattern) >= 2:
            return _exact_form(response) == _exact_form(pattern[1:-1])
        return normalize_text(response, diacritics=diacritics) == normalize_text(
            pattern, diacritics=diacritics
        )




#: A pattern list holds at least one entry (schema `patternList`, `minItems: 1`).
PatternList = Annotated[list[AnswerPattern], Field(min_length=1)]


class ShortAnswerQuestion(BaseQuestion[t.TextResponse]):
    type: Literal["short-answer"] = "short-answer"
    #: Grading rules. `accept` decides the score and wins over `reject`
    #: when both match; `reject` only attaches feedback to answers known
    #: to be wrong.
    accept: PatternList | None = None
    reject: PatternList | None = None

    #: Pre-submission validators. A system warns the student before
    #: accepting the answer; grading ignores them entirely.
    pre_accept: PatternList | None = None
    pre_reject: PatternList | None = None

    #: How inexact literals treat diacritics, in every pattern list.
    diacritics: Diacritics = "fold"

    #: What becomes of a response that matches no pattern (short-answer.md,
    #: "Grading"). `None` means the default, see `effective_unmatched`.
    unmatched: Unmatched | None = None

    #: Feedback for an incorrect response that no pattern gave feedback to
    #: (short-answer.md, "Feedback").
    incorrect_feedback: Annotated[str | None, Field(default=None, min_length=1)] = None

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
            _lint.check_short_answer(
                accept=self.accept,
                reject=self.reject,
                pre_accept=self.pre_accept,
                pre_reject=self.pre_reject,
                path=(),
            )
        )
        diagnostics.extend(
            _lint.check_no_correct_answer(
                accept=self.accept,
                unmatched=self.effective_unmatched,
                path=("unmatched",),
            )
        )
        diagnostics.extend(
            _lint.check_blank_text_field(self.incorrect_feedback, "incorrectFeedback")
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

    def effective_accept(self) -> list[AnswerPattern]:
        """Return the accept list grading uses: `accept`, or empty when unset."""
        return self.accept or []

    def score_response(self, response: t.TextResponse) -> QuestionScore:
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
        outcome = settle_response(
            self.accept,
            self.reject,
            response,
            unmatched=self.effective_unmatched,
            diacritics=self.diacritics,
        )
        if outcome == "pending":
            raise NotAutoGradable(
                "the response matches no pattern and 'unmatched' is 'manual'"
            )
        feedback = first_feedback(
            (self.accept if outcome == "correct" else self.reject) or [],
            response,
            diacritics=self.diacritics,
        )
        if outcome == "incorrect" and not feedback and self.incorrect_feedback:
            feedback = [self.incorrect_feedback]
        return QuestionScore(
            score=1.0 if outcome == "correct" else 0.0, feedback=feedback
        )




class EssayQuestion(BaseQuestion[t.TextResponse]):
    type: Literal["essay"] = "essay"
    input: EssayInput = "text"
    highlight: Annotated[str | None, Field(default=None, min_length=1)] = None

    #: A model answer for the human grading this. Carrying one does not
    #: make the question auto-gradable.
    answer_key: Annotated[str | None, Field(default=None, min_length=1)] = None

    @property
    def automation(self) -> Automation:
        """Always `manual` (essay.md)."""
        return "manual"

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
    `diacritics == "fold"`, NFD, remove `Mn`, NFC and replace the
    `letters` table; replace the `punctuation` table; replace the
    `caseFolding` table and NFC; collapse each run of `UNICODE_SPACE`
    to one U+0020 and trim U+0020 from the ends. The tables come from
    `inexact-tables.json`, not from `str.casefold()`.
    """
    value = unicodedata.normalize("NFKC", value).translate(_IGNORABLE_TABLE)
    if diacritics == "fold":
        value = unicodedata.normalize("NFD", value)
        value = "".join(c for c in value if unicodedata.category(c) != "Mn")
        value = unicodedata.normalize("NFC", value).translate(_LETTERS)
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
    written. A question with no `accept` renders an empty `[<tag>]:`, followed by
    the reject block if any. `tag`
    names the owning construct: a fill-in blank passes `^<id>/short-answer`.
    """
    if accept is None:
        # The grammar requires the accept block, even with no pattern.
        yield f"[{tag}]:"
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



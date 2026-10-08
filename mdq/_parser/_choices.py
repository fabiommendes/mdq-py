"""
Choice-list parsing, shared by multiple-choice, multiple-selection,
true-false and fill-in choice blanks -- every question shape whose body
is a bracket-led list (`* [x] ...`).

Also home to the slug regexes (`SLUG_BODY_RE`/`SLUG_PREFIX_RE`): a
choice id is written with the exact same syntax as a question/exam slug
(`CHOICE_ID_PREFIX_RE`), so the body pattern lives here rather than in
`_question`, which needs it too (for `BLANK_RE`'s id, and for the
`[slug]` prefix on a stem/title) but must not become this module's
dependency -- `MDQParser.parse_choice_body` already imports from here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple

from ..errors import ParseError
from ..types import PatternDict

__all__ = ["RawChoice", "SLUG_BODY_RE", "SLUG_PREFIX_RE"]

# The grammar's `ws` is only spaces and tabs (docs/references/grammar.md):
# every `[ \t]` below is `ws`, and every `strip(" \t")` in this package
# trims `ws`. Any other Unicode space is text.

# Slugs and choice ids. A bracket followed by `(` or `[` opens a markdown
# link (`[text](url)`, `[text][ref]`), so it is never a slug or a choice id
# (base.md, "Slug"; multiple-choice.md, "Body").
SLUG_BODY_RE = r"[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*"
_NOT_A_LINK = r"(?![(\[])"
SLUG_PREFIX_RE = re.compile(rf"^\[(?P<slug>{SLUG_BODY_RE})\]{_NOT_A_LINK}[ \t]*")
CHOICE_ID_PREFIX_RE = re.compile(rf"^\[(?P<id>{SLUG_BODY_RE})\]{_NOT_A_LINK}[ \t]*")

ITEM_MARKER_RE = re.compile(r"^[*+-][ \t]+\[(?P<value>[^\]]*)\][ \t]?(?P<rest>.*)$")
PERCENT_RE = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?%$")
#: A list item with no `[value]` marker, e.g. a pattern line. A bare
#: marker (`*` alone on its line) is an item with no text, so an empty
#: pattern line is reported as such instead of being read as a
#: continuation of the item before it.
PLAIN_ITEM_RE = re.compile(r"^[*+-](?:[ \t]+(?P<rest>.*)|[ \t]*)$")
LIST_ITEM_START_RE = re.compile(r"^[*+-](?:[ \t]|[ \t]*$)")

# True/false marker classification, per
# docs/question-types/true-false.md#body. Only FALSE letters mean false;
# TRUE and WARNING letters both mean true. CJK characters have no
# case, so they're listed once rather than lowercased.
FALSE_LETTERS = {"f", "错", "偽"}


@dataclass(slots=True)
class RawChoice:
    value: str
    explicit_id: str | None
    text: str
    feedback: str | None = None
    comment: str | None = None


class ParsedMarker(NamedTuple):
    marker: str
    id: str | None
    rest: str


def parse_marker(line: str) -> ParsedMarker:
    """
    Extract a choice item's (value, explicit id, remaining text) from
    its first raw line, e.g. `* [x] [my-id] Some text`.

    Raises:
        ParseError: If `line` does not start with a `* [value]` marker, or the
            brackets are empty (`[]`).
    """

    m = ITEM_MARKER_RE.match(line)
    if not m:
        raise ParseError(f"malformed choice item: {line!r}")

    if not m.group("value"):
        raise ParseError(f"empty choice marker `[]` (use `[ ]` for blank): {line!r}")
    value = m.group("value").strip(" \t")
    rest = m.group("rest")

    id = None
    id_match = CHOICE_ID_PREFIX_RE.match(rest)
    if id_match:
        id = id_match.group("id")
        rest = rest[id_match.end() :]

    return ParsedMarker(value, id, rest)


def _strip_list_marker(line: str) -> str:
    """Strip a plain (non-bracket) list item's `* `/`- ` marker."""

    m = PLAIN_ITEM_RE.match(line)
    return (m.group("rest") or "").strip(" \t") if m else line.strip(" \t")


def _split_list_items(item_lines: list[str]) -> list[list[str]]:
    items: list[list[str]] = []
    current: list[str] = []
    for line in item_lines:
        if LIST_ITEM_START_RE.match(line):
            current = [line]
            items.append(current)
        else:
            current.append(line)
    return items


def _assign_choice_ids(choices: list[RawChoice]) -> list[str | None]:
    """
    Return each choice's id, exactly as the author wrote it -- `None` for
    a choice with no explicit id.

    A choice without an id used to get one derived from its text here;
    that derivation now lives in `mdq.models.BaseQuestion.with_ids`,
    called by whoever needs an addressable document
    (dev/specs/to-do/derived-ids.md).
    """
    return [choice.explicit_id for choice in choices]


def foreign_choice_index(question_type: str, values: list[str]) -> int | None:
    """
    The index of the first value that is not in the `value` rule of
    `question_type` (base.md, "Type inference"), or None when every value
    belongs to it. `values` are the bracket values stripped of spaces and
    tabs, as `RawChoice.value` holds them: multiple-choice takes `""`,
    `*` or a percentage; multiple-selection `""`, `x` or `X`; true-false
    one letter (`\\p{L}`) other than `x`/`X`.
    """
    for index, value in enumerate(values):
        if question_type == "multiple-choice":
            ok = value in ("", "*") or bool(PERCENT_RE.match(value))
        elif question_type == "multiple-selection":
            ok = value in ("", "x", "X")
        elif question_type == "true-false":
            ok = len(value) == 1 and value.isalpha() and value.lower() != "x"
        else:
            continue
        if not ok:
            return index
    return None


def _infer_choice_type(values: list[str]) -> str | None:
    """
    Infer multiple-choice / multiple-selection / true-false from the
    bracket values used in a choice list, per generic.md's rule that a
    bracket-led list is never valid preamble -- it is always a choice
    body of one of these three kinds.

    A list whose markers are all blank is multiple-selection: nothing is
    marked correct, which multiple-selection allows outright (zero correct
    choices is a legal answer key) but multiple-choice does not.
    """

    for v in values:
        if v == "*" or PERCENT_RE.match(v):
            return "multiple-choice"
    for v in values:
        if v.lower() == "x":
            return "multiple-selection"
    for v in values:
        if v and v.lower() not in ("x",) and len(v) == 1 and v.isalpha():
            return "true-false"
    return "multiple-selection"


def _score_from_value(value: str) -> float | int | None:
    """
    The `score` of a choice `value` (multiple-choice.md, "Choices"): `*`
    is 1, a percentage is its fraction, and a blank omits the score --
    the grading strategy decides what it is worth. Any other value is
    read as a blank too.
    """
    if value == "*":
        return 1
    if PERCENT_RE.match(value):
        return float(value[:-1]) / 100
    return None


def _pattern_entry(item: RawChoice) -> str | PatternDict:
    """Return one accept/reject entry, bare when it has no feedback or comment."""
    pattern = item.text.strip(" \t")
    if not pattern:
        raise ParseError("a short-answer pattern line cannot be empty")
    if not item.feedback and not item.comment:
        return pattern
    entry: PatternDict = {"pattern": pattern}
    if item.feedback:
        entry["feedback"] = item.feedback
    if item.comment:
        entry["comment"] = item.comment
    return entry

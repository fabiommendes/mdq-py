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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, NamedTuple

from .._markdown import SLUG_BODY_RE
from .._letters import is_letter, normalize_value, strip_marker_space
from ..errors import ParseError
from ..types import PatternDict

__all__ = ["RawChoice", "SLUG_BODY_RE", "SLUG_PREFIX_RE"]

# The grammar's `ws` is only spaces and tabs (docs/references/grammar.md):
# every `[ \t]` below is `ws`, and every `strip(" \t")` in this package
# trims `ws`. Any other Unicode space is text.

# Slugs and choice ids. A bracket followed by `(` or `[` opens a markdown
# link (`[text](url)`, `[text][ref]`), so it is never a slug or a choice id
# (base.md, "Slug"; multiple-choice.md, "Body").
_NOT_A_LINK = r"(?![(\[])"
SLUG_PREFIX_RE = re.compile(rf"^\[(?P<slug>{SLUG_BODY_RE})\]{_NOT_A_LINK}[ \t]*")
CHOICE_ID_PREFIX_RE = re.compile(rf"^\[(?P<id>{SLUG_BODY_RE})\]{_NOT_A_LINK}[ \t]*")

#: The `CHOICE_MARK` terminal of docs/references/choices.md: a bracket
#: with no `]` or line ending inside, not followed by `(` or `[` (which
#: would start a markdown link).
CHOICE_MARK_RE = re.compile(r"\[(?P<value>[^\]\r\n]*)\](?![(\[])")
#: A bracket that starts a markdown link, `[text](url)` or `[text][ref]`.
LINK_START_RE = re.compile(r"\[[^\]\r\n]*\][(\[]")
#: The `percent` rule of multiple-choice.md: an `INTEGER` or a `DECIMAL`
#: (no leading zeros) with an optional sign.
PERCENT_RE = re.compile(r"^[+-]?(?:[1-9][0-9]*|0)(?:\.[0-9]+)?%$")
#: The `LAZY_START` terminal of docs/references/grammar.md, for a line
#: without its line ending: the first character of a line that continues
#: the block before it. It is not a `>` or `!` marker, and it does not
#: start a block that interrupts a paragraph.
LAZY_START_RE = re.compile(
    r"(?!>|!(?!\[)|[*+-][ \t]|0{0,8}1[.)][ \t]|#{1,6}(?:[ \t]|$)|`{3}|~{3}"
    r"|(?:\*[ \t]*){3,}$|(?:-[ \t]*){3,}$|(?:_[ \t]*){3,}$)[^ \t\r\n]"
)
#: Columns of indentation that make a line code or a continuation line,
#: relative to the content of the list item that holds it.
CODE_INDENT = 4


@dataclass(slots=True)
class RawChoice:
    value: str
    explicit_id: str | None
    text: str
    feedback: str | None = None
    comment: str | None = None
    #: The number of source lines of `text`.
    text_lines: int = 1


class ParsedMarker(NamedTuple):
    marker: str
    id: str | None
    rest: str


def indentation(line: str) -> int:
    """
    The columns of whitespace at the start of `line`, with a tab
    expanded to the next multiple of four columns, as in CommonMark.
    """
    column = 0
    for char in line:
        if char == " ":
            column += 1
        elif char == "\t":
            column += 4 - column % 4
        else:
            break
    return column


def dedent(line: str, columns: int) -> str:
    """
    Remove `columns` columns of indentation from the start of `line`.

    Tabs in the indentation expand to spaces first, so a tab that spans
    the cut keeps the columns after it. A line with less indentation
    loses all of it, as a lazy continuation line does in CommonMark.
    """
    rest = line.lstrip(" \t")
    return " " * max(indentation(line) - columns, 0) + rest


def match_choice_marker(line: str) -> re.Match[str] | None:
    """
    The choice marker at the start of the first content line of a list
    item (choices.md, "Choice marker"), or None when the line does not
    start with one. Up to three columns of indentation can come before
    it; with more, the content is an indented code block
    (grammar.md, "Content of a list item").
    """
    if indentation(line) >= CODE_INDENT:
        return None
    return CHOICE_MARK_RE.match(line.lstrip(" \t"))


def parse_marker(line: str) -> ParsedMarker:
    """
    Extract a choice item's (value, explicit id, remaining text) from the
    first content line of the item, e.g. `[x] [my-id] Some text`.

    Raises:
        ParseError: If `line` does not start with a choice marker, or the
            brackets are empty (`[]`).
    """

    m = match_choice_marker(line)
    if not m:
        raise ParseError(f"malformed choice item: {line!r}")
    if not m.group("value"):
        raise ParseError(f"empty choice marker `[]` (use `[ ]` for blank): {line!r}")
    value = strip_marker_space(m.group("value"))
    rest = line.lstrip(" \t")[m.end() :].lstrip(" \t")

    id = None
    id_match = CHOICE_ID_PREFIX_RE.match(rest)
    if id_match:
        id = id_match.group("id")
        rest = rest[id_match.end() :]

    return ParsedMarker(value, id, rest)


def is_choice_value(value: str) -> bool:
    """
    Whether the text of a choice marker is the value of some choice type
    or is empty (question-base.md, "Forbidden elements"): blank, `x`/`X`,
    `*`, a percentage, a single letter, or `[]`. The value is normalized
    first (`normalize_value`), so `[＊]` is `*`.
    """
    normalized = normalize_value(value)
    return (
        normalized in ("", "*")
        or bool(PERCENT_RE.match(normalized))
        or is_letter(normalized)
    )


#
# Feedback and comment lines (grammar.md, "Feedback and comment lines")
#
#: The kind of a line after the text of an element: a `>` feedback line,
#: a `!` comment line, a lazy continuation line, a blank line, or a line
#: that starts a block which interrupts a paragraph.
LineKind = Literal[">", "!", "lazy", "blank", "block"]


def classify_line(line: str) -> tuple[LineKind, str]:
    """
    Return the kind of `line` and its content: the text after the marker
    and its `ws` for a feedback or comment line, the text without its
    indentation for a lazy line.

    `line` is relative to the content of its element: a line with four
    or more columns of indentation is a continuation line, whatever it
    starts with (grammar.md, "Content of a list item").
    """
    stripped = line.strip(" \t")
    if not stripped:
        return "blank", ""
    if indentation(line) >= CODE_INDENT:
        return "lazy", stripped
    if stripped.startswith(">"):
        return ">", stripped[1:].strip(" \t")
    if stripped.startswith("!") and not stripped.startswith("!["):
        return "!", stripped[1:].strip(" \t")
    if LAZY_START_RE.match(stripped):
        return "lazy", stripped
    return "block", stripped


def join_paragraph_lines(lines: list[str]) -> str:
    """
    Join the lines of a text, feedback or comment as markdown joins the
    lines of a paragraph: with one space. An empty string in `lines` is an
    empty marker line, which separates two paragraphs with a blank line.
    """
    paragraphs: list[list[str]] = [[]]
    for line in lines:
        if line:
            paragraphs[-1].append(line)
        elif paragraphs[-1]:
            paragraphs.append([])
    return "\n\n".join(" ".join(p) for p in paragraphs if p)


def split_item(
    first: str,
    lines: list[str],
    join_text: Callable[[list[str]], str] = join_paragraph_lines,
) -> RawChoice:
    """
    Split the content of an element into its text, feedback and comment.

    Args:
        first: The text on the first line, after the marker, value and id.
        lines: The other content lines of the element, relative to its
            content column.
        join_text: Joins the lines of the text. A pattern joins them as
            `join_pattern_lines` does.

    Returns:
        A `RawChoice` with an empty value and no id, which the caller
        fills in.

    Raises:
        ParseError: The lines after the text are not a feedback block and
            a comment block (`parse_observations`).
    """
    text = [first.strip(" \t")]
    index = 0
    while index < len(lines):
        kind, content = classify_line(lines[index])
        if kind != "lazy":
            break
        text.append(content)
        index += 1
    feedback, comment = parse_observations(lines[index:])
    return RawChoice("", None, join_text(text), feedback, comment, len(text))


def parse_observations(lines: list[str]) -> tuple[str | None, str | None]:
    """
    Read the feedback (`>`) and comment (`!`) blocks of an element, in
    either order, and return the value of each, or None when absent.

    A marker line of the other kind, or a blank line, ends a block. A lazy
    line continues the open block. An empty marker line separates two
    paragraphs of the value.

    Raises:
        ParseError: A second block of the same kind (also after a blank
            line or a block of the other kind), a lazy line with no open
            block, or a line that starts another markdown block.
    """
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        kind, content = classify_line(line)
        if kind == "blank":
            current = None
        elif kind in (">", "!"):
            if kind != current:
                if kind in blocks:
                    name = "feedback" if kind == ">" else "comment"
                    raise ParseError(
                        f"an element has at most one {name} block: {line!r}"
                    )
                blocks[kind] = []
                current = kind
            blocks[kind].append(content)
        elif kind == "lazy" and current is not None:
            blocks[current].append(content)
        else:
            raise ParseError(
                "only a feedback block and a comment block can follow the text "
                f"of an element: {line!r}"
            )
    feedback = blocks.get(">")
    comment = blocks.get("!")
    return (
        None if feedback is None else join_paragraph_lines(feedback),
        None if comment is None else join_paragraph_lines(comment),
    )


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
    tabs, as `RawChoice.value` holds them. The rules apply to the
    normalized value (`normalize_value`): multiple-choice takes `""`, `*`
    or a percentage; multiple-selection `""` or `x`; true-false one
    letter (`LETTER`) that is not `x`.
    """
    for index, value in enumerate(values):
        normalized = normalize_value(value)
        if question_type == "multiple-choice":
            ok = normalized in ("", "*") or bool(PERCENT_RE.match(normalized))
        elif question_type == "multiple-selection":
            ok = normalized in ("", "x")
        elif question_type == "true-false":
            ok = is_letter(normalized) and normalized != "x"
        else:
            continue
        if not ok:
            return index
    return None


def _infer_choice_type(values: list[str]) -> str | None:
    """
    Infer multiple-choice / multiple-selection / true-false from the
    bracket values used in a choice list, per generic.md's rule that a
    bracket-led list is never valid stem -- it is always a choice
    body of one of these three kinds.

    A list whose markers are all blank is multiple-selection: nothing is
    marked correct, which multiple-selection allows outright (zero correct
    choices is a legal answer key) but multiple-choice does not.
    """

    normalized = [normalize_value(v) for v in values]
    for n in normalized:
        if n == "*" or PERCENT_RE.match(n):
            return "multiple-choice"
    if "x" in normalized:
        return "multiple-selection"
    for n in normalized:
        if is_letter(n):
            return "true-false"
    return "multiple-selection"


def _score_from_value(value: str) -> float | int | None:
    """
    The `score` of a choice `value` (multiple-choice.md, "Choices"): `*`
    is 1, a percentage is its fraction, and a blank omits the score --
    the grading strategy decides what it is worth. Any other value is
    read as a blank too.
    """
    value = normalize_value(value)
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
    if item.feedback is None and item.comment is None:
        return pattern
    entry: PatternDict = {"pattern": pattern}
    if item.feedback is not None:
        entry["feedback"] = item.feedback
    if item.comment is not None:
        entry["comment"] = item.comment
    return entry

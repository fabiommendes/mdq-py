"""
`[ordering]` body parsing: turning the raw `(indent, text)` lines of an
`[ordering]`/`[extra]`/`[accept]`/`[reject]` block into the leveled
`[level, text]` pairs the schema expects, once the indentation unit has
been inferred across the whole question (ordering.md#indentation).
"""

from __future__ import annotations

import math
import re
from typing import NamedTuple

from markdown_it.common.utils import unescapeAll
from markdown_it.tree import SyntaxTreeNode as Node

from .._markdown import span
from ..errors import ParseError
from ..types import OrderingAlternativeDict

#: A line before its indentation is reduced to a level -- the leading
#: whitespace measured in columns (tab stops of 4) for a code line, or the
#: nesting depth for a `ul` item, and the text.
RawLine = tuple[int, str]

# `## [extra]` / `## [accept]` / `## [reject]`, matched the way
# ANSWER_KEY_RE matches `## [answer-key]`.
ORDERING_SECTION_RE = re.compile(r"^\[(?P<name>extra|accept|reject)\]$")
# An ordering `ul` item's line: leading whitespace (the indentation to be
# measured), the marker, and the item's raw markdown source verbatim.
ORDERING_ITEM_RE = re.compile(r"^(?P<indent>[ \t]*)[*+-][ \t]+(?P<text>.*)$")
# A bare marker with no text.
EMPTY_ITEM_RE = re.compile(r"^[ \t]*[*+-][ \t]*$")
# Markers of nested lists opened on the same source line (`- - Bahia`).
NESTED_MARKER_RE = re.compile(r"^[*+-][ \t]+")
NESTED_ORDERED_RE = re.compile(r"^\d{1,9}[.)](?:[ \t]|$)")


class RawAlternative(NamedTuple):
    """One raw `## [accept]`/`## [reject]` section, before leveling."""

    lines: list[RawLine]
    feedback: str | None
    comment: str | None


def fence_language(info: str) -> str | None:
    """
    The language of a code fence: the first word of its info string, after
    CommonMark backslash and entity processing. A word ends at the first
    space or tab. `None` when the info string is empty.
    """
    text = unescapeAll(info).strip(" \t")
    return re.split(r"[ \t]", text, maxsplit=1)[0] or None


def ordering_code_lines(content: str) -> list[RawLine]:
    """Split a fence's raw content into `(indent, text)` pairs, one per line."""
    raw_lines = content.split("\n")
    if raw_lines and raw_lines[-1] == "":  # trailing newline
        raw_lines.pop()
    return [ordering_line_indent(line) for line in raw_lines]


def collect_item_depths(
    node: Node, depth: int, depths: dict[int, int], parents: set[int] | None = None
) -> None:
    """
    Record the nesting depth of every item of a list node, by source line.

    Args:
        node: a list node of the markdown-it syntax tree.
        depth: the depth of the items directly under `node`.
        depths: filled with `{0-based source line: depth}`.
        parents: when given, filled with the source lines of the items
            that hold a nested list.
    """
    for item in node.children:
        if item.type != "list_item":
            continue
        depths[span(item)[0]] = depth
        for child in item.children:
            if child.type in ("bullet_list", "ordered_list"):
                if parents is not None:
                    parents.add(span(item)[0])
                collect_item_depths(child, depth + 1, depths, parents)


def ordering_ul_lines(
    raw_lines: list[str],
    depths: dict[int, int],
    first_line: int,
    parents: set[int] | None = None,
) -> list[RawLine]:
    """
    Split a `ul` block's raw source lines into `(depth, text)` pairs.

    The first element of a pair is the item's nesting depth, not a column
    (ordering.md#body): top-level items are 0, their children 1, and so on.

    Args:
        raw_lines: the source lines of the whole list block.
        depths: nesting depth of each list item, by its 0-based source line.
        first_line: the 0-based source line of `raw_lines[0]`.
        parents: the source lines of the items that hold a nested list. An
            item with no text of its own among them is not a line.

    Raises:
        ParseError: a non-blank line is not a bullet list item, i.e. an item
            has a continuation line or a second paragraph, or a nested list
            is ordered (an ordering item is exactly one line), or an item
            has no text and holds no nested list.
    """
    items = []
    for offset, line in enumerate(raw_lines):
        if not line.strip(" \t"):
            continue
        if (
            parents is not None
            and first_line + offset in parents
            and EMPTY_ITEM_RE.match(line)
        ):
            continue
        m = ORDERING_ITEM_RE.match(line)
        depth = depths.get(first_line + offset)
        if m is None or depth is None:
            raise ParseError(
                "an ordering item is exactly one line and a nested list is "
                f"a `ul`, found: {line!r}"
            )
        text = m.group("text").rstrip(" \t")
        # An item holding only a nested list is not a line: it adds a level
        # of depth, which `depths` already holds (`- - Bahia`).
        while nested := NESTED_MARKER_RE.match(text):
            text = text[nested.end() :]
        if not text:
            raise ParseError(f"an ordering item must have text, found: {line!r}")
        if NESTED_ORDERED_RE.match(text):
            raise ParseError(
                "an ordering item is exactly one line and a nested list is "
                f"a `ul`, found: {line!r}"
            )
        items.append((depth, text))
    return items


def ordering_line_indent(line: str) -> RawLine:
    """
    A code line's `(indent, text)`.

    Trailing spaces and tabs are removed. The leading whitespace is
    measured in columns, with CommonMark tab stops: a tab advances to the
    next multiple of 4. A blank line (spaces and tabs only) is level 0 with
    empty text, regardless of any accidental whitespace.
    """
    line = line.rstrip(" \t")
    if not line:
        return 0, ""
    expanded = line.expandtabs(4)
    stripped = expanded.lstrip(" ")
    return len(expanded) - len(stripped), stripped


def ordering_unit(indents: list[int]) -> int:
    """
    The indentation unit for a question: the GCD of every positive
    indent among `indents`, or 4 spaces when none is indented at all
    (ordering.md#indentation).
    """
    positives = [i for i in indents if i > 0]
    return math.gcd(*positives) if positives else 4


def ordering_leveled(raw: list[RawLine], unit: int) -> list[list[int | str]]:
    """Convert `(indent, text)` pairs into `[level, text]` lists, per fixture shape."""
    return [[indent // unit, text] for indent, text in raw]


def ordering_alternative(alt: RawAlternative, unit: int) -> OrderingAlternativeDict:
    """Build one `accept`/`reject` entry from its raw lines and observations."""
    entry: OrderingAlternativeDict = {"lines": ordering_leveled(alt.lines, unit)}
    if alt.feedback is not None:
        entry["feedback"] = alt.feedback
    if alt.comment is not None:
        entry["comment"] = alt.comment
    return entry


def is_comment_block(lines: list[str]) -> bool:
    """Whether every raw line of a paragraph is a `!`-prefixed comment line."""
    return bool(lines) and all(line.strip(" \t").startswith("!") for line in lines)

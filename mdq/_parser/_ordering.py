"""
`[ordering]` body parsing: turning the raw `(indent, text)` lines of an
`[ordering]`/`[extra]`/`[accept]`/`[reject]` block into the leveled
`[level, text]` pairs the schema expects, once the indentation unit has
been inferred across the whole question (ordering.md#indentation).
"""

from __future__ import annotations

import math
import re
from typing import Any, NamedTuple

#: A line before its indentation is reduced to a level -- the leading
#: whitespace measured in columns (tabs counted as 4), and the text.
RawLine = tuple[int, str]

# `## [extra]` / `## [accept]` / `## [reject]`, matched the way
# ANSWER_KEY_RE matches `## [answer-key]`.
ORDERING_SECTION_RE = re.compile(r"^\[(?P<name>extra|accept|reject)\]$")
# An ordering `ul` item's line: leading whitespace (the indentation to be
# measured), the marker, and the item's raw markdown source verbatim.
ORDERING_ITEM_RE = re.compile(r"^(?P<indent>[ \t]*)[*+-][ \t]+(?P<text>.*)$")


class RawAlternative(NamedTuple):
    """One raw `## [accept]`/`## [reject]` section, before leveling."""

    lines: list[RawLine]
    feedback: str | None
    comment: str | None


def ordering_code_lines(content: str) -> list[RawLine]:
    """Split a fence's raw content into `(indent, text)` pairs, one per line."""
    raw_lines = content.split("\n")
    if raw_lines and raw_lines[-1] == "":  # trailing newline
        raw_lines.pop()
    return [ordering_line_indent(line) for line in raw_lines]


def ordering_ul_lines(raw_lines: list[str]) -> list[RawLine]:
    """Split a `ul` block's raw source lines into `(indent, text)` pairs."""
    items = []
    for line in raw_lines:
        m = ORDERING_ITEM_RE.match(line)
        if m:
            items.append((len(m.group("indent").expandtabs(4)), m.group("text")))
    return items


def ordering_line_indent(line: str) -> RawLine:
    """
    A code line's `(indent, text)`, tabs expanded to 4 spaces.

    A blank line (whitespace only) carries no indentation of its own,
    regardless of any accidental leading whitespace.
    """
    if not line.strip():
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


def ordering_alternative(alt: RawAlternative, unit: int) -> dict[str, Any]:
    """Build one `accept`/`reject` entry from its raw lines and observations."""
    entry: dict[str, Any] = {"lines": ordering_leveled(alt.lines, unit)}
    if alt.feedback:
        entry["feedback"] = alt.feedback
    if alt.comment:
        entry["comment"] = alt.comment
    return entry


def join_prefixed_lines(lines: list[str], prefix: str) -> str:
    """Strip a `>`/`!` prefix from each raw line and join the rest with spaces."""
    parts = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :].strip()
        parts.append(stripped)
    return " ".join(p for p in parts if p)


def is_comment_block(lines: list[str]) -> bool:
    """Whether every raw line of a paragraph is a `!`-prefixed comment line."""
    return bool(lines) and all(line.strip().startswith("!") for line in lines)

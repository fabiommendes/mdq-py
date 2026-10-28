"""
Helpers shared by the GIFT and Moodle XML converters.

Moodle's embedded-answer (Cloze) syntax is GIFT's answer syntax, so both
converters escape, scan and format text the same way.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ..models import Tolerance

#: GIFT and Cloze special characters, which a backslash escapes.
ESCAPE_REGEX = re.compile(r"[:=~{}#\\]")
UNESCAPE_REGEX = re.compile(r"\\(.)")
#: A `%credit%` tag at the start of an answer entry.
CREDIT_TAG_REGEX = re.compile(r"%(-?\d+(?:\.\d+)?)%")


def escape_text(text: str) -> str:
    r"""Backslash-escape the special characters (`:=~{}#\`) of a GIFT or Cloze text."""
    return ESCAPE_REGEX.sub(lambda m: "\\" + m.group(), text)


def unescape_text(text: str) -> str:
    """Undo `escape_text`."""
    return UNESCAPE_REGEX.sub(r"\1", text)


def find_unescaped(text: str, target: str, start: int = 0) -> int:
    """Return the index of the first unescaped occurrence of `target`, or -1."""
    i = start
    n = len(text)
    m = len(target)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i : i + m] == target:
            return i
        i += 1
    return -1


def split_unescaped(text: str, chars: str) -> list[str]:
    """Split `text` into segments, each starting at an unescaped char in `chars`."""
    positions = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch in chars:
            positions.append(i)
        i += 1
    return [text[a:b] for a, b in zip(positions, positions[1:] + [n])]


@dataclass
class Entry:
    """One `=`/`~` entry of an answer body. `text` and `feedback` are still escaped."""

    credit: float
    text: str
    feedback: str | None


def parse_entries(
    body: str, markers: str, credit_from_percent: Callable[[float], float]
) -> list[Entry]:
    """
    Split an answer body into its entries: a marker from `markers` (`=` is
    full credit, `~` none), an optional `%credit%` tag, the text and an
    optional `#feedback`. `credit_from_percent` converts the tag's percentage
    to a credit, which GIFT and Cloze do differently.
    """
    return entries_from_segments(split_unescaped(body, markers), credit_from_percent)


def entries_from_segments(
    segments: list[str], credit_from_percent: Callable[[float], float]
) -> list[Entry]:
    """Parse the segments of `parse_entries`: each starts with its `=` or `~` marker."""
    entries = []
    for entry in segments:
        credit = 1.0 if entry[0] == "=" else 0.0
        rest = entry[1:]
        credit_match = CREDIT_TAG_REGEX.match(rest)
        if credit_match:
            credit = credit_from_percent(float(credit_match.group(1)))
            rest = rest[credit_match.end() :]
        hash_pos = find_unescaped(rest, "#")
        if hash_pos == -1:
            entries.append(Entry(credit, rest, None))
        else:
            entries.append(Entry(credit, rest[:hash_pos], rest[hash_pos + 1 :] or None))
    return entries


def common_prefix(strings: list[str]) -> str:
    """Return the longest common prefix of `strings` (empty if `strings` is empty)."""
    if not strings:
        return ""
    first, *rest = strings
    length = len(first)
    for s in rest:
        length = min(length, len(s))
        while first[:length] != s[:length]:
            length -= 1
    return first[:length]


def join_blocks(*parts: str | None) -> str:
    """Join non-empty, stripped parts with a blank line, as the stem and epilogue do."""
    stripped = [part.strip() for part in parts if part]
    return "\n\n".join(part for part in stripped if part)


def format_num(value: float) -> str:
    """Render a float compactly: as an integer when it has no fractional part."""
    if value == int(value):
        return str(int(value))
    return repr(value)


def numeric_tolerance(value: float, tolerance: Tolerance | None) -> float:
    """Resolve an MDQ `Tolerance` to the single absolute tolerance of GIFT and Moodle XML."""
    if tolerance is None:
        return 0.0
    if tolerance.absolute is not None:
        return tolerance.absolute
    if tolerance.relative is not None:
        return tolerance.relative * abs(value)
    return 0.0

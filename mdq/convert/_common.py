"""
Helpers shared by the GIFT and Moodle XML converters.

Moodle's embedded-answer (Cloze) syntax is GIFT's answer syntax, so both
converters escape, scan and format text the same way.
"""

from __future__ import annotations

import re

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

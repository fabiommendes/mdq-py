"""
The exact literal of a pattern string (docs/references/patterns.md,
"Exact literals"): a CommonMark code span.
"""

from __future__ import annotations

import re

__all__ = ["exact_literal", "exact_span", "join_pattern_lines"]


_BACKTICK_RUN_RE = re.compile(r"`+")


def exact_literal(pattern: str) -> str | None:
    """
    Return the text of an exact literal, or `None` if `pattern` is not one.

    The literal follows the CommonMark code span (patterns.md, "Exact
    literals"): N backticks open it and the first run of exactly N
    backticks closes it. The closing run MUST end the pattern, otherwise
    the span is not complete and the result is `None`. If the content
    starts and ends with a space and is not only spaces, one space is
    removed from each end.
    """
    text = pattern.strip(" \t")
    opening = _BACKTICK_RUN_RE.match(text)
    if opening is None:
        return None
    width = opening.end()
    for run in _BACKTICK_RUN_RE.finditer(text, width):
        if run.end() - run.start() != width:
            continue
        if run.end() != len(text):
            return None
        content = text[width : run.start()]
        if content.startswith(" ") and content.endswith(" ") and content.strip(" "):
            content = content[1:-1]
        return content
    return None


def exact_span(text: str) -> str:
    """
    Return the pattern string of the exact literal whose content is `text`:
    the inverse of `exact_literal`. The fence is the shortest backtick run
    that no run of `text` equals. A space on each end keeps a backtick, or
    a space, at the end of `text` out of the fence.
    """
    runs = {len(run) for run in _BACKTICK_RUN_RE.findall(text)}
    width = 1
    while width in runs:
        width += 1
    fence = "`" * width
    needs_padding = text.startswith("`") or text.endswith("`") or (
        text.startswith(" ") and text.endswith(" ") and bool(text.strip(" "))
    )
    if needs_padding:
        text = f" {text} "
    return f"{fence}{text}{fence}"


def join_pattern_lines(lines: list[str]) -> str:
    """
    Join the lines of a pattern in the body of a document with one space
    each, as docs/references/patterns.md ("Continuation lines") defines.

    An exact literal cannot open at the end of a line, and its closing run
    cannot start a continuation line (patterns.md, "Exact literals"). The
    line endings of a literal exist for word wrap, and an edge space would
    need a rule on whether it is removed. For such a literal the lines are
    joined with a line feed instead, which no pattern string can hold, so
    the model reports a `schema-error` for it.
    """
    lines = [line.strip(" \t") for line in lines]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    opening = _BACKTICK_RUN_RE.match(lines[0])
    if opening is None or len(lines) == 1:
        return " ".join(lines)
    width = opening.end()
    if width == len(lines[0]):
        return "\n".join(lines)
    text = "\n".join(lines)
    for run in _BACKTICK_RUN_RE.finditer(text, width):
        if run.end() - run.start() == width:
            if text[run.start() - 1] == "\n":
                return "\n".join(lines)
            break
    return " ".join(lines)

"""
The exact literal of a pattern string (docs/references/patterns.md,
"Exact literals"): a CommonMark code span.
"""

from __future__ import annotations

import re

__all__ = ["exact_literal", "exact_span"]


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

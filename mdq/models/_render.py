"""
Auxiliary helpers to implement the `render()` methods of the models in this
package.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any, Iterable

import yaml

if TYPE_CHECKING:
    from . import _base, _choice


def yield_frontmatter(
    data: dict[str, Any], comment: str | None = None
) -> Iterable[str]:
    """
    Yield lines of the frontmatter as strings.
    """
    if not data and not comment:
        return

    yield "---"
    if comment:
        for line in comment.splitlines():
            yield f"# {line}"

    with io.StringIO() as buf:
        yaml.dump(data, buf)
        dump = buf.getvalue().rstrip()
        if dump and dump != "{}":
            yield dump
    yield "---"


def yield_introduction(
    model: _base.BaseQuestion, id: str | None = None
) -> Iterable[str]:
    """
    Yield lines of the introductory sections (preamble, stem) as strings.

    The `id` is passed to `mdq.models._render.yield_introduction()`.
    """

    if model.preamble:
        if id is not None:
            yield f"[{id}] {model.preamble}"
            id = None
        else:
            yield model.preamble
        if model.stem:
            yield ""

    if id is not None:
        yield f"[{id}] {model.stem}"
    else:
        yield model.stem


def yield_conclusion(
    model: _base.BaseQuestion, skip_line: bool = False
) -> Iterable[str]:
    """
    Yield lines of the concluding sections (epilogue) as strings.

    The `**kwargs` are passed to `mdq.models._render.render()`.
    """
    if model.epilogue:
        if skip_line:
            yield ""
        yield model.epilogue


def yield_ordering_content(
    lines: Iterable[tuple[int, str]], content: str, highlight: str | None
) -> Iterable[str]:
    """
    Yield an ordering question's content block: a fenced code block for
    `content == "code"`, a `ul` list otherwise.

    A line's indentation is `level * 4` spaces in a code block and
    `level * 2` spaces before the `* ` marker in a `ul`. A blank line
    carries no indentation of its own, regardless of its level.
    """
    if content == "code":
        yield f"```{highlight}" if highlight else "```"
        for level, text in lines:
            yield f"{' ' * (level * 4)}{text}" if text else ""
        yield "```"
    else:
        for level, text in lines:
            yield f"{' ' * (level * 2)}* {text}"


def yield_ordering_section(
    tag: str,
    lines: Iterable[tuple[int, str]],
    content: str,
    highlight: str | None,
    feedback: str | None = None,
    comment: str | None = None,
) -> Iterable[str]:
    """
    Yield an ordering `## [extra]`/`## [accept]`/`## [reject]` section.

    Observations, when either is present, render feedback (`> `) before
    comment (`! `), each block separated by a blank line -- the spec
    allows either order, this is the canonical one.
    """
    yield ""
    yield f"## [{tag}]"
    if feedback or comment:
        yield ""
        if feedback:
            for line in feedback.splitlines():
                yield f"> {line}"
        if feedback and comment:
            yield ""
        if comment:
            for line in comment.splitlines():
                yield f"! {line}"
        yield ""
    yield from yield_ordering_content(lines, content, highlight)


def yield_choice(
    choice: _choice.ScoredChoice | _choice.BooleanChoice | _choice.Statement, mark: str
):
    """
    Yield lines of a choice as strings.
    """
    text_lines = iter(choice.text.splitlines())
    yield f"* [{mark}] {next(text_lines)}"
    for line in text_lines:
        yield f"  {line}"

    if choice.feedback:
        for line in choice.feedback.splitlines():
            yield f"  > {line}"

    if choice.comment:
        for line in choice.comment.splitlines():
            yield f"  ! {line}"

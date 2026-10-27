"""
`[ordering]` body parsing: turning the raw `(indent, text)` lines of an
`[ordering]`/`[extra]`/`[accept]`/`[reject]` block into the leveled
`[level, text]` pairs the schema expects, once the indentation unit has
been inferred across the whole question (ordering.md#indentation).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import NamedTuple

from markdown_it.common.utils import unescapeAll
from markdown_it.tree import SyntaxTreeNode as Node

from .._markdown import span, starts_after
from ..errors import ParseError
from ..types import OrderingAlternativeDict
from ._blocks import BLOCK_NAMES, BlockCursor, BlockReader
from ._choices import parse_observations
from ._frontmatter import _normalize_list
from ._tags import OrderingTag

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


def check_ordering_tag(tag: OrderingTag) -> None:
    """
    Raise a `ParseError` unless `tag` is `[ordering]:` alone: the tag
    has a colon and no text after it (question-base.md, "Body tags").
    """
    if tag.rest is None:
        raise ParseError(
            "the tag of an ordering question is `[ordering]:`, with a colon; "
            "the code block or list follows on the next line"
        )
    if tag.rest:
        raise ParseError(
            "the line of `[ordering]:` has no text after the colon; the "
            "code block or list starts on the next line"
        )


def parse_ordering_body(
    cursor: BlockCursor, front: Mapping[str, object], tag_node: Node
) -> tuple[dict[str, object], list[Node]]:
    """
    Fill `lines`, `extra`, `accept` and `reject` from an `[ordering]`
    block and its `## [extra]`/`## [accept]`/`## [reject]` sections.

    The optional epilogue sits between the content block and the
    first section; the sections are contiguous after it and nothing
    follows the last one.

    The indentation unit is inferred once across every block of the
    question (ordering.md#indentation), so every block is read raw
    first and only converted to `[level, text]` pairs at the end.
    `content` and `highlight` always come from the body (a code
    fence implies `code` and its language, a list implies `text`);
    the frontmatter cannot declare them.

    Args:
        tag_node: the `[ordering]` tag paragraph; the content block
            must start on the line right after it.

    Raises:
        ParseError: the block after `[ordering]` (or a section) is
            neither a fenced code block nor a `ul` list, a blank
            line separates `[ordering]` from its block, a section
            has no content block, a section's
            content is not the same kind as `[ordering]`'s or its
            fence names another language than the `[ordering]` fence, two
            `## [extra]` sections are declared, or a section's
            observations carry more than one feedback/comment block
            or interleave the two, or a block that is not a section
            follows the first section.

    Returns:
        The epilogue nodes, between the content block and the first
        section.
    """
    main_kind, main_highlight, main_raw = parse_ordering_content(cursor, 
        tag_node=tag_node
    )

    first_section = next(
        (
            i
            for i in range(cursor.pos, len(cursor.reader.children))
            if is_ordering_section(cursor.reader, cursor.reader.children[i])
        ),
        len(cursor.reader.children),
    )
    epilogue_nodes = cursor.reader.children[cursor.pos : first_section]
    cursor.pos = first_section

    extra_raw: list[RawLine] | None = None
    accept_raw: list[RawAlternative] = []
    reject_raw: list[RawAlternative] = []

    while True:
        node = cursor.peek()
        if node is None or node.type != "heading" or node.tag != "h2":
            break
        m = ORDERING_SECTION_RE.match(cursor.reader.raw_text(node))
        if m is None:
            break
        cursor.read()
        name = m.group("name")
        if name == "extra":
            if extra_raw is not None:
                raise ParseError("a question defines at most one [extra] section")
            kind, highlight, extra_raw = parse_ordering_content(cursor, section=name)
            if kind != main_kind:
                raise ParseError(
                    "[extra] must use the same content type as [ordering]"
                )
            check_section_highlight(name, highlight, main_highlight)
        else:
            feedback, comment = parse_ordering_observations(cursor)
            kind, highlight, raw = parse_ordering_content(cursor, section=name)
            if kind != main_kind:
                raise ParseError(
                    f"[{name}] must use the same content type as [ordering]"
                )
            check_section_highlight(name, highlight, main_highlight)
            target = accept_raw if name == "accept" else reject_raw
            target.append(RawAlternative(raw, feedback, comment))

    if cursor.pos < len(cursor.reader.children):
        raise ParseError(
            "only [extra], [accept] and [reject] sections can follow the "
            "first section; the epilogue goes before it",
            cursor.reader.children[cursor.pos],
        )

    # A `ul` line already holds its nesting depth: no unit applies.
    unit = (
        1
        if main_kind == "text"
        else ordering_unit(
            [indent for indent, _ in main_raw]
            + [indent for indent, _ in (extra_raw or [])]
            + [
                indent
                for alt in (*accept_raw, *reject_raw)
                for indent, _ in alt.lines
            ]
        )
    )

    doc: dict[str, object] = {}
    doc["content"] = main_kind
    if main_highlight:
        doc["highlight"] = main_highlight
    if front.get("normalizations") is not None:
        doc["normalizations"] = _normalize_list(front["normalizations"])

    doc["lines"] = ordering_leveled(main_raw, unit)
    if extra_raw is not None:
        doc["extra"] = ordering_leveled(extra_raw, unit)
    if accept_raw:
        doc["accept"] = [ordering_alternative(alt, unit) for alt in accept_raw]
    if reject_raw:
        doc["reject"] = [ordering_alternative(alt, unit) for alt in reject_raw]
    return doc, epilogue_nodes


def check_section_highlight(
    name: str, highlight: str | None, main_highlight: str | None
) -> None:
    """
    A section's fence MUST name the language of the `[ordering]` fence
    or none, which inherits it (ordering.md#body).

    Raises:
        ParseError: the section's fence names another language.
    """
    if highlight is not None and highlight != main_highlight:
        raise ParseError(
            f"the fence of [{name}] must use the language of the [ordering] "
            f"fence ({main_highlight or 'none'}) or none, found {highlight!r}"
        )


def is_ordering_section(reader: BlockReader, node: Node) -> bool:
    """Whether `node` is an `## [extra]`, `## [accept]` or `## [reject]` heading."""
    return (
        node.type == "heading"
        and node.tag == "h2"
        and ORDERING_SECTION_RE.match(reader.raw_text(node)) is not None
    )


def parse_ordering_content(
    cursor: BlockCursor, *, tag_node: Node | None = None, section: str | None = None
) -> tuple[str, str | None, list[RawLine]]:
    """
    Read the fenced code block or `ul` list holding one content
    block's raw `(indent, text)` lines, along with the content kind
    and highlight language it implies.

    Args:
        tag_node: the `[ordering]` tag paragraph, when reading the
            main block: the block must start on the next line.
        section: the name of the `extra`/`accept`/`reject` section
            whose block is read, when reading a section.

    Raises:
        ParseError: the current node is neither a fence nor a
            bullet list, or a blank line separates the main block
            from its tag.
    """
    node = cursor.peek()
    if node is None or node.type not in ("fence", "bullet_list"):
        if section is not None:
            raise ParseError(
                f"the ## [{section}] section has no content block", node
            )
        raise ParseError(
            "an [ordering] block must be followed by a code block or a list",
            node,
        )
    if (
        tag_node is not None and not starts_after(tag_node, node)
    ):
        raise ParseError(
            "the content of [ordering]: must start on the line right after "
            "the tag, with no blank line in between",
            node,
        )
    cursor.read()
    if node.type == "bullet_list":
        cursor.check_no_adjacent_list(node)
    if node.type == "fence":
        return "code", fence_language(node.info), ordering_code_lines(node.content)
    check_ordering_item_blocks(cursor.reader, node)
    depths: dict[int, int] = {}
    parents: set[int] = set()
    collect_item_depths(node, 0, depths, parents)
    first_line = span(node)[0]
    return (
        "text",
        None,
        ordering_ul_lines(cursor.reader.raw_lines(node), depths, first_line, parents),
    )


def check_ordering_item_blocks(reader: BlockReader, node: Node) -> None:
    """
    Raise a `ParseError` if an item of the `ul` block `node`, at any
    depth, holds a block that is neither a paragraph nor a nested list:
    indented code, a heading, a block quote, a fence, an HTML block or
    a thematic break (ordering.md, "Body"). An item is one paragraph.
    """
    for item in node.children:
        if item.type != "list_item":
            continue
        for child in item.children:
            if child.type in ("bullet_list", "ordered_list"):
                check_ordering_item_blocks(reader, child)
            elif child.type != "paragraph":
                line = reader.raw_lines(item)[0].strip(" \t")
                raise ParseError(
                    f"an ordering item is one paragraph, but the item "
                    f"{line!r} holds a "
                    f"{BLOCK_NAMES.get(child.type, child.type)}",
                    item,
                )


def parse_ordering_observations(cursor: BlockCursor) -> tuple[str | None, str | None]:
    """
    Consume an accept/reject section's optional feedback (`>`) and
    comment (`!`) blocks, in either order (ordering.md,
    "Accepted/rejected answers").

    The blocks are read from the raw lines, not from the markdown
    nodes: with no blank line between them, CommonMark folds a `!`
    line into the blockquote before it as a lazy continuation, which
    the grammar does not do.

    Raises:
        ParseError: a section carries more than one feedback or
            comment block, or a line that is not part of one.
    """
    first: Node | None = None
    last: Node | None = None
    while True:
        node = cursor.peek()
        if node is None:
            break
        if node.type == "blockquote" or (
            node.type == "paragraph" and is_comment_block(cursor.reader.raw_lines(node)[:1])
        ):
            if first is None:
                first = node
            last = node
            cursor.read()
        else:
            break
    if first is None or last is None:
        return None, None
    return parse_observations(cursor.reader.lines[span(first)[0] : span(last)[1]])

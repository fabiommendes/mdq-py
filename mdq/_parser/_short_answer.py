"""
The body of a short-answer question, and the pattern blocks that the
short-answer blanks of a fill-in question share with it.
"""

from __future__ import annotations

from collections.abc import Mapping

from markdown_it.tree import SyntaxTreeNode as Node

from .._diagnostics import Diagnostic
from .._exact import exact_literal, join_pattern_lines
from .._markdown import starts_after
from ..errors import ParseError
from ..types import PatternEntry
from ._blocks import BLOCK_NAMES, BlockCursor, BlockReader, parse_plain_item
from ._choices import CODE_INDENT, _pattern_entry, indentation
from ._frontmatter import _copy_pattern_lists
from ._tags import SHORT_ANSWER_RE, TAG_REST_RE, ShortAnswerTag, read_short_answer_tag


def parse_short_answer_body(
    cursor: BlockCursor,
    front: Mapping[str, object],
    tag: ShortAnswerTag,
    tag_node: Node,
) -> dict[str, object]:
    """
    Read the short-answer fields from a run of `[short-answer...]` blocks.

    `[short-answer]` (alias `[short-answer/accept]`) gives `accept` and
    `[short-answer/reject]` gives `reject`, in any order and at most
    once each. `[short-answer]` without a colon is a block with no
    pattern (question-base.md, "Body tags").

    Raises:
        ParseError: a block is repeated (the two accept spellings
            count as one block), a block has a pattern and a list, a
            tag with a colon has no content or a blank line separates
            it from its list, or a reject tag has no colon.
    """
    doc: dict[str, object] = {}
    for key in ("diacritics", "unmatched", "incorrectFeedback"):
        if key in front:
            doc[key] = front[key]

    seen: set[str] = set()
    while True:
        if tag.role in seen:
            raise ParseError(f"repeated [short-answer] {tag.role} block")
        seen.add(tag.role)
        patterns = parse_answer_block(cursor, 
            tag_node,
            tag.rest,
            reject=tag.role == "reject",
            tag="short-answer",
            path=(tag.role,),
        )
        if patterns:
            doc[tag.role] = patterns

        node = cursor.peek()
        cursor.reader.check_no_setext_tag(node, SHORT_ANSWER_RE)
        if node is None or node.type != "paragraph":
            break
        next_tag = read_short_answer_tag(cursor.reader.raw_text(node))
        if next_tag is None:
            break
        tag = next_tag
        tag_node = cursor.read()

    _copy_pattern_lists(front, doc)
    return doc


def _join_content_lines(reader: BlockReader, tag_node: Node, rest: str) -> str:
    """
    The content of a short-answer tag: the text after the colon and the
    continuation lines, joined with one U+0020 each. A line ending and
    the indentation of the next line become that space
    (docs/references/patterns.md, "Continuation lines"). `rest` is the
    text `raw_text` gave, whose line endings already are spaces.
    """
    lines = reader.raw_lines(tag_node)
    if len(lines) < 2:
        return rest.strip(" \t")
    first = TAG_REST_RE.match(lines[0])
    assert first is not None  # the caller matched a tag
    return join_pattern_lines([first.group("rest"), *lines[1:]])


def _warn_multi_line_pattern(
    diagnostics: list[Diagnostic], path: tuple[str | int, ...], pattern: str, lines: int
) -> None:
    """
    Report an exact literal or a regex of the body that spans more than
    one line: the line ending becomes a significant U+0020
    (patterns.md, "Continuation lines").
    """
    if lines > 1 and pattern.startswith(("`", "/")):
        diagnostics.append(
            Diagnostic(
                severity="warning",
                code="multi-line-pattern",
                path=path,
                message=(
                    "an exact literal or a regex spans more than one line, so "
                    "each line ending becomes a space that is part of the "
                    f"pattern: write it on one line: {pattern!r}"
                ),
            )
        )


def parse_answer_block(
    cursor: BlockCursor,
    tag_node: Node,
    rest: str | None,
    *,
    reject: bool,
    tag: str,
    path: tuple[str | int, ...],
) -> list[PatternEntry]:
    """
    Read the patterns of one short-answer tag: the text on its line,
    or the list on the lines right after it.

    Args:
        tag_node: the paragraph of the tag.
        rest: the text after the colon, or `None` for a tag without a
            colon.
        reject: whether the tag is a `reject` tag.
        tag: the tag without brackets (`short-answer` or
            `^id/short-answer`), for the messages.
        path: the path of the pattern list in the document, for the
            `multi-line-pattern` warning.

    Returns:
        The patterns. Empty for a tag without a colon.

    Raises:
        ParseError: the tag has text and an attached list; a tag with a
            colon has no text and no list on the next line (a blank
            line before the list included); a tag without a colon is a
            `reject` tag, or has a list on the next line.
    """
    if rest is None:
        return _bare_answer_block(cursor, tag_node, reject=reject, tag=tag)
    rest = _join_content_lines(cursor.reader, tag_node, rest)
    # The tag paragraph also holds the lazy continuation lines of the
    # content. A `!` line is not lazy (a comment), so it is an error.
    for line in cursor.reader.raw_lines(tag_node)[1:]:
        if _is_comment_line(line):
            raise ParseError(_OBSERVATION_AFTER_CONTENT)
    node = cursor.peek()
    if (
        node is not None
        and node.type == "blockquote"
        and starts_after(tag_node, node)
    ):
        raise ParseError(_OBSERVATION_AFTER_CONTENT)
    attached = (
        node is not None
        and node.type == "bullet_list"
        and starts_after(tag_node, node)
    )
    if not rest:
        if not attached:
            raise ParseError(_empty_answer_tag_message(tag, reject=reject))
    elif attached:
        raise ParseError(
            f"a [{tag}] tag with a pattern on its line cannot be followed by a list"
        )
    if not attached:
        check_exact_pattern(rest)
        tag_line, *other_lines = cursor.reader.raw_lines(tag_node)
        first = TAG_REST_RE.match(tag_line)
        content_lines = [first.group("rest") if first else "", *other_lines]
        _warn_multi_line_pattern(cursor.diagnostics, 
            (*path, 0), rest, sum(1 for line in content_lines if line.strip(" \t"))
        )
        return [rest]
    assert node is not None
    cursor.read()
    cursor.check_no_adjacent_list(node)
    for item in node.children:
        cursor.reader.check_no_setext_item(item)
        check_pattern_item_paragraph(cursor.reader, item)
    raw_items = [parse_plain_item(cursor.reader.item_lines(item)) for item in node.children]
    entries = [_pattern_entry(item) for item in raw_items]
    for index, (entry, raw_item) in enumerate(zip(entries, raw_items)):
        pattern = entry if isinstance(entry, str) else entry["pattern"]
        check_exact_pattern(pattern)
        _warn_multi_line_pattern(cursor.diagnostics, (*path, index), pattern, raw_item.text_lines)
    return entries


def _bare_answer_block(
    cursor: BlockCursor, tag_node: Node, *, reject: bool, tag: str
) -> list[PatternEntry]:
    """
    Check a short-answer tag written without a colon. It has no
    content, so it is no `reject` tag (that one needs patterns) and no
    list starts on the line after it (the colon is missing).
    """
    if reject:
        raise ParseError(
            f"[{tag}/reject] needs patterns: write `[{tag}/reject]:` "
            "followed by a pattern or a list"
        )
    node = cursor.peek()
    adjacent = node is not None and starts_after(tag_node, node)
    if adjacent and node is not None and node.type == "bullet_list":
        raise ParseError(
            f"[{tag}] without a colon has no content: write `[{tag}]:` "
            "before a list of patterns"
        )
    if adjacent and node is not None and node.type == "blockquote":
        raise ParseError(
            f"a line that starts with '>' cannot follow [{tag}] without a "
            f"colon: it would be feedback for no pattern; write `[{tag}]:` "
            "with a pattern or a list, or leave a blank line before the "
            "epilogue"
        )
    return []


def check_pattern_item_paragraph(reader: BlockReader, item: Node) -> None:
    """
    Raise a `ParseError` if the content of the pattern item `item` starts
    with a block that is not a paragraph in CommonMark: a block quote, a
    heading, a list, a fenced or indented code block, an HTML block or a
    thematic break (patterns.md, "Pattern items").
    """
    if not item.children or item.children[0].type == "paragraph":
        return
    line = reader.item_lines(item)[0].strip(" \t")
    raise ParseError(
        f"the pattern line {line!r} starts a block of its own "
        f"({BLOCK_NAMES.get(item.children[0].type, item.children[0].type)}) "
        f"in markdown, so it is not a pattern: write an exact literal "
        f"instead, e.g. `{line}`"
    )


def check_exact_pattern(pattern: str) -> None:
    """
    Raise a `ParseError` if `pattern`, a pattern of the Markdown body, opens
    with a backtick and is not a complete exact literal (patterns.md, "Exact
    literals"). A literal that opens at the end of a line, or whose closing
    run starts a continuation line, holds a line feed after the join of the
    lines. The form of the YAML, JSON and frontmatter has no line ending and
    stays a `schema-error`.
    """
    if not pattern.startswith("`"):
        return
    if "\n" in pattern:
        raise ParseError(
            f"an exact literal cannot open at the end of a line, nor close at "
            f"the start of a line: {' '.join(pattern.split())!r}"
        )
    if exact_literal(pattern) is None:
        raise ParseError(
            f"a pattern that opens with a backtick must be a complete exact "
            f"literal: {pattern!r}"
        )


_OBSERVATION_AFTER_CONTENT = (
    "a line that starts with '>' or '!' cannot follow the content of a "
    "short answer tag; use the list form ('* pattern' with the '>' or '!' "
    "lines indented under it)"
)


def _empty_answer_tag_message(tag: str, *, reject: bool) -> str:
    """The error for a short-answer tag with a colon and no content."""
    if reject:
        return (
            f"[{tag}/reject]: has no pattern: write it on the same line "
            "or in a list on the line right after the tag"
        )
    return (
        f"[{tag}]: has no content: write the answer on the same line or in a "
        "list on the line right after the tag, with no blank line in between, "
        f"or use `[{tag}]` for a manual question"
    )


def _is_comment_line(line: str) -> bool:
    """
    Whether `line` starts a comment: `!` but not an image, `![`, with up to
    three columns of indentation. With four or more, it is continuation text.
    """
    if indentation(line) >= CODE_INDENT:
        return False
    stripped = line.lstrip(" \t")
    return stripped.startswith("!") and not stripped.startswith("![")

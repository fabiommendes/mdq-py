"""
The top-level blocks of a Markdown text (`BlockReader`) and the field
helpers built on them: the reconstruction of the text of a block and the
checks of the `stem`, `epilogue` and `answerKey` fields shared with
`mdq.models`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode as Node

from .._markdown import md, span, split_lines
from ._choices import (
    CODE_INDENT,
    LINK_START_RE,
    dedent,
    indentation,
    is_choice_value,
    match_choice_marker,
)
from ._tags import is_reserved_label, tag_lines

# The markers around the text of an ATX heading.
ATX_OPENING_RE = re.compile(r"^[ \t]*#{1,6}")
ATX_CLOSING_RE = re.compile(r"(?:[ \t]+#+)?[ \t]*$")
#: Reads link reference definitions, which `md` leaves as paragraphs.
_REFERENCE_MD = MarkdownIt("commonmark")


#: Readable names of the blocks that can start a pattern or an ordering item.
BLOCK_NAMES = {
    "blockquote": "block quote",
    "heading": "heading",
    "bullet_list": "list",
    "ordered_list": "list",
    "fence": "fenced code block",
    "code_block": "code block",
    "html_block": "HTML block",
    "hr": "thematic break",
}


def setext_message(text: str) -> str:
    """The error for a line of `text` that a setext underline turned into a heading."""
    return (
        f"the line {text!r} became a setext heading because the next line is "
        "'---' or '==='; add a blank line between them"
    )


@dataclass(frozen=True)
class BlockReader:
    """
    The top-level blocks of a Markdown text, with the helpers that
    rebuild their source text.

    The text is read as is: a leading `---` is a thematic break, not a
    frontmatter. `MDQParser` splits the frontmatter off first and reads
    the body; the field helpers read a `stem`, `epilogue` or `answerKey`
    field.

    Attributes:
        text: The Markdown source.
        children: The top-level markdown-it block nodes.
        lines: The raw source lines, indexed by `node.map`.
    """

    text: str

    @cached_property
    def children(self) -> list[Node]:
        return list(Node(md.parse(self.text)).children)

    @cached_property
    def lines(self) -> list[str]:
        return split_lines(self.text)

    def raw_lines(self, node: Node) -> list[str]:
        start, end = span(node)
        return self.lines[start:end]

    def inline_source(self, node: Node) -> str | None:
        """
        The source text of a paragraph or an ATX heading, before
        markdown-it trims it.

        Only the text of the block itself: the `#` markers and the closing
        sequence of a heading are removed. `None` for other blocks.
        """
        lines = self.raw_lines(node)
        if not lines:
            return None
        if node.type == "paragraph":
            return "\n".join(lines)
        if node.type == "heading" and node.markup.startswith("#"):
            return ATX_CLOSING_RE.sub("", ATX_OPENING_RE.sub("", lines[0]))
        return None

    def raw_text(self, node: Node) -> str:
        """
        Reconstruct a block's text like the original source.

        Prefer the block's inline child's `.content`: it is markdown-it's
        own raw-source text for the block with the block-level markup
        (heading `#`s, list markers, blockquote `>`s) already peeled off,
        which is more reliable than re-slicing lines ourselves for
        anything but a plain paragraph.
        """

        if node.children and node.children[0].type == "inline":
            content = node.children[0].content
            source = self.inline_source(node)
            if source is not None:
                content = _restore_trimmed(content, source)
            return _join_soft_breaks(content)
        lines = self.raw_lines(node)
        # markdown-it's `.map` for a list (bullet or ordered) that is not
        # the last block in the document extends one line past the list's
        # own content, into the blank line that follows it -- see the
        # module docstring's note on trusting `.map` for line ranges.
        # Trailing blank lines are never part of a block's own content, so
        # dropping them is always correct, not just for lists -- verified
        # this is a no-op (never trims real content) for a fenced code
        # block, whose `.map` always ends on its own closing ` ``` ` line,
        # and for an indented code block, whose `.map` always ends on its
        # last indented line, even when either has a blank line before
        # the end of its own body.
        # CommonMark treats only spaces and tabs as blank, not Unicode
        # whitespace such as NBSP.
        while lines and not lines[-1].strip(" \t"):
            lines.pop()
        return "\n".join(lines)

    def block_text(self, node: Node) -> str:
        """
        A block's text as it reads in a `stem`, `epilogue` or
        `answerKey` field: `raw_text`, plus the `#` markers of an ATX
        heading, which stay part of the field so a heading is still a
        heading when the field is parsed again.
        """
        text = self.raw_text(node)
        if node.type == "heading" and node.markup.startswith("#"):
            return f"{node.markup} {text}"
        return text

    def join_blocks(self, nodes: list[Node]) -> str | None:
        if not nodes:
            return None
        return "\n\n".join(self.block_text(n) for n in nodes)

    def item_lines(self, item: Node) -> list[str]:
        """
        The content lines of a list item, as CommonMark gives them
        (grammar.md, "Content of a list item"): the first line without the
        list marker and its padding, the other lines without the
        indentation of the item content. Trailing blank lines are dropped.

        The content column comes from markdown-it (`meta["indent"]`, see
        `mdq._markdown`). An empty first line has none: CommonMark then
        puts the content one column after the marker.
        """
        lines = self.raw_lines(item)
        while lines and not lines[-1].strip(" \t"):
            lines.pop()
        if not lines:
            return [""]
        first = lines[0]
        marker = len(first) - len(first.lstrip(" \t"))
        first = first[:marker] + " " + first[marker + 1 :]
        column = item.meta.get("indent")
        if column is None:
            column = indentation(lines[0]) + 2
        return [dedent(first, column)] + [dedent(line, column) for line in lines[1:]]


#
# Block reconstruction, shared with mdq.models
#
def reconstruct_blocks(src: str) -> list[tuple[str, str]]:
    """
    Parse `src` as a standalone sequence of top-level Markdown blocks and
    reconstruct each one exactly as it would read after being embedded in
    a full MDQ document and parsed back out.

    This is `BlockReader.raw_text`, applied to every top-level block `src`
    parses into: a plain paragraph's soft-wrapped lines collapse to
    single spaces, while a list, blockquote, heading or code block is
    reproduced byte-for-byte. It exists so `mdq.models` can canonicalize
    a `stem`/`epilogue` field into the fixed point a
    render-then-parse round trip actually produces, using the parser's
    own reconstruction rules instead of a second, drifting copy of them.

    Args:
        src: Markdown source for a stem or epilogue -- a
            sequence of block elements with no YAML frontmatter of its
            own. A leading `---` is a thematic break.

    Returns:
        One `(node_type, text)` pair per top-level block found in `src`,
        in source order.
    """
    reader = BlockReader(src)
    return [(node.type, reader.block_text(node)) for node in reader.children]


def _join_soft_breaks(content: str) -> str:
    """
    Join the soft line breaks of a paragraph into one space.

    A hard break (two or more spaces, or an unescaped `\\`, before the
    line ending) is kept byte for byte, line ending included
    (question-base.md, "Stem").
    """
    lines = content.split("\n")
    out = lines[0]
    for line in lines[1:]:
        trailing_backslashes = len(out) - len(out.rstrip("\\"))
        hard = out.endswith("  ") or trailing_backslashes % 2 == 1
        out += ("\n" if hard else " ") + line
    return out


def _restore_trimmed(content: str, source: str) -> str:
    """
    Put back the Unicode spaces that markdown-it trimmed from `content`.

    markdown-it trims a paragraph or a heading with `str.strip()`, which
    also removes Unicode spaces such as U+00A0. CommonMark and
    docs/references/grammar.md trim only spaces, tabs and line endings,
    so these characters are text and stay in the block.

    Args:
        content: The trimmed text that markdown-it gives for the block.
        source: The source text of the same block.

    Returns:
        `content`, with the Unicode spaces at the start and at the end of
        `source` put back.
    """
    inner = source.strip(" \t\r\n")
    if not inner.strip():
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()) :]
    return lead + content + trail


def _starts_with_bracket(text: str) -> bool:
    """
    Whether `text` starts with optional `ws` and a `[` that does not start
    a markdown link (question-base.md, "Forbidden elements").
    """
    stripped = text.lstrip(" \t")
    return stripped.startswith("[") and not LINK_START_RE.match(stripped)


def _after_reference_definitions(src: str) -> str:
    """
    The text of the paragraph `src` after its leading CommonMark link
    reference definitions (`[inpe]: https://www.inpe.br`), or an empty
    string when the paragraph holds only definitions.

    `md` does not read definitions, so that MDQ tags such as
    `[numeric]: 42` stay paragraphs; `_REFERENCE_MD` does.
    """
    for token in _REFERENCE_MD.parse(src):
        if token.type == "inline":
            return token.content
    return ""


def find_forbidden_elements(
    src: str, *, allow_first_paragraph_bracket: bool = False
) -> list[str]:
    """
    base.md, "Forbidden elements": return a human-readable description of
    every forbidden top-level block construct in `src` -- a stem
    or epilogue field, checked on its own.

    The forbidden constructs are: an H1 heading; a heading starting with
    optional whitespace and `[`; an unordered list whose items all start
    with optional whitespace and `[`; and a paragraph starting with
    optional whitespace and `[`, unless it is immediately followed by
    `^` (the fill-in blank marker syntax) or -- see
    `allow_first_paragraph_bracket` -- it is `src`'s own first block (the
    slug syntax, base.md "Slug"). A `[` that starts a markdown link
    (`[text](url)`, `[text][ref]`) does not count, and neither does a
    paragraph of CommonMark link reference definitions
    (`[inpe]: https://www.inpe.br`) with no reserved tag label.

    Args:
        src: Markdown source for one field -- no YAML frontmatter.
        allow_first_paragraph_bracket: Exempt a leading `[...]` paragraph
            as a possible slug. Only the stem's own first block
            qualifies -- pass `True` for the stem, `False` for the
            epilogue, which is never that first block.

    Returns:
        One description per forbidden block found, in source order.
        Empty when `src` is blank or holds nothing forbidden.
    """
    if not src.strip():
        return []

    reader = BlockReader(src)
    forbidden: list[str] = []
    for index, node in enumerate(reader.children):
        if node.type == "heading":
            if node.tag == "h1":
                forbidden.append("an H1 heading")
            elif _starts_with_bracket(reader.raw_text(node)):
                forbidden.append("a heading starting with '['")
            continue

        if node.type == "bullet_list" and all(
            indentation(first := reader.item_lines(item)[0]) < CODE_INDENT
            and _starts_with_bracket(first)
            for item in node.children
        ):
            forbidden.append("an unordered list whose items all start with '['")
            continue

        if node.type == "paragraph":
            text = reader.raw_text(node)
            stripped = text.lstrip(" \t")
            if not _starts_with_bracket(stripped):
                continue
            has_tag = any(
                is_reserved_label(label)
                for label, _ in tag_lines(text, reader.raw_lines(node))
            )
            if not has_tag and not _starts_with_bracket(
                _after_reference_definitions("\n".join(reader.raw_lines(node)))
            ):
                continue
            if stripped.startswith("[^"):
                continue
            if index == 0 and allow_first_paragraph_bracket:
                continue
            forbidden.append("a paragraph starting with '['")

    return forbidden


def find_answer_key_forbidden_elements(src: str) -> list[str]:
    """
    essay.md, "Answer key": the section holds every block except an H1
    heading. Return one description per H1 heading (ATX or setext) in
    `src`, an `answerKey` field checked on its own, in source order.
    """
    if not src.strip():
        return []
    reader = BlockReader(src)
    return [
        "an H1 heading"
        for node in reader.children
        if node.type == "heading" and node.tag == "h1"
    ]


def find_stray_choice_markers(src: str) -> list[str]:
    """
    question-base.md, "Forbidden elements": return the choice marker of
    every stray item in `src`, a stem or epilogue field.

    A stray item belongs to a top-level unordered list in which some
    items, but not all, start with a choice marker, and its marker holds
    the value of a choice type or is empty (`is_choice_value`). Such a
    list is valid prose, but it is almost always a broken choice list.

    Args:
        src: Markdown source for one field -- no YAML frontmatter.

    Returns:
        The marker of each stray item, such as `[x]`, in source order.
    """
    if not src.strip():
        return []
    reader = BlockReader(src)
    stray: list[str] = []
    for node in reader.children:
        if node.type != "bullet_list":
            continue
        markers = [
            match_choice_marker(reader.item_lines(item)[0]) for item in node.children
        ]
        if all(m is not None for m in markers):
            continue
        stray.extend(
            m.group(0)
            for m in markers
            if m is not None and is_choice_value(m.group("value"))
        )
    return stray

"""
The `## [attachments]` section (question-base.md, "Attachments") and the
helpers that the sections of a question share: the heading of a section, the
split of the blocks into sections, and the paragraph with one link that both
`## [tests]` and `## [attachments]` read.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from markdown_it import MarkdownIt
from markdown_it.common.utils import unescapeAll
from markdown_it.token import Token
from markdown_it.tree import SyntaxTreeNode as Node

from .._markdown import UNICODE_SPACE, has_visible_character
from ..errors import ParseError
from ..types import AttachmentDict
from ._blocks import BLOCK_NAMES, BlockCursor, BlockReader

__all__ = [
    "ATTACHMENTS",
    "Section",
    "link_paragraph",
    "parse_attachments",
    "section_name",
    "split_sections",
]

#: The name of the section that every question type and the exam have.
ATTACHMENTS = "attachments"

#: The text of the heading of a section: `[name]` alone.
_SECTION_RE = re.compile(r"^\[(?P<name>[^\[\]]+)\]$")

#: The `ORIGIN` terminal of docs/question-types/code.md, after the reading
#: of the destination of the link.
ORIGIN_RE = re.compile(r"(?![A-Za-z][A-Za-z0-9+.-]*:)(?!/)[^?#]*[.][^.\/?#]+")
_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")

#: A character that a name of an attachment cannot have, besides `/` and `\`.
_NAME_FORBIDDEN_RE = re.compile(rf"[{UNICODE_SPACE}`]")


class _RawLinkMarkdownIt(MarkdownIt):
    """
    Reads a paragraph as CommonMark does, keeping the destination of a link
    as the author wrote it. `normalizeLink` would percent-encode it, and the
    origin is an opaque key: MDQ does not decode or encode it.
    """

    def normalizeLink(self, url: str) -> str:
        return url


_LINK_MD = _RawLinkMarkdownIt("commonmark")
_LINK_MD.block.ruler.disable("reference")


class Section(NamedTuple):
    """One section of a question: its name, its heading and its blocks."""

    name: str
    heading: Node
    blocks: list[Node]


def section_name(reader: BlockReader, node: Node, names: frozenset[str]) -> str | None:
    """
    The name of the section that `node` opens, if it is the H2 heading (ATX
    or setext) of a section in `names`, else `None`. An escaped heading,
    `## \\[name]`, opens no section.
    """
    if node.type != "heading" or node.tag != "h2":
        return None
    found = _SECTION_RE.match(reader.raw_text(node))
    if found is None or found.group("name") not in names:
        return None
    return found.group("name")


def split_sections(
    cursor: BlockCursor, names: frozenset[str]
) -> tuple[list[Node], list[Section]]:
    """
    Read the rest of a question as an epilogue and a sequence of sections.

    The epilogue holds the blocks before the first heading of a section in
    `names`. Each section holds the blocks up to the next such heading or
    the end of the question. The cursor ends at the end of the question.

    Raises:
        ParseError: a section is declared twice.
    """
    reader = cursor.reader
    epilogue: list[Node] = []
    while (node := cursor.peek()) is not None and section_name(reader, node, names) is None:
        epilogue.append(cursor.read())
    sections: list[Section] = []
    seen: set[str] = set()
    while (heading := cursor.peek()) is not None:
        name = section_name(reader, heading, names)
        assert name is not None  # the loop reads whole sections
        if name in seen:
            raise ParseError(f"the ## [{name}] section is declared at most once", heading)
        seen.add(name)
        cursor.read()
        blocks: list[Node] = []
        while (block := cursor.peek()) is not None and section_name(reader, block, names) is None:
            blocks.append(cursor.read())
        sections.append(Section(name, heading, blocks))
    return epilogue, sections


def link_paragraph(reader: BlockReader, node: Node, message: str) -> tuple[str, list[Token]]:
    """
    The origin and the inline tokens of the text of a paragraph whose only
    content is an inline link (code.md, "Test sources").

    Args:
        reader: The blocks of the question.
        node: The paragraph.
        message: The error when the paragraph is not one inline link.

    Raises:
        ParseError: the paragraph is not one inline link.
    """
    tokens = _LINK_MD.parse("\n".join(reader.raw_lines(node)))
    inline = next((t for t in tokens if t.type == "inline"), None)
    children = inline.children if inline is not None and inline.children else []
    links = [t for t in children if t.type == "link_open"]
    if (
        len(links) != 1
        or children[0].type != "link_open"
        or children[-1].type != "link_close"
        or links[0].markup == "autolink"
    ):
        raise ParseError(message, node)
    return str(links[0].attrGet("href") or ""), children[1:-1]


def origin_message(origin: str, owner: str) -> str:
    """Why `origin`, the destination of a link of `owner`, is not allowed."""
    if _SCHEME_RE.match(origin):
        reason = "it has a scheme"
    elif origin.startswith("/"):
        reason = "it starts with `/`"
    elif "?" in origin:
        reason = "it has a query"
    elif "#" in origin:
        reason = "it has a fragment, which is reserved"
    else:
        reason = "its file name has no extension, which is the format"
    return f"the origin {origin!r} of {owner} must be a relative path: {reason}"


def parse_attachments(reader: BlockReader, heading: Node, blocks: list[Node]) -> list[AttachmentDict]:
    """
    The `attachments` of an `## [attachments]` section: one for each fenced
    block and each paragraph with one link, in order.

    Args:
        reader: The blocks of the question or of the exam.
        heading: The heading of the section.
        blocks: The blocks of the section, after its heading.

    Raises:
        ParseError: the section has no block or a block that it does not
            allow, or an attachment is malformed.
    """
    if not blocks:
        raise ParseError("the ## [attachments] section has no content block", heading)
    attachments: list[AttachmentDict] = []
    for block in blocks:
        if block.type == "fence":
            attachments.append(_fenced_attachment(block))
        elif block.type == "paragraph":
            attachments.append(_linked_attachment(reader, block))
        else:
            raise ParseError(
                "the ## [attachments] section holds fenced code blocks and "
                f"paragraphs with only a link, not a {BLOCK_NAMES.get(block.type, block.type)}",
                block,
            )
    return attachments


def _fenced_attachment(node: Node) -> AttachmentDict:
    """The attachment of a fence whose info string is `format name`."""
    # The words end at a space or a tab only: a Unicode space is a
    # character of the word, which the name rule then rejects.
    words = [w for w in re.split(r"[ \t]+", unescapeAll(node.info).strip(" \t")) if w]
    if len(words) != 2:
        raise ParseError(
            "the info string of a fenced attachment has exactly two words, the "
            f"format and the name, as in ```csv dados.csv; found {len(words)}",
            node,
        )
    attachment_format, name = words
    problem = _name_problem(name)
    if problem is not None:
        raise ParseError(f"the name {name!r} of a fenced attachment {problem}", node)
    return {"name": name, "format": attachment_format, "text": node.content}


def _linked_attachment(reader: BlockReader, node: Node) -> AttachmentDict:
    """The attachment of a paragraph whose only content is an inline link."""
    origin, text_tokens = link_paragraph(
        reader,
        node,
        "a paragraph of the ## [attachments] section is an attachment only when "
        "its whole content is one inline link, as in `[dados](dados/tabela.csv)`; "
        "a fenced block holds the text of the other attachments",
    )
    if not ORIGIN_RE.fullmatch(origin):
        raise ParseError(origin_message(origin, "an attachment"), node)
    name = origin.rsplit("/", 1)[-1]
    problem = _name_problem(name)
    if problem is not None:
        raise ParseError(
            f"the name of a linked attachment is the last segment of its origin "
            f"{origin!r}, and the name {name!r} {problem}",
            node,
        )
    attachment: AttachmentDict = {
        "name": name,
        "format": origin.rsplit(".", 1)[1],
        "origin": origin,
    }
    label = _plain_text(text_tokens).strip(" \t\n")
    if has_visible_character(label) and label != name:
        attachment["label"] = label
    return attachment


def _name_problem(name: str) -> str | None:
    """Why `name` is not the name of an attachment (question-base.md, "Name")."""
    if name in (".", ".."):
        return "cannot be `.` or `..`"
    if "/" in name or "\\" in name:
        return "cannot have `/` or `\\`"
    if _NAME_FORBIDDEN_RE.search(name):
        return "cannot have a space or a backtick"
    return None


def _plain_text(tokens: list[Token]) -> str:
    """
    The text of inline tokens with no markup: the characters of the text and
    of the code spans. A line break is a line ending.
    """
    parts: list[str] = []
    for token in tokens:
        if token.type in ("text", "code_inline"):
            parts.append(token.content)
        elif token.type in ("softbreak", "hardbreak"):
            parts.append("\n")
        elif token.type == "image" and token.children:
            parts.append(_plain_text(token.children))
    return "".join(parts)

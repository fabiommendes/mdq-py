"""
The body of a code question: the `[code]` tag and its `## [template]`,
`## [tests]`, `## [rubric]`, `## [attachments]` and `## [answer-key]` sections
(docs/question-types/code.md).

The parser reads the blocks only. It does not read the text of a test source,
so the annotations of a fenced block are scanned later, by the model.
"""

from __future__ import annotations

from markdown_it.tree import SyntaxTreeNode as Node

from ..errors import ParseError
from ..types import RubricItemDict, TestSourceDict
from ._attachments import (
    ATTACHMENTS,
    ORIGIN_RE,
    link_paragraph,
    origin_message,
    parse_attachments,
    split_sections,
)
from ._blocks import BlockCursor, BlockReader
from ._choices import split_item
from ._ordering import fence_language
from ._rubric import (
    LIST_MODIFIERS,
    RubricSyntaxError,
    parse_item_line,
)

__all__ = ["InvalidRubricItem", "parse_code_body"]

#: The sections of a code question.
_SECTIONS = frozenset({"template", "tests", "rubric", ATTACHMENTS, "answer-key"})


class InvalidRubricItem(ParseError):
    """
    An item of `## [rubric]` that breaks the rubric item syntax. Carries the
    `invalid-rubric-item` code and the `path` of the item, so
    `mdq._loading._parse_error` reports it like the model does for the same
    fault in a YAML or JSON document.
    """

    code = "invalid-rubric-item"

    def __init__(self, message: str, index: int, node: Node | None = None):
        super().__init__(message, node=node, path=("rubric", index))


def parse_code_body(cursor: BlockCursor) -> tuple[dict[str, object], list[Node]]:
    """
    Read the sections that follow the `[code]` tag.

    The epilogue is between the tag and the first section, and the sections
    are contiguous after it, in any order. Each one, `## [answer-key]`
    included, ends at the heading of the next section.

    Args:
        cursor: The cursor, right after the `[code]` paragraph.

    Raises:
        ParseError: A section is declared twice, a section has no block or
            a block that it does not allow, or a test source is malformed.

    Returns:
        The fields `template`, `tests`, `rubric`, `attachments` and
        `answerKey` that the sections define, and the nodes of the epilogue.
    """
    reader = cursor.reader
    epilogue, sections = split_sections(cursor, _SECTIONS)
    fields: dict[str, object] = {}
    for name, heading, blocks in sections:
        if name == "answer-key":
            text = reader.join_blocks(blocks)
            if text:
                fields["answerKey"] = text
            continue
        if not blocks:
            raise ParseError(f"the ## [{name}] section has no content block", heading)
        match name:
            case "template":
                fields["template"] = _template(reader, blocks)
            case "tests":
                fields["tests"] = _tests(reader, blocks)
            case "rubric":
                fields["rubric"] = _rubric(reader, blocks)
            case _:
                fields["attachments"] = parse_attachments(reader, heading, blocks)
    return fields, epilogue


def _offender(blocks: list[Node], expected: str) -> Node:
    """
    The block that breaks a section of exactly one block of the type
    `expected`: the first block of another type, else the extra block.
    """
    return next((b for b in blocks if b.type != expected), blocks[1] if len(blocks) > 1 else blocks[0])


def _template(reader: BlockReader, blocks: list[Node]) -> str:
    """The `template`: the Markdown source of the one fenced block."""
    if len(blocks) != 1 or blocks[0].type != "fence":
        raise ParseError(
            "the ## [template] section holds exactly one fenced code block",
            _offender(blocks, "fence"),
        )
    return reader.block_text(blocks[0])


def _tests(reader: BlockReader, blocks: list[Node]) -> list[TestSourceDict]:
    """The `tests`: a fenced block or a paragraph with one link, in order."""
    sources: list[TestSourceDict] = []
    for block in blocks:
        if block.type == "fence":
            test_format = fence_language(block.info)
            if test_format is None:
                raise ParseError(
                    "a fenced test source starts its info string with the test "
                    "format, as in ```pytest",
                    block,
                )
            sources.append({"format": test_format, "text": block.content})
        elif block.type == "paragraph":
            sources.append(_linked_source(reader, block))
        else:
            raise ParseError(
                "the ## [tests] section holds fenced code blocks and paragraphs "
                "with only a link",
                block,
            )
    return sources


def _linked_source(reader: BlockReader, node: Node) -> TestSourceDict:
    """The test source of a paragraph whose only content is an inline link."""
    origin, _ = link_paragraph(
        reader,
        node,
        "a paragraph of the ## [tests] section is a test source only when "
        "its whole content is one inline link, as in `[tests](test_x.py)`; "
        "a fenced block holds the other tests",
    )
    if not ORIGIN_RE.fullmatch(origin):
        raise ParseError(origin_message(origin, "a test source"), node)
    return {"format": origin.rsplit(".", 1)[1], "origin": origin}


def _rubric(reader: BlockReader, blocks: list[Node]) -> list[RubricItemDict]:
    """The `rubric`: the manual items of the one unordered list."""
    if len(blocks) != 1 or blocks[0].type != "bullet_list":
        raise ParseError(
            "the ## [rubric] section holds exactly one unordered list",
            _offender(blocks, "bullet_list"),
        )
    node = blocks[0]
    for item in node.children:
        reader.check_no_setext_item(item)
        if item.children and item.children[0].type != "paragraph":
            raise ParseError(
                "an item of `## [rubric]` starts with a paragraph: the criterion "
                f"is not a {item.children[0].type.replace('_', ' ')}",
                item,
            )
    return [
        _rubric_item(reader.item_lines(item), index, item)
        for index, item in enumerate(node.children)
    ]


def _rubric_item(lines: list[str], index: int, node: Node) -> RubricItemDict:
    """One item of the list, with the binding `{manual}`."""
    try:
        parsed = parse_item_line(lines[0])
    except RubricSyntaxError as exc:
        raise InvalidRubricItem(str(exc), index, node) from exc
    names = parsed.modifiers
    unknown = next((n for n in names if n not in LIST_MODIFIERS), None)
    if unknown is not None:
        hint = (
            "`public` and `example` are modifiers of an annotation of a test source"
            if unknown in ("public", "example")
            else "the only modifier of an item of `## [rubric]` is `{manual}`"
        )
        raise InvalidRubricItem(f"the modifier {{{unknown}}}: {hint}", index, node)
    if len(names) > 1:
        raise InvalidRubricItem("a modifier repeats in one item", index, node)
    if not names:
        raise InvalidRubricItem(
            "an item of `## [rubric]` needs the binding `{manual}`", index, node
        )
    raw = split_item(parsed.criterion, lines[1:])
    item: RubricItemDict = {"binding": "manual", "text": raw.text if parsed.criterion else ""}
    if parsed.value is not None:
        item["value"] = parsed.value
    if raw.feedback is not None:
        item["feedback"] = raw.feedback
    if raw.comment is not None:
        item["comment"] = raw.comment
    return item

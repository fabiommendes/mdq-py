# doc0: skip
"""
A basic Markdown parser for one MDQ question document.

This module turns MDQ Markdown source (frontmatter + introduction + body +
epilogue, as described in ``docs/question-types/generic.md``) into the same
dict shape that ``mdq.validator.validate_document`` expects, i.e. the
shape documented by ``schema/*.yaml``.

Design notes
------------
We use ``markdown-it-py`` to get *block*-level structure (paragraphs,
headings, bullet lists) because that part of CommonMark -- what starts a
new block, when a list interrupts a paragraph, etc. -- is exactly the kind
of thing not worth reimplementing. But MDQ layers its own inline
mini-grammars on top of plain block content (choice markers, feedback `>`
and comment `!` lines inside a single list item, the `[numeric(unit)]:`
tag, ...) that are not CommonMark constructs -- markdown-it has no idea
what a "feedback line" is, and in fact a run of `!`-prefixed lines
directly under a `>` blockquote gets lazily absorbed *into* the
blockquote's paragraph by CommonMark's lazy-continuation rule, which
throws away exactly the split we need. So once we know a block's *line
range* (`node.map`), we re-read those raw source lines ourselves for
anything with MDQ-specific syntax, rather than trusting markdown-it's
subtree for it. Plain prose blocks (stem, epilogue, choice/blank
text) are just reconstructed from their raw lines, soft-wrapped lines
joined with a single space -- the same collapsing a YAML folded (`>-`)
scalar does, which is how every paired `.yaml` fixture represents them.

`parse_question` is a thin wrapper around `MDQParser`, a recursive-descent
parser that walks a cursor over one question's block children. Exam-level
concerns (splitting a document into question blocks, inheritance, the
`===` grammar) live in `_exam`, which calls back into `parse_question` for
each block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from collections.abc import Mapping
from typing import assert_never, cast

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode as Node

from .._diagnostics import Diagnostic
from .._exact import exact_literal, join_pattern_lines
from .._markdown import SLUG_BODY_RE, md, span, split_lines, starts_after
from ..errors import (
    IncompleteQuestion,
    MissingField,
    ParseError,
    UndefinedBlank,
)
from ..types import (
    BlankDict,
    PatternEntry,
    NumericBlankDict,
    QuestionDict,
    ScoredChoiceDict,
    ShortAnswerBlankDict,
)
from ._choices import (
    ChoiceType,
    LINK_START_RE,
    RawChoice,
    SLUG_PREFIX_RE,
    _infer_choice_type,
    _pattern_entry,
    dedent,
    as_choice_type,
    build_choices,
    CODE_INDENT,
    indentation,
    is_choice_value,
    match_choice_marker,
    parse_marker,
    parse_observations,
    split_item,
)
from ._frontmatter import (
    GRADED_QUESTION_TYPES,
    _copy_pattern_lists,
    _extract_comment,
    common_frontmatter,
    _load_frontmatter_yaml,
    _normalize_list,
    _invalid_frontmatter_fields,
    _split_frontmatter,
)
from ._numeric import _parse_numeric_expression, numeric_fields
from ._ordering import (
    ORDERING_SECTION_RE,
    RawAlternative,
    RawLine,
    fence_language,
    is_comment_block,
    ordering_alternative,
    collect_item_depths,
    ordering_code_lines,
    ordering_leveled,
    ordering_ul_lines,
    ordering_unit,
)
from ._tags import (
    BLANK_RE,
    SHORT_ANSWER_RE,
    TAG_REST_RE,
    BlankTag,
    ChoiceBlankTag,
    EssayTag,
    NumericBlankTag,
    NumericTag,
    OrderingTag,
    ShortAnswerBlankTag,
    ShortAnswerTag,
    UnrecognizedBlankTag,
    check_bare_tag_alone,
    check_tag_label,
    is_reserved_label,
    read_blank_tag,
    read_body_tag,
    read_short_answer_tag,
    tag_lines,
)

__all__ = [
    "parse_question",
    "reconstruct_blocks",
    "find_forbidden_elements",
    "find_answer_key_forbidden_elements",
    "find_stray_choice_markers",
]

#
# Constants
#

#: A raw line that looks like the first line of a choice: a list marker
#: and a choice marker (choices.md, "Choice marker").
BRACKET_ITEM_RE = re.compile(r"^[*+-][ \t]+\[[^\]\r\n]*\](?![(\[])")
ANSWER_KEY_RE = re.compile(r"^\[answer-key\]$")
# The markers around the text of an ATX heading.
ATX_OPENING_RE = re.compile(r"^[ \t]*#{1,6}")
ATX_CLOSING_RE = re.compile(r"(?:[ \t]+#+)?[ \t]*$")
#: Reads link reference definitions, which `md` leaves as paragraphs.
_REFERENCE_MD = MarkdownIt("commonmark")


#
# Public API
#
def parse_question(
    text: str, *, warnings: list[Diagnostic] | None = None
) -> QuestionDict:
    """
    Parse MDQ Markdown source into a question document dict, matching the
    shape validated by mdq.validator.validate_document.

    Args:
        text: MDQ source text for a single question, with or without YAML
            frontmatter.
        warnings: When given, the parser appends its diagnostics: an
            `invalid-frontmatter-field` error for every frontmatter key
            that is not in the frontmatter table of the question's type,
            and the warnings about the source layout. Parsing never
            fails because of them; the caller checks the severity.

    Returns:
        The parsed question document, in the shape validated by
        `mdq.validator.validate_document`.

    Raises:
        MissingField: If the question has no stem.
        ParseError: If the body does not match any known question shape.
        IncompleteQuestion: If a bracket-list body's type cannot be
            inferred and none is declared in frontmatter.

    Example:
        >>> doc = parse_question(
        ...     "What is the capital of Brazil?\\n\\n"
        ...     "* [ ] Rio de Janeiro\\n* [x] Brasília\\n"
        ... )
        >>> doc["stem"]
        'What is the capital of Brazil?'
        >>> doc["type"]
        'multiple-selection'
    """

    parser = MDQParser(text)
    doc = parser.parse_question()
    if warnings is not None:
        warnings.extend(_invalid_frontmatter_fields(parser.frontmatter, doc["type"]))
        warnings.extend(parser.diagnostics)
    return doc


def _redundant_id(front_id: object, slug: str) -> Diagnostic:
    """The `redundant-id` warning: `id` in the frontmatter and as a slug."""
    if front_id == slug:
        detail = "with the same value"
    else:
        detail = f"with the value {slug!r}; the frontmatter value {front_id!r} wins"
    return Diagnostic(
        severity="warning",
        code="redundant-id",
        path=("id",),
        message=f"`id` is set in the frontmatter and as a slug {detail}",
    )


#
# Implementation
#
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


@dataclass
class MDQParser:
    """
    A recursive-descent parser for one MDQ question document.

    Holds a cursor (`reader`/`pos`) over the question's markdown-it block
    tree, the parsed frontmatter (`front`/`comment`),
    and the output document being built up (`doc`). Grammar-rule methods
    read from the cursor and write into `doc` as they go, which avoids
    threading `(children, lines, index, front, doc)` through a long chain
    of free functions.

    Attributes:
        frontmatter: The question's parsed YAML frontmatter.
        comment: The leading `#`-comment block from the frontmatter, if any.
        reader: The block reader over the body, after the frontmatter.
        pos: Index of the next unread node in `reader.children`.
        doc: The output document being assembled.
    """

    src: str

    #: Position in the token stream.
    pos: int = field(default=0, init=False)

    #: Accumulate the currently parsed object
    state: dict[str, object] = field(default_factory=dict, init=False)

    #: Frontmatter for the current element
    frontmatter: Mapping[str, object] = field(default_factory=dict, init=False)

    #: Frontmatter comment
    comment: str | None = field(default=None, init=False)

    #: The body blocks, after the frontmatter.
    reader: BlockReader = field(init=False)

    #: Warnings the parser found in the source layout.
    diagnostics: list[Diagnostic] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        frontmatter_text, body_text = _split_frontmatter(self.src)
        if frontmatter_text is not None:
            self.frontmatter = _load_frontmatter_yaml(frontmatter_text)
            self.comment = _extract_comment(frontmatter_text)
        else:
            self.frontmatter = {}
            self.comment = None
        self.reader = BlockReader(body_text)

    #
    # Cursor primitives
    #
    def read(self) -> Node:
        """
        Consume and return the current node, advancing the cursor.

        Raises:
            ParseError: If the cursor is already exhausted.
        """

        node = self.peek()
        if node is None:
            raise ParseError("unexpected end of document")
        self.pos += 1
        return node

    def peek(self) -> Node | None:
        """
        Return the current node without consuming it, or None at the end.
        """

        if self.pos >= len(self.reader.children):
            return None
        return self.reader.children[self.pos]

    def expect(self, node_type: str, error_msg: str) -> Node:
        """
        Consume and return the current node if it has type `node_type`.

        Raises:
            ParseError: If the cursor is exhausted or the current node's
                type does not match `node_type`.
        """

        node = self.peek()
        if node is None or node.type != node_type:
            raise ParseError(error_msg, node)
        return self.read()

    #
    # Body-start / tag detection
    #
    def is_choice_list(self, node: Node) -> bool:
        """
        Whether `node` is a choice list: an unordered list whose every
        item starts with a choice marker (choices.md, "Choice marker").
        """
        if node.type != "bullet_list" or not node.children:
            return False
        return all(
            match_choice_marker(self.reader.item_lines(item)[0]) is not None
            for item in node.children
        )

    def check_no_setext_tag(self, node: Node | None, pattern: re.Pattern[str]) -> None:
        """
        Raise a `ParseError` if `node` is a setext heading whose first line
        is a tag that `pattern` matches: the line after the tag content
        was a setext underline (short-answer.md, "Pattern lines").
        """
        if node is None or node.type != "heading" or node.markup not in ("-", "="):
            return
        first_line = self.reader.raw_lines(node)[:1]
        if first_line and pattern.match(first_line[0].strip(" \t")):
            raise ParseError(_setext_message(first_line[0].strip(" \t")))

    def check_no_setext_item(self, item: Node) -> None:
        """
        Raise a `ParseError` if a setext underline follows the text of the
        list item `item`: CommonMark turns the text into a heading
        (grammar.md, "Feedback and comment lines").
        """
        for child in item.children:
            if child.type == "heading" and child.markup in ("-", "="):
                text = self.reader.raw_lines(child)[:1]
                raise ParseError(_setext_message(text[0].strip(" \t") if text else ""))

    def check_pattern_item_paragraph(self, item: Node) -> None:
        """
        Raise a `ParseError` if the content of the pattern item `item` starts
        with a block that is not a paragraph in CommonMark: a block quote, a
        heading, a list, a fenced or indented code block, an HTML block or a
        thematic break (patterns.md, "Pattern items").
        """
        if not item.children or item.children[0].type == "paragraph":
            return
        line = self.reader.item_lines(item)[0].strip(" \t")
        raise ParseError(
            f"the pattern line {line!r} starts a block of its own "
            f"({_BLOCK_NAMES.get(item.children[0].type, item.children[0].type)}) "
            f"in markdown, so it is not a pattern: write an exact literal "
            f"instead, e.g. `{line}`"
        )

    def find_body_start(self) -> int:
        """
        Return the index of the first body node in `self.reader.children`.

        Scans from the start of the document (independent of `self.pos`,
        which is still 0 at call time) for the first paragraph matching a
        known body tag, or the first bracket-led bullet list. A document
        that declares `type: fill-in` and has none is a stem with no blank:
        the result is then the number of nodes.

        Raises:
            MissingField: If no body node is found. The message says so when
                a tag line became a setext heading (CommonMark: a `---` or
                `===` line right under a paragraph makes it a heading).
        """

        setext_tag: str | None = None
        for i, child in enumerate(self.reader.children):
            if (
                setext_tag is None
                and child.type == "heading"
                and child.markup in ("-", "=")
            ):
                first_line = self.reader.raw_lines(child)[:1]
                if first_line and read_body_tag(first_line[0].strip()) is not None:
                    setext_tag = first_line[0].strip()
            if child.type == "paragraph":
                text = self.reader.raw_text(child)
                if read_body_tag(text) is not None:
                    return i
            elif self.is_choice_list(child):
                return i
        if setext_tag is not None:
            raise MissingField(
                "body",
                message=_setext_message(setext_tag),
            )
        if self.frontmatter.get("type") == "fill-in":
            # A fill-in stem with no blank has no body at all: every block
            # is the stem and `blanks` stays empty (fill-in.md).
            return len(self.reader.children)
        raise MissingField("body")

    #
    # Intro / stem
    #
    def split_intro(self, intro_blocks: list[Node]) -> tuple[str, str | None]:
        """
        Split the blocks preceding the body into (stem, slug).

        The stem is every intro block, joined. An inline `[slug]` prefix,
        if present, only ever appears on the *first* intro block and is
        removed from the stem.
        """

        first_node = intro_blocks[0]
        first_text = self.reader.raw_text(first_node)
        slug_match = (
            SLUG_PREFIX_RE.match(first_text) if first_node.type == "paragraph" else None
        )
        if not slug_match:
            return "\n\n".join(self.reader.block_text(n) for n in intro_blocks), None

        stem_text = "\n\n".join(
            [first_text[slug_match.end() :]]
            + [self.reader.block_text(n) for n in intro_blocks[1:]]
        )
        return stem_text, slug_match.group("slug")

    #
    # Choice/item-list parsing
    #
    def parse_item_list(self, node: Node) -> list[RawChoice]:
        for item in node.children:
            self.check_no_setext_item(item)
        return [self.parse_item(self.reader.item_lines(item)) for item in node.children]

    def parse_item(self, item_lines: list[str]) -> RawChoice:
        """
        Parse the content lines of one choice (choices.md, "Item").

        Raises:
            ParseError: The item does not start with a choice marker, the
                marker is empty, or the lines after the text are not one
                feedback block and one comment block.
        """
        value, explicit_id, rest = parse_marker(item_lines[0])
        choice = split_item(rest, item_lines[1:])
        choice.value = value
        choice.explicit_id = explicit_id
        return choice

    def parse_plain_item(self, item_lines: list[str]) -> RawChoice:
        """
        Parse the content lines of a list item with no `[value]` marker,
        e.g. a pattern line.

        Raises:
            ParseError: The lines after the text are not one feedback block
                and one comment block.
        """
        return split_item(item_lines[0], item_lines[1:], join_pattern_lines)

    #
    # Per-type body fillers
    #
    def parse_choice_body(
        self, question_type: ChoiceType | None, raw_choices: list[RawChoice]
    ) -> None:
        self.state["choices"] = build_choices(question_type, raw_choices)

    def parse_essay_body(self) -> None:
        front = self.frontmatter
        if "content" in front:
            self.state["content"] = front["content"]
        if "highlight" in front:
            self.state["highlight"] = front["highlight"]

    @staticmethod
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

    def parse_ordering_body(self, tag_node: Node) -> list[Node]:
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
        main_kind, main_highlight, main_raw = self.parse_ordering_content(
            tag_node=tag_node
        )

        first_section = next(
            (
                i
                for i in range(self.pos, len(self.reader.children))
                if self.is_ordering_section(self.reader.children[i])
            ),
            len(self.reader.children),
        )
        epilogue_nodes = self.reader.children[self.pos : first_section]
        self.pos = first_section

        extra_raw: list[RawLine] | None = None
        accept_raw: list[RawAlternative] = []
        reject_raw: list[RawAlternative] = []

        while True:
            node = self.peek()
            if node is None or node.type != "heading" or node.tag != "h2":
                break
            m = ORDERING_SECTION_RE.match(self.reader.raw_text(node))
            if m is None:
                break
            self.read()
            name = m.group("name")
            if name == "extra":
                if extra_raw is not None:
                    raise ParseError("a question defines at most one [extra] section")
                kind, highlight, extra_raw = self.parse_ordering_content(section=name)
                if kind != main_kind:
                    raise ParseError(
                        "[extra] must use the same content type as [ordering]"
                    )
                self.check_section_highlight(name, highlight, main_highlight)
            else:
                feedback, comment = self.parse_ordering_observations()
                kind, highlight, raw = self.parse_ordering_content(section=name)
                if kind != main_kind:
                    raise ParseError(
                        f"[{name}] must use the same content type as [ordering]"
                    )
                self.check_section_highlight(name, highlight, main_highlight)
                target = accept_raw if name == "accept" else reject_raw
                target.append(RawAlternative(raw, feedback, comment))

        if self.pos < len(self.reader.children):
            raise ParseError(
                "only [extra], [accept] and [reject] sections can follow the "
                "first section; the epilogue goes before it",
                self.reader.children[self.pos],
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

        front = self.frontmatter
        doc = self.state
        doc["content"] = main_kind
        if main_highlight:
            doc["highlight"] = main_highlight
        if "indentation" in front:
            doc["indentation"] = front["indentation"]
        if "unmatched" in front:
            doc["unmatched"] = front["unmatched"]
        if "incorrectFeedback" in front:
            doc["incorrectFeedback"] = front["incorrectFeedback"]
        if front.get("normalizations") is not None:
            doc["normalizations"] = _normalize_list(front["normalizations"])

        doc["lines"] = ordering_leveled(main_raw, unit)
        if extra_raw is not None:
            doc["extra"] = ordering_leveled(extra_raw, unit)
        if accept_raw:
            doc["accept"] = [ordering_alternative(alt, unit) for alt in accept_raw]
        if reject_raw:
            doc["reject"] = [ordering_alternative(alt, unit) for alt in reject_raw]
        return epilogue_nodes

    @staticmethod
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

    def is_ordering_section(self, node: Node) -> bool:
        """Whether `node` is an `## [extra]`, `## [accept]` or `## [reject]` heading."""
        return (
            node.type == "heading"
            and node.tag == "h2"
            and ORDERING_SECTION_RE.match(self.reader.raw_text(node)) is not None
        )

    def parse_ordering_content(
        self, *, tag_node: Node | None = None, section: str | None = None
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
        node = self.peek()
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
        self.read()
        if node.type == "bullet_list":
            self.check_no_adjacent_list(node)
        if node.type == "fence":
            return "code", fence_language(node.info), ordering_code_lines(node.content)
        self.check_ordering_item_blocks(node)
        depths: dict[int, int] = {}
        parents: set[int] = set()
        collect_item_depths(node, 0, depths, parents)
        first_line = span(node)[0]
        return (
            "text",
            None,
            ordering_ul_lines(self.reader.raw_lines(node), depths, first_line, parents),
        )

    def check_ordering_item_blocks(self, node: Node) -> None:
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
                    self.check_ordering_item_blocks(child)
                elif child.type != "paragraph":
                    line = self.reader.raw_lines(item)[0].strip(" \t")
                    raise ParseError(
                        f"an ordering item is one paragraph, but the item "
                        f"{line!r} holds a "
                        f"{_BLOCK_NAMES.get(child.type, child.type)}",
                        item,
                    )

    def parse_ordering_observations(self) -> tuple[str | None, str | None]:
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
            node = self.peek()
            if node is None:
                break
            if node.type == "blockquote" or (
                node.type == "paragraph" and is_comment_block(self.reader.raw_lines(node)[:1])
            ):
                if first is None:
                    first = node
                last = node
                self.read()
            else:
                break
        if first is None or last is None:
            return None, None
        return parse_observations(self.reader.lines[span(first)[0] : span(last)[1]])

    def parse_short_answer_body(self, tag: ShortAnswerTag, tag_node: Node) -> None:
        """
        Fill the short-answer fields from a run of `[short-answer...]` blocks.

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
        front = self.frontmatter
        doc = self.state
        for key in ("diacritics", "unmatched", "incorrectFeedback"):
            if key in front:
                doc[key] = front[key]

        seen: set[str] = set()
        while True:
            if tag.role in seen:
                raise ParseError(f"repeated [short-answer] {tag.role} block")
            seen.add(tag.role)
            patterns = self.parse_answer_block(
                tag_node,
                tag.rest,
                reject=tag.role == "reject",
                tag="short-answer",
                path=(tag.role,),
            )
            if patterns:
                doc[tag.role] = patterns

            node = self.peek()
            self.check_no_setext_tag(node, SHORT_ANSWER_RE)
            if node is None or node.type != "paragraph":
                break
            next_tag = read_short_answer_tag(self.reader.raw_text(node))
            if next_tag is None:
                break
            tag = next_tag
            tag_node = self.read()

        _copy_pattern_lists(front, doc)

    def _join_content_lines(self, tag_node: Node, rest: str) -> str:
        """
        The content of a short-answer tag: the text after the colon and the
        continuation lines, joined with one U+0020 each. A line ending and
        the indentation of the next line become that space
        (docs/references/patterns.md, "Continuation lines"). `rest` is the
        text `raw_text` gave, whose line endings already are spaces.
        """
        lines = self.reader.raw_lines(tag_node)
        if len(lines) < 2:
            return rest.strip(" \t")
        first = TAG_REST_RE.match(lines[0])
        assert first is not None  # the caller matched a tag
        return join_pattern_lines([first.group("rest"), *lines[1:]])

    def _warn_multi_line_pattern(
        self, path: tuple[str | int, ...], pattern: str, lines: int
    ) -> None:
        """
        Report an exact literal or a regex of the body that spans more than
        one line: the line ending becomes a significant U+0020
        (patterns.md, "Continuation lines").
        """
        if lines > 1 and pattern.startswith(("`", "/")):
            self.diagnostics.append(
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
        self,
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
            return self._bare_answer_block(tag_node, reject=reject, tag=tag)
        rest = self._join_content_lines(tag_node, rest)
        # The tag paragraph also holds the lazy continuation lines of the
        # content. A `!` line is not lazy (a comment), so it is an error.
        for line in self.reader.raw_lines(tag_node)[1:]:
            if _is_comment_line(line):
                raise ParseError(_OBSERVATION_AFTER_CONTENT)
        node = self.peek()
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
            tag_line, *other_lines = self.reader.raw_lines(tag_node)
            first = TAG_REST_RE.match(tag_line)
            content_lines = [first.group("rest") if first else "", *other_lines]
            self._warn_multi_line_pattern(
                (*path, 0), rest, sum(1 for line in content_lines if line.strip(" \t"))
            )
            return [rest]
        assert node is not None
        self.read()
        self.check_no_adjacent_list(node)
        for item in node.children:
            self.check_no_setext_item(item)
            self.check_pattern_item_paragraph(item)
        raw_items = [self.parse_plain_item(self.reader.item_lines(item)) for item in node.children]
        entries = [_pattern_entry(item) for item in raw_items]
        for index, (entry, raw_item) in enumerate(zip(entries, raw_items)):
            pattern = entry if isinstance(entry, str) else entry["pattern"]
            check_exact_pattern(pattern)
            self._warn_multi_line_pattern((*path, index), pattern, raw_item.text_lines)
        return entries

    def _bare_answer_block(
        self, tag_node: Node, *, reject: bool, tag: str
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
        node = self.peek()
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

    def parse_numeric_body(self, tag: NumericTag) -> None:
        parsed = _parse_numeric_expression(tag.rest)
        front = self.frontmatter
        doc = self.state

        doc["answer"] = parsed["answer"]
        if tag.unit:
            doc["unit"] = tag.unit
        doc.update(numeric_fields(parsed, front))
        if "tolerance" in parsed:
            doc["tolerance"] = parsed["tolerance"]
        if "incorrectFeedback" in front:
            doc["incorrectFeedback"] = front["incorrectFeedback"]

    def parse_fill_in_body(self, tag: BlankTag, tag_node: Node) -> None:
        """
        Fill `blanks` from a run of `[^id...]:` definitions.

        A slug may be defined more than once -- a short answer blank
        spreads its accept block and its reject block over
        separate definitions -- so definitions accumulate into one blank
        per slug, keyed by the order the slug is first seen.

        Raises:
            ParseError: an unrecognized or misplaced tag suffix, a slug
                whose definitions disagree about the blank's kind, a
                repeated definition of the same form.
        """
        front = self.frontmatter
        if "shuffle" in front:
            self.state["shuffle"] = front["shuffle"]
        for key in ("diacritics", "unmatched"):
            if key in front:
                self.state[key] = front[key]

        numeric_maps = self.numeric_blank_maps(front)
        blanks: dict[str, BlankDict] = {}
        #: The (blank id, `accept`/`reject`) short-answer definitions seen.
        defined: set[tuple[str, str]] = set()
        while True:
            match tag:
                case UnrecognizedBlankTag(text=text):
                    raise ParseError(f"unrecognized blank definition: {text!r}")
                case ChoiceBlankTag(id=blank_id, rest=rest):
                    next_node = self.peek()
                    if not rest and next_node is not None and next_node.type == "bullet_list":
                        if not starts_after(tag_node, next_node):
                            raise ParseError(
                                f"the choice list of [^{blank_id}] must start on the "
                                f"line right after its tag, with no blank line in between"
                            )
                        self.read()
                        self.check_no_adjacent_list(next_node)
                        raw_choices = self.parse_item_list(next_node)
                        # The choices of a multiple-choice blank are scored choices.
                        choices = cast(
                            "list[ScoredChoiceDict]",
                            build_choices(
                                "multiple-choice",
                                raw_choices,
                                ("blanks", _blank_index(blanks, blank_id)),
                            ),
                        )
                        self._add_blank(
                            blanks,
                            {"id": blank_id, "type": "multiple-choice", "choices": choices},
                        )
                    elif not rest:
                        raise ParseError(
                            f"the choice blank [^{blank_id}]: has no choice list: the "
                            f"list starts on the line right after the tag"
                        )
                    else:
                        raise ParseError(
                            f"the tag line of the choice blank [^{blank_id}] must be "
                            f"empty and the choice list must follow it; text after the "
                            f"colon is not a choice. For a text answer, write "
                            f"[^{blank_id}/short-answer]: {rest}"
                        )
                case NumericBlankTag(id=blank_id, unit=unit, rest=rest):
                    parsed = _parse_numeric_expression(rest)
                    # A numeric blank is graded exactly like a numeric
                    # question (fill-in.md), so the domain is inferred from
                    # the written representation there too.
                    blank: NumericBlankDict = {
                        "id": blank_id,
                        "type": "numeric",
                        "answer": parsed["answer"],
                    }
                    if unit:
                        blank["unit"] = unit
                    # fill-in.md, "Frontmatter": the `domain` and `decimalPlaces`
                    # maps win over the inferred values, as they do in a numeric
                    # question (numeric.md, "Number type/domain").
                    declared = {
                        key: numeric_maps[key][blank_id]
                        for key in ("domain", "decimalPlaces")
                        if blank_id in numeric_maps[key]
                    }
                    cast("dict[str, object]", blank).update(numeric_fields(parsed, declared))
                    if "tolerance" in parsed:
                        blank["tolerance"] = parsed["tolerance"]
                    self._add_blank(blanks, blank)
                case ShortAnswerBlankTag(id=blank_id, role=role, rest=rest):
                    if (blank_id, role) in defined:
                        raise ParseError(
                            f"repeated [^{blank_id}/short-answer] {role} definition"
                        )
                    defined.add((blank_id, role))
                    patterns = self.parse_answer_block(
                        tag_node,
                        rest,
                        reject=role == "reject",
                        tag=f"^{blank_id}/short-answer",
                        path=("blanks", _blank_index(blanks, blank_id), role),
                    )
                    sa_blank: ShortAnswerBlankDict = {
                        "id": blank_id,
                        "type": "short-answer",
                    }
                    if patterns and role == "accept":
                        sa_blank["accept"] = patterns
                    elif patterns:
                        sa_blank["reject"] = patterns
                    self._add_blank(blanks, sa_blank)
                case _:
                    assert_never(tag)

            node = self.peek()
            self.check_no_setext_tag(node, BLANK_RE)
            if node is None or node.type != "paragraph":
                break
            next_tag = read_blank_tag(self.reader.raw_text(node))
            if next_tag is None:
                break
            tag = next_tag
            tag_node = self.read()

        self.distribute_blank_pattern_lists(front, blanks)
        self.distribute_numeric_blank_maps(numeric_maps, blanks)
        self.state["blanks"] = list(blanks.values())

    def check_tag_lines(self) -> None:
        """
        Raise a `ParseError` for a reserved tag that is not a valid tag, in
        any paragraph of the question: a tag in the wrong case, a tag with an
        unknown suffix, a tag of the frontmatter such as `preAccept`
        (question-base.md, "Body tags"). A label that does not start with a
        type name is an ordinary link reference definition.
        """
        for node in self.reader.children:
            if node.type != "paragraph":
                continue
            text = self.reader.raw_text(node)
            lines = self.reader.raw_lines(node)
            for label, colon in tag_lines(text, lines):
                check_tag_label(label, colon)
            check_bare_tag_alone(text, lines)

    def report_detached_tags(self, blocks: list[Node], *, fill_in: bool) -> None:
        """
        Report a tag in the epilogue.

        The blocks of the body are one run, so the first other block starts
        the epilogue, and a tag after it defines nothing. Each such tag is an
        error `detached-tag`. Code blocks are not paragraphs, so a tag inside
        fenced code does not count. The error stops the load before the model
        checks, so the stem reference of a blank gives no `undefined-blank`.

        Args:
            blocks: The blocks of the epilogue.
            fill_in: Whether the question is a fill-in question, where
                `[^id]:` is the tag of a choice blank.
        """
        for node in blocks:
            if node.type != "paragraph":
                continue
            for label, colon in tag_lines(self.reader.raw_text(node), self.reader.raw_lines(node)):
                choice_blank = (
                    fill_in and colon and re.fullmatch(rf"\^{SLUG_BODY_RE}", label)
                )
                if not (is_reserved_label(label) or choice_blank):
                    continue
                self.diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="detached-tag",
                        path=("epilogue",),
                        message=(
                            f"the tag `[{label}]{':' if colon else ''}` comes after the "
                            "epilogue started, so it is part of the epilogue; move "
                            "the tag up, before the epilogue"
                        ),
                    )
                )

    def check_no_adjacent_list(self, content: Node) -> None:
        """
        Raise a `ParseError` if a list starts on the line right after the
        content list `content`. In CommonMark a change of the list marker
        (`*` to `-`, or to `1.`) starts a new list, and that list would go
        to the epilogue with no sign: an item would leave the answer.
        """
        node = self.peek()
        if node is None:
            return
        # The map of a list includes the blank lines inside it.
        start, end = span(content)
        while end > start and not self.reader.lines[end - 1].strip(" \t"):
            end -= 1
        if node.type in ("bullet_list", "ordered_list") and span(node)[0] == end:
            raise ParseError(
                "use the same list marker for every item, or separate the "
                "epilogue with a blank line",
                node,
            )

    @staticmethod
    def numeric_blank_maps(front: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
        """
        The frontmatter `domain` and `decimalPlaces` maps of a fill-in
        question (fill-in.md, "Frontmatter"), each from a blank id to the
        value of the field of the same name. A missing map is empty. The
        values are not checked here: the schema checks them on the blank.

        Raises:
            ParseError: a map is not a mapping.
        """
        maps: dict[str, Mapping[str, object]] = {}
        for key in ("domain", "decimalPlaces"):
            mapping = front.get(key, {})
            if not isinstance(mapping, Mapping):
                raise ParseError(
                    f"frontmatter {key!r} of a fill-in question must map blank "
                    "ids to values"
                )
            maps[key] = mapping
        return maps

    @staticmethod
    def distribute_numeric_blank_maps(
        maps: Mapping[str, Mapping[str, object]], blanks: dict[str, BlankDict]
    ) -> None:
        """
        Check the keys of the `domain` and `decimalPlaces` maps against the
        blanks. A numeric blank took its values when it was built; a key
        that is the id of another kind of blank puts the value on that
        blank, where the schema rejects it.

        Raises:
            UndefinedBlank: a key is not the id of a blank in `blanks`.
        """
        for key, mapping in maps.items():
            for blank_id, value in mapping.items():
                blank = blanks.get(blank_id)
                if blank is None:
                    raise UndefinedBlank(str(blank_id), key)
                if blank["type"] != "numeric":
                    _set_field(blank, key, value)

    @staticmethod
    def distribute_blank_pattern_lists(
        front: Mapping[str, object], blanks: dict[str, BlankDict]
    ) -> None:
        """
        Move the frontmatter `preAccept`/`preReject`/`incorrectFeedback`
        maps onto the blanks they key (fill-in.md, "Frontmatter"). Each map
        goes from a blank id to a pattern list (a string for
        `incorrectFeedback`); the value becomes the field of the same name
        of that blank, whatever its kind -- the schema rejects `preAccept`
        and `preReject` on a choice or numeric blank, and `incorrectFeedback`
        on a choice blank.

        Raises:
            UndefinedBlank: a key is not the id of a blank in `blanks`.
            ParseError: a map is not a mapping of lists (of strings for
                `incorrectFeedback`).
        """
        for key in ("preAccept", "preReject", "incorrectFeedback"):
            if key not in front:
                continue
            mapping = front[key]
            is_text = key == "incorrectFeedback"
            if not isinstance(mapping, Mapping):
                raise ParseError(
                    f"frontmatter {key!r} of a fill-in question must map "
                    f"blank ids to {'strings' if is_text else 'pattern lists'}"
                )
            for blank_id, value in mapping.items():
                if is_text and not isinstance(value, str):
                    raise ParseError(
                        f"frontmatter {key!r} entry {blank_id!r} must be a string"
                    )
                if not is_text and not isinstance(value, list):
                    raise ParseError(
                        f"frontmatter {key!r} entry {blank_id!r} must be "
                        "a list of patterns"
                    )
                blank = blanks.get(blank_id)
                if blank is None:
                    raise UndefinedBlank(str(blank_id), key)
                _set_field(blank, key, value)

    @staticmethod
    def _add_blank(blanks: dict[str, BlankDict], new: BlankDict) -> None:
        """
        Merge one definition into the blank its slug names.

        Raises:
            ParseError: the slug is already defined with a different
                kind, or it is a repeated choice or numeric definition.
        """
        blank_id = new["id"]
        existing = blanks.get(blank_id)
        if existing is None:
            blanks[blank_id] = new
            return
        if existing["type"] != new["type"]:
            raise ParseError(
                f"blank {blank_id!r} is defined both as {existing['type']} "
                f"and as {new['type']}"
            )
        if existing["type"] != "short-answer":
            raise ParseError(f"repeated definition of blank {blank_id!r}")
        for key, value in new.items():
            if key not in ("id", "type"):
                # The caller rejects a repeated `accept` or `reject`
                # definition of a short-answer blank before it gets here.
                _set_field(existing, key, value)

    def parse_answer_key(self) -> list[Node]:
        """
        Look for the optional `## [answer-key]` section among the
        remaining nodes. Only ever called for essay questions -- other
        types have no answer-key syntax and epilogue swallows everything
        after their body verbatim.

        Returns:
            The nodes that should still be treated as epilogue (i.e.
            everything before the heading, if one was found, or all
            remaining nodes otherwise). Does not advance `self.pos`.
        """

        remaining = self.reader.children[self.pos :]
        for i, node in enumerate(remaining):
            if node.type == "heading" and node.tag == "h2":
                text = self.reader.raw_text(node)
                if ANSWER_KEY_RE.match(text):
                    answer_blocks = remaining[i + 1 :]
                    for later in answer_blocks:
                        if (
                            later.type == "heading"
                            and later.tag == "h2"
                            and ANSWER_KEY_RE.match(self.reader.raw_text(later))
                        ):
                            raise ParseError(
                                "a question defines at most one [answer-key] section"
                            )
                    answer_text = self.reader.join_blocks(answer_blocks)
                    if answer_text:
                        self.state["answerKey"] = answer_text
                    return remaining[:i]
        return remaining

    def apply_type_specific_frontmatter(self, question_type: object) -> None:
        if question_type in GRADED_QUESTION_TYPES:
            for key in ("shuffle", "grading"):
                if key in self.frontmatter and key not in self.state:
                    self.state[key] = self.frontmatter[key]

    #
    # Main driver
    #
    def parse_question(self) -> QuestionDict:
        """
        Parse the question document this instance was constructed with.

        Raises:
            MissingField: If the question has no stem.
            ParseError: If the body does not match any known question
                shape.
            IncompleteQuestion: If a bracket-list body's type cannot be
                inferred and none is declared in frontmatter.
        """

        self.state.update(common_frontmatter(self.frontmatter, self.comment))
        if "weight" in self.frontmatter:
            self.state["weight"] = self.frontmatter["weight"]

        if not self.reader.children:
            raise MissingField("stem")

        self.check_tag_lines()
        body_start = self.find_body_start()
        if body_start == 0:
            raise MissingField("stem")

        intro_blocks = [self.read() for _ in range(body_start)]
        stem_text, inline_slug = self.split_intro(intro_blocks)

        if inline_slug and "id" in self.state:
            self.diagnostics.append(_redundant_id(self.state["id"], inline_slug))
        elif inline_slug:
            self.state["id"] = inline_slug
        self.state["stem"] = stem_text

        question_type = self.frontmatter.get("type")
        node = self.peek()
        epilogue_nodes: list[Node] | None = None

        if node is None:
            # `find_body_start` found no body: a fill-in stem with no blank.
            # The schema reports the empty `blanks` list.
            question_type = "fill-in"
            self.state["blanks"] = []
        elif node.type == "bullet_list":
            # Ambiguous between multiple-choice / multiple-selection /
            # true-false: infer from the bracket values unless declared.
            body_node = self.expect("bullet_list", "malformed choice list")
            raw_choices = self.parse_item_list(body_node)
            values = [c.value for c in raw_choices]
            question_type = question_type or _infer_choice_type(values)
            self.parse_choice_body(as_choice_type(question_type), raw_choices)
        else:
            body_node = self.expect("paragraph", "unrecognized question body")
            text = self.reader.raw_text(body_node)
            tag = read_body_tag(text)
            match tag:
                case EssayTag():
                    question_type = question_type or "essay"
                    self.parse_essay_body()
                case OrderingTag():
                    question_type = question_type or "ordering"
                    self.check_ordering_tag(tag)
                    epilogue_nodes = self.parse_ordering_body(body_node)
                case ShortAnswerTag():
                    question_type = question_type or "short-answer"
                    self.parse_short_answer_body(tag, body_node)
                case NumericTag():
                    question_type = question_type or "numeric"
                    self.parse_numeric_body(tag)
                case (
                    ChoiceBlankTag()
                    | NumericBlankTag()
                    | ShortAnswerBlankTag()
                    | UnrecognizedBlankTag()
                ):
                    question_type = question_type or "fill-in"
                    self.parse_fill_in_body(tag, body_node)
                case None:  # pragma: no cover - find_body_start already filtered this
                    raise IncompleteQuestion()
                case _:
                    assert_never(tag)

        self.state["type"] = question_type

        epilogue_blocks = (
            self.parse_answer_key()
            if question_type == "essay"
            else epilogue_nodes
            if epilogue_nodes is not None
            else self.reader.children[self.pos :]
        )
        self.report_detached_tags(epilogue_blocks, fill_in=question_type == "fill-in")
        if epilogue_blocks:
            epilogue_text = self.reader.join_blocks(epilogue_blocks)
            if epilogue_text:
                self.state["epilogue"] = epilogue_text

        self.apply_type_specific_frontmatter(question_type)

        # The one cast of the parser: a `type` forced by the frontmatter can
        # contradict the body, so the document is checked by the schema, not
        # by construction.
        return cast(QuestionDict, self.state)


def _blank_index(blanks: Mapping[str, BlankDict], blank_id: str) -> int:
    """The index `blank_id` has, or will have, in the `blanks` list."""
    return list(blanks).index(blank_id) if blank_id in blanks else len(blanks)


def _set_field(blank: BlankDict, key: str, value: object) -> None:
    """
    Set a field of a blank by name. The keys come from the frontmatter
    and from another definition of the same blank, so a blank of the wrong
    kind can get a field: the schema rejects it.
    """
    cast("dict[str, object]", blank)[key] = value


#: Readable names of the blocks that can start a pattern item.
_BLOCK_NAMES = {
    "blockquote": "block quote",
    "heading": "heading",
    "bullet_list": "list",
    "ordered_list": "list",
    "fence": "fenced code block",
    "code_block": "code block",
    "html_block": "HTML block",
    "hr": "thematic break",
}


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


def _setext_message(text: str) -> str:
    """The error for a line of `text` that a setext underline turned into a heading."""
    return (
        f"the line {text!r} became a setext heading because the next line is "
        "'---' or '==='; add a blank line between them"
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

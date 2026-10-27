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
from collections.abc import Mapping
from typing import assert_never, cast

from markdown_it.tree import SyntaxTreeNode as Node

from .._diagnostics import Diagnostic
from .._markdown import SLUG_BODY_RE
from ..errors import (
    IncompleteQuestion,
    MissingField,
    ParseError,
)
from ..types import (
    QuestionDict,
)
from ._blocks import (
    BlockCursor,
    BlockReader,
    parse_item_list,
    setext_message,
)
from ._choices import (
    ChoiceType,
    RawChoice,
    SLUG_PREFIX_RE,
    _infer_choice_type,
    as_choice_type,
    build_choices,
    match_choice_marker,
)
from ._frontmatter import (
    GRADED_QUESTION_TYPES,
    _extract_comment,
    common_frontmatter,
    _load_frontmatter_yaml,
    _invalid_frontmatter_fields,
    _split_frontmatter,
)
from ._numeric import _parse_numeric_expression, numeric_fields
from ._fill_in import parse_fill_in_body
from ._short_answer import parse_short_answer_body
from ._ordering import check_ordering_tag, parse_ordering_body
from ._tags import (
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
    read_body_tag,
    tag_lines,
)

__all__ = [
    "parse_question",
]

#
# Constants
#

#: A raw line that looks like the first line of a choice: a list marker
#: and a choice marker (choices.md, "Choice marker").
BRACKET_ITEM_RE = re.compile(r"^[*+-][ \t]+\[[^\]\r\n]*\](?![(\[])")
ANSWER_KEY_RE = re.compile(r"^\[answer-key\]$")

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
@dataclass
class MDQParser:
    """
    A recursive-descent parser for one MDQ question document.

    Holds a cursor over the question's markdown-it block tree, the parsed
    frontmatter (`frontmatter`/`comment`), and the output document being
    built up (`state`). Grammar-rule methods
    read from the cursor and write into `doc` as they go, which avoids
    threading `(children, lines, index, front, doc)` through a long chain
    of free functions.

    Attributes:
        frontmatter: The question's parsed YAML frontmatter.
        comment: The leading `#`-comment block from the frontmatter, if any.
        reader: The block reader over the body, after the frontmatter.
        cursor: The cursor over `reader`; it shares `diagnostics`.
        state: The output document being assembled.
    """

    src: str

    #: Accumulate the currently parsed object
    state: dict[str, object] = field(default_factory=dict, init=False)

    #: Frontmatter for the current element
    frontmatter: Mapping[str, object] = field(default_factory=dict, init=False)

    #: Frontmatter comment
    comment: str | None = field(default=None, init=False)

    #: The body blocks, after the frontmatter.
    reader: BlockReader = field(init=False)

    #: The cursor over the body blocks.
    cursor: BlockCursor = field(init=False)

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
        self.cursor = BlockCursor(self.reader, self.diagnostics)

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


    def find_body_start(self) -> int:
        """
        Return the index of the first body node in `self.reader.children`.

        Scans from the start of the document (independent of `self.cursor.pos`,
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
                message=setext_message(setext_tag),
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





    def parse_answer_key(self) -> list[Node]:
        """
        Look for the optional `## [answer-key]` section among the
        remaining nodes. Only ever called for essay questions -- other
        types have no answer-key syntax and epilogue swallows everything
        after their body verbatim.

        Returns:
            The nodes that should still be treated as epilogue (i.e.
            everything before the heading, if one was found, or all
            remaining nodes otherwise). Does not advance `self.cursor.pos`.
        """

        remaining = self.reader.children[self.cursor.pos :]
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

        intro_blocks = [self.cursor.read() for _ in range(body_start)]
        stem_text, inline_slug = self.split_intro(intro_blocks)

        if inline_slug and "id" in self.state:
            self.diagnostics.append(_redundant_id(self.state["id"], inline_slug))
        elif inline_slug:
            self.state["id"] = inline_slug
        self.state["stem"] = stem_text

        question_type = self.frontmatter.get("type")
        node = self.cursor.peek()
        epilogue_nodes: list[Node] | None = None

        if node is None:
            # `find_body_start` found no body: a fill-in stem with no blank.
            # The schema reports the empty `blanks` list.
            question_type = "fill-in"
            self.state["blanks"] = []
        elif node.type == "bullet_list":
            # Ambiguous between multiple-choice / multiple-selection /
            # true-false: infer from the bracket values unless declared.
            body_node = self.cursor.expect("bullet_list", "malformed choice list")
            raw_choices = parse_item_list(self.reader, body_node)
            values = [c.value for c in raw_choices]
            question_type = question_type or _infer_choice_type(values)
            self.parse_choice_body(as_choice_type(question_type), raw_choices)
        else:
            body_node = self.cursor.expect("paragraph", "unrecognized question body")
            text = self.reader.raw_text(body_node)
            tag = read_body_tag(text)
            match tag:
                case EssayTag():
                    question_type = question_type or "essay"
                    self.parse_essay_body()
                case OrderingTag():
                    question_type = question_type or "ordering"
                    check_ordering_tag(tag)
                    fields, epilogue_nodes = parse_ordering_body(
                        self.cursor, self.frontmatter, body_node
                    )
                    self.state.update(fields)
                case ShortAnswerTag():
                    question_type = question_type or "short-answer"
                    self.state.update(
                        parse_short_answer_body(
                            self.cursor, self.frontmatter, tag, body_node
                        )
                    )
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
                    self.state.update(
                        parse_fill_in_body(self.cursor, self.frontmatter, tag, body_node)
                    )
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
            else self.reader.children[self.cursor.pos :]
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














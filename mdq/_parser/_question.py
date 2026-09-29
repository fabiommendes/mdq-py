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
subtree for it. Plain prose blocks (preamble, stem, epilogue, choice/blank
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
from typing import Any, cast

from markdown_it.tree import SyntaxTreeNode as Node

from .._diagnostics import Diagnostic
from .._markdown import UNICODE_SPACE, md, split_lines
from ..errors import ConflictingAnswerKey, IncompleteQuestion, MissingField, ParseError
from ..types import (
    BlankDict,
    NumericBlankDict,
    QuestionDict,
    ScoredChoiceDict,
    ShortAnswerBlankDict,
)
from ._choices import (
    FALSE_LETTERS,
    PLAIN_ITEM_RE,
    RawChoice,
    SLUG_BODY_RE,
    SLUG_PREFIX_RE,
    _assign_choice_ids,
    _infer_choice_type,
    _pattern_entry,
    _score_from_value,
    _split_list_items,
    _strip_list_marker,
    parse_marker,
)
from ._frontmatter import (
    GRADED_QUESTION_TYPES,
    _copy_pattern_lists,
    _extract_comment,
    _load_frontmatter_yaml,
    _normalize_tags,
    _question_frontmatter_warnings,
    _split_frontmatter,
)
from ._numeric import _parse_numeric_expression
from ._ordering import (
    ORDERING_SECTION_RE,
    RawAlternative,
    RawLine,
    is_comment_block,
    join_prefixed_lines,
    ordering_alternative,
    ordering_code_lines,
    ordering_leveled,
    ordering_ul_lines,
    ordering_unit,
)

__all__ = ["parse_question", "reconstruct_blocks", "find_forbidden_elements"]

#
# Constants
#

# Body-start detection.
ESSAY_TAG_RE = re.compile(r"^\[essay\]$")
SHORT_ANSWER_RE = re.compile(
    r"^\[short-answer(?:/(?P<variant>accept|reject))?\][ \t]*:[ \t]*(?P<rest>.*)$"
)
#: The `UNIT` terminal of docs/references/grammar.md: any character
#: except a `UNICODE_SPACE` and the brackets `(`, `)`, `[`, `]`. It admits
#: `µm`, `°C`, `km/h`, `Ω`.
UNIT_RE = rf"[^()\[\]{UNICODE_SPACE}]+"
NUMERIC_TAG_RE = re.compile(
    rf"^\[numeric(?:\((?P<unit>{UNIT_RE})\))?\]:[ \t]*(?P<rest>.*)$"
)
# A blank definition tag. Deliberately permissive in `kind`: an
# unrecognized suffix must reach BLANK_KIND_RE and raise a real error,
# not fail to match and get swallowed by the epilogue.
BLANK_RE = re.compile(
    rf"^\[\^(?P<id>{SLUG_BODY_RE})(?:/(?P<kind>[^\]]+))?\]:[ \t]*(?P<rest>.*)$"
)
# Validates that suffix. Units attach to `numeric` and to nothing else,
# and the accept/reject sublists to `short-answer` and nothing else --
# both restrictions are enforced by this alternation's shape rather than
# by a follow-up check (fill-in.md#blank-definitions).
BLANK_KIND_RE = re.compile(
    rf"^(?:"
    rf"(?P<numeric>numeric)(?:\((?P<unit>{UNIT_RE})\))?"
    r"|(?P<short>short-answer)(?:/(?P<variant>accept|reject))?"
    r")$"
)
BRACKET_ITEM_RE = re.compile(r"^[*+-][ \t]*\[")
ANSWER_KEY_RE = re.compile(r"^\[answer-key\]$")
# The markers around the text of an ATX heading.
ATX_OPENING_RE = re.compile(r"^[ \t]*#{1,6}")
ATX_CLOSING_RE = re.compile(r"(?:[ \t]+#+)?[ \t]*$")
ORDERING_TAG_RE = re.compile(r"^\[ordering\]$")


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
        warnings: When given, an `unknown-frontmatter-key` `Diagnostic`
            is appended for every frontmatter key the parser does not
            consume, given the question's own type. Parsing never fails
            because of them.

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
        warnings.extend(_question_frontmatter_warnings(parser.frontmatter, doc["type"]))
    return doc


#
# Implementation
#
@dataclass
class MDQParser:
    """
    A recursive-descent parser for one MDQ question document.

    Holds a cursor (`children`/`lines`/`pos`) over the question's
    markdown-it block tree, the parsed frontmatter (`front`/`comment`),
    and the output document being built up (`doc`). Grammar-rule methods
    read from the cursor and write into `doc` as they go, which avoids
    threading `(children, lines, index, front, doc)` through a long chain
    of free functions.

    Attributes:
        frontmatter: The question's parsed YAML frontmatter.
        comment: The leading `#`-comment block from the frontmatter, if any.
        children: The body's top-level markdown-it block nodes.
        lines: The body's raw source lines, indexed by `node.map`.
        pos: Index of the next unread node in `children`.
        doc: The output document being assembled.
    """

    src: str

    #: Position in the token stream.
    pos: int = field(default=0, init=False)

    #: Accumulate the currently parsed object
    state: dict[str, Any] = field(default_factory=dict, init=False)

    #: Frontmatter for the current element
    frontmatter: dict[str, Any] = field(default_factory=dict, init=False)

    #: Frontmatter comment
    comment: str | None = field(default=None, init=False)

    #: Unprocessed md nodes.
    children: list[Node] = field(default_factory=list, init=False)

    #: File lines as strings. For rendering back to text.
    lines: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        frontmatter_text, body_text = _split_frontmatter(self.src)
        if frontmatter_text is not None:
            self.frontmatter = _load_frontmatter_yaml(frontmatter_text)
            self.comment = _extract_comment(frontmatter_text)
        else:
            self.frontmatter = {}
            self.comment = None

        tokens = md.parse(body_text)
        self.children = list(Node(tokens).children)
        self.lines = split_lines(body_text)

    #
    # Cursor primitives
    #
    def read(self) -> Node:
        """
        Consume and return the current node, advancing the cursor.

        Raises:
            ParseError: If the cursor is already exhausted.
        """

        node = self.seek()
        if node is None:
            raise ParseError("unexpected end of document")
        self.pos += 1
        return node

    def seek(self) -> Node | None:
        """
        Return the current node without consuming it, or None at the end.

        Despite the name, this is a non-consuming peek at the cursor's
        current position, not a `file.seek`-style jump to an arbitrary one.
        """

        if self.pos >= len(self.children):
            return None
        return self.children[self.pos]

    def expect(self, node_type: str, error_msg: str) -> Node:
        """
        Consume and return the current node if it has type `node_type`.

        Raises:
            ParseError: If the cursor is exhausted or the current node's
                type does not match `node_type`.
        """

        node = self.seek()
        if node is None or node.type != node_type:
            raise ParseError(error_msg, node)
        return self.read()

    def at_end(self) -> bool:
        """True once every child node has been consumed."""

        return self.pos >= len(self.children)

    #
    # Line/text reconstruction
    #
    def raw_lines(self, node: Node) -> list[str]:
        if node.map is None:
            return []
        start, end = node.map
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
            return content.replace("\n", " ")
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

    def join_blocks(self, nodes: list[Node]) -> str | None:
        if not nodes:
            return None
        return "\n\n".join(self.raw_text(n) for n in nodes)

    #
    # Frontmatter
    #

    def apply_common_frontmatter(self) -> None:
        front = self.frontmatter
        doc = self.state
        # Unconverted: `id: 2024` is not a string, and the model reports it
        # (base.md, "Frontmatter"). A null `id` is absent.
        if front.get("id") is not None:
            doc["id"] = front["id"]
        if "uuid" in front:
            doc["uuid"] = front["uuid"]
        if "title" in front:
            doc["title"] = front["title"]
        if "author" in front:
            doc["author"] = front["author"]
        if "locale" in front:
            doc["locale"] = front["locale"]
        if "tags" in front and front["tags"] is not None:
            doc["tags"] = _normalize_tags(front["tags"])
        if "meta" in front:
            doc["meta"] = front["meta"]
        if "weight" in front:
            doc["weight"] = front["weight"]

    #
    # Body-start / tag detection
    #
    def is_bracket_list(self, node: Node) -> bool:
        if node.type != "bullet_list":
            return False
        for item in node.children:
            first_line = self.raw_lines(item)[0] if item.map else ""
            if not BRACKET_ITEM_RE.match(first_line):
                return False
        return bool(node.children)

    def find_body_start(self) -> int:
        """
        Return the index of the first body node in `self.children`.

        Scans from the start of the document (independent of `self.pos`,
        which is still 0 at call time) for the first paragraph matching a
        known body tag, or the first bracket-led bullet list.

        Raises:
            MissingField: If no body node is found.
        """

        for i, child in enumerate(self.children):
            if child.type == "paragraph":
                text = self.raw_text(child)
                if _matches_tag(text):
                    return i
            elif self.is_bracket_list(child):
                return i
        raise MissingField("body")

    #
    # Intro / stem / preamble
    #
    def split_intro(
        self, intro_blocks: list[Node]
    ) -> tuple[str, str | None, str | None]:
        """
        Split the blocks preceding the body into (stem, preamble, slug).

        The stem is the last intro block; everything before it is the
        preamble. An inline `[slug]` prefix, if present, only ever
        appears on the *first* intro block -- which is the stem itself
        when there's no preamble, and the preamble's first block
        otherwise, in which case the stem is untouched.
        """

        stem_node = intro_blocks[-1]
        preamble_blocks = intro_blocks[:-1]

        first_node = intro_blocks[0]
        first_text = self.raw_text(first_node)
        slug_match = (
            SLUG_PREFIX_RE.match(first_text) if first_node.type == "paragraph" else None
        )
        inline_slug = None
        if slug_match:
            inline_slug = slug_match.group("slug")
            stripped_first_text = first_text[slug_match.end() :]
            stem_text = (
                stripped_first_text
                if first_node is stem_node
                else self.raw_text(stem_node)
            )
        else:
            stem_text = self.raw_text(stem_node)

        preamble_text = None
        if preamble_blocks:
            if slug_match and preamble_blocks[0] is first_node:
                preamble_text = "\n\n".join(
                    [first_text[slug_match.end() :]]
                    + [self.raw_text(n) for n in preamble_blocks[1:]]
                )
            else:
                preamble_text = self.join_blocks(preamble_blocks)

        return stem_text, preamble_text, inline_slug

    #
    # Choice/item-list parsing
    #
    def parse_item_list(self, node: Node) -> list[RawChoice]:
        raw_lines = self.raw_lines(node)
        return [self.parse_item(item) for item in _split_list_items(raw_lines)]

    def parse_item(self, item_lines: list[str]) -> RawChoice:
        value, explicit_id, rest = parse_marker(item_lines[0])
        return self.collect_item(item_lines, value, explicit_id, rest)

    def parse_plain_item(self, item_lines: list[str]) -> RawChoice:
        """
        Parse a list item carrying no `[value]` marker, e.g. a pattern line.

        Raises:
            ParseError: `item_lines` does not start with a list marker.
        """
        m = PLAIN_ITEM_RE.match(item_lines[0])
        if not m:
            raise ParseError(f"malformed list item: {item_lines[0]!r}")
        return self.collect_item(item_lines, "", None, m.group("rest"))

    def collect_item(
        self, item_lines: list[str], value: str, explicit_id: str | None, rest: str
    ) -> RawChoice:
        """Split an item's continuation lines into text, `>` feedback and `!` comments."""
        text_lines = [rest] if rest.strip(" \t") else []
        feedback_lines: list[str] = []
        comment_lines: list[str] = []
        mode = "text"

        for line in item_lines[1:]:
            stripped = line.strip(" \t")
            if stripped.startswith(">"):
                mode = "feedback"
                feedback_lines.append(stripped[1:].strip(" \t"))
            elif stripped.startswith("!"):
                mode = "comment"
                comment_lines.append(stripped[1:].strip(" \t"))
            elif mode == "text":
                text_lines.append(stripped)
            elif mode == "feedback":
                feedback_lines.append(stripped)
            else:
                comment_lines.append(stripped)

        choice = RawChoice(value, explicit_id, " ".join(t for t in text_lines if t))
        if any(feedback_lines):
            choice.feedback = " ".join(t for t in feedback_lines if t)
        if any(comment_lines):
            choice.comment = " ".join(t for t in comment_lines if t)
        return choice

    #
    # Per-type body fillers
    #
    def parse_choice_body(
        self, question_type: str, raw_choices: list[RawChoice]
    ) -> None:
        ids = _assign_choice_ids(raw_choices)
        choices = []
        for choice, choice_id in zip(raw_choices, ids):
            entry: dict[str, Any] = {"text": choice.text}
            if choice_id is not None:
                entry["id"] = choice_id
            if question_type == "multiple-choice":
                # Always explicit (see multiple-choice/simple.yaml): score
                # is emitted even when 0, not just for correct/partial
                # choices.
                entry["score"] = _score_from_value(choice.value)
            elif question_type == "multiple-selection":
                if choice.value.lower() == "x":
                    entry["correct"] = True
            elif question_type == "true-false":
                letter = choice.value
                # TRUE and PROVISIONAL letters both mean true; only FALSE
                # letters mean false (docs/question-types/true-false.md).
                entry["correct"] = letter.lower() not in FALSE_LETTERS
                if letter:
                    entry["marker"] = letter
            if choice.feedback:
                entry["feedback"] = choice.feedback
            if choice.comment:
                entry["comment"] = choice.comment
            choices.append(entry)
        self.state["choices"] = choices

    def parse_essay_body(self) -> None:
        front = self.frontmatter
        if "input" in front:
            self.state["input"] = front["input"]
        if "highlight" in front:
            self.state["highlight"] = front["highlight"]

    def parse_ordering_body(self) -> None:
        """
        Fill `lines`, `extra`, `accept` and `reject` from an `[ordering]`
        block and its `## [extra]`/`## [accept]`/`## [reject]` sections.

        The indentation unit is inferred once across every block of the
        question (ordering.md#indentation), so every block is read raw
        first and only converted to `[level, text]` pairs at the end. A
        declared `content`/`highlight`/`indentation`/`unmatched`/
        `normalizations` wins over what the body implies, the same way
        `parse_essay_body` copies `input`/`highlight`.

        Raises:
            ParseError: the block after `[ordering]` (or a section) is
                neither a fenced code block nor a `ul` list, a section's
                content is not the same kind as `[ordering]`'s, two
                `## [extra]` sections are declared, or a section's
                observations carry more than one feedback/comment block
                or interleave the two.
        """
        main_kind, main_highlight, main_raw = self.parse_ordering_content()

        extra_raw: list[RawLine] | None = None
        accept_raw: list[RawAlternative] = []
        reject_raw: list[RawAlternative] = []

        while True:
            node = self.seek()
            if node is None or node.type != "heading" or node.tag != "h2":
                break
            m = ORDERING_SECTION_RE.match(self.raw_text(node))
            if m is None:
                break
            self.read()
            name = m.group("name")
            if name == "extra":
                if extra_raw is not None:
                    raise ParseError("a question defines at most one [extra] section")
                kind, _highlight, extra_raw = self.parse_ordering_content()
                if kind != main_kind:
                    raise ParseError(
                        "[extra] must use the same content type as [ordering]"
                    )
            else:
                feedback, comment = self.parse_ordering_observations()
                kind, _highlight, raw = self.parse_ordering_content()
                if kind != main_kind:
                    raise ParseError(
                        f"[{name}] must use the same content type as [ordering]"
                    )
                target = accept_raw if name == "accept" else reject_raw
                target.append(RawAlternative(raw, feedback, comment))

        unit = ordering_unit(
            [indent for indent, _ in main_raw]
            + [indent for indent, _ in (extra_raw or [])]
            + [indent for alt in (*accept_raw, *reject_raw) for indent, _ in alt.lines]
        )

        front = self.frontmatter
        doc = self.state
        doc["content"] = front.get("content", main_kind)
        highlight = front["highlight"] if "highlight" in front else main_highlight
        if highlight:
            doc["highlight"] = highlight
        if "indentation" in front:
            doc["indentation"] = front["indentation"]
        if "unmatched" in front:
            doc["unmatched"] = front["unmatched"]
        if front.get("normalizations") is not None:
            doc["normalizations"] = _normalize_tags(front["normalizations"])

        doc["lines"] = ordering_leveled(main_raw, unit)
        if extra_raw is not None:
            doc["extra"] = ordering_leveled(extra_raw, unit)
        if accept_raw:
            doc["accept"] = [ordering_alternative(alt, unit) for alt in accept_raw]
        if reject_raw:
            doc["reject"] = [ordering_alternative(alt, unit) for alt in reject_raw]

    def parse_ordering_content(self) -> tuple[str, str | None, list[RawLine]]:
        """
        Read the fenced code block or `ul` list holding one content
        block's raw `(indent, text)` lines, along with the content kind
        and highlight language it implies.

        Raises:
            ParseError: the current node is neither a fence nor a
                bullet list.
        """
        node = self.seek()
        if node is None or node.type not in ("fence", "bullet_list"):
            raise ParseError(
                "an [ordering] block must be followed by a code block or a list",
                node,
            )
        self.read()
        if node.type == "fence":
            return "code", node.info.strip() or None, ordering_code_lines(node.content)
        return "text", None, ordering_ul_lines(self.raw_lines(node))

    def parse_ordering_observations(self) -> tuple[str | None, str | None]:
        """
        Consume an accept/reject section's optional feedback (`>`) and
        comment (`!`) blocks, in either order.

        markdown-it gives a `blockquote` node for the feedback and an
        ordinary `paragraph` whose raw lines start with `!` for the
        comment -- CommonMark has no idea these two are related, so
        telling them apart from each other, and from the section's own
        content block that follows, is just node type and a prefix
        check, not re-parsing.

        Raises:
            ParseError: a section carries more than one feedback or
                comment block, or the two interleave.
        """
        feedback = comment = None
        for _ in range(2):
            node = self.seek()
            if node is not None and node.type == "blockquote" and feedback is None:
                feedback = join_prefixed_lines(self.raw_lines(node), ">")
                self.read()
            elif (
                node is not None
                and node.type == "paragraph"
                and comment is None
                and is_comment_block(self.raw_lines(node))
            ):
                comment = join_prefixed_lines(self.raw_lines(node), "!")
                self.read()
            else:
                break

        node = self.seek()
        if node is not None and (
            node.type == "blockquote"
            or (node.type == "paragraph" and is_comment_block(self.raw_lines(node)))
        ):
            raise ParseError(
                "an accept/reject section carries at most one feedback and one "
                "comment block, and they must not interleave",
                node,
            )
        return feedback, comment

    def parse_short_answer_body(self, tag_text: str) -> None:
        m = SHORT_ANSWER_RE.match(tag_text)
        assert m
        variant = m.group("variant")
        if "diacritics" in self.frontmatter:
            self.state["diacritics"] = self.frontmatter["diacritics"]
        if variant in ("accept", "reject"):
            self.parse_short_answer_pattern_blocks(tag_text)
            return

        rest = m.group("rest").strip(" \t")

        value: str | None = None
        values: list[str] | None = None
        if rest:
            value = rest
        else:
            node = self.seek()
            if node is not None and node.type == "bullet_list":
                self.read()
                raw_lines = self.raw_lines(node)
                values = [
                    " ".join(_strip_list_marker(line) for line in item)
                    for item in _split_list_items(raw_lines)
                ]

        front = self.frontmatter
        doc = self.state
        if "openEnded" in front:
            doc["openEnded"] = front["openEnded"]
        _copy_pattern_lists(front, doc)

        regex = front.get("regex")
        if (
            regex is None
            and value
            and value.startswith("/")
            and value.endswith("/")
            and len(value) >= 2
        ):
            regex = value[1:-1]
            value = None

        if regex is not None:
            doc["regex"] = regex
        elif values is not None:
            doc["oneOf"] = values
        elif value is not None:
            doc["oneOf"] = [value]

        self.parse_trailing_pattern_blocks()

        # A bare block is open-ended only when nothing grades it: no
        # pattern in the body, in a trailing block or in the frontmatter
        # (short-answer.md, "Fully manual"). preAccept/preReject only
        # validate the form of a response, so they do not count.
        if not any(key in doc for key in ("oneOf", "regex", "accept", "reject", "openEnded")):
            doc["openEnded"] = True

    def parse_trailing_pattern_blocks(self) -> None:
        """
        Consume `[short-answer/accept|reject]` blocks after a simple block.

        Raises:
            ParseError: the following block is another `[short-answer]`
                block, which the simple block already is.
        """
        node = self.seek()
        if node is None or node.type != "paragraph":
            return
        m = SHORT_ANSWER_RE.match(self.raw_text(node))
        if m is None:
            return
        if m.group("variant") not in ("accept", "reject"):
            raise ParseError("a question defines at most one [short-answer] block")
        self.read()
        self.parse_short_answer_pattern_blocks(self.raw_text(node))

    def parse_short_answer_pattern_blocks(self, tag_text: str) -> None:
        """
        Fill `accept`/`reject` from a run of `[short-answer/<variant>]` blocks.

        Raises:
            ParseError: a variant is declared twice, or a block is not
                followed by the bullet list holding its patterns.
        """
        text = tag_text
        while True:
            m = SHORT_ANSWER_RE.match(text)
            if m is None:
                break
            variant = m.group("variant")
            if variant not in ("accept", "reject"):
                raise ParseError(
                    "a [short-answer] block cannot follow "
                    f"[short-answer/{variant or 'accept'}]"
                )
            if variant in self.state:
                raise ParseError(f"repeated [short-answer/{variant}] block")
            if variant in self.frontmatter:
                raise ConflictingAnswerKey(
                    f"'{variant}' is declared both in the frontmatter and as "
                    f"a [short-answer/{variant}] body block"
                )
            if m.group("rest").strip(" \t"):
                raise ParseError(
                    f"[short-answer/{variant}] takes a list, not inline text"
                )

            node = self.seek()
            if node is None or node.type != "bullet_list":
                raise ParseError(f"[short-answer/{variant}] must be followed by a list")
            self.read()
            self.state[variant] = [
                _pattern_entry(self.parse_plain_item(item))
                for item in _split_list_items(self.raw_lines(node))
            ]

            node = self.seek()
            if node is None or node.type != "paragraph":
                break
            text = self.raw_text(node)
            if not SHORT_ANSWER_RE.match(text):
                break
            self.read()

        _copy_pattern_lists(self.frontmatter, self.state)

    def parse_numeric_body(self, tag_text: str) -> None:
        m = NUMERIC_TAG_RE.match(tag_text)
        assert m
        unit = m.group("unit")
        parsed = _parse_numeric_expression(m.group("rest"))
        front = self.frontmatter
        doc = self.state

        doc["answer"] = parsed["answer"]
        if unit and "unit" not in front:
            doc["unit"] = unit
        if "domain" in front:
            doc["domain"] = front["domain"]
        elif "domain" in parsed:
            doc["domain"] = parsed["domain"]
        if "decimalPlaces" in front:
            doc["decimalPlaces"] = front["decimalPlaces"]
        elif "decimalPlaces" in parsed:
            doc["decimalPlaces"] = parsed["decimalPlaces"]
        if "unit" in front:
            doc["unit"] = front["unit"]
        if "tolerance" in parsed:
            doc["tolerance"] = parsed["tolerance"]

    def parse_fill_in_body(self, tag_text: str) -> None:
        """
        Fill `blanks` from a run of `[^id...]:` definitions.

        A slug may be defined more than once -- a short answer blank
        spreads its answer, its accept list and its reject list over
        separate definitions -- so definitions accumulate into one blank
        per slug, keyed by the order the slug is first seen.

        Raises:
            ParseError: an unrecognized or misplaced tag suffix, a slug
                whose definitions disagree about the blank's kind, or a
                repeated definition of the same form.
        """
        front = self.frontmatter
        if "shuffle" in front:
            self.state["shuffle"] = front["shuffle"]
        if "diacritics" in front:
            self.state["diacritics"] = front["diacritics"]

        blanks: dict[str, BlankDict] = {}
        text = tag_text
        while True:
            m = BLANK_RE.match(text)
            if not m:
                break
            blank_id = m.group("id")
            kind = m.group("kind")
            rest = m.group("rest").strip(" \t")

            unit = variant = None
            if kind is None:
                blank_type = None
            else:
                km = BLANK_KIND_RE.match(kind)
                if km is None:
                    raise ParseError(f"unrecognized blank definition: {text!r}")
                blank_type = "numeric" if km.group("numeric") else "short-answer"
                unit = km.group("unit")
                variant = km.group("variant")

            next_node = self.seek()
            if (
                blank_type is None
                and not rest
                and next_node is not None
                and next_node.type == "bullet_list"
            ):
                self.read()
                raw_choices = self.parse_item_list(next_node)
                ids = _assign_choice_ids(raw_choices)
                choices: list[ScoredChoiceDict] = []
                for choice, choice_id in zip(raw_choices, ids):
                    entry: ScoredChoiceDict = {"text": choice.text}
                    if choice_id is not None:
                        entry["id"] = choice_id
                    score = _score_from_value(choice.value)
                    if score:
                        entry["score"] = score
                    if choice.feedback:
                        entry["feedback"] = choice.feedback
                    if choice.comment:
                        entry["comment"] = choice.comment
                    choices.append(entry)
                self._add_blank(
                    blanks,
                    {"id": blank_id, "type": "multiple-choice", "choices": choices},
                )
            elif blank_type == "numeric":
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
                if "domain" in parsed:
                    blank["domain"] = parsed["domain"]
                if "decimalPlaces" in parsed:
                    blank["decimalPlaces"] = parsed["decimalPlaces"]
                if "tolerance" in parsed:
                    blank["tolerance"] = parsed["tolerance"]
                self._add_blank(blanks, blank)
            elif blank_type == "short-answer" and variant is not None:
                if rest:
                    raise ParseError(
                        f"[^{blank_id}/short-answer/{variant}] takes a list, "
                        "not inline text"
                    )
                node = self.seek()
                if node is None or node.type != "bullet_list":
                    raise ParseError(
                        f"[^{blank_id}/short-answer/{variant}] must be "
                        "followed by a list"
                    )
                self.read()
                patterns = [
                    _pattern_entry(self.parse_plain_item(item))
                    for item in _split_list_items(self.raw_lines(node))
                ]
                list_blank: ShortAnswerBlankDict = {
                    "id": blank_id,
                    "type": "short-answer",
                }
                if variant == "accept":
                    list_blank["accept"] = patterns
                else:
                    list_blank["reject"] = patterns
                self._add_blank(blanks, list_blank)
            elif blank_type == "short-answer":
                # `/re/` with no trailing flags is the one form with a
                # field of its own; everything else -- a plain literal, a
                # backtick-enclosed exact answer, a flagged regex -- is a
                # pattern string and goes to `oneOf` verbatim.
                if rest.startswith("/") and rest.endswith("/") and len(rest) >= 2:
                    entry_blank: ShortAnswerBlankDict = {
                        "id": blank_id,
                        "type": "short-answer",
                        "regex": rest[1:-1],
                    }
                else:
                    entry_blank = {
                        "id": blank_id,
                        "type": "short-answer",
                        "oneOf": [rest],
                    }
                self._add_blank(blanks, entry_blank)
            else:
                raise ParseError(f"unrecognized blank definition: {text!r}")

            node = self.seek()
            if node is None or node.type != "paragraph":
                break
            text = self.raw_text(node)
            if not BLANK_RE.match(text):
                break
            self.read()

        self.state["blanks"] = list(blanks.values())

    @staticmethod
    def _add_blank(blanks: dict[str, BlankDict], new: BlankDict) -> None:
        """
        Merge one definition into the blank its slug names.

        Raises:
            ParseError: the slug is already defined with a different
                kind, or this form of definition is already present.
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
            if key in ("id", "type"):
                continue
            if key in existing:
                raise ParseError(
                    f"repeated {key!r} definition for blank {blank_id!r}"
                )
            existing[key] = value  # type: ignore[literal-required]

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

        remaining = self.children[self.pos :]
        for i, node in enumerate(remaining):
            if node.type == "heading" and node.tag == "h2":
                text = self.raw_text(node)
                if ANSWER_KEY_RE.match(text):
                    answer_blocks = remaining[i + 1 :]
                    answer_text = self.join_blocks(answer_blocks)
                    if answer_text:
                        self.state["answerKey"] = answer_text
                    return remaining[:i]
        return remaining

    def apply_type_specific_frontmatter(self, question_type: str) -> None:
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

        if self.comment:
            self.state["comment"] = self.comment
        self.apply_common_frontmatter()

        if not self.children:
            raise MissingField("stem")

        body_start = self.find_body_start()
        if body_start == 0:
            raise MissingField("stem")

        intro_blocks = [self.read() for _ in range(body_start)]
        stem_text, preamble_text, inline_slug = self.split_intro(intro_blocks)

        if "id" not in self.state and inline_slug:
            self.state["id"] = inline_slug
        if preamble_text:
            self.state["preamble"] = preamble_text
        self.state["stem"] = stem_text

        question_type = self.frontmatter.get("type")
        node = self.seek()
        assert node is not None

        if node.type == "bullet_list":
            # Ambiguous between multiple-choice / multiple-selection /
            # true-false: infer from the bracket values unless declared.
            body_node = self.expect("bullet_list", "malformed choice list")
            raw_choices = self.parse_item_list(body_node)
            values = [c.value for c in raw_choices]
            question_type = question_type or _infer_choice_type(values)
            if not question_type:
                raise IncompleteQuestion()
            self.parse_choice_body(question_type, raw_choices)
        else:
            body_node = self.expect("paragraph", "unrecognized question body")
            text = self.raw_text(body_node)
            tag = _matches_tag(text)
            if tag == "essay":
                question_type = question_type or "essay"
                self.parse_essay_body()
            elif tag == "ordering":
                question_type = question_type or "ordering"
                self.parse_ordering_body()
            elif tag == "short-answer":
                question_type = question_type or "short-answer"
                self.parse_short_answer_body(text)
            elif tag == "numeric":
                question_type = question_type or "numeric"
                self.parse_numeric_body(text)
            elif tag == "blank":
                question_type = question_type or "fill-in"
                self.parse_fill_in_body(text)
            else:  # pragma: no cover - find_body_start already filtered this
                raise IncompleteQuestion()

        self.state["type"] = question_type

        epilogue_blocks = (
            self.parse_answer_key()
            if question_type == "essay"
            else self.children[self.pos :]
        )
        if epilogue_blocks:
            epilogue_text = self.join_blocks(epilogue_blocks)
            if epilogue_text:
                self.state["epilogue"] = epilogue_text

        self.apply_type_specific_frontmatter(question_type)

        return cast(QuestionDict, self.state)


def _matches_tag(text: str) -> str | None:
    """Return which known body/blank tag `text` looks like, if any."""

    if ESSAY_TAG_RE.match(text):
        return "essay"
    if ORDERING_TAG_RE.match(text):
        return "ordering"
    if SHORT_ANSWER_RE.match(text):
        return "short-answer"
    if NUMERIC_TAG_RE.match(text):
        return "numeric"
    if BLANK_RE.match(text):
        return "blank"
    return None


#
# Block reconstruction, shared with mdq.models
#
def reconstruct_blocks(src: str) -> list[tuple[str, str]]:
    """
    Parse `src` as a standalone sequence of top-level Markdown blocks and
    reconstruct each one exactly as it would read after being embedded in
    a full MDQ document and parsed back out.

    This is `MDQParser.raw_text`, applied to every top-level block `src`
    parses into: a plain paragraph's soft-wrapped lines collapse to
    single spaces, while a list, blockquote, heading or code block is
    reproduced byte-for-byte. It exists so `mdq.models` can canonicalize
    a `preamble`/`epilogue`/`stem` field into the fixed point a
    render-then-parse round trip actually produces, using the parser's
    own reconstruction rules instead of a second, drifting copy of them.

    Args:
        src: Markdown source for a preamble, epilogue, or stem -- a
            sequence of block elements with no YAML frontmatter of its
            own (a bare `---` at the very start would be misread as one,
            but no MDQ block legitimately starts with a thematic break).

    Returns:
        One `(node_type, text)` pair per top-level block found in `src`,
        in source order.
    """
    reader = MDQParser(src)
    return [(node.type, reader.raw_text(node)) for node in reader.children]


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
    return text.lstrip(" \t").startswith("[")


def find_forbidden_elements(
    src: str, *, allow_first_paragraph_bracket: bool = False
) -> list[str]:
    """
    base.md, "Forbidden elements": return a human-readable description of
    every forbidden top-level block construct in `src` -- a preamble,
    stem, or epilogue field, checked on its own.

    The forbidden constructs are: an H1 heading; a heading starting with
    optional whitespace and `[`; an unordered list whose items all start
    with optional whitespace and `[`; and a paragraph starting with
    optional whitespace and `[`, unless it is immediately followed by
    `^` (the fill-in blank marker syntax) or -- see
    `allow_first_paragraph_bracket` -- it is `src`'s own first block (the
    slug syntax, base.md "Slug").

    Args:
        src: Markdown source for one field -- no YAML frontmatter.
        allow_first_paragraph_bracket: Exempt a leading `[...]` paragraph
            as a possible slug. Only the combined preamble+stem
            sequence's own first block qualifies -- pass `True` for
            whichever of `preamble`/`stem` is first when the other is
            absent or empty, `False` for everything else (including the
            epilogue, which is never that first block).

    Returns:
        One description per forbidden block found, in source order.
        Empty when `src` is blank or holds nothing forbidden.
    """
    if not src.strip():
        return []

    reader = MDQParser(src)
    forbidden: list[str] = []
    for index, node in enumerate(reader.children):
        if node.type == "heading":
            if node.tag == "h1":
                forbidden.append("an H1 heading")
            elif _starts_with_bracket(reader.raw_text(node)):
                forbidden.append("a heading starting with '['")
            continue

        if node.type == "bullet_list" and reader.is_bracket_list(node):
            forbidden.append("an unordered list whose items all start with '['")
            continue

        if node.type == "paragraph":
            text = reader.raw_text(node)
            stripped = text.lstrip(" \t")
            if not stripped.startswith("["):
                continue
            if stripped.startswith("[^"):
                continue
            if index == 0 and allow_first_paragraph_bracket:
                continue
            forbidden.append("a paragraph starting with '['")

    return forbidden

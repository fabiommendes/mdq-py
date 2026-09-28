"""
Markdown-level helpers shared by `mdq.parser` and `mdq.models`.

`md` is the one `markdown_it.MarkdownIt` instance every MDQ document is
parsed with -- `mdq.parser.MDQParser` builds its block tree from it, and
the two functions below use it (directly, or through `MDQParser`) to
re-read raw Markdown outside the question grammar: reconstructing a
preamble/epilogue/stem field to the fixed point a render-then-parse
round trip produces (`reconstruct_blocks`, used by
`mdq.models.normalize_paragraphs`), and checking one of those fields for
constructs `docs/question-types/base.md` forbids
(`find_forbidden_elements`) or a misplaced fill-in blank marker
(`find_misplaced_blank_markers`).

`reconstruct_blocks` and `find_forbidden_elements` import `MDQParser`
from `mdq.parser` inside the function body rather than at module level,
since `mdq.parser` imports `md` from here -- a module-level import
either way would be circular.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token

__all__ = [
    "md",
    "reconstruct_blocks",
    "find_forbidden_elements",
    "find_misplaced_blank_markers",
]

md = MarkdownIt("gfm-like")

# MDQ's own tags (`[short-answer]: ...`, `[numeric]: ...`, `[^blank]: ...`)
# are syntactically indistinguishable from CommonMark link reference
# definitions (`[label]: destination`), which are otherwise consumed
# silently with no token emitted at all. Disable that rule so these lines
# survive as ordinary paragraphs for us to pattern-match.
md.block.ruler.disable("reference")


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
    from .parser import MDQParser

    reader = MDQParser(src)
    return [(node.type, reader.raw_text(node)) for node in reader.children]


def _starts_with_bracket(text: str) -> bool:
    return text.lstrip().startswith("[")


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

    from .parser import MDQParser

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
            stripped = text.lstrip()
            if not stripped.startswith("["):
                continue
            if stripped.startswith("[^"):
                continue
            if index == 0 and allow_first_paragraph_bracket:
                continue
            forbidden.append("a paragraph starting with '['")

    return forbidden


#: `[^id]` markers, as written in a fill-in stem -- duplicated from
#: `mdq.models._BLANK_MARKER_RE` (structurally identical, kept separate
#: since the two modules check different things: `mdq.models` cares only
#: about which ids are referenced, this module about where in the markup
#: a marker sits).
_BLANK_MARKER_RE = re.compile(r"\[\^([^\]]+)\]")


def find_misplaced_blank_markers(text: str) -> list[str]:
    """
    fill-in.md:301: a `[^id]` marker naming a blank may only appear in a
    plain text run of a paragraph.

    At the block level, the paragraph must sit at the top of the stem: a
    marker in a heading, list item, table cell or blockquote is misplaced.
    At the inline level, a marker inside emphasis, a strong span or a link
    is misplaced. Code (fenced or inline) is literal text, so a marker in
    it is not a blank and is not reported.

    Args:
        text: A fill-in question's stem.

    Returns:
        The id of every marker found violating that, in source order (a
        marker may appear more than once).
    """
    misplaced: list[str] = []
    open_blocks: list[str] = []
    for block_token in md.parse(text):
        if block_token.nesting == 1:
            open_blocks.append(block_token.type)
        elif block_token.nesting == -1:
            open_blocks.pop()
        elif block_token.type == "inline" and block_token.children:
            in_paragraph = open_blocks == ["paragraph_open"]
            misplaced.extend(_misplaced_in_inline(block_token.children, in_paragraph))
    return misplaced


def _misplaced_in_inline(children: list[Token], in_paragraph: bool) -> list[str]:
    """Markers of one inline run that are outside plain paragraph text."""
    misplaced: list[str] = []
    depth = 0
    for token in children:
        if token.nesting == 1:
            depth += 1
        elif token.nesting == -1:
            depth -= 1
        elif token.type == "text" and (depth > 0 or not in_paragraph):
            misplaced.extend(
                match.group(1) for match in _BLANK_MARKER_RE.finditer(token.content)
            )
    return misplaced

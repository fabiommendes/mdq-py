"""
Markdown-level helpers shared by `mdq._parser` and `mdq.models`.

`md` is the one `markdown_it.MarkdownIt` instance every MDQ document is
parsed with -- `mdq._parser._question.MDQParser` builds its block tree
from it, and `find_misplaced_blank_markers` below uses it directly to
re-read raw Markdown outside the question grammar, checking a fill-in
stem for a misplaced blank marker.

`reconstruct_blocks` and `find_forbidden_elements`, the two other
`mdq.models` helpers that replay a field through `MDQParser`, live in
`mdq._parser` instead of here, since they need the parser itself, not
just `md`.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.rules_block import StateBlock
from markdown_it.token import Token

__all__ = [
    "md",
    "find_blank_markers",
    "find_misplaced_blank_markers",
    "UNICODE_SPACE",
    "split_lines",
    "strip_bom",
]

#: The `UNICODE_SPACE` class of docs/references/grammar.md: the 25 code
#: points of the Unicode `White_Space` property. Python `\s` also matches
#: U+001C to U+001F, and JavaScript `\s` matches U+FEFF instead of U+0085,
#: so the grammar never uses `\s`. Written without the brackets, to be
#: embedded in other classes.
UNICODE_SPACE = (
    r"\t\n\v\f\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"
)

#: One line and its line ending. Only `\r\n`, `\r` and `\n` end a line,
#: as in CommonMark and markdown-it. `str.splitlines()` also splits on
#: U+000B, U+000C, U+001C to U+001E, U+0085, U+2028 and U+2029, and so
#: would disagree with the line numbers in markdown-it's `Token.map`.
_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")

BOM = "\ufeff"

md = MarkdownIt("gfm-like")

# MDQ's own tags (`[short-answer]: ...`, `[numeric]: ...`, `[^blank]: ...`)
# are syntactically indistinguishable from CommonMark link reference
# definitions (`[label]: destination`), which are otherwise consumed
# silently with no token emitted at all. Disable that rule so these lines
# survive as ordinary paragraphs for us to pattern-match.
md.block.ruler.disable("reference")


def _record_item_indent(
    state: StateBlock, start_line: int, end_line: int, silent: bool
) -> bool:
    """
    Store the content column of a list item in the `meta` of its token.

    The list rule of markdown-it opens an item, sets `blkIndent` to the
    column where the content of the item starts (after the list marker
    and its padding, as CommonMark defines it) and then parses the
    content. This rule runs first on the first line of that content and
    copies the column to `meta["indent"]`. It never consumes a line.
    """
    if not silent and state.tokens:
        token = state.tokens[-1]
        if token.type == "list_item_open" and "indent" not in token.meta:
            token.meta["indent"] = state.blkIndent
    return False


md.block.ruler.before("table", "mdq_item_indent", _record_item_indent)


#: `[^id]` markers, as written in a fill-in stem. The id is a `SLUG`
#: (base.md, "Bracketed tags"): `[^ a]` and `[^-x]` are ordinary text. A
#: `]` followed by `(` or `[` starts a markdown link (`[^x](url)`,
#: `[^x][ref]`), so that is not a blank (fill-in.md, "Stem").
#: Duplicated from `mdq.models._BLANK_MARKER_RE` (structurally identical,
#: kept separate since the two modules check different things:
#: `mdq.models` cares only about which ids are referenced, this module
#: about where in the markup a marker sits).
_BLANK_MARKER_RE = re.compile(r"\[\^([a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*)\](?![(\[])")


def find_blank_markers(text: str) -> list[tuple[str, bool]]:
    """
    fill-in.md, "Where blanks may appear": find the `[^id]` markers of a
    stem and tell which ones are misplaced.

    The inline parse of each paragraph comes first (CommonMark). A marker
    is misplaced if it sits in a heading, list item, table cell or
    blockquote, or inside emphasis, a strong span, link text or image alt
    text. Code (fenced, indented or a code span) is literal text: it
    holds no marker. `[^x](url)` and `[^x][ref]` are links, not markers.

    Args:
        text: A fill-in question's stem.

    Returns:
        A `(id, misplaced)` pair for every marker, in source order (an id
        may appear more than once).
    """
    found: list[tuple[str, bool]] = []
    open_blocks: list[str] = []
    for block_token in md.parse(text):
        if block_token.nesting == 1:
            open_blocks.append(block_token.type)
        elif block_token.nesting == -1:
            open_blocks.pop()
        elif block_token.type == "inline" and block_token.children:
            in_paragraph = open_blocks == ["paragraph_open"]
            found.extend(_markers_in_inline(block_token.children, not in_paragraph))
    return found


def find_misplaced_blank_markers(text: str) -> list[str]:
    """
    The ids of the markers that `find_blank_markers` reports as misplaced.

    Args:
        text: A fill-in question's stem.

    Returns:
        The id of every misplaced marker, in source order.
    """
    return [name for name, misplaced in find_blank_markers(text) if misplaced]


def _markers_in_inline(
    children: list[Token], misplaced: bool
) -> list[tuple[str, bool]]:
    """Markers of one inline run, flagged when outside plain paragraph text."""
    found: list[tuple[str, bool]] = []
    depth = 0
    for token in children:
        if token.nesting == 1:
            depth += 1
        elif token.nesting == -1:
            depth -= 1
        elif token.type == "image":
            # Alt text: the children are the inline tokens of the label.
            found.extend(_markers_in_inline(token.children or [], True))
        elif token.type == "text":
            found.extend(
                (match.group(1), misplaced or depth > 0)
                for match in _BLANK_MARKER_RE.finditer(token.content)
            )
    return found


def split_lines(text: str, /, *, keepends: bool = False) -> list[str]:
    """
    Split `text` into lines at `\\r\\n`, `\\r` and `\\n` only.

    Use this instead of `str.splitlines()`, which also splits on other
    characters (see `_LINE_RE`). Like `str.splitlines()`, a line ending at
    the end of `text` does not start one more, empty line.

    Args:
        text: The text to split.
        keepends: Keep the line ending at the end of each line.

    Returns:
        The lines of `text`, in order.

    Example:
        >>> split_lines("a\\r\\nb\\x85c\\rd\\n")
        ['a', 'b\\x85c', 'd']
        >>> split_lines("a\\n\\nb", keepends=True)
        ['a\\n', '\\n', 'b']
    """
    lines = _LINE_RE.findall(text)
    if keepends:
        return lines
    return [line.rstrip("\r\n") for line in lines]


def strip_bom(text: str, /) -> str:
    """
    Remove the byte order mark (U+FEFF) at the start of `text`, if any.

    docs/references/grammar.md: implementations remove it before they
    parse a file. A U+FEFF anywhere else is text.

    Example:
        >>> strip_bom("\\ufeff# Prova")
        '# Prova'
    """
    return text.removeprefix(BOM)

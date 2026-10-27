"""
Markdown-level helpers shared by `mdq._parser` and `mdq.models`.

`md` is the one `markdown_it.MarkdownIt` instance every MDQ document is
parsed with -- `mdq._parser` builds its block tree from it, and `find_misplaced_blank_markers` below uses it directly to
re-read raw Markdown outside the question grammar, checking a fill-in
stem for a misplaced blank marker.

`reconstruct_blocks` and `find_forbidden_elements`, the two other
`mdq.models` helpers that replay a field through the parser, live in
`mdq._parser` instead of here, since they need the parser itself, not
just `md`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

from markdown_it import MarkdownIt
from markdown_it.rules_block import StateBlock
from markdown_it.rules_inline import StateInline
from markdown_it.token import Token
from markdown_it.tree import SyntaxTreeNode as Node

__all__ = [
    "md",
    "span",
    "starts_after",
    "BlankMarker",
    "find_blank_markers",
    "locate_blank_markers",
    "find_misplaced_blank_markers",
    "UNICODE_SPACE",
    "SLUG_BODY_RE",
    "SLUG_PATTERN",
    "UUID_RE",
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

#: The `SLUG` terminal of docs/references/grammar.md, unanchored, to embed
#: in other patterns.
SLUG_BODY_RE = r"[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*"

#: `SLUG_BODY_RE` anchored: the schema's `pattern` on a choice or blank `id`.
SLUG_PATTERN = rf"^{SLUG_BODY_RE}$"

#: generic.md: `uuid` MUST be `xxxxxxxx-xxxx-Mxxx-Nxxx-xxxxxxxxxxxx`
#: (hexadecimal digits). `M` is the version and `N` the variant, at indexes
#: 14 and 19 of a match.
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

#: One line and its line ending. Only `\r\n`, `\r` and `\n` end a line,
#: as in CommonMark and markdown-it. `str.splitlines()` also splits on
#: U+000B, U+000C, U+001C to U+001E, U+0085, U+2028 and U+2029, and so
#: would disagree with the line numbers in markdown-it's `Token.map`.
_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")

BOM = "\ufeff"

md = MarkdownIt("gfm-like")


def span(node: Node) -> tuple[int, int]:
    """
    The source lines of a block node, as a `(start, end)` range with `end`
    exclusive.
    """
    # markdown-it sets the line map of every block node.
    assert node.map is not None
    return node.map


def starts_after(previous: Node, node: Node) -> bool:
    """Whether `node` starts on the line right after `previous` ends."""
    return span(node)[0] == span(previous)[1]

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
_BLANK_MARKER_RE = re.compile(rf"\[\^({SLUG_BODY_RE})\](?![(\[])")


#: The `markup` of the `link_open` token of an autolink: `<https://...>`
#: and the bare URL or `www.` address of GFM.
_AUTOLINK_MARKUPS = frozenset({"autolink", "linkify"})


#: Key of `env` where `_note_blank_position` records the offsets of the
#: `[^id]` candidates: `{inline source: {offset, ...}}`.
_POSITIONS_KEY = "mdq_blank_positions"


def _note_blank_position(state: StateInline, silent: bool) -> bool:
    """
    Record the offset of a `[^id]` candidate in `env`, when `env` asks for it.

    markdown-it does not keep source offsets in its tokens. The inline rules
    reach a candidate only when it is not inside code or an autolink, so the
    offsets recorded here are the ones `locate_blank_markers` needs. It never
    consumes any text.
    """
    positions = state.env.get(_POSITIONS_KEY)
    if positions is not None and _BLANK_MARKER_RE.match(state.src, state.pos):
        positions.setdefault(state.src, set()).add(state.pos)
    return False


md.inline.ruler.before("link", "mdq_blank_position", _note_blank_position)


class BlankMarker(NamedTuple):
    """One `[^id]` marker of a stem, as `locate_blank_markers` reports it."""

    id: str
    #: Whether the marker sits where fill-in.md does not allow a blank.
    misplaced: bool
    #: `(start, end)` offsets of the marker in the text, `end` exclusive.
    #: `None` when the marker cannot be located (an escaped `\\[^id]`).
    span: tuple[int, int] | None


def locate_blank_markers(text: str) -> list[BlankMarker]:
    """
    fill-in.md, "Where blanks may appear": find the `[^id]` markers of a
    stem, tell which ones are misplaced and where each one is.

    The inline parse of each paragraph comes first (CommonMark). A marker
    is misplaced if it sits in a heading, list item, table cell or
    blockquote, or inside emphasis, a strong span, link text or image alt
    text. Code (fenced, indented or a code span) and the text of an
    autolink (`<https://...>`, a bare URL, a `www.` address) are literal:
    they hold no marker. `[^x](url)` and `[^x][ref]` are links, not markers.

    Args:
        text: A fill-in question's stem.

    Returns:
        A `BlankMarker` for every marker, in source order (an id may appear
        more than once).
    """
    env: dict[str, object] = {_POSITIONS_KEY: {}}
    tokens = md.parse(text, env)
    recorded = env[_POSITIONS_KEY]
    assert isinstance(recorded, dict)
    line_starts = [0]
    for line in split_lines(text, keepends=True):
        line_starts.append(line_starts[-1] + len(line))
    found: list[BlankMarker] = []
    open_blocks: list[str] = []
    for block_token in tokens:
        if block_token.nesting == 1:
            open_blocks.append(block_token.type)
        elif block_token.nesting == -1:
            open_blocks.pop()
        elif block_token.type == "inline" and block_token.children:
            in_paragraph = open_blocks == ["paragraph_open"]
            markers = _markers_in_inline(block_token.children, not in_paragraph)
            offsets = sorted(recorded.get(block_token.content, ()))
            found.extend(
                BlankMarker(name, misplaced, span)
                for name, misplaced, span in _place_markers(
                    markers, offsets, block_token, text, line_starts
                )
            )
    return found


def _place_markers(
    markers: list[tuple[str, bool]],
    offsets: list[int],
    block_token: Token,
    text: str,
    line_starts: list[int],
) -> list[tuple[str, bool, tuple[int, int] | None]]:
    """Pair the markers of one inline token with their offsets in `text`."""
    placed: list[tuple[str, bool, tuple[int, int] | None]] = []
    content = block_token.content
    cursor = 0
    for name, misplaced in markers:
        literal = f"[^{name}]"
        span = None
        for index in range(cursor, len(offsets)):
            if content.startswith(literal, offsets[index]):
                cursor = index + 1
                start = _source_offset(block_token, text, line_starts, offsets[index])
                if start is not None and text.startswith(literal, start):
                    span = (start, start + len(literal))
                break
        placed.append((name, misplaced, span))
    return placed


def _source_offset(
    block_token: Token, text: str, line_starts: list[int], offset: int
) -> int | None:
    """
    Map an offset in the content of an inline token to an offset in `text`.

    The content is the source lines of the block with their prefix (indent,
    list marker, `#`) removed, so each content line is found in the source
    line of the same index. Returns `None` when it is not found there.
    """
    if block_token.map is None:
        return None
    content = block_token.content
    line_index = content.count("\n", 0, offset)
    column = offset - (content.rfind("\n", 0, offset) + 1)
    source_line_index = block_token.map[0] + line_index
    if source_line_index >= len(line_starts) - 1:
        return None
    content_line = content.split("\n")[line_index]
    source_line = text[line_starts[source_line_index] : line_starts[source_line_index + 1]]
    source_line = source_line.rstrip("\r\n")
    for candidate in (source_line, source_line.rstrip()):
        if candidate.endswith(content_line):
            shift = len(candidate) - len(content_line)
            break
    else:
        shift = source_line.find(content_line)
        if shift < 0:
            return None
    return line_starts[source_line_index] + shift + column


def find_blank_markers(text: str) -> list[tuple[str, bool]]:
    """
    fill-in.md, "Where blanks may appear": find the `[^id]` markers of a
    stem and tell which ones are misplaced. See `locate_blank_markers`.

    Args:
        text: A fill-in question's stem.

    Returns:
        A `(id, misplaced)` pair for every marker, in source order (an id
        may appear more than once).
    """
    return [(marker.id, marker.misplaced) for marker in locate_blank_markers(text)]


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
    #: Depth at which an autolink opened; its text is the address, literal.
    autolink_depth: int | None = None
    for token in children:
        if token.nesting == 1:
            depth += 1
            if autolink_depth is None and token.markup in _AUTOLINK_MARKUPS:
                autolink_depth = depth
        elif token.nesting == -1:
            if depth == autolink_depth:
                autolink_depth = None
            depth -= 1
        elif autolink_depth is not None:
            continue
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


def starts_block(pattern: str) -> bool:
    """
    Report whether `pattern` is an inexact literal whose text starts a
    CommonMark block other than a paragraph (patterns.md, "Pattern string").
    An exact literal (opens with a backtick) and a regex (opens with `/`)
    are never concerned.
    """
    text = pattern.strip(" \t")
    if text.startswith(("`", "/")):
        return False
    tokens = md.parse(text)
    return bool(tokens) and tokens[0].type != "paragraph_open"


def has_visible_character(value: str) -> bool:
    """
    Whether `value` has a visible character, as grammar.md "Visible
    characters" defines it: not white space, and not a control (`Cc`) or
    format (`Cf`) character such as U+200B.
    """
    return any(
        not (c.isspace() or unicodedata.category(c) in ("Cc", "Cf")) for c in value
    )

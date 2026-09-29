"""
The `non-ascii-whitespace` lint (docs/references/grammar.md, "Unicode
spaces").

The grammar reads a Unicode space as text, but Markdown parsers, editors
and string functions can read it as whitespace or as a line break, so the
result of the document can change from one implementation to another.
This check reads the source text, not the parsed document: it needs the
lines, the code blocks and the code spans, which the parsed document no
longer has.
"""

from __future__ import annotations

import re
import unicodedata

from .._diagnostics import Diagnostic, Severity
from .._markdown import md, split_lines, strip_bom
from ._exam import _code_line_indices, _looks_like_frontmatter, is_exam
from ._frontmatter import _split_frontmatter

__all__ = ["find_unicode_spaces"]

CODE = "non-ascii-whitespace"

#: The characters the lint reports: `UNICODE_SPACE` outside ASCII, and
#: U+FEFF, which is invisible and which JavaScript `\s` matches.
_REPORTED = r"\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_REPORTED_RE = re.compile(rf"[{_REPORTED}]")
#: Many editors show these as line breaks, so they are a `warning` at any
#: position.
_LINE_SEPARATORS = frozenset("\x85\u2028\u2029")

#: A space, a tab or a reported character.
_SPACE = rf"[ \t{_REPORTED}]"
#: The markers at the start of a line: list items, headings, blockquotes
#: and the `!` of a comment line, each after optional spaces and tabs.
_PREFIX_RE = re.compile(r"(?:[ \t]*(?:[*+-]|[0-9]{1,9}[.)]|#{1,6}|>|!))*")
_SPACES_RE = re.compile(rf"{_SPACE}*")
_TRAILING_RE = re.compile(rf"{_SPACE}*$")
#: A bracketed tag followed by `:`, as in `[numeric]:`.
_TAG_LINE_RE = re.compile(rf"\[[^\]\r\n]*\]{_SPACE}*:")
#: The bracketed tags at the start of a choice item or a stem, as in
#: `[*] [ipe]`, with the spaces around them.
_BRACKETS_RE = re.compile(rf"(?:\[[^\]\r\n]*\]{_SPACE}*)+")
#: The tag before an `accept` or `reject` pattern list.
_PATTERN_LIST_TAG_RE = re.compile(
    r"^\[(?:short-answer|\^[^\]/]+/short-answer)/(?:accept|reject)\]"
)
#: A code span: a run of backticks, up to the next run of the same length.
_CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)

#: `unicodedata.name` has no name for the control character U+0085.
_NAMES = {0x85: "NEXT LINE"}


def find_unicode_spaces(text: str, /) -> list[Diagnostic]:
    """
    Report each Unicode space in an MDQ source document.

    Code blocks, code spans, YAML frontmatter and a byte order mark at the
    start of `text` are skipped. The severity is `warning` for a line
    separator (U+0085, U+2028, U+2029) and for a character in a syntax
    position, and `info` for a character inside prose.

    Args:
        text: MDQ source of a question or an exam.

    Returns:
        One `non-ascii-whitespace` diagnostic per character, in source
        order. `line` is the 1-based line in `text`.

    Example:
        >>> [(d.severity, d.line) for d in find_unicode_spaces("6\\u202f400 km")]
        [('info', 1)]
    """
    text = strip_bom(text)
    frontmatter, body = _split_frontmatter(text)
    offset = 0
    if frontmatter is not None:
        offset = len(split_lines(text, keepends=True)) - len(
            split_lines(body, keepends=True)
        )

    lines = split_lines(body)
    skipped = _code_line_indices(lines)
    if is_exam(body):
        skipped |= _question_frontmatter_lines(lines, skipped)
    pattern_lines = _pattern_line_indices(body)
    masked = _mask_code_spans(lines, skipped)

    diagnostics: list[Diagnostic] = []
    for index, line in enumerate(masked):
        if index in skipped:
            continue
        for match in _REPORTED_RE.finditer(line):
            severity: Severity = "info"
            if (
                match.group() in _LINE_SEPARATORS
                or index in pattern_lines
                or _in_syntax_position(line, match.start())
            ):
                severity = "warning"
            diagnostics.append(_diagnostic(match.group(), severity, offset + index + 1))
    return diagnostics


def _in_syntax_position(line: str, column: int) -> bool:
    """Whether the character at `column` of `line` is in a syntax position."""
    start = _PREFIX_RE.match(line).end()  # type: ignore[union-attr]
    content = _SPACES_RE.match(line, start).end()  # type: ignore[union-attr]
    if column < content:
        return True
    if column >= _TRAILING_RE.search(line).start():  # type: ignore[union-attr]
        return True
    if _TAG_LINE_RE.match(line, content):
        return True
    brackets = _BRACKETS_RE.match(line, content)
    return brackets is not None and column < brackets.end()


def _pattern_line_indices(body: str) -> set[int]:
    """The first line of each item of an `accept` or `reject` pattern list."""
    indices: set[int] = set()
    after_tag = False
    in_pattern_list = False
    for token in md.parse(body):
        if in_pattern_list:
            if token.type == "bullet_list_close" and token.level == 0:
                in_pattern_list = False
            elif token.type == "list_item_open" and token.level == 1 and token.map:
                indices.add(token.map[0])
            continue
        if token.type == "inline" and token.level == 1:
            after_tag = bool(_PATTERN_LIST_TAG_RE.match(token.content))
        elif token.type == "bullet_list_open" and token.level == 0:
            in_pattern_list = after_tag
            after_tag = False
        elif token.nesting == 1 and token.level == 0 and token.type != "paragraph_open":
            after_tag = False
    return indices


def _question_frontmatter_lines(lines: list[str], code_lines: set[int]) -> set[int]:
    """
    The lines of each question frontmatter inside an exam: a `---` line,
    the YAML after it, and the next `---` line.

    Uses the same test as the exam parser: the text between the two lines
    must load as a YAML mapping.
    """
    covered: set[int] = set()
    fences = [
        i for i, line in enumerate(lines)
        if i not in code_lines and line.rstrip(" \t") == "---"
    ]
    position = 0
    while position + 1 < len(fences):
        start, end = fences[position], fences[position + 1]
        if _looks_like_frontmatter(lines[start + 1 : end]):
            covered.update(range(start, end + 1))
            position += 2
        else:
            position += 1
    return covered


def _mask_code_spans(lines: list[str], code_lines: set[int]) -> list[str]:
    """
    Replace the characters of each code span with `x`.

    A code span can continue on the next line, but not past a blank line
    or a code block, so each run of other lines is searched as one text.
    """
    masked = list(lines)
    run: list[int] = []
    for index in [*range(len(lines)), len(lines)]:
        in_run = (
            index < len(lines)
            and index not in code_lines
            and lines[index].strip(" \t") != ""
        )
        if in_run:
            run.append(index)
            continue
        if run:
            joined = "\n".join(lines[i] for i in run)
            for span in _CODE_SPAN_RE.finditer(joined):
                start, end = span.span()
                joined = (
                    joined[:start]
                    + re.sub(r"[^\n]", "x", joined[start:end])
                    + joined[end:]
                )
            for i, line in zip(run, joined.split("\n")):
                masked[i] = line
            run = []
    return masked


def _diagnostic(char: str, severity: Severity, line: int) -> Diagnostic:
    code_point = ord(char)
    name = _NAMES.get(code_point) or unicodedata.name(char, "")
    label = f"U+{code_point:04X} {name}".rstrip()
    if char in _LINE_SEPARATORS:
        detail = "editors may show it as a line break"
    elif severity == "warning":
        detail = "it is in MDQ syntax, and other tools may read it as whitespace"
    else:
        detail = "other tools may read it as whitespace"
    return Diagnostic(
        severity=severity,
        code=CODE,
        message=f"{label} is text in MDQ, but {detail}",
        line=line,
    )

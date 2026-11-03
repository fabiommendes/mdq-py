"""
Text conversion shared by GIFT and Moodle XML: plain text and HTML to MDQ Markdown.
"""

from __future__ import annotations

import re

from .._markdown import has_visible_character
from ._base import HtmlMode, Report

_PLAIN_FORMATS = frozenset({"plain", "plain_text"})
_MARKDOWN_SPECIALS_RE = re.compile(r"[\\`*_\[\]<>&~]")
#: A character that starts a block at the beginning of a line: `#`, `-`, `1.`, ...
_LINE_START_SPECIAL_RE = re.compile(r"^( {0,3})(?:([#+\-=])|(\d+)([.)]))")


def _escape_line_start(match: re.Match[str]) -> str:
    """Escape the character of a line start that `_LINE_START_SPECIAL_RE` matched."""
    indent, mark, digits, delimiter = match.groups()
    if mark:
        return f"{indent}\\{mark}"
    return f"{indent}{digits}\\{delimiter}"


def plain_text_to_markdown(text: str) -> str:
    r"""
    Return the Markdown that renders as the plain text `text`: the
    punctuation with a Markdown meaning is backslash-escaped (`*`, `_`,
    `[`, `<`, `&`, a leading `#` or `1.`, ...) and each line break inside a
    paragraph becomes a hard break (a trailing backslash).
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    escaped = [_MARKDOWN_SPECIALS_RE.sub(lambda m: "\\" + m.group(), line) for line in lines]
    escaped = [
        _LINE_START_SPECIAL_RE.sub(_escape_line_start, line) for line in escaped
    ]
    for i in range(len(escaped) - 1):
        if lines[i].strip() and lines[i + 1].strip():
            escaped[i] += "\\"
    return "\n".join(escaped)


#: Elements whose text keeps its line breaks, so a blank line in them matters.
_VERBATIM_HTML_RE = re.compile(
    r"(<(pre|textarea)\b[^>]*>.*?</\2\s*>)", re.DOTALL | re.IGNORECASE
)
_BLANK_LINE_RUN_RE = re.compile(r"\s*\n[ \t]*\n\s*")
_BLANK_LINE_IN_VERBATIM_RE = re.compile(r"(?<=\n)[ \t]*\n")


def html_to_mdq(text: str) -> str:
    """
    Return the Markdown that renders as the HTML `text`: one CommonMark HTML
    block (`<div>...</div>`) that is never read as Markdown. Return `text`
    unchanged if it has no visible character.

    An HTML block ends at a blank line, so no blank line may remain. Outside
    `<pre>` and `<textarea>`, HTML collapses whitespace: each run of
    whitespace that has a blank line becomes one line break. Inside them, each
    blank line is joined to the next line as the character reference `&#10;`
    (the whitespace of a blank line is lost).
    """
    if not has_visible_character(text):
        return text
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    parts = _VERBATIM_HTML_RE.split(text)
    # `split` with two groups yields: other, verbatim element, tag name, other, ...
    out: list[str] = []
    for i in range(0, len(parts), 3):
        out.append(_BLANK_LINE_RUN_RE.sub("\n", parts[i]))
        if i + 1 < len(parts):
            out.append(_BLANK_LINE_IN_VERBATIM_RE.sub("&#10;", parts[i + 1]))
    return f"<div>{''.join(out)}</div>"

_HTML_PARAGRAPH_RE = re.compile(r"<p(?:\s[^>]*)?>(.*?)</p\s*>", re.DOTALL | re.IGNORECASE)
_LINE_BREAK_RUN_RE = re.compile(r"\s*\n\s*")
_MARKER_RE = re.compile(r"\[\^[^\]\s]+\]")
_HTML_BLOCK_TAGS = (
    "address|article|aside|blockquote|body|caption|center|col|colgroup|dd|details|"
    "dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|"
    "h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|"
    "noframes|ol|optgroup|option|p|param|section|summary|table|tbody|td|tfoot|th|"
    "thead|title|tr|track|ul"
)
_HTML_BLOCK_START_RE = re.compile(
    rf"^ {{0,3}}<(?:/?(?:{_HTML_BLOCK_TAGS})(?=[\s/>]|$)|(pre|script|style|textarea)(?=[\s/>]|$))",
    re.IGNORECASE,
)


def html_with_blanks_to_mdq(text: str, report: Report) -> str:
    """
    Return the Markdown for the HTML `text` of a cloze or missing-word stem,
    where `[^id]` markers stand for the blanks.

    A marker inside a CommonMark HTML block is literal text, so each top-level
    `<p>...</p>` becomes a Markdown paragraph holding its inner content
    (attributes such as `class`, `dir` and `style` are dropped), separated from
    the next block by one blank line. Inside a paragraph, a whitespace run with
    a line break becomes one space (HTML collapses it anyway), so no blank line
    is left. Inline tags (`<b>`, `<span>`, `<br>`) stay as inline HTML.

    Raises:
        ConversionError: a block-level tag, other than `<p>`, opens an HTML block
            that holds a marker.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    def paragraph(match: re.Match[str]) -> str:
        inner = _LINE_BREAK_RUN_RE.sub(" ", match.group(1)).strip()
        return f"\n\n{inner}\n\n" if inner else "\n\n"

    text = _HTML_PARAGRAPH_RE.sub(paragraph, text)
    text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text).strip()

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        start = _HTML_BLOCK_START_RE.match(lines[i])
        if not start:
            i += 1
            continue
        verbatim = start.group(1)
        end = i
        while end < len(lines):
            if verbatim:
                if re.search(rf"</{verbatim}\s*>", lines[end], re.IGNORECASE):
                    break
            elif not lines[end].strip():
                break
            end += 1
        if _MARKER_RE.search("\n".join(lines[i : end + 1])):
            tag = lines[i].lstrip()[1:].split(maxsplit=1)[0].split(">")[0].rstrip("/")
            report.error(
                "blank-in-html-block",
                f"a blank inside the HTML block starting at `<{tag.lstrip('/')}>` "
                "cannot be a `[^id]` marker: CommonMark reads an HTML block as "
                "literal text. Only `<p>` paragraphs are converted; use "
                '`html="markdown"` (`--html markdown`) to convert other block tags'
            )
        i = end + 1
    return text


def html_to_markdown(text: str) -> str:
    """
    Return the Markdown that renders as the HTML `text`, converted with the
    optional `markdownify` package (extra `mdq[html]`). Return `text`
    unchanged if it has no visible character.
    """
    if not has_visible_character(text):
        return text
    from markdownify import markdownify

    return str(markdownify(text, heading_style="ATX")).strip()


def html_with_blanks_to_markdown(text: str) -> str:
    """
    Return the Markdown for the HTML `text` of a cloze or missing-word stem,
    where `[^id]` markers stand for the blanks. The stem is converted as a
    whole, so no HTML element is split: each marker is a placeholder that
    `markdownify` keeps, and it is put back after the conversion.
    """
    markers = _MARKER_RE.findall(text)
    for index, marker in enumerate(markers):
        text = text.replace(marker, f"MDQBLANK{index}X", 1)
    text = html_to_markdown(text)
    for index, marker in enumerate(markers):
        text = text.replace(f"MDQBLANK{index}X", marker, 1)
    return text


def html_blanks_to_mdq(text: str, report: Report) -> str:
    """The MDQ text of the HTML `text` with `[^id]` markers, by the `html` mode of `report`."""
    if report.html == "markdown":
        return html_with_blanks_to_markdown(text)
    return html_with_blanks_to_mdq(text, report)


def mdq_text(text: str, text_format: str, *, block: bool = False, html: HtmlMode = "block") -> str:
    """
    Return the MDQ text for a `text` an external format wrote in
    `text_format`: `plain` and `plain_text` are escaped
    (`plain_text_to_markdown`); auto-format (`moodle`, `moodle_auto_format`)
    and `markdown` are copied as they are.

    `html` is copied as it is, except when `block` is true: `text` is then a
    whole block of the MDQ document (a stem without blanks, a general
    feedback, a grader info) and becomes one HTML block (`html_to_mdq`). The
    text of a choice, an inline feedback or a text around a blank is not a
    whole block. With `html="markdown"`, every `html` text is converted to
    Markdown (`html_to_markdown`) instead.
    """
    if text_format in _PLAIN_FORMATS:
        return plain_text_to_markdown(text)
    if text_format != "html":
        return text
    if html == "markdown":
        return html_to_markdown(text)
    return html_to_mdq(text) if block else text

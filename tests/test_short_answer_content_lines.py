"""
Short answer: the lines after single-line content follow the CommonMark
paragraph (docs/references/patterns.md, "Continuation lines").

A lazy line continues the content, also after an empty tag. A `>` or `!` line
(not `![`) right after the content is a `parse-error`. A heading, a fenced
code block, an HTML block or a thematic break ends the block.
"""

from __future__ import annotations

import pytest

from mdq._parser import parse_question
from mdq.errors import MissingField, ParseError

STEM = "Qual é a capital do Brasil?"
FILL_STEM = "A capital é [^cap]."


def _q(body: str) -> str:
    return f"{STEM}\n\n{body}\n"


def _f(body: str) -> str:
    return f"{FILL_STEM}\n\n{body}\n"


def test_lazy_line_continues_content() -> None:
    q = parse_question(_q("[short-answer]: Rio\n  Negro"))
    assert q["accept"] == ["Rio Negro"]


def test_exact_literal_spans_lines() -> None:
    q = parse_question(_q("[short-answer]: `math.\nisnan`"))
    assert q["accept"] == ["`math. isnan`"]


def test_empty_accept_tag_then_text_line() -> None:
    q = parse_question(_q("[short-answer]:\nBrasília"))
    assert q["accept"] == ["Brasília"]


def test_empty_reject_tag_then_text_line() -> None:
    q = parse_question(_q("[short-answer]: Brasília\n\n[short-answer/reject]:\nRio"))
    assert q["reject"] == ["Rio"]


def test_empty_blank_definition_then_text_line() -> None:
    q = parse_question(_f("[^cap/short-answer]:\nBrasília"))
    assert q["blanks"][0]["accept"] == ["Brasília"]  # type: ignore[typeddict-item]


@pytest.mark.parametrize("line", ["> Good", "! note", "!note", "  ! note"])
@pytest.mark.parametrize(
    "tag", ["[short-answer]: Brasília", "[short-answer/reject]: Rio", "[short-answer]:"]
)
def test_marker_line_after_content_is_a_parse_error(tag: str, line: str) -> None:
    with pytest.raises(ParseError, match="list form"):
        parse_question(_q(f"{tag}\n{line}"))


def test_marker_line_after_continuation_is_a_parse_error() -> None:
    for line in ("> Good", "! note"):
        with pytest.raises(ParseError, match="list form"):
            parse_question(_q(f"[short-answer]: Rio\nNegro\n{line}"))


@pytest.mark.parametrize("line", ["> note", "! note"])
def test_marker_line_after_blank_definition_content(line: str) -> None:
    with pytest.raises(ParseError, match="list form"):
        parse_question(_f(f"[^cap/short-answer]: Brasília\n{line}"))


def test_image_line_continues_content() -> None:
    q = parse_question(_q("[short-answer]: Brasília\n![mapa](mapa.png)"))
    assert q["accept"] == ["Brasília ![mapa](mapa.png)"]


def test_list_item_after_content_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_question(_q("[short-answer]: Brasília\n* Rio"))


@pytest.mark.parametrize(
    ("line", "epilogue"),
    [
        ("## Nota", "## Nota"),
        ("<div>x</div>", "<div>x</div>"),
        ("***", "***"),
        ("```\ncódigo\n```", "```\ncódigo\n```"),
    ],
)
def test_interrupting_block_goes_to_the_epilogue(line: str, epilogue: str) -> None:
    q = parse_question(_q(f"[short-answer]: Brasília\n{line}"))
    assert q["accept"] == ["Brasília"]
    assert q["epilogue"] == epilogue


@pytest.mark.parametrize("marker", ["---", "==="])
@pytest.mark.parametrize("tag", ["[short-answer]: Brasília", "[short-answer]:"])
def test_setext_heading_tag_message_suggests_a_blank_line(tag: str, marker: str) -> None:
    with pytest.raises(MissingField, match="setext heading.*blank line"):
        parse_question(_q(f"{tag}\n{marker}"))


def test_missing_body_without_setext_keeps_the_default_message() -> None:
    with pytest.raises(MissingField, match="required field"):
        parse_question(_q("Texto\n---"))

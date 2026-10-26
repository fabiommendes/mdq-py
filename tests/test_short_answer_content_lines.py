"""
Short answer: the lines after single-line content follow the CommonMark
paragraph (docs/references/patterns.md, "Continuation lines").

The accepted and rejected forms are in the example corpus. This module
keeps the message of the setext heading error.
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


@pytest.mark.parametrize("marker", ["---", "==="])
@pytest.mark.parametrize("tag", ["[short-answer]: Brasília", "[short-answer]:"])
def test_setext_heading_tag_message_suggests_a_blank_line(tag: str, marker: str) -> None:
    with pytest.raises(MissingField, match="setext heading.*blank line"):
        parse_question(_q(f"{tag}\n{marker}"))


def test_missing_body_without_setext_keeps_the_default_message() -> None:
    with pytest.raises(MissingField, match="required field"):
        parse_question(_q("Texto\n---"))


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

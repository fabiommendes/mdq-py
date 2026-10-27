"""
Short answer: the lines after single-line content follow the CommonMark
paragraph (docs/references/patterns.md, "Continuation lines").

The accepted and rejected forms are in the example corpus. This module
keeps the messages of the errors.
"""

from __future__ import annotations

import pytest

from mdq._parser import parse_question
from mdq.errors import MissingField, ParseError

STEM = "Qual é a capital do Brasil?"


def _q(body: str) -> str:
    return f"{STEM}\n\n{body}\n"


@pytest.mark.parametrize("marker", ["---", "==="])
@pytest.mark.parametrize("tag", ["[short-answer]: Brasília", "[short-answer]:"])
def test_setext_heading_tag_message_suggests_a_blank_line(tag: str, marker: str) -> None:
    with pytest.raises(MissingField, match="setext heading.*blank line"):
        parse_question(_q(f"{tag}\n{marker}"))


def test_missing_body_without_setext_keeps_the_default_message() -> None:
    with pytest.raises(MissingField, match="required field"):
        parse_question(_q("Texto\n---"))


def test_marker_line_after_content_points_to_the_list_form() -> None:
    with pytest.raises(ParseError, match="list form"):
        parse_question(_q("[short-answer]: Brasília\n> Good"))

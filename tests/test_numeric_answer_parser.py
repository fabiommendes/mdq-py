"""
`parse_numeric_answer` and `_parse_numeric_expression` read the whole text
as `sign? numeric_value`: a regex `$` also matches before a final newline,
so the grammar is matched with `fullmatch`. The importers can pass text with
a trailing newline; the corpus covers the `answer` of a loaded document
(`invalid/model-only/numeric-answer-trailing-newline`).
"""

from __future__ import annotations

import pytest

from mdq._parser import parse_numeric_answer
from mdq.errors import ParseError
from mdq._parser._numeric import _parse_numeric_expression


@pytest.mark.parametrize("text", ["5\n", "-3.5\n", "1/2\n", "5\n\n", "5\r\n"])
def test_a_numeric_answer_with_a_line_break_is_malformed(text: str) -> None:
    with pytest.raises(ParseError, match="malformed numeric value"):
        parse_numeric_answer(text)


@pytest.mark.parametrize("text", ["5\n", "5 +- 1\n"])
def test_a_numeric_body_with_a_line_break_is_malformed(text: str) -> None:
    with pytest.raises(ParseError, match="malformed numeric body"):
        _parse_numeric_expression(text)


def test_a_numeric_answer_keeps_ignoring_spaces_and_tabs_at_both_ends() -> None:
    assert parse_numeric_answer(" \t5\t ") == 5

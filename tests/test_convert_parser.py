"""
Tests for the `mdq.convert._string_parser` recursive-descent primitives
(`StringParser`, `ParserError`).

These primitives are format-agnostic building blocks used by
`mdq.convert._aiken` (and future converters), so they're exercised here
directly through a minimal subclass rather than through Aiken.
"""

from __future__ import annotations

import re

import pytest

from mdq.convert._string_parser import ParserError, StringParser


class EchoParser(StringParser[str]):
    """A trivial parser whose `start` is overridden per test."""

    def start(self) -> str:
        raise NotImplementedError


def make_parser(source: str, start) -> EchoParser:
    parser = EchoParser(source)
    parser.start = start  # type: ignore[method-assign]
    return parser


def test_read_returns_lines_in_order():
    parser = EchoParser("a\nb\nc")
    assert parser.read() == "a"
    assert parser.read() == "b"
    assert parser.read() == "c"


def test_read_past_eof_raises_parser_error():
    parser = EchoParser("a")
    parser.read()
    with pytest.raises(ParserError, match="EOF reached"):
        parser.read()


def test_peek_does_not_consume():
    parser = EchoParser("a\nb")
    assert parser.peek() == "a"
    assert parser.peek() == "a"
    assert parser.read() == "a"


def test_peek_on_empty_source_returns_empty_string():
    parser = EchoParser("")
    assert parser.peek() == ""


def test_ws_skips_blank_and_whitespace_only_lines():
    parser = EchoParser("\n   \n\ndata")
    parser.ws()
    assert parser.peek() == "data"


def test_ws_strips_leading_whitespace_on_first_nonblank_line():
    parser = EchoParser("   data")
    parser.ws()
    assert parser.peek() == "data"
    assert parser.colno == 3


def test_match_returns_none_without_consuming_on_failure():
    parser = EchoParser("abc")
    assert parser.match("xyz") is None
    assert parser.peek() == "abc"


def test_match_consumes_matched_prefix():
    parser = EchoParser("abcdef")
    result = parser.match("abc")
    assert result == "abc"
    assert parser.peek() == "def"


def test_match_full_requires_entire_line():
    parser = EchoParser("abc\ndef")
    assert parser.match("ab", full=True) is None
    assert parser.match("abc", full=True) == "abc"
    assert parser.peek() == "def"


def test_match_pops_line_once_fully_consumed():
    parser = EchoParser("abc\ndef")
    parser.match("abc", full=True)
    assert len(parser.lines) == 1
    assert parser.peek() == "def"


def test_expect_raises_on_mismatch():
    parser = EchoParser("xyz")
    with pytest.raises(ParserError):
        parser.expect("abc")


def test_expect_returns_match_on_success():
    parser = EchoParser("abcdef")
    assert parser.expect("abc") == "abc"


def test_match_group_exposes_named_groups():
    parser = EchoParser("key: value")
    pattern = re.compile(r"(?P<key>\w+): (?P<value>.*)")
    result = parser.match_group(pattern, full=True)
    assert result is not None
    assert result["key"] == "key"
    assert result["value"] == "value"
    assert result[""] == "key: value"


def test_parse_raises_on_unparsed_trailing_lines():
    parser = make_parser("done\nextra", lambda: parser.read())
    with pytest.raises(ParserError, match="unparsed lines"):
        parser.parse()


def test_parse_succeeds_when_all_input_consumed():
    parser = make_parser("done\n\n", lambda: parser.read())
    assert parser.parse() == "done"


def test_parser_error_reports_one_indexed_line_and_col():
    parser = EchoParser("a\nb")
    parser.read()
    try:
        parser.error("boom")
    except ParserError as exc:
        assert str(exc) == "[line 2, col 1]: boom"
    else:
        pytest.fail("expected ParserError")


# ---------------------------------------------------------------------
# Regression tests for bugs fixed in `mdq.convert._string_parser`.
# ---------------------------------------------------------------------


def test_match_raw_true_treats_pattern_as_literal():
    parser = EchoParser("AxB rest")
    # "." should only match a literal dot, not "any character".
    assert parser.match("A.B", raw=True) is None


def test_match_raw_true_matches_literal_prefix():
    parser = EchoParser("A.B rest")
    assert parser.match("A.B", raw=True) == "A.B"
    assert parser.peek() == " rest"


def test_match_raw_true_full_requires_exact_line():
    parser = EchoParser("A.B\nnext")
    assert parser.match("A.B", raw=True, full=True) == "A.B"
    assert parser.peek() == "next"


def test_expect_default_message_mentions_pattern():
    parser = EchoParser("nope")
    with pytest.raises(ParserError, match=re.escape(repr("abc"))):
        parser.expect("abc")


def test_match_group_full_line_advances_lineno():
    parser = EchoParser("line1\nline2")
    parser.match_group(re.compile("line1"), full=True)
    assert parser.peek() == "line2"
    assert parser.lineno == 1

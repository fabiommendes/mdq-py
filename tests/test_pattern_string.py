"""
Pattern string rules (docs/references/patterns.md, "Pattern string"):
blank patterns are `blank-text`, spaces and tabs at both ends are removed
before classification, and a backtick opening needs a complete span.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mdq._exact import exact_literal, exact_span
from mdq.models import AnswerPattern

ZERO_WIDTH_SPACE = chr(0x200B)


def error_types(exc: ValidationError) -> list[str]:
    return [error["type"] for error in exc.errors()]


@pytest.mark.parametrize(
    "pattern",
    ["   ", "\t", "` `", "  `   `  ", ZERO_WIDTH_SPACE, f"`{ZERO_WIDTH_SPACE}`"],
)
def test_pattern_without_visible_character_is_blank_text(pattern: str) -> None:
    with pytest.raises(ValidationError) as info:
        AnswerPattern(pattern=pattern)
    assert error_types(info.value) == ["blank-text"]


def test_empty_pattern_is_schema_error() -> None:
    with pytest.raises(ValidationError) as info:
        AnswerPattern(pattern="")
    assert error_types(info.value) == ["string_too_short"]


@pytest.mark.parametrize("pattern", [
        "`math.isnan` (x)",
        "`math.isnan",
        "`a`b",
        "`",
        "``x`",
        "`x``",
        "`` `x` ``y",
        "``",
        "`` x",
    ])
def test_incomplete_backtick_span_is_schema_error(pattern: str) -> None:
    with pytest.raises(ValidationError) as info:
        AnswerPattern(pattern=pattern)
    assert error_types(info.value) == ["schema-error"]


@pytest.mark.parametrize("pattern", ["a\nb", "`a\nb`", "a\rb"])
def test_pattern_with_line_ending_is_schema_error(pattern: str) -> None:
    with pytest.raises(ValidationError) as info:
        AnswerPattern(pattern=pattern)
    assert error_types(info.value) == ["schema-error"]


@pytest.mark.parametrize(
    ("pattern", "response", "expected"),
    [
        ("  `x`", "x", True),
        ("\t`x`  ", "x", True),
        ("  `x`", "X", False),
        ("  /abc/i", "ABC", True),
        ("  Brasília ", "brasilia", True),
        ("`x`  ", "x", True),
    ],
)
def test_spaces_and_tabs_at_the_ends_are_removed(
    pattern: str, response: str, expected: bool
) -> None:
    assert AnswerPattern(pattern=pattern).matches(response) is expected


def test_pattern_with_one_visible_character_is_valid() -> None:
    assert AnswerPattern(pattern="`.`").matches(".")
    assert AnswerPattern(pattern="/ /").pattern == "/ /"


@pytest.mark.parametrize(
    ("pattern", "content"),
    [
        ("`x`", "x"),
        ("`` `print` ``", "`print`"),
        ("``a`b``", "a`b"),
        ("```a``b```", "a``b"),
        ("`a``b`", "a``b"),
        ("`` ` ``", "`"),
        ("`  x  `", " x "),
        ("`   `", "   "),
        ("` x`", " x"),
        ("  `` `date` ``\t", "`date`"),
    ],
)
def test_exact_literal_follows_the_commonmark_code_span(
    pattern: str, content: str
) -> None:
    assert exact_literal(pattern) == content


@pytest.mark.parametrize("pattern", ["x", "/x/", "`x` y", "``x`", "`", "`` x"])
def test_exact_literal_is_none_for_other_patterns(pattern: str) -> None:
    assert exact_literal(pattern) is None


@pytest.mark.parametrize(
    "text",
    ["x", "`date`", "a`b", "a``b", "`", "``", " x ", "`a", "a`", "  ", "a ` b"],
)
def test_exact_span_round_trips(text: str) -> None:
    assert exact_literal(exact_span(text)) == text


@pytest.mark.parametrize(
    ("pattern", "response", "expected"),
    [
        ("`` `print` ``", "`print`", True),
        ("`` `print` ``", "print", False),
        ("``a`b``", " a`b ", True),
        ("`a``b`", "a``b", True),
        ("`` ` ``", "`", True),
    ],
)
def test_backtick_in_an_exact_literal_matches_exactly(
    pattern: str, response: str, expected: bool
) -> None:
    assert AnswerPattern(pattern=pattern).matches(response) is expected


def test_blank_text_checks_the_content_of_a_long_fence() -> None:
    with pytest.raises(ValidationError) as info:
        AnswerPattern(pattern="``   ``")
    assert error_types(info.value) == ["blank-text"]

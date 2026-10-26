"""
Pattern string rules (docs/references/patterns.md, "Pattern string"): an
empty pattern and an incomplete backtick span are schema errors, and the
exact literal follows the CommonMark code span. Blank patterns, the spaces
and tabs at the ends and the matching of exact literals live in the corpus.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mdq._exact import exact_literal, exact_span
from mdq.models import AnswerPattern


def error_types(exc: ValidationError) -> list[str]:
    return [error["type"] for error in exc.errors()]


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

"""
The regex syntax table of docs/references/patterns.md ("Supported
constructs"): every construct of the table matches as its row says, and the
constructs outside it are `invalid-regex`.

The shared vectors live in `examples/matching/regex.yaml`; the invalid
documents are the `examples/invalid/short-answer-regex-*.mdq.md` files. The
cases below are the ones the corpus does not have.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from mdq.models._regex import InvalidRegexError, RegexPattern

from _corpus import EXAMPLES_ROOT

_CASES: list[dict[str, Any]] = yaml.safe_load(
    (EXAMPLES_ROOT / "matching" / "regex.yaml").read_text(encoding="utf-8")
)["cases"]

VECTORS = [
    pytest.param(case["pattern"], response, expected, id=f"{case['name']}-{index}")
    for case in _CASES
    for index, (response, expected) in enumerate(
        [(r, True) for r in case["accept"]] + [(r, False) for r in case["reject"]]
    )
]


@pytest.mark.parametrize(("pattern", "response", "expected"), VECTORS)
def test_construct_vectors(pattern: str, response: str, expected: bool) -> None:
    assert RegexPattern(pattern).match(response) is expected


@pytest.mark.parametrize(
    "body",
    [
        r"negro|*",
        r"\ud83d\ude00",
        r"[\udc00]",
        r"\u{D800}",
        r"[\u{dfff}]",
        r"\u00e",
    ],
)
def test_construct_outside_the_table_is_invalid(body: str) -> None:
    with pytest.raises(InvalidRegexError):
        RegexPattern(f"/{body}/")

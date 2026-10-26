"""
The regex syntax table of docs/references/patterns.md ("Supported
constructs"): every construct of the table matches as its row says, and the
constructs outside it are `invalid-regex`.

The shared vectors live in `examples/matching/regex.yaml`; the invalid
documents are the `examples/invalid/short-answer-regex-*.mdq.md` files.
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
        r"(?<rio>negro)",
        r"(n)egro\1",
        r"negro\0",
        r"(?i:negro)",
        r"(?>negro)",
        r"(?#comment)negro",
        r"(?(1)a|b)",
        r"ne++gro",
        r"ne*+gro",
        r"ne?+gro",
        r"\Anegro",
        r"negro\Z",
        r"negro\a",
        r"ne{,3}gro",
        r"negro{",
        r"negro}",
        r"negro]",
        r"rio\-negro",
        r"rio\_negro",
        r"rio\ negro",
        r"negro\cJ",
        r"rio[]negro",
        r"rio[^]negro",
        r"rio[a-\d]negro",
        r"rio[\d-z]negro",
        r"rio[z-a]negro",
        r"rio[\B]negro",
        r"ne{3,2}gro",
        r"*negro",
        r"negro|*",
        r"(?=ne)*gro",
        r"^*negro",
        r"(negro",
        r"negro)",
        r"rio[negro",
        r"\u{110000}",
        r"\x4",
        r"\u00e",
        "negro\\",
    ],
)
def test_construct_outside_the_table_is_invalid(body: str) -> None:
    with pytest.raises(InvalidRegexError):
        RegexPattern(f"/{body}/")


def test_dot_translation_does_not_match_line_terminators() -> None:
    for terminator in ("\n", "\r", " ", " "):
        assert RegexPattern("/a.b/f").match(f"a{terminator}b") is False
    for other in ("\u0085", "\x0b", "\x0c"):
        assert RegexPattern("/a.b/").match(f"a{other}b") is True

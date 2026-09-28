"""
`misplaced-blank` at the block level (fill-in.md, "A blank may appear only
in a regular paragraph"): headings, list items, table cells and
blockquotes cannot host a blank. Code is literal text, so it is not
reported.
"""

from __future__ import annotations

import pytest

from mdq.parser import find_misplaced_blank_markers


@pytest.mark.parametrize(
    "stem",
    [
        "## A capital é [^capital]\n",
        "* A capital é [^capital]\n",
        "> A capital é [^capital]\n",
        "| Capital |\n| --- |\n| [^capital] |\n",
        "A capital é **[^capital]**.\n",
    ],
)
def test_marker_outside_a_top_level_paragraph_is_misplaced(stem: str) -> None:
    assert find_misplaced_blank_markers(stem) == ["capital"]


@pytest.mark.parametrize(
    "stem",
    [
        "A capital do Brasil é [^capital].\n",
        "Escreva `[^capital]` literalmente.\n",
        "```\n[^capital]\n```\n",
    ],
)
def test_marker_in_plain_paragraph_text_or_code_is_not_reported(stem: str) -> None:
    assert find_misplaced_blank_markers(stem) == []

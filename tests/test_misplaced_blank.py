"""
`misplaced-blank` at the block level (fill-in.md, "A blank may appear only
in a regular paragraph"): headings, list items, table cells and
blockquotes cannot host a blank. Code is literal text, so it is not
reported.
"""

from __future__ import annotations

import pytest

from mdq._markdown import find_misplaced_blank_markers


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
        "```\n[^capital]\n```\n",
    ],
)
def test_marker_in_plain_paragraph_text_or_fenced_code_is_not_reported(stem: str) -> None:
    assert find_misplaced_blank_markers(stem) == []


def test_marker_in_a_code_span_is_misplaced() -> None:
    # fill-in.md, "Where blanks may appear": inline code is markup, so a
    # marker inside it is not a plain text run of the paragraph.
    assert find_misplaced_blank_markers("Escreva `[^capital]` literalmente.\n") == [
        "capital"
    ]


@pytest.mark.parametrize("stem", ["Veja [^ a] e [^-x] e [^a/numeric].\n"])
def test_brackets_that_are_not_slug_markers_are_text(stem: str) -> None:
    assert find_misplaced_blank_markers(f"*{stem.strip()}*\n") == []

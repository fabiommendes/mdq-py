"""
`misplaced-blank` (fill-in.md, "Where blanks may appear"): headings, list
items, table cells, blockquotes, emphasis, link text and image alt text
cannot host a blank. Code (fenced, indented, code span) is literal text
and `[^x](url)` is a link, so neither is a blank.
"""

from __future__ import annotations

import pytest

from mdq._markdown import find_blank_markers, find_misplaced_blank_markers


@pytest.mark.parametrize(
    "stem",
    [
        "## A capital é [^capital]\n",
        "* A capital é [^capital]\n",
        "> A capital é [^capital]\n",
        "| Capital |\n| --- |\n| [^capital] |\n",
        "A capital é **[^capital]**.\n",
        "**start [^capital] end**\n",
        "A capital é [a cidade de [^capital]](https://exemplo.com.br).\n",
        "A capital é ![a cidade de [^capital]](capital.png).\n",
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


@pytest.mark.parametrize(
    "stem",
    [
        "Escreva `[^capital]` literalmente.\n",
        "    [^capital]\n",
        "~~~\n[^capital]\n~~~\n",
    ],
)
def test_marker_in_code_is_literal_text(stem: str) -> None:
    assert find_blank_markers(stem) == []


@pytest.mark.parametrize(
    "stem",
    [
        "Veja [^nota](https://www.ibge.gov.br) agora.\n",
        "Veja [^nota][ref] agora.\n",
    ],
)
def test_marker_followed_by_link_syntax_is_a_link_not_a_blank(stem: str) -> None:
    assert find_blank_markers(stem) == []


def test_find_blank_markers_flags_each_marker_by_position() -> None:
    stem = "Um [^a] e *dois [^b]*.\n\n> três [^c]\n"
    assert find_blank_markers(stem) == [("a", False), ("b", True), ("c", True)]


@pytest.mark.parametrize("stem", ["Veja [^ a] e [^-x] e [^a/numeric].\n"])
def test_brackets_that_are_not_slug_markers_are_text(stem: str) -> None:
    assert find_misplaced_blank_markers(f"*{stem.strip()}*\n") == []

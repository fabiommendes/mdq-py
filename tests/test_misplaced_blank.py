"""
`misplaced-blank` (fill-in.md, "Where blanks may appear"). Most placements
live in the corpus (`examples/invalid/fill-in-misplaced-blank-*`,
`examples/valid/fill-in/blank-in-code-*`); this covers the ones the
corpus does not.
"""

from __future__ import annotations

import pytest

from mdq._markdown import find_blank_markers, find_misplaced_blank_markers


def test_marker_in_image_alt_text_is_misplaced() -> None:
    stem = "A capital é ![a cidade de [^capital]](capital.png).\n"
    assert find_misplaced_blank_markers(stem) == ["capital"]


@pytest.mark.parametrize("stem", ["    [^capital]\n", "~~~\n[^capital]\n~~~\n"])
def test_marker_in_indented_code_or_tilde_fence_is_literal_text(stem: str) -> None:
    assert find_blank_markers(stem) == []

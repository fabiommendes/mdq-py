"""
Lazy lines and exact literals of a pattern (docs/references/patterns.md,
"Continuation lines" and "Exact literals"). The parse results and errors
are in the example corpus; this module keeps the helper API.
"""

from __future__ import annotations

import pytest

from mdq._exact import join_pattern_lines


@pytest.mark.parametrize(
    ("lines", "joined"),
    [
        ([], ""),
        (["`a", "``b`"], "`a ``b`"),
    ],
)
def test_join_pattern_lines(lines: list[str], joined: str) -> None:
    assert join_pattern_lines(lines) == joined

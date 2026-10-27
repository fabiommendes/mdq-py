"""
`unmatchable-regex-escape` and the `n` flag (patterns.md, "Regex flags").

The diagnostics per document live in the corpus
(`examples/valid/**/unmatchable-regex-escape*.yaml` and their `.lint.json`).
"""

from __future__ import annotations

from mdq.models._regex import escaped_code_points


def test_escaped_code_points() -> None:
    body = r"\u00e1\xE9\u{1F600}\\u00e1\."
    assert escaped_code_points(body) == [0xE1, 0xE9, 0x1F600]

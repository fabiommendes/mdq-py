"""
`unsafe-thematic-break` (exam.md "Questions", base.md "Additional Rules"):
a thematic break written with `-` warns, since a `---` line opens a block
inside an exam. The corpus covers the warning and the safe breaks; this
module covers a `---` glued to text, which is a setext heading that
`setext-heading` already reports.
"""

import mdq


def _codes(loaded: mdq.Loaded) -> list[tuple[str, tuple[str | int, ...]]]:
    return [(d.code, d.path) for d in loaded.diagnostics if d.severity == "warning"]


def test_setext_heading_is_not_doubly_reported() -> None:
    loaded = mdq.load("# Prova\n\nLeia.\n---\n\n===\n\nQual?\n\n[essay]\n", kind="exam")
    codes = [c for c, _ in _codes(loaded)]
    assert "setext-heading" in codes
    assert "unsafe-thematic-break" not in codes

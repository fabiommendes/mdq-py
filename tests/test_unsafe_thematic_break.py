"""
`unsafe-thematic-break` (exam.md "Questions", base.md "Additional Rules"):
a thematic break written with `-` warns, since a `---` line opens a block
inside an exam. `***` and `___` are safe, and a `---` glued to text is a
setext heading, which `setext-heading` already reports.
"""

import pytest

import mdq


def _codes(loaded: mdq.Loaded) -> list[tuple[str, tuple[str | int, ...]]]:
    return [(d.code, d.path) for d in loaded.diagnostics if d.severity == "warning"]


@pytest.mark.parametrize("line", ["---", "----", "- - -", " ---"])
def test_dash_thematic_break_warns_with_the_field_path(line: str) -> None:
    loaded = mdq.load(f"Um.\n\n{line}\n\nDois.\n\nQual?\n\n[essay]\n")
    assert _codes(loaded) == [("unsafe-thematic-break", ("preamble",))]


@pytest.mark.parametrize("line", ["***", "___", "* * *"])
def test_other_thematic_breaks_are_safe(line: str) -> None:
    loaded = mdq.load(f"Um.\n\n{line}\n\nDois.\n\nQual?\n\n[essay]\n")
    assert _codes(loaded) == []


def test_exam_instructions_are_checked_too() -> None:
    loaded = mdq.load("# Prova\n\nLeia.\n\n---\n\nBoa sorte.\n\n===\n\nQual?\n\n[essay]\n", kind="exam")
    assert ("unsafe-thematic-break", ("instructions",)) in _codes(loaded)


def test_setext_heading_is_not_doubly_reported() -> None:
    loaded = mdq.load("# Prova\n\nLeia.\n---\n\n===\n\nQual?\n\n[essay]\n", kind="exam")
    codes = [c for c, _ in _codes(loaded)]
    assert "setext-heading" in codes
    assert "unsafe-thematic-break" not in codes

"""
docs/references/grammar.md: the grammar whitespace `ws` is only spaces and
tabs. Every other Unicode space is text, and the `non-ascii-whitespace`
lint reports it. The example corpus covers the parse results and lint
codes; this file keeps what it cannot: lint line numbers, a Unicode
space starting a regex pattern line, and the frontmatter comment helper.

The characters are built with `chr` so that this file holds no invisible
code point.
"""

from __future__ import annotations

import pytest

from mdq import load
from mdq._parser import parse_question
from mdq._parser._frontmatter import _extract_comment

NBSP = chr(0x00A0)
EM_SPACE = chr(0x2003)


def _lint(source: str) -> list[tuple[str, int | None]]:
    """(severity, line) of every non-ASCII whitespace diagnostic.

    One severity per code: `warning` is `non-ascii-whitespace` and `info`
    is `non-ascii-whitespace-in-prose`.
    """
    expected = {
        "warning": "non-ascii-whitespace",
        "info": "non-ascii-whitespace-in-prose",
    }
    return [
        (d.severity, d.line)
        for d in load(source, format="mdq").diagnostics
        if d.code in expected.values()
        and d.code == expected.get(d.severity)
    ]


# ---------------------------------------------------------------------
# ws: only spaces and tabs
# ---------------------------------------------------------------------
@pytest.mark.parametrize("ch", [NBSP, EM_SPACE])
def test_unicode_space_starts_a_pattern_line(ch: str) -> None:
    doc = parse_question(
        "Qual a capital?\n\n[short-answer/accept]:\n"
        f"* {ch}/bras[íi]lia/i\n"
    )
    assert doc["accept"] == [f"{ch}/bras[íi]lia/i"]  # type: ignore[typeddict-item]
    loaded = load(
        f"Qual a capital?\n\n[short-answer/accept]:\n* {ch}/bras[íi]lia/i\n",
        format="mdq",
    )
    assert loaded.document is not None
    assert not loaded.document.accept[0].matches("Brasília")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------
def test_unicode_space_line_is_not_blank_in_frontmatter() -> None:
    assert _extract_comment("\n \t\n# Ipê\nid: ipe\n") == "Ipê"
    assert _extract_comment(f"{NBSP}\n# Ipê\nid: ipe\n") is None


# ---------------------------------------------------------------------
# non-ascii-whitespace lint: line numbers (the corpus snapshots keep none)
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "source, line",
    [
        # Start and end of a line.
        (f"{NBSP}Descreva o ipê.\n\n[essay]\n", 1),
        (f"Descreva o ipê.{NBSP}\n\n[essay]\n", 1),
        (f"Descreva o ipê. \t{NBSP} \n\n[essay]\n", 1),
        # After list, heading, blockquote and `!` markers.
        (f"Veja:\n\n>{NBSP}citação\n\nDescreva.\n\n[essay]\n", 3),
        (f"...\n\n*{NBSP}[*] Ipê\n* [ ] Jatobá\n", 3),
        # A tag line, answer included.
        (f"Qual a capital?\n\n[short-answer]:{NBSP}Brasília\n", 3),
        (f"Qual a capital?\n\n[short-answer]: Bras{NBSP}ília\n", 3),
        (f"Quanto?\n\n[numeric]: 42{NBSP}+- 1\n", 3),
        (f"A capital é [^c].\n\n[^c/short-answer]: Bras{NBSP}ília\n", 3),
        # A choice prefix.
        (f"...\n\n* [{NBSP}] Ipê\n* [*] Jatobá\n", 3),
        (f"...\n\n* [*] [ipe]{NBSP}Ipê\n* [ ] Jatobá\n", 3),
        # A pattern line.
        (f"Qual a capital?\n\n[short-answer/accept]:\n* Bras{NBSP}ília\n", 4),
    ],
)
def test_unicode_space_in_syntax_position_is_warning(source: str, line: int) -> None:
    assert ("warning", line) in _lint(source)


def test_report_line_counts_the_frontmatter() -> None:
    source = f"---\nid: ipe\n---\n\nDescreva o ipê{NBSP}amarelo.\n\n[essay]\n"
    assert _lint(source) == [("info", 5)]

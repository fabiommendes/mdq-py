"""
exam.md, "Questions": the `---` that opens a frontmatter or include block
MUST be preceded by a blank line. Without it, CommonMark reads the line as
a setext heading underline and the block is swallowed into the text
before it. Lint `setext-heading` (warning) points at the field holding it.

`examples/valid/exam/setext-heading` covers the `instructions` case. The cases
below keep the ones the corpus cannot hold, such as the text of a message.
"""

from __future__ import annotations

import mdq
from mdq.models._lint import check_setext_heading

TRAP = "# Prova\n\nLeia com atenção.\n---\nid: q1\n---\n\nQual?\n\n* [*] a\n* [ ] b\n"


def _codes(loaded: mdq.Loaded) -> list[tuple[str, tuple[str | int, ...]]]:
    return [(d.code, tuple(d.path)) for d in loaded.diagnostics]


def test_setext_heading_message_suggests_a_blank_line() -> None:
    loaded = mdq.load(TRAP, kind="exam")
    [diag] = [d for d in loaded.diagnostics if d.code == "setext-heading"]
    assert "blank line" in diag.message


def test_fence_glued_to_a_question_epilogue_warns() -> None:
    # The glued include block is swallowed into the epilogue of the first
    # question, which then holds a setext heading.
    source = (
        "# Prova\n\n===\n\nQual?\n\n* [*] a\n* [ ] b\n\nNota: leia.\n---\n"
        "include: outra\n---\n"
    )
    loaded = mdq.load(source, kind="exam")
    assert loaded.document is not None
    assert len(loaded.document.questions) == 1
    assert ("setext-heading", ("questions", 0, "epilogue")) in _codes(loaded)
    assert [c for c, _ in _codes(loaded)].count("setext-heading") == 1


def test_fence_glued_to_a_question_stem_warns() -> None:
    source = "# Prova\n\n===\n\nIntro\n---\nid: q1\n---\n\nQual?\n\n* [*] a\n* [ ] b\n"
    loaded = mdq.load(source, kind="exam")
    assert ("setext-heading", ("questions", 0, "stem")) in _codes(loaded)


def test_atx_heading_is_not_reported() -> None:
    assert list(check_setext_heading("## Título\n\nTexto.", ("instructions",))) == []


def test_equals_underline_message_names_the_equals_line() -> None:
    [diag] = list(check_setext_heading("Parte 1\n===", ("answerKey",)))
    assert "'==='" in diag.message
    assert "'---'" not in diag.message


def test_dash_underline_message_names_the_dash_line() -> None:
    [diag] = list(check_setext_heading("Parte 1\n---", ("answerKey",)))
    assert "'---' that opens a block" in diag.message

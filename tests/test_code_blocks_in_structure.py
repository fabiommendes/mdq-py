"""
A code block is literal text. A line inside one never acts as MDQ
structure: not as the H1 exam title, not as a `===` separator, not as a
`---` frontmatter fence, and not as a body tag.

Also covers `reconstruct_blocks` keeping an indented code block whose
content is non-ASCII whitespace: CommonMark only treats spaces and tabs
as blank.
"""

from __future__ import annotations

import pytest

from mdq import load
from mdq._parser import reconstruct_blocks
from mdq.models import Exam, NumericQuestion

_PYTHON_BLOCK = "```python\n# soma dos estados\nprint(26 + 1)\n```"
_TILDE_BLOCK = "~~~\n# Região Norte\n~~~"


@pytest.mark.parametrize("block", [_PYTHON_BLOCK, _TILDE_BLOCK])
def test_h1_line_in_an_epilogue_code_block_does_not_make_an_exam(block: str) -> None:
    text = f"Quantos estados tem o Brasil?\n\n[numeric]: 26\n\n{block}\n"
    loaded = load(text)
    assert isinstance(loaded.document, NumericQuestion), loaded.diagnostics
    assert loaded.document.epilogue == block


def test_h1_line_in_a_preamble_code_block_does_not_make_an_exam() -> None:
    text = f"{_PYTHON_BLOCK}\n\nQuantos estados tem o Brasil?\n\n[numeric]: 26\n"
    loaded = load(text, kind="question")
    assert isinstance(loaded.document, NumericQuestion), loaded.diagnostics
    assert loaded.document.preamble == _PYTHON_BLOCK


_EXAM_CODE = "```text\n# não é título\n\n===\n\n---\nid: nada\n---\n\n[numeric]: 7\n```"

_EXAM = f"""\
# Prova de Programação

Leia com atenção.

===

Qual é a saída de `print(1 + 1)`?

[numeric]: 2

{_EXAM_CODE}

===

Quantos estados tem o Brasil?

[numeric]: 26
"""


def test_exam_ignores_structure_lines_inside_a_code_block() -> None:
    loaded = load(_EXAM, kind="exam")
    exam = loaded.document
    assert isinstance(exam, Exam), loaded.diagnostics
    assert exam.title == "Prova de Programação"
    assert len(exam.questions) == 2
    first, second = exam.questions
    assert isinstance(first, NumericQuestion)
    assert first.answer == 2
    assert first.epilogue == _EXAM_CODE
    assert isinstance(second, NumericQuestion)
    assert second.answer == 26


@pytest.mark.parametrize(
    "src",
    ["    \xa0", "    a\n     ", "Texto.\n\n    \xa0\xa0"],
)
def test_reconstruct_keeps_an_indented_code_block_of_unicode_whitespace(src: str) -> None:
    blocks = reconstruct_blocks(src)
    assert "\n\n".join(text for _, text in blocks) == src
    assert blocks[-1][0] == "code_block"

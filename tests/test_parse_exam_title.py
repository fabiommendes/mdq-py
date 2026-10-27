"""
`parse_exam` called directly on a text that `is_exam` does not route to it.

The corpus routes a document by its shape, so it cannot reach these paths.
"""

from __future__ import annotations

import pytest

from mdq._parser import parse_exam
from mdq.errors import MissingField


@pytest.mark.parametrize(
    "text",
    [
        "Descreva o ipê.\n\n[essay]\n",
        " # Prova\n\n[essay]\n",
    ],
)
def test_text_without_h1_is_a_missing_title(text: str) -> None:
    with pytest.raises(MissingField) as excinfo:
        parse_exam(text)
    assert excinfo.value.field == "title"


@pytest.mark.parametrize(
    "text",
    [
        "```text\n# Falso título\n```\n\n# Título real\n",
        "Antes.\n\n    # Falso título\n\n# Título real\n",
    ],
)
def test_h1_line_in_code_is_not_the_title(text: str) -> None:
    assert parse_exam(text)["title"] == "Título real"

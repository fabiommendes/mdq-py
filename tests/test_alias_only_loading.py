"""
Building a model in Python takes the field names, even though a document
is validated by alias only (the alias-only loading itself is covered by
the invalid corpus, e.g. `essay-snake-case-key`).
"""

from __future__ import annotations

from mdq import load
from mdq.models import EssayQuestion


def test_python_construction_takes_field_names() -> None:
    assert EssayQuestion(stem="Explique.", answer_key="luz").answer_key == "luz"


def test_include_all_snake_case_is_not_an_include_block() -> None:
    doc = {"type": "exam", "title": "Biomas", "questions": [{"include_all": "biome"}]}
    [d] = load(doc).diagnostics
    assert (d.code, d.path) == ("schema-error", ("questions", 0))
    assert "did you mean `includeAll` instead of `include_all`?" in d.message

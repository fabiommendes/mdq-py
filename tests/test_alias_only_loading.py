"""
A document is validated by alias only: the Python name of an aliased
field is an unknown key, like in the schema. Building a model in Python
still takes the field names.
"""

from __future__ import annotations

import pytest

from mdq import load
from mdq.models import EssayQuestion


def _paths(doc: dict) -> list[tuple[str, tuple]]:
    return [(d.code, d.path) for d in load(doc).diagnostics]


@pytest.mark.parametrize(
    ("doc", "path"),
    [
        (
            {"type": "essay", "stem": "Explique.", "answer_key": "luz"},
            ("answer_key",),
        ),
        (
            {
                "type": "short-answer",
                "stem": "Qual?",
                "accept": ["a"],
                "incorrect_feedback": "n",
            },
            ("incorrect_feedback",),
        ),
        (
            {"type": "numeric", "stem": "Quanto?", "answer": 1, "decimal_places": 2},
            ("decimal_places",),
        ),
        (
            {
                "type": "exam",
                "title": "Biomas",
                "questions": [
                    {"type": "essay", "stem": "Explique.", "answer_key": "luz"}
                ],
            },
            ("questions", 0, "answer_key"),
        ),
    ],
)
def test_snake_case_key_is_a_schema_error(doc: dict, path: tuple) -> None:
    assert ("schema-error", path) in _paths(doc)
    assert load(doc).document is None


def test_include_all_snake_case_is_not_an_include_block() -> None:
    doc = {"type": "exam", "title": "Biomas", "questions": [{"include_all": "biome"}]}
    [d] = load(doc).diagnostics
    assert (d.code, d.path) == ("schema-error", ("questions", 0))
    assert "did you mean `includeAll` instead of `include_all`?" in d.message


def test_camel_case_key_still_loads() -> None:
    doc = {"type": "essay", "stem": "Explique.", "answerKey": "luz"}
    assert load(doc).document is not None


def test_python_construction_takes_field_names() -> None:
    assert EssayQuestion(stem="Explique.", answer_key="luz").answer_key == "luz"


def test_markdown_frontmatter_snake_case_is_an_invalid_field() -> None:
    source = "---\nanswer_key: luz\n---\n\nExplique.\n\n[essay]\n"
    loaded = load(source, format="mdq")
    [d] = [d for d in loaded.diagnostics if d.code == "invalid-frontmatter-field"]
    assert (d.code, d.severity, d.path) == (
        "invalid-frontmatter-field",
        "error",
        ("answer_key",),
    )
    assert loaded.document is None

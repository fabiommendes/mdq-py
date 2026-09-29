"""
exam.md and base.md: `id`, `include` and `include-all` take only a YAML
string. A number or boolean is not converted (`id: 2024` is not
`"2024"`); `load` reports it as `schema-error`, as it does for a
YAML/JSON document.
"""

from __future__ import annotations

import pytest

from mdq import load


def _errors(text: str) -> list[tuple[str, tuple]]:
    loaded = load(text, format="mdq")
    assert loaded.document is None
    return [(d.code, d.path) for d in loaded.diagnostics if d.severity == "error"]


@pytest.mark.parametrize("value", ["2024", "yes", "3.5", "[a, b]"])
def test_question_id_must_be_a_string(value: str) -> None:
    text = f"---\nid: {value}\n---\n\nDescreva o Cerrado.\n\n[essay]\n"
    assert _errors(text) == [("schema-error", ("id",))]


@pytest.mark.parametrize("value", ["2024", "no"])
def test_exam_id_must_be_a_string(value: str) -> None:
    text = f"---\nid: {value}\n---\n\n# Prova\n\nDescreva o Cerrado.\n\n[essay]\n"
    assert _errors(text) == [("schema-error", ("id",))]


def test_question_id_inside_an_exam_must_be_a_string() -> None:
    text = "# Prova\n\n---\nid: 7\n---\n\nDescreva o Cerrado.\n\n[essay]\n"
    assert _errors(text) == [("schema-error", ("questions", 0, "id"))]


@pytest.mark.parametrize(("key", "value"), [("include", "yes"), ("include", "2024"), ("include-all", "7")])
def test_include_must_be_a_string(key: str, value: str) -> None:
    text = f"# Prova\n\n---\n{key}: {value}\n---\n"
    assert _errors(text) == [("schema-error", ("questions", 0, key))]


def test_quoted_values_are_strings() -> None:
    text = '---\nid: "2024"\n---\n\n# Prova\n\n---\ninclude: "2024"\n---\n'
    loaded = load(text, format="mdq")
    assert loaded.document is not None, loaded.diagnostics
    assert loaded.document.id == "2024"


def test_null_id_is_absent() -> None:
    for text in (
        "---\nid:\n---\n\nDescreva o Cerrado.\n\n[essay]\n",
        "---\nid:\n---\n\n# Prova\n\nDescreva o Cerrado.\n\n[essay]\n",
    ):
        loaded = load(text, format="mdq")
        assert loaded.document is not None, loaded.diagnostics
        assert loaded.document.id is None


def test_exam_entry_error_path_has_no_union_tag() -> None:
    doc = {"type": "exam", "title": "Prova", "questions": [{"type": "essay"}]}
    loaded = load(doc)
    assert [(d.code, d.path) for d in loaded.diagnostics] == [("schema-error", ("questions", 0, "stem"))]

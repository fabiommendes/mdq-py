"""
J1: a key repeated in the same YAML mapping is an error, not
last-value-wins (base.md, "Frontmatter"; exam.md, "Frontmatter"). The
same code, `yaml-syntax-error`, covers Markdown frontmatter and a YAML
document. A JSON document with a repeated key is `json-syntax-error`.

J3: `tags:` with a null value in an exam's frontmatter is absent, as it
is in a question's; a non-list, non-string `tags` is a `schema-error`.
"""

from __future__ import annotations

import pytest

from mdq import load


def _codes(text: str, format: str = "mdq") -> list[str]:
    loaded = load(text, format=format)
    assert loaded.document is None
    return [d.code for d in loaded.diagnostics if d.severity == "error"]


QUESTION = "---\n{front}\n---\n\nDescreva o Cerrado.\n\n[essay]\n"
EXAM = "---\n{front}\n---\n\n# Prova de Geografia\n\nDescreva o Cerrado.\n\n[essay]\n"


@pytest.mark.parametrize(
    "front",
    [
        "id: rio-amazonas\nid: rio-negro",
        "title: Cerrado\ntags: [bioma]\ntitle: Caatinga",
        "meta:\n  fonte: IBGE\n  fonte: Embrapa",
    ],
)
def test_duplicate_key_in_question_frontmatter(front: str) -> None:
    assert _codes(QUESTION.format(front=front)) == ["yaml-syntax-error"]


def test_duplicate_key_in_exam_frontmatter() -> None:
    assert _codes(EXAM.format(front="id: geo\nid: geografia")) == ["yaml-syntax-error"]


def test_duplicate_key_in_a_question_block_of_an_exam() -> None:
    text = "# Prova\n\n---\nid: q1\nid: q2\n---\n\nDescreva o Cerrado.\n\n[essay]\n"
    assert _codes(text) == ["yaml-syntax-error"]


def test_duplicate_key_in_an_include_block() -> None:
    text = "# Prova\n\n---\ninclude: cerrado\ninclude: caatinga\n---\n"
    assert _codes(text) == ["yaml-syntax-error"]


def test_duplicate_key_in_a_yaml_document() -> None:
    text = "type: essay\nstem: Descreva o Cerrado.\nstem: Descreva a Caatinga.\n"
    assert _codes(text, format="yaml") == ["yaml-syntax-error"]


def test_duplicate_key_in_a_json_document() -> None:
    text = '{"type": "essay", "stem": "Descreva o Cerrado.", "stem": "Descreva a Caatinga."}'
    assert _codes(text, format="json") == ["json-syntax-error"]


def test_malformed_frontmatter_yaml_is_a_diagnostic() -> None:
    assert _codes(QUESTION.format(front="id: [cerrado")) == ["yaml-syntax-error"]


def test_same_key_in_different_mappings_is_fine() -> None:
    text = QUESTION.format(front="meta:\n  a:\n    id: 1\n  b:\n    id: 2")
    assert load(text, format="mdq").document is not None


def test_yaml_document_reads_hh_mm_as_a_string() -> None:
    text = "type: exam\ntitle: Prova\nduration: 1:30\nquestions: []\n"
    loaded = load(text, format="yaml")
    assert loaded.document is not None, loaded.diagnostics
    assert loaded.document.to_dict()["duration"] == "PT1H30M"


# ---------------------------------------------------------------------
# J3: tags
# ---------------------------------------------------------------------


def test_null_tags_in_an_exam_are_absent() -> None:
    loaded = load(EXAM.format(front="tags:"), format="mdq")
    assert loaded.document is not None, loaded.diagnostics
    assert not loaded.document.tags


def test_null_tags_in_a_question_are_absent() -> None:
    loaded = load(QUESTION.format(front="tags:"), format="mdq")
    assert loaded.document is not None, loaded.diagnostics
    assert loaded.document.tags == []


@pytest.mark.parametrize("template", [QUESTION, EXAM])
@pytest.mark.parametrize("value", ["5", "{a: 1}", "true"])
def test_tags_of_the_wrong_type_are_a_schema_error(template: str, value: str) -> None:
    loaded = load(template.format(front=f"tags: {value}"), format="mdq")
    assert loaded.document is None
    assert [(d.code, d.path) for d in loaded.diagnostics] == [("schema-error", ("tags",))]

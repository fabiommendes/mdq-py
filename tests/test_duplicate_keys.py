"""
J1: a key repeated in the same YAML mapping is an error, not
last-value-wins (base.md, "Frontmatter"; exam.md, "Frontmatter"). The
same code, `yaml-syntax-error`, covers Markdown frontmatter and a YAML
document. The Markdown and JSON cases live in the example corpus.

J3: a non-list, non-string `tags` is a `schema-error`. A null `tags` is
absent (corpus: `valid/*/tags-null`).
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


def test_duplicate_key_in_a_yaml_document() -> None:
    text = "type: essay\nstem: Descreva o Cerrado.\nstem: Descreva a Caatinga.\n"
    assert _codes(text, format="yaml") == ["yaml-syntax-error"]


def test_yaml_document_reads_hh_mm_as_a_string() -> None:
    text = "type: exam\ntitle: Prova\nduration: 1:30\nquestions: []\n"
    loaded = load(text, format="yaml")
    assert loaded.document is not None, loaded.diagnostics
    assert loaded.document.to_dict()["duration"] == "PT1H30M"


# ---------------------------------------------------------------------
# J3: tags
# ---------------------------------------------------------------------


@pytest.mark.parametrize("template", [QUESTION, EXAM])
@pytest.mark.parametrize("value", ["5", "{a: 1}", "true"])
def test_tags_of_the_wrong_type_are_a_schema_error(template: str, value: str) -> None:
    loaded = load(template.format(front=f"tags: {value}"), format="mdq")
    assert loaded.document is None
    assert [(d.code, d.path) for d in loaded.diagnostics] == [("schema-error", ("tags",))]

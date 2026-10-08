"""
base.md, "Frontmatter": a `null` value in any OPTIONAL field is the same
as an absent field, in Markdown, YAML and JSON, including nested objects
such as choices and blanks. A field with a default takes its default.
"""

from __future__ import annotations

from typing import Any

import pytest
from _corpus import EXAMPLES_ROOT

import mdq

MC_BODY = "Qual?\n\n* [*] [a] Bahia\n* [ ] [b] Maranhão\n"


def _errors(loaded: mdq.Loaded) -> list[str]:
    return [d.code for d in loaded.diagnostics if d.severity == "error"]


def _mc_md(frontmatter: str) -> mdq.Loaded:
    return mdq.load(f"---\n{frontmatter}\n---\n\n{MC_BODY}", kind="question")


#
# AC1: null in a question frontmatter field is an absent field
#
@pytest.mark.parametrize(
    "line", ["title:", "author: ~", "title: null", "locale:", "uuid: ~", "comment:", "meta:"]
)
def test_null_without_default_is_absent(line: str) -> None:
    loaded = _mc_md(line)
    assert _errors(loaded) == []
    field = line.split(":")[0]
    assert getattr(loaded.document, field) is None
    assert f"{field}:" not in loaded.document.render()


def test_null_weight_takes_the_default() -> None:
    loaded = _mc_md("weight: null")
    assert _errors(loaded) == []
    assert loaded.document.weight == 1
    assert "weight:" not in loaded.document.render()


def test_null_grading_and_shuffle_are_inherit() -> None:
    loaded = _mc_md("grading: null\nshuffle: ~")
    assert _errors(loaded) == []
    assert loaded.document.grading == "inherit"
    assert loaded.document.shuffle == "inherit"


def test_null_essay_input_takes_the_default() -> None:
    loaded = mdq.load("---\ninput: null\n---\n\nDisserte.\n\n[essay]\n", kind="question")
    assert _errors(loaded) == []
    assert loaded.document.input == "text"


def test_null_diacritics_takes_the_default() -> None:
    loaded = mdq.load(
        "---\ndiacritics:\n---\n\nQual?\n\n[short-answer]: Bahia\n", kind="question"
    )
    assert _errors(loaded) == []
    assert loaded.document.diacritics == "fold"


#
# AC2: the same in JSON and YAML, including nested objects
#
def test_null_in_a_json_dict_is_absent() -> None:
    loaded = mdq.load(
        {"type": "essay", "stem": "Disserte.", "weight": None, "title": None, "input": None},
        kind="question",
    )
    assert _errors(loaded) == []
    assert loaded.document.weight == 1
    assert loaded.document.title is None
    assert loaded.document.input == "text"


def test_null_in_a_nested_choice_is_absent() -> None:
    loaded = mdq.load(
        {
            "type": "multiple-choice",
            "stem": "Qual?",
            "choices": [
                {"text": "a", "score": 1, "feedback": None, "id": None},
                {"text": "b", "score": None, "comment": None},
            ],
        },
        kind="question",
    )
    assert _errors(loaded) == []
    first, second = loaded.document.choices
    assert first.feedback is None and first.id is None
    assert second.score is None and second.comment is None


def test_null_in_a_nested_blank_is_absent() -> None:
    loaded = mdq.load(
        {
            "type": "fill-in",
            "stem": "Quanto [^x]?",
            "blanks": [{"id": "x", "type": "numeric", "answer": 42, "tolerance": None}],
        },
        kind="question",
    )
    assert _errors(loaded) == []
    assert loaded.document.blanks[0].tolerance is None


def test_null_in_a_yaml_source_is_absent() -> None:
    loaded = mdq.load(
        "type: essay\nstem: Disserte.\nweight: ~\ntitle:\n", kind="question", format="yaml"
    )
    assert _errors(loaded) == []
    assert loaded.document.weight == 1


#
# AC3: exam fields, including the ones the parser converts
#
@pytest.mark.parametrize(
    ("line", "field", "value"),
    [
        ("duration:", "duration", None),
        ("start: ~", "start", None),
        ("grading: null", "grading", "symmetric"),
        ("penalty:", "penalty", "none"),
        ("shuffle: null", "shuffle", False),
        ("author:", "author", None),
        ("course: ~", "course", None),
    ],
)
def test_null_exam_field_is_absent(line: str, field: str, value: Any) -> None:
    source = f"---\n{line}\n---\n\n# Prova\n\n## Q1\n\n{MC_BODY}"
    loaded = mdq.load(source, kind="exam")
    assert _errors(loaded) == []
    assert getattr(loaded.document, field) == value


def test_null_meta_value_is_kept() -> None:
    # `meta` maps to arbitrary JSON; its values are not MDQ fields.
    loaded = mdq.load(
        {"type": "essay", "stem": "Disserte.", "meta": {"a": None}}, kind="question"
    )
    assert _errors(loaded) == []
    assert loaded.document.meta == {"a": None}


def test_corpus_null_fields_example_matches_its_yaml() -> None:
    source = EXAMPLES_ROOT / "valid" / "multiple-choice" / "null-fields.mdq.md"
    from_md = mdq.load(source, kind="question")
    from_yaml = mdq.load(source.with_suffix("").with_suffix(".yaml"), kind="question")
    assert _errors(from_md) == []
    assert from_md.document == from_yaml.document
    assert from_md.document.weight == 1

"""
`blank-text` (docs/lint-codes.md, "Errors"): a free-text field, or a
`tags` entry, that is defined but empty or whitespace only. One error
code for every field; `null` and the identifier fields are schema errors.

Written against the public `mdq.load` API and the models.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

import mdq
from mdq import Diagnostic, models

BLANKS = ["", "   ", "\n\t ", "​"]

_MC_CHOICES: list[dict[str, Any]] = [
    {"id": "brasilia", "text": "Brasília", "score": 1},
    {"id": "salvador", "text": "Salvador"},
]
_MS_CHOICES: list[dict[str, Any]] = [
    {"id": "cerrado", "text": "Cerrado", "correct": True},
    {"id": "tundra", "text": "Tundra", "correct": False},
]
_TF_CHOICES: list[dict[str, Any]] = [
    {"id": "cerrado", "text": "O Cerrado é um bioma.", "correct": True},
    {"id": "tundra", "text": "A Tundra é um bioma.", "correct": False},
]
_LINES = [[0, "a"], [0, "b"]]


def _essay(**fields: Any) -> dict[str, Any]:
    return {"type": "essay", "stem": "Explique o efeito Coriolis.", **fields}


def _errors(doc: Any, **kwargs: Any) -> list[Diagnostic]:
    loaded = mdq.load(doc, **kwargs)
    assert loaded.document is None
    return [d for d in loaded.diagnostics if d.severity == "error"]


def _assert_blank_text(doc: Any, path: tuple[str | int, ...], **kwargs: Any) -> None:
    errors = _errors(doc, **kwargs)
    assert [(d.code, d.path) for d in errors] == [("blank-text", path)]


def _choice_blank_fill_in(choice: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "fill-in",
        "stem": "A capital é [^capital].",
        "blanks": [
            {
                "id": "capital",
                "type": "multiple-choice",
                "choices": [{"id": "brasilia", "text": "Brasília", "score": 1}, choice],
            }
        ],
    }


#
# Each field family, with "" and whitespace only
#
@pytest.mark.parametrize("value", BLANKS)
@pytest.mark.parametrize(
    "field_name", ["title", "author", "comment", "preamble", "stem", "epilogue", "answerKey"]
)
def test_question_free_text_field(field_name: str, value: str) -> None:
    _assert_blank_text(_essay(**{field_name: value}), (field_name,))


@pytest.mark.parametrize("value", BLANKS)
def test_short_answer_incorrect_feedback(value: str) -> None:
    doc = {
        "type": "short-answer",
        "stem": "Capital?",
        "accept": ["Brasília"],
        "incorrectFeedback": value,
    }
    _assert_blank_text(doc, ("incorrectFeedback",))


@pytest.mark.parametrize("value", BLANKS)
@pytest.mark.parametrize("field_name", ["title", "author", "description", "course", "instructions"])
def test_exam_free_text_field(field_name: str, value: str) -> None:
    _assert_blank_text({"type": "exam", field_name: value, "questions": []}, (field_name,))


@pytest.mark.parametrize("value", BLANKS)
@pytest.mark.parametrize("field_name", ["text", "feedback", "comment"])
@pytest.mark.parametrize(
    ("question_type", "choices"),
    [
        ("multiple-choice", _MC_CHOICES),
        ("multiple-selection", _MS_CHOICES),
        ("true-false", _TF_CHOICES),
    ],
)
def test_choice_field(
    question_type: str, choices: list[dict[str, Any]], field_name: str, value: str
) -> None:
    choices = [choices[0], {**choices[1], field_name: value}]
    doc = {"type": question_type, "stem": "Qual?", "choices": choices}
    _assert_blank_text(doc, ("choices", 1, field_name))


@pytest.mark.parametrize("value", BLANKS)
@pytest.mark.parametrize("field_name", ["text", "feedback", "comment"])
def test_fill_in_choice_blank_field(field_name: str, value: str) -> None:
    choice = {"id": "salvador", "text": "Salvador", field_name: value}
    _assert_blank_text(_choice_blank_fill_in(choice), ("blanks", 0, "choices", 1, field_name))


@pytest.mark.parametrize("value", BLANKS)
@pytest.mark.parametrize("field_name", ["feedback", "comment"])
@pytest.mark.parametrize("section", ["accept", "reject"])
def test_ordering_alternative_field(section: str, field_name: str, value: str) -> None:
    alternative = {"lines": [[0, "b"], [0, "a"]], field_name: value}
    doc = {"type": "ordering", "stem": "Ordene.", "lines": _LINES, section: [alternative]}
    _assert_blank_text(doc, (section, 0, field_name))


@pytest.mark.parametrize("value", BLANKS)
@pytest.mark.parametrize("field_name", ["feedback", "comment"])
def test_short_answer_pattern_field(field_name: str, value: str) -> None:
    doc = {
        "type": "short-answer",
        "stem": "Capital?",
        "accept": [{"pattern": "Brasília", field_name: value}],
    }
    _assert_blank_text(doc, ("accept", 0, field_name))


@pytest.mark.parametrize("value", BLANKS)
def test_fill_in_short_answer_blank_pattern_feedback(value: str) -> None:
    doc = {
        "type": "fill-in",
        "stem": "A capital é [^c].",
        "blanks": [
            {
                "id": "c",
                "type": "short-answer",
                "accept": [{"pattern": "Brasília", "feedback": value}],
            }
        ],
    }
    _assert_blank_text(doc, ("blanks", 0, "accept", 0, "feedback"))


def test_blank_text_is_reported_for_every_blank_field() -> None:
    errors = _errors(_essay(title=" ", comment="", answerKey="\n"))
    assert sorted((d.code, d.path) for d in errors) == [
        ("blank-text", ("answerKey",)),
        ("blank-text", ("comment",)),
        ("blank-text", ("title",)),
    ]


def test_a_field_with_a_visible_character_is_not_blank() -> None:
    loaded = mdq.load(_essay(title=" Coriolis ", comment="x", answerKey="​x"))
    assert loaded.document is not None
    assert "blank-text" not in [d.code for d in loaded.diagnostics]


def test_a_markdown_comment_that_is_empty_is_not_stored() -> None:
    # No `comment` is written, so there is nothing to report.
    loaded = mdq.load("---\nid: q\ntitle: T\n---\n\nExplique.\n\n[essay]\n")
    assert "blank-text" not in [d.code for d in loaded.diagnostics]


#
# The check is on the models too, not only on `load`
#
def test_building_a_model_with_a_blank_field_raises() -> None:
    with pytest.raises(ValidationError) as excinfo:
        models.EssayQuestion(stem="Explique.", title="")
    assert [e["type"] for e in excinfo.value.errors()] == ["blank-text"]


def test_yaml_source_is_checked() -> None:
    _assert_blank_text(
        "type: essay\nstem: Explique.\ntitle: ''\n", ("title",), format="yaml"
    )


def test_json_source_is_checked() -> None:
    _assert_blank_text(
        '{"type": "essay", "stem": "Explique.", "answerKey": "  "}',
        ("answerKey",),
        format="json",
    )


#
# null and identifier fields are schema errors
#
def test_null_choice_text_is_a_schema_error() -> None:
    doc = {"type": "multiple-choice", "stem": "Qual?", "choices": [_MC_CHOICES[0], {"text": None}]}
    errors = _errors(doc)
    assert [(d.code, d.path) for d in errors] == [("schema-error", ("choices", 1, "text"))]


def test_null_stem_is_a_schema_error() -> None:
    errors = _errors({"type": "essay", "stem": None})
    assert [d.code for d in errors] == ["schema-error"]


def test_null_tag_entry_is_a_schema_error() -> None:
    errors = _errors(_essay(tags=[None]))
    assert [(d.code, d.path) for d in errors] == [("schema-error", ("tags", 0))]


@pytest.mark.parametrize(
    ("doc", "path"),
    [
        (_essay(id=""), ("id",)),
        (_essay(input="code", highlight=""), ("highlight",)),
        ({"type": "exam", "id": "", "questions": []}, ("id",)),
        ({"type": "exam", "questions": [{"include": ""}]}, ("questions", 0, "include")),
        ({"type": "exam", "questions": [{"includeAll": ""}]}, ("questions", 0, "includeAll")),
        (
            {
                "type": "short-answer",
                "stem": "Capital?",
                "accept": [{"pattern": ""}],
            },
            ("accept", 0, "pattern"),
        ),
    ],
)
def test_identifier_and_syntax_fields_keep_their_schema_error(
    doc: dict[str, Any], path: tuple[str | int, ...]
) -> None:
    errors = _errors(doc)
    assert [(d.code, d.path) for d in errors][:1] == [("schema-error", path)]


#
# tags
#
def _md(tags: str) -> str:
    return f"---\nid: q\ntitle: T\ntags: {tags}\n---\n\nExplique.\n\n[essay]\n"


def _exam_md(tags: str) -> str:
    return f"---\ntitle: T\ntags: {tags}\n---\n\n# [e] Prova\n\n---\nid: q\n---\n\nExplique.\n\n[essay]\n"


@pytest.mark.parametrize("tags", ['"cerrado, bioma,"', '"cerrado,bioma,"', "cerrado, bioma,"])
def test_final_comma_of_a_tags_string_is_dropped(tags: str) -> None:
    loaded = mdq.load(_md(tags))
    assert loaded.document is not None
    assert loaded.document.tags == ["cerrado", "bioma"]
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []


@pytest.mark.parametrize(
    ("tags", "path"),
    [
        ('"a,, b"', ("tags", 1)),
        ('", a"', ("tags", 0)),
        ('"a, ,"', ("tags", 1)),
        ('""', ("tags", 0)),
        ('"  "', ("tags", 0)),
        ('","', ("tags", 0)),
    ],
)
def test_other_empty_parts_of_a_tags_string_are_blank_text(
    tags: str, path: tuple[str | int, ...]
) -> None:
    _assert_blank_text(_md(tags), path)


@pytest.mark.parametrize("entry", ["''", "'  '"])
def test_blank_entry_in_a_tags_list_is_blank_text(entry: str) -> None:
    _assert_blank_text(_md(f"[cerrado, {entry}]"), ("tags", 1))


@pytest.mark.parametrize("entry", ["", "   "])
def test_blank_entry_in_a_tags_list_of_a_dict_is_blank_text(entry: str) -> None:
    _assert_blank_text(_essay(tags=["cerrado", entry]), ("tags", 1))


def test_exam_tags_in_a_dict_follow_the_same_rules() -> None:
    _assert_blank_text({"type": "exam", "tags": ["a", " "], "questions": []}, ("tags", 1))


def test_exam_tags_string_drops_the_final_comma() -> None:
    loaded = mdq.load(_exam_md('"cerrado, bioma,"'))
    assert loaded.document is not None
    assert loaded.document.tags == ["cerrado", "bioma"]


def test_exam_tags_string_with_an_inner_empty_part_is_blank_text() -> None:
    _assert_blank_text(_exam_md('"a,, b"'), ("tags", 1))


#
# Markdown: cases that must reach the check instead of failing the parse
#
_MD_HEAD = "---\nid: q\ntitle: T\n---\n\nQual a capital?\n\n"


def test_markdown_choice_with_no_text() -> None:
    _assert_blank_text(_MD_HEAD + "* [ ]\n* [*] Brasília\n", ("choices", 0, "text"))


def test_markdown_choice_with_only_an_id_has_no_text() -> None:
    _assert_blank_text(_MD_HEAD + "* [ ] Salvador\n* [*] [brasilia]\n", ("choices", 1, "text"))


def test_markdown_choice_id_is_not_taken_as_text() -> None:
    loaded = mdq.load(_MD_HEAD + "* [*] [brasilia] Brasília\n* [ ] Salvador\n")
    assert loaded.document is not None
    assert (loaded.document.choices[0].id, loaded.document.choices[0].text) == (
        "brasilia",
        "Brasília",
    )


@pytest.mark.parametrize("marks", [">", ">\n  >", ">   "])
def test_markdown_feedback_block_of_empty_marker_lines(marks: str) -> None:
    source = _MD_HEAD + f"* [*] Brasília\n  {marks}\n* [ ] Salvador\n"
    _assert_blank_text(source, ("choices", 0, "feedback"))


def test_markdown_comment_block_of_empty_marker_lines() -> None:
    source = _MD_HEAD + "* [*] Brasília\n  !\n* [ ] Salvador\n"
    _assert_blank_text(source, ("choices", 0, "comment"))


def test_markdown_feedback_with_text_after_an_empty_marker_line_is_kept() -> None:
    loaded = mdq.load(_MD_HEAD + "* [*] Brasília\n  >\n  > Isso.\n* [ ] Salvador\n")
    assert loaded.document is not None
    assert loaded.document.choices[0].feedback == "Isso."


def test_markdown_ordering_alternative_with_empty_feedback_block() -> None:
    source = (
        "---\nid: q\ntitle: T\n---\n\nOrdene.\n\n[ordering]\n\n* a\n* b\n\n"
        "## [accept]\n\n>\n\n* b\n* a\n"
    )
    _assert_blank_text(source, ("accept", 0, "feedback"))

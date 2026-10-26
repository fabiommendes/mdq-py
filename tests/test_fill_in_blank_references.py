"""
Blank references and definition errors of a fill-in question
(docs/question-types/fill-in.md "Blank definitions", "Choice blanks" and
"Additional Rules"; docs/references/grammar.md "Content of a list item").
"""

from __future__ import annotations

import pytest

import mdq
from mdq import errors
from mdq._parser import parse_question


def _load(source: str) -> mdq.Loaded:
    return mdq.load(source, kind="question")


def test_a_repeated_blank_reference_is_an_error_at_the_stem() -> None:
    loaded = _load(
        "O rio [^rio] nasce nos Andes. O rio [^rio] chega ao Atlântico.\n\n"
        "[^rio/short-answer]: Amazonas\n"
    )
    assert loaded.document is None
    assert [(d.code, d.severity, d.path) for d in loaded.diagnostics] == [
        ("duplicate-blank-reference", "error", ("stem",))
    ]


def test_a_blank_in_code_is_not_a_second_reference() -> None:
    loaded = _load(
        "O rio [^rio] tem um marcador `[^rio]` em código.\n\n"
        "[^rio/short-answer]: Amazonas\n"
    )
    assert loaded.document is not None


def test_text_on_a_choice_tag_line_suggests_the_short_answer_suffix() -> None:
    with pytest.raises(errors.ParseError, match=r"\[\^capital/short-answer\]"):
        parse_question("A capital é [^capital].\n\n[^capital]: Brasília\n")


def test_a_list_item_after_short_answer_content_is_a_parse_error() -> None:
    with pytest.raises(errors.ParseError):
        parse_question(
            "A capital é [^capital].\n\n[^capital/short-answer]: Brasília\n* Brasilia\n"
        )


def test_a_change_of_bullet_character_starts_a_new_list() -> None:
    source = "A capital é [^capital].\n\n[^capital/short-answer]:\n* Brasília\n- Brasilia\n"
    with pytest.raises(errors.ParseError, match="same list marker"):
        parse_question(source)
    # With a blank line the second list is a normal epilogue element.
    question = parse_question(source.replace("\n- Brasilia", "\n\n- Brasilia"))
    assert question["blanks"][0]["accept"] == ["Brasília"]
    assert question["epilogue"] == "- Brasilia"

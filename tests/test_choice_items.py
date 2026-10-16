"""
The item of a choice list and the feedback and comment blocks shared by
every element that carries them (docs/references/choices.md;
docs/references/grammar.md, "Content of a list item" and "Feedback and
comment lines"), and the `stray-choice-marker` warning
(question-base.md, "Forbidden elements").

The corpus covers multiple selection; these cases cover the other users
of the same rules and the indentation edge cases.
"""

from __future__ import annotations

import pytest

import mdq
from mdq._parser import parse_question
from mdq.errors import MissingField, ParseError

STEM = "Quais destes rios correm no Brasil?\n\n"


def _codes(loaded: mdq.Loaded) -> list[tuple[str, tuple[object, ...]]]:
    """The code and path of each warning and error, without `info`."""
    return [(d.code, tuple(d.path)) for d in loaded.diagnostics if d.severity != "info"]


#
# B2: one feedback block and one comment block per element
#
@pytest.mark.parametrize(
    "source",
    [
        # Multiple choice, a blank line between two feedback blocks.
        STEM + "* [*] Amazonas\n  > Maior em volume.\n\n  > Muito longo.\n* [ ] Nilo\n",
        # True/false, a comment between two feedback blocks.
        STEM + "* [V] Amazonas\n  > Maior.\n  ! Nota.\n  > Longo.\n* [F] Nilo\n",
        # Two comment blocks.
        STEM + "* [x] Amazonas\n  ! Nota.\n\n  ! Outra nota.\n* [ ] Nilo\n",
        # A comment between two comment blocks of the other order.
        STEM + "* [x] Amazonas\n  ! Nota.\n  > Maior.\n  ! Outra.\n* [ ] Nilo\n",
        # A fill-in choice blank.
        "O maior rio é o [^rio].\n\n[^rio]:\n"
        "* [*] Amazonas\n  > Maior.\n\n  > Longo.\n* [ ] Nilo\n",
        # A pattern item of a short answer.
        "Qual é o maior rio do Brasil?\n\n[short-answer]:\n"
        "* Amazonas\n  > Maior.\n\n  > Longo.\n",
        # A section of ordering.
        "Ordene os rios.\n\n[ordering]\n\n* Amazonas\n* Negro\n\n"
        "## [reject]\n\n> Ao contrário.\n\n> De novo.\n\n* Negro\n* Amazonas\n",
    ],
)
def test_a_second_block_of_the_same_kind_is_a_parse_error(source: str) -> None:
    with pytest.raises(ParseError):
        parse_question(source)


def test_a_nested_block_after_the_choice_text_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_question(STEM + "* [x] Amazonas\n  - Negro\n* [ ] Nilo\n")


def test_a_paragraph_after_a_blank_line_in_a_choice_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_question(STEM + "* [x] Amazonas\n\n  Maior em volume.\n* [ ] Nilo\n")


#
# B3: an empty marker line separates two paragraphs
#
def test_an_empty_comment_marker_line_separates_two_paragraphs() -> None:
    doc = parse_question(
        STEM + "* [x] Amazonas\n  ! Primeira\n  linha.\n  !\n  ! Segunda.\n* [ ] Nilo\n"
    )
    assert doc["choices"][0]["comment"] == "Primeira linha.\n\nSegunda."


def test_an_empty_marker_line_in_an_ordering_section() -> None:
    doc = parse_question(
        "Ordene os rios.\n\n[ordering]\n\n* Amazonas\n* Negro\n\n"
        "## [reject]\n\n> Ao contrário.\n>\n> Releia.\n\n* Negro\n* Amazonas\n"
    )
    assert doc["reject"][0]["feedback"] == "Ao contrário.\n\nReleia."


def test_an_empty_marker_line_in_a_pattern_item() -> None:
    doc = parse_question(
        "Qual é o maior rio do Brasil?\n\n[short-answer]:\n"
        "* Amazonas\n  > Certo.\n  >\n  > Em volume.\n"
    )
    assert doc["accept"] == [
        {"pattern": "Amazonas", "feedback": "Certo.\n\nEm volume."}
    ]


#
# B4: indentation relative to the item content
#
def test_a_feedback_line_indented_four_columns_continues_the_text() -> None:
    doc = parse_question(STEM + "* [x] Amazonas\n      > Negro\n* [ ] Nilo\n")
    assert doc["choices"][0] == {"text": "Amazonas > Negro", "correct": True}


def test_a_comment_line_indented_four_columns_continues_the_feedback() -> None:
    doc = parse_question(
        STEM + "* [x] Amazonas\n  > Maior.\n      ! Nota.\n* [ ] Nilo\n"
    )
    assert doc["choices"][0]["feedback"] == "Maior. ! Nota."
    assert "comment" not in doc["choices"][0]


def test_a_feedback_line_indented_three_columns_is_feedback() -> None:
    doc = parse_question(STEM + "* [x] Amazonas\n     > Maior.\n* [ ] Nilo\n")
    assert doc["choices"][0]["feedback"] == "Maior."


def test_indentation_is_relative_to_a_wide_item_content() -> None:
    doc = parse_question(STEM + "*    [x] Amazonas\n     > Maior.\n*    [ ] Nilo\n")
    assert doc["choices"][0]["feedback"] == "Maior."


def test_a_tab_after_the_list_marker() -> None:
    doc = parse_question(STEM + "*\t[x] Amazonas\n*\t[ ] Nilo\n")
    assert [c["text"] for c in doc["choices"]] == ["Amazonas", "Nilo"]


def test_an_image_line_continues_the_feedback() -> None:
    doc = parse_question(
        STEM + "* [x] Amazonas\n  > Veja:\n  ![mapa](a.png)\n* [ ] Nilo\n"
    )
    assert doc["choices"][0]["feedback"] == "Veja: ![mapa](a.png)"


@pytest.mark.parametrize(
    "first",
    [
        "*      [x] Amazonas",
        "* [x](https://ana.gov.br) Amazonas",
        "* [x][ana] Amazonas",
    ],
)
def test_an_item_that_is_not_a_choice_makes_the_list_prose(first: str) -> None:
    source = STEM + f"{first}\n* [ ] Nilo\n* [x] Negro\n\n[ana]: https://ana.gov.br\n"
    with pytest.raises(MissingField):
        parse_question(source)


#
# B1: links and stray choice markers
#
def test_a_paragraph_that_starts_with_a_link_is_valid_in_the_epilogue() -> None:
    loaded = mdq.load(
        STEM
        + "* [x] Amazonas\n* [ ] Nilo\n\n[ANA](https://ana.gov.br) tem os dados.\n",
        kind="question",
    )
    assert loaded.document is not None
    assert _codes(loaded) == []


@pytest.mark.parametrize("field", ["preamble", "stem", "epilogue"])
def test_stray_choice_marker_on_a_yaml_document(field: str) -> None:
    data = {
        "type": "multiple-selection",
        "id": "rios",
        "title": "Rios",
        "stem": "Quais destes rios correm no Brasil?",
        "choices": [
            {"id": "amazonas", "text": "Amazonas", "correct": True},
            {"id": "nilo", "text": "Nilo", "correct": False},
        ],
    }
    data[field] = (
        "Leia:\n\n* [] Negro\n* [ANA](https://ana.gov.br)\n* [?] Tapajós\n* [a] Xingu"
    )
    loaded = mdq.load(data, kind="question")
    assert loaded.document is not None
    # `[?]` is not the value of a choice type, so only `[]` and `[a]` count.
    assert _codes(loaded) == [("stray-choice-marker", (field,))] * 2


def test_a_list_without_choice_markers_is_not_stray() -> None:
    loaded = mdq.load(
        STEM
        + "* [x] Amazonas\n* [ ] Nilo\n\nLeia:\n\n* Negro\n* [ANA](https://ana.gov.br)\n",
        kind="question",
    )
    assert _codes(loaded) == []

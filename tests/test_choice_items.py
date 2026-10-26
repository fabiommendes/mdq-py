"""
The item of a choice list and the feedback and comment blocks shared by
every element that carries them (docs/references/choices.md;
docs/references/grammar.md, "Content of a list item" and "Feedback and
comment lines").

The corpus covers the item rules; these cases keep the few that it cannot
express yet.
"""

from __future__ import annotations

import pytest

from mdq._parser import parse_question
from mdq.errors import MissingField, ParseError

STEM = "Quais destes rios correm no Brasil?\n\n"


def test_a_second_feedback_block_in_a_fill_in_choice_blank_is_a_parse_error() -> None:
    source = (
        "O maior rio é o [^rio].\n\n[^rio]:\n"
        "* [*] Amazonas\n  > Maior.\n\n  > Longo.\n* [ ] Nilo\n"
    )
    with pytest.raises(ParseError):
        parse_question(source)


def test_a_tab_after_the_list_marker() -> None:
    doc = parse_question(STEM + "*\t[x] Amazonas\n*\t[ ] Nilo\n")
    assert [c["text"] for c in doc["choices"]] == ["Amazonas", "Nilo"]


def test_an_item_indented_past_the_content_column_makes_the_list_prose() -> None:
    source = STEM + "*      [x] Amazonas\n* [ ] Nilo\n* [x] Negro\n"
    with pytest.raises(MissingField):
        parse_question(source)

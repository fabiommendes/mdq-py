"""
Blank references and definition errors of a fill-in question
(docs/question-types/fill-in.md "Blank definitions", "Choice blanks" and
"Additional Rules"; docs/references/grammar.md "Content of a list item").
"""

from __future__ import annotations

import pytest

from mdq import errors
from mdq._parser import parse_question


def test_text_on_a_choice_tag_line_suggests_the_short_answer_suffix() -> None:
    with pytest.raises(errors.ParseError, match=r"\[\^capital/short-answer\]"):
        parse_question("A capital é [^capital].\n\n[^capital]: Brasília\n")


def test_a_change_of_bullet_character_asks_for_the_same_marker() -> None:
    source = "A capital é [^capital].\n\n[^capital/short-answer]:\n* Brasília\n- Brasilia\n"
    with pytest.raises(errors.ParseError, match="same list marker"):
        parse_question(source)

"""
`mdq.convert._base.literal_pattern` joins the lines of an imported answer
with one space, as the continuation lines of a body block do
(docs/references/patterns.md, "Continuation lines").
"""

from __future__ import annotations

import pytest

from mdq.convert._base import literal_pattern


@pytest.mark.parametrize(
    ("text", "pattern"),
    [
        ("Rio de\nJaneiro", "Rio de Janeiro"),
        ("Rio de\r\nJaneiro", "Rio de Janeiro"),
        ("Rio de\r  \tJaneiro", "Rio de Janeiro"),
        ("\n  Rio de\nJaneiro  \n", "Rio de Janeiro"),
        ("São\nPaulo\nSP", "São Paulo SP"),
        ("Brasília", "Brasília"),
    ],
)
def test_a_line_ending_becomes_one_space(text: str, pattern: str) -> None:
    assert literal_pattern(text, format="GIFT").pattern == pattern


def test_the_lines_of_an_exact_literal_are_joined_inside_the_backticks() -> None:
    entry = literal_pattern("/usr/\nbin", format="Moodle XML")
    assert entry.pattern == "`/usr/ bin`"


def test_a_single_line_answer_is_kept_as_it_is() -> None:
    assert literal_pattern(" Brasília ", format="GIFT").pattern == " Brasília "

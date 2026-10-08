"""
base.md, "Slug" and the `choice_id` rule of multiple-choice.md: a bracket
followed by `(` or `[` opens a markdown link and is never a slug or a
choice id.
"""

from __future__ import annotations

import pytest

import mdq
from mdq._parser import parse_question

WIKI = "https://pt.wikipedia.org/wiki/"


def _choices(md: str) -> list[tuple[str | None, str]]:
    return [(c.get("id"), c["text"]) for c in parse_question(md)["choices"]]


def test_inline_link_at_the_start_of_a_choice_is_text() -> None:
    md = f"Qual?\n\n* [*] [Brasilia]({WIKI}Brasília)\n* [ ] Rio\n"
    assert _choices(md) == [(None, f"[Brasilia]({WIKI}Brasília)"), (None, "Rio")]


def test_reference_link_at_the_start_of_a_choice_is_text() -> None:
    md = "Qual?\n\n* [*] [Salvador][ref]\n* [ ] Rio\n\n[ref]: https://x.org\n"
    assert _choices(md)[0] == (None, "[Salvador][ref]")


@pytest.mark.parametrize("sep", [" ", "\t", ""])
def test_slug_bracket_not_followed_by_a_link_opener_is_an_id(sep: str) -> None:
    md = f"Qual?\n\n* [*] [bsb]{sep}Brasília\n* [ ] [rio] Rio\n"
    assert _choices(md) == [("bsb", "Brasília"), ("rio", "Rio")]


def test_choice_id_then_a_link_keeps_both() -> None:
    md = f"Qual?\n\n* [*] [bsb] [Brasília]({WIKI}Brasília)\n* [ ] Rio\n"
    assert _choices(md)[0] == ("bsb", f"[Brasília]({WIKI}Brasília)")


def test_link_at_the_start_of_the_stem_is_not_a_question_slug() -> None:
    doc = parse_question(f"[Amazonia]({WIKI}Amazônia) fica onde?\n\n[essay]\n")
    assert "id" not in doc
    assert doc["stem"] == f"[Amazonia]({WIKI}Amazônia) fica onde?"


def test_slug_at_the_start_of_the_stem_still_works() -> None:
    doc = parse_question("[Q1] Onde fica a Amazônia?\n\n[essay]\n")
    assert doc["id"] == "Q1"
    assert doc["stem"] == "Onde fica a Amazônia?"


def test_link_in_an_exam_title_is_not_a_slug() -> None:
    text = f"# [Prova]({WIKI}Prova) final\n\n===\n\nQual?\n\n* [*] A\n* [ ] B\n"
    exam = mdq.load(text, kind="exam").document
    assert exam.id is None
    assert exam.title == f"[Prova]({WIKI}Prova) final"


def test_render_of_a_link_choice_is_a_fixed_point() -> None:
    md = f"Qual?\n\n* [*] [Brasilia]({WIKI}Brasília)\n* [ ] [rio] Rio\n"
    question = mdq.load(md, kind="question").document
    again = mdq.load(str(question), kind="question")
    assert [d for d in again.diagnostics if d.severity == "error"] == []
    assert again.document == question

"""
base.md, "Bracketed tags": a tag followed by `:` may have spaces around the
colon. Every tag that takes a colon accepts them.
"""

from __future__ import annotations

import pytest

from mdq._parser import parse_question


@pytest.mark.parametrize("colon", [":", " :", "\t:", " : ", ":  "])
def test_numeric_tag_accepts_spaces_around_the_colon(colon: str) -> None:
    doc = parse_question(f"Quanto?\n\n[numeric(km)]{colon}6400 +- 5%\n")
    assert doc["answer"] == 6400 and doc["unit"] == "km"


@pytest.mark.parametrize("colon", [":", " :", " : "])
def test_blank_tags_accept_spaces_around_the_colon(colon: str) -> None:
    doc = parse_question(
        f"[^n] and [^w].\n\n[^n/numeric]{colon}42\n\n[^w/short-answer]{colon}Amazon\n"
    )
    assert doc["blanks"][0]["answer"] == 42
    assert doc["blanks"][1]["accept"] == ["Amazon"]


@pytest.mark.parametrize("colon", [":", " :", " : "])
def test_short_answer_tag_accepts_spaces_around_the_colon(colon: str) -> None:
    doc = parse_question(f"Qual?\n\n[short-answer]{colon}Amazon\n")
    assert doc["accept"] == ["Amazon"]

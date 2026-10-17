"""Normalized value of a choice marker (choices.md, "Choice marker")."""

import pytest

import mdq
from mdq._letters import is_letter, normalize_value


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Ｆ", "f"), ("Ｘ", "x"), ("＊", "*"), ("T", "t"), ("Å", "Å"), ("ſ", "s")],
)
def test_normalize_value(value: str, expected: str) -> None:
    assert normalize_value(value) == expected


@pytest.mark.parametrize("text", ["ˇ", "ー", "✓", "7", "", "ab", "É"])
def test_not_a_letter(text: str) -> None:
    assert not is_letter(text)


@pytest.mark.parametrize("text", ["T", "对", "क़", "𐐀"])
def test_letter(text: str) -> None:
    assert is_letter(text)


def test_fullwidth_f_is_false_and_keeps_its_marker() -> None:
    question = mdq.parse("Julgue.\n\n* [Ｆ] O Sol é um planeta.\n* [T] O Sol é uma estrela.\n")
    assert question.type == "true-false"
    assert question.choices[0].correct is False
    assert question.choices[0].marker == "Ｆ"


def test_fullwidth_x_is_multiple_selection() -> None:
    question = mdq.parse("Quais são rios?\n\n* [Ｘ] Madeira\n* [ ] Serra\n")
    assert question.type == "multiple-selection"
    assert question.choices[0].correct is True


def test_modifier_letter_marker_is_foreign() -> None:
    with pytest.raises(mdq.InvalidDocument) as info:
        mdq.parse("---\ntype: true-false\n---\n\nJulgue.\n\n* [ˇ] A\n* [T] B\n")
    assert [d.code for d in info.value.diagnostics] == ["foreign-choice-marker"]

"""Letter test of a choice marker (choices.md, "Choice marker"). The normalized
values are in the example corpus (`fullwidth-*`, `long-s-marker`, ...)."""

import pytest

from mdq._letters import is_letter


@pytest.mark.parametrize("text", ["ˇ", "ー", "✓", "7", "", "ab", "É"])
def test_not_a_letter(text: str) -> None:
    assert not is_letter(text)


@pytest.mark.parametrize("text", ["T", "对", "क़", "𐐀"])
def test_letter(text: str) -> None:
    assert is_letter(text)

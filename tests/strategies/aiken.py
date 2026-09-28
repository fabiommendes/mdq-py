"""
Hypothesis strategies for `mdq.convert._aiken` values, in "Brazil core"
flavored text.
"""

from __future__ import annotations

from typing import Literal

from hypothesis import strategies as st

from mdq.convert._aiken import CHOICE_REGEX, AikenQuestion

__all__ = ["aiken_line_text", "aiken_stems", "aiken_questions"]


#: `characters()` needs the literal type it declares -- a bare
#: `tuple[str, ...]` loses it and fails mypy at every use site.
type CharCategory = Literal["Cc", "Cs"]
EXCLUDED_CATEGORIES: tuple[CharCategory, ...] = ("Cc", "Cs")


def aiken_questions(max_choices: int = 4) -> st.SearchStrategy[AikenQuestion]:
    """Aiken questions whose rendered source parses back to an equal value."""
    return st.lists(aiken_line_text(), min_size=1, max_size=max_choices).flatmap(
        lambda choices: st.builds(
            AikenQuestion,
            stem=aiken_stems(),
            choices=st.just(choices),
            answer=st.integers(min_value=0, max_value=len(choices) - 1),
        )
    )


def aiken_stems(max_lines: int = 3) -> st.SearchStrategy[str]:
    """
    A stem is every line before the first choice, so no line of it may look
    like a choice marker or the parser would read it as one.
    """
    return (
        st.lists(aiken_line_text(), min_size=1, max_size=max_lines)
        .map("\n".join)
        .filter(
            lambda s: not any(CHOICE_REGEX.fullmatch(line) for line in s.splitlines())
        )
    )


def aiken_line_text(max_size: int = 40) -> st.SearchStrategy[str]:
    """
    Single-line text, stripped at both ends: Aiken holds one choice per line
    and `AikenQuestion` strips what it stores.
    """
    alphabet = st.characters(
        blacklist_categories=EXCLUDED_CATEGORIES, blacklist_characters="\r"
    )
    return st.text(alphabet=alphabet, min_size=1, max_size=max_size).filter(
        lambda s: s == s.strip() and s != ""
    )

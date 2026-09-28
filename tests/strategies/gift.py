"""
Hypothesis strategies for `mdq.convert._gift` values, in "Brazil core"
flavored text.
"""

from __future__ import annotations

from typing import Literal

from hypothesis import strategies as st

from mdq.convert._gift import GiftBlock, GiftNumericOption, GiftOption

__all__ = [
    "GIFT_SPECIAL_CHARS",
    "gift_text",
    "gift_line_text",
    "gift_options",
    "gift_choice_options",
    "gift_numeric_options",
    "gift_blocks",
    "force_non_full_credit",
]


#: `characters()` needs the literal type it declares -- a bare
#: `tuple[str, ...]` loses it and fails mypy at every use site.
type CharCategory = Literal["Cc", "Cs"]
EXCLUDED_CATEGORIES: tuple[CharCategory, ...] = ("Cc", "Cs")


#: Characters GIFT treats as syntactically meaningful and that must
#: round-trip through `escape_gift`/`unescape_gift`.
GIFT_SPECIAL_CHARS = ":=~{}#\\"


def gift_text(max_size: int = 30) -> st.SearchStrategy[str]:
    """
    Unicode text safe to embed in a GIFT field: no blank (`\\n\\n`) lines
    -- those would be read as a block separator -- and stripped at both
    ends, matching how GIFT trims stems/options. Includes every
    escapable character, `%`, single newlines and non-ASCII text.
    """
    alphabet = st.characters(
        blacklist_categories=EXCLUDED_CATEGORIES, blacklist_characters="\r"
    )
    return st.text(alphabet=alphabet, min_size=1, max_size=max_size).filter(
        lambda s: "\n\n" not in s and s == s.strip() and s != ""
    )


def gift_line_text(max_size: int = 20) -> st.SearchStrategy[str]:
    """Single-line text, for fields (title, comment) that can't hold a newline."""
    alphabet = st.characters(
        blacklist_categories=EXCLUDED_CATEGORIES, blacklist_characters="\r\n"
    )
    return st.text(alphabet=alphabet, min_size=1, max_size=max_size).filter(
        lambda s: s == s.strip() and s != ""
    )


def gift_options(
    min_size: int = 1, max_size: int = 4
) -> st.SearchStrategy[list[GiftOption]]:
    return st.lists(
        st.builds(
            GiftOption,
            text=gift_text(),
            credit=st.sampled_from([0.0, 1.0, 0.5, -0.5, 0.25]),
            feedback=st.none() | gift_text(),
        ),
        min_size=min_size,
        max_size=max_size,
    )


def force_non_full_credit(
    options: list[GiftOption], index: int, credit: float
) -> list[GiftOption]:
    """Overwrite one option's credit so it is guaranteed != 1.0."""
    i = index % len(options)
    forced = options[i]
    options = list(options)
    options[i] = GiftOption(text=forced.text, credit=credit, feedback=forced.feedback)
    return options


def gift_choice_options(
    min_size: int = 2, max_size: int = 4
) -> st.SearchStrategy[list[GiftOption]]:
    """
    Like `gift_options`, but guaranteed to have at least one option with
    credit != 1.0 (a `~` entry). A body where every option has credit
    1.0 renders with no `~` entry at all, so it reparses as `GiftShort`
    rather than `GiftChoice` -- in GIFT a body of bare `=` entries is
    genuinely a short-answer question.
    """
    return st.builds(
        force_non_full_credit,
        gift_options(min_size=min_size, max_size=max_size),
        st.integers(min_value=0, max_value=10),
        st.sampled_from([0.0, 0.5, -0.5, 0.25]),
    )


def gift_numeric_options(
    min_size: int = 1, max_size: int = 3
) -> st.SearchStrategy[list[GiftNumericOption]]:
    return st.lists(
        st.builds(
            GiftNumericOption,
            value=st.floats(
                min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False
            ).map(lambda x: round(x, 2)),
            tolerance=st.floats(
                min_value=0, max_value=100, allow_nan=False, allow_infinity=False
            ).map(lambda x: round(x, 2)),
            credit=st.sampled_from([1.0, 0.0, 0.5, -0.5]),
            feedback=st.none() | gift_text(),
        ),
        min_size=min_size,
        max_size=max_size,
    )


def gift_blocks(
    answer: st.SearchStrategy,
    *,
    tail: st.SearchStrategy[str] | None = None,
) -> st.SearchStrategy[GiftBlock]:
    return st.builds(
        GiftBlock,
        stem=gift_text(),
        answer=answer,
        tail=tail if tail is not None else st.just(""),
        title=st.none() | gift_line_text(),
        comment=st.none() | gift_line_text(),
        text_format=st.sampled_from(["moodle", "html", "plain", "markdown"]),
        general_feedback=st.none() | gift_text(),
    )

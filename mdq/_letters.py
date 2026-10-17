"""
Letters and the normalized value of a choice marker.

The spec defines both (docs/references/choices.md, "Choice marker", and
docs/question-types/true-false.md, "Body"). They use the Unicode tables of
`unicodedata2`, not those of the Python in use, so the result does not
depend on the interpreter version.
"""

from __future__ import annotations

from typing import NamedTuple

import unicodedata2  # type: ignore[import-not-found]  # ships no stubs

__all__ = [
    "FALSE_LETTERS",
    "LOCALE_ROWS",
    "TRUE_LETTERS",
    "LocaleRow",
    "is_letter",
    "nfkc",
    "normalize_value",
]

#: General_Category values of a `LETTER` (grammar.md, "Regex dialect"):
#: Lu, Ll, Lt and Lo. Lm (modifier letters) is not a letter.
_LETTER_CATEGORIES = frozenset({"Lu", "Ll", "Lt", "Lo"})

_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def is_letter(text: str) -> bool:
    """Whether `text` is exactly one code point whose category is in `LETTER`."""
    return len(text) == 1 and unicodedata2.category(text) in _LETTER_CATEGORIES


def nfkc(text: str) -> str:
    """The NFKC form of `text`."""
    return unicodedata2.normalize("NFKC", text)


def normalize_value(value: str) -> str:
    """
    The value of a choice marker as the parser reads it: NFKC, then ASCII
    lowercase (`A` to `Z` only). `Ｆ` (U+FF26) becomes `f`.
    """
    return nfkc(value).translate(_ASCII_LOWER)


def _both_cases(letters: str) -> frozenset[str]:
    """
    The space-separated `letters` in upper and lower case. The normalized
    value only lowercases ASCII, so a cased non-ASCII letter (`Đ`, `В`, `Н`)
    appears in both cases.
    """
    return frozenset(
        form for letter in letters.split() for form in (letter, letter.lower())
    )


#: TRUE and FALSE letters of true-false.md, "Body", matched against the
#: normalized value. Every other letter (but `x`) is a WARNING letter.
TRUE_LETTERS = _both_cases("T V B D Đ 对 對 真 是 В 참 ص स স ब ఒ ச ถ સ")
FALSE_LETTERS = _both_cases("F M 错 錯 偽 非 Н 거 خ غ ग ম च త த ผ ખ")


class LocaleRow(NamedTuple):
    """One row of the locale table of true-false.md, "Locale"."""

    #: Letters accepted for true. May hold WARNING letters.
    true: frozenset[str]
    #: Letters accepted for false.
    false: frozenset[str]
    #: Letters that mean false in the language but true globally.
    false_friends: frozenset[str]


def _row(true: str, false: str, false_friends: str = "") -> LocaleRow:
    return LocaleRow(
        _both_cases(true), _both_cases(false), _both_cases(false_friends)
    )


#: The locale table of true-false.md, keyed by language subtag.
LOCALE_ROWS: dict[str, LocaleRow] = {
    "en": _row("T", "F", "W"),
    "zh": _row("T 对 對 是", "F 错 錯 非", "C"),
    "yue": _row("T 對", "F 錯", "C"),
    "hi": _row("T S स", "F ग", "G"),
    "es": _row("T V", "F"),
    "ar": _row("T S ص", "F خ", "K"),
    "fr": _row("T V", "F"),
    "bn": _row("T S স", "F M ম"),
    "pt": _row("T V C", "F", "E"),
    "id": _row("T B", "F", "S"),
    "ms": _row("T B", "F", "S"),
    "ur": _row("T S ص", "F غ", "G J"),
    "ru": _row("T V В", "F Н", "N"),
    "de": _row("T W R", "F"),
    "ja": _row("T 真 O", "F 偽"),
    "mr": _row("T B ब", "F च", "C"),
    "vi": _row("T D Đ", "F", "S"),
    "te": _row("T ఒ", "F త"),
    "sw": _row("T K", "F", "S H"),
    "tr": _row("T D", "F", "Y"),
    "tl": _row("T", "F M"),
    "ta": _row("T S ச", "F த"),
    "fa": _row("T S D ص", "F غ", "G N"),
    "ko": _row("T 참 O", "F 거"),
    "th": _row("T ถ", "F ผ", "P"),
    "gu": _row("T સ", "F ખ"),
    "it": _row("T V", "F"),
}

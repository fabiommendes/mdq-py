"""
Regexes in MDQ documents use a subset of JavaScript regex syntax, with some
differences in the flags.

This module normalizes regexes to a canonical form, and provides Python
abstractions to use regexes from MDQ documents.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "RegexPattern",
    "InvalidRegexError",
    "parse_regex",
    "normalize_regex",
    "normalize_text",
]


class InvalidRegexError(ValueError):
    """An MDQ regex pattern is malformed or uses unsupported syntax."""


class RegexPattern:
    """
    A compiled regex pattern from an MDQ document.
    """

    #: The original pattern string, exactly as passed in.
    pattern: str
    #: The regex body, with delimiters and flags stripped.
    regex: str
    #: Effective flags: meaningful flags only, ignored ones dropped.
    flags: frozenset[str]

    def __init__(self, pattern: str, *, flags: str = "") -> None:
        self.pattern = pattern
        body, raw_flags = parse_regex(pattern)
        validate_flag_chars(flags)
        effective = effective_flags(raw_flags) | effective_flags(flags)
        validate_regex_body(body)

        # The 'n' flag normalizes the body's literal text, not its escape
        # sequences: normalize_text only sees the characters written in the
        # source, so a literal "á" is normalized but "á" is not.
        compile_body = normalize_text(body) if "n" in effective else body
        py_flags = re.IGNORECASE if "i" in effective else 0
        try:
            compiled = re.compile(compile_body, py_flags)
        except re.error as exc:
            raise InvalidRegexError(f"invalid regex body: {body!r}") from exc

        self._compiled: re.Pattern[str] = compiled
        self.regex = body
        self.flags = effective

    def match(self, string: str) -> bool:
        """Match `string` using the strategy selected by the `f`/`b` flags."""
        if "f" in self.flags:
            return self.include_match(string)
        if "b" in self.flags:
            return self.start_match(string)
        return self.full_match(string)

    def start_match(self, string: str) -> bool:
        """True if the regex matches a prefix of `string`."""
        return self._compiled.match(self._subject(string)) is not None

    def include_match(self, string: str) -> bool:
        """True if the regex matches anywhere in `string`."""
        return self._compiled.search(self._subject(string)) is not None

    def full_match(self, string: str) -> bool:
        """True if the regex matches the entirety of `string`."""
        return self._compiled.fullmatch(self._subject(string)) is not None

    def _subject(self, string: str) -> str:
        """Apply the `n` flag's normalization to a match subject, if set."""
        return normalize_text(string) if "n" in self.flags else string

    def __repr__(self) -> str:
        flag_str = "".join(f for f in FLAG_ORDER if f in self.flags)
        return f"RegexPattern({self.pattern!r}, flags={flag_str!r})"


def parse_regex(pattern: str) -> tuple[str, str]:
    """
    Split a pattern into its regex body and raw flag string.

    Raises:
        InvalidRegexError: the delimiters or flag characters are malformed.
    """
    text = pattern.strip()
    if text.startswith("/"):
        closing = text.rfind("/")
        if closing == 0:
            raise InvalidRegexError(f"unterminated regex literal: {pattern!r}")
        body, raw_flags = text[1:closing], text[closing + 1 :]
    else:
        body, raw_flags = text, ""
    validate_flag_chars(raw_flags)
    return body, raw_flags


def normalize_regex(pattern: str) -> str:
    """
    Return the canonical "/body/flags" form of `pattern`.

    Raises:
        InvalidRegexError: the pattern is malformed or uses unsupported syntax.
    """
    body, raw_flags = parse_regex(pattern)
    validate_regex_body(body)
    try:
        re.compile(body)
    except re.error as exc:
        raise InvalidRegexError(f"invalid regex body: {body!r}") from exc

    effective = effective_flags(raw_flags)
    flag_str = "".join(f for f in FLAG_ORDER if f in effective)
    return f"/{body}/{flag_str}"


def normalize_text(string: str) -> str:
    """
    NFD-decompose `string`, drop combining marks, and recompose with NFC.
    """
    decomposed = unicodedata.normalize("NFD", string)
    without_marks = "".join(
        ch for ch in decomposed if unicodedata.category(ch) != "Mn"
    )
    return unicodedata.normalize("NFC", without_marks)


#
# Flag validation
#
MEANINGFUL_FLAGS = frozenset({"i", "n", "f", "b"})
IGNORED_FLAGS = frozenset({"m", "g", "u", "y", "x"})
VALID_FLAGS = MEANINGFUL_FLAGS | IGNORED_FLAGS
FLAG_ORDER = "bfin"


def validate_flag_chars(flags: str) -> None:
    """Reject unknown or repeated flag characters."""
    seen: set[str] = set()
    for ch in flags:
        if ch not in VALID_FLAGS:
            raise InvalidRegexError(f"unknown regex flag: {ch!r}")
        if ch in seen:
            raise InvalidRegexError(f"repeated regex flag: {ch!r}")
        seen.add(ch)


def effective_flags(flags: str) -> frozenset[str]:
    """Reduce a flag string to its meaningful (non-ignored) characters."""
    return frozenset(ch for ch in flags if ch in MEANINGFUL_FLAGS)


#
# Body syntax validation
#
# A hand-written scanner, not a pile of independent regex searches: rejecting
# these constructs correctly requires tracking escape state (so an escaped
# "\\p" is not mistaken for a "\p{...}" property escape) and character-class
# context (so "&&" is only an intersection operator inside an unescaped
# "[...]" class).
#
ALLOWED_GROUP_OPENERS = frozenset({":", "=", "!"})
REJECTED_ESCAPE_LETTERS = frozenset({"p", "P", "k", "c"})


def validate_regex_body(body: str) -> None:
    """
    Reject MDQ-unsupported constructs: class intersections, named/lookbehind
    groups, inline flags, comment groups, and property/backreference escapes.
    """
    length = len(body)
    index = 0
    in_class = False
    literal_bracket = -1

    while index < length:
        char = body[index]

        if char == "\\":
            if index + 1 < length:
                check_escape(body, index)
                index += 2
            else:
                index += 1
            continue

        if in_class:
            if char == "]" and index != literal_bracket:
                in_class = False
            elif char == "&" and index + 1 < length and body[index + 1] == "&":
                raise InvalidRegexError(
                    f"character class intersection is not supported: {body!r}"
                )
            index += 1
            continue

        if char == "[":
            in_class = True
            # A ']' right after '[' or '[^' is a literal, not the closer.
            literal_bracket = index + 1
            if literal_bracket < length and body[literal_bracket] == "^":
                literal_bracket += 1
            index += 1
            continue

        if char == "(" and index + 1 < length and body[index + 1] == "?":
            opener = body[index + 2] if index + 2 < length else ""
            if opener not in ALLOWED_GROUP_OPENERS:
                raise InvalidRegexError(
                    f"unsupported group construct at position {index}: {body!r}"
                )
            index += 3
            continue

        index += 1


def check_escape(body: str, index: int) -> None:
    """Reject unsupported escapes at `body[index:index + 2]` ('\\' + letter)."""
    letter = body[index + 1]
    if letter.isdigit():
        raise InvalidRegexError(
            f"octal and backreference escapes are not supported: {body!r}"
        )
    if letter in REJECTED_ESCAPE_LETTERS:
        raise InvalidRegexError(f"unsupported escape '\\{letter}': {body!r}")
    if letter == "u" and index + 2 < len(body) and body[index + 2] == "{":
        raise InvalidRegexError(f"\\u{{...}} escapes are not supported: {body!r}")

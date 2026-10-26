"""
Regexes in MDQ documents use a closed subset of JavaScript regex syntax, with
some differences in the flags. They run in code point mode (JavaScript with the
`u` flag), and `.` and the shorthand classes are fixed explicit classes, see
docs/references/patterns.md.

This module normalizes regexes to a canonical form, and provides Python
abstractions to use regexes from MDQ documents.
"""

from __future__ import annotations

import json
import re
import unicodedata
from importlib import resources

from .._markdown import UNICODE_SPACE

__all__ = [
    "RegexPattern",
    "InvalidRegexError",
    "parse_regex",
    "normalize_regex",
    "normalize_text",
    "escaped_code_points",
]


#: `UNICODE_SPACE` at the start or at the end of a string.
_SPACE_ENDS_RE = re.compile(rf"^[{UNICODE_SPACE}]+|[{UNICODE_SPACE}]+$")


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
        compiled = compile_regex(compile_body, py_flags, body)

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
        """
        Prepare a response for matching (patterns.md, "Regex"): NFC, then
        remove the `UNICODE_SPACE` code points from both ends, then apply
        the `n` flag's normalization, if set.
        """
        subject = _SPACE_ENDS_RE.sub("", unicodedata.normalize("NFC", string))
        return normalize_text(subject) if "n" in self.flags else subject

    def __repr__(self) -> str:
        flag_str = "".join(f for f in FLAG_ORDER if f in self.flags)
        return f"RegexPattern({self.pattern!r}, flags={flag_str!r})"


def parse_regex(pattern: str) -> tuple[str, str]:
    """
    Split a pattern into its regex body and raw flag string.

    Spaces and tabs are removed from both ends first. The last `/` closes the
    regex, so an unescaped `/` in the body is valid.

    Raises:
        InvalidRegexError: the delimiters or flag characters are malformed.
    """
    text = pattern.strip(" \t")
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
    compile_regex(body, 0, body)

    effective = effective_flags(raw_flags)
    flag_str = "".join(f for f in FLAG_ORDER if f in effective)
    return f"/{body}/{flag_str}"


def _load_nonspacing() -> dict[int, None]:
    """The `nonspacing` table of `inexact-tables.json`, as a translate table."""
    raw = json.loads(
        resources.files("mdq").joinpath("inexact-tables.json").read_text("utf-8")
    )
    return {cp: None for first, last in raw["nonspacing"] for cp in range(first, last + 1)}


#: The code points of the general category `Mn` in the pinned Unicode
#: version, not the one of the runtime (patterns.md, "Inexact literals").
_NONSPACING_TABLE = _load_nonspacing()


def normalize_text(string: str) -> str:
    """
    NFD-decompose `string`, remove the code points of the `nonspacing` table
    (the marks of the general category `Mn`), and recompose with NFC.
    """
    decomposed = unicodedata.normalize("NFD", string)
    return unicodedata.normalize("NFC", decomposed.translate(_NONSPACING_TABLE))


_CODE_POINT_ESCAPE_RE = re.compile(
    r"\\(?:u([0-9A-Fa-f]{4})|x([0-9A-Fa-f]{2})|u\{([0-9A-Fa-f]{1,6})\})"
)


def escaped_code_points(body: str) -> list[int]:
    """
    The code points denoted by the `\\uXXXX`, `\\xXX` and `\\u{...}` escapes
    of `body`, in order. A backslash escaped by another one is not an escape.
    """
    found: list[int] = []
    index = 0
    while index < len(body):
        if body[index] != "\\":
            index += 1
            continue
        match = _CODE_POINT_ESCAPE_RE.match(body, index)
        if match is None:
            index += 2
            continue
        found.append(int(next(group for group in match.groups() if group), 16))
        index = match.end()
    return found


#
# Flag validation
#
MEANINGFUL_FLAGS = frozenset({"i", "n", "f", "b"})
IGNORED_FLAGS = frozenset({"m", "g", "s", "u", "v", "y", "d"})
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
# Body syntax: an allow-list
#
# `_Translator` reads the body with the grammar of the table in
# docs/references/patterns.md ("Regex") and writes the equivalent Python
# `re` pattern in the same pass. Whatever the table does not list raises
# `InvalidRegexError`, so Python-only syntax never reaches `re`.
#
# Python and JavaScript disagree on `.`, `\d`, `\w`, `\s` and `\b`, so those
# are written as explicit classes. `re.ASCII` is not an option: it breaks `i`
# on non-ASCII text. Under `i` a shorthand class folds like any other class
# (JavaScript `ui`), so `\w` matches U+017F and U+212A.
#
_WORD = "A-Za-z0-9_"
_SHORTHAND = {
    "d": "[0-9]",
    "D": "[^0-9]",
    "w": f"[{_WORD}]",
    "W": f"[^{_WORD}]",
    "s": f"[{UNICODE_SPACE}]",
    "S": f"[^{UNICODE_SPACE}]",
}
_BOUNDARY = {
    "b": f"(?:(?<![{_WORD}])(?=[{_WORD}])|(?<=[{_WORD}])(?![{_WORD}]))",
    "B": f"(?:(?<![{_WORD}])(?![{_WORD}])|(?<=[{_WORD}])(?=[{_WORD}]))",
}
#: `.` is any code point except the four line terminators of JavaScript.
_DOT = "[^\\n\\r\\u2028\\u2029]"
_SYNTAX_CHARACTERS = frozenset("^$\\.*+?()[]{}|")
#: The escapes of a character that is not a syntax character.
_CONTROL_ESCAPES = {"t": 0x09, "n": 0x0A, "v": 0x0B, "f": 0x0C, "r": 0x0D}
_QUANTIFIER_RE = re.compile(r"\{([0-9]+)(?:(,)([0-9]*))?\}")
_HEX4_RE = re.compile(r"[0-9A-Fa-f]{4}")
_HEX2_RE = re.compile(r"[0-9A-Fa-f]{2}")
_BRACED_ESCAPE_RE = re.compile(r"\\u\{([0-9A-Fa-f]{1,6})\}")


def _code_point(value: int) -> str:
    """A Python escape for one code point, valid in and out of a class."""
    return f"\\U{value:08x}"


class _Translator:
    """Read an MDQ regex body, check it and translate it to Python `re`."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.index = 0

    def translate(self) -> str:
        try:
            text = self._disjunction(top=True)
        except RecursionError:
            raise self._error("groups are nested too deeply") from None
        return text

    def _error(self, reason: str) -> InvalidRegexError:
        return InvalidRegexError(
            f"{reason} at position {self.index}: {self.body!r}"
        )

    def _peek(self, offset: int = 0) -> str:
        position = self.index + offset
        return self.body[position] if position < len(self.body) else ""

    def _disjunction(self, *, top: bool = False) -> str:
        alternatives = [self._alternative()]
        while self._peek() == "|":
            self.index += 1
            alternatives.append(self._alternative())
        if top and self.index < len(self.body):
            raise self._error("unmatched ')'")
        return "|".join(alternatives)

    def _alternative(self) -> str:
        terms: list[str] = []
        while self.index < len(self.body) and self._peek() not in "|)":
            terms.append(self._term())
        return "".join(terms)

    def _term(self) -> str:
        char = self._peek()
        if char == "^" or char == "$":
            self.index += 1
            return char
        if char == "\\" and self._peek(1) in ("b", "B"):
            self.index += 2
            return _BOUNDARY[self.body[self.index - 1]]
        if char == "(" and self._peek(1) == "?" and self._peek(2) in ("=", "!"):
            opener = self.body[self.index : self.index + 3]
            self.index += 3
            return opener + self._close_group()
        return self._atom() + self._quantifier()

    def _atom(self) -> str:
        char = self._peek()
        if char == ".":
            self.index += 1
            return _DOT
        if char == "(":
            return self._group()
        if char == "[":
            return self._class()
        if char == "\\":
            return self._escape()
        if char in "*+?":
            raise self._error("nothing to repeat")
        if char in "{}]":
            raise self._error(f"{char!r} must be escaped here")
        self.index += 1
        return re.escape(char)

    def _group(self) -> str:
        self.index += 1
        if self._peek() == "?":
            if self._peek(1) != ":":
                raise self._error("unsupported group construct")
            self.index += 2
            return "(?:" + self._close_group()
        return "(" + self._close_group()

    def _close_group(self) -> str:
        inner = self._disjunction()
        if self._peek() != ")":
            raise self._error("missing ')'")
        self.index += 1
        return inner + ")"

    def _quantifier(self) -> str:
        char = self._peek()
        if char in ("*", "+", "?"):
            self.index += 1
            text = char
        elif char == "{":
            found = _QUANTIFIER_RE.match(self.body, self.index)
            if found is None:
                raise self._error("'{' must be escaped or start a quantifier")
            low, comma, high = found.groups()
            if comma and high and int(low) > int(high):
                raise self._error("quantifier range is out of order")
            self.index = found.end()
            text = found.group(0)
        else:
            return ""
        if self._peek() == "?":
            self.index += 1
            text += "?"
        return text

    def _escape(self) -> str:
        """An escape outside a class, other than `\\b` and `\\B`."""
        letter = self._peek(1)
        if letter in _SHORTHAND:
            self.index += 2
            return _SHORTHAND[letter]
        return re.escape(chr(self._escaped_code_point(in_class=False)))

    def _escaped_code_point(self, *, in_class: bool) -> int:
        """
        Read the escape at `self.index` that denotes one code point, and
        move past it.
        """
        letter = self._peek(1)
        if letter in _SYNTAX_CHARACTERS or letter == "/" or (in_class and letter == "-"):
            self.index += 2
            return ord(letter)
        if letter in _CONTROL_ESCAPES:
            self.index += 2
            return _CONTROL_ESCAPES[letter]
        if in_class and letter == "b":
            self.index += 2
            return 0x08
        if letter == "x" and _HEX2_RE.fullmatch(self.body, self.index + 2, self.index + 4):
            self.index += 4
            return int(self.body[self.index - 2 : self.index], 16)
        if letter == "u":
            if self._peek(2) == "{":
                found = _BRACED_ESCAPE_RE.match(self.body, self.index)
                if found is None or int(found.group(1), 16) > 0x10FFFF:
                    raise self._error("invalid \\u{...} escape")
                value = int(found.group(1), 16)
                if 0xD800 <= value <= 0xDFFF:
                    raise self._error("surrogate escape is not a code point")
                self.index = found.end()
                return value
            if _HEX4_RE.fullmatch(self.body, self.index + 2, self.index + 6):
                value = int(self.body[self.index + 2 : self.index + 6], 16)
                if 0xD800 <= value <= 0xDFFF:
                    raise self._error(
                        "surrogate escape, write the code point as \\u{...}"
                    )
                self.index += 6
                return value
        raise self._error(f"unsupported escape {self.body[self.index:self.index + 2]!r}")

    def _class(self) -> str:
        """Read the class that opens at `self.index` and translate it."""
        self.index += 1
        negated = self._peek() == "^"
        if negated:
            self.index += 1
        if self._peek() == "]":
            raise self._error("empty character class")
        plain: list[str] = []
        shorthands: list[str] = []
        while self._peek() != "]":
            if self.index >= len(self.body):
                raise self._error("missing ']'")
            low = self._class_atom()
            if self._peek() == "-" and self._peek(1) not in ("]", ""):
                self.index += 1
                high = self._class_atom()
                if isinstance(low, str) or isinstance(high, str):
                    raise self._error("shorthand class in a range")
                if low > high:
                    raise self._error("class range is out of order")
                plain.append(f"{_code_point(low)}-{_code_point(high)}")
            elif isinstance(low, str):
                shorthands.append(_SHORTHAND[low])
            else:
                plain.append(_code_point(low))
        self.index += 1

        plain_text = "".join(plain)
        if not shorthands:
            return f"[{'^' if negated else ''}{plain_text}]"
        options = [f"[{plain_text}]"] if plain_text else []
        union = "|".join(options + shorthands)
        if negated:
            return f"(?:(?!{union})(?s:.))"
        return f"(?:{union})"

    def _class_atom(self) -> int | str:
        """
        Read one atom of a class: a code point, or the letter of a shorthand
        class (`d`, `D`, `w`, `W`, `s` or `S`).
        """
        char = self._peek()
        if char == "\\":
            letter = self._peek(1)
            if letter in _SHORTHAND:
                self.index += 2
                return letter
            return self._escaped_code_point(in_class=True)
        if char == "&" and self._peek(1) == "&":
            raise self._error("character class intersection is not supported")
        if self.index >= len(self.body):
            raise self._error("missing ']'")
        self.index += 1
        return ord(char)


def translate_body(body: str) -> str:
    """
    Check `body` against the allow-list of docs/references/patterns.md and
    translate it to syntax that Python `re` reads with the MDQ semantics.

    Raises:
        InvalidRegexError: `body` uses a construct that the table of the
            spec does not list.
    """
    return _Translator(body).translate()


def validate_regex_body(body: str) -> None:
    """
    Reject every construct that the table of docs/references/patterns.md
    does not list.

    Raises:
        InvalidRegexError: `body` uses an unsupported construct.
    """
    translate_body(body)


def compile_regex(body: str, flags: int, original: str) -> re.Pattern[str]:
    """
    Translate `body` to Python syntax and compile it.

    Raises:
        InvalidRegexError: `body` is outside the allow-list, or Python cannot
            compile it.
    """
    try:
        return re.compile(translate_body(body), flags)
    except re.error as exc:
        raise InvalidRegexError(f"invalid regex body: {original!r}") from exc

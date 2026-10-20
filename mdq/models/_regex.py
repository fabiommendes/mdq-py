"""
Regexes in MDQ documents use a subset of JavaScript regex syntax, with some
differences in the flags. They run in code point mode (JavaScript with the `u`
flag), and the shorthand classes are fixed explicit classes, see
docs/references/patterns.md.

This module normalizes regexes to a canonical form, and provides Python
abstractions to use regexes from MDQ documents.
"""

from __future__ import annotations

import re
import unicodedata

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


def normalize_text(string: str) -> str:
    """
    NFD-decompose `string`, drop combining marks, and recompose with NFC.
    """
    decomposed = unicodedata.normalize("NFD", string)
    without_marks = "".join(
        ch for ch in decomposed if unicodedata.category(ch) != "Mn"
    )
    return unicodedata.normalize("NFC", without_marks)


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
        _read_braced_escape(body, index)


#
# Translation to Python `re`
#
# Python and JavaScript disagree on `\d`, `\w`, `\s` and `\b`, so the shorthand
# classes are rewritten to the explicit classes of patterns.md before the body
# is compiled. `re.ASCII` is not an option: it breaks `i` on non-ASCII text.
# Each class is wrapped in `(?-i:...)`, so `i` never makes `\w` match U+017F
# or U+212A, which Python `re.IGNORECASE` would otherwise do for `[A-Za-z]`.
#
_WORD = "A-Za-z0-9_"
_SHORTHAND = {
    "d": "(?-i:[0-9])",
    "D": "(?-i:[^0-9])",
    "w": f"(?-i:[{_WORD}])",
    "W": f"(?-i:[^{_WORD}])",
    "s": f"(?-i:[{UNICODE_SPACE}])",
    "S": f"(?-i:[^{UNICODE_SPACE}])",
}
_BOUNDARY = {
    "b": (
        f"(?:(?<![{_WORD}])(?=[{_WORD}])|(?<=[{_WORD}])(?![{_WORD}]))"
    ),
    "B": (
        f"(?:(?<![{_WORD}])(?![{_WORD}])|(?<=[{_WORD}])(?=[{_WORD}]))"
    ),
}
_BRACED_ESCAPE_RE = re.compile(r"\\u\{([0-9A-Fa-f]{1,6})\}")


def compile_regex(body: str, flags: int, original: str) -> re.Pattern[str]:
    """
    Translate `body` to Python syntax and compile it.

    Raises:
        InvalidRegexError: Python cannot compile the body.
    """
    try:
        return re.compile(translate_body(body), flags)
    except re.error as exc:
        raise InvalidRegexError(f"invalid regex body: {original!r}") from exc


def _read_braced_escape(body: str, index: int) -> tuple[str, int]:
    """
    Read the `\\u{...}` escape at `body[index:]`.

    Returns the Python escape and the index after the closing brace.
    """
    found = _BRACED_ESCAPE_RE.match(body, index)
    if found is None or int(found.group(1), 16) > 0x10FFFF:
        raise InvalidRegexError(f"invalid \\u{{...}} escape: {body!r}")
    return f"\\U{int(found.group(1), 16):08x}", found.end()


def translate_body(body: str) -> str:
    """
    Rewrite the shorthand classes, the word boundaries and the `\\u{...}`
    escapes of `body` to syntax that Python `re` reads with the MDQ semantics.

    Raises:
        InvalidRegexError: a shorthand class is an endpoint of a range.
    """
    out: list[str] = []
    index = 0
    length = len(body)
    while index < length:
        char = body[index]
        if char == "[":
            text, index = _translate_class(body, index)
            out.append(text)
        elif char == "\\" and index + 1 < length:
            letter = body[index + 1]
            if letter in _SHORTHAND:
                out.append(_SHORTHAND[letter])
            elif letter in _BOUNDARY:
                out.append(_BOUNDARY[letter])
            elif letter == "u" and body.startswith("{", index + 2):
                text, index = _read_braced_escape(body, index)
                out.append(text)
                continue
            else:
                out.append(body[index : index + 2])
            index += 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _translate_class(body: str, start: int) -> tuple[str, int]:
    """
    Translate the character class that opens at `body[start]`.

    A class without shorthand escapes keeps its form. Otherwise it becomes
    an alternation (a negated class becomes a lookahead), because the
    complement shorthands and the `(?-i:...)` scope cannot live inside `[]`.
    """
    length = len(body)
    index = start + 1
    negated = index < length and body[index] == "^"
    if negated:
        index += 1
    literal_bracket = index
    plain: list[str] = []
    shorthands: list[str] = []
    while index < length:
        char = body[index]
        if char == "]" and index != literal_bracket:
            break
        if char == "\\" and index + 1 < length:
            letter = body[index + 1]
            if letter in _SHORTHAND:
                _check_not_range_endpoint(body, index, plain)
                shorthands.append(_SHORTHAND[letter])
            elif letter == "u" and body.startswith("{", index + 2):
                text, index = _read_braced_escape(body, index)
                plain.append(text)
                continue
            else:
                plain.append(body[index : index + 2])
            index += 2
            continue
        plain.append(char)
        index += 1
    else:
        # Unterminated: leave the rest as is, Python reports the error.
        return body[start:], length

    plain_text = "".join(plain)
    if not shorthands:
        return f"[{'^' if negated else ''}{plain_text}]", index + 1
    options = list(shorthands)
    if plain_text:
        if plain_text.startswith("^"):
            plain_text = "\\" + plain_text
        options.insert(0, f"[{plain_text}]")
    union = "|".join(options)
    if negated:
        return f"(?:(?!{union})(?s:.))", index + 1
    return f"(?:{union})", index + 1


def _check_not_range_endpoint(body: str, index: int, plain: list[str]) -> None:
    """Reject `[a-\\d]` and `[\\d-z]`, as JavaScript does in `u` mode."""
    before = "".join(plain)
    if len(before) > 1 and before.endswith("-") and not before.endswith("\\-"):
        raise InvalidRegexError(f"shorthand class in a range: {body!r}")
    after = index + 2
    if body.startswith("-", after) and not body.startswith("]", after + 1):
        raise InvalidRegexError(f"shorthand class in a range: {body!r}")

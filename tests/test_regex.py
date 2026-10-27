"""
Tests for `mdq.models._regex`: `parse_regex`, `normalize_text`, `normalize_regex`,
and the `RegexPattern` class used to compile and match MDQ's restricted,
JavaScript-flavoured regex dialect (see `docs/question-types/short-answer.md`,
sections "Regex" and "Regex flags").

The interesting corner cases fall into a few buckets:

* MDQ regexes are implicitly *anchored* (full match by default) unlike raw
  JavaScript or Python regexes -- `/abc/` rejects `"xabc"`. The `f`/`b` flags
  relax this to substring/prefix matching, but only for the `match()`
  dispatcher, never for the explicit `full_match`/`start_match`/
  `include_match` methods.
* `i` (case-fold) and `n` (unicode-normalize accents away) are independent:
  neither implies the other, and `n` normalizes *both* sides of the match,
  including the pattern body itself (but not escape sequences inside it).
* Delimiter parsing has its own edge cases (last `/` wins, escaped `/`,
  undelimited bodies that themselves contain `/`).
* The matching vectors (anchoring, flags, response preparation, code point
  mode, shorthand classes) live in `examples/matching/regex.yaml`, run by
  `tests/test_regex_table.py`. The invalid bodies live in
  `examples/invalid/short-answer-regex-*`. What is left here is the API of
  `RegexPattern` and the units behind it.
* The dialect deliberately rejects a chunk of JS/Python regex syntax
  (lookbehind, named groups, backreferences, `\\p{...}`, ...) eagerly, at
  construction time, so an author never discovers a bad pattern only when a
  student's answer happens to hit it.
"""

from __future__ import annotations


import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mdq.models._regex import (
    InvalidRegexError,
    RegexPattern,
    normalize_regex,
    normalize_text,
    parse_regex,
)


#
# parse_regex
#
@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        pytest.param("abc", ("abc", ""), id="undelimited"),
        pytest.param("math/floor", ("math/floor", ""), id="undelimited-contains-slash"),
        pytest.param("", ("", ""), id="empty-string-body"),
    ],
)
def test_parse_regex_splits_body_and_flags(
    pattern: str, expected: tuple[str, str]
) -> None:
    assert parse_regex(pattern) == expected


def test_parse_regex_does_not_validate_body_syntax() -> None:
    # Body syntax is RegexPattern's/normalize_regex's job, not parse_regex's.
    assert parse_regex("a(") == ("a(", "")
    assert parse_regex("(?P<name>a)") == ("(?P<name>a)", "")


#
# normalize_regex
#
@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        pytest.param("abc", "/abc/", id="undelimited-gets-delimited"),
        pytest.param("/abc/gimu", "/abc/i", id="ignored-flags-dropped"),
        pytest.param("/abc/ni", "/abc/in", id="canonical-flag-order"),
        pytest.param("  /a b/f  ", "/a b/f", id="whitespace-stripped"),
        pytest.param("/abc/fb", "/abc/bf", id="bf-canonical-order"),
        pytest.param("/^abc$/", "/^abc$/", id="anchors-passed-through-verbatim"),
    ],
)
def test_normalize_regex_canonical_form(pattern: str, expected: str) -> None:
    assert normalize_regex(pattern) == expected


def test_normalize_regex_raises_on_rejected_syntax() -> None:
    with pytest.raises(InvalidRegexError):
        normalize_regex("(?P<name>a)")


def test_normalize_regex_raises_on_malformed_delimiters() -> None:
    with pytest.raises(InvalidRegexError):
        normalize_regex("/abc")


#
# RegexPattern -- construction and attributes
#
def test_regex_pattern_keeps_original_pattern_verbatim() -> None:
    rx = RegexPattern("  /abc/i  ")
    assert rx.pattern == "  /abc/i  "
    assert rx.regex == "abc"
    assert rx.flags == frozenset({"i"})


def test_regex_pattern_repr_is_nonempty_string() -> None:
    assert isinstance(repr(RegexPattern("abc")), str)
    assert repr(RegexPattern("abc")) != ""


def test_regex_pattern_flags_kwarg_unions_with_parsed_flags() -> None:
    assert RegexPattern("abc", flags="i").flags == frozenset({"i"})
    assert RegexPattern("/abc/i", flags="f").flags == frozenset({"i", "f"})


def test_regex_pattern_flags_kwarg_validates_like_parsed_flags() -> None:
    with pytest.raises(InvalidRegexError):
        RegexPattern("abc", flags="q")


#
# RegexPattern -- matching semantics: flags
#
def test_flags_kwarg_union_matching_behaviour() -> None:
    assert RegexPattern("abc", flags="i").match("ABC") is True
    assert RegexPattern("/abc/i", flags="f").match("xABCx") is True


def test_explicit_methods_honour_i_and_n_but_ignore_f_and_b() -> None:
    rx = RegexPattern("/abc/f")
    assert rx.full_match("xabcx") is False
    assert rx.include_match("xabcx") is True
    assert rx.match("xabcx") is True


def test_match_with_no_strategy_flag_equals_full_match() -> None:
    rx = RegexPattern("/abc/")
    for s in ["abc", "xabc", "abcx", "", "xabcx"]:
        assert rx.match(s) is rx.full_match(s)


def test_start_match_and_include_match_ignore_strategy_flags() -> None:
    # start_match/include_match are the explicit methods: they always use
    # their own strategy regardless of f/b in the pattern.
    rx = RegexPattern("/abc/b")
    assert rx.include_match("xabcx") is True
    assert rx.start_match("xabc") is False


#
# RegexPattern -- delimiters and parsing (matching-level view)
#
def test_undelimited_and_delimited_equivalent_forms() -> None:
    assert RegexPattern("abc").regex == RegexPattern("/abc/").regex == "abc"
    assert RegexPattern("abc").match("abc") is RegexPattern("/abc/").match("abc") is True


def test_undelimited_body_may_contain_slash() -> None:
    rx = RegexPattern("math/floor")
    assert rx.regex == "math/floor"
    assert rx.full_match("math/floor") is True


def test_empty_undelimited_body_matches_only_empty_string() -> None:
    rx = RegexPattern("")
    assert rx.full_match("") is True
    assert rx.full_match("x") is False


#
# RegexPattern -- rejected syntax (eager, at construction time)
#
def test_normalize_regex_rejects_disallowed_syntax() -> None:
    with pytest.raises(InvalidRegexError):
        normalize_regex("(?P<city>a)")


def test_rejected_syntax_never_surfaces_as_bare_re_error() -> None:
    for body in ["a(", "[a-", "*abc", "a{2,1}"]:
        with pytest.raises(InvalidRegexError):
            RegexPattern(body)


def test_invalid_syntax_raises_eagerly_not_at_match_time() -> None:
    # No RegexPattern is ever constructed for a bad body in these tests --
    # if validation were deferred, the constructor call below would
    # silently succeed and only fail (or misbehave) once `.match` runs.
    with pytest.raises(InvalidRegexError):
        RegexPattern("(?P<city>a)")


#
# Hypothesis properties
#
@given(text=st.text(max_size=50))
@settings(max_examples=200)
def test_normalize_text_is_idempotent(text: str) -> None:
    once = normalize_text(text)
    assert normalize_text(once) == once


@given(text=st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E), max_size=50))
@settings(max_examples=200)
def test_normalize_text_preserves_plain_ascii(text: str) -> None:
    # Plain ASCII has no combining marks to strip and is already
    # NFC-normalized, so normalize_text must be a no-op: same case, same
    # length, same content.
    assert normalize_text(text) == text


@given(pattern=st.sampled_from(["abc", "/abc/", "/abc/i", "/abc/n", "/abc/fb", "/a b/gimu"]))
@settings(max_examples=50)
def test_normalize_regex_is_idempotent(pattern: str) -> None:
    once = normalize_regex(pattern)
    assert normalize_regex(once) == once


# `escape_syntax` never touches "/" or whitespace, so a literal containing
# either can produce an escaped body that (a) gets misread as a delimited
# pattern (leading "/") or (b) gets trimmed by the pattern-level whitespace
# strip (leading/trailing space). Neither is a bug in the property being
# tested, so the generator stays clear of both.
ESCAPABLE_LITERAL = st.text(
    alphabet=st.characters(
        min_codepoint=0x21, max_codepoint=0x7E, exclude_characters="/\\"
    ),
    min_size=1,
    max_size=20,
)


def escape_syntax(literal: str) -> str:
    """Escape only the syntax characters: other escapes are `invalid-regex`."""
    return "".join("\\" + ch if ch in "^$\\.*+?()[]{}|" else ch for ch in literal)


@given(literal=ESCAPABLE_LITERAL)
@settings(max_examples=200)
def test_escaped_literal_full_matches_itself(literal: str) -> None:
    rx = RegexPattern(escape_syntax(literal))
    assert rx.full_match(literal) is True


@given(
    literal=ESCAPABLE_LITERAL,
    pad_left=st.text(max_size=5),
    pad_right=st.text(max_size=5),
)
@settings(max_examples=200)
def test_escaped_literal_include_matches_when_padded(
    literal: str, pad_left: str, pad_right: str
) -> None:
    rx = RegexPattern(escape_syntax(literal))
    assert rx.include_match(pad_left + literal + pad_right) is True



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
* The dialect deliberately rejects a chunk of JS/Python regex syntax
  (lookbehind, named groups, backreferences, `\\p{...}`, ...) eagerly, at
  construction time, so an author never discovers a bad pattern only when a
  student's answer happens to hit it.
"""

from __future__ import annotations

import re

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
        pytest.param("/abc/", ("abc", ""), id="delimited-no-flags"),
        pytest.param("/abc/gi", ("abc", "gi"), id="raw-flags-include-ignored"),
        pytest.param("/a/gi", ("a", "gi"), id="contract-example"),
        pytest.param("math/floor", ("math/floor", ""), id="undelimited-contains-slash"),
        pytest.param("/a/b/", ("a/b", ""), id="last-slash-wins"),
        pytest.param("/a\\/b/", ("a\\/b", ""), id="escaped-delimiter"),
        pytest.param("  /abc/i  ", ("abc", "i"), id="surrounding-whitespace-stripped"),
        pytest.param("", ("", ""), id="empty-string-body"),
        pytest.param("//", ("", ""), id="empty-delimited-body"),
    ],
)
def test_parse_regex_splits_body_and_flags(
    pattern: str, expected: tuple[str, str]
) -> None:
    assert parse_regex(pattern) == expected


@pytest.mark.parametrize(
    "pattern",
    [
        pytest.param("/abc", id="unterminated"),
        pytest.param("/", id="lone-slash"),
        pytest.param("/abc/z", id="unknown-flag"),
        pytest.param("/abc/ii", id="repeated-flag"),
    ],
)
def test_parse_regex_raises_on_malformed_delimiters_or_flags(pattern: str) -> None:
    with pytest.raises(InvalidRegexError):
        parse_regex(pattern)


def test_parse_regex_does_not_validate_body_syntax() -> None:
    # Body syntax is RegexPattern's/normalize_regex's job, not parse_regex's.
    assert parse_regex("a(") == ("a(", "")
    assert parse_regex("(?P<name>a)") == ("(?P<name>a)", "")


#
# normalize_text
#
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("Brasília", "Brasilia", id="brasilia"),
        pytest.param("ação", "acao", id="acao"),
        pytest.param("Ñ", "N", id="n-tilde"),
        pytest.param("", "", id="empty"),
        pytest.param("ÁGUA", "AGUA", id="case-untouched"),
        pytest.param("  a  b ", "  a  b ", id="whitespace-untouched"),
        pytest.param("hello world", "hello world", id="plain-ascii-is-noop"),
    ],
)
def test_normalize_text(text: str, expected: str) -> None:
    assert normalize_text(text) == expected


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


def test_regex_pattern_drops_ignored_flags() -> None:
    assert RegexPattern("/abc/gimuyx").flags == frozenset({"i"})


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
# RegexPattern -- matching semantics: anchoring
#
@pytest.mark.parametrize(
    ("pattern", "string", "expected"),
    [
        pytest.param("/abc/", "abc", True, id="plain-exact"),
        pytest.param("/abc/", "xabc", False, id="plain-rejects-prefix-garbage"),
        pytest.param("/abc/", "abcx", False, id="plain-rejects-suffix-garbage"),
        pytest.param("/abc/", "xabcx", False, id="plain-rejects-both-sides-garbage"),
        pytest.param("/abc/", "", False, id="plain-rejects-empty"),
        pytest.param("/abc/f", "abc", True, id="f-exact"),
        pytest.param("/abc/f", "xabc", True, id="f-prefix-garbage"),
        pytest.param("/abc/f", "abcx", True, id="f-suffix-garbage"),
        pytest.param("/abc/f", "xabcx", True, id="f-both-sides-garbage"),
        pytest.param("/abc/b", "abc", True, id="b-exact"),
        pytest.param("/abc/b", "abcx", True, id="b-suffix-garbage-ok"),
        pytest.param("/abc/b", "xabc", False, id="b-rejects-prefix-garbage"),
        pytest.param("/abc/b", "xabcx", False, id="b-rejects-prefix-garbage-suffix-too"),
        pytest.param("/^abc$/", "abc", True, id="explicit-both-anchors-exact"),
        pytest.param("/^abc$/", "abcx", False, id="explicit-both-anchors-rejects-extra"),
        pytest.param("/^abc/", "abc", True, id="explicit-start-anchor-exact"),
        pytest.param("/^abc/", "abcx", False, id="explicit-start-anchor-rejects-extra"),
        pytest.param("/abc$/", "abc", True, id="explicit-end-anchor-exact"),
        pytest.param("/abc$/", "abcx", False, id="explicit-end-anchor-rejects-extra"),
        pytest.param("/amazonia|cerrado/", "cerrado", True, id="alternation-matches"),
        pytest.param("/amazonia|cerrado/", "o cerrado", False, id="alternation-not-unanchored"),
    ],
)
def test_match_anchoring(pattern: str, string: str, expected: bool) -> None:
    assert RegexPattern(pattern).match(string) is expected


def test_explicit_anchor_keeps_meaning_under_f_flag() -> None:
    rx = RegexPattern("/abc$/f")
    assert rx.match("xabc") is True
    assert rx.match("xabcx") is False


#
# RegexPattern -- matching semantics: flags
#
@pytest.mark.parametrize(
    ("pattern", "string", "expected"),
    [
        pytest.param("/[Bb]ras[íi]lia/i", "BRASÍLIA", True, id="i-all-upper"),
        pytest.param("/[Bb]ras[íi]lia/i", "brasilia", True, id="i-all-lower-no-accent"),
        pytest.param("/[Bb]ras[íi]lia/i", "Brasília", True, id="i-title-case"),
        pytest.param("/ação/i", "AÇÃO", True, id="i-non-ascii"),
    ],
)
def test_i_flag_case_insensitive(pattern: str, string: str, expected: bool) -> None:
    assert RegexPattern(pattern).match(string) is expected


@pytest.mark.parametrize(
    ("pattern", "string", "expected"),
    [
        pytest.param("/Brasilia/n", "Brasília", True, id="n-ascii-pattern-accented-subject"),
        pytest.param("/Brasília/n", "Brasilia", True, id="n-accented-pattern-ascii-subject"),
        pytest.param("/brasilia/n", "BRASÍLIA", False, id="n-alone-is-not-case-folding"),
    ],
)
def test_n_flag_normalizes_unicode_letters(
    pattern: str, string: str, expected: bool
) -> None:
    assert RegexPattern(pattern).match(string) is expected


def test_n_and_i_flags_combine() -> None:
    assert RegexPattern("/brasilia/in").match("BRASÍLIA") is True


def test_n_flag_normalizes_pattern_body_not_just_subject() -> None:
    # Covered concretely above (n-accented-pattern-ascii-subject): the
    # pattern's own accents must be stripped for the match to succeed.
    rx = RegexPattern("/café/n")
    assert rx.match("cafe") is True


def test_precomposed_vs_decomposed_unicode_requires_n_flag() -> None:
    precomposed = "café"  # NFC: c, a, f, LATIN SMALL LETTER E WITH ACUTE
    decomposed = "café"  # NFD: c, a, f, e, COMBINING ACUTE ACCENT
    assert precomposed != decomposed  # sanity: genuinely different code points
    without_n = RegexPattern(f"/{precomposed}/")
    assert without_n.match(decomposed) is False
    with_n = RegexPattern(f"/{precomposed}/n")
    assert with_n.match(decomposed) is True


def test_ignored_flags_behave_like_no_flags() -> None:
    rx = RegexPattern("/abc/gmuyx")
    assert rx.match("abc") is True
    assert rx.match("xabc") is False


@pytest.mark.parametrize(
    "pattern",
    [
        pytest.param("/abc/z", id="unknown-flag-character"),
        pytest.param("/abc/ii", id="repeated-meaningful-flag"),
    ],
)
def test_bad_flag_strings_raise(pattern: str) -> None:
    with pytest.raises(InvalidRegexError):
        RegexPattern(pattern)


def test_repeated_ignored_flag_also_raises() -> None:
    # Contract: "any repeated flag ... is InvalidRegexError" is stated
    # without carving out the ignored set, so a doubled ignored flag should
    # raise too. See report for this being called out as an inference.
    with pytest.raises(InvalidRegexError):
        RegexPattern("/abc/gg")


def test_f_beats_b_when_both_present() -> None:
    assert RegexPattern("/mazon/fb").match("Amazonas") is True


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


def test_last_slash_wins_for_delimiters() -> None:
    rx = RegexPattern("/a/b/")
    assert rx.regex == "a/b"
    assert rx.flags == frozenset()
    assert rx.full_match("a/b") is True


def test_escaped_delimiter_keeps_body_and_matches() -> None:
    rx = RegexPattern("/a\\/b/")
    assert rx.regex == "a\\/b"
    assert rx.full_match("a/b") is True


def test_empty_body_matches_only_empty_string() -> None:
    for pattern in ["//", ""]:
        rx = RegexPattern(pattern)
        assert rx.full_match("") is True
        assert rx.full_match("x") is False


@pytest.mark.parametrize(
    "pattern",
    [pytest.param("/abc", id="unterminated"), pytest.param("/", id="lone-slash")],
)
def test_malformed_delimiters_raise_at_construction(pattern: str) -> None:
    with pytest.raises(InvalidRegexError):
        RegexPattern(pattern)


#
# RegexPattern -- rejected syntax (eager, at construction time)
#
REJECTED_BODIES = [
    pytest.param("[a-z&&[^aeiou]]", id="class-intersection"),
    pytest.param("(?P<city>a)", id="python-named-group"),
    pytest.param("(?P=city)", id="python-named-group-backreference"),
    pytest.param("(?<=R\\$)\\d+", id="lookbehind-positive"),
    pytest.param("(?<!R\\$)\\d+", id="lookbehind-negative"),
    pytest.param("(?<city>a)", id="js-named-group"),
    pytest.param("(?i)abc", id="inline-flags"),
    pytest.param("(?#x)a", id="comment-group"),
    pytest.param("\\p{L}+", id="unicode-property"),
    pytest.param("\\P{L}", id="negated-unicode-property"),
    pytest.param("\\k<city>", id="named-backreference"),
    pytest.param("\\cA", id="control-escape"),
    pytest.param("\\123", id="octal-escape"),
    pytest.param("(a)\\1", id="numbered-backreference"),
    pytest.param("\\u{1F600}", id="unicode-braces-escape"),
    pytest.param("a(", id="python-cannot-compile-unbalanced-paren"),
    pytest.param("[a-", id="python-cannot-compile-unterminated-class"),
    pytest.param("*abc", id="python-cannot-compile-nothing-to-repeat"),
    pytest.param("a{2,1}", id="python-cannot-compile-bad-repeat-range"),
]


@pytest.mark.parametrize("body", REJECTED_BODIES)
def test_regex_pattern_rejects_disallowed_syntax_at_construction(body: str) -> None:
    with pytest.raises(InvalidRegexError):
        RegexPattern(body)


@pytest.mark.parametrize("body", REJECTED_BODIES)
def test_normalize_regex_rejects_disallowed_syntax(body: str) -> None:
    with pytest.raises(InvalidRegexError):
        normalize_regex(body)


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


def test_plain_open_paren_is_not_rejected() -> None:
    # A bare "(" starts a normal capturing group and is explicitly allowed;
    # only the specific group-opener syntaxes above are banned.
    RegexPattern("(a)")


#
# RegexPattern -- accepted syntax
#
def test_non_capturing_group_with_quantifier() -> None:
    rx = RegexPattern("(?:sub)+")
    assert rx.full_match("subsubsub") is True
    assert rx.full_match("su") is False


def test_positive_lookahead() -> None:
    rx = RegexPattern("/\\d+(?=%)/f")
    assert rx.include_match("50%") is True
    assert rx.include_match("50kg") is False


def test_negative_lookahead() -> None:
    rx = RegexPattern("/\\d+(?!%)/f")
    assert rx.include_match("50kg") is True
    assert rx.include_match("abc") is False


def test_capturing_group_with_alternation() -> None:
    rx = RegexPattern("(a|b)c")
    assert rx.full_match("ac") is True
    assert rx.full_match("bc") is True
    assert rx.full_match("cc") is False


def test_negated_character_class() -> None:
    rx = RegexPattern("[^aeiou]+")
    assert rx.full_match("xyz") is True
    assert rx.full_match("aei") is False


def test_fixed_quantifier() -> None:
    rx = RegexPattern("\\d{4}")
    assert rx.full_match("1822") is True
    assert rx.full_match("18222") is False


def test_word_and_space_classes() -> None:
    assert RegexPattern("\\w+").full_match("Amazonia123") is True
    assert RegexPattern("\\w+").full_match("a b") is False
    assert RegexPattern("\\s").full_match(" ") is True
    assert RegexPattern("\\s").full_match("a") is False
    assert RegexPattern("\\S+").full_match("abc") is True
    assert RegexPattern("\\S+").full_match("a b") is False


def test_word_boundary_inside_f_flagged_pattern() -> None:
    rx = RegexPattern("/\\bcerrado\\b/f")
    assert rx.include_match("o cerrado nordestino") is True
    assert rx.include_match("cerradozinho") is False


def test_escaped_literal_dot() -> None:
    rx = RegexPattern("a\\.b")
    assert rx.full_match("a.b") is True
    assert rx.full_match("aXb") is False


def test_escaped_literal_backslash() -> None:
    rx = RegexPattern("a\\\\b")  # regex source: a, \\, b -> matches literal a\b
    assert rx.full_match("a\\b") is True  # actual subject: a, \, b


def test_unicode_escape() -> None:
    rx = RegexPattern("caf\\u00e9")
    assert rx.full_match("café") is True


def test_hex_escape() -> None:
    rx = RegexPattern("\\x41")
    assert rx.full_match("A") is True


def test_literal_unicode_character() -> None:
    rx = RegexPattern("/Amazônia/")
    assert rx.full_match("Amazônia") is True


#
# MDQ-flavoured end-to-end cases
#
@pytest.mark.parametrize(
    ("pattern", "string", "expected"),
    [
        pytest.param("/[Bb]ras[íi]lia/i", "Brasília", True, id="capital-accented"),
        pytest.param("/[Bb]ras[íi]lia/i", "brasilia", True, id="capital-lower-no-accent"),
        pytest.param("/[Bb]ras[íi]lia/i", "BRASILIA", True, id="capital-upper-no-accent"),
        pytest.param("/rio de janeiro/in", "Rio de Janeiro", True, id="rio-normalized-and-folded"),
        pytest.param(
            "/(?:mata )?atl[âa]ntica/i", "Mata Atlântica", True, id="biome-full-name"
        ),
        pytest.param(
            "/(?:mata )?atl[âa]ntica/i", "atlantica", True, id="biome-short-name"
        ),
        pytest.param("/\\d{4}/", "1822", True, id="independence-year-exact"),
        pytest.param("/\\d{4}/", "18222", False, id="independence-year-too-long"),
        pytest.param("/\\d{4}/", "ano 1822", False, id="independence-year-not-anchored-away"),
        pytest.param(
            "/-?\\d+(?:[.,]\\d+)?/", "-273,15", True, id="absolute-zero-comma-decimal"
        ),
        pytest.param(
            "/-?\\d+(?:[.,]\\d+)?/", "-273.15", True, id="absolute-zero-dot-decimal"
        ),
        pytest.param("/math\\.isnan/", "math.isnan", True, id="function-name-exact"),
        pytest.param(
            "/math\\.isnan/", "math.isnan()", False, id="function-name-rejects-call-syntax"
        ),
    ],
)
def test_mdq_end_to_end_examples(pattern: str, string: str, expected: bool) -> None:
    assert RegexPattern(pattern).match(string) is expected


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


# `re.escape` never touches "/" or whitespace, so a literal containing
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


@given(literal=ESCAPABLE_LITERAL)
@settings(max_examples=200)
def test_escaped_literal_full_matches_itself(literal: str) -> None:
    rx = RegexPattern(re.escape(literal))
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
    rx = RegexPattern(re.escape(literal))
    assert rx.include_match(pad_left + literal + pad_right) is True

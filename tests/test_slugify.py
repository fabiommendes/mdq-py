"""
Tests for `mdq.slugify`: the `loose`/`simple` unique-slugifier strategies,
`validate_slug`, and the `slugify` dispatcher.

`loose` is the interesting one -- it must *always* produce a valid, unique,
non-forbidden slug for every item, no matter how degenerate the input text
is (empty, symbols-only, all-identical-once-slugified, ...). The corner
cases below pin specific inputs; the Hypothesis properties at the bottom
check the same contract holds for the much wider space of inputs
`mdq.hypothesis.slugs` can generate, including deliberately collision-prone
sets built from cosmetic variants of the same text.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mdq.hypothesis import slugs as st_slugs
from mdq.slugify import (
    DIGIT_NAMES,
    SLUGIFIERS,
    SYMBOL_NAMES,
    loose,
    simple,
    slugify,
    validate_slug,
)


#
# validate_slug
#
@pytest.mark.parametrize(
    "value", ["a", "a-b", "a1-b2", "0", "a-b-c", "x" * 100, "1-2-3"]
)
def test_validate_slug_accepts_valid_slugs(value: str) -> None:
    assert validate_slug(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "-a",
        "a-",
        "-",
        "A",
        "a_b",
        "a b",
        "a.b",
        "café",
        "µ",  # unicode lowercase letter, but not ASCII (str.islower() is True)
        "٣",  # unicode digit, but not ASCII (str.isdigit() is True)
    ],
)
def test_validate_slug_rejects_invalid_slugs(value: str) -> None:
    with pytest.raises(ValueError):
        validate_slug(value)


def test_validate_slug_coerce_delegates_to_single_slugify() -> None:
    assert validate_slug("Café com Leite!", coerce=True) == "cafe-com-leite"


#
# simple
#
def test_simple_slugifies_each_item_independently() -> None:
    result = simple(frozenset({"Ouro Preto", "Amazônia"}))
    assert result == {"Ouro Preto": "ouro-preto", "Amazônia": "amazonia"}


def test_simple_raises_on_collision() -> None:
    with pytest.raises(ValueError):
        simple(frozenset({"Café", "cafe"}))


def test_simple_raises_when_result_hits_forbid() -> None:
    with pytest.raises(ValueError):
        simple(frozenset({"Café"}), forbid=frozenset({"cafe"}))


#
# loose -- corner cases
#
def test_loose_empty_items_returns_empty_dict() -> None:
    assert loose(frozenset()) == {}


def test_loose_single_item() -> None:
    result = loose(frozenset({"Capoeira"}))
    assert result == {"Capoeira": "capoeira"}


@pytest.mark.parametrize(
    "items",
    [
        frozenset({"", "   ", "!!!", "???", "***"}),
        frozenset({"", "🎉🎉🎉"}),
        frozenset({"\t", "\n", " \t\n "}),
    ],
)
def test_loose_handles_sets_with_no_sluggable_content(items: frozenset[str]) -> None:
    result = loose(items)
    _assert_valid_unique_slugs(items, frozenset(), result)


def test_loose_resolves_cosmetic_collisions() -> None:
    items = frozenset({"Ana", "ANA", "ana ", "Ana!", "Ana?", "AnA"})
    result = loose(items)
    _assert_valid_unique_slugs(items, frozenset(), result)
    # every value should still be recognizably "ana"-derived
    assert all(v == "ana" or v.startswith("ana-") for v in result.values())


def test_loose_resolves_accented_vs_ascii_collision() -> None:
    items = frozenset({"Café", "cafe"})
    result = loose(items)
    _assert_valid_unique_slugs(items, frozenset(), result)


def test_loose_avoids_forbid() -> None:
    items = frozenset({"Ana"})
    result = loose(items, forbid=frozenset({"ana"}))
    assert result == {"Ana": "ana-2"}


def test_loose_avoids_forbid_through_a_long_run_of_suffixes() -> None:
    forbid = frozenset({"a"} | {f"a-{n}" for n in range(2, 20)})
    result = loose(frozenset({"a"}), forbid=forbid)
    _assert_valid_unique_slugs(frozenset({"a"}), forbid, result)
    assert result["a"] == "a-20"


def test_loose_placeholder_collides_with_forbid_too() -> None:
    # The degenerate-text placeholder ("item") is itself forbidden, so the
    # numeric-suffix ladder must kick in even for symbol-only text.
    result = loose(frozenset({"!!!"}), forbid=frozenset({"item"}))
    assert result == {"!!!": "item-2"}


def test_loose_never_raises_on_pathological_forbid() -> None:
    # forbid intentionally covers every "item"/"item-N" the fallback ladder
    # would try for a while; loose() must keep climbing, never raise.
    forbid = frozenset({"item"} | {f"item-{n}" for n in range(2, 500)})
    result = loose(frozenset({"", "!!!", "???"}), forbid=forbid)
    _assert_valid_unique_slugs(frozenset({"", "!!!", "???"}), forbid, result)


def test_loose_handles_very_long_text() -> None:
    a = "x" * 300
    b = "x" * 300 + "y"
    result = loose(frozenset({a, b}))
    _assert_valid_unique_slugs(frozenset({a, b}), frozenset(), result)


def test_loose_short_and_full_candidates_both_used_when_they_collide() -> None:
    """
    Two items that share their first words but diverge later should get
    the *short* slug for one and the *full* slug for the other, not both
    falling through to numeric suffixes -- that's the whole point of
    trying the short/full ladder before the counter fallback.
    """
    a = "What is the capital of Brazil?"
    b = "What is the capital of Brazil (revised)?"
    result = loose(frozenset({a, b}))
    _assert_valid_unique_slugs(frozenset({a, b}), frozenset(), result)
    assert "-2" not in result[a] and "-2" not in result[b]


def test_loose_is_deterministic_regardless_of_set_build_order() -> None:
    items = ["banana", "abacaxi", "caju", "banana!", "Abacaxi"]
    forward = loose(frozenset(items))
    backward = loose(frozenset(reversed(items)))
    assert forward == backward


#
# slugify dispatcher
#
def test_slugify_rejects_duplicate_input() -> None:
    with pytest.raises(ValueError):
        slugify(["a", "a"])


def test_slugify_rejects_unknown_strategy() -> None:
    with pytest.raises(ValueError):
        slugify(["a"], strategy="does-not-exist")


def test_slugify_dispatches_to_registered_strategy() -> None:
    assert slugify(["Ouro Preto"], strategy="loose") == {"Ouro Preto": "ouro-preto"}


def test_loose_and_simple_are_registered() -> None:
    assert SLUGIFIERS["loose"] is loose
    assert SLUGIFIERS["simple"] is simple


#
# Hypothesis properties
#
@given(items=st_slugs.text_sets(max_size=12), forbid=st_slugs.forbid_sets())
@settings(max_examples=300)
def test_loose_always_returns_valid_unique_non_forbidden_slugs(
    items: frozenset[str], forbid: frozenset[str]
) -> None:
    result = loose(items, forbid=forbid)
    _assert_valid_unique_slugs(items, forbid, result)


@given(items=st_slugs.colliding_text_sets(min_size=2, max_size=10))
@settings(max_examples=300)
def test_loose_resolves_deliberately_collision_prone_sets(
    items: frozenset[str],
) -> None:
    """
    `colliding_text_sets` is built to make many items reduce to the same
    slug -- this is the strategy most likely to surface a bug in the
    disambiguation ladder itself, as opposed to in candidate generation.
    """
    result = loose(items)
    _assert_valid_unique_slugs(items, frozenset(), result)


@given(items=st_slugs.text_sets(max_size=10))
@settings(max_examples=200)
def test_loose_is_deterministic(items: frozenset[str]) -> None:
    assert loose(items) == loose(items)
    assert loose(items) == loose(frozenset(list(items)[::-1]))


@given(items=st_slugs.text_sets(min_size=1, max_size=8))
@settings(max_examples=200)
def test_loose_still_resolves_when_its_own_output_is_forbidden(
    items: frozenset[str],
) -> None:
    """
    Forbid exactly the slugs `loose` would naturally pick, forcing it past
    its first choice for every item; it must still produce a valid, unique,
    non-forbidden result instead of reusing or raising.
    """
    natural = frozenset(loose(items).values())
    result = loose(items, forbid=natural)
    _assert_valid_unique_slugs(items, natural, result)


@given(items=st_slugs.sluggable_texts().map(lambda s: frozenset({s})))
@settings(max_examples=200)
def test_loose_singleton_never_raises(items: frozenset[str]) -> None:
    result = loose(items)
    _assert_valid_unique_slugs(items, frozenset(), result)


#: A single digit or symbol is also a valid one-character slug, but
#: `loose` names it from a fixed table instead (dev/specs/to-do/derived-ids.md)
#: -- excluded from the no-op check below, which is about there being
#: nothing *more descriptive* to slugify a short text into.
_NAMED_GLYPHS = frozenset(DIGIT_NAMES) | frozenset(SYMBOL_NAMES)


@given(
    items=st.sets(st_slugs.short_slug_like_strings(), min_size=1, max_size=8)
    .map(frozenset)
    .filter(lambda items: items.isdisjoint(_NAMED_GLYPHS))
)
@settings(max_examples=150)
def test_loose_is_a_no_op_on_short_text_that_is_already_a_unique_slug(
    items: frozenset[str],
) -> None:
    """
    Short text that is already a valid, unique slug shape should slugify
    to itself -- there's nothing for the short/full/counter ladder to
    change. (Longer slug-shaped text can legitimately come back
    *truncated* by the short-candidate heuristic; that's covered by the
    general `_assert_valid_unique_slugs` properties instead.)
    """
    result = loose(items)
    assert result == {item: item for item in items}


#
# Helpers
#
def _assert_valid_unique_slugs(
    items: frozenset[str], forbid: frozenset[str], result: dict[str, str]
) -> None:
    """Shared contract every `loose`/`simple` result must satisfy."""
    assert set(result) == set(items)

    values = list(result.values())
    assert len(values) == len(set(values)), f"collision in {result}"
    assert not (set(values) & set(forbid)), f"forbidden slug used in {result}"

    for slug in values:
        validate_slug(slug)  # raises ValueError if not a valid slug shape

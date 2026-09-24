"""
This module defines a set of slugifier strategy functions.
"""

from typing import Protocol, Sequence

from slugify import slugify as single_slugify

type SetLike[T] = set[T] | frozenset[T]


class UniqueSlugifier(Protocol):
    """
    A slugifier function that takes a set of strings and returns a dict mapping
    each string to a unique slug.

    Slugs are URL-safe and unique within the set of strings. The slugifier may
    also take an optional `forbid` argument, which is a set of strings that the
    slugifier should avoid producing
    """

    __name__: str

    def __call__(
        self, items: SetLike[str], *, forbid: SetLike[str] = frozenset()
    ) -> dict[str, str]: ...


SLUGIFIERS: dict[str, UniqueSlugifier] = {}


def slugifier(fn: UniqueSlugifier) -> UniqueSlugifier:
    """
    Decorator to register a slugifier function.
    """
    SLUGIFIERS[fn.__name__] = fn
    return fn


def slugify(items: Sequence[str], strategy: str = "loose") -> dict[str, str]:
    """
    Slugify a set of strings using the specified strategy.
    """
    set_items = frozenset(items)

    if len(set_items) != len(items):
        raise ValueError("Input strings are not unique")
    if strategy not in SLUGIFIERS:
        raise ValueError(f"Unknown slugifier strategy: {strategy}")

    return SLUGIFIERS[strategy](set_items)


def validate_slug(value: str, coerce: bool = False) -> str:
    """
    Validate that a string is a valid slug.

    Return the slug if it is valid, or raise a ValueError if it is not.
    If `coerce` is True, attempt to coerce the value into a valid slug.
    """

    if coerce:
        return single_slugify(value)

    if not value:
        raise ValueError("Slug cannot be empty")
    if value[0] == "-" or value[-1] == "-":
        raise ValueError("Slug cannot start or end with a hyphen")
    for c in value:
        if not (c.isascii() and (c.islower() or c.isdigit()) or c == "-"):
            raise ValueError(
                "Slug can only contain lowercase letters, numbers, and hyphens"
            )
    return value


#
# The strategies
#
@slugifier
def loose(items: SetLike[str], *, forbid: SetLike[str] = frozenset()) -> dict[str, str]:
    """
    The default slugifier strategy.

    It tries increasingly difficult heuristics to produce a unique slug for
    each item in the set, until some of them succeed:

    1. A short slug made of the item's first few words.
    2. The full slug of the item's entire text.
    3. The full slug with an incrementing numeric suffix (`-2`, `-3`, ...),
       which always succeeds since it is tried arbitrarily many times.

    Unlike `simple`, this strategy never raises on a collision: it always
    returns a slug for every item, avoiding both duplicates among the
    results and anything in `forbid`.

    Items are processed in sorted order so the result only depends on the
    *content* of `items`, not on the (unordered) set's iteration order.
    """
    used: set[str] = set(forbid)
    result: dict[str, str] = {}

    for item in sorted(items):
        candidates = _slug_candidates(item)
        base = candidates[-1]

        slug = next((c for c in candidates if c not in used), None)
        if slug is None:
            counter = 2
            slug = f"{base}-{counter}"
            while slug in used:
                counter += 1
                slug = f"{base}-{counter}"

        used.add(slug)
        result[item] = slug

    return result


_SHORT_SLUG_MAX_LENGTH = 24
_EMPTY_SLUG_PLACEHOLDER = "item"

# Single-glyph text (a lone symbol or digit) slugifies to nothing useful
# once punctuation is stripped, so it gets a small name table instead --
# the "typical case" workaround docs/question-types/multiple-choice.md
# gestures at (`! -> bang`, `? -> question`). Formerly `mdq.parser`'s
# `DIGIT_NAMES`/`SYMBOL_NAMES`, moved here so a derived id stays the same
# regardless of who computes it (dev/specs/to-do/derived-ids.md).
DIGIT_NAMES = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}
SYMBOL_NAMES = {
    "-": "hyphen",
    "*": "asterisk",
    "+": "plus",
    "!": "bang",
    "?": "question",
    "/": "slash",
    ".": "dot",
    ",": "comma",
    ":": "colon",
    ";": "semicolon",
    "@": "at",
    "#": "hash",
    "$": "dollar",
    "%": "percent",
    "&": "ampersand",
    "=": "equals",
    "_": "underscore",
}


def _named_glyph(item: str) -> str | None:
    """
    Return the fixed name for `item` if it is a single glyph, wrapped in a
    Markdown code span (`` `-` ``) or not -- `None` otherwise.
    """
    core = item.strip()
    if len(core) >= 2 and core[0] == "`" and core[-1] == "`" and core.count("`") == 2:
        core = core[1:-1]
    if len(core) != 1:
        return None
    return SYMBOL_NAMES.get(core) or DIGIT_NAMES.get(core)


def _slug_candidates(item: str) -> list[str]:
    """
    Return `item`'s slug candidates, from the shortest/easiest to the most
    complete, with duplicates removed and never empty.

    A single-glyph text's fixed name (see `SYMBOL_NAMES`/`DIGIT_NAMES`)
    comes first, since there is nothing more descriptive to slugify it
    into. A "short" candidate (the item's first few words, cut at a word
    boundary) comes next since it usually reads better and is often
    already unique on its own. The "full" candidate (the item's entire
    text) comes after, since two items that share their first words can
    still differ later on. Items with no sluggable content at all (empty,
    whitespace, or symbols only) fall back to a fixed placeholder so a
    numeric suffix always has something to attach to.
    """
    named = _named_glyph(item)
    short = single_slugify(
        item,
        max_length=_SHORT_SLUG_MAX_LENGTH,
        word_boundary=True,
        save_order=True,
    )
    full = single_slugify(item)

    candidates = [c for c in (named, short, full) if c]
    unique_candidates = list(dict.fromkeys(candidates))
    return unique_candidates or [_EMPTY_SLUG_PLACEHOLDER]


@slugifier
def simple(
    items: SetLike[str], *, forbid: SetLike[str] = frozenset()
) -> dict[str, str]:
    """
    A simple slugifier strategy: use a sensible single-word slugifier function
    and raise ValueError if any collisions occur.
    """
    attempt = {item: single_slugify(item) for item in items}
    values = set(attempt.values())

    if len(attempt) != len(values):
        raise ValueError("Slugifier produced collisions")
    if invalid := forbid.intersection(values):
        raise ValueError(f"Slugifier produced forbidden slugs: {invalid}")

    return attempt

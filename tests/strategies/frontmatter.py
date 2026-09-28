"""
Hypothesis strategies for the `unknown-frontmatter-key` lint rule (see
`dev/specs/to-do/unknown-frontmatter-keys.md`,
`docs/question-types/base.md` and each type's own "Frontmatter" section,
and `docs/exam.md` §§ Frontmatter and Question block).

The known-key lists below are transcribed from the documented frontmatter
tables, not from `mdq.parser`'s own registry -- so a test built on them
exercises the spec, not whatever the parser happens to accept today. If
the parser's key set ever drifts from these lists, that is exactly the
bug this rule (and these strategies) exist to catch.
"""

from __future__ import annotations

from hypothesis import strategies as st

#: Keys common to every question type's frontmatter
#: (docs/question-types/base.md § Frontmatter).
COMMON_QUESTION_KEYS: tuple[str, ...] = (
    "type",
    "title",
    "id",
    "uuid",
    "tags",
    "author",
    "locale",
    "meta",
    "weight",
)

#: Extra frontmatter keys accepted per question type, beyond
#: `COMMON_QUESTION_KEYS` (each type's own "## Frontmatter" section under
#: docs/question-types/*.md).
TYPE_QUESTION_KEYS: dict[str, tuple[str, ...]] = {
    "essay": ("input", "highlight"),
    "multiple-choice": ("shuffle", "grading"),
    "multiple-selection": ("shuffle", "grading"),
    "true-false": ("shuffle", "grading"),
    "numeric": ("unit", "domain", "decimalPlaces"),
    "short-answer": ("accept", "reject", "preAccept", "preReject", "diacritics"),
    "fill-in": ("shuffle", "grading", "diacritics"),
    "ordering": (
        "content",
        "highlight",
        "indentation",
        "unmatched",
        "normalizations",
    ),
}

#: Exam-level frontmatter keys (docs/exam.md § Frontmatter).
EXAM_KEYS: tuple[str, ...] = (
    "type",
    "title",
    "description",
    "id",
    "uuid",
    "course",
    "author",
    "locale",
    "tags",
    "meta",
    "penalty",
    "grading",
    "start",
    "duration",
)

#: Keys accepted on an exam's per-block `include` frontmatter
#: (docs/exam.md § Question block).
EXAM_BLOCK_KEYS: tuple[str, ...] = ("include",)


def known_question_keys(question_type: str) -> tuple[str, ...]:
    """The documented frontmatter keys for `question_type`."""
    return COMMON_QUESTION_KEYS + TYPE_QUESTION_KEYS.get(question_type, ())


def unknown_keys(known: tuple[str, ...] = ()) -> st.SearchStrategy[str]:
    """
    Arbitrary YAML-mapping-key-shaped identifiers guaranteed not to be in
    `known`. Restricted to a plain identifier alphabet (letters, digits,
    underscore/hyphen, not starting with a digit) so every draw is a
    bare YAML key with no quoting or escaping to worry about.
    """
    ident = st.from_regex(r"[a-zA-Z_][a-zA-Z0-9_-]{2,15}", fullmatch=True)
    return ident.filter(lambda key: key not in known)

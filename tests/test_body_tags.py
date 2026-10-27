"""
Messages of the body tag errors (docs/question-types/question-base.md,
"Body tags"). The codes and paths are in the example corpus; a `.lint.json`
does not record the text.
"""

from __future__ import annotations

import mdq

STEM = "Qual é a capital do Brasil?\n\n"


def _errors(source: str) -> list[tuple[str, str]]:
    loaded = mdq.load(source, format="mdq")
    return [(d.code, d.message) for d in loaded.diagnostics if d.severity == "error"]


def test_the_unit_of_a_numeric_tag_keeps_its_case() -> None:
    [(code, message)] = _errors("Pressão?\n\n[Numeric(Pa)]: 101325\n")
    assert code == "parse-error"
    assert message == "tags are lower case: write `[numeric(Pa)]:`"


def test_a_known_tag_in_another_case_says_tags_are_lower_case() -> None:
    [(_, message)] = _errors(STEM + "[Short-Answer]: Brasília\n")
    assert message.startswith("tags are lower case: write `[")


def test_a_tag_with_an_unknown_suffix_says_unknown_tag() -> None:
    [(_, message)] = _errors(STEM + "[short-answer/foo]: b\n")
    assert message.startswith("unknown tag")


def test_a_frontmatter_field_is_not_a_tag() -> None:
    source = STEM + "[short-answer]: Brasília\n\n[short-answer/preAccept]: Brasilia\n"
    [(_, message)] = _errors(source)
    assert "frontmatter only" in message


def test_a_list_glued_to_a_content_list_asks_for_the_same_marker() -> None:
    [(_, message)] = _errors(STEM + "[short-answer]:\n* Brasília\n- Brasilia\n")
    assert "same list marker" in message

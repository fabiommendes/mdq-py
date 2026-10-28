"""
A `type` in the frontmatter that disagrees with the body is one
`parse-error`, and the frontmatter errors are reported even when the body
fails to parse (question-base.md, "Frontmatter" and "Type inference").
"""

from __future__ import annotations

import pytest

from mdq import load

STEM = "Qual é a capital do Brasil?\n\n"


def _codes(source: str) -> list[tuple[str, tuple[str | int, ...]]]:
    return [(d.code, tuple(d.path)) for d in load(source, format="mdq").diagnostics]


@pytest.mark.parametrize(
    ("declared", "body", "tag"),
    [
        ("numeric", "[short-answer]: Brasília\n", "short-answer"),
        ("short-answer", "[numeric]: 42\n", "numeric"),
        ("numeric", "[essay]\n", "essay"),
        ("essay", "[ordering]:\n* a\n* b\n", "ordering"),
        ("numeric", "* [*] Brasília\n* [ ] Rio\n", "choice list"),
        ("fill-in", "* [*] Brasília\n* [ ] Rio\n", "choice list"),
        ("multiple-choice", "[numeric]: 42\n", "numeric"),
    ],
)
def test_type_disagreeing_with_the_body_is_one_parse_error(
    declared: str, body: str, tag: str
) -> None:
    loaded = load(f"---\ntype: {declared}\n---\n\n{STEM}{body}", format="mdq")
    assert [d.code for d in loaded.diagnostics] == ["parse-error"]
    message = loaded.diagnostics[0].message
    assert declared in message
    assert tag in message


def test_matching_type_still_loads() -> None:
    loaded = load(f"---\ntype: short-answer\n---\n\n{STEM}[short-answer]: Brasília\n", format="mdq")
    assert loaded.document is not None


def test_frontmatter_error_is_reported_with_a_body_parse_error() -> None:
    codes = _codes(f"---\nfoo: 1\n---\n\n{STEM}[numeric]: abc\n")
    assert ("invalid-frontmatter-field", ("foo",)) in codes
    assert ("parse-error", ()) in codes


def test_declared_type_decides_the_frontmatter_keys_on_a_body_error() -> None:
    # `accept` is a field of a short answer, not of a numeric: the declared
    # `type`, not the body, says which keys are allowed.
    codes = _codes(f"---\ntype: numeric\naccept: x\n---\n\n{STEM}[numeric]: abc\n")
    assert ("invalid-frontmatter-field", ("accept",)) in codes
    codes = _codes(f"---\ntype: numeric\ndomain: integer\n---\n\n{STEM}[numeric]: abc\n")
    assert codes == [("parse-error", ())]


def test_body_type_decides_the_frontmatter_keys_without_a_declared_type() -> None:
    loaded = load(f"---\nfoo: 1\n---\n\n{STEM}[numeric]: abc\n", format="mdq")
    found = [d for d in loaded.diagnostics if d.code == "invalid-frontmatter-field"]
    assert [d.message for d in found] == ["'foo' is not a frontmatter field of a numeric"]


def test_unknown_type_reports_the_keys_no_type_allows() -> None:
    codes = _codes(f"---\ntype: foo\nbar: 1\n---\n\n{STEM}[numeric]: abc\n")
    assert ("invalid-frontmatter-field", ("bar",)) in codes

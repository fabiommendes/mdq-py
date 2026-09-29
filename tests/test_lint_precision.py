"""
Rules made more precise after the lint-codes audit:

* `accept-reject-overlap` compares ordering lines after all forms of
  normalization (ordering.md, "Accepted/rejected answers").
* `domain-mismatch` infers the domain from the answer and the absolute
  tolerance (numeric.md, "Number type/domain").
* `redundant-regex-anchor` reports only an anchor that is already
  implicit, given the `f`/`b` flags, in `regex` and in delimited
  `accept`/`reject` entries (short-answer.md, "Regex flags").
"""

from __future__ import annotations

import pytest

from mdq import Diagnostic, load


def _load(doc: dict) -> list[Diagnostic]:
    return load(doc, kind="question").diagnostics


def _paths(doc: dict, code: str) -> list[tuple]:
    return [d.path for d in _load(doc) if d.code == code]


# ---------------------------------------------------------------------
# accept-reject-overlap: after normalization
# ---------------------------------------------------------------------


def _ordering(accept: list, reject: list, **fields: object) -> dict:
    return {
        "type": "ordering",
        "id": "ciclo",
        "title": "Ciclo da água",
        "stem": "Ordene as etapas do ciclo da água na Amazônia.",
        "lines": [[0, "evaporação"], [0, "condensação"], [0, "precipitação"]],
        "accept": [{"lines": accept}],
        "reject": [{"lines": reject}],
        **fields,
    }


def test_overlap_after_dedent_is_an_error() -> None:
    doc = _ordering(
        accept=[[0, "condensação"], [0, "evaporação"]],
        reject=[[1, "condensação"], [1, "evaporação"]],
        normalizations=["dedent"],
    )
    loaded = load(doc, kind="question")
    assert loaded.document is None
    assert [d.code for d in loaded.diagnostics if d.severity == "error"] == [
        "accept-reject-overlap"
    ]


def test_overlap_after_skip_blanks_is_an_error() -> None:
    doc = _ordering(
        accept=[[0, "condensação"], [0, ""], [0, "evaporação"]],
        reject=[[0, "condensação"], [0, "evaporação"]],
        normalizations=["skip-blanks"],
    )
    loaded = load(doc, kind="question")
    assert loaded.document is None
    assert "accept-reject-overlap" in {d.code for d in loaded.diagnostics}


def test_lines_that_differ_after_normalization_do_not_overlap() -> None:
    doc = _ordering(
        accept=[[0, "condensação"], [0, "evaporação"]],
        reject=[[1, "condensação"], [1, "evaporação"]],
        indentation="strict",
    )
    loaded = load(doc, kind="question")
    assert loaded.document is not None, loaded.diagnostics


# ---------------------------------------------------------------------
# domain-mismatch: answer and absolute tolerance
# ---------------------------------------------------------------------


def _numeric(**fields: object) -> dict:
    return {
        "type": "numeric",
        "id": "altitude",
        "title": "Altitude",
        "stem": "Qual a altitude média de Brasília, em metros?",
        **fields,
    }


def test_decimal_absolute_tolerance_widens_the_inferred_domain() -> None:
    doc = _numeric(answer=1172, domain="decimal", tolerance={"absolute": 0.5})
    assert _paths(doc, "domain-mismatch") == []


def test_integer_domain_disagrees_with_a_decimal_absolute_tolerance() -> None:
    doc = _numeric(answer=1172, domain="integer", tolerance={"absolute": 0.5})
    assert _paths(doc, "domain-mismatch") == [("domain",)]


def test_relative_tolerance_takes_no_part_in_the_inferred_domain() -> None:
    doc = _numeric(answer=1172, domain="decimal", tolerance={"relative": 0.05})
    assert _paths(doc, "domain-mismatch") == [("domain",)]


def test_numeric_blank_domain_uses_the_absolute_tolerance() -> None:
    doc = {
        "type": "fill-in",
        "id": "altitude",
        "title": "Altitude",
        "stem": "Brasília fica a [^h] metros de altitude.",
        "blanks": [
            {
                "id": "h",
                "type": "numeric",
                "answer": 1172,
                "domain": "decimal",
                "tolerance": {"absolute": 0.5},
            }
        ],
    }
    assert _paths(doc, "domain-mismatch") == []


# ---------------------------------------------------------------------
# redundant-regex-anchor: only an implicit anchor, in every pattern
# ---------------------------------------------------------------------


def _short_answer(**fields: object) -> dict:
    return {
        "type": "short-answer",
        "id": "rio",
        "title": "Rio",
        "stem": "Qual rio banha Manaus?",
        **fields,
    }


@pytest.mark.parametrize(
    "regex",
    ["^Negro", "Negro$", "/^Negro/", "/Negro$/i", "/^Negro/b", "/^Rio Negro$/n"],
)
def test_implicit_anchor_in_regex_is_redundant(regex: str) -> None:
    assert _paths(_short_answer(regex=regex), "redundant-regex-anchor") == [("regex",)]


@pytest.mark.parametrize(
    "regex",
    ["Negro", "/Negro$/b", "/^Negro/f", "/Negro$/f", "/^Negro$/fb", r"Negro\$", r"/Negro\$/"],
)
def test_explicit_or_literal_anchor_in_regex_is_not_redundant(regex: str) -> None:
    assert _paths(_short_answer(regex=regex), "redundant-regex-anchor") == []


@pytest.mark.parametrize("section", ["accept", "reject"])
def test_implicit_anchor_in_a_delimited_pattern_is_redundant(section: str) -> None:
    fields: dict[str, object] = {section: [{"pattern": "Negro"}, {"pattern": "/^Solimões/"}]}
    if section == "reject":
        fields["oneOf"] = ["Negro"]
    doc = _short_answer(**fields)
    assert _paths(doc, "redundant-regex-anchor") == [(section, 1)]


@pytest.mark.parametrize("pattern", ["^Negro", "/Negro$/b", "/^Negro/f"])
def test_literal_or_needed_anchor_in_accept_is_not_redundant(pattern: str) -> None:
    doc = _short_answer(accept=[{"pattern": pattern}])
    assert _paths(doc, "redundant-regex-anchor") == []


# ---------------------------------------------------------------------
# The parser derives `domain` from the value and the absolute tolerance
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "domain"),
    [
        ("0 +- 0.01", "decimal"),
        ("42 +- 1", "integer"),
        ("42 +- 5%", "integer"),
        ("42 +- 0.5 +- 5%", "decimal"),
        ("1/3 +- 1", "fraction"),
        ("1/3 +- 0.01", "decimal"),
        ("3.5 +- 1", "decimal"),
    ],
)
def test_parser_domain_is_the_wider_of_value_and_absolute_tolerance(
    body: str, domain: str
) -> None:
    text = f"Qual a altitude do Pico da Bandeira?\n\n[numeric]: {body}\n"
    loaded = load(text, kind="question")
    assert loaded.document is not None, loaded.diagnostics
    assert loaded.document.domain == domain
    assert "domain-mismatch" not in {d.code for d in loaded.diagnostics}


def test_parser_numeric_blank_domain_uses_the_absolute_tolerance() -> None:
    text = "O Pico da Bandeira tem [^h] km.\n\n[^h/numeric]: 3 +- 0.1\n"
    loaded = load(text, kind="question")
    assert loaded.document is not None, loaded.diagnostics
    assert loaded.document.blanks[0].domain == "decimal"


@pytest.mark.parametrize("domain", ["fraction", "decimal"])
def test_a_float_answer_can_be_a_fraction_or_a_decimal(domain: str) -> None:
    """numeric.md, "Answer representation": a parsed `[numeric]: 3/4` is
    `answer: 0.75` with `domain: fraction`. A float cannot tell a fraction
    from a decimal, so neither declared domain contradicts it."""
    doc = _numeric(answer=0.75, domain=domain, tolerance={"absolute": 1})
    assert _paths(doc, "domain-mismatch") == []


def test_a_float_answer_with_a_decimal_tolerance_is_not_a_fraction() -> None:
    doc = _numeric(answer=0.75, domain="fraction", tolerance={"absolute": 0.01})
    assert _paths(doc, "domain-mismatch") == [("domain",)]

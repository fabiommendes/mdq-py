"""
numeric.md: which answers agree with a declared `domain` (P4), and when
`decimalPlaces` is ignored (Q5).

* With `domain: fraction`, the answer SHOULD be a fraction string or an
  integer (a number or an integer string). A non-whole number is a
  decimal only, so it gets `domain-mismatch`.
* `ignored-decimal-places` uses the effective domain: the declared one,
  else the one inferred from the answer and the absolute tolerance.
"""

from __future__ import annotations

import pytest

from mdq import load


def _numeric(**fields: object) -> dict:
    return {
        "type": "numeric",
        "id": "moeda",
        "title": "Moedas",
        "stem": "Que fração de um real vale uma moeda de 25 centavos?",
        **fields,
    }


def _blank(**fields: object) -> dict:
    return {
        "type": "fill-in",
        "id": "moeda",
        "title": "Moedas",
        "stem": "Uma moeda de 25 centavos vale [^v] de um real.",
        "blanks": [{"id": "v", "type": "numeric", **fields}],
    }


def _codes(doc: dict | str) -> list[str]:
    if isinstance(doc, str):
        return [d.code for d in load(doc, format="mdq").diagnostics]
    return [d.code for d in load(doc).diagnostics]


# ---------------------------------------------------------------------
# P4: domain fraction
# ---------------------------------------------------------------------


@pytest.mark.parametrize("answer", ["1/4", "-3/4", 1, -2, "2", 2.0])
def test_fraction_domain_accepts_a_fraction_string_or_an_integer(answer: object) -> None:
    assert "domain-mismatch" not in _codes(_numeric(answer=answer, domain="fraction"))
    assert "domain-mismatch" not in _codes(_blank(answer=answer, domain="fraction"))


@pytest.mark.parametrize("answer", [0.25, -0.75, "0.25", "2.50"])
def test_fraction_domain_rejects_a_decimal(answer: object) -> None:
    assert "domain-mismatch" in _codes(_numeric(answer=answer, domain="fraction"))
    assert "domain-mismatch" in _codes(_blank(answer=answer, domain="fraction"))


def test_markdown_decimal_with_a_declared_fraction_domain_mismatches() -> None:
    source = "---\ndomain: fraction\n---\n\nQuanto vale?\n\n[numeric]: 0.75 +- 1\n"
    assert "domain-mismatch" in _codes(source)


def test_markdown_integer_with_a_declared_fraction_domain_agrees() -> None:
    source = "---\ndomain: fraction\n---\n\nQuanto vale?\n\n[numeric]: 2\n"
    assert "domain-mismatch" not in _codes(source)


@pytest.mark.parametrize("answer", [0.75, 1172, "1/3"])
def test_non_whole_number_still_agrees_with_decimal(answer: object) -> None:
    codes = _codes(_numeric(answer=answer, domain="decimal", tolerance={"absolute": 0.5}))
    assert "domain-mismatch" not in codes


def test_integer_answer_still_disagrees_with_a_declared_decimal() -> None:
    assert "domain-mismatch" in _codes(_numeric(answer=1172, domain="decimal"))


# ---------------------------------------------------------------------
# Q5: ignored-decimal-places uses the effective domain
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"answer": 203},
        {"answer": "1/3"},
        {"answer": 203, "tolerance": {"absolute": 1}},
        {"answer": 203, "domain": "integer"},
        {"answer": "1/3", "domain": "fraction"},
        {"answer": 3.25, "domain": "fraction"},
    ],
)
def test_decimal_places_ignored_unless_the_effective_domain_is_decimal(fields: dict) -> None:
    assert "ignored-decimal-places" in _codes(_numeric(decimalPlaces=2, **fields))
    assert "ignored-decimal-places" in _codes(_blank(decimalPlaces=2, **fields))


@pytest.mark.parametrize(
    "fields",
    [
        {"answer": 3.25},
        {"answer": "2.50"},
        {"answer": 203, "tolerance": {"absolute": 0.5}},
        {"answer": 203, "domain": "decimal"},
    ],
)
def test_decimal_places_used_when_the_effective_domain_is_decimal(fields: dict) -> None:
    assert "ignored-decimal-places" not in _codes(_numeric(decimalPlaces=2, **fields))
    assert "ignored-decimal-places" not in _codes(_blank(decimalPlaces=2, **fields))

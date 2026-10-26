"""
numeric.md, "Decimal places": a fraction has no decimal places of its own.
Under `decimal`, with no `decimalPlaces`, only the absolute tolerance gives
them; if it gives none, the document is an error (`missing-decimal-places`).
"""

from __future__ import annotations

import pytest

from mdq import load
from mdq.models._numeric import infer_decimal_places, numeric_matches
from mdq.models import Tolerance


def _numeric(**fields: object) -> dict:
    return {
        "type": "numeric",
        "id": "amazonia",
        "title": "Amazônia",
        "stem": "Qual fração do território brasileiro a Amazônia Legal ocupa?",
        "answer": "1/3",
        **fields,
    }


def _blank(**fields: object) -> dict:
    return {
        "type": "fill-in",
        "id": "amazonia",
        "title": "Amazônia",
        "stem": "A Amazônia Legal ocupa [^v] do território.",
        "blanks": [{"id": "v", "type": "numeric", "answer": "1/3", **fields}],
    }


def _codes(doc: dict | str, **kwargs: str) -> list[str]:
    result = load(doc, **kwargs)
    return [d.code for d in result.diagnostics if d.severity == "error"]


@pytest.mark.parametrize("maker", [_numeric, _blank])
@pytest.mark.parametrize(
    "fields",
    [
        {"domain": "decimal"},
        {"domain": "decimal", "tolerance": {"relative": 0.1}},
        {"domain": "decimal", "tolerance": {"absolute": 1}},
        {"domain": "decimal", "tolerance": {"absolute": 1.0}},
    ],
)
def test_fraction_without_any_places_is_an_error(maker, fields: dict) -> None:
    assert _codes(maker(**fields)) == ["missing-decimal-places"]


@pytest.mark.parametrize("maker", [_numeric, _blank])
@pytest.mark.parametrize(
    "fields",
    [
        {"domain": "decimal", "decimalPlaces": 2},
        {"domain": "decimal", "decimalPlaces": 0},
        {"domain": "decimal", "tolerance": {"absolute": 0.01}},
        {"tolerance": {"absolute": 0.01}},
        {},
        {"domain": "fraction"},
    ],
)
def test_fraction_with_places_or_other_domain_is_valid(maker, fields: dict) -> None:
    assert _codes(maker(**fields)) == []


def test_markdown_fraction_under_declared_decimal_is_an_error() -> None:
    source = "---\ndomain: decimal\n---\n\nQuanto?\n\n[numeric]: 1/3\n"
    assert _codes(source, format="mdq") == ["missing-decimal-places"]


@pytest.mark.parametrize(
    "body",
    ["1/3 +- 0.01", "1/3 +- 0.5%", "1/3 +- 1"],
)
def test_markdown_fraction_without_declared_decimal_is_valid(body: str) -> None:
    assert _codes(f"Quanto?\n\n[numeric]: {body}\n", format="mdq") == []


def test_markdown_fraction_with_declared_places_is_valid() -> None:
    source = "---\ndomain: decimal\ndecimalPlaces: 2\n---\n\nQuanto?\n\n[numeric]: 1/3\n"
    assert _codes(source, format="mdq") == []


def test_inference_ignores_the_places_of_a_fraction() -> None:
    assert infer_decimal_places("1/3", None) == 0
    assert infer_decimal_places("1/3", Tolerance(absolute=0.01)) == 2


def test_declared_places_round_a_fraction_answer() -> None:
    kwargs = {"tolerance": None, "decimal_places": 2, "domain": "decimal"}
    assert numeric_matches("1/3", 0.33, **kwargs)
    assert numeric_matches("1/3", 0.333, **kwargs)
    assert not numeric_matches("1/3", 0.34, **kwargs)

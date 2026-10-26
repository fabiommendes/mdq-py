"""
numeric.md, "Decimal places": a fraction blank under `decimal`, with no
`decimalPlaces`, gets them only from the absolute tolerance; if it gives
none, the document is an error (`missing-decimal-places`). The question-level
cases are in the corpus (`numeric-fraction-decimal-places-missing`).
"""

from __future__ import annotations

import pytest

from mdq import load


def _blank(**fields: object) -> dict:
    return {
        "type": "fill-in",
        "id": "amazonia",
        "title": "Amazônia",
        "stem": "A Amazônia Legal ocupa [^v] do território.",
        "blanks": [{"id": "v", "type": "numeric", "answer": "1/3", **fields}],
    }


def _codes(doc: dict) -> list[str]:
    return [d.code for d in load(doc).diagnostics if d.severity == "error"]


@pytest.mark.parametrize(
    "fields",
    [
        {"domain": "decimal"},
        {"domain": "decimal", "tolerance": {"relative": 0.1}},
        {"domain": "decimal", "tolerance": {"absolute": 1}},
        {"domain": "decimal", "tolerance": {"absolute": 1.0}},
    ],
)
def test_fraction_without_any_places_is_an_error(fields: dict) -> None:
    assert _codes(_blank(**fields)) == ["missing-decimal-places"]

"""
A diagnostic path points into the document as written. A bare string is
shorthand for a mapping, so an error on the expanded field (for example
a bare choice missing a field) is reported at the string, not below it.
"""

from __future__ import annotations

from typing import Any

from mdq import load


def _paths(doc: dict[str, Any]) -> list[tuple[str | int, ...]]:
    loaded = load(doc)
    assert loaded.document is None
    return [d.path for d in loaded.diagnostics if d.severity == "error"]


def test_bare_choice_missing_a_field_is_reported_at_the_choice() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": ["Brasília", "Recife"],
    }
    assert _paths(doc) == [("choices", 0), ("choices", 1)]

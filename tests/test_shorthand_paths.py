"""
A diagnostic path points into the document as written. A bare string is
shorthand for a mapping, so an error on the expanded field (for example
an empty `pattern`) is reported at the string, not below it.
"""

from __future__ import annotations

from typing import Any

import pytest

from mdq import load

_BLANK = {"id": "bioma", "type": "short-answer"}


def _short_answer(**fields: Any) -> dict[str, Any]:
    return {
        "type": "short-answer",
        "stem": "Qual é o maior bioma brasileiro?",
        "accept": ["Amazônia"],
        **fields,
    }


def _fill_in(accept: list[Any]) -> dict[str, Any]:
    return {
        "type": "fill-in",
        "stem": "O maior bioma brasileiro é [^bioma].",
        "blanks": [{**_BLANK, "accept": accept}],
    }


def _paths(doc: dict[str, Any]) -> list[tuple[str | int, ...]]:
    loaded = load(doc)
    assert loaded.document is None
    return [d.path for d in loaded.diagnostics if d.severity == "error"]


@pytest.mark.parametrize("field", ["accept", "reject", "preAccept", "preReject"])
def test_empty_bare_pattern_is_reported_at_the_list_item(field: str) -> None:
    doc = _short_answer(**{field: ["Amazônia", ""]})
    assert _paths(doc) == [(field, 1)]


def test_empty_bare_pattern_in_a_fill_in_blank_is_reported_at_the_item() -> None:
    assert _paths(_fill_in([""])) == [("blanks", 0, "accept", 0)]


def test_empty_pattern_written_as_a_mapping_keeps_the_field_in_the_path() -> None:
    assert _paths(_short_answer(accept=[{"pattern": ""}])) == [("accept", 0, "pattern")]
    assert _paths(_fill_in([{"pattern": ""}])) == [("blanks", 0, "accept", 0, "pattern")]


def test_bare_choice_missing_a_field_is_reported_at_the_choice() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": ["Brasília", "Recife"],
    }
    assert _paths(doc) == [("choices", 0), ("choices", 1)]

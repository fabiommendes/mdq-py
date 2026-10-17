"""
An id in a response that names nothing in the question is a malformed
response (`ResponseError`), never ignored (responses.md).
"""

from __future__ import annotations

from typing import Any

import pytest

import mdq
from mdq.errors import ResponseError


def _question(doc: dict[str, Any]) -> Any:
    loaded = mdq.load(doc, kind="question")
    assert loaded.document is not None, loaded.diagnostics
    return loaded.document


def test_multiple_selection_unknown_tick_raises() -> None:
    question = _question(
        {
            "type": "multiple-selection",
            "stem": "Biomes of Brazil",
            "choices": [
                {"id": "a", "text": "Cerrado", "correct": True},
                {"id": "b", "text": "Tundra", "correct": False},
            ],
        }
    )
    with pytest.raises(ResponseError, match="'z'"):
        question.score_response({"a", "z"})


def test_multiple_selection_non_string_tick_raises() -> None:
    question = _question(
        {
            "type": "multiple-selection",
            "stem": "Biomes of Brazil",
            "choices": [
                {"id": "a", "text": "Cerrado", "correct": True},
                {"id": "b", "text": "Tundra", "correct": False},
            ],
        }
    )
    with pytest.raises(ResponseError):
        question.score_response({"a", 1})


def test_true_false_unknown_statement_raises() -> None:
    question = _question(
        {
            "type": "true-false",
            "stem": "Amazon facts",
            "choices": [
                {"id": "a", "text": "It is a rainforest", "correct": True},
                {"id": "b", "text": "It is a desert", "correct": False},
            ],
        }
    )
    with pytest.raises(ResponseError, match="'z'"):
        question.score_response({"a": True, "b": False, "z": True})


def test_fill_in_unknown_blank_raises() -> None:
    question = _question(
        {
            "type": "fill-in",
            "stem": "The capital of Brazil is [^city] in the [^region] region.",
            "blanks": [
                {"id": "city", "type": "short-answer", "accept": [{"pattern": "Brasília"}]},
                {"id": "region", "type": "short-answer", "accept": [{"pattern": "Centro-Oeste"}]},
            ],
        }
    )
    with pytest.raises(ResponseError, match="'zzz'"):
        question.score_response({"city": "Brasília", "zzz": "x"})

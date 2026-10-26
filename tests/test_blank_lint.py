"""
Numeric lint rules for an `answer` written as a string.

Written against the public `mdq.load` API.
"""

from __future__ import annotations

import pytest

from mdq import Diagnostic, load


def _diagnostics(doc: dict, code: str) -> list[Diagnostic]:
    loaded = load(doc, kind="question")
    assert loaded.document is not None, loaded.diagnostics
    return [d for d in loaded.diagnostics if d.code == code]


def _numeric_doc(**fields: object) -> dict:
    return {
        "type": "numeric",
        "id": "rios",
        "title": "Rios",
        "stem": "Quantos estados o rio São Francisco atravessa?",
        **fields,
    }


def _numeric_blank_doc(**fields: object) -> dict:
    return {
        "type": "fill-in",
        "id": "rios",
        "title": "Rios",
        "stem": "O rio São Francisco atravessa [^n] estados.",
        "blanks": [{"id": "n", "type": "numeric", **fields}],
    }


@pytest.mark.parametrize("answer", ["0", "-0"])
def test_relative_tolerance_around_a_string_zero_answer_warns(answer: str) -> None:
    doc = _numeric_doc(answer=answer, tolerance={"relative": 0.05})
    found = _diagnostics(doc, "relative-tolerance-around-zero")
    assert [d.path for d in found] == [("tolerance", "relative")]


def test_numeric_blank_relative_tolerance_around_a_string_zero_warns() -> None:
    doc = _numeric_blank_doc(answer="0", tolerance={"relative": 0.1})
    found = _diagnostics(doc, "relative-tolerance-around-zero")
    assert [d.path for d in found] == [("blanks", 0, "tolerance", "relative")]

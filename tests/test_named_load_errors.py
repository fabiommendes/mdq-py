"""
Error codes `load` reports when a document cannot become a model.

* Q6: every built-in pydantic error type is reported as `schema-error`.
  A named MDQ rule keeps its own code.
* Q7: an exam `duration` must be a positive ISO 8601 duration
  (`invalid-duration`), and `start` an ISO 8601 date or date-time
  (`malformed-start`) -- exam.md, "Duration and Start Time".
* Q8: a true-false marker must be a single letter
  (`malformed-true-false-marker`) -- true-false.md, "Additional Rules".
  `X`/`x` keeps `reserved-true-false-marker`.
"""

from __future__ import annotations

import pytest

from mdq import load


def _errors(doc: dict) -> list[tuple[str, tuple]]:
    loaded = load(doc)
    assert loaded.document is None
    return [(d.code, d.path) for d in loaded.diagnostics if d.severity == "error"]


# ---------------------------------------------------------------------
# Q6: schema-error
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("doc", "path"),
    [
        ({"type": "essay"}, ("stem",)),
        ({"type": "essay", "stem": "Descreva o Cerrado.", "colour": "verde"}, ("colour",)),
        ({"type": "essay", "stem": "Descreva o Cerrado.", "weight": -1}, ("weight",)),
        ({"type": "numeric", "stem": "Quanto?", "answer": 1, "decimalPlaces": -1}, ("decimalPlaces",)),
        ({"type": "numeric", "stem": "Quanto?", "answer": 1, "unit": "k g"}, ("unit",)),
    ],
)
def test_builtin_pydantic_errors_are_schema_errors(doc: dict, path: tuple) -> None:
    assert _errors(doc) == [("schema-error", path)]


def test_schema_error_keeps_pydantics_message() -> None:
    [diagnostic] = load({"type": "essay"}).diagnostics
    assert diagnostic.code == "schema-error"
    assert diagnostic.message


def test_named_rule_keeps_its_code() -> None:
    doc = {"type": "numeric", "stem": "Quanto?", "answer": "1/0"}
    assert _errors(doc) == [("malformed-numeric-answer", ("answer",))]


# ---------------------------------------------------------------------
# Q7: exam duration and start
# ---------------------------------------------------------------------


def _exam(**fields: object) -> dict:
    return {"type": "exam", "title": "Prova de Geografia", "questions": [], **fields}


@pytest.mark.parametrize("duration", ["PT0S", "P0D", "P1M", "P1Y", "1 hour", ""])
def test_invalid_duration(duration: str) -> None:
    assert _errors(_exam(duration=duration)) == [("invalid-duration", ("duration",))]


@pytest.mark.parametrize("start", ["10/03/2026", "2026-13-01", "amanhã", ""])
def test_malformed_start(start: str) -> None:
    assert _errors(_exam(start=start)) == [("malformed-start", ("start",))]


def test_valid_schedule_loads() -> None:
    loaded = load(_exam(start="2026-03-10T09:00:00-03:00", duration="PT1H30M"))
    assert loaded.document is not None


# ---------------------------------------------------------------------
# Q8: true-false marker
# ---------------------------------------------------------------------


def _true_false(marker: str) -> dict:
    return {
        "type": "true-false",
        "stem": "Julgue as afirmações sobre o Pantanal.",
        "choices": [
            {"text": "É a maior planície alagável do mundo.", "correct": True, "marker": marker},
            {"text": "Fica inteiramente no Brasil.", "correct": False, "marker": "F"},
        ],
    }


@pytest.mark.parametrize("marker", ["", "TRUE", "1", "*", "?", "T́"])
def test_malformed_true_false_marker(marker: str) -> None:
    assert _errors(_true_false(marker)) == [
        ("malformed-true-false-marker", ("choices", 0, "marker"))
    ]


@pytest.mark.parametrize("marker", ["X", "x"])
def test_reserved_marker_keeps_its_code(marker: str) -> None:
    assert _errors(_true_false(marker)) == [
        ("reserved-true-false-marker", ("choices", 0, "marker"))
    ]


@pytest.mark.parametrize("marker", ["T", "V", "C", "É", "Ω"])
def test_single_letter_marker_loads(marker: str) -> None:
    loaded = load(_true_false(marker))
    assert loaded.document is not None, loaded.diagnostics

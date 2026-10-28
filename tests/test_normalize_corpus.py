"""
`examples/normalize.yaml`: inputs the models accept and normalize (a nested
`null`, a YAML 1.1 form, a non-canonical duration), and, with
`normalize: true`, the result of `normalize()`. The header of the file
describes the format.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml

from mdq import load
from _corpus import EXAMPLES_ROOT

CASES: list[dict[str, Any]] = yaml.safe_load(
    (EXAMPLES_ROOT / "normalize.yaml").read_text(encoding="utf-8")
)["cases"]


def test_there_are_normalize_cases() -> None:
    assert CASES


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_load_normalizes_the_input(case: dict[str, Any]) -> None:
    kwargs: dict[str, Any] = {}
    if "kind" in case:
        kwargs["kind"] = case["kind"]
    if case.get("format") == "yaml":
        kwargs["format"] = "yaml"
    loaded = load(case["input"], **kwargs)
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    assert loaded.document is not None
    document = loaded.document.normalize() if case.get("normalize") else loaded.document
    # JSON round trip: `to_dict()` holds a tuple where the corpus has a list.
    assert json.loads(json.dumps(document.to_dict())) == case["output"]


#: Cases whose normalized form does not load back from its render: a stem or
#: epilogue that starts with a thematic break (the render reads as frontmatter).
_NO_ROUND_TRIP = {
    "a stem that starts with a thematic break is kept by normalize",
    "an epilogue that starts with a thematic break is kept by normalize",
}
ROUND_TRIP_CASES = [
    case for case in CASES if case.get("normalize") and case["name"] not in _NO_ROUND_TRIP
]


@pytest.mark.parametrize(
    "case", ROUND_TRIP_CASES, ids=[case["name"] for case in ROUND_TRIP_CASES]
)
def test_normalize_is_what_a_render_parse_round_trip_gives(case: dict[str, Any]) -> None:
    loaded = load(case["input"])
    assert loaded.document is not None
    normalized = loaded.document.normalize()
    reparsed = load(normalized.render()).document
    assert reparsed is not None
    assert reparsed.to_dict() == normalized.to_dict()


_ANSWERS: list[int | float | str] = [
    "1e3", "1.5e2", "100", "2.50", "1/3", "+5", "-0.5", "1E-2", "6.022e23",
    "3e-324", "12345678901", 1, 100, 1.5, 1e20, 1e-7, 0.1, -3, 1e3,
]  # fmt: skip
_TOLERANCES: list[dict[str, float] | None] = [
    None,
    {"absolute": 0.5},
    {"absolute": 1},
    {"relative": 0.05},
    {"absolute": 0.25, "relative": 0.1},
]


@pytest.mark.parametrize("tolerance", _TOLERANCES, ids=str)
@pytest.mark.parametrize("answer", _ANSWERS, ids=repr)
def test_normalized_numeric_question_is_what_render_parse_keeps(
    answer: int | float | str, tolerance: dict[str, float] | None
) -> None:
    data: dict[str, Any] = {"type": "numeric", "stem": "Qual?", "answer": answer}
    if tolerance:
        data["tolerance"] = tolerance
    document = load(data).document
    assert document is not None
    normalized = document.normalize()
    assert normalized.normalize() == normalized
    reparsed = load(normalized.render()).document
    assert reparsed is not None
    assert reparsed.to_dict() == normalized.to_dict()
    # A float that has an exponent in the source is written without it, and
    # the written form (`1000.0`) reads as a string: the original render
    # differs from the normalized form only there.
    if "e" not in str(answer).lower():
        original = load(document.render()).document
        assert original is not None
        assert original.to_dict() == normalized.to_dict()

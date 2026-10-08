"""
`examples/grading/*.yaml`: tables of answer keys and the score each
response gets. The choice types list every grading strategy
(multiple-choice.md, multiple-selection.md and true-false.md, "Grading");
numeric and short-answer are binary, and also list the responses that
are malformed or pending (responses.md).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import pytest
import yaml
from _corpus import EXAMPLES_ROOT

import mdq
from mdq.errors import NotAutoGradable, ResponseError

GRADING_ROOT = EXAMPLES_ROOT / "grading"


def _number(value: Any) -> float:
    # Fractions in the files stand for values that floats cannot write exactly.
    return float(Fraction(str(value)))


def _cases(name: str) -> list[Any]:
    data = yaml.safe_load((GRADING_ROOT / f"{name}.yaml").read_text(encoding="utf-8"))
    return data["questions"]


def _question(type_: str, case: dict[str, Any], **choice_field: Any) -> Any:
    key = "score" if type_ == "multiple-choice" else "correct"
    choices = [
        {"id": cid, "text": cid, **({} if value is None else {key: value})}
        for cid, value in case["choices"].items()
    ]
    doc = {"type": type_, "stem": case["name"], "grading": case["grading"], "choices": choices}
    loaded = mdq.load(doc, kind="question")
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    return loaded.document


def _mc_params() -> list[Any]:
    return [
        pytest.param(case, response, expected, id=f"{case['grading']}/{case['name']}/{response}")
        for case in _cases("multiple-choice")
        for response, expected in case["examples"].items()
    ]


@pytest.mark.parametrize(("case", "response", "expected"), _mc_params())
def test_multiple_choice(case: dict[str, Any], response: str, expected: Any) -> None:
    question = _question("multiple-choice", case)
    assert question.score_response(response).score == pytest.approx(_number(expected))


def _ms_params() -> list[Any]:
    return [
        pytest.param(case, example, id=f"{case['grading']}/{case['name']}/{example['ticks']}")
        for case in _cases("multiple-selection")
        for example in case["examples"]
    ]


@pytest.mark.parametrize(("case", "example"), _ms_params())
def test_multiple_selection(case: dict[str, Any], example: dict[str, Any]) -> None:
    question = _question("multiple-selection", case)
    score = question.score_response(set(example["ticks"])).score
    assert score == pytest.approx(_number(example["score"]))


def _tf_params() -> list[Any]:
    return [
        pytest.param(case, example, id=f"{case['grading']}/{case['name']}/{example['marks']}")
        for case in _cases("true-false")
        for example in case["examples"]
    ]


@pytest.mark.parametrize(("case", "example"), _tf_params())
def test_true_false(case: dict[str, Any], example: dict[str, Any]) -> None:
    question = _question("true-false", case)
    marks = {cid: example["marks"].get(cid) for cid in case["choices"]}
    score = question.score_response(marks).score
    assert score == pytest.approx(_number(example["score"]))


def _binary_question(type_: str, case: dict[str, Any]) -> Any:
    doc = {"type": type_, "stem": case["name"], **case["question"]}
    loaded = mdq.load(doc, kind="question")
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    return loaded.document


def _binary_params(name: str) -> list[Any]:
    return [
        pytest.param(case, example, id=f"{case['name']}/{example['response']!r}")
        for case in _cases(name)
        for example in case["examples"]
    ]


@pytest.mark.parametrize(("case", "example"), _binary_params("numeric"))
def test_numeric(case: dict[str, Any], example: dict[str, Any]) -> None:
    question = _binary_question("numeric", case)
    if example["score"] == "malformed":
        with pytest.raises(ResponseError):
            question.score_response(example["response"])
        return
    score = question.score_response(example["response"]).score
    assert score == pytest.approx(_number(example["score"]))


@pytest.mark.parametrize(("case", "example"), _binary_params("short-answer"))
def test_short_answer(case: dict[str, Any], example: dict[str, Any]) -> None:
    question = _binary_question("short-answer", case)
    if example["score"] == "pending":
        with pytest.raises(NotAutoGradable):
            question.score_response(example["response"])
        return
    score = question.score_response(example["response"]).score
    assert score == pytest.approx(_number(example["score"]))


def test_every_grading_file_is_covered() -> None:
    names = sorted(p.stem for p in GRADING_ROOT.glob("*.yaml"))
    assert names == [
        "multiple-choice",
        "multiple-selection",
        "numeric",
        "short-answer",
        "true-false",
    ]

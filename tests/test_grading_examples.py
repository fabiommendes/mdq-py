"""
`examples/grading/*.yaml`: tables of answer keys and the score each
response gets. The choice types list every grading strategy
(multiple-choice.md, multiple-selection.md and true-false.md, "Grading");
numeric and short-answer are binary, and also list the responses that
are malformed or pending (responses.md). `exam.yaml` scores whole exams and
resolves the inheritance of `grading` and `shuffle`; `automation.yaml` gives
the `automation` of a question; `essay.yaml` lists the essay responses.
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


def _cases(name: str, key: str = "questions") -> list[Any]:
    data = yaml.safe_load((GRADING_ROOT / f"{name}.yaml").read_text(encoding="utf-8"))
    return data[key]


def _question(type_: str, case: dict[str, Any], **choice_field: Any) -> Any:
    key = "score" if type_ == "multiple-choice" else "correct"
    feedback = case.get("feedback", {})
    choices = [
        {
            "id": cid,
            "text": cid,
            **({} if value is None else {key: value}),
            **({"feedback": feedback[cid]} if cid in feedback else {}),
        }
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
    if expected == "malformed":
        with pytest.raises(ResponseError):
            question.score_response(response)
        return
    result = question.score_response(response)
    if isinstance(expected, dict):
        assert result.score == pytest.approx(_number(expected["score"]))
        assert result.feedback == expected["feedback"]
    else:
        assert result.score == pytest.approx(_number(expected))


def _ms_params() -> list[Any]:
    return [
        pytest.param(case, example, id=f"{case['grading']}/{case['name']}/{example['ticks']}")
        for case in _cases("multiple-selection")
        for example in case["examples"]
    ]


@pytest.mark.parametrize(("case", "example"), _ms_params())
def test_multiple_selection(case: dict[str, Any], example: dict[str, Any]) -> None:
    question = _question("multiple-selection", case)
    ticks = set(example["ticks"])
    if example["score"] == "malformed":
        with pytest.raises(ResponseError):
            question.score_response(ticks)
        return
    result = question.score_response(ticks)
    assert result.score == pytest.approx(_number(example["score"]))
    if "feedback" in example:
        assert result.feedback == example["feedback"]


def _tf_params() -> list[Any]:
    return [
        pytest.param(case, example, id=f"{case['grading']}/{case['name']}/{example['marks']}")
        for case in _cases("true-false")
        for example in case["examples"]
    ]


@pytest.mark.parametrize(("case", "example"), _tf_params())
def test_true_false(case: dict[str, Any], example: dict[str, Any]) -> None:
    question = _question("true-false", case)
    marks = {cid: None for cid in case["choices"]} | example["marks"]
    if example["score"] == "malformed":
        with pytest.raises(ResponseError):
            question.score_response(marks)
        return
    result = question.score_response(marks)
    assert result.score == pytest.approx(_number(example["score"]))
    if "feedback" in example:
        assert result.feedback == example["feedback"]


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
    result = question.score_response(example["response"])
    assert result.score == pytest.approx(_number(example["score"]))
    if "feedback" in example:
        assert (result.feedback[0] if result.feedback else None) == example["feedback"]
        assert len(result.feedback) <= 1


@pytest.mark.parametrize(("case", "example"), _binary_params("short-answer"))
def test_short_answer(case: dict[str, Any], example: dict[str, Any]) -> None:
    question = _binary_question("short-answer", case)
    if example["score"] == "malformed":
        with pytest.raises(ResponseError):
            question.score_response(example["response"])
        return
    if example["score"] == "pending":
        with pytest.raises(NotAutoGradable):
            question.score_response(example["response"])
        return
    result = question.score_response(example["response"])
    assert result.score == pytest.approx(_number(example["score"]))
    if "feedback" in example:
        assert (result.feedback[0] if result.feedback else None) == example["feedback"]
        assert len(result.feedback) <= 1


@pytest.mark.parametrize(("case", "example"), _binary_params("short-answer-prevalidation"))
def test_short_answer_prevalidation(case: dict[str, Any], example: dict[str, Any]) -> None:
    if "blank" in case:
        fill_in = _binary_question("fill-in", case)
        (question,) = [b for b in fill_in.blanks if b.id == case["blank"]]
    else:
        question = _binary_question("short-answer", case)
    assert question.prevalidate(example["response"]) == (
        example["valid"],
        example["feedback"],
    )


_STRATEGIES = ("partial", "no-mistakes", "all-or-nothing", "symmetric")


def _fill_in_params() -> list[Any]:
    params = []
    for case in _cases("fill-in"):
        for example in case["examples"]:
            expected = example.get("scores") or {s: example["score"] for s in _STRATEGIES}
            for strategy, score in expected.items():
                params.append(
                    pytest.param(
                        case,
                        example,
                        strategy,
                        score,
                        id=f"{strategy}/{case['name']}/{example['response']!r}",
                    )
                )
    return params


@pytest.mark.parametrize(("case", "example", "strategy", "expected"), _fill_in_params())
def test_fill_in(case: dict[str, Any], example: dict[str, Any], strategy: str, expected: Any) -> None:
    doc = {"type": "fill-in", "grading": strategy, **case["question"]}
    loaded = mdq.load(doc, kind="question")
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    question = loaded.document
    if expected == "malformed":
        with pytest.raises(ResponseError):
            question.score_response(example["response"])
        return
    if expected == "pending":
        with pytest.raises(NotAutoGradable):
            question.score_response(example["response"])
        # A pending response shows no feedback (responses.md, "Pending").
        assert example.get("feedback", []) == []
        return
    result = question.score_response(example["response"])
    assert result.score == pytest.approx(_number(expected))
    if "feedback" in example:
        assert result.feedback == example["feedback"]


def test_every_grading_file_is_covered() -> None:
    names = sorted(p.stem for p in GRADING_ROOT.glob("*.yaml"))
    assert names == [
        "automation",
        "essay",
        "exam",
        "fill-in",
        "multiple-choice",
        "multiple-selection",
        "numeric",
        "ordering",
        "short-answer",
        "short-answer-prevalidation",
        "true-false",
    ]


@pytest.mark.parametrize(("case", "example"), _binary_params("ordering"))
def test_ordering(case: dict[str, Any], example: dict[str, Any]) -> None:
    question = _binary_question("ordering", case)
    if example["score"] == "malformed":
        with pytest.raises(ResponseError):
            question.score_response(example["response"])
        return
    if example["score"] == "pending":
        with pytest.raises(NotAutoGradable):
            question.score_response(example["response"])
        return
    result = question.score_response(example["response"])
    assert result.score == pytest.approx(_number(example["score"]))
    if "feedback" in example:
        assert (result.feedback[0] if result.feedback else None) == example["feedback"]


@pytest.mark.parametrize(("case", "example"), _binary_params("essay"))
def test_essay(case: dict[str, Any], example: dict[str, Any]) -> None:
    question = _binary_question("essay", case)
    expected = example["score"]
    with pytest.raises(NotAutoGradable if expected == "pending" else ResponseError):
        question.score_response(example["response"])


def _automation_params() -> list[Any]:
    return [pytest.param(case, id=case["name"]) for case in _cases("automation")]


@pytest.mark.parametrize("case", _automation_params())
def test_automation(case: dict[str, Any]) -> None:
    loaded = mdq.load(case["question"], kind="question")
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    question = loaded.document
    assert question.automation == case["automation"]
    if "unmatched" in case:
        assert question.effective_unmatched == case["unmatched"]
    for blank in question.blanks if "blanks" in case else []:
        expected = case["blanks"][blank.id]
        assert blank.effective_unmatched(question.unmatched) == expected["unmatched"]
        assert blank.automation(question.unmatched) == expected["automation"]


def _load_exam(case: dict[str, Any]) -> Any:
    if "source" in case:
        source = EXAMPLES_ROOT / case["source"]
        loaded = mdq.load(source, kind="exam")
    else:
        doc = {"type": "exam", "title": "Prova", **case["exam"]}
        loaded = mdq.load(doc, kind="exam")
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    return loaded.document


def _exam_cases(*keys: str) -> list[Any]:
    return [
        pytest.param(case, id=case["name"])
        for case in _cases("exam", "cases")
        if any(key in case for key in keys)
    ]


@pytest.mark.parametrize("case", [c for c in _exam_cases("effective") if "question" in c.values[0]])
def test_effective_values_of_a_question(case: dict[str, Any]) -> None:
    doc = {**case["question"], **case.get("override", {})}
    loaded = mdq.load(doc, kind="question")
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    expected = case["effective"]
    assert loaded.document.effective_grading() == expected["grading"]
    assert loaded.document.effective_shuffle() is expected["shuffle"]


@pytest.mark.parametrize("case", [c for c in _exam_cases("effective") if "question" not in c.values[0]])
def test_effective_values_in_an_exam(case: dict[str, Any]) -> None:
    exam = _load_exam(case)
    by_id = {q.id: q for q in exam.questions}
    for qid, expected in case["effective"].items():
        question = by_id[qid]
        resolved = exam.resolve_question(question)
        if "grading" in expected:
            assert exam.grading_for(question) == expected["grading"]
            assert resolved.grading == expected["grading"]
        if "shuffle" in expected:
            assert exam.shuffle_for(question) is expected["shuffle"]
            assert resolved.shuffle is expected["shuffle"]


def _exam_example_params() -> list[Any]:
    return [
        pytest.param(case, example, id=f"{case['name']}/{index}")
        for case in _cases("exam", "cases")
        for index, example in enumerate(case.get("examples", []))
    ]


@pytest.mark.parametrize(("case", "example"), _exam_example_params())
def test_exam_score(case: dict[str, Any], example: dict[str, Any]) -> None:
    exam = _load_exam(case)
    if example["score"] == "malformed":
        with pytest.raises(ResponseError):
            exam.score_responses(example["responses"])
        return
    result = exam.score_responses(example["responses"])
    if example["score"] == "pending":
        assert result.score is None
    else:
        assert result.score == pytest.approx(example["score"])
    for key in ("provisional", "total_weight"):
        if key in example:
            assert getattr(result, key) == pytest.approx(example[key])
    if "penalty" in example:
        assert result.penalty == example["penalty"]
    for key in ("skipped", "pending"):
        if key in example:
            assert list(getattr(result, key)) == example[key]
    if "questions" in example:
        scores = {
            qid: None if question is None else question.score
            for qid, question in result.questions.items()
        }
        assert scores == pytest.approx(example["questions"])

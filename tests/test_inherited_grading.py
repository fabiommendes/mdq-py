"""
exam.md, "Inheritance" and "Grading": the `render()` of `grading` and
`shuffle`, and `Exam.resolve_question`. The values after inheritance and
the scoring with an inherited strategy are in `examples/grading/exam.yaml`;
the parsing of `inherit` and of the exam `grading` is in the example pairs
and `examples/invalid/`.
"""

from __future__ import annotations

from typing import Any

import mdq
from mdq import models

MC = {
    "type": "multiple-choice",
    "stem": "Qual?",
    "choices": [
        {"id": "a", "text": "certa", "score": 1},
        {"id": "b", "text": "errada"},
    ],
}


def _load(doc: dict[str, Any], **fields: Any) -> Any:
    loaded = mdq.load({**doc, **fields}, kind="question")
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    return loaded.document


def _exam(*questions: dict[str, Any], **fields: Any) -> models.Exam:
    qs = [{"id": f"q{i}", **q} for i, q in enumerate(questions, 1)]
    loaded = mdq.load({"type": "exam", "title": "Prova", "questions": qs, **fields}, kind="exam")
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    return loaded.document


def test_inherit_is_not_written_out() -> None:
    question = _load(MC, grading="inherit", shuffle="inherit")
    assert "grading" not in question.frontmatter()
    assert "shuffle" not in question.frontmatter()
    assert "grading" not in question.render()
    assert "shuffle" not in question.render()


def test_resolve_returns_a_copy() -> None:
    exam = _exam(MC, grading="partial", shuffle=True)
    (question,) = exam.questions
    exam.resolve_question(question)
    assert question.grading == "inherit"  # the original is untouched


def test_resolve_leaves_a_question_without_grading_alone() -> None:
    essay = {"type": "essay", "stem": "Disserte."}
    exam = _exam(essay, grading="partial")
    (question,) = exam.questions
    assert exam.resolve_question(question) == question

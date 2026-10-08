"""
exam.md, "Inheritance" and "Grading": `grading` and `shuffle` of a
question default to `"inherit"`. Inside an exam, `inherit` takes the
exam's value (`grading` may be a mapping by question type); outside,
it is `symmetric` and `false`. The exam's `shuffle` defaults to false.
"""

from __future__ import annotations

from typing import Any

import pytest
from _corpus import EXAMPLES_ROOT

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
MS = {
    "type": "multiple-selection",
    "stem": "Quais?",
    "choices": [
        {"id": "a", "text": "certa", "correct": True},
        {"id": "b", "text": "errada", "correct": False},
    ],
}
TF = {
    "type": "true-false",
    "stem": "Julgue.",
    "choices": [
        {"id": "a", "text": "verdade", "correct": True},
        {"id": "b", "text": "mentira", "correct": False},
    ],
}
FILL_IN = {
    "type": "fill-in",
    "stem": "A capital é [^x] e o rio é [^y].",
    "blanks": [
        {"id": "x", "type": "short-answer", "accept": ["Brasília"]},
        {"id": "y", "type": "short-answer", "accept": ["Amazonas"]},
    ],
}
GRADED = [MC, MS, TF, FILL_IN]


def _load(doc: dict[str, Any], **fields: Any) -> Any:
    loaded = mdq.load({**doc, **fields}, kind="question")
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    return loaded.document


def _exam(*questions: dict[str, Any], **fields: Any) -> models.Exam:
    qs = [{"id": f"q{i}", **q} for i, q in enumerate(questions, 1)]
    loaded = mdq.load({"type": "exam", "title": "Prova", "questions": qs, **fields}, kind="exam")
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    return loaded.document


#
# AC1: defaults and resolution outside an exam
#
@pytest.mark.parametrize("doc", GRADED, ids=[d["type"] for d in GRADED])
def test_grading_and_shuffle_default_to_inherit(doc: dict[str, Any]) -> None:
    question = _load(doc)
    assert question.grading == "inherit"
    assert question.shuffle == "inherit"
    assert question.effective_grading() == "symmetric"
    assert question.effective_shuffle() is False


@pytest.mark.parametrize("doc", GRADED, ids=[d["type"] for d in GRADED])
def test_explicit_inherit_is_accepted(doc: dict[str, Any]) -> None:
    question = _load(doc, grading="inherit", shuffle="inherit")
    assert question.grading == "inherit"
    assert question.shuffle == "inherit"


@pytest.mark.parametrize("doc", GRADED, ids=[d["type"] for d in GRADED])
def test_own_values_resolve_to_themselves(doc: dict[str, Any]) -> None:
    question = _load(doc, grading="partial", shuffle=True)
    assert question.effective_grading() == "partial"
    assert question.effective_shuffle() is True


def test_inherit_is_not_written_out() -> None:
    question = _load(MC, grading="inherit", shuffle="inherit")
    assert "grading" not in question.frontmatter()
    assert "shuffle" not in question.frontmatter()
    assert "grading" not in question.render()
    assert "shuffle" not in question.render()


def test_own_values_are_written_out() -> None:
    question = _load(MC, grading="partial", shuffle=False)
    assert question.frontmatter()["grading"] == "partial"
    assert question.frontmatter()["shuffle"] is False


def test_markdown_frontmatter_accepts_inherit() -> None:
    loaded = mdq.load(
        "---\ngrading: inherit\nshuffle: inherit\n---\n\nQual?\n\n* [*] a\n* [ ] b\n",
        kind="question",
    )
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    assert loaded.document.grading == "inherit"
    assert loaded.document.shuffle == "inherit"


def test_unknown_grading_is_a_schema_error() -> None:
    loaded = mdq.load({**MC, "grading": "random"}, kind="question")
    assert "schema-error" in [d.code for d in loaded.diagnostics]


def test_exam_grading_does_not_accept_inherit() -> None:
    loaded = mdq.load(
        {"type": "exam", "title": "Prova", "grading": "inherit", "questions": [MC]},
        kind="exam",
    )
    assert "schema-error" in [d.code for d in loaded.diagnostics]


#
# AC2: resolution inside an exam
#
def test_exam_shuffle_defaults_to_false() -> None:
    assert _exam(MC).shuffle is False


def test_exam_values_apply_to_inherit() -> None:
    exam = _exam(MC, grading="partial", shuffle=True)
    (question,) = exam.questions
    assert exam.grading_for(question) == "partial"
    assert exam.shuffle_for(question) is True


def test_exam_defaults_apply_to_inherit() -> None:
    exam = _exam(MC)
    (question,) = exam.questions
    assert exam.grading_for(question) == "symmetric"
    assert exam.shuffle_for(question) is False


def test_own_values_beat_the_exam() -> None:
    exam = _exam({**MC, "grading": "all-or-nothing", "shuffle": False}, grading="partial", shuffle=True)
    (question,) = exam.questions
    assert exam.grading_for(question) == "all-or-nothing"
    assert exam.shuffle_for(question) is False


def test_exam_grading_mapping_resolves_by_type() -> None:
    exam = _exam(MC, MS, TF, FILL_IN, grading={"multiple-choice": "partial", "true-false": "all-or-nothing"})
    mc, ms, tf, fill = exam.questions
    assert exam.grading_for(mc) == "partial"
    assert exam.grading_for(ms) == "symmetric"
    assert exam.grading_for(tf) == "all-or-nothing"
    assert exam.grading_for(fill) == "symmetric"


def test_resolve_returns_a_copy_with_effective_values() -> None:
    exam = _exam(MC, grading="partial", shuffle=True)
    (question,) = exam.questions
    resolved = exam.resolve_question(question)
    assert resolved.grading == "partial"
    assert resolved.shuffle is True
    assert question.grading == "inherit"  # the original is untouched


def test_resolve_leaves_a_question_without_grading_alone() -> None:
    essay = {"type": "essay", "stem": "Disserte."}
    exam = _exam(essay, grading="partial")
    (question,) = exam.questions
    assert exam.resolve_question(question) == question


#
# AC3: scoring inside an exam uses the inherited strategy
#
def test_inherited_partial_grading_gives_zero_for_a_wrong_pick() -> None:
    symmetric = _exam(MC).score_responses({"q1": "b"})
    partial = _exam(MC, grading="partial").score_responses({"q1": "b"})
    assert symmetric.questions["q1"].score == -1.0
    assert partial.questions["q1"].score == 0.0


def test_inherited_mapping_applies_per_type() -> None:
    exam = _exam(MC, MS, grading={"multiple-choice": "partial"})
    result = exam.score_responses({"q1": "b", "q2": ["a", "b"]})
    assert result.questions["q1"].score == 0.0
    # multiple-selection keeps symmetric: one right, one wrong -> 0
    assert result.questions["q2"].score == 0.0


def test_own_grading_wins_when_scoring() -> None:
    exam = _exam({**MC, "grading": "symmetric"}, grading="partial")
    assert exam.score_responses({"q1": "b"}).questions["q1"].score == -1.0


def test_corpus_inherited_grading_example() -> None:
    source = EXAMPLES_ROOT / "valid" / "exam" / "inherited-grading.mdq.md"
    exam = mdq.load(source, kind="exam").document
    assert exam.shuffle is True
    cerrado, pantanal = exam.questions
    assert cerrado.grading == "inherit" and cerrado.shuffle == "inherit"
    assert exam.grading_for(cerrado) == "partial" and exam.shuffle_for(cerrado) is True
    assert pantanal.grading == "symmetric" and pantanal.shuffle is False
    result = exam.score_responses({"cerrado": "caatinga", "pantanal": "amazon"})
    assert result.questions["cerrado"].score == 0.0
    assert result.questions["pantanal"].score == -0.5

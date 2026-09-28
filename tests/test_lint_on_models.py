"""
Tests for the `lint()` contract of `dev/specs/to-do/lint-on-models.md`
(candidate C2 of `dev/architecture-review.md`).

Every question class and `Exam` get `lint(self) -> list[Diagnostic]`:

* `BaseQuestion.lint()` runs the rules common to all questions, and each
  subclass's `lint()` adds its own on top (via `super().lint()`).
* `Exam.lint()` runs the exam-level rules, then calls `lint()` on each
  question and prepends `("questions", i)` to every diagnostic path.
* Calling `lint()` directly on a model returns the same diagnostics as
  `load()` returns for the equivalent document -- `load` no longer runs
  its own per-question lint loop, it just calls `document.lint()`.

Only *warning*/*info* rules are exercised here: the seven rules that
become model errors (`dev/specs/to-do/lint-on-models.md`, "New errors")
stop a bad document from ever becoming a model in the first place, so
there is no instance to call `.lint()` on for those -- see
`tests/test_model_rule_errors.py`.

Fixtures use Brazil-themed questions, per AGENTS.md. Written against the
public `mdq.load` API and the models' own `lint()` method -- no
`mdq.models._lint` internals.
"""

from __future__ import annotations

from mdq import Diagnostic, Exam, Question, load


def _codes(diagnostics: list[Diagnostic]) -> set[str]:
    return {d.code for d in diagnostics}


def _load_question(doc: dict) -> Question:
    loaded = load(doc, kind="question")
    assert loaded.document is not None, loaded.diagnostics
    return loaded.document


def _load_exam(doc: dict) -> Exam:
    loaded = load(doc, kind="exam")
    assert loaded.document is not None, loaded.diagnostics
    return loaded.document


# ---------------------------------------------------------------------
# lint() exists on every question type and returns a list[Diagnostic]
# ---------------------------------------------------------------------


def test_question_lint_returns_a_list_of_diagnostics() -> None:
    doc = {
        "type": "essay",
        "stem": "Descreva o bioma da Caatinga.",
        "input": "text",
    }
    question = _load_question(doc)
    result = question.lint()
    assert isinstance(result, list)
    assert all(isinstance(d, Diagnostic) for d in result)


def test_exam_lint_returns_a_list_of_diagnostics() -> None:
    doc = {
        "type": "exam",
        "title": "Prova de Geografia do Brasil",
        "questions": [
            {"id": "q1", "type": "essay", "stem": "Descreva o Pantanal.", "input": "text"},
        ],
    }
    exam = _load_exam(doc)
    result = exam.lint()
    assert isinstance(result, list)
    assert all(isinstance(d, Diagnostic) for d in result)


# ---------------------------------------------------------------------
# lint() on a model matches what load() reports for the same document
# ---------------------------------------------------------------------


def test_multiple_choice_lint_matches_load_diagnostics() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": [
            {"id": "a", "text": "Rio de Janeiro", "score": 0},
            {"id": "b", "text": "Brasília", "score": 0},
        ],
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert loaded.document.lint() == loaded.diagnostics
    assert "multiple-choice-no-correct-choice" in _codes(loaded.document.lint())


def test_essay_lint_matches_load_diagnostics_for_ignored_highlight() -> None:
    doc = {
        "type": "essay",
        "stem": "Descreva o bioma do Cerrado.",
        "input": "text",
        "highlight": "python",
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert loaded.document.lint() == loaded.diagnostics
    assert "ignored-highlight" in _codes(loaded.document.lint())


def test_true_false_lint_matches_load_diagnostics_for_provisional_marker() -> None:
    doc = {
        "type": "true-false",
        "stem": "Julgue as afirmações sobre o Brasil.",
        "choices": [
            {
                "id": "a",
                "text": "O Rio Amazonas é o maior rio do mundo em volume de água.",
                "correct": True,
                "marker": "Q",
            },
            {"id": "b", "text": "Brasília fica no litoral.", "correct": False, "marker": "F"},
        ],
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert loaded.document.lint() == loaded.diagnostics
    assert "provisional-true-false-marker" in _codes(loaded.document.lint())


def test_ordering_lint_matches_load_diagnostics_for_reject_without_feedback() -> None:
    doc = {
        "type": "ordering",
        "stem": "Ordene as etapas da fotossíntese.",
        "lines": [[0, "Absorção de luz"], [0, "Produção de glicose"]],
        "reject": [{"lines": [[0, "Produção de glicose"], [0, "Absorção de luz"]]}],
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert loaded.document.lint() == loaded.diagnostics
    assert "reject-without-feedback" in _codes(loaded.document.lint())


def test_fill_in_lint_matches_load_diagnostics() -> None:
    doc = {
        "type": "fill-in",
        "stem": "O maior bioma brasileiro é a [^bioma].",
        "blanks": [
            {
                "id": "bioma",
                "type": "multiple-choice",
                "choices": [
                    {"id": "a", "text": " ", "score": 1},
                    {"id": "b", "text": "Cerrado", "score": 0},
                ],
            },
        ],
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert loaded.document.lint() == loaded.diagnostics
    assert "blank-choice-text" in _codes(loaded.document.lint())


# ---------------------------------------------------------------------
# BaseQuestion.lint() rules run for every subclass, via super().lint()
# ---------------------------------------------------------------------


def test_common_rule_runs_regardless_of_question_type() -> None:
    """
    `blank-tag` (a common `BaseQuestion.lint()` rule) fires for a
    numeric question exactly as it would for any other type -- there is
    nothing numeric-specific about it.
    """
    doc = {
        "type": "numeric",
        "stem": "Quantos estados tem o Brasil?",
        "answer": 26,
        "tags": ["geografia", "  "],
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert "blank-tag" in _codes(loaded.document.lint())
    assert loaded.document.lint() == loaded.diagnostics


# ---------------------------------------------------------------------
# Exam.lint(): exam-level rules, plus each question's diagnostics
# prefixed with ("questions", i)
# ---------------------------------------------------------------------


def test_exam_lint_prefixes_question_diagnostics_with_questions_index() -> None:
    doc = {
        "type": "exam",
        "title": "Prova de Biologia",
        "questions": [
            {
                "id": "q1",
                "title": "Fotossíntese",
                "type": "essay",
                "stem": "Descreva a fotossíntese.",
                "input": "text",
                "answerKey": "Processo de conversão de luz em energia química nas plantas.",
            },
            {
                "id": "q2",
                "type": "multiple-choice",
                "stem": "Qual é o maior bioma do Brasil?",
                "choices": [
                    {"id": "a", "text": "Amazônia", "score": 0},
                    {"id": "b", "text": "Cerrado", "score": 0},
                ],
            },
        ],
    }
    exam = _load_exam(doc)
    diagnostics = exam.lint()

    matching = [d for d in diagnostics if d.code == "multiple-choice-no-correct-choice"]
    assert len(matching) == 1
    assert matching[0].path == ("questions", 1, "choices")

    # The first question's own lint() is empty, so it contributes
    # nothing -- but it must not be skipped or mis-indexed either.
    assert exam.questions[0].lint() == []


def test_exam_lint_matches_load_diagnostics() -> None:
    doc = {
        "type": "exam",
        "title": "Prova de Biologia",
        "questions": [
            {
                "id": "q1",
                "type": "multiple-choice",
                "stem": "Qual é o maior bioma do Brasil?",
                "choices": [
                    {"id": "a", "text": "Amazônia", "score": 0},
                    {"id": "b", "text": "Cerrado", "score": 0},
                ],
            },
        ],
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert loaded.document.lint() == loaded.diagnostics


def test_exam_without_questions_warns_at_the_exam_level() -> None:
    doc = {"type": "exam", "title": "Prova vazia", "questions": []}
    exam = _load_exam(doc)
    diagnostics = exam.lint()
    matching = [d for d in diagnostics if d.code == "exam-without-questions"]
    assert len(matching) == 1
    assert matching[0].path == ("questions",)


def test_exam_with_questions_does_not_warn_exam_without_questions() -> None:
    doc = {
        "type": "exam",
        "title": "Prova de Biologia",
        "questions": [
            {"id": "q1", "type": "essay", "stem": "Descreva a fotossíntese.", "input": "text"},
        ],
    }
    exam = _load_exam(doc)
    assert "exam-without-questions" not in _codes(exam.lint())

"""
Tests for the `lint()` contract of the models.

`lint()` on a model returns the same diagnostics as `load()` returns for the
equivalent document, and `Exam.lint()` prefixes the path of each question
diagnostic with `("questions", i)`.

Which rules fire for which document is covered by the example corpus
(`examples/**/*.lint.json`).
"""

from __future__ import annotations

from mdq import Diagnostic, load


def test_question_lint_matches_load_diagnostics() -> None:
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
    result = loaded.document.lint()
    assert all(isinstance(d, Diagnostic) for d in result)
    assert result == loaded.diagnostics
    assert "no-correct-choice" in {d.code for d in result}


def test_exam_lint_matches_load_and_prefixes_question_paths() -> None:
    doc = {
        "type": "exam",
        "title": "Prova de Biologia",
        "questions": [
            {
                "id": "q1",
                "type": "essay",
                "stem": "Descreva a fotossíntese.",
                "content": "text",
                "answerKey": "Conversão de luz em energia química nas plantas.",
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
    loaded = load(doc, kind="exam")
    assert loaded.document is not None
    assert loaded.document.lint() == loaded.diagnostics
    [matching] = [d for d in loaded.document.lint() if d.code == "no-correct-choice"]
    assert matching.path == ("questions", 1, "choices")

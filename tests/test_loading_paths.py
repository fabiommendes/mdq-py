"""
Diagnostic paths from pydantic errors, and the empty stem.

Regressions from the review of `dev/specs/to-do/lint-on-models.md`:
pydantic adds the `type` tag of a discriminated union member to an
error's `loc`. `load` removes that tag, but must keep real keys that look
like a tag, such as the question types used as keys of an exam's
`grading`.
"""

from __future__ import annotations

from mdq import load


def test_exam_grading_key_named_like_a_question_type_stays_in_the_path() -> None:
    loaded = load(
        {
            "type": "exam",
            "title": "Prova de Geografia",
            "grading": {"multiple-choice": "bogus-strategy"},
            "questions": [],
        },
        kind="exam",
    )
    assert loaded.document is None
    # Pydantic also adds the name of the plain (not discriminated) union
    # member to the path; only the key matters here.
    paths = [d.path for d in loaded.diagnostics]
    assert any(p[0] == "grading" and p[-1] == "multiple-choice" for p in paths)


def test_question_error_path_has_no_type_tag() -> None:
    loaded = load(
        {
            "type": "multiple-choice",
            "stem": "Qual é a capital do Brasil?",
            "choices": [
                {"id": "a", "text": "Brasília", "score": 1},
                {"id": "a", "text": "Salvador", "score": 0},
            ],
        },
        kind="question",
    )
    assert loaded.document is None
    paths = [d.path for d in loaded.diagnostics if d.code == "duplicate-choice-id"]
    assert paths == [("choices", 1, "id")]


def test_blank_error_path_has_no_blank_type_tag() -> None:
    loaded = load(
        {
            "type": "fill-in",
            "stem": "A capital do Brasil é [^capital].",
            "blanks": [
                {
                    "id": "capital",
                    "type": "multiple-choice",
                    "choices": [
                        {"id": "a", "text": "Brasília", "score": 1},
                        {"id": "a", "text": "Salvador", "score": 0},
                    ],
                }
            ],
        },
        kind="question",
    )
    assert loaded.document is None
    paths = [d.path for d in loaded.diagnostics if d.code == "duplicate-choice-id"]
    assert paths == [("blanks", 0, "choices", 1, "id")]


def test_empty_stem_is_an_error() -> None:
    loaded = load(
        {
            "type": "true-false",
            "stem": "",
            "choices": [
                {"text": "O Cerrado é uma savana.", "correct": True},
                {"text": "O Pantanal fica no Amazonas.", "correct": False},
            ],
        },
        kind="question",
    )
    assert loaded.document is None
    assert [(d.code, d.path) for d in loaded.diagnostics] == [("blank-text-field", ("stem",))]

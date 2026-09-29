"""
Lint rules a fill-in blank inherits from the question type it declares
(fill-in.md, "Additional Rules"), and the numeric rules applied to an
`answer` written as a string.

Written against the public `mdq.load` API and the models' `lint()`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mdq import Diagnostic, load
from mdq.models import FillInQuestion, NumericQuestion


def _diagnostics(doc: dict, code: str) -> list[Diagnostic]:
    loaded = load(doc, kind="question")
    assert loaded.document is not None, loaded.diagnostics
    return [d for d in loaded.diagnostics if d.code == code]


def _choice_blank_doc(*choices: dict) -> dict:
    return {
        "type": "fill-in",
        "id": "capital",
        "title": "Capital",
        "stem": "A capital do Brasil é [^capital].",
        "blanks": [
            {
                "id": "capital",
                "type": "multiple-choice",
                "choices": list(choices),
            }
        ],
    }


# ---------------------------------------------------------------------
# choice blanks: the multiple-choice choice rules
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field_name", "code"),
    [("feedback", "blank-choice-feedback"), ("comment", "blank-choice-comment")],
)
def test_choice_blank_with_a_blank_choice_text_field_warns(field_name: str, code: str) -> None:
    doc = _choice_blank_doc(
        {"id": "brasilia", "text": "Brasília", "score": 1},
        {"id": "salvador", "text": "Salvador", field_name: "  \n "},
    )
    found = _diagnostics(doc, code)
    assert [d.path for d in found] == [("blanks", 0, "choices", 1, field_name)]
    assert found[0].severity == "warning"


def test_choice_blank_with_visible_feedback_and_comment_does_not_warn() -> None:
    doc = _choice_blank_doc(
        {"id": "brasilia", "text": "Brasília", "score": 1, "feedback": "Isso."},
        {"id": "salvador", "text": "Salvador", "comment": "Capital até 1763."},
    )
    assert _diagnostics(doc, "blank-choice-feedback") == []
    assert _diagnostics(doc, "blank-choice-comment") == []


def test_choice_blank_choice_without_id_is_reported() -> None:
    doc = _choice_blank_doc(
        {"id": "brasilia", "text": "Brasília", "score": 1},
        {"text": "Salvador"},
    )
    found = _diagnostics(doc, "missing-choice-id")
    assert [d.path for d in found] == [("blanks", 0, "choices", 1, "id")]
    assert found[0].severity == "info"


def test_choice_blank_choices_with_ids_are_not_reported() -> None:
    doc = _choice_blank_doc(
        {"id": "brasilia", "text": "Brasília", "score": 1},
        {"id": "salvador", "text": "Salvador"},
    )
    assert _diagnostics(doc, "missing-choice-id") == []


def test_choice_blank_visually_identical_choices_are_reported() -> None:
    doc = _choice_blank_doc(
        {"id": "brasilia", "text": "Brasília", "score": 1},
        {"id": "salvador", "text": "*Salvador*"},
        {"id": "salvador-2", "text": "_Salvador_"},
    )
    found = _diagnostics(doc, "visually-identical-choices")
    assert [d.path for d in found] == [("blanks", 0, "choices", 2, "text")]
    assert found[0].severity == "info"


def test_choice_blank_rules_apply_to_the_second_blank_path() -> None:
    doc = {
        "type": "fill-in",
        "id": "biomas",
        "title": "Biomas",
        "stem": "O [^a] e o [^b] são biomas brasileiros.",
        "blanks": [
            {"id": "a", "type": "short-answer", "oneOf": ["Cerrado"]},
            {
                "id": "b",
                "type": "multiple-choice",
                "choices": [
                    {"id": "caatinga", "text": "Caatinga", "score": 1},
                    {"text": "Tundra"},
                ],
            },
        ],
    }
    found = _diagnostics(doc, "missing-choice-id")
    assert [d.path for d in found] == [("blanks", 1, "choices", 1, "id")]


def test_fill_in_model_lint_matches_load() -> None:
    doc = _choice_blank_doc(
        {"id": "brasilia", "text": "Brasília", "score": 1, "feedback": " "},
        {"text": "Salvador"},
    )
    loaded = load(doc, kind="question")
    assert isinstance(loaded.document, FillInQuestion)
    assert {d.code for d in loaded.document.lint()} >= {
        "blank-choice-feedback",
        "missing-choice-id",
    }


# ---------------------------------------------------------------------
# numeric: an `answer` written as a string
# ---------------------------------------------------------------------


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


@pytest.mark.parametrize("answer", ["3/2", "2.5", "-7/4"])
def test_string_answer_that_is_not_whole_is_outside_the_integer_domain(answer: str) -> None:
    doc = _numeric_doc(answer=answer, domain="integer")
    found = _diagnostics(doc, "answer-outside-domain")
    assert [d.path for d in found] == [("answer",)]
    assert found[0].severity == "warning"


@pytest.mark.parametrize("answer", ["5", "10/2", "5.0"])
def test_string_answer_that_is_whole_is_inside_the_integer_domain(answer: str) -> None:
    doc = _numeric_doc(answer=answer, domain="integer")
    assert _diagnostics(doc, "answer-outside-domain") == []


def test_numeric_blank_string_answer_outside_the_integer_domain_warns() -> None:
    doc = _numeric_blank_doc(answer="11/2", domain="integer")
    found = _diagnostics(doc, "answer-outside-domain")
    assert [d.path for d in found] == [("blanks", 0, "answer")]


@pytest.mark.parametrize("answer", ["0", "-0", "0/7", "0.0"])
def test_relative_tolerance_around_a_string_zero_answer_warns(answer: str) -> None:
    doc = _numeric_doc(answer=answer, tolerance={"relative": 0.05})
    found = _diagnostics(doc, "relative-tolerance-around-zero")
    assert [d.path for d in found] == [("tolerance", "relative")]


def test_relative_tolerance_around_a_nonzero_string_answer_does_not_warn() -> None:
    doc = _numeric_doc(answer="1/3", tolerance={"relative": 0.05})
    assert _diagnostics(doc, "relative-tolerance-around-zero") == []


def test_numeric_blank_relative_tolerance_around_a_string_zero_warns() -> None:
    doc = _numeric_blank_doc(answer="0", tolerance={"relative": 0.1})
    found = _diagnostics(doc, "relative-tolerance-around-zero")
    assert [d.path for d in found] == [("blanks", 0, "tolerance", "relative")]


# ---------------------------------------------------------------------
# numeric: `unit` follows numeric.md, "Unit conversion"
# ---------------------------------------------------------------------

_INVALID_UNITS = ["", "m s", "km\th", "(kg)", "kg)", "[m]", "m]", " m"]
_VALID_UNITS = ["m", "µm", "°C", "km/h", "Ω", "m²", "R$"]


@pytest.mark.parametrize("unit", _INVALID_UNITS)
def test_numeric_question_rejects_a_malformed_unit(unit: str) -> None:
    with pytest.raises(ValidationError):
        NumericQuestion(stem="Qual a altura do Pico da Neblina?", answer=2995, unit=unit)


@pytest.mark.parametrize("unit", _VALID_UNITS)
def test_numeric_question_accepts_a_well_formed_unit(unit: str) -> None:
    question = NumericQuestion(stem="Qual a altura do Pico da Neblina?", answer=2995, unit=unit)
    assert question.unit == unit


@pytest.mark.parametrize("unit", _INVALID_UNITS)
def test_load_reports_a_malformed_unit(unit: str) -> None:
    loaded = load(_numeric_doc(answer=9, unit=unit), kind="question")
    assert loaded.document is None
    assert [d.path for d in loaded.diagnostics if d.severity == "error"] == [("unit",)]


@pytest.mark.parametrize("unit", _INVALID_UNITS)
def test_load_reports_a_malformed_numeric_blank_unit(unit: str) -> None:
    loaded = load(_numeric_blank_doc(answer=9, unit=unit), kind="question")
    assert loaded.document is None
    assert [d.path for d in loaded.diagnostics if d.severity == "error"] == [
        ("blanks", 0, "unit")
    ]


@pytest.mark.parametrize("unit", _VALID_UNITS)
def test_load_accepts_a_well_formed_numeric_blank_unit(unit: str) -> None:
    loaded = load(_numeric_blank_doc(answer=9, unit=unit), kind="question")
    assert loaded.document is not None, loaded.diagnostics

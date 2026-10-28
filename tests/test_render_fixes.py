"""
Render fixes: non-ASCII frontmatter, whole absolute tolerances, `str()` of
a model that is not a question.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _corpus import EXAMPLES_ROOT
from mdq import load, models, parse


def test_frontmatter_keeps_non_ascii_text() -> None:
    question = models.EssayQuestion.model_validate(
        {
            "type": "essay",
            "id": "ciclo",
            "title": "Ciclo da água",
            "stem": "Explique o ciclo.",
        }
    )
    text = question.render()
    assert "title: Ciclo da água" in text
    assert "\\x" not in text
    assert parse(text).title == "Ciclo da água"


@pytest.mark.parametrize(
    "title", ["Ilha\xa0", "0\xa0", "Rio\u2028Negro", "Sertão\u3000"]
)
def test_frontmatter_quotes_non_ascii_spaces(title: str) -> None:
    question = models.MultipleChoiceQuestion.model_validate(
        {
            "type": "multiple-choice",
            "title": title,
            "stem": "Qual?",
            "choices": [{"text": "a", "score": 1.0}, {"text": "b"}],
        }
    )
    assert parse(question.render()).title == title
    exam = models.Exam.model_validate(
        {"type": "exam", "questions": [question.to_dict()]}
    )
    assert parse(exam.render(), kind="exam", format="mdq").to_dict() == exam.to_dict()


def test_whole_absolute_tolerance_renders_without_decimal_point() -> None:
    question = models.NumericQuestion.model_validate(
        {
            "type": "numeric",
            "stem": "Quanto?",
            "answer": 6,
            "tolerance": {"absolute": 1},
        }
    )
    assert "[numeric]: 6 +- 1\n" in question.render() + "\n"
    assert "1.0" not in question.render()


def test_decimal_absolute_tolerance_keeps_its_point() -> None:
    question = models.NumericQuestion.model_validate(
        {
            "type": "numeric",
            "stem": "Quanto?",
            "answer": 6,
            "tolerance": {"absolute": 0.5},
        }
    )
    assert "[numeric]: 6 +- 0.5" in question.render()


def test_fill_in_numeric_blank_round_trips() -> None:
    path: Path = EXAMPLES_ROOT / "valid" / "fill-in" / "unmatched-manual.yaml"
    loaded = load(path.read_text(encoding="utf-8"), format="yaml").document
    assert loaded is not None
    text = loaded.render()
    assert "[^length/numeric]: 6 +- 1\n" in text + "\n"
    again = load(text).document
    assert again is not None
    assert again.to_dict() == loaded.to_dict()


def test_str_of_a_model_that_is_not_a_question() -> None:
    tolerance = models.Tolerance(absolute=1)
    assert str(tolerance) == "absolute=1.0 relative=None"

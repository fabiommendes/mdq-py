"""
Moodle's grade list and numeric answers, in the Moodle XML and GIFT
converters.

Moodle accepts only the grades in `question_bank::fraction_options_full()`
(question/engine/bank.php): 0, +-1, and +-p/q for 9/10, 5/6, 4/5, 3/4,
7/10, 2/3, 3/5, 1/2, 2/5, 1/3, 3/10, 1/4, 1/5, 1/6, 1/7, 1/8, 1/9, 1/10,
1/20. The Moodle XML and GIFT importers (question/format.php,
`match_grade_options`) reject a question with any other grade, or move it
to the nearest one, and accept a grade within 0.00001 of a listed one.
Embedded answers (Cloze) do not check their grades against the list.

A Moodle numerical answer is a floating-point number.
"""

from __future__ import annotations

import re
from fractions import Fraction

import pytest

from mdq.convert import export_question, import_question
from mdq.models import (
    ChoiceBlank,
    FillInQuestion,
    MultipleChoiceQuestion,
    MultipleSelectionQuestion,
    NumericBlank,
    NumericQuestion,
    ScoredChoice,
    BooleanChoice,
    Tolerance,
)

MOODLE_GRADES = [
    (Fraction(1), "100"),
    (Fraction(9, 10), "90"),
    (Fraction(5, 6), "83.33333"),
    (Fraction(4, 5), "80"),
    (Fraction(3, 4), "75"),
    (Fraction(7, 10), "70"),
    (Fraction(2, 3), "66.66667"),
    (Fraction(3, 5), "60"),
    (Fraction(1, 2), "50"),
    (Fraction(2, 5), "40"),
    (Fraction(1, 3), "33.33333"),
    (Fraction(3, 10), "30"),
    (Fraction(1, 4), "25"),
    (Fraction(1, 5), "20"),
    (Fraction(1, 6), "16.66667"),
    (Fraction(1, 7), "14.28571"),
    (Fraction(1, 8), "12.5"),
    (Fraction(1, 9), "11.11111"),
    (Fraction(1, 10), "10"),
    (Fraction(1, 20), "5"),
    (Fraction(0), "0"),
    (Fraction(-1, 7), "-14.28571"),
    (Fraction(-1), "-100"),
]


def _choice_question(score: float) -> MultipleChoiceQuestion:
    return MultipleChoiceQuestion(
        stem="Qual bioma cobre a maior parte do Brasil?",
        choices=[
            ScoredChoice(text="Amazônia", score=1.0),
            ScoredChoice(text="Cerrado", score=score),
        ],
    )


def _selection_question(n_correct: int, n_wrong: int) -> MultipleSelectionQuestion:
    choices = [BooleanChoice(text=f"certo {i}", correct=True) for i in range(n_correct)]
    choices += [BooleanChoice(text=f"errado {i}", correct=False) for i in range(n_wrong)]
    return MultipleSelectionQuestion(stem="Quais são estados do Nordeste?", choices=choices)


def _moodle_fractions(source: str) -> list[str]:
    return re.findall(r'<answer fraction="([^"]+)"', source)


# ---------------------------------------------------------------------
# Export: only Moodle's grades, written as Moodle writes them
# ---------------------------------------------------------------------


@pytest.mark.parametrize(("grade", "percent"), MOODLE_GRADES)
def test_moodle_xml_exports_a_listed_grade_as_moodle_writes_it(
    grade: Fraction, percent: str
) -> None:
    source = export_question(_choice_question(float(grade)), format="moodle-xml")
    assert _moodle_fractions(source) == ["100", percent]


def test_moodle_xml_accepts_a_score_within_moodles_grade_tolerance() -> None:
    source = export_question(_choice_question(0.833333), format="moodle-xml")
    assert _moodle_fractions(source) == ["100", "83.33333"]


@pytest.mark.parametrize("score", [0.35, 0.8333, 0.99, -0.35])
def test_moodle_xml_rejects_a_score_moodle_does_not_list(score: float) -> None:
    with pytest.raises(ValueError, match="Moodle"):
        export_question(_choice_question(score), format="moodle-xml")


def test_moodle_xml_selection_writes_listed_grades() -> None:
    source = export_question(_selection_question(3, 7), format="moodle-xml")
    assert _moodle_fractions(source) == ["33.33333"] * 3 + ["-14.28571"] * 7


@pytest.mark.parametrize(("n_correct", "n_wrong"), [(11, 1), (1, 11)])
def test_moodle_xml_selection_rejects_an_unlisted_share(n_correct: int, n_wrong: int) -> None:
    with pytest.raises(ValueError, match="Moodle"):
        export_question(_selection_question(n_correct, n_wrong), format="moodle-xml")


def test_moodle_xml_cloze_keeps_an_unlisted_grade() -> None:
    # Moodle does not check the grades of embedded answers against the list.
    question = FillInQuestion(
        stem="O maior bioma do Brasil é a [^b].",
        blanks=[
            ChoiceBlank(
                id="b",
                choices=[
                    ScoredChoice(text="Amazônia", score=1.0),
                    ScoredChoice(text="Floresta Amazônica", score=0.35),
                ],
            )
        ],
    )
    source = export_question(question, format="moodle-xml")
    assert "~%35%Floresta Amazônica" in source


@pytest.mark.parametrize(("grade", "percent"), [g for g in MOODLE_GRADES if g[0] not in (0, 1)])
def test_gift_exports_a_listed_grade_as_moodle_writes_it(grade: Fraction, percent: str) -> None:
    source = export_question(_choice_question(float(grade)), format="gift")
    assert f"~%{percent}%Cerrado" in source


@pytest.mark.parametrize("score", [0.35, 0.8333, -0.35])
def test_gift_rejects_a_score_moodle_does_not_list(score: float) -> None:
    with pytest.raises(ValueError, match="Moodle"):
        export_question(_choice_question(score), format="gift")


# ---------------------------------------------------------------------
# Import: Moodle's rounded grades become the exact fractions
# ---------------------------------------------------------------------


def _moodle_multichoice(percent: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<quiz>\n'
        '  <question type="multichoice">\n'
        '    <questiontext format="markdown"><text>Qual bioma?</text></questiontext>\n'
        '    <single>true</single>\n'
        '    <answer fraction="100"><text>Amazônia</text></answer>\n'
        f'    <answer fraction="{percent}"><text>Cerrado</text></answer>\n'
        '  </question>\n'
        '</quiz>\n'
    )


@pytest.mark.parametrize(("grade", "percent"), MOODLE_GRADES)
def test_moodle_xml_imports_a_listed_grade_exactly(grade: Fraction, percent: str) -> None:
    question = import_question(_moodle_multichoice(percent), format="moodle-xml")
    assert question.choices[1].score == float(grade)  # type: ignore[union-attr]


@pytest.mark.parametrize(("percent", "score"), [("66.666", 2 / 3), ("33.33333333333333", 1 / 3)])
def test_moodle_xml_import_snaps_within_moodles_tolerance(percent: str, score: float) -> None:
    question = import_question(_moodle_multichoice(percent), format="moodle-xml")
    assert question.choices[1].score == score  # type: ignore[union-attr]


def test_moodle_xml_import_keeps_an_unlisted_grade() -> None:
    question = import_question(_moodle_multichoice("35"), format="moodle-xml")
    assert question.choices[1].score == 0.35  # type: ignore[union-attr]


def test_moodle_xml_import_snaps_a_cloze_grade() -> None:
    source = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<quiz>\n'
        '  <question type="multianswer">\n'
        '    <questiontext format="markdown"><text>'
        "O maior bioma é {1:MULTICHOICE:=Amazônia~%33.33333%Floresta}."
        '</text></questiontext>\n'
        '  </question>\n'
        '</quiz>\n'
    )
    question = import_question(source, format="moodle-xml")
    assert question.blanks[0].choices[1].score == 1 / 3  # type: ignore[union-attr]


def test_gift_imports_a_listed_grade_exactly() -> None:
    question = import_question("Qual bioma? {=Amazônia ~%83.33333%Cerrado}", format="gift")
    assert question.choices[1].score == 5 / 6  # type: ignore[union-attr]


# ---------------------------------------------------------------------
# Numeric answers: a Moodle answer is a float
# ---------------------------------------------------------------------


def _numeric(answer: int | float | str, tolerance: Tolerance | None = None) -> NumericQuestion:
    return NumericQuestion(stem="Quanto vale?", answer=answer, tolerance=tolerance)


def _numeric_blank(answer: int | float | str, tolerance: Tolerance | None = None) -> FillInQuestion:
    return FillInQuestion(
        stem="Vale [^v].",
        blanks=[NumericBlank(id="v", answer=answer, tolerance=tolerance)],
    )


INEXACT = ["1/3", "3.14159265358979323846", "3000000000000000000001"]


@pytest.mark.parametrize("format", ["moodle-xml", "gift"])
@pytest.mark.parametrize("answer", INEXACT)
def test_inexact_answer_without_tolerance_is_rejected(format: str, answer: str) -> None:
    with pytest.raises(ValueError, match="tolerance"):
        export_question(_numeric(answer), format=format)
    with pytest.raises(ValueError, match="tolerance"):
        export_question(_numeric_blank(answer), format=format)


@pytest.mark.parametrize("format", ["moodle-xml", "gift"])
def test_inexact_answer_with_tolerance_is_the_nearest_float(format: str) -> None:
    source = export_question(_numeric("1/3", Tolerance(absolute=0.01)), format=format)
    assert "0.3333333333333333" in source
    source = export_question(_numeric_blank("1/3", Tolerance(relative=0.05)), format=format)
    assert "0.3333333333333333" in source


@pytest.mark.parametrize("format", ["moodle-xml", "gift"])
@pytest.mark.parametrize(("answer", "text"), [("2.50", "2.5"), ("3000000000", "3000000000"), ("3/4", "0.75")])
def test_exact_string_answer_is_exported_without_tolerance(
    format: str, answer: str, text: str
) -> None:
    source = export_question(_numeric(answer), format=format)
    assert text in source


# ---------------------------------------------------------------------
# Cloze: every subquestion needs an answer worth 100%
# ---------------------------------------------------------------------
# qtype_multianswer_validate_question (question/type/multianswer/
# questiontype.php) rejects a subquestion none of whose non-empty
# answers has a fraction of exactly 1 (`fractionsnomax`). Only a
# multiple-response subquestion, which MDQ never exports, may instead
# have any positive fraction.


def _choice_blank_question(*scores: float | None) -> FillInQuestion:
    texts = ["Amazônia", "Cerrado", "Caatinga"]
    return FillInQuestion(
        stem="O maior bioma do Brasil é a [^b].",
        blanks=[
            ChoiceBlank(
                id="b",
                choices=[ScoredChoice(text=t, score=s) for t, s in zip(texts, scores)],
            )
        ],
    )


@pytest.mark.parametrize("scores", [(0.5, 0.0), (0.0, 0.0), (None, None), (0.9, 0.5, -0.5)])
def test_moodle_xml_cloze_choice_blank_needs_a_full_credit_choice(
    scores: tuple[float | None, ...],
) -> None:
    with pytest.raises(ValueError, match="100%"):
        export_question(_choice_blank_question(*scores), format="moodle-xml")


def test_moodle_xml_cloze_choice_blank_with_a_full_credit_choice_exports() -> None:
    source = export_question(_choice_blank_question(0.5, 1.0, None), format="moodle-xml")
    assert "{1:MULTICHOICE:~%50%Amazônia=Cerrado~Caatinga}" in source

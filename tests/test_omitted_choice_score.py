"""
multiple-choice.md, "Choices" and "Grading": a blank value, `[ ]`, omits
`score` from the document; `[0%]` is an explicit zero. The grading strategy
decides what an omitted score is worth, so the parser must not turn `[ ]`
into 0, and the converters export the score the student would get.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

import mdq
from mdq import models
from mdq._parser import parse_question
from mdq.convert import export_question

STEM = "Qual é a maior floresta tropical do mundo?"

MD = f"""{STEM}

* [*] Amazônia
* [ ] Mata Atlântica
* [0%] Cerrado
* [-25%] Saara
"""

FILL_IN_MD = """O bioma [^biome] é o maior do Brasil.

[^biome]:
* [*] Amazônia
* [ ] Cerrado
* [0%] Pampa
"""


def _mc(*scores: float | None, **fields) -> models.MultipleChoiceQuestion:
    choices = [
        {"text": f"choice {i}", **({} if s is None else {"score": s})}
        for i, s in enumerate(scores)
    ]
    return mdq.load(
        {"type": "multiple-choice", "stem": STEM, "choices": choices, **fields},
        kind="question",
    ).document


#
# Parser
#
def test_blank_value_omits_score_and_zero_percent_is_explicit() -> None:
    choices = parse_question(MD)["choices"]
    assert "score" not in choices[1]
    assert choices[2]["score"] == 0
    assert choices[0]["score"] == 1
    assert choices[3]["score"] == -0.25


def test_fill_in_choice_blank_follows_the_same_rule() -> None:
    (blank,) = parse_question(FILL_IN_MD)["blanks"]
    assert "score" not in blank["choices"][1]
    assert blank["choices"][2]["score"] == 0


def test_loaded_blank_value_is_none() -> None:
    question = mdq.load(MD, kind="question").document
    assert [c.score for c in question.choices] == [1.0, None, 0.0, -0.25]


#
# Render
#
def test_render_writes_blank_for_none_and_zero_percent_for_zero() -> None:
    question = _mc(1, None, 0, -0.25)
    lines = str(question).splitlines()
    marks = [line for line in lines if line.startswith("* [")]
    assert marks == [
        "* [*] choice 0",
        "* [ ] choice 1",
        "* [0%] choice 2",
        "* [-25%] choice 3",
    ]


def test_render_of_fill_in_choice_blank_distinguishes_none_from_zero() -> None:
    question = mdq.load(FILL_IN_MD, kind="question").document
    lines = str(question).splitlines()
    assert "* [ ] Cerrado" in lines
    assert "* [0%] Pampa" in lines


@pytest.mark.parametrize("source", [MD, FILL_IN_MD])
def test_render_then_load_is_a_fixed_point(source: str) -> None:
    question = mdq.load(source, kind="question").document
    again = mdq.load(str(question), kind="question")
    assert [d for d in again.diagnostics if d.severity == "error"] == []
    assert again.document == question


#
# Grading
#
def test_symmetric_penalizes_an_omitted_score_but_not_an_explicit_zero() -> None:
    question = _mc(1, None, 0, None).with_ids()
    assert question.unspecified_score() == pytest.approx(-0.5)
    assert question.score_response(question.choices[1].id).score == pytest.approx(-0.5)
    assert question.score_response(question.choices[2].id).score == 0


def test_two_correct_choices_give_minus_one_in_symmetric() -> None:
    # The table in multiple-choice.md, "Grading": `[1, 1, _, _]` is -1.00.
    assert _mc(1, 1, None, None).unspecified_score() == pytest.approx(-1.0)


#
# Converters: an omitted score exports as the score the strategy gives it
#
def _moodle_fractions(question: models.MultipleChoiceQuestion) -> list[float]:
    root = ET.fromstring(export_question(question, format="moodle-xml"))
    return [float(a.get("fraction")) for a in root.findall("./question/answer")]


def test_moodle_xml_exports_the_strategy_score_of_an_omitted_score() -> None:
    assert _moodle_fractions(_mc(1, None, None, None)) == pytest.approx(
        [100, -33.33333, -33.33333, -33.33333]
    )
    assert _moodle_fractions(_mc(1, None, None, None, grading="partial")) == [
        100,
        0,
        0,
        0,
    ]


def test_gift_exports_the_strategy_score_of_an_omitted_score() -> None:
    gift = export_question(_mc(1, None, None, None), format="gift")
    assert gift.count("~%-33.33333%") == 3
    gift = export_question(_mc(1, None, None, None, grading="partial"), format="gift")
    assert "~%-" not in gift and gift.count("~") == 3


def test_aiken_exports_a_question_with_omitted_scores() -> None:
    aiken = export_question(_mc(None, 1, None), format="aiken")
    assert aiken.rstrip().endswith("ANSWER: b")

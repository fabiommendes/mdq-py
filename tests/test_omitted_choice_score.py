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

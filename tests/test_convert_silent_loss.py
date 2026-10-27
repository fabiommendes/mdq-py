"""
Converter fixes for text that an export or import used to drop or merge:
the spaces around a GIFT missing-word blank, the epilogue of a GIFT
question, and the feedback of a Moodle cloze choice.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from mdq import models
from mdq.convert import export_question, import_question


# ---------------------------------------------------------------------
# GIFT missing word: spaces around the blank
# ---------------------------------------------------------------------
def test_gift_missing_word_import_keeps_the_spaces() -> None:
    q = import_question("::q:: A capital é {=Brasília ~Rio} hoje.", format="gift")
    assert q.stem == "A capital é [^blank] hoje."


def test_gift_missing_word_import_keeps_a_missing_space() -> None:
    q = import_question("A capital é {=Brasília ~Rio}.", format="gift")
    assert q.stem == "A capital é [^blank]."


def _fill_in(stem: str) -> models.FillInQuestion:
    return models.FillInQuestion(
        stem=stem,
        blanks=[
            models.ChoiceBlank(
                id="c",
                choices=[
                    models.ScoredChoice(text="Brasília", score=1.0),
                    models.ScoredChoice(text="Rio", score=0.0),
                ],
            )
        ],
    )


def test_gift_missing_word_export_writes_the_spaces() -> None:
    source = export_question(_fill_in("A capital é [^c] hoje."), format="gift")
    assert "A capital é {=Brasília ~Rio} hoje." in source


def test_gift_missing_word_export_keeps_punctuation_attached() -> None:
    source = export_question(_fill_in("A capital é [^c]."), format="gift")
    assert "{=Brasília ~Rio}." in source


def test_gift_missing_word_round_trip_keeps_the_stem() -> None:
    for stem in ("A capital é [^blank] hoje.", "A capital é [^blank].", "[^blank] é a capital."):
        question = _fill_in(stem.replace("blank", "c"))
        again = import_question(export_question(question, format="gift"), format="gift")
        assert again.stem == stem


# ---------------------------------------------------------------------
# GIFT epilogue
# ---------------------------------------------------------------------
TF = models.TrueFalseQuestion(
    stem="Julgue.",
    choices=[
        models.Statement(text="Brasília é a capital.", correct=True),
        models.Statement(text="Rio é a capital.", correct=False),
    ],
    epilogue="Fonte: IBGE.",
)


def test_gift_true_false_export_keeps_the_epilogue() -> None:
    source = export_question(TF, format="gift")
    assert source.count("Fonte\\: IBGE.") == 2  # GIFT escapes the colon


def test_gift_true_false_round_trip_keeps_the_epilogue_in_the_stem() -> None:
    again = import_question(export_question(TF, format="gift"), format="gift")
    assert again.stem == "Julgue.\n\nFonte: IBGE."
    assert [c.text for c in again.choices] == [c.text for c in TF.choices]


def test_gift_epilogue_of_a_choice_question_goes_before_the_answers() -> None:
    question = models.MultipleChoiceQuestion(
        stem="Qual é a capital?",
        epilogue="A capital mudou em 1960.",
        choices=[
            models.ScoredChoice(text="Brasília", score=1.0),
            models.ScoredChoice(text="Rio", score=0.0),
        ],
    )
    source = export_question(question, format="gift")
    assert "A capital mudou em 1960. {" in source
    again = import_question(source, format="gift")
    assert isinstance(again, models.MultipleChoiceQuestion)
    assert again.stem == "Qual é a capital?\n\nA capital mudou em 1960."


def test_gift_epilogue_of_a_fill_in_question_does_not_split_the_block() -> None:
    question = _fill_in("A capital é [^c].").model_copy(
        update={"epilogue": "A capital mudou em 1960."}
    )
    again = import_question(export_question(question, format="gift"), format="gift")
    assert isinstance(again, models.FillInQuestion)
    assert "A capital mudou em 1960." in again.stem


# ---------------------------------------------------------------------
# Moodle cloze choice feedback
# ---------------------------------------------------------------------
def test_moodle_cloze_export_keeps_choice_feedback() -> None:
    question = models.FillInQuestion(
        stem="A capital é [^c].",
        blanks=[
            models.ChoiceBlank(
                id="c",
                choices=[
                    models.ScoredChoice(text="Brasília", score=1.0, feedback="Isso!"),
                    models.ScoredChoice(text="Rio", score=0.0, feedback="Foi até 1960."),
                ],
            )
        ],
    )
    source = export_question(question, format="moodle-xml")
    text = ET.fromstring(source).findtext("./question/questiontext/text")
    assert text == "A capital é {1:MULTICHOICE:=Brasília#Isso!~Rio#Foi até 1960.}."
    again = import_question(source, format="moodle-xml")
    assert [c.feedback for c in again.blanks[0].choices] == ["Isso!", "Foi até 1960."]

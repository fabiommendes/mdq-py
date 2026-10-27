"""
General feedback (GIFT `####`, Moodle `<generalfeedback>`) is `meta.generalFeedback`.

The key is converter-defined, not part of the MDQ spec. The GIFT essay keeps
its own rule: `####` is the `answerKey`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from mdq import models
from mdq.convert import export_question, import_question

STEM = "Qual é a capital do Brasil?"
GENERAL = "A capital mudou do Rio de Janeiro para Brasília em 1960."


def _xml(qtype: str, general: str | None, *, body: str = "") -> str:
    gf = f"<generalfeedback><text>{general}</text></generalfeedback>\n" if general is not None else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<quiz>\n'
        f'  <question type="{qtype}">\n'
        f'    <questiontext format="markdown"><text>{STEM}</text></questiontext>\n'
        f"    {gf}{body}\n  </question>\n</quiz>\n"
    )


MC_ANSWERS = (
    '<answer fraction="100"><text>Brasília</text></answer>'
    '<answer fraction="0"><text>Rio</text></answer>'
)


def _mc(**fields: object) -> models.MultipleChoiceQuestion:
    return models.MultipleChoiceQuestion(
        stem=STEM,
        choices=[
            models.ScoredChoice(text="Brasília", score=1.0),
            models.ScoredChoice(text="Rio", score=0.0),
        ],
        **fields,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "source",
    [
        f"{STEM} {{=Brasília ~Rio ####{GENERAL}}}",
        f"{STEM} {{=Brasília ####{GENERAL}}}",
        f"{STEM} {{#=1960:0 ####{GENERAL}}}",
        f"{STEM} {{TRUE ####{GENERAL}}}",
    ],
    ids=["choice", "short-answer", "numeric", "true-false"],
)
def test_gift_general_feedback_is_meta(source: str) -> None:
    q = import_question(source, format="gift")
    assert q.meta == {"generalFeedback": GENERAL.replace("\\", "")}


def test_gift_essay_general_feedback_stays_the_answer_key() -> None:
    q = import_question(f"Explique o ciclo da água. {{####{GENERAL}}}", format="gift")
    assert q.answer_key == GENERAL
    assert q.meta is None


def test_gift_without_general_feedback_has_no_meta() -> None:
    assert import_question(f"{STEM} {{=Brasília ~Rio}}", format="gift").meta is None


def test_moodle_general_feedback_is_meta() -> None:
    q = import_question(_xml("multichoice", GENERAL, body=MC_ANSWERS), format="moodle-xml")
    assert q.meta == {"generalFeedback": GENERAL}


def test_moodle_essay_keeps_grader_info_and_general_feedback_apart() -> None:
    body = '<graderinfo format="markdown"><text>Chave.</text></graderinfo>'
    q = import_question(_xml("essay", GENERAL, body=body), format="moodle-xml")
    assert q.answer_key == "Chave."
    assert q.meta == {"generalFeedback": GENERAL}


@pytest.mark.parametrize("general", ["", "   \n "])
def test_empty_general_feedback_is_ignored(general: str) -> None:
    q = import_question(_xml("multichoice", general, body=MC_ANSWERS), format="moodle-xml")
    assert q.meta is None


def test_moodle_cloze_general_feedback_is_meta() -> None:
    xml = _xml("multianswer", GENERAL).replace(STEM, "A capital é {1:SHORTANSWER:=Brasília}.")
    assert import_question(xml, format="moodle-xml").meta == {"generalFeedback": GENERAL}


# ---------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------
def test_gift_export_writes_general_feedback() -> None:
    source = export_question(_mc(meta={"generalFeedback": GENERAL}), format="gift")
    assert "#### A capital mudou" in source


def test_moodle_export_writes_general_feedback() -> None:
    source = export_question(_mc(meta={"generalFeedback": GENERAL}), format="moodle-xml")
    root = ET.fromstring(source)
    assert root.findtext("./question/generalfeedback/text") == GENERAL


def test_moodle_export_without_general_feedback_has_no_element() -> None:
    root = ET.fromstring(export_question(_mc(), format="moodle-xml"))
    assert root.find("./question/generalfeedback") is None


@pytest.mark.parametrize("format", ["gift", "moodle-xml"])
def test_general_feedback_round_trip(format: str) -> None:
    original = _mc(meta={"generalFeedback": GENERAL})
    again = import_question(export_question(original, format=format), format=format)
    assert again.meta == {"generalFeedback": GENERAL}


@pytest.mark.parametrize("format", ["gift", "moodle-xml"])
@pytest.mark.parametrize("value", [3, ["x"], "", "  \n"])
def test_invalid_general_feedback_raises(format: str, value: object) -> None:
    with pytest.raises(ValueError, match="generalFeedback"):
        export_question(_mc(meta={"generalFeedback": value}), format=format)


@pytest.mark.parametrize("format", ["gift", "moodle-xml"])
def test_other_meta_keys_are_ignored(format: str) -> None:
    export_question(_mc(meta={"fonte": "IBGE"}), format=format)


def test_gift_essay_with_answer_key_and_general_feedback_raises() -> None:
    question = models.EssayQuestion(
        stem="Explique.", answer_key="Chave.", meta={"generalFeedback": GENERAL}
    )
    with pytest.raises(ValueError, match="generalFeedback"):
        export_question(question, format="gift")


def test_gift_essay_general_feedback_alone_is_written() -> None:
    question = models.EssayQuestion(stem="Explique.", meta={"generalFeedback": GENERAL})
    assert "#### A capital mudou" in export_question(question, format="gift")


def test_moodle_essay_writes_both() -> None:
    question = models.EssayQuestion(
        stem="Explique.", answer_key="Chave.", meta={"generalFeedback": GENERAL}
    )
    root = ET.fromstring(export_question(question, format="moodle-xml"))
    assert root.findtext("./question/graderinfo/text") == "Chave."
    assert root.findtext("./question/generalfeedback/text") == GENERAL


def test_true_false_group_writes_general_feedback_once() -> None:
    question = models.TrueFalseQuestion(
        stem="Julgue.",
        choices=[
            models.Statement(text="Brasília é a capital.", correct=True),
            models.Statement(text="Rio é a capital.", correct=False),
        ],
        meta={"generalFeedback": GENERAL},
    )
    gift = export_question(question, format="gift")
    assert gift.count("####") == 1
    again = import_question(gift, format="gift")
    assert again.meta == {"generalFeedback": GENERAL}
    moodle = export_question(question, format="moodle-xml")
    assert moodle.count("<generalfeedback") == 1
    assert import_question(moodle, format="moodle-xml").meta == {"generalFeedback": GENERAL}

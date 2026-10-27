"""
Answer key of short-answer and numeric questions on import and export.

MDQ grading is binary: a 100% answer is `accept` (or the numeric `answer`), a
0% short answer is `reject`, and partial credit has no MDQ form
(`ValueError`). GIFT, Moodle XML and Moodle cloze blanks follow the same rules.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from mdq import models
from mdq.convert import export_question, import_question

STEM = "Qual é a capital do Brasil?"
NUM_STEM = "Em que ano o Brasil declarou a independência?"
WILD = "o Brasil tem um bioma chamado Mata *"


def _xml(qtype: str, *answers: str, stem: str = STEM) -> str:
    body = "\n".join(answers)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<quiz>\n'
        f'  <question type="{qtype}">\n'
        f'    <questiontext format="markdown"><text>{stem}</text></questiontext>\n'
        f"{body}\n  </question>\n</quiz>\n"
    )


def _ans(text: str, fraction: float, feedback: str | None = None, tol: float | None = None) -> str:
    fb = f"<feedback><text>{feedback}</text></feedback>" if feedback else ""
    tl = f"<tolerance>{tol}</tolerance>" if tol is not None else ""
    return f'    <answer fraction="{fraction}"><text>{text}</text>{fb}{tl}</answer>'


def _sa_xml(*answers: str) -> str:
    return _xml("shortanswer", *answers)


def _num_xml(*answers: str) -> str:
    return _xml("numerical", *answers, stem=NUM_STEM)


def _cloze_xml(body: str) -> str:
    return _xml("multianswer", stem=f"A capital é {body}.").replace("\n\n", "\n")


def _patterns(patterns: list[models.AnswerPattern] | None) -> list[tuple[str, str | None]]:
    return [(p.pattern, p.feedback) for p in patterns or []]


# ---------------------------------------------------------------------
# Short answer import
# ---------------------------------------------------------------------
def test_moodle_short_answer_splits_by_fraction() -> None:
    q = import_question(
        _sa_xml(
            _ans("Brasília", 100, "Isso!"),
            _ans("Rio de Janeiro", 0, "Foi capital até 1960."),
        ),
        format="moodle-xml",
    )
    assert _patterns(q.accept) == [("Brasília", "Isso!")]
    assert _patterns(q.reject) == [("Rio de Janeiro", "Foi capital até 1960.")]


def test_moodle_short_answer_partial_credit_raises() -> None:
    source = _sa_xml(_ans("Brasília", 100), _ans("Brasilia", 50))
    with pytest.raises(ValueError, match=r"cannot convert from Moodle XML.*partial credit"):
        import_question(source, format="moodle-xml")


def test_gift_short_answer_splits_by_credit() -> None:
    q = import_question(
        f"{STEM} {{=%100%Brasília#Isso! =%0%Rio de Janeiro#Foi até 1960.}}", format="gift"
    )
    assert _patterns(q.accept) == [("Brasília", "Isso!")]
    assert _patterns(q.reject) == [("Rio de Janeiro", "Foi até 1960.")]


def test_gift_short_answer_partial_credit_raises() -> None:
    with pytest.raises(ValueError, match=r"cannot convert from GIFT.*partial credit"):
        import_question(f"{STEM} {{=%50%Rio#meio =Brasília#sim}}", format="gift")


def test_gift_short_answer_without_reject_has_no_reject_list() -> None:
    q = import_question(f"{STEM} {{=Brasília =Brasilia}}", format="gift")
    assert [p.pattern for p in q.accept] == ["Brasília", "Brasilia"]
    assert q.reject is None


def test_moodle_star_zero_keeps_incorrect_feedback() -> None:
    q = import_question(
        _sa_xml(_ans("Brasília", 100), _ans("*", 0, "Errado.")), format="moodle-xml"
    )
    assert q.incorrect_feedback == "Errado."
    assert q.reject is None


def test_wildcard_inside_short_answer_text_raises() -> None:
    source = _sa_xml(_ans(WILD, 100))
    with pytest.raises(ValueError, match=r"cannot convert from Moodle XML.*wildcard"):
        import_question(source, format="moodle-xml")
    with pytest.raises(ValueError, match=r"cannot convert from GIFT.*wildcard"):
        import_question(f"{STEM} {{={WILD}}}", format="gift")


def test_cloze_short_answer_blank_splits_by_fraction() -> None:
    q = import_question(
        _cloze_xml("{1:SHORTANSWER:=Brasília#Isso!~%0%Rio#Não}"), format="moodle-xml"
    )
    [blank] = q.blanks
    assert _patterns(blank.accept) == [("Brasília", "Isso!")]
    assert _patterns(blank.reject) == [("Rio", "Não")]


def test_cloze_short_answer_blank_partial_credit_raises() -> None:
    with pytest.raises(ValueError, match="partial credit"):
        import_question(
            _cloze_xml("{1:SHORTANSWER:=Brasília~%50%Brasilia}"), format="moodle-xml"
        )


def test_gift_missing_word_short_answer_splits_by_credit() -> None:
    q = import_question("A capital é {=Brasília =%0%Rio#Não}.", format="gift")
    [blank] = q.blanks
    assert _patterns(blank.accept) == [("Brasília", None)]
    assert _patterns(blank.reject) == [("Rio", "Não")]


# ---------------------------------------------------------------------
# Numeric import
# ---------------------------------------------------------------------
def test_moodle_numeric_key_is_the_full_credit_answer() -> None:
    q = import_question(
        _num_xml(_ans("1823", 0, "Quase."), _ans("1822", 100)), format="moodle-xml"
    )
    assert q.answer == 1822


def test_gift_numeric_key_is_the_full_credit_answer() -> None:
    q = import_question(f"{NUM_STEM} {{#=%0%1823 =1822}}", format="gift")
    assert q.answer == 1822


def test_numeric_partial_credit_raises() -> None:
    with pytest.raises(ValueError, match=r"cannot convert from GIFT.*partial credit"):
        import_question(f"{NUM_STEM} {{#=1822 =%50%1823:1}}", format="gift")
    source = _num_xml(_ans("1822", 100), _ans("1822", 50, tol=2))
    with pytest.raises(ValueError, match=r"cannot convert from Moodle XML.*partial credit"):
        import_question(source, format="moodle-xml")


def test_numeric_second_full_credit_answer_is_dropped_when_identical() -> None:
    q = import_question(f"{NUM_STEM} {{#=1822 =1822.0}}", format="gift")
    assert q.answer == 1822


def test_numeric_second_full_credit_answer_raises_when_different() -> None:
    with pytest.raises(ValueError, match="worth 100%"):
        import_question(f"{NUM_STEM} {{#=1822 =1823}}", format="gift")
    with pytest.raises(ValueError, match="worth 100%"):
        import_question(f"{NUM_STEM} {{#=1822:1 =1822}}", format="gift")


def test_numeric_without_full_credit_answer_raises() -> None:
    with pytest.raises(ValueError, match="full credit"):
        import_question(f"{NUM_STEM} {{#=%0%1823}}", format="gift")


def test_numeric_zero_answer_is_dropped() -> None:
    q = import_question(_num_xml(_ans("1822", 100), _ans("1823", 0, "Quase.")), format="moodle-xml")
    assert q.answer == 1822
    assert q.incorrect_feedback is None


def test_moodle_numeric_star_zero_becomes_incorrect_feedback() -> None:
    q = import_question(
        _num_xml(_ans("1822", 100), _ans("*", 0, "Foi em 1822.")), format="moodle-xml"
    )
    assert q.answer == 1822
    assert q.incorrect_feedback == "Foi em 1822."


def test_cloze_numeric_blank_key_is_the_full_credit_answer() -> None:
    q = import_question(_cloze_xml("{1:NUMERICAL:~1823#Quase=1822}"), format="moodle-xml")
    [blank] = q.blanks
    assert blank.answer == 1822


def test_cloze_numeric_blank_partial_credit_raises() -> None:
    with pytest.raises(ValueError, match="partial credit"):
        import_question(_cloze_xml("{1:NUMERICAL:=1822~%50%1823}"), format="moodle-xml")


def test_gift_missing_word_numeric_blank_key_is_the_full_credit_answer() -> None:
    q = import_question("Foi em {#=%0%1823 =1822}.", format="gift")
    [blank] = q.blanks
    assert blank.answer == 1822


# ---------------------------------------------------------------------
# Export of reject and accept feedback
# ---------------------------------------------------------------------
def _sa(**fields: object) -> models.ShortAnswerQuestion:
    return models.ShortAnswerQuestion(stem=STEM, **fields)  # type: ignore[arg-type]


RICH = {
    "accept": [models.AnswerPattern(pattern="Brasília", feedback="Isso!")],
    "reject": [models.AnswerPattern(pattern="Rio de Janeiro", feedback="Foi até 1960.")],
}


def test_moodle_export_writes_reject_as_fraction_zero_with_feedback() -> None:
    root = ET.fromstring(export_question(_sa(**RICH), format="moodle-xml"))
    answers = [
        (float(a.get("fraction", "")), a.findtext("text"), a.findtext("feedback/text"))
        for a in root.findall("./question/answer")
    ]
    assert answers == [(100.0, "Brasília", "Isso!"), (0.0, "Rio de Janeiro", "Foi até 1960.")]


def test_gift_export_writes_reject_as_zero_credit_with_feedback() -> None:
    source = export_question(_sa(**RICH), format="gift")
    assert "=Brasília#Isso!" in source
    assert "=%0%Rio de Janeiro#Foi até 1960." in source


@pytest.mark.parametrize("format", ["gift", "moodle-xml"])
def test_reject_round_trip(format: str) -> None:
    original = _sa(**RICH)
    again = import_question(export_question(original, format=format), format=format)
    assert _patterns(again.accept) == _patterns(original.accept)
    assert _patterns(again.reject) == _patterns(original.reject)


@pytest.mark.parametrize("format", ["gift", "moodle-xml"])
def test_reject_regex_still_raises(format: str) -> None:
    question = _sa(accept=["Brasília"], reject=["/Rio.*/"])
    with pytest.raises(ValueError, match="regex"):
        export_question(question, format=format)


def test_moodle_numeric_incorrect_feedback_round_trip() -> None:
    question = models.NumericQuestion(
        stem=NUM_STEM, answer=1822, incorrect_feedback="Foi em 1822."
    )
    source = export_question(question, format="moodle-xml")
    root = ET.fromstring(source)
    last = root.findall("./question/answer")[-1]
    assert (last.get("fraction"), last.findtext("text")) == ("0", "*")
    assert import_question(source, format="moodle-xml").incorrect_feedback == "Foi em 1822."


def test_cloze_short_answer_blank_export_keeps_reject_and_feedback() -> None:
    question = models.FillInQuestion(
        stem="A capital é [^c].",
        blanks=[models.ShortAnswerBlank(id="c", accept=RICH["accept"], reject=RICH["reject"])],
    )
    source = export_question(question, format="moodle-xml")
    root = ET.fromstring(source)
    text = root.findtext("./question/questiontext/text")
    assert text == "A capital é {1:SHORTANSWER:=Brasília#Isso!~Rio de Janeiro#Foi até 1960.}."
    again = import_question(source, format="moodle-xml")
    [blank] = again.blanks
    assert _patterns(blank.reject) == _patterns(RICH["reject"])

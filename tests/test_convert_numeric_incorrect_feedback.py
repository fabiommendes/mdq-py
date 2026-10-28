"""GIFT writes the `incorrectFeedback` of a numeric question as a 0% `*` answer."""

from __future__ import annotations

from mdq import models
from mdq.convert import export_question, import_question

NUMERIC = models.NumericQuestion(
    stem="Quanto vale a aceleração da gravidade em m/s²?",
    answer=9.8,
    tolerance=models.Tolerance(absolute=0.1),
    incorrect_feedback="Veja a tabela de constantes.",
)


def test_gift_export_keeps_the_incorrect_feedback() -> None:
    source = export_question(NUMERIC, format="gift")
    assert "=%0%*#Veja a tabela de constantes." in source


def test_gift_round_trip_keeps_the_incorrect_feedback() -> None:
    again = import_question(export_question(NUMERIC, format="gift"), format="gift")
    assert isinstance(again, models.NumericQuestion)
    assert again.incorrect_feedback == "Veja a tabela de constantes."
    assert again.answer == 9.8


def test_gift_import_reads_moodles_multi_line_incorrect_feedback() -> None:
    source = "Quanto vale g? {#\n=%100%9.8:0.1#\n~#Veja a tabela.\n}"
    q = import_question(source, format="gift")
    assert isinstance(q, models.NumericQuestion)
    assert q.answer == 9.8
    assert q.incorrect_feedback == "Veja a tabela."


def test_gift_import_reads_moodles_one_line_incorrect_feedback() -> None:
    q = import_question("Quanto vale g? {#=9.8:0.1 ~#Veja a tabela.}", format="gift")
    assert isinstance(q, models.NumericQuestion)
    assert q.answer == 9.8
    assert q.incorrect_feedback == "Veja a tabela."

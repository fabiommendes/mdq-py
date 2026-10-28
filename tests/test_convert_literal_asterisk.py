"""
A literal short-answer pattern with an inner `*` is exported with the
asterisk escaped (`\\*`), which Moodle's shortanswer reads as a literal
asterisk. The importers read `\\*` back as `*`.
"""

from __future__ import annotations

import pytest

from mdq import models
from mdq.convert import export_question, import_question


def _short(pattern: str) -> models.ShortAnswerQuestion:
    return models.ShortAnswerQuestion(
        stem="Qual é a fórmula?", accept=[models.AnswerPattern(pattern=pattern)]
    )


def test_moodle_xml_export_escapes_an_inner_asterisk() -> None:
    source = export_question(_short("2*3"), format="moodle-xml")
    assert "<text>2\\*3</text>" in source


def test_gift_export_escapes_an_inner_asterisk() -> None:
    source = export_question(_short("2*3"), format="gift")
    assert "{=2\\\\*3}" in source


@pytest.mark.parametrize("format", ["gift", "moodle-xml"])
@pytest.mark.parametrize("pattern", ["2*3", "*x*", "a**b"])
def test_an_inner_asterisk_round_trips(format: str, pattern: str) -> None:
    again = import_question(export_question(_short(pattern), format=format), format=format)
    assert isinstance(again, models.ShortAnswerQuestion)
    assert again.accept is not None
    assert [a.pattern for a in again.accept] == [pattern]


def test_an_exact_literal_with_an_asterisk_round_trips() -> None:
    source = export_question(_short("`2*3`"), format="gift")
    again = import_question(source, format="gift")
    assert again.accept is not None
    assert again.accept[0].pattern == "2*3"


def test_gift_import_reads_an_escaped_asterisk_as_literal() -> None:
    q = import_question("Fórmula? {=2\\\\*3}", format="gift")
    assert q.accept is not None
    assert q.accept[0].pattern == "2*3"


def test_gift_import_still_rejects_an_unescaped_inner_asterisk() -> None:
    with pytest.raises(ValueError, match="wildcard"):
        import_question("Fórmula? {=2*3}", format="gift")


@pytest.mark.parametrize("format", ["gift", "moodle-xml"])
@pytest.mark.parametrize("pattern", ["`*`", "2\\*3", "a\\\\*b"])
def test_a_lone_or_backslashed_asterisk_round_trips(format: str, pattern: str) -> None:
    again = import_question(export_question(_short(pattern), format=format), format=format)
    assert isinstance(again, models.ShortAnswerQuestion)
    assert again.accept is not None
    assert [a.pattern for a in again.accept] == [pattern]


def test_a_lone_asterisk_is_exported_escaped() -> None:
    xml = export_question(_short("`*`"), format="moodle-xml")
    assert "<text>\\*</text>" in xml
    assert "{=\\\\*}" in export_question(_short("`*`"), format="gift")


def _fill_in(pattern: str) -> models.FillInQuestion:
    return models.FillInQuestion(
        stem="Quanto é [^1]?",
        blanks=[
            models.ShortAnswerBlank(id="1", accept=[models.AnswerPattern(pattern=pattern)])
        ],
    )


def test_cloze_export_does_not_double_the_backslash() -> None:
    source = export_question(_fill_in("2*3"), format="moodle-xml")
    assert "{1:SHORTANSWER:=2\\*3}" in source
    assert "\\\\*" not in source


@pytest.mark.parametrize("pattern", ["2*3", "`*`", "2\\*3"])
def test_cloze_asterisk_round_trips(pattern: str) -> None:
    source = export_question(_fill_in(pattern), format="moodle-xml")
    again = import_question(source, format="moodle-xml")
    assert isinstance(again, models.FillInQuestion)
    blank = again.blanks[0]
    assert isinstance(blank, models.ShortAnswerBlank)
    assert blank.accept is not None
    assert [a.pattern for a in blank.accept] == [pattern]


def test_cloze_export_keeps_colon_and_equals_unescaped() -> None:
    source = export_question(_fill_in("10:30"), format="moodle-xml")
    assert "{1:SHORTANSWER:=10:30}" in source
    source = export_question(_fill_in("x=y"), format="moodle-xml")
    assert "{1:SHORTANSWER:=x=y}" in source


@pytest.mark.parametrize("pattern", ["10:30", "x=y", "a}b", "a#b", "a*b=c:d"])
def test_cloze_short_text_round_trips(pattern: str) -> None:
    source = export_question(_fill_in(pattern), format="moodle-xml")
    again = import_question(source, format="moodle-xml")
    blank = again.blanks[0]
    assert [a.pattern for a in blank.accept] == [pattern]


def test_cloze_export_escapes_closing_brace_and_hash() -> None:
    source = export_question(_fill_in("a}b#c"), format="moodle-xml")
    assert "{1:SHORTANSWER:=a\\}b\\#c}" in source


@pytest.mark.parametrize("pattern", ["a~b", "a\\", "a\\}b", "a\\#b", "a\\~b"])
def test_cloze_export_rejects_what_it_cannot_express(pattern: str) -> None:
    with pytest.raises(ValueError, match="cannot convert"):
        export_question(_fill_in(pattern), format="moodle-xml")


def test_cloze_zero_credit_answer_starting_with_equals_is_marked_explicitly() -> None:
    question = models.FillInQuestion(
        stem="Fórmula? [^1]",
        blanks=[
            models.ShortAnswerBlank(
                id="1",
                accept=[models.AnswerPattern(pattern="SOMA")],
                reject=[models.AnswerPattern(pattern="=SOMA(A1)")],
            )
        ],
    )
    source = export_question(question, format="moodle-xml")
    assert "{1:SHORTANSWER:=SOMA~%0%=SOMA(A1)}" in source
    blank = import_question(source, format="moodle-xml").blanks[0]
    assert [a.pattern for a in blank.accept] == ["SOMA"]
    assert [a.pattern for a in blank.reject] == ["=SOMA(A1)"]


def test_cloze_alternatives_are_separated_by_tilde_in_every_kind() -> None:
    from mdq.convert._moodle_xml import MoodleAnswer, MoodleCloze, parse_cloze, render_cloze

    cloze = MoodleCloze(
        kind="MULTICHOICE",
        answers=[
            MoodleAnswer(text="a", fraction=100.0),
            MoodleAnswer(text="b", fraction=100.0),
            MoodleAnswer(text="c", fraction=0.0),
        ],
    )
    assert render_cloze(cloze) == "{1:MULTICHOICE:=a~=b~c}"
    _, [parsed] = parse_cloze(render_cloze(cloze))
    assert [(a.text, a.fraction) for a in parsed.answers] == [
        ("a", 100.0),
        ("b", 100.0),
        ("c", 0.0),
    ]
    numeric = MoodleCloze(
        kind="NUMERICAL",
        answers=[
            MoodleAnswer(text="9.8", fraction=100.0, tolerance=0.1),
            MoodleAnswer(text="10", fraction=100.0),
        ],
    )
    assert render_cloze(numeric) == "{1:NUMERICAL:=9.8:0.1~=10}"

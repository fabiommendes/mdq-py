"""
GIFT and Moodle XML converters and the automation of short answer questions.

Both formats grade every response themselves, so a manual question cannot be
exported. Moodle's "any other answer" idiom (`*`, fraction 0) carries
`incorrectFeedback`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from mdq import models
from mdq.convert import export_question, import_question

FORMATS = ["gift", "moodle-xml"]
STEM = "Qual é a capital do Brasil?"
NOT_THE_CAPITAL = "Not the capital."


def _sa(**fields) -> models.ShortAnswerQuestion:
    return models.ShortAnswerQuestion(stem=STEM, **fields)


def _moodle_answers(question: models.ShortAnswerQuestion) -> list[ET.Element]:
    root = ET.fromstring(export_question(question, format="moodle-xml"))
    return root.findall("./question/answer")


def _moodle_xml(*answers: str) -> str:
    body = "\n".join(answers)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<quiz>\n  <question type="shortanswer">\n'
        f'    <questiontext format="markdown"><text>{STEM}</text></questiontext>\n'
        f"    <defaultgrade>1.0</defaultgrade>\n{body}\n  </question>\n</quiz>\n"
    )


def _answer(text: str, fraction: int, feedback: str | None = None) -> str:
    fb = f"<feedback><text>{feedback}</text></feedback>" if feedback else ""
    return f'    <answer fraction="{fraction}"><text>{text}</text>{fb}</answer>'


#
# AC1: export
#
@pytest.mark.parametrize("format", FORMATS)
@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"unmatched": "manual"},
        {"accept": ["Brasília"], "unmatched": "manual"},
        {"reject": ["Rio"]},
    ],
    ids=[
        "no-pattern",
        "unmatched-manual-no-pattern",
        "accept-unmatched-manual",
        "reject-only",
    ],
)
def test_manual_or_semi_automatic_question_cannot_be_exported(
    format: str, fields: dict
) -> None:
    with pytest.raises(ValueError, match="(?i)unmatched|manual"):
        export_question(_sa(**fields), format=format)


@pytest.mark.parametrize("format", FORMATS)
def test_regex_accept_still_cannot_be_exported(format: str) -> None:
    with pytest.raises(ValueError):
        export_question(_sa(accept=["/Bras[íi]lia/"]), format=format)


@pytest.mark.parametrize("format", FORMATS)
def test_asterisk_exports_as_a_plain_literal(format: str) -> None:
    output = export_question(_sa(accept=["Brasília", "*"]), format=format)
    if format == "gift":
        assert "=*" in output
    else:
        assert [
            a.findtext("text") for a in _moodle_answers(_sa(accept=["Brasília", "*"]))
        ] == [
            "Brasília",
            "*",
        ]


@pytest.mark.parametrize("format", FORMATS)
def test_unmatched_incorrect_with_accept_is_exported(format: str) -> None:
    export_question(_sa(accept=["Brasília"], unmatched="incorrect"), format=format)


def test_moodle_export_writes_incorrect_feedback_as_the_last_catch_all_answer() -> None:
    answers = _moodle_answers(
        _sa(accept=["Brasília"], incorrect_feedback=NOT_THE_CAPITAL)
    )
    assert len(answers) == 2
    last = answers[-1]
    assert float(last.get("fraction")) == 0
    assert last.findtext("text") == "*"
    assert last.findtext("feedback/text") == NOT_THE_CAPITAL


def test_moodle_export_without_incorrect_feedback_has_no_catch_all_answer() -> None:
    answers = _moodle_answers(_sa(accept=["Brasília"]))
    assert [a.findtext("text") for a in answers] == ["Brasília"]


def test_gift_export_ignores_incorrect_feedback() -> None:
    plain = export_question(_sa(accept=["Brasília"]), format="gift")
    with_feedback = export_question(
        _sa(accept=["Brasília"], incorrect_feedback=NOT_THE_CAPITAL), format="gift"
    )
    assert with_feedback == plain
    assert NOT_THE_CAPITAL not in with_feedback


@pytest.mark.parametrize("format", FORMATS)
def test_reject_patterns_are_not_exported_and_do_not_fail(format: str) -> None:
    """Current behavior: `reject` entries (and their feedback) are dropped."""
    question = _sa(
        accept=["Brasília"],
        reject=[
            models.AnswerPattern(pattern="Rio de Janeiro", feedback="Foi até 1960.")
        ],
    )
    output = export_question(question, format=format)
    assert "Rio de Janeiro" not in output
    assert "Foi até 1960." not in output


#
# AC2: import
#
def test_moodle_import_zero_fraction_asterisk_becomes_incorrect_feedback() -> None:
    source = _moodle_xml(_answer("Brasília", 100), _answer("*", 0, NOT_THE_CAPITAL))
    question = import_question(source, format="moodle-xml")
    assert question.incorrect_feedback == NOT_THE_CAPITAL
    assert [p.pattern for p in question.accept] == ["Brasília"]
    assert not question.reject


def test_moodle_import_full_credit_asterisk_becomes_the_catch_all_regex() -> None:
    question = import_question(_moodle_xml(_answer("*", 100)), format="moodle-xml")
    assert [p.pattern for p in question.accept] == ["/.*/"]


def test_moodle_import_keeps_other_texts_and_wraps_a_leading_slash() -> None:
    source = _moodle_xml(
        _answer("Brasília", 100), _answer("/usr/bin", 100), _answer("Plano*", 100)
    )
    question = import_question(source, format="moodle-xml")
    assert [p.pattern for p in question.accept] == ["Brasília", "`/usr/bin`", "Plano*"]


def test_gift_import_keeps_a_lone_asterisk_as_a_plain_literal() -> None:
    question = import_question(f"{STEM} {{=*}}", format="gift")
    assert [p.pattern for p in question.accept] == ["*"]


@pytest.mark.parametrize(
    ("format", "source"),
    [
        ("gift", f"{STEM} {{=Brasília}}"),
        ("moodle-xml", _moodle_xml(_answer("Brasília", 100))),
    ],
)
def test_imported_short_answer_is_automatic_with_no_unmatched(
    format: str, source: str
) -> None:
    question = import_question(source, format=format)
    assert question.unmatched is None
    assert question.automation == "automatic"


#
# AC3: round trip through Moodle XML
#
def test_moodle_round_trip_keeps_accept_and_incorrect_feedback() -> None:
    original = _sa(
        accept=["Brasília"],
        reject=[
            models.AnswerPattern(pattern="Rio de Janeiro", feedback="Foi até 1960.")
        ],
        incorrect_feedback=NOT_THE_CAPITAL,
    )
    source = export_question(original, format="moodle-xml")
    again = import_question(source, format="moodle-xml")
    assert again.incorrect_feedback == NOT_THE_CAPITAL
    assert [p.pattern for p in again.accept] == ["Brasília"]

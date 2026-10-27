"""
Text formats of GIFT and Moodle XML on import.

`html` text is copied as is (CommonMark carries raw HTML). `plain` text has its
Markdown punctuation escaped and its line breaks kept as hard breaks. GIFT
auto-format (no prefix), Moodle `moodle_auto_format` and `markdown` are copied
as is. A Moodle XML element without `format`, or with an unknown one, is `html`.
"""

from __future__ import annotations

import pytest

from mdq import models
from mdq.convert import import_question
from mdq.convert._base import plain_text_to_markdown
from mdq.convert._moodle_xml import MoodleXmlParser


def _xml(
    questiontext: str,
    *,
    qformat: str | None = "html",
    answers: str = "",
    qtype: str = "multichoice",
    extra: str = "",
) -> str:
    attr = f' format="{qformat}"' if qformat is not None else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<quiz>\n'
        f'  <question type="{qtype}">\n'
        f"    <questiontext{attr}><text><![CDATA[{questiontext}]]></text></questiontext>\n"
        f"{extra}{answers}\n  </question>\n</quiz>\n"
    )


def _choice(text: str, fraction: int, fmt: str | None = None, feedback: str = "") -> str:
    attr = f' format="{fmt}"' if fmt else ""
    fb = f"<feedback{attr}><text><![CDATA[{feedback}]]></text></feedback>" if feedback else ""
    return (
        f'    <answer fraction="{fraction}"{attr}><text><![CDATA[{text}]]></text>{fb}</answer>'
    )


# ---------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    ("plain", "markdown"),
    [
        ("Quanto é 2 * 3 * 4?", r"Quanto é 2 \* 3 \* 4?"),
        ("snake_case e [^x] e <b>", r"snake\_case e \[^x\] e \<b\>"),
        ("Tom & Jerry", r"Tom \& Jerry"),
        ("# título", r"\# título"),
        ("- item", r"\- item"),
        ("1. um", r"1\. um"),
        ("linha um\nlinha dois", "linha um\\\nlinha dois"),
        ("linha um\r\nlinha dois", "linha um\\\nlinha dois"),
        ("par um\n\npar dois", "par um\n\npar dois"),
        ("Brasília, capital.", "Brasília, capital."),
    ],
)
def test_plain_text_to_markdown(plain: str, markdown: str) -> None:
    assert plain_text_to_markdown(plain) == markdown


# ---------------------------------------------------------------------
# Moodle XML
# ---------------------------------------------------------------------
def test_missing_format_is_html() -> None:
    block = MoodleXmlParser(_xml("<p>Oi</p>", qformat=None)).parse().blocks[0]
    assert block.text_format == "html"


def test_moodle_auto_format_is_accepted_and_unknown_is_html() -> None:
    auto = MoodleXmlParser(_xml("Oi", qformat="moodle_auto_format")).parse().blocks[0]
    wiki = MoodleXmlParser(_xml("Oi", qformat="wiki_like")).parse().blocks[0]
    other = MoodleXmlParser(_xml("Oi", qformat="rst")).parse().blocks[0]
    assert (auto.text_format, wiki.text_format, other.text_format) == (
        "moodle_auto_format",
        "html",
        "html",
    )


def test_html_is_copied_as_is() -> None:
    answers = _choice("<b>Brasília</b>", 100, "html", "<p>Isso!</p>") + _choice("Rio", 0)
    q = import_question(
        _xml("<p>Qual é a <b>capital</b> do Brasil?</p>", answers=answers),
        format="moodle-xml",
    )
    assert q.stem == "<p>Qual é a <b>capital</b> do Brasil?</p>"
    assert [c.text for c in q.choices] == ["<b>Brasília</b>", "Rio"]
    assert q.choices[0].feedback == "<p>Isso!</p>"


@pytest.mark.parametrize("fmt", ["moodle_auto_format", "markdown"])
def test_auto_format_and_markdown_are_copied_as_is(fmt: str) -> None:
    q = import_question(
        _xml("Quanto é 2 * 3?\nSegunda linha", qformat=fmt, answers=_choice("6", 100) + _choice("7", 0)),
        format="moodle-xml",
    )
    assert q.stem == "Quanto é 2 * 3?\nSegunda linha"


def test_plain_text_is_escaped() -> None:
    answers = _choice("2 * 3", 100, "plain_text", "dois * três") + _choice("5", 0, "plain_text")
    q = import_question(
        _xml("Quanto é 2 * 3 * 4?\nSegunda linha", qformat="plain_text", answers=answers),
        format="moodle-xml",
    )
    assert q.stem == "Quanto é 2 \\* 3 \\* 4?\\\nSegunda linha"
    assert q.choices[0].text == "2 \\* 3"
    assert q.choices[0].feedback == "dois \\* três"


def test_each_element_has_its_own_format() -> None:
    answers = _choice("a * b", 100, "plain_text") + _choice("<i>c</i>", 0)
    q = import_question(_xml("<p>x * y</p>", answers=answers), format="moodle-xml")
    assert q.stem == "<p>x * y</p>"
    assert [c.text for c in q.choices] == ["a \\* b", "<i>c</i>"]


def test_plain_text_cloze_keeps_the_blank_syntax() -> None:
    xml = _xml(
        "A capital * é {1:MULTICHOICE:=Brasília~Rio}.",
        qformat="plain_text",
        qtype="multianswer",
    )
    q = import_question(xml, format="moodle-xml")
    assert q.stem == "A capital \\* é [^blank1]."
    assert [c.text for c in q.blanks[0].choices] == ["Brasília", "Rio"]


def test_plain_text_general_feedback_and_essay_answer_key() -> None:
    extra = (
        '    <generalfeedback format="plain_text"><text>a * b</text></generalfeedback>\n'
        '    <graderinfo format="plain_text"><text>c * d</text></graderinfo>\n'
    )
    q = import_question(
        _xml("Explique.", qtype="essay", extra=extra), format="moodle-xml"
    )
    assert q.answer_key == "c \\* d"
    assert q.meta == {"generalFeedback": "a \\* b"}


# ---------------------------------------------------------------------
# GIFT
# ---------------------------------------------------------------------
def test_gift_html_is_copied_as_is() -> None:
    q = import_question(
        "[html]<p>Qual é a <b>capital</b>?</p> {=<b>Brasília</b>#<p>Isso!</p> ~Rio}",
        format="gift",
    )
    assert q.stem == "<p>Qual é a <b>capital</b>?</p>"
    assert q.choices[0].text == "<b>Brasília</b>"
    assert q.choices[0].feedback == "<p>Isso!</p>"


def test_gift_plain_is_escaped() -> None:
    q = import_question(
        "[plain]Quanto é 2 * 3 * 4? {=12#três * quatro ~10}", format="gift"
    )
    assert q.stem == "Quanto é 2 \\* 3 \\* 4?"
    assert q.choices[0].feedback == "três \\* quatro"


@pytest.mark.parametrize("prefix", ["", "[moodle]", "[markdown]"])
def test_gift_auto_format_and_markdown_are_copied_as_is(prefix: str) -> None:
    q = import_question(f"{prefix}Quanto é 2 * 3 * 4? {{=12 ~10}}", format="gift")
    assert q.stem == "Quanto é 2 * 3 * 4?"


def test_gift_plain_missing_word_and_short_answer_feedback() -> None:
    q = import_question("[plain]A taxa de * é {=Selic#sim *}.", format="gift")
    assert isinstance(q, models.FillInQuestion)
    assert q.stem == "A taxa de \\* é [^blank]."
    assert q.blanks[0].accept[0].feedback == "sim \\*"

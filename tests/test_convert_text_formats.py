"""
Text formats of GIFT and Moodle XML on import.

`html` text is wrapped in one `<div>` HTML block, without blank lines, only if it is a
whole block of the document (stem without blanks, general feedback, grader info).
Other `html` text is copied as is. `plain` text has its
Markdown punctuation escaped and its line breaks kept as hard breaks. GIFT
auto-format (no prefix), Moodle `moodle_auto_format` and `markdown` are copied
as is. A Moodle XML element without `format`, or with an unknown one, is `html`.
"""

from __future__ import annotations

import html as html_lib

import pytest
from markdown_it import MarkdownIt

from mdq import models
from mdq.convert import import_question
from mdq.convert._text import html_to_mdq, plain_text_to_markdown
from mdq.convert._moodle_xml import MoodleXmlParser

# These tests convert with losses on purpose: the warnings are expected.
pytestmark = pytest.mark.filterwarnings("ignore::mdq.errors.ConversionWarning")


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
    assert q.stem == "<div><p>Qual é a <b>capital</b> do Brasil?</p></div>"
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
    assert q.stem == "<div><p>x * y</p></div>"
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
def test_gift_html_stem_is_wrapped_only() -> None:
    q = import_question(
        "[html]<p>Qual é a <b>capital</b>?</p> {=<b>Brasília</b>#<p>Isso!</p> ~Rio}",
        format="gift",
    )
    assert q.stem == "<div><p>Qual é a <b>capital</b>?</p></div>"
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


# ---------------------------------------------------------------------
# HTML text is one HTML block
# ---------------------------------------------------------------------
_MD = MarkdownIt("commonmark")


def _render(markdown: str) -> str:
    return _MD.render(markdown)


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (
            "<p>Um barco desce o rio São Francisco.</p>\n\n    Use v = d / t.\n\nA velocidade é dada em *km/h*?",
            "<div><p>Um barco desce o rio São Francisco.</p>\nUse v = d / t.\nA velocidade é dada em *km/h*?</div>",
        ),
        ("<b>Cerrado</b> é *bioma*", "<div><b>Cerrado</b> é *bioma*</div>"),
        ("Ar&nbsp;puro, *sem* &amp; nada", "<div>Ar&nbsp;puro, *sem* &amp; nada</div>"),
        ("  \r\n<p>a</p>\r\n \r\n<p>b</p>\n  ", "<div><p>a</p>\n<p>b</p></div>"),
        (
            "<pre>linha 1\n\nlinha 3\n \n\nlinha 6</pre>\n\n*fim*",
            "<div><pre>linha 1\n&#10;linha 3\n&#10;&#10;linha 6</pre>\n*fim*</div>",
        ),
        ("   \n ", "   \n "),
        ("", ""),
    ],
)
def test_html_to_mdq(html: str, expected: str) -> None:
    assert html_to_mdq(html) == expected


@pytest.mark.parametrize(
    ("html", "rendered"),
    [
        (
            "<p>Um barco desce o rio São Francisco.</p>\n\n    Use v = d / t.\n\nA velocidade é dada em *km/h*?",
            "<div><p>Um barco desce o rio São Francisco.</p>\nUse v = d / t.\nA velocidade é dada em *km/h*?</div>",
        ),
        ("<b>Cerrado</b> é *bioma*", "<div><b>Cerrado</b> é *bioma*</div>"),
        ("Ar&nbsp;puro", "<div>Ar&nbsp;puro</div>"),
        (
            "<pre>a\n\nb</pre>",
            "<div><pre>a\n&#10;b</pre></div>",
        ),
    ],
)
def test_imported_html_renders_as_one_html_block(html: str, rendered: str) -> None:
    out = _render(html_to_mdq(html))
    assert out.strip() == rendered


def test_blank_line_in_pre_keeps_its_text() -> None:
    out = _render(html_to_mdq("<pre>a\n\nb</pre>"))
    # The browser decodes `&#10;` to a line break: three lines, the middle one empty.
    assert html_lib.unescape(out).strip() == "<div><pre>a\n\nb</pre></div>"


def test_moodle_html_import_renders_as_html() -> None:
    xml = _xml(
        "<p>Um barco desce o rio São Francisco.</p>\n\n    Use v = d / t.\n\nA velocidade é dada em *km/h*?",
        answers=_choice("Sim", 100) + _choice("Não", 0),
    )
    q = import_question(xml, format="moodle-xml")
    assert _render(q.stem).count("<pre>") == 0
    assert "<em>" not in _render(q.stem)
    assert "*km/h*" in _render(q.stem)


def test_moodle_html_cloze_is_copied_as_is() -> None:
    text = "<p>A capital é</p>\n\n{1:MULTICHOICE:=<b>Brasília</b>~Rio} <b>hoje</b>."
    q = import_question(_xml(text, qtype="multianswer"), format="moodle-xml")
    assert q.stem == "A capital é\n\n[^blank1] <b>hoje</b>."
    assert [c.text for c in q.blanks[0].choices] == ["<b>Brasília</b>", "Rio"]


def test_moodle_html_general_feedback_and_grader_info_are_wrapped() -> None:
    extra = (
        "    <generalfeedback><text><![CDATA[<b>a</b>\n\n*b*]]></text></generalfeedback>\n"
        "    <graderinfo><text><![CDATA[<i>c</i>\n\n*d*]]></text></graderinfo>\n"
    )
    q = import_question(_xml("Redija.", qtype="essay", extra=extra), format="moodle-xml")
    assert q.answer_key == "<div><i>c</i>\n*d*</div>"
    assert q.meta["generalFeedback"] == "<div><b>a</b>\n*b*</div>"


def test_moodle_html_short_and_numeric_stem_is_wrapped_patterns_are_not() -> None:
    short = import_question(
        _xml("<p>Capital?</p>", qtype="shortanswer", answers=_choice("Brasília", 100, feedback="<p>ok</p>")),
        format="moodle-xml",
    )
    assert short.stem == "<div><p>Capital?</p></div>"
    assert [(p.pattern, p.feedback) for p in short.accept] == [("Brasília", "<p>ok</p>")]
    numeric = import_question(
        _xml(
            "<p>Quanto?</p>",
            qtype="numerical",
            answers='    <answer fraction="100"><text>3.14</text><tolerance>0</tolerance></answer>',
        ),
        format="moodle-xml",
    )
    assert numeric.stem == "<div><p>Quanto?</p></div>"
    assert numeric.answer == 3.14


def test_gift_html_stem_is_wrapped_choices_are_not() -> None:
    q = import_question(
        "::q:: [html]<p>Capital?</p>\n\n    texto *x* {=<b>Brasília</b> ~Rio #<i>não</i>}", format="gift"
    )
    assert q.stem == "<div><p>Capital?</p>\ntexto *x*</div>"
    assert q.choices[0].text == "<b>Brasília</b>"
    assert q.choices[1].feedback == "<i>não</i>"


def test_gift_html_short_answer_stem_is_wrapped() -> None:
    q = import_question("[html]<p>Capital?</p> {=Brasília #<i>ok</i>}", format="gift")
    assert q.stem == "<div><p>Capital?</p></div>"
    assert [p.pattern for p in q.accept] == ["Brasília"]


def test_gift_html_missing_word_is_copied_as_is() -> None:
    src = "::Bioma::[html]O bioma {=Cerrado ~Pantanal} cobre o <b>MS</b>."
    q = import_question(src, format="gift")
    assert q.stem == "O bioma [^blank] cobre o <b>MS</b>."
    assert [c.text for c in q.blanks[0].choices] == ["Cerrado", "Pantanal"]


def _stem_html(stem: str) -> str:
    return MarkdownIt("commonmark").render(stem)


_BIOMA_GIFT = "::Bioma::[html]<p>O bioma {=Cerrado ~Pantanal} cobre o <b>MS</b>.</p>"


def test_gift_html_missing_word_in_a_paragraph_is_inline() -> None:
    q = import_question(_BIOMA_GIFT, format="gift")
    assert q.stem == "O bioma [^blank] cobre o <b>MS</b>."
    assert [c.text for c in q.blanks[0].choices] == ["Cerrado", "Pantanal"]
    assert _stem_html(q.stem) == "<p>O bioma [^blank] cobre o <b>MS</b>.</p>\n"


def test_moodle_html_cloze_in_a_paragraph_is_inline() -> None:
    text = "<p>O bioma {1:MULTICHOICE:=Cerrado~Pantanal} cobre o <b>MS</b>.</p>"
    q = import_question(_xml(text, qtype="multianswer"), format="moodle-xml")
    assert q.stem == "O bioma [^blank1] cobre o <b>MS</b>."
    assert _stem_html(q.stem) == "<p>O bioma [^blank1] cobre o <b>MS</b>.</p>\n"


def test_html_cloze_paragraphs_are_separated_by_one_blank_line() -> None:
    text = (
        "<p>O Pantanal fica no\n\n  Centro-Oeste.</p>\n\n"
        "<p>O bioma {1:SHORTANSWER:=Cerrado} cobre o MS.</p>\n"
    )
    q = import_question(_xml(text, qtype="multianswer"), format="moodle-xml")
    assert q.stem == "O Pantanal fica no Centro-Oeste.\n\nO bioma [^blank1] cobre o MS."
    assert _stem_html(q.stem).count("<p>") == 2
    assert "<p>O bioma [^blank1] cobre o MS.</p>" in _stem_html(q.stem)


def test_html_cloze_paragraph_attributes_are_dropped() -> None:
    text = '<p dir="ltr" class="x">O bioma {1:SHORTANSWER:=Cerrado} cobre o MS.</p>'
    q = import_question(_xml(text, qtype="multianswer"), format="moodle-xml")
    assert q.stem == "O bioma [^blank1] cobre o MS."


def test_html_cloze_in_a_div_is_rejected_with_the_tag() -> None:
    src = "::Bioma::[html]<div>O bioma {=Cerrado ~Pantanal} cobre o MS.</div>"
    with pytest.raises(ValueError, match=r"<div>.*--html markdown"):
        import_question(src, format="gift")
    text = "<table><tr><td>{1:SHORTANSWER:=Cerrado}</td></tr></table>"
    with pytest.raises(ValueError, match=r"<table>"):
        import_question(_xml(text, qtype="multianswer"), format="moodle-xml")


def test_html_cloze_block_tag_without_a_marker_is_kept() -> None:
    text = "<div>Leia.</div>\n\n<p>O bioma {1:SHORTANSWER:=Cerrado} cobre o MS.</p>"
    q = import_question(_xml(text, qtype="multianswer"), format="moodle-xml")
    assert q.stem == "<div>Leia.</div>\n\nO bioma [^blank1] cobre o MS."

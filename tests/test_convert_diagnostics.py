"""
Converter diagnostics (dev/specs/to-do/converter-diagnostics.md): every
row of the inventory with a code, through `load_question` and
`dump_question`, the simple calls, the CLI, and the registry.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mdq import Diagnostic
from mdq.cli import app
from mdq.convert import (
    CONVERTER_CODES,
    Converted,
    dump_question,
    export_question,
    import_question,
    load_question,
)
from mdq.errors import ConversionError, ConversionWarning
from mdq.models import (
    BooleanChoice,
    ChoiceBlank,
    EssayQuestion,
    FillInQuestion,
    MultipleChoiceQuestion,
    MultipleSelectionQuestion,
    NumericBlank,
    NumericQuestion,
    OrderingQuestion,
    Question,
    ScoredChoice,
    ShortAnswerBlank,
    ShortAnswerQuestion,
    Statement,
    TrueFalseQuestion,
)

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "mdq-py" / "README.md"


def found(converted: Converted[object]) -> list[tuple[str, str, tuple[str | int, ...]]]:
    return [(d.severity, d.code, d.path) for d in converted.diagnostics]


def dump(question: Question, format: str, *codes: tuple[str, str, tuple[str | int, ...]]) -> str:
    """Export `question`, check that every diagnostic in `codes` is there, return the text."""
    converted = dump_question(question, format=format)
    for code in codes:
        assert code in found(converted), (code, found(converted))
    assert converted.value is not None, found(converted)
    return converted.value


def load(source: str, format: str, *codes: tuple[str, str, tuple[str | int, ...]]) -> Question:
    converted = load_question(source, format=format)
    for code in codes:
        assert code in found(converted), (code, found(converted))
    assert converted.value is not None, found(converted)
    return converted.value


def error_code(converted: Converted[object]) -> str:
    assert converted.value is None
    return next(d.code for d in converted.diagnostics if d.severity == "error")


def xml(qtype: str, body: str, text: str = "Qual?", extra: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<quiz>\n'
        f'<question type="{qtype}"><questiontext format="markdown"><text>{text}</text>'
        f"</questiontext>{extra}{body}</question></quiz>"
    )


def mc(**fields: object) -> MultipleChoiceQuestion:
    choices = fields.pop("choices", None) or [
        ScoredChoice(text="Brasília", score=1.0),
        ScoredChoice(text="Rio", score=0.0),
    ]
    fields.setdefault("stem", "Capital?")
    return MultipleChoiceQuestion(choices=choices, **fields)  # type: ignore[arg-type]


GIFT_AND_XML = ["gift", "moodle-xml"]


# ---------------------------------------------------------------------
# Rows of the inventory: export
# ---------------------------------------------------------------------
@pytest.mark.parametrize("format", GIFT_AND_XML)
def test_x1_score_rounded(format: str) -> None:
    question = mc(choices=[ScoredChoice(text="a", score=1.0), ScoredChoice(text="b", score=0.35)])
    dump(question, format, ("warning", "score-rounded", ("choices", 1, "score")))
    blank = ChoiceBlank(
        id="b",
        choices=[ScoredChoice(text="a", score=1.0), ScoredChoice(text="b", score=0.35)],
    )
    fill = FillInQuestion(stem="Capital [^b].", blanks=[blank])
    if format == "gift":
        dump(fill, format, ("warning", "score-rounded", ("blanks", 0, "choices", 1, "score")))


def test_x1_selection_share_is_rounded() -> None:
    question = MultipleSelectionQuestion(
        stem="Quais?",
        choices=[BooleanChoice(text=str(i), correct=i < 11) for i in range(12)],
    )
    dump(question, "moodle-xml", ("warning", "score-rounded", ("choices", 0)))


@pytest.mark.parametrize("format", GIFT_AND_XML)
def test_x2_inexact_answer(format: str) -> None:
    dump(
        NumericQuestion(stem="Fração?", answer="1/3"),
        format,
        ("warning", "inexact-answer", ("answer",)),
    )


@pytest.mark.parametrize("format", GIFT_AND_XML)
def test_x3_x4_x5_short_answer(format: str) -> None:
    manual = ShortAnswerQuestion(stem="Rio?", accept=["Amazonas"], unmatched="manual")
    dump(manual, format, ("warning", "manual-grading-dropped", ("unmatched",)))
    regex = ShortAnswerQuestion(stem="Rio?", accept=["Amazonas", "/Amaz[oô]nas/"])
    text = dump(regex, format, ("warning", "regex-dropped", ("accept", 1)))
    assert "Amaz[o" not in text
    only_regex = dump_question(
        ShortAnswerQuestion(stem="Rio?", accept=["/Amaz/"]), format=format
    )
    assert error_code(only_regex) == "no-accept"
    assert ("warning", "regex-dropped", ("accept", 0)) in found(only_regex)
    assert error_code(dump_question(ShortAnswerQuestion(stem="Rio?"), format=format)) == "no-accept"


@pytest.mark.parametrize("format", GIFT_AND_XML)
def test_x6_general_feedback(format: str) -> None:
    dump(
        mc(meta={"generalFeedback": 3}),
        format,
        ("warning", "general-feedback-dropped", ("meta", "generalFeedback")),
    )


@pytest.mark.parametrize(
    ("question", "format"),
    [
        (MultipleSelectionQuestion(stem="Q", choices=[BooleanChoice(text="a", correct=True), BooleanChoice(text="b", correct=False)]), "gift"),
        (OrderingQuestion(content="text", stem="Q", lines=[(0, "a"), (0, "b")]), "gift"),
        (OrderingQuestion(content="text", stem="Q", lines=[(0, "a"), (0, "b")]), "moodle-xml"),
        (EssayQuestion(stem="Q"), "aiken"),
        (NumericQuestion(stem="Q", answer=1), "aiken"),
    ],
)
def test_x12_to_x15_unsupported_type(question: Question, format: str) -> None:
    converted = dump_question(question, format=format)
    assert error_code(converted) == "unsupported-type"
    with pytest.raises(ConversionError) as raised:
        export_question(question, format=format)
    assert raised.value.code == "unsupported-type"
    assert not isinstance(raised.value, TypeError)


def test_x16_too_many_choices() -> None:
    question = mc(choices=[ScoredChoice(text=str(i), score=float(i == 0)) for i in range(27)])
    assert error_code(dump_question(question, format="aiken")) == "too-many-choices"


def test_x17_gift_essay_with_answer_key_and_general_feedback() -> None:
    question = EssayQuestion(stem="Q", answer_key="Chave", meta={"generalFeedback": "Geral"})
    text = dump(
        question, "gift", ("warning", "general-feedback-dropped", ("meta", "generalFeedback"))
    )
    assert "#### Chave" in text


def test_x18_multiple_blanks() -> None:
    question = FillInQuestion(
        stem="[^a] e [^b]",
        blanks=[NumericBlank(id="a", answer=1), NumericBlank(id="b", answer=2)],
    )
    assert error_code(dump_question(question, format="gift")) == "multiple-blanks"
    dump(question, "moodle-xml")


def test_x23_cloze_blank_without_full_credit() -> None:
    blank = ChoiceBlank(
        id="b", choices=[ScoredChoice(text="a", score=0.5), ScoredChoice(text="b", score=0.0)]
    )
    converted = dump_question(FillInQuestion(stem="[^b]", blanks=[blank]), format="moodle-xml")
    assert error_code(converted) == "no-full-credit"
    assert converted.diagnostics[-1].path == ("blanks", 0)


def test_x24_cloze_text() -> None:
    blank = ChoiceBlank(
        id="b", choices=[ScoredChoice(text="a~b", score=1.0), ScoredChoice(text="c", score=0.0)]
    )
    text = dump(
        FillInQuestion(stem="[^b]", blanks=[blank]),
        "moodle-xml",
        ("warning", "cloze-text-changed", ("blanks", 0, "choices", 0, "text")),
    )
    assert "a&amp;\\#126;b" in text
    short = ShortAnswerBlank(id="b", accept=["`a~b`", "ok"])
    text = dump(
        FillInQuestion(stem="[^b]", blanks=[short]),
        "moodle-xml",
        ("warning", "answer-dropped", ("blanks", 0, "accept", 0)),
    )
    assert "a~b" not in text and "ok" in text


def test_x24_short_blank_with_nothing_left() -> None:
    short = ShortAnswerBlank(id="b", accept=["`a~b`"])
    converted = dump_question(FillInQuestion(stem="[^b]", blanks=[short]), format="moodle-xml")
    assert error_code(converted) == "no-accept"


def test_invalid_xml_character_is_an_error() -> None:
    converted = dump_question(mc(choices=[ScoredChoice(text="a\x0c", score=1.0), ScoredChoice(text="b", score=0.0)]), format="moodle-xml")
    assert error_code(converted) == "invalid-xml-character"


# ---------------------------------------------------------------------
# Rows of the inventory: import
# ---------------------------------------------------------------------
def test_x7_x9_x10_x11_numeric_key() -> None:
    star = load(
        "Ano? {#=1822 =%100%*}",
        "gift",
        ("warning", "answer-dropped", ("answer",)),
    )
    assert star.answer == 1822  # type: ignore[union-attr]
    converted = load_question("Ano? {#=%100%*}", format="gift")
    assert error_code(converted) == "no-full-credit"
    load(
        "Ano? {#=1822 =1823}",
        "gift",
        ("warning", "answer-dropped", ("answer",)),
    )
    best = load(
        "Ano? {#=%25%1 =%50%2}",
        "gift",
        ("warning", "partial-credit-dropped", ("answer",)),
    )
    assert best.answer == 2  # type: ignore[union-attr]


def test_x8_wildcard_regex_matches_the_whole_response() -> None:
    q = load(
        "Qual? {=Mata *}",
        "gift",
        ("warning", "wildcard-to-regex", ("accept", 0)),
    )
    assert isinstance(q, ShortAnswerQuestion)
    assert q.score_response("mata atlântica").score == 1
    assert q.score_response("a Mata Atlântica").score == 0
    # A special character of a regex is a literal one.
    q = load("Qual? {=(a+)*.b}", "gift", ("warning", "wildcard-to-regex", ("accept", 0)))
    assert isinstance(q, ShortAnswerQuestion)
    assert q.score_response("(a+)xyz.b").score == 1
    assert q.score_response("aab").score == 0


def test_x25_x26_multiple_questions_and_no_question() -> None:
    assert error_code(load_question("A? {=a ~b}\n\nB? {=c ~d}", format="gift")) == "multiple-questions"
    assert error_code(load_question("<quiz></quiz>", format="moodle-xml")) == "no-question"
    two = xml("shortanswer", '<answer fraction="100"><text>a</text></answer>')
    both = two.replace("</quiz>", two.split("<quiz>")[1])
    assert error_code(load_question(both, format="moodle-xml")) == "multiple-questions"


@pytest.mark.parametrize("answer", ["{T}", "{F}"])
def test_x27_true_false_with_a_tail_is_a_fill_in(answer: str) -> None:
    q = load("A capital é Brasília: " + answer + " mesmo.", "gift")
    assert isinstance(q, FillInQuestion)
    [blank] = q.blanks
    assert isinstance(blank, ChoiceBlank)
    assert [c.text for c in blank.choices] == ["True", "False"]
    assert [c.score for c in blank.choices] == ([1.0, 0.0] if answer == "{T}" else [0.0, 1.0])


def test_x28_essay_with_a_tail() -> None:
    q = load("Explique {} sua resposta.", "gift", ("warning", "missing-word-joined", ("stem",)))
    assert isinstance(q, EssayQuestion)
    assert q.stem == "Explique sua resposta."


def test_x29_unsupported_moodle_type() -> None:
    converted = load_question(xml("matching", ""), format="moodle-xml")
    assert error_code(converted) == "unsupported-type"
    # `category` is still skipped.
    source = xml("shortanswer", '<answer fraction="100"><text>a</text></answer>')
    source = source.replace("<quiz>", '<quiz><question type="category"/>')
    load(source, "moodle-xml")


def test_x30_unterminated_blank() -> None:
    source = xml("multianswer", "", text="Capital {1:SHORTANSWER:=Brasília")
    assert error_code(load_question(source, format="moodle-xml")) == "syntax-error"


def test_x31_cloze_kinds() -> None:
    source = xml("multianswer", "", text="Capital {1:SAC:=Brasília}.")
    q = load(
        source,
        "moodle-xml",
        ("warning", "case-sensitivity-dropped", ("blanks", 0)),
    )
    assert isinstance(q, FillInQuestion) and isinstance(q.blanks[0], ShortAnswerBlank)
    source = xml("multianswer", "", text="Capital {1:MULTIRESPONSE:=Brasília}.")
    assert error_code(load_question(source, format="moodle-xml")) == "unsupported-cloze-kind"


def test_x32_syntax_errors_have_a_line() -> None:
    for format, source in (("gift", "Qual?\n\n{=a\n"), ("moodle-xml", "<quiz>"), ("aiken", "x")):
        converted = load_question(source, format=format)
        assert error_code(converted) == "syntax-error"
        assert converted.diagnostics[-1].line is not None


# ---------------------------------------------------------------------
# Rows of the inventory: silent losses
# ---------------------------------------------------------------------
def test_s3_s4_s5_numeric_answers() -> None:
    answers = (
        '<answer fraction="100"><text>1822</text><feedback><text>Isso!</text></feedback></answer>'
        '<answer fraction="100"><text>1822</text></answer>'
        '<answer fraction="0"><text>1</text><feedback><text>Não.</text></feedback></answer>'
    )
    converted = load_question(xml("numerical", answers), format="moodle-xml")
    assert found(converted) == [
        ("warning", "answer-dropped", ("answer",)),
        ("warning", "answer-dropped", ("answer",)),
        ("warning", "feedback-dropped", ("answer",)),
    ]


def test_s6_fill_in_with_a_manual_short_answer_blank() -> None:
    short = ShortAnswerBlank(id="b", accept=["Brasília"], unmatched=None)
    question = FillInQuestion(stem="Capital [^b].", blanks=[short], unmatched="manual")
    for format in GIFT_AND_XML:
        dump(question, format, ("warning", "manual-grading-dropped", ("blanks", 0)))


def test_s7_s8_grading_changed() -> None:
    question = MultipleSelectionQuestion(
        stem="Quais?",
        choices=[BooleanChoice(text="a", correct=True), BooleanChoice(text="b", correct=False)],
    )
    text = dump(question, "moodle-xml", ("warning", "grading-changed", ("grading",)))
    q = load(text, "moodle-xml", ("warning", "grading-changed", ("grading",)))
    assert isinstance(q, MultipleSelectionQuestion)
    assert [c.correct for c in q.choices] == [True, False]


def test_s9_blank_weight() -> None:
    source = xml("multianswer", "", text="Capital {2:SHORTANSWER:=Brasília}.")
    load(source, "moodle-xml", ("warning", "blank-weight-dropped", ("blanks", 0)))


def test_s10_units() -> None:
    answer = '<answer fraction="100"><text>3</text></answer>'
    units = (
        "<units><unit><unit_name>m (metro)</unit_name><unit_multiplier>1</unit_multiplier></unit>"
        "<unit><unit_name>km</unit_name><unit_multiplier>1000</unit_multiplier></unit></units>"
    )
    q = load(
        xml("numerical", answer + units),
        "moodle-xml",
        ("warning", "unit-changed", ("unit",)),
    )
    assert isinstance(q, NumericQuestion)
    assert q.unit == "mmetro"
    converted = load_question(xml("numerical", answer + units), format="moodle-xml")
    assert [d.code for d in converted.diagnostics] == ["unit-changed", "unit-changed"]


def test_s11_s12_s13_essay_elements() -> None:
    extra = (
        "<responseformat>noinline</responseformat>"
        '<file name="a.png" encoding="base64">AAAA</file>'
        "<hint><text>Dica</text></hint>"
    )
    converted = load_question(xml("essay", extra), format="moodle-xml")
    assert ("warning", "field-dropped", ("content",)) in found(converted)
    assert ("warning", "embedded-file-dropped", ()) in found(converted)
    assert ("warning", "field-dropped", ()) in found(converted)
    plugin = xml("essay", "", text="Veja @@PLUGINFILE@@/a.png")
    assert ("warning", "embedded-file-dropped", ()) in found(
        load_question(plugin, format="moodle-xml")
    )


def test_s14_true_false_group_fields() -> None:
    def block(name: str) -> str:
        return (
            f'<question type="truefalse"><name><text>{name}</text></name>'
            f'<questiontext format="markdown"><text>Julgue.\n\n{name}</text></questiontext>'
            '<answer fraction="100"><text>true</text></answer>'
            '<answer fraction="0"><text>false</text></answer></question>'
        )

    source = f"<quiz>{block('Um')}{block('Dois')}</quiz>"
    q = load(source, "moodle-xml", ("warning", "field-dropped", ("title",)))
    assert q.title == "Um"
    gift = "::Um:: Julgue.\n\nA {T}\n\n::Dois:: Julgue.\n\nB {F}"
    load(gift, "gift", ("warning", "field-dropped", ("title",)))


def test_s16_s17_aiken() -> None:
    question = mc(
        choices=[
            ScoredChoice(text="a", score=0.5),
            ScoredChoice(text="b\nc", score=1.0),
            ScoredChoice(text="d", score=1.0),
        ]
    )
    text = dump(
        question,
        "aiken",
        ("warning", "partial-credit-dropped", ("choices",)),
        ("warning", "line-breaks-dropped", ("choices", 1, "text")),
    )
    assert "ANSWER: b" in text


@pytest.mark.parametrize("format", GIFT_AND_XML)
def test_s18_diacritics_not_folded(format: str) -> None:
    question = ShortAnswerQuestion(stem="Capital?", accept=["Brasília"])
    dump(question, format, ("warning", "diacritics-not-folded", ("accept", 0)))
    kept = ShortAnswerQuestion(stem="Capital?", accept=["Brasília"], diacritics="keep")
    assert "diacritics-not-folded" not in [d.code for d in dump_question(kept, format=format).diagnostics]
    exact = ShortAnswerQuestion(stem="Capital?", accept=["`Brasília`"])
    assert "diacritics-not-folded" not in [d.code for d in dump_question(exact, format=format).diagnostics]


FIELDS = dict(
    id="q1",
    tags=["geo"],
    weight=2.0,
    shuffle=True,
    author="Ana",
    uuid="12345678-1234-4234-8234-123456789012",
    locale="pt-BR",
    meta={"fonte": "IBGE"},
)


def test_s20_gift_fields() -> None:
    converted = dump_question(mc(comment="nota", **FIELDS), format="gift")
    assert converted.value is not None
    by_code = {(d.severity, d.code, d.path) for d in converted.diagnostics}
    for field in ("tags", "weight", "shuffle"):
        assert ("warning", "field-dropped", (field,)) in by_code
    for field in ("id", "author", "uuid", "locale"):
        assert ("info", "metadata-dropped", (field,)) in by_code
    assert ("info", "metadata-dropped", ("meta", "fonte")) in by_code
    # `comment` is a `//` comment line in GIFT.
    assert ("info", "metadata-dropped", ("comment",)) not in by_code
    assert "// nota" in converted.value
    # Choice comment, numeric unit, domain and decimal places.
    choices = [ScoredChoice(text="a", score=1.0, comment="c"), ScoredChoice(text="b", score=0.0)]
    dump(mc(choices=choices), "gift", ("info", "metadata-dropped", ("choices", 0, "comment")))
    numeric = NumericQuestion(stem="Q", answer=1, unit="m", domain="integer", decimal_places=2)
    dump(
        numeric,
        "gift",
        ("warning", "field-dropped", ("unit",)),
        ("warning", "field-dropped", ("domain",)),
        ("warning", "field-dropped", ("decimalPlaces",)),
    )
    dump(
        EssayQuestion(stem="Q", content="code", highlight="python"),
        "gift",
        ("warning", "field-dropped", ("content",)),
        ("warning", "field-dropped", ("highlight",)),
    )


def test_s21_moodle_xml_fields() -> None:
    converted = dump_question(mc(comment="nota", **FIELDS), format="moodle-xml")
    by_code = {(d.severity, d.code, d.path) for d in converted.diagnostics}
    # Kept by Moodle XML: `id`, `tags`, `weight` and `shuffle`.
    assert not {path for _, code, path in by_code if code == "field-dropped"}
    for field in ("comment", "author", "uuid", "locale"):
        assert ("info", "metadata-dropped", (field,)) in by_code
    short = ShortAnswerQuestion(stem="Q", accept=["a"], pre_accept=["b"], pre_reject=["c"])
    dump(
        short,
        "moodle-xml",
        ("warning", "field-dropped", ("preAccept",)),
        ("warning", "field-dropped", ("preReject",)),
    )
    dump(
        TrueFalseQuestion(
            stem="Q",
            choices=[Statement(text="a", correct=True), Statement(text="b", correct=False)],
            grading="partial",
        ),
        "moodle-xml",
        ("warning", "field-dropped", ("grading",)),
    )


def test_s22_aiken_fields() -> None:
    choices = [
        ScoredChoice(text="a", score=1.0, feedback="Sim"),
        ScoredChoice(text="b", score=0.0),
    ]
    converted = dump_question(
        mc(
            choices=choices,
            title="T",
            **{**FIELDS, "meta": {"generalFeedback": "G", "fonte": "IBGE"}},
        ),
        format="aiken",
    )
    by_code = {(d.severity, d.code, d.path) for d in converted.diagnostics}
    for path in (("title",), ("tags",), ("weight",), ("shuffle",)):
        assert ("warning", "field-dropped", path) in by_code
    assert ("info", "metadata-dropped", ("id",)) in by_code
    assert ("warning", "field-dropped", ("choices", 0, "feedback")) in by_code
    assert ("warning", "field-dropped", ("meta", "generalFeedback")) in by_code
    assert ("info", "metadata-dropped", ("meta", "fonte")) in by_code


def test_s23_gift_blank_line_is_read_with_a_warning() -> None:
    source = "Capital\n\ndo Brasil? {\n=Brasília\n\n~Rio\n}"
    converted = load_question(source, format="gift")
    assert converted.value is not None
    assert [(d.code, d.line, d.path) for d in converted.diagnostics] == [
        ("gift-blank-line", 2, ())
    ]
    assert isinstance(converted.value, MultipleChoiceQuestion)


def test_s25_indentation_lost() -> None:
    question = mc()
    code = question.model_copy(update={"stem": "Veja\n\n    x = 1\n\nQual?"})
    dump(code, "gift", ("warning", "indentation-lost", ("stem",)))
    assert "indentation-lost" not in [
        d.code for d in dump_question(code, format="moodle-xml").diagnostics
    ]


# ---------------------------------------------------------------------
# A3: import_question and export_question
# ---------------------------------------------------------------------
def test_a3_error_raises_conversion_error() -> None:
    with pytest.raises(ConversionError) as raised:
        export_question(ShortAnswerQuestion(stem="Q"), format="gift")
    assert isinstance(raised.value, ValueError)
    assert raised.value.code == "no-accept"
    assert raised.value.diagnostics[-1].severity == "error"


def test_a3_warning_is_emitted_and_the_result_returned() -> None:
    question = NumericQuestion(stem="Fração?", answer="1/3")
    with pytest.warns(ConversionWarning, match="tolerance") as record:
        text = export_question(question, format="gift")
    assert "0.3333333333333333" in text
    [warning] = [w.message for w in record if isinstance(w.message, ConversionWarning)]
    assert isinstance(warning, ConversionWarning)
    assert warning.diagnostic.code == "inexact-answer"


def test_a3_info_is_not_emitted(recwarn: pytest.WarningsRecorder) -> None:
    export_question(mc(comment="nota"), format="moodle-xml")
    assert not [w for w in recwarn if issubclass(w.category, ConversionWarning)]


def test_a3_strict_raises_on_a_warning() -> None:
    with pytest.raises(ConversionError, match="tolerance") as raised:
        export_question(NumericQuestion(stem="Q", answer="1/3"), format="gift", strict=True)
    assert raised.value.code == "inexact-answer"
    with pytest.raises(ConversionError):
        import_question("Qual? {=%50%a =b}", format="gift", strict=True)


def test_a3_converted() -> None:
    converted = dump_question(NumericQuestion(stem="Q", answer="1/3"), format="gift")
    assert converted
    assert converted.validate("error") == converted.value
    with pytest.raises(ConversionError):
        converted.validate("warning")
    failed = dump_question(ShortAnswerQuestion(stem="Q"), format="gift")
    assert not failed
    with pytest.raises(ConversionError):
        failed.validate()


def test_unknown_format_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown format"):
        load_question("x", format="nope")
    with pytest.raises(ValueError, match="Unknown format"):
        dump_question(mc(), format="nope")


# ---------------------------------------------------------------------
# A4: CLI
# ---------------------------------------------------------------------
def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


FRACTION = "Fração?\n\n[numeric]: 1/3\n"


def test_a4_warning_writes_the_output(tmp_path: Path) -> None:
    source = _write(tmp_path, "q.mdq.md", FRACTION)
    result = runner.invoke(app, ["export", str(source), "--format", "gift"])
    assert result.exit_code == 0
    assert "0.3333333333333333" in result.stdout
    assert "warning: " in result.stderr and "[inexact-answer] at answer" in result.stderr


def test_a4_strict_writes_nothing(tmp_path: Path) -> None:
    source = _write(tmp_path, "q.mdq.md", FRACTION)
    out = tmp_path / "q.gift"
    result = runner.invoke(app, ["export", str(source), "-o", str(out), "--strict"])
    assert result.exit_code == 1
    assert not out.exists()
    assert "warning: " in result.stderr


def test_a4_error_writes_nothing(tmp_path: Path) -> None:
    source = _write(tmp_path, "q.mdq.md", "Rio?\n\n[short-answer]\n")
    out = tmp_path / "q.gift"
    result = runner.invoke(app, ["export", str(source), "-o", str(out)])
    assert result.exit_code == 1
    assert not out.exists()
    assert "error: " in result.stderr and "[no-accept]" in result.stderr


def test_a4_import_prints_diagnostics(tmp_path: Path) -> None:
    source = _write(tmp_path, "q.gift", "Qual? {=%50%a =b}")
    result = runner.invoke(app, ["import", str(source)])
    assert result.exit_code == 0
    assert "warning: " in result.stderr and "[partial-credit-dropped] at reject/0" in result.stderr
    assert runner.invoke(app, ["import", str(source), "--strict"]).exit_code == 1


# ---------------------------------------------------------------------
# A5: GIFT blank lines
# ---------------------------------------------------------------------
def moodle_questions(text: str) -> list[list[str]]:
    """The questions of `qformat_default::readquestions`: split at a blank line, trim each line."""
    questions: list[list[str]] = []
    current: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.strip(" \t\n\r\0\x0b")
        if line.startswith("//"):
            continue
        if line:
            current.append(line)
        elif current:
            questions.append(current)
            current = []
    if current:
        questions.append(current)
    return questions


GIFT_CASES = [
    mc(stem="Primeiro parágrafo.\n\nSegundo parágrafo.", epilogue="Epílogo.\n\nMais um."),
    ShortAnswerQuestion(stem="A\n\n\nB", accept=["x"], incorrect_feedback="Nada.\n\nNada."),
    EssayQuestion(stem="Explique.", epilogue="Dica 1.\n\nDica 2.", answer_key="Chave.\n\nFim."),
    TrueFalseQuestion(
        stem="Julgue.\n\nAs frases.",
        choices=[Statement(text="A", correct=True), Statement(text="B", correct=False)],
        epilogue="Fim.",
    ),
    FillInQuestion(
        stem="Antes.\n\nA capital é [^b].\n\nDepois.",
        blanks=[ShortAnswerBlank(id="b", accept=["Brasília"])],
        epilogue="Fim.\n\nFim.",
    ),
]


@pytest.mark.parametrize("question", GIFT_CASES, ids=lambda q: q.type)
def test_a5_gift_export_has_no_blank_line_inside_a_question(question: Question) -> None:
    text = dump(question, "gift")
    expected = len(question.choices) if isinstance(question, TrueFalseQuestion) else 1
    assert len(moodle_questions(text)) == expected
    assert import_question(text, format="gift").type == question.type


def test_a5_round_trip_of_a_multi_paragraph_stem_and_a_true_false_group() -> None:
    group = TrueFalseQuestion(
        stem="Julgue.\n\nAs frases.",
        choices=[Statement(text="A", correct=True), Statement(text="B", correct=False)],
    )
    again = import_question(dump(group, "gift"), format="gift")
    assert isinstance(again, TrueFalseQuestion)
    assert again.stem == "Julgue.\n\nAs frases."
    assert [(c.text, c.correct) for c in again.choices] == [("A", True), ("B", False)]
    # GIFT has no epilogue: it is joined to the stem.
    q = import_question(dump(GIFT_CASES[0], "gift"), format="gift")
    assert q.stem == "Primeiro parágrafo.\n\nSegundo parágrafo.\n\nEpílogo.\n\nMais um."
    short = import_question(dump(GIFT_CASES[1], "gift"), format="gift")
    assert short.stem == "A\n\n\nB"
    fill = import_question(dump(GIFT_CASES[4], "gift"), format="gift")
    assert isinstance(fill, FillInQuestion)
    assert fill.stem == "Antes.\n\nA capital é [^blank].\n\nDepois.\nFim.\n\nFim."


# ---------------------------------------------------------------------
# A6: GIFT escapes and any other answer
# ---------------------------------------------------------------------
def test_a6_incorrect_feedback_round_trips() -> None:
    short = ShortAnswerQuestion(stem="Q", accept=["a"], incorrect_feedback="Não")
    text = dump(short, "gift")
    assert "=%0%*#Não" in text
    again = import_question(text, format="gift")
    assert isinstance(again, ShortAnswerQuestion) and again.incorrect_feedback == "Não"
    for blank in (
        ShortAnswerBlank(id="b", accept=["a"], incorrect_feedback="Não"),
        NumericBlank(id="b", answer=1, incorrect_feedback="Não"),
    ):
        text = dump(FillInQuestion(stem="Isto é [^b].", blanks=[blank]), "gift")
        assert "=%0%*#Não" in text
        again = import_question(text, format="gift")
        assert isinstance(again, FillInQuestion)
        assert again.blanks[0].incorrect_feedback == "Não"  # type: ignore[union-attr]


def test_a6_escapes() -> None:
    literal = import_question("Qual? {=\\*}", format="gift")
    assert isinstance(literal, ShortAnswerQuestion)
    assert [p.pattern for p in literal.accept or []] == ["`*`"]
    feedback = import_question("Qual? {=a =%0%*#fb}", format="gift")
    assert isinstance(feedback, ShortAnswerQuestion)
    assert feedback.incorrect_feedback == "fb"
    stem = import_question("Primeiro\\n\\nSegundo {=a ~b}", format="gift")
    assert stem.stem == "Primeiro\n\nSegundo"
    stem = import_question("Use \\* e \\_ e \\\\ {=a ~b}", format="gift")
    assert stem.stem == "Use \\* e \\_ e \\"


# ---------------------------------------------------------------------
# A7: true or false weights
# ---------------------------------------------------------------------
def test_a7_true_false_group_weight() -> None:
    question = TrueFalseQuestion(
        stem="Julgue.",
        weight=3.0,
        choices=[Statement(text=t, correct=True) for t in "ABC"],
    )
    text = dump(question, "moodle-xml")
    grades = [e.text for e in ET.fromstring(text).iter("defaultgrade")]
    assert grades == ["1", "1", "1"]
    again = import_question(text, format="moodle-xml")
    assert again.weight == 3.0
    odd = question.model_copy(update={"weight": 1.0})
    again = import_question(dump(odd, "moodle-xml"), format="moodle-xml")
    assert again.weight == 1.0


# ---------------------------------------------------------------------
# A8: html="markdown"
# ---------------------------------------------------------------------
def test_a8_html_markdown_without_markdownify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "markdownify", None)
    with pytest.raises(ImportError, match=r"html=\"markdown\" needs the markdownify package"):
        load_question("[html] <p>x</p> {=a ~b}", format="gift", html="markdown")
    with pytest.raises(ImportError, match=r"install mdq\[html\]"):
        import_question("[html] <p>x</p> {=a ~b}", format="gift", html="markdown")


def test_a8_cli_without_markdownify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "markdownify", None)
    source = _write(tmp_path, "q.gift", "[html] <p>x</p> {=a ~b}")
    result = runner.invoke(app, ["import", str(source), "--html", "markdown"])
    assert result.exit_code == 2
    assert "error: html=\"markdown\" needs the markdownify package" in result.stderr


def test_a8_unknown_html_mode() -> None:
    with pytest.raises(ValueError, match="html"):
        load_question("x", format="gift", html="nope")  # type: ignore[arg-type]


def test_a8_html_markdown() -> None:
    pytest.importorskip("markdownify")
    q = import_question(
        "[html] <p>Capital do <b>Brasil</b></p> {=Brasília ~Rio}", format="gift", html="markdown"
    )
    assert q.stem == "Capital do **Brasil**"
    source = xml(
        "multianswer",
        "",
        text="&lt;p&gt;A capital do &lt;b&gt;Brasil&lt;/b&gt; é {1:SHORTANSWER:=Brasília}.&lt;/p&gt;"
        "&lt;p&gt;E {1:SHORTANSWER:=Rio} também.&lt;/p&gt;",
    ).replace('format="markdown"', 'format="html"')
    cloze = import_question(source, format="moodle-xml", html="markdown")
    assert isinstance(cloze, FillInQuestion)
    assert "[^blank1]" in cloze.stem and "[^blank2]" in cloze.stem
    assert "**Brasil**" in cloze.stem
    # Without the option, a marker inside a block tag other than `<p>` is an error.
    block = source.replace("&lt;p&gt;", "&lt;div&gt;").replace("&lt;/p&gt;", "&lt;/div&gt;")
    assert error_code(load_question(block, format="moodle-xml")) == "blank-in-html-block"
    assert load_question(block, format="moodle-xml", html="markdown").value is not None


def test_a8_cli_html_markdown(tmp_path: Path) -> None:
    pytest.importorskip("markdownify")
    source = _write(tmp_path, "q.gift", "[html] <p>Capital do <b>Brasil</b></p> {=Brasília ~Rio}")
    result = runner.invoke(app, ["import", str(source), "--html", "markdown"])
    assert result.exit_code == 0
    assert "Capital do **Brasil**" in result.stdout


# ---------------------------------------------------------------------
# A2: the registry
# ---------------------------------------------------------------------
def _readme_table() -> dict[str, str]:
    section = README.read_text(encoding="utf-8").split("### Converter diagnostics")[1]
    section = section.split("\n### ")[0]
    rows = re.findall(r"^\| `([a-z-]+)` \| (error|warning|info) \|", section, re.MULTILINE)
    return dict(rows)


def test_a2_registry_and_readme_agree() -> None:
    table = _readme_table()
    assert table == dict(CONVERTER_CODES)


def test_a2_every_code_in_the_source_is_in_the_registry() -> None:
    used: set[str] = set()
    for path in (ROOT / "mdq-py" / "mdq" / "convert").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        used |= set(re.findall(r"\.(?:warning|info|error)\(\s*\"([a-z-]+)\"", text))
    assert used
    assert used <= set(CONVERTER_CODES), used - set(CONVERTER_CODES)
    # `syntax-error` and `invalid-question` are built without a call to `report`.
    assert set(CONVERTER_CODES) - used <= {"syntax-error", "invalid-question"}


def test_a2_no_registry_code_is_a_lint_code() -> None:
    lint = (ROOT / "docs" / "lint-codes.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"^\| `([a-z-]+)` \|", lint, re.MULTILINE))
    assert listed
    assert not listed & set(CONVERTER_CODES)


def test_diagnostic_type() -> None:
    converted = dump_question(NumericQuestion(stem="Q", answer="1/3"), format="gift")
    assert all(isinstance(d, Diagnostic) for d in converted.diagnostics)


def test_a_number_the_source_gets_wrong_is_a_diagnostic() -> None:
    bad_fraction = xml("shortanswer", '<answer fraction="abc"><text>a</text></answer>')
    converted = load_question(bad_fraction, format="moodle-xml")
    assert error_code(converted) == "syntax-error"
    bad_tolerance = xml("multianswer", "", text="x {1:NUMERICAL:=1:abc}")
    assert error_code(load_question(bad_tolerance, format="moodle-xml")) == "invalid-question"

"""
Tests for `mdq.convert.moodle_xml`: parsing the Moodle XML question format,
rendering it back, and round-tripping through the internal MDQ `Question`
models.

Reference: https://docs.moodle.org/502/en/Moodle_XML_format
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mdq.convert.moodle_xml import (
    MoodleAnswer,
    MoodleCloze,
    MoodleXml,
    MoodleXmlBlock,
    MoodleXmlDecoder,
    MoodleXmlEncoder,
    MoodleXmlParser,
    MoodleXmlQuestion,
    parse_cloze,
    render_cloze,
)
from mdq.convert.parser import ParserError
from mdq.hypothesis.moodle_xml import (
    mdq_text,
    moodle_cloze,
    moodle_essay_block,
    moodle_multichoice_block,
    moodle_numerical_block,
    moodle_shortanswer_block,
    moodle_truefalse_block,
)
from mdq.models import (
    BooleanChoice,
    ChoiceBlank,
    EssayQuestion,
    FillInQuestion,
    MultipleChoiceQuestion,
    MultipleSelectionQuestion,
    NumericBlank,
    NumericQuestion,
    ScoredChoice,
    ShortAnswerQuestion,
    Statement,
    Tolerance,
    TrueFalseQuestion,
)


def parse(source: str) -> MoodleXmlQuestion:
    return MoodleXmlParser(source).parse()


XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'

MULTICHOICE_XML = (
    f"{XML_DECLARATION}\n"
    "<quiz>\n"
    '  <question type="multichoice">\n'
    "    <name><text>Capital</text></name>\n"
    "    <idnumber>mc-capital</idnumber>\n"
    '    <questiontext format="markdown"><text>'
    "<![CDATA[What is the capital of Brazil?]]></text></questiontext>\n"
    '    <generalfeedback format="markdown"><text></text></generalfeedback>\n'
    "    <defaultgrade>1.0</defaultgrade>\n"
    "    <single>true</single>\n"
    "    <shuffleanswers>true</shuffleanswers>\n"
    '    <answer fraction="100" format="markdown">\n'
    "      <text><![CDATA[Brasilia]]></text>\n"
    '      <feedback format="markdown"><text><![CDATA[Correct.]]></text></feedback>\n'
    "    </answer>\n"
    '    <answer fraction="0" format="markdown">'
    "<text><![CDATA[Rio de Janeiro]]></text></answer>\n"
    "    <tags><tag><text>geography</text></tag></tags>\n"
    "  </question>\n"
    "</quiz>\n"
)

TRUEFALSE_XML = (
    f"{XML_DECLARATION}\n"
    "<quiz>\n"
    '  <question type="truefalse">\n'
    "    <name><text>Amazon fact</text></name>\n"
    '    <questiontext format="markdown"><text>'
    "<![CDATA[The Amazon River is the longest river in the world.]]>"
    "</text></questiontext>\n"
    "    <defaultgrade>1.0</defaultgrade>\n"
    '    <answer fraction="100" format="markdown"><text>true</text></answer>\n'
    '    <answer fraction="0" format="markdown"><text>false</text></answer>\n'
    "  </question>\n"
    "</quiz>\n"
)

SHORTANSWER_XML = (
    f"{XML_DECLARATION}\n"
    "<quiz>\n"
    '  <question type="shortanswer">\n'
    "    <name><text>Longest river</text></name>\n"
    '    <questiontext format="markdown"><text>'
    "<![CDATA[Name Brazil's longest river.]]></text></questiontext>\n"
    "    <defaultgrade>1.0</defaultgrade>\n"
    '    <answer fraction="100" format="markdown">'
    "<text><![CDATA[Amazon]]></text></answer>\n"
    '    <answer fraction="100" format="markdown">'
    "<text><![CDATA[Amazon River]]></text></answer>\n"
    "  </question>\n"
    "</quiz>\n"
)

NUMERICAL_XML = (
    f"{XML_DECLARATION}\n"
    "<quiz>\n"
    '  <question type="numerical">\n'
    "    <name><text>Speed of light</text></name>\n"
    '    <questiontext format="markdown"><text>'
    "<![CDATA[Speed of light in vacuum, in units of 10^8 m/s?]]>"
    "</text></questiontext>\n"
    "    <defaultgrade>1.0</defaultgrade>\n"
    '    <answer fraction="100" format="markdown">\n'
    "      <text>3</text>\n"
    "      <tolerance>0.1</tolerance>\n"
    "    </answer>\n"
    "  </question>\n"
    "</quiz>\n"
)

ESSAY_XML = (
    f"{XML_DECLARATION}\n"
    "<quiz>\n"
    '  <question type="essay">\n'
    "    <name><text>Darwin essay</text></name>\n"
    '    <questiontext format="markdown"><text>'
    "<![CDATA[Explain natural selection using an example from Brazilian fauna.]]>"
    "</text></questiontext>\n"
    "    <defaultgrade>1.0</defaultgrade>\n"
    '    <graderinfo format="markdown"><text>'
    "<![CDATA[Look for variation, heredity, selection.]]></text></graderinfo>\n"
    "    <responseformat>editor</responseformat>\n"
    "  </question>\n"
    "</quiz>\n"
)

MULTIANSWER_XML = (
    f"{XML_DECLARATION}\n"
    "<quiz>\n"
    '  <question type="multianswer">\n'
    "    <name><text>Darwin cloze</text></name>\n"
    '    <questiontext format="markdown"><text>'
    "<![CDATA[The ship used by Darwin was the {1:SHORTANSWER:=Beagle}, "
    "and Brazil has {1:NUMERICAL:=26:1} states.]]></text></questiontext>\n"
    "    <defaultgrade>1.0</defaultgrade>\n"
    "  </question>\n"
    "</quiz>\n"
)


# ---------------------------------------------------------------------
# parse_cloze / render_cloze: table-driven examples
# ---------------------------------------------------------------------


def test_parse_cloze_shortanswer():
    fragments, [cloze] = parse_cloze(
        "The ship used by Darwin was the {1:SHORTANSWER:=Beagle}."
    )
    assert cloze.kind == "SHORTANSWER"
    assert [a.text for a in cloze.answers] == ["Beagle"]
    assert cloze.answers[0].fraction == 100.0
    assert len(fragments) == 2


def test_parse_cloze_numerical_with_tolerance():
    fragments, [cloze] = parse_cloze("Brazil has {1:NUMERICAL:=26:1} states.")
    assert cloze.kind == "NUMERICAL"
    assert cloze.answers[0].text == "26"
    assert cloze.answers[0].tolerance == 1.0


def test_parse_cloze_multichoice_options_split_on_tilde():
    _, [cloze] = parse_cloze(
        "The crater was formed by a {1:MULTICHOICE:=storm~mountain~crater}."
    )
    assert cloze.kind == "MULTICHOICE"
    assert [a.text for a in cloze.answers] == ["storm", "mountain", "crater"]
    assert cloze.answers[0].fraction == 100.0
    assert cloze.answers[1].fraction == 0.0
    assert cloze.answers[2].fraction == 0.0


def test_parse_cloze_multichoice_credit_tag():
    _, [cloze] = parse_cloze("Pick one: {1:MULTICHOICE:=storm~%50%mountain~crater}.")
    fractions = [a.fraction for a in cloze.answers]
    assert fractions == [100.0, 50.0, 0.0]


@pytest.mark.parametrize("abbrev", ["SA", "SHORTANSWER"])
def test_parse_cloze_shortanswer_abbreviation(abbrev: str) -> None:
    _, [cloze] = parse_cloze(f"The ship was the {{1:{abbrev}:=Beagle}}.")
    assert cloze.kind == "SHORTANSWER"


@pytest.mark.parametrize("abbrev", ["NM", "NUMERICAL"])
def test_parse_cloze_numerical_abbreviation(abbrev: str) -> None:
    _, [cloze] = parse_cloze(f"Brazil has {{1:{abbrev}:=26:1}} states.")
    assert cloze.kind == "NUMERICAL"


@pytest.mark.parametrize(
    "abbrev", ["MC", "MULTICHOICE", "MULTICHOICE_V", "MULTICHOICE_H", "MCV", "MCH"]
)
def test_parse_cloze_multichoice_variants_normalize(abbrev: str) -> None:
    _, [cloze] = parse_cloze(f"Pick one: {{1:{abbrev}:=storm~mountain}}.")
    assert cloze.kind == "MULTICHOICE"


def test_parse_cloze_multiple_blanks_in_order():
    text = "The ship was the {1:SHORTANSWER:=Beagle} and Brazil has {1:NUMERICAL:=26:1} states."
    fragments, clozes = parse_cloze(text)
    assert [c.kind for c in clozes] == ["SHORTANSWER", "NUMERICAL"]
    assert len(fragments) == len(clozes) + 1


def test_render_cloze_shortanswer():
    cloze = MoodleCloze(
        kind="SHORTANSWER", answers=[MoodleAnswer(text="Beagle", fraction=100.0)]
    )
    assert render_cloze(cloze) == "{1:SHORTANSWER:=Beagle}"


def test_render_cloze_numerical_includes_tolerance():
    cloze = MoodleCloze(
        kind="NUMERICAL",
        answers=[MoodleAnswer(text="95", fraction=100.0, tolerance=5.0)],
    )
    assert render_cloze(cloze) == "{1:NUMERICAL:=95:5}"


def test_render_cloze_multichoice_joins_with_tilde():
    cloze = MoodleCloze(
        kind="MULTICHOICE",
        answers=[
            MoodleAnswer(text="storm", fraction=100.0),
            MoodleAnswer(text="mountain", fraction=0.0),
            MoodleAnswer(text="crater", fraction=0.0),
        ],
    )
    assert render_cloze(cloze) == "{1:MULTICHOICE:=storm~mountain~crater}"


def test_render_cloze_uses_canonical_names_even_for_abbreviated_input():
    _, [cloze] = parse_cloze("{1:SA:=Beagle}")
    assert render_cloze(cloze) == "{1:SHORTANSWER:=Beagle}"


def test_render_cloze_includes_custom_weight():
    cloze = MoodleCloze(
        kind="SHORTANSWER",
        answers=[MoodleAnswer(text="Beagle", fraction=100.0)],
        weight=2,
    )
    assert render_cloze(cloze).startswith("{2:SHORTANSWER")


@given(moodle_cloze())
def test_render_cloze_then_parse_recovers_kind_and_texts(cloze: MoodleCloze) -> None:
    text = f"Stem: {render_cloze(cloze)} end."
    _, [parsed] = parse_cloze(text)
    assert parsed.kind == cloze.kind
    assert [a.text for a in parsed.answers] == [a.text for a in cloze.answers]
    assert parsed.weight == cloze.weight


# ---------------------------------------------------------------------
# Parsing: table-driven examples
# ---------------------------------------------------------------------


def test_parse_multichoice_example():
    q = parse(MULTICHOICE_XML)
    [block] = q.blocks
    assert block.type == "multichoice"
    assert block.name == "Capital"
    assert block.idnumber == "mc-capital"
    assert block.questiontext == "What is the capital of Brazil?"
    assert block.single is True
    assert block.shuffle_answers is True
    assert block.tags == ["geography"]
    assert [a.text for a in block.answers] == ["Brasilia", "Rio de Janeiro"]
    assert block.answers[0].fraction == 100.0
    assert block.answers[0].feedback == "Correct."
    assert block.answers[1].fraction == 0.0


def test_parse_truefalse_example():
    q = parse(TRUEFALSE_XML)
    [block] = q.blocks
    assert block.type == "truefalse"
    assert len(block.answers) == 2


def test_parse_shortanswer_example():
    q = parse(SHORTANSWER_XML)
    [block] = q.blocks
    assert block.type == "shortanswer"
    assert [a.text for a in block.answers] == ["Amazon", "Amazon River"]


def test_parse_numerical_example():
    q = parse(NUMERICAL_XML)
    [block] = q.blocks
    assert block.type == "numerical"
    assert block.answers[0].text == "3"
    assert block.answers[0].tolerance == 0.1


def test_parse_essay_example():
    q = parse(ESSAY_XML)
    [block] = q.blocks
    assert block.type == "essay"
    assert block.grader_info == "Look for variation, heredity, selection."
    assert block.response_format == "editor"


def test_parse_multianswer_example():
    q = parse(MULTIANSWER_XML)
    [block] = q.blocks
    assert block.type == "multianswer"
    assert "{1:SHORTANSWER:=Beagle}" in block.questiontext
    assert "{1:NUMERICAL:=26:1}" in block.questiontext


def test_parse_category_block_is_skipped():
    xml = (
        f"{XML_DECLARATION}\n"
        "<quiz>\n"
        '  <question type="category">'
        "<category><text>$course$/top/Brazil</text></category></question>\n"
        f"{ESSAY_XML.split('<quiz>')[1]}"
    )
    q = parse(xml)
    assert len(q.blocks) == 1
    assert q.blocks[0].type == "essay"


def test_parse_default_text_format_field_survives():
    q = parse(MULTICHOICE_XML)
    [block] = q.blocks
    assert block.text_format == "markdown"


# ---------------------------------------------------------------------
# Parsing: errors
# ---------------------------------------------------------------------


def test_parse_malformed_xml_raises_parser_error():
    with pytest.raises(ParserError):
        parse(f'{XML_DECLARATION}\n<quiz><question type="essay">')


def test_parse_non_quiz_root_raises_parser_error():
    with pytest.raises(ParserError):
        parse(f'{XML_DECLARATION}\n<exam><question type="essay"/></exam>')


def test_parse_empty_source_raises():
    with pytest.raises(ParserError):
        parse("")


def test_parse_unsupported_question_type_raises_naming_type():
    xml = (
        f"{XML_DECLARATION}\n"
        "<quiz>\n"
        '  <question type="matching">\n'
        "    <name><text>Not supported</text></name>\n"
        "  </question>\n"
        "</quiz>\n"
    )
    with pytest.raises(ValueError, match="matching"):
        parse(xml)


# ---------------------------------------------------------------------
# Rendering / parsing: hypothesis round trips
# ---------------------------------------------------------------------


@given(moodle_multichoice_block())
def test_multichoice_block_round_trips(block: MoodleXmlBlock) -> None:
    q = MoodleXmlQuestion(blocks=[block])
    assert parse(str(q)) == q


@given(moodle_truefalse_block())
def test_truefalse_block_round_trips(block: MoodleXmlBlock) -> None:
    q = MoodleXmlQuestion(blocks=[block])
    assert parse(str(q)) == q


@given(moodle_shortanswer_block())
def test_shortanswer_block_round_trips(block: MoodleXmlBlock) -> None:
    q = MoodleXmlQuestion(blocks=[block])
    assert parse(str(q)) == q


@given(moodle_numerical_block())
def test_numerical_block_round_trips(block: MoodleXmlBlock) -> None:
    q = MoodleXmlQuestion(blocks=[block])
    assert parse(str(q)) == q


@given(moodle_essay_block())
def test_essay_block_round_trips(block: MoodleXmlBlock) -> None:
    q = MoodleXmlQuestion(blocks=[block])
    assert parse(str(q)) == q


@given(st.lists(moodle_truefalse_block(), min_size=2, max_size=4))
def test_truefalse_group_round_trips(blocks: list[MoodleXmlBlock]) -> None:
    q = MoodleXmlQuestion(blocks=blocks)
    assert parse(str(q)) == q


def test_render_includes_xml_declaration():
    q = MoodleXmlQuestion(
        blocks=[MoodleXmlBlock(type="essay", questiontext="Explain the Cerrado biome.")]
    )
    assert str(q).startswith(XML_DECLARATION)


def test_render_wraps_blocks_in_quiz_element():
    q = MoodleXmlQuestion(
        blocks=[MoodleXmlBlock(type="essay", questiontext="Explain the Cerrado biome.")]
    )
    assert "<quiz>" in str(q)
    assert "</quiz>" in str(q)


# ---------------------------------------------------------------------
# to_mdq: single-block conversions
# ---------------------------------------------------------------------


def test_to_mdq_multichoice_single_true_becomes_multiple_choice():
    block = MoodleXmlBlock(
        type="multichoice",
        questiontext="What is the capital of Brazil?",
        answers=[
            MoodleAnswer(text="Brasilia", fraction=100.0, feedback="Correct."),
            MoodleAnswer(text="Rio de Janeiro", fraction=0.0),
        ],
        single=True,
    )
    question = MoodleXml().to_mdq(MoodleXmlQuestion(blocks=[block]))
    assert isinstance(question, MultipleChoiceQuestion)
    assert question.choices[0] == ScoredChoice(
        text="Brasilia", score=1.0, feedback="Correct."
    )
    assert question.choices[1].score == 0.0


def test_to_mdq_multichoice_single_absent_defaults_to_multiple_choice():
    block = MoodleXmlBlock(
        type="multichoice",
        questiontext="Pick the correct biome.",
        answers=[
            MoodleAnswer(text="Amazonia", fraction=100.0),
            MoodleAnswer(text="Caatinga", fraction=0.0),
        ],
        single=None,
    )
    question = MoodleXml().to_mdq(MoodleXmlQuestion(blocks=[block]))
    assert isinstance(question, MultipleChoiceQuestion)


def test_to_mdq_multichoice_single_false_becomes_multiple_selection():
    block = MoodleXmlBlock(
        type="multichoice",
        questiontext="Select all Brazilian biomes.",
        answers=[
            MoodleAnswer(text="Amazonia", fraction=50.0, feedback="Correct biome."),
            MoodleAnswer(text="Sahara", fraction=-50.0),
        ],
        single=False,
    )
    question = MoodleXml().to_mdq(MoodleXmlQuestion(blocks=[block]))
    assert isinstance(question, MultipleSelectionQuestion)
    assert question.choices[0] == BooleanChoice(
        text="Amazonia", correct=True, feedback="Correct biome."
    )
    assert question.choices[1].correct is False


def test_to_mdq_truefalse_alone_becomes_multiple_choice():
    block = MoodleXmlBlock(
        type="truefalse",
        questiontext="The Amazon River is the longest river in the world.",
        answers=[
            MoodleAnswer(text="true", fraction=100.0),
            MoodleAnswer(text="false", fraction=0.0),
        ],
    )
    question = MoodleXml().to_mdq(MoodleXmlQuestion(blocks=[block]))
    assert isinstance(question, MultipleChoiceQuestion)
    texts = {c.text: c.score for c in question.choices}
    assert texts == {"True": 1.0, "False": 0.0}


def test_to_mdq_shortanswer_becomes_short_answer():
    block = MoodleXmlBlock(
        type="shortanswer",
        questiontext="Name Brazil's longest river.",
        answers=[
            MoodleAnswer(text="Amazon", fraction=100.0),
            MoodleAnswer(text="Amazon River", fraction=100.0),
        ],
    )
    question = MoodleXml().to_mdq(MoodleXmlQuestion(blocks=[block]))
    assert isinstance(question, ShortAnswerQuestion)
    assert question.one_of == ["Amazon", "Amazon River"]


def test_to_mdq_numerical_with_tolerance():
    block = MoodleXmlBlock(
        type="numerical",
        questiontext="Speed of light in vacuum (x10^8 m/s)?",
        answers=[MoodleAnswer(text="3", fraction=100.0, tolerance=0.1)],
        unit="x10^8 m/s",
    )
    question = MoodleXml().to_mdq(MoodleXmlQuestion(blocks=[block]))
    assert isinstance(question, NumericQuestion)
    assert question.answer == pytest.approx(3.0)
    assert question.unit == "x10^8 m/s"
    assert question.tolerance == Tolerance(absolute=0.1)


def test_to_mdq_numerical_zero_tolerance_omits_tolerance_field():
    block = MoodleXmlBlock(
        type="numerical",
        questiontext="Number of Brazilian states?",
        answers=[MoodleAnswer(text="26", fraction=100.0, tolerance=0.0)],
    )
    question = MoodleXml().to_mdq(MoodleXmlQuestion(blocks=[block]))
    assert isinstance(question, NumericQuestion)
    assert question.tolerance is None


@pytest.mark.parametrize(
    "response_format, expected_input",
    [
        ("editor", "text"),
        ("plain", "plain"),
        ("monospaced", "code"),
        (None, "text"),
        ("noeditor", "text"),
    ],
)
def test_to_mdq_essay_response_format_mapping(
    response_format: str | None, expected_input: str
) -> None:
    block = MoodleXmlBlock(
        type="essay",
        questiontext="Explain natural selection using an example from Brazilian fauna.",
        grader_info="Look for variation, heredity, selection.",
        response_format=response_format,
    )
    question = MoodleXml().to_mdq(MoodleXmlQuestion(blocks=[block]))
    assert isinstance(question, EssayQuestion)
    assert question.answer_key == "Look for variation, heredity, selection."
    assert question.input == expected_input


def test_to_mdq_multianswer_becomes_fill_in():
    block = MoodleXmlBlock(
        type="multianswer",
        questiontext=(
            "The ship used by Darwin was the {1:SHORTANSWER:=Beagle}, "
            "and Brazil has {1:NUMERICAL:=26:1} states."
        ),
    )
    question = MoodleXml().to_mdq(MoodleXmlQuestion(blocks=[block]))
    assert isinstance(question, FillInQuestion)
    assert len(question.blanks) == 2
    assert question.blanks[0].id == "blank1"
    assert question.blanks[1].id == "blank2"
    assert question.blanks[0].type == "short-answer"
    assert question.blanks[1].type == "numeric"
    assert "[^blank1]" in question.stem
    assert "[^blank2]" in question.stem


def test_to_mdq_common_fields_carry_over():
    block = MoodleXmlBlock(
        type="essay",
        questiontext="Explain photosynthesis.",
        name="Bio1",
        idnumber="bio-1",
        tags=["biology", "brazil"],
        default_grade=2.0,
    )
    question = MoodleXml().to_mdq(MoodleXmlQuestion(blocks=[block]))
    assert question.title == "Bio1"
    assert question.id == "bio-1"
    assert question.tags == ["biology", "brazil"]
    assert question.weight == 2.0


# ---------------------------------------------------------------------
# to_mdq: multi-block (true/false groups)
# ---------------------------------------------------------------------


def test_to_mdq_truefalse_group_becomes_true_false():
    blocks = [
        MoodleXmlBlock(
            type="truefalse",
            questiontext="About Brazilian geography.\n\nBrasilia is the capital.",
            answers=[
                MoodleAnswer(text="true", fraction=100.0),
                MoodleAnswer(text="false", fraction=0.0),
            ],
        ),
        MoodleXmlBlock(
            type="truefalse",
            questiontext="About Brazilian geography.\n\nRio de Janeiro is the capital.",
            answers=[
                MoodleAnswer(text="true", fraction=0.0),
                MoodleAnswer(text="false", fraction=100.0),
            ],
        ),
    ]
    question = MoodleXml().to_mdq(MoodleXmlQuestion(blocks=blocks))
    assert isinstance(question, TrueFalseQuestion)
    assert question.stem == "About Brazilian geography."
    texts = {c.text: c.correct for c in question.choices}
    assert texts == {
        "Brasilia is the capital.": True,
        "Rio de Janeiro is the capital.": False,
    }


def test_to_mdq_truefalse_group_without_common_prefix_uses_empty_stem():
    blocks = [
        MoodleXmlBlock(
            type="truefalse",
            questiontext="Brasilia is the capital of Brazil.",
            answers=[
                MoodleAnswer(text="true", fraction=100.0),
                MoodleAnswer(text="false", fraction=0.0),
            ],
        ),
        MoodleXmlBlock(
            type="truefalse",
            questiontext="The Amazon is the longest river.",
            answers=[
                MoodleAnswer(text="true", fraction=100.0),
                MoodleAnswer(text="false", fraction=0.0),
            ],
        ),
    ]
    question = MoodleXml().to_mdq(MoodleXmlQuestion(blocks=blocks))
    assert isinstance(question, TrueFalseQuestion)
    assert question.stem == ""
    assert {c.text for c in question.choices} == {
        "Brasilia is the capital of Brazil.",
        "The Amazon is the longest river.",
    }


def test_to_mdq_mixed_multi_block_group_raises():
    blocks = [
        MoodleXmlBlock(
            type="truefalse",
            questiontext="Brasilia is the capital of Brazil.",
            answers=[
                MoodleAnswer(text="true", fraction=100.0),
                MoodleAnswer(text="false", fraction=0.0),
            ],
        ),
        MoodleXmlBlock(type="essay", questiontext="Explain photosynthesis."),
    ]
    with pytest.raises(ValueError):
        MoodleXml().to_mdq(MoodleXmlQuestion(blocks=blocks))


def test_to_mdq_no_blocks_raises():
    with pytest.raises(ValueError):
        MoodleXml().to_mdq(MoodleXmlQuestion(blocks=[]))


# ---------------------------------------------------------------------
# from_mdq: single-question conversions
# ---------------------------------------------------------------------


def test_from_mdq_multiple_choice():
    question = MultipleChoiceQuestion(
        stem="What is the capital of Brazil?",
        choices=[
            ScoredChoice(text="Brasilia", score=1.0),
            ScoredChoice(text="Rio de Janeiro", score=0.0),
        ],
    )
    moodle = MoodleXml().from_mdq(question)
    [block] = moodle.blocks
    assert block.type == "multichoice"
    assert block.single is True
    assert block.answers[0].fraction == 100.0
    assert block.answers[1].fraction == 0.0


def test_from_mdq_multiple_choice_missing_score_raises():
    question = MultipleChoiceQuestion(
        stem="Q", choices=[ScoredChoice(text="a"), ScoredChoice(text="b", score=1.0)]
    )
    with pytest.raises(ValueError):
        MoodleXml().from_mdq(question)


def test_from_mdq_multiple_selection_uses_split_fractions():
    question = MultipleSelectionQuestion(
        stem="Select all Brazilian biomes.",
        choices=[
            BooleanChoice(text="Amazonia", correct=True),
            BooleanChoice(text="Caatinga", correct=True),
            BooleanChoice(text="Sahara", correct=False),
        ],
    )
    moodle = MoodleXml().from_mdq(question)
    [block] = moodle.blocks
    assert block.type == "multichoice"
    assert block.single is False
    assert block.answers[0].fraction == pytest.approx(50.0)
    assert block.answers[1].fraction == pytest.approx(50.0)
    assert block.answers[2].fraction == pytest.approx(-100.0)


def test_from_mdq_true_false_produces_one_block_per_statement():
    question = TrueFalseQuestion(
        stem="About Brazilian geography.",
        choices=[
            Statement(text="Brasilia is the capital.", correct=True),
            Statement(text="Rio de Janeiro is the capital.", correct=False),
        ],
    )
    moodle = MoodleXml().from_mdq(question)
    assert len(moodle.blocks) == 2
    assert all(b.type == "truefalse" for b in moodle.blocks)
    assert all(
        b.questiontext.startswith("About Brazilian geography.") for b in moodle.blocks
    )


def test_from_mdq_true_false_empty_stem_uses_bare_statement_text():
    question = TrueFalseQuestion(
        stem="",
        choices=[
            Statement(text="Brasilia is the capital of Brazil.", correct=True),
            Statement(text="The Amazon is the longest river.", correct=True),
        ],
    )
    moodle = MoodleXml().from_mdq(question)
    assert moodle.blocks[0].questiontext == "Brasilia is the capital of Brazil."
    assert moodle.blocks[1].questiontext == "The Amazon is the longest river."


def test_from_mdq_numeric():
    question = NumericQuestion(
        stem="Speed of light in vacuum (x10^8 m/s)?",
        answer=3.0,
        tolerance=Tolerance(absolute=0.1),
        unit="x10^8 m/s",
    )
    moodle = MoodleXml().from_mdq(question)
    [block] = moodle.blocks
    assert block.type == "numerical"
    assert block.unit == "x10^8 m/s"
    [answer] = block.answers
    assert answer.tolerance == pytest.approx(0.1)


def test_from_mdq_numeric_relative_tolerance_is_scaled_by_answer():
    question = NumericQuestion(
        stem="Number of Brazilian states?",
        answer=26.0,
        tolerance=Tolerance(relative=0.1),
    )
    moodle = MoodleXml().from_mdq(question)
    [block] = moodle.blocks
    [answer] = block.answers
    assert answer.tolerance == pytest.approx(2.6)


def test_from_mdq_numeric_rational_string_answer():
    question = NumericQuestion(stem="What fraction is one third?", answer="1/3")
    moodle = MoodleXml().from_mdq(question)
    [block] = moodle.blocks
    assert float(block.answers[0].text) == pytest.approx(1 / 3)


def test_from_mdq_short_answer():
    question = ShortAnswerQuestion(
        stem="Name Brazil's longest river.", one_of=["Amazon", "Amazon River"]
    )
    moodle = MoodleXml().from_mdq(question)
    [block] = moodle.blocks
    assert block.type == "shortanswer"
    assert [a.text for a in block.answers] == ["Amazon", "Amazon River"]


def test_from_mdq_short_answer_without_one_of_raises():
    question = ShortAnswerQuestion(stem="Q", open_ended=True)
    with pytest.raises(ValueError):
        MoodleXml().from_mdq(question)


def test_from_mdq_essay():
    question = EssayQuestion(
        stem="Explain natural selection using an example from Brazilian fauna.",
        answer_key="Look for variation, heredity, selection.",
        input="code",
    )
    moodle = MoodleXml().from_mdq(question)
    [block] = moodle.blocks
    assert block.type == "essay"
    assert block.grader_info == "Look for variation, heredity, selection."
    assert block.response_format == "monospaced"


def test_from_mdq_fill_in_multiple_blanks():
    question = FillInQuestion(
        stem="The ship used by Darwin was the [^ship], and Brazil has [^states] states.",
        blanks=[
            ChoiceBlank(id="ship", choices=[ScoredChoice(text="Beagle", score=1.0)]),
            NumericBlank(id="states", answer=26, tolerance=Tolerance(absolute=1)),
        ],
    )
    moodle = MoodleXml().from_mdq(question)
    [block] = moodle.blocks
    assert block.type == "multianswer"
    assert "{1:MULTICHOICE:=Beagle}" in block.questiontext
    assert "{1:NUMERICAL:=26:1}" in block.questiontext


def test_from_mdq_fill_in_stem_marker_without_matching_blank_raises():
    question = FillInQuestion(
        stem="Brazil has [^a] states and [^b] time zones.",
        blanks=[NumericBlank(id="a", answer=26)],
    )
    with pytest.raises(ValueError):
        MoodleXml().from_mdq(question)


def test_from_mdq_fill_in_unreferenced_blank_raises():
    question = FillInQuestion(
        stem="Brazil has [^a] states.",
        blanks=[
            NumericBlank(id="a", answer=26),
            NumericBlank(id="b", answer=4),
        ],
    )
    with pytest.raises(ValueError):
        MoodleXml().from_mdq(question)


def test_from_mdq_common_fields_carry_over():
    question = EssayQuestion(
        stem="Explain photosynthesis.",
        title="Bio1",
        id="bio-1",
        tags=["biology", "brazil"],
        weight=2.0,
    )
    moodle = MoodleXml().from_mdq(question)
    [block] = moodle.blocks
    assert block.name == "Bio1"
    assert block.idnumber == "bio-1"
    assert block.tags == ["biology", "brazil"]
    assert block.default_grade == 2.0


def test_shuffle_field_carries_over_both_directions():
    question = MultipleChoiceQuestion(
        stem="Pick the correct biome.",
        choices=[
            ScoredChoice(text="Amazonia", score=1.0),
            ScoredChoice(text="Caatinga", score=0.0),
        ],
        shuffle=True,
    )
    moodle = MoodleXml().from_mdq(question)
    [block] = moodle.blocks
    assert block.shuffle_answers is True
    roundtripped = MoodleXml().to_mdq(moodle)
    assert isinstance(roundtripped, MultipleChoiceQuestion)
    assert roundtripped.shuffle is True


def test_from_mdq_prepends_preamble_with_blank_line():
    question = EssayQuestion(
        preamble="Consider Brazilian ecosystems.", stem="Explain the Cerrado."
    )
    moodle = MoodleXml().from_mdq(question)
    [block] = moodle.blocks
    assert (
        block.questiontext == "Consider Brazilian ecosystems.\n\nExplain the Cerrado."
    )


def test_from_mdq_appends_epilogue_with_blank_line():
    question = EssayQuestion(
        stem="Explain the Cerrado.", epilogue="Score based on accuracy."
    )
    moodle = MoodleXml().from_mdq(question)
    [block] = moodle.blocks
    assert block.questiontext == "Explain the Cerrado.\n\nScore based on accuracy."


def test_from_mdq_always_renders_markdown_format():
    question = EssayQuestion(stem="Explain the Cerrado biome.")
    moodle = MoodleXml().from_mdq(question)
    [block] = moodle.blocks
    assert block.text_format == "markdown"
    assert 'format="markdown"' in str(moodle)


# ---------------------------------------------------------------------
# Full round trips: MDQ -> Moodle XML source -> MDQ
# ---------------------------------------------------------------------


def test_full_round_trip_multiple_choice():
    question = MultipleChoiceQuestion(
        stem="What is the capital of Brazil?",
        choices=[
            ScoredChoice(text="Brasilia", score=1.0),
            ScoredChoice(text="Rio de Janeiro", score=0.0),
            ScoredChoice(text="Sao Paulo", score=0.0),
        ],
    )
    converter = MoodleXml()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, MultipleChoiceQuestion)
    assert [c.text for c in roundtripped.choices] == [c.text for c in question.choices]
    assert [c.score for c in roundtripped.choices] == pytest.approx(
        [c.score for c in question.choices]
    )


def test_full_round_trip_multiple_selection():
    question = MultipleSelectionQuestion(
        stem="Select all Brazilian biomes.",
        choices=[
            BooleanChoice(text="Amazonia", correct=True),
            BooleanChoice(text="Caatinga", correct=True),
            BooleanChoice(text="Sahara", correct=False),
        ],
    )
    converter = MoodleXml()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, MultipleSelectionQuestion)
    assert [c.text for c in roundtripped.choices] == [c.text for c in question.choices]
    assert [c.correct for c in roundtripped.choices] == [
        c.correct for c in question.choices
    ]


def test_full_round_trip_true_false():
    question = TrueFalseQuestion(
        stem="About Brazilian geography.",
        choices=[
            Statement(text="Brasilia is the capital.", correct=True),
            Statement(text="Rio de Janeiro is the capital.", correct=False),
        ],
    )
    converter = MoodleXml()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, TrueFalseQuestion)
    assert roundtripped.stem == question.stem
    texts = {c.text: c.correct for c in roundtripped.choices}
    assert texts == {c.text: c.correct for c in question.choices}


def test_full_round_trip_numeric():
    question = NumericQuestion(
        stem="Speed of light in vacuum (x10^8 m/s)?",
        answer=3.0,
        tolerance=Tolerance(absolute=0.1),
        unit="x10^8 m/s",
    )
    converter = MoodleXml()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, NumericQuestion)
    assert roundtripped.answer == pytest.approx(question.answer)
    assert roundtripped.tolerance == question.tolerance
    assert roundtripped.unit == question.unit


def test_full_round_trip_short_answer():
    question = ShortAnswerQuestion(
        stem="Name Brazil's longest river.", one_of=["Amazon", "Amazon River"]
    )
    converter = MoodleXml()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, ShortAnswerQuestion)
    assert roundtripped.one_of == question.one_of


def test_full_round_trip_essay():
    question = EssayQuestion(
        stem="Explain natural selection using an example from Brazilian fauna.",
        answer_key="Look for variation, heredity, selection.",
    )
    converter = MoodleXml()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, EssayQuestion)
    assert roundtripped.stem == question.stem
    assert roundtripped.answer_key == question.answer_key


def test_full_round_trip_fill_in_multiple_blanks():
    question = FillInQuestion(
        stem="The ship used by Darwin was the [^ship], and Brazil has [^states] states.",
        blanks=[
            ChoiceBlank(
                id="ship",
                choices=[
                    ScoredChoice(text="Beagle", score=1.0),
                    ScoredChoice(text="Endeavour", score=0.0),
                ],
            ),
            NumericBlank(id="states", answer=26, tolerance=Tolerance(absolute=1)),
        ],
    )
    converter = MoodleXml()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, FillInQuestion)
    assert len(roundtripped.blanks) == 2
    assert roundtripped.blanks[0].id == "blank1"
    assert roundtripped.blanks[0].type == "multiple-choice"
    assert roundtripped.blanks[1].id == "blank2"
    assert roundtripped.blanks[1].type == "numeric"


# ---------------------------------------------------------------------
# Rendering / parsing: hypothesis round trips over MDQ models
# ---------------------------------------------------------------------


@given(
    stem=mdq_text(),
    choices=st.lists(
        st.builds(
            ScoredChoice,
            text=mdq_text(),
            score=st.sampled_from([0.0, 1.0, 0.5, -0.5, 0.25]),
            feedback=st.none() | mdq_text(),
        ),
        # Choice texts must be unique (`duplicate-choice-text` --
        # dev/specs/to-do/unique-ids.md), so `MultipleChoiceQuestion`
        # itself now rejects two choices sharing a text.
        unique_by=lambda choice: choice.text,
        min_size=2,
        max_size=4,
    ),
)
def test_multiple_choice_round_trips_through_moodle_xml(
    stem: str, choices: list[ScoredChoice]
) -> None:
    question = MultipleChoiceQuestion(stem=stem, choices=choices)
    converter = MoodleXml()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, MultipleChoiceQuestion)
    assert [c.text for c in roundtripped.choices] == [c.text for c in question.choices]
    assert [c.score for c in roundtripped.choices] == pytest.approx(
        [c.score for c in question.choices]
    )


@given(
    stem=mdq_text(),
    one_of=st.lists(mdq_text(max_size=15), min_size=1, max_size=3),
)
def test_short_answer_round_trips_through_moodle_xml(
    stem: str, one_of: list[str]
) -> None:
    question = ShortAnswerQuestion(stem=stem, one_of=one_of)
    converter = MoodleXml()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, ShortAnswerQuestion)
    assert roundtripped.one_of == question.one_of


@given(
    stem=mdq_text(),
    answer=st.floats(
        min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False
    ).map(lambda x: round(x, 2)),
)
def test_numeric_round_trips_through_moodle_xml(stem: str, answer: float) -> None:
    question = NumericQuestion(stem=stem, answer=answer)
    converter = MoodleXml()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, NumericQuestion)
    assert roundtripped.answer == pytest.approx(question.answer)


# ---------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------


def test_moodle_xml_supports_all_seven_types_both_directions():
    assert MoodleXml.supports == {
        "multiple-choice": "both",
        "multiple-selection": "both",
        "true-false": "both",
        "numeric": "both",
        "short-answer": "both",
        "essay": "both",
        "fill-in": "both",
    }


def test_encoder_and_decoder_are_reachable_directly():
    """`MoodleXmlEncoder`/`MoodleXmlDecoder` are exported for direct use, not only via `MoodleXml`."""
    question = EssayQuestion(stem="Explain the Cerrado biome.")
    moodle = MoodleXmlEncoder().encode(question)
    [block] = moodle.blocks
    assert block.type == "essay"
    back = MoodleXmlDecoder().decode(moodle)
    assert isinstance(back, EssayQuestion)


def test_fill_in_choice_blank_allows_unscored_choices():
    # An unmarked choice inside a blank parses to `score = None`, unlike a
    # top-level multiple-choice, where the parser backfills 0.0.
    question = FillInQuestion(
        stem="The Great Red Spot is a [^feature].",
        blanks=[
            ChoiceBlank(
                id="feature",
                choices=[
                    ScoredChoice(text="mountain"),
                    ScoredChoice(text="storm", score=1.0),
                    ScoredChoice(text="crater"),
                ],
            )
        ],
    )
    cloze = MoodleXmlEncoder().cloze_from_blank(question.blanks[0])
    assert [answer.fraction for answer in cloze.answers] == [0.0, 100.0, 0.0]

"""
Tests for `mdq.convert.gift`: parsing the GIFT question format, rendering
it back, and round-tripping through the internal MDQ `Question` models.

Reference: https://docs.moodle.org/502/en/GIFT_format
"""

from __future__ import annotations

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from mdq.convert.base import TRUE_FALSE_FALLBACK_STEM
from mdq.convert.gift import (
    Gift,
    GiftBlock,
    GiftBoolean,
    GiftChoice,
    GiftEssay,
    GiftNumeric,
    GiftNumericOption,
    GiftOption,
    GiftParser,
    GiftQuestion,
    GiftShort,
    escape_gift,
    unescape_gift,
)
from mdq.convert.parser import ParserError
from mdq.hypothesis.gift import (
    GIFT_SPECIAL_CHARS,
    gift_blocks,
    gift_choice_options,
    gift_numeric_options,
    gift_options,
    gift_text,
)
from mdq.models import (
    ChoiceBlank,
    EssayQuestion,
    FillInQuestion,
    MultipleChoiceQuestion,
    NumericQuestion,
    ScoredChoice,
    ShortAnswerQuestion,
    Tolerance,
    TrueFalseQuestion,
)


def parse(source: str) -> GiftQuestion:
    return GiftParser(source).parse()


# ---------------------------------------------------------------------
# escape_gift / unescape_gift
# ---------------------------------------------------------------------


@given(gift_text())
@example("Rio\\de:Janeiro={Brasilia}~#100%")
def test_unescape_undoes_escape(text: str) -> None:
    assert unescape_gift(escape_gift(text)) == text


@pytest.mark.parametrize("char", list(GIFT_SPECIAL_CHARS))
def test_escape_prefixes_every_special_character_with_backslash(char: str) -> None:
    escaped = escape_gift(char)
    assert escaped == f"\\{char}"


def test_escape_leaves_plain_text_untouched():
    assert escape_gift("Amazonia") == "Amazonia"


# ---------------------------------------------------------------------
# Parsing: table-driven examples
# ---------------------------------------------------------------------


def test_parse_essay_block():
    q = parse("::Q1:: Explain the water cycle of the Amazon rainforest. {}")
    [block] = q.blocks
    assert block.title == "Q1"
    assert block.stem == "Explain the water cycle of the Amazon rainforest."
    assert block.answer == GiftEssay()
    assert block.tail == ""


def test_parse_boolean_true_block():
    q = parse("Brasilia is the capital of Brazil. {T}")
    [block] = q.blocks
    assert block.answer == GiftBoolean(True)


def test_parse_boolean_false_block():
    q = parse("Rio de Janeiro is the capital of Brazil. {FALSE}")
    [block] = q.blocks
    assert block.answer == GiftBoolean(False)


def test_parse_choice_block_with_credits():
    q = parse(
        "What is the largest biome in Brazil? "
        "{=Amazonia ~Caatinga#dry shrubland ~Pantanal}"
    )
    [block] = q.blocks
    assert isinstance(block.answer, GiftChoice)
    assert block.answer.options == [
        GiftOption(text="Amazonia", credit=1.0),
        GiftOption(text="Caatinga", credit=0.0, feedback="dry shrubland"),
        GiftOption(text="Pantanal", credit=0.0),
    ]


def test_parse_choice_block_with_percentage_credit():
    q = parse("Pick the best guess. {~%50%Brasilia ~Rio de Janeiro}")
    [block] = q.blocks
    assert isinstance(block.answer, GiftChoice)
    assert block.answer.options[0].credit == 0.5


def test_parse_short_answer_block():
    q = parse("Name the largest river in Brazil. {=Amazon =amazon}")
    [block] = q.blocks
    assert isinstance(block.answer, GiftShort)
    assert [o.text for o in block.answer.options] == ["Amazon", "amazon"]


def test_bare_equals_only_body_is_short_not_choice():
    """
    A body with only `=` entries (no `~`) is a short-answer question,
    even with a single option -- per the dispatch table ("all entries
    are `=`" -> short answer takes priority over "contains any `~`
    entry" -> choice, and a body needs a `~` to ever be read as choice).
    This matches real Moodle GIFT semantics: `{=Brasilia}` alone is not
    distinguishable from a short-answer key with one accepted answer.
    """
    q = parse("::t:: Capital of Brazil {=Brasilia}")
    [block] = q.blocks
    assert isinstance(block.answer, GiftShort)
    assert not isinstance(block.answer, GiftChoice)
    assert [o.text for o in block.answer.options] == ["Brasilia"]


def test_parse_numeric_block_plain():
    q = parse("What is the speed of light in vacuum (m/s x 10^8)? {#3}")
    [block] = q.blocks
    assert isinstance(block.answer, GiftNumeric)
    assert block.answer.options == [GiftNumericOption(value=3, tolerance=0.0)]


def test_parse_numeric_block_with_tolerance():
    q = parse("Boiling point of water at sea level (Celsius)? {#100:0.5}")
    [block] = q.blocks
    [opt] = block.answer.options
    assert opt.value == 100
    assert opt.tolerance == 0.5


def test_parse_numeric_block_with_range():
    q = parse("Estimate pi times ten. {#31..32}")
    [block] = q.blocks
    [opt] = block.answer.options
    # A `lo..hi` range is the midpoint +- half the span.
    assert opt.value == pytest.approx(31.5)
    assert opt.tolerance == pytest.approx(0.5)


def test_parse_numeric_block_multi_entry():
    q = parse("Population of Brasilia in millions, roughly? {# =3:0.5 =%50%3.5:1}")
    [block] = q.blocks
    assert isinstance(block.answer, GiftNumeric)
    assert len(block.answer.options) == 2
    assert block.answer.options[0].value == 3
    assert block.answer.options[0].tolerance == 0.5
    assert block.answer.options[1].credit == 0.5


def test_parse_title_and_text_format_tag():
    q = parse("::Capital:: [html] What is the capital of Brazil? {}")
    [block] = q.blocks
    assert block.title == "Capital"
    assert block.text_format == "html"


def test_parse_default_text_format_is_moodle():
    q = parse("What is the capital of Brazil? {}")
    [block] = q.blocks
    assert block.text_format == "moodle"


def test_parse_comment_lines_attach_to_block():
    q = parse("// About Brazilian geography\nWhat is the capital of Brazil? {}")
    [block] = q.blocks
    assert block.comment is not None
    assert "Brazilian geography" in block.comment


def test_parse_multiline_answer_body():
    q = parse("Pick a Brazilian state capital.\n{\n=Brasilia\n~Manaus\n}")
    [block] = q.blocks
    assert isinstance(block.answer, GiftChoice)
    assert [o.text for o in block.answer.options] == ["Brasilia", "Manaus"]


def test_parse_tail_text_after_closing_brace():
    q = parse("The capital of Brazil is {=Brasilia} in the Midwest region.")
    [block] = q.blocks
    assert block.tail == "in the Midwest region."


def test_parse_general_feedback():
    q = parse("What is the capital of Brazil? {=Brasilia ####It was founded in 1960.}")
    [block] = q.blocks
    assert block.general_feedback == "It was founded in 1960."


# ---------------------------------------------------------------------
# Parsing: escapes
# ---------------------------------------------------------------------


def test_parse_escaped_brace_in_stem_is_literal():
    q = parse("What does \\{tropical\\} mean? {}")
    [block] = q.blocks
    assert block.stem == "What does {tropical} mean?"


def test_parse_escaped_equals_and_tilde_in_option_text():
    q = parse("Choose one. {=2 \\= 1 + 1 ~2 \\~ 3}")
    [block] = q.blocks
    texts = [o.text for o in block.answer.options]
    assert texts == ["2 = 1 + 1", "2 ~ 3"]


def test_parse_escaped_hash_in_stem():
    q = parse("What is \\#1 in Brazilian exports? {}")
    [block] = q.blocks
    assert block.stem == "What is #1 in Brazilian exports?"


# ---------------------------------------------------------------------
# Parsing: errors
# ---------------------------------------------------------------------


def test_parse_missing_closing_brace_raises():
    with pytest.raises(ParserError):
        parse("What is the capital of Brazil? {=Brasilia")


def test_parse_two_answer_bodies_raises():
    with pytest.raises(ParserError):
        parse("Q {=A} extra {=B}")


def test_parse_empty_source_raises():
    with pytest.raises(ParserError):
        parse("")


def test_parse_no_answer_body_raises():
    with pytest.raises(ParserError):
        parse("What is the capital of Brazil?")


# ---------------------------------------------------------------------
# Rendering: examples
# ---------------------------------------------------------------------


def test_render_essay_round_trips():
    block = GiftBlock(stem="Explain photosynthesis.", answer=GiftEssay())
    q = GiftQuestion(blocks=[block])
    assert parse(str(q)) == q


def test_render_always_includes_markdown_tag_when_from_mdq():
    question = EssayQuestion(stem="Explain the Cerrado biome.")
    gift = Gift().from_mdq(question)
    assert "[markdown]" in str(gift)


def test_render_blocks_are_joined_by_blank_line():
    blocks = [
        GiftBlock(stem="Brasilia is the capital of Brazil.", answer=GiftBoolean(True)),
        GiftBlock(
            stem="Rio de Janeiro is the capital of Brazil.", answer=GiftBoolean(False)
        ),
    ]
    q = GiftQuestion(blocks=blocks)
    assert "\n\n" in str(q)
    assert parse(str(q)) == q


# ---------------------------------------------------------------------
# Rendering / parsing: hypothesis round trips
# ---------------------------------------------------------------------


@given(gift_blocks(st.just(GiftEssay())))
def test_essay_block_round_trips(block: GiftBlock) -> None:
    q = GiftQuestion(blocks=[block])
    assert parse(str(q)) == q


@given(gift_blocks(st.booleans().map(GiftBoolean)))
def test_boolean_block_round_trips(block: GiftBlock) -> None:
    q = GiftQuestion(blocks=[block])
    assert parse(str(q)) == q


@given(gift_blocks(gift_choice_options().map(lambda opts: GiftChoice(options=opts))))
def test_choice_block_round_trips(block: GiftBlock) -> None:
    q = GiftQuestion(blocks=[block])
    assert parse(str(q)) == q


@given(gift_blocks(gift_options().map(lambda opts: GiftShort(options=opts))))
def test_short_block_round_trips(block: GiftBlock) -> None:
    q = GiftQuestion(blocks=[block])
    assert parse(str(q)) == q


@given(gift_blocks(gift_numeric_options().map(lambda opts: GiftNumeric(options=opts))))
def test_numeric_block_round_trips(block: GiftBlock) -> None:
    q = GiftQuestion(blocks=[block])
    assert parse(str(q)) == q


@given(
    gift_blocks(
        gift_choice_options().map(lambda opts: GiftChoice(options=opts)),
        tail=gift_text(),
    )
)
def test_choice_block_with_tail_round_trips(block: GiftBlock) -> None:
    q = GiftQuestion(blocks=[block])
    assert parse(str(q)) == q


@given(
    st.lists(
        gift_blocks(st.booleans().map(GiftBoolean)),
        min_size=2,
        max_size=4,
    )
)
def test_boolean_group_round_trips(blocks: list[GiftBlock]) -> None:
    q = GiftQuestion(blocks=blocks)
    assert parse(str(q)) == q


# ---------------------------------------------------------------------
# to_mdq: single-block conversions
# ---------------------------------------------------------------------


def test_to_mdq_essay():
    block = GiftBlock(
        stem="Explain photosynthesis.",
        answer=GiftEssay(),
        general_feedback="Mention chlorophyll and sunlight.",
    )
    question = Gift().to_mdq(GiftQuestion(blocks=[block]))
    assert isinstance(question, EssayQuestion)
    assert question.stem == "Explain photosynthesis."
    assert question.answer_key == "Mention chlorophyll and sunlight."


def test_to_mdq_boolean_alone_becomes_multiple_choice():
    block = GiftBlock(
        stem="Brasilia is the capital of Brazil.", answer=GiftBoolean(True)
    )
    question = Gift().to_mdq(GiftQuestion(blocks=[block]))
    assert isinstance(question, MultipleChoiceQuestion)
    texts = {c.text: c.score for c in question.choices}
    assert texts == {"True": 1.0, "False": 0.0}


def test_to_mdq_boolean_false_marks_false_choice():
    block = GiftBlock(stem="Rio is the capital of Brazil.", answer=GiftBoolean(False))
    question = Gift().to_mdq(GiftQuestion(blocks=[block]))
    assert isinstance(question, MultipleChoiceQuestion)
    texts = {c.text: c.score for c in question.choices}
    assert texts == {"True": 0.0, "False": 1.0}


def test_to_mdq_choice_becomes_multiple_choice():
    block = GiftBlock(
        stem="What is the largest biome in Brazil?",
        answer=GiftChoice(
            options=[
                GiftOption(text="Amazonia", credit=1.0),
                GiftOption(text="Caatinga", credit=0.0, feedback="dry shrubland"),
            ]
        ),
    )
    question = Gift().to_mdq(GiftQuestion(blocks=[block]))
    assert isinstance(question, MultipleChoiceQuestion)
    assert question.choices[0] == ScoredChoice(
        text="Amazonia", score=1.0, feedback=None
    )
    assert question.choices[1].score == 0.0
    assert question.choices[1].feedback == "dry shrubland"


def test_to_mdq_short_becomes_short_answer():
    block = GiftBlock(
        stem="Name the largest river in Brazil.",
        answer=GiftShort(
            options=[GiftOption(text="Amazon"), GiftOption(text="amazon")]
        ),
    )
    question = Gift().to_mdq(GiftQuestion(blocks=[block]))
    assert isinstance(question, ShortAnswerQuestion)
    assert question.one_of == ["Amazon", "amazon"]


def test_to_mdq_numeric_becomes_numeric_with_tolerance():
    block = GiftBlock(
        stem="Boiling point of water at sea level (Celsius)?",
        answer=GiftNumeric(options=[GiftNumericOption(value=100, tolerance=0.5)]),
    )
    question = Gift().to_mdq(GiftQuestion(blocks=[block]))
    assert isinstance(question, NumericQuestion)
    assert question.answer == 100
    assert question.tolerance == Tolerance(absolute=0.5)


def test_to_mdq_numeric_zero_tolerance_omits_tolerance_field():
    block = GiftBlock(
        stem="Number of Brazilian states?",
        answer=GiftNumeric(options=[GiftNumericOption(value=26, tolerance=0.0)]),
    )
    question = Gift().to_mdq(GiftQuestion(blocks=[block]))
    assert isinstance(question, NumericQuestion)
    assert question.tolerance is None


def test_to_mdq_choice_with_tail_becomes_fill_in():
    block = GiftBlock(
        stem="The capital of Brazil is",
        answer=GiftChoice(
            options=[
                GiftOption(text="Brasilia", credit=1.0),
                GiftOption(text="Rio", credit=0.0),
            ]
        ),
        tail="in the Midwest region.",
    )
    question = Gift().to_mdq(GiftQuestion(blocks=[block]))
    assert isinstance(question, FillInQuestion)
    assert question.stem == "The capital of Brazil is[^blank]in the Midwest region."
    [blank] = question.blanks
    assert blank.id == "blank"
    assert blank.type == "multiple-choice"


def test_to_mdq_short_with_tail_becomes_fill_in():
    block = GiftBlock(
        stem="The Amazon is the largest",
        answer=GiftShort(options=[GiftOption(text="river")]),
        tail="in the world.",
    )
    question = Gift().to_mdq(GiftQuestion(blocks=[block]))
    assert isinstance(question, FillInQuestion)
    [blank] = question.blanks
    assert blank.type == "short-answer"


def test_to_mdq_numeric_with_tail_becomes_fill_in():
    block = GiftBlock(
        stem="Brazil has approximately",
        answer=GiftNumeric(options=[GiftNumericOption(value=26, tolerance=0.0)]),
        tail="states.",
    )
    question = Gift().to_mdq(GiftQuestion(blocks=[block]))
    assert isinstance(question, FillInQuestion)
    [blank] = question.blanks
    assert blank.type == "numeric"


def test_to_mdq_title_and_comment_carry_over():
    block = GiftBlock(
        stem="Explain photosynthesis.",
        answer=GiftEssay(),
        title="Bio1",
        comment="from the botany unit",
    )
    question = Gift().to_mdq(GiftQuestion(blocks=[block]))
    assert question.title == "Bio1"
    assert question.comment == "from the botany unit"


# ---------------------------------------------------------------------
# to_mdq: multi-block (true/false groups)
# ---------------------------------------------------------------------


def test_to_mdq_boolean_group_becomes_true_false():
    blocks = [
        GiftBlock(
            stem="About Brazilian geography.\n\nBrasilia is the capital.",
            answer=GiftBoolean(True),
        ),
        GiftBlock(
            stem="About Brazilian geography.\n\nRio de Janeiro is the capital.",
            answer=GiftBoolean(False),
        ),
    ]
    question = Gift().to_mdq(GiftQuestion(blocks=blocks))
    assert isinstance(question, TrueFalseQuestion)
    assert question.stem == "About Brazilian geography."
    texts = {c.text: c.correct for c in question.choices}
    assert texts == {
        "Brasilia is the capital.": True,
        "Rio de Janeiro is the capital.": False,
    }


def test_to_mdq_boolean_group_without_common_prefix_uses_fallback_stem():
    blocks = [
        GiftBlock(stem="Brasilia is the capital of Brazil.", answer=GiftBoolean(True)),
        GiftBlock(stem="The Amazon is the longest river.", answer=GiftBoolean(False)),
    ]
    question = Gift().to_mdq(GiftQuestion(blocks=blocks))
    assert isinstance(question, TrueFalseQuestion)
    assert question.stem == TRUE_FALSE_FALLBACK_STEM
    assert {c.text for c in question.choices} == {
        "Brasilia is the capital of Brazil.",
        "The Amazon is the longest river.",
    }


def test_to_mdq_mixed_multi_block_group_raises():
    blocks = [
        GiftBlock(stem="Brasilia is the capital of Brazil.", answer=GiftBoolean(True)),
        GiftBlock(stem="Explain photosynthesis.", answer=GiftEssay()),
    ]
    with pytest.raises(ValueError):
        Gift().to_mdq(GiftQuestion(blocks=blocks))


# ---------------------------------------------------------------------
# from_mdq: single-question conversions
# ---------------------------------------------------------------------


def test_from_mdq_multiple_choice():
    question = MultipleChoiceQuestion(
        stem="What is the largest biome in Brazil?",
        choices=[
            ScoredChoice(text="Amazonia", score=1.0),
            ScoredChoice(text="Caatinga", score=0.0),
        ],
    )
    gift = Gift().from_mdq(question)
    [block] = gift.blocks
    assert isinstance(block.answer, GiftChoice)
    assert block.answer.options[0].credit == 1.0
    assert block.answer.options[1].credit == 0.0


def test_from_mdq_multiple_choice_partial_credit_uses_percentage():
    question = MultipleChoiceQuestion(
        stem="Pick the best guess.",
        choices=[
            ScoredChoice(text="Brasilia", score=1.0),
            ScoredChoice(text="Rio de Janeiro", score=0.5),
        ],
    )
    gift = Gift().from_mdq(question)
    [block] = gift.blocks
    assert block.answer.options[1].credit == 0.5
    assert "%50%" in str(gift)


def test_from_mdq_multiple_choice_missing_score_raises():
    question = MultipleChoiceQuestion(
        stem="Q",
        choices=[ScoredChoice(text="a"), ScoredChoice(text="b", score=1.0)],
    )
    with pytest.raises(ValueError):
        Gift().from_mdq(question)


def test_from_mdq_short_answer():
    question = ShortAnswerQuestion(
        stem="Name the largest river in Brazil.", one_of=["Amazon", "amazon"]
    )
    gift = Gift().from_mdq(question)
    [block] = gift.blocks
    assert isinstance(block.answer, GiftShort)
    assert [o.text for o in block.answer.options] == ["Amazon", "amazon"]


def test_from_mdq_short_answer_without_one_of_raises():
    question = ShortAnswerQuestion(stem="Q", open_ended=True)
    with pytest.raises(ValueError):
        Gift().from_mdq(question)


def test_from_mdq_numeric():
    question = NumericQuestion(
        stem="Boiling point of water at sea level (Celsius)?",
        answer=100.0,
        tolerance=Tolerance(absolute=0.5),
    )
    gift = Gift().from_mdq(question)
    [block] = gift.blocks
    assert isinstance(block.answer, GiftNumeric)
    [opt] = block.answer.options
    assert opt.value == 100.0
    assert opt.tolerance == 0.5


def test_from_mdq_numeric_relative_tolerance_is_scaled_by_answer():
    question = NumericQuestion(
        stem="Number of Brazilian states?",
        answer=26.0,
        tolerance=Tolerance(relative=0.1),
    )
    gift = Gift().from_mdq(question)
    [block] = gift.blocks
    [opt] = block.answer.options
    assert opt.tolerance == pytest.approx(2.6)


def test_from_mdq_numeric_no_tolerance_defaults_to_zero():
    question = NumericQuestion(stem="Number of Brazilian states?", answer=26.0)
    gift = Gift().from_mdq(question)
    [block] = gift.blocks
    [opt] = block.answer.options
    assert opt.tolerance == 0.0


def test_from_mdq_numeric_rational_string_answer():
    question = NumericQuestion(stem="What fraction is one third?", answer="1/3")
    gift = Gift().from_mdq(question)
    [block] = gift.blocks
    [opt] = block.answer.options
    assert opt.value == pytest.approx(1 / 3)


def test_from_mdq_essay():
    question = EssayQuestion(
        stem="Explain photosynthesis.", answer_key="Mention chlorophyll and sunlight."
    )
    gift = Gift().from_mdq(question)
    [block] = gift.blocks
    assert block.answer == GiftEssay()
    assert block.general_feedback == "Mention chlorophyll and sunlight."


def test_from_mdq_true_false_produces_one_block_per_statement():
    from mdq.models import Statement

    question = TrueFalseQuestion(
        stem="About Brazilian geography.",
        choices=[
            Statement(text="Brasilia is the capital.", correct=True),
            Statement(text="Rio de Janeiro is the capital.", correct=False),
        ],
    )
    gift = Gift().from_mdq(question)
    assert len(gift.blocks) == 2
    assert all(b.stem.startswith("About Brazilian geography.") for b in gift.blocks)
    assert gift.blocks[0].answer == GiftBoolean(True)
    assert gift.blocks[1].answer == GiftBoolean(False)


def test_from_mdq_true_false_fallback_stem_uses_bare_statement_text():
    from mdq.models import Statement

    question = TrueFalseQuestion(
        stem=TRUE_FALSE_FALLBACK_STEM,
        choices=[
            Statement(text="Brasilia is the capital of Brazil.", correct=True),
            Statement(text="The Amazon is the longest river.", correct=True),
        ],
    )
    gift = Gift().from_mdq(question)
    assert gift.blocks[0].stem == "Brasilia is the capital of Brazil."
    assert gift.blocks[1].stem == "The Amazon is the longest river."


def test_from_mdq_fill_in_single_blank():
    from mdq.models import ChoiceBlank

    question = FillInQuestion(
        stem="The capital of Brazil is [^cap] in the Midwest region.",
        blanks=[
            ChoiceBlank(
                id="cap",
                choices=[
                    ScoredChoice(text="Brasilia", score=1.0),
                    ScoredChoice(text="Rio", score=0.0),
                ],
            )
        ],
    )
    gift = Gift().from_mdq(question)
    [block] = gift.blocks
    assert block.stem == "The capital of Brazil is"
    assert block.tail == "in the Midwest region."
    assert isinstance(block.answer, GiftChoice)


def test_from_mdq_fill_in_multiple_blanks_raises():
    from mdq.models import NumericBlank

    question = FillInQuestion(
        stem="Brazil has [^a] states and [^b] time zones.",
        blanks=[
            NumericBlank(id="a", answer=26),
            NumericBlank(id="b", answer=4),
        ],
    )
    with pytest.raises(ValueError):
        Gift().from_mdq(question)


def test_from_mdq_prepends_preamble_with_blank_line():
    question = EssayQuestion(
        preamble="Consider Brazilian ecosystems.", stem="Explain the Cerrado."
    )
    gift = Gift().from_mdq(question)
    [block] = gift.blocks
    assert block.stem == "Consider Brazilian ecosystems.\n\nExplain the Cerrado."


def test_from_mdq_appends_epilogue_to_tail_with_blank_line():
    from mdq.models import ChoiceBlank

    question = FillInQuestion(
        stem="The capital of Brazil is [^cap].",
        epilogue="Score based on accuracy.",
        blanks=[
            ChoiceBlank(
                id="cap",
                choices=[
                    ScoredChoice(text="Brasilia", score=1.0),
                    ScoredChoice(text="Rio", score=0.0),
                ],
            )
        ],
    )
    gift = Gift().from_mdq(question)
    [block] = gift.blocks
    assert "Score based on accuracy." in block.tail


def test_from_mdq_always_renders_markdown_tag():
    question = EssayQuestion(stem="Explain the Cerrado biome.")
    gift = Gift().from_mdq(question)
    assert str(gift).count("[markdown]") == 1


# ---------------------------------------------------------------------
# Full round trips: MDQ -> GIFT source -> MDQ
# ---------------------------------------------------------------------


def test_full_round_trip_multiple_choice():
    question = MultipleChoiceQuestion(
        stem="What is the largest biome in Brazil?",
        choices=[
            ScoredChoice(text="Amazonia", score=1.0),
            ScoredChoice(text="Caatinga", score=0.0),
            ScoredChoice(text="Pantanal", score=0.0),
        ],
    )
    converter = Gift()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, MultipleChoiceQuestion)
    assert [c.text for c in roundtripped.choices] == [c.text for c in question.choices]
    assert [c.score for c in roundtripped.choices] == [
        c.score for c in question.choices
    ]


def test_full_round_trip_short_answer():
    question = ShortAnswerQuestion(
        stem="Name the largest river in Brazil.", one_of=["Amazon", "amazon"]
    )
    converter = Gift()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, ShortAnswerQuestion)
    assert roundtripped.one_of == question.one_of


def test_full_round_trip_numeric():
    question = NumericQuestion(
        stem="Boiling point of water at sea level (Celsius)?",
        answer=100.0,
        tolerance=Tolerance(absolute=0.5),
    )
    converter = Gift()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, NumericQuestion)
    assert roundtripped.answer == pytest.approx(question.answer)
    assert roundtripped.tolerance == question.tolerance


def test_full_round_trip_essay():
    question = EssayQuestion(
        stem="Explain photosynthesis.", answer_key="Mention chlorophyll and sunlight."
    )
    converter = Gift()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, EssayQuestion)
    assert roundtripped.stem == question.stem
    assert roundtripped.answer_key == question.answer_key


def test_full_round_trip_true_false():
    from mdq.models import Statement

    question = TrueFalseQuestion(
        stem="About Brazilian geography.",
        choices=[
            Statement(text="Brasilia is the capital.", correct=True),
            Statement(text="Rio de Janeiro is the capital.", correct=False),
        ],
    )
    converter = Gift()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, TrueFalseQuestion)
    assert roundtripped.stem == question.stem
    texts = {c.text: c.correct for c in roundtripped.choices}
    assert texts == {c.text: c.correct for c in question.choices}


def test_full_round_trip_fill_in():
    from mdq.models import ChoiceBlank

    question = FillInQuestion(
        stem="The capital of Brazil is [^cap] in the Midwest region.",
        blanks=[
            ChoiceBlank(
                id="cap",
                choices=[
                    ScoredChoice(text="Brasilia", score=1.0),
                    ScoredChoice(text="Rio", score=0.0),
                ],
            )
        ],
    )
    converter = Gift()
    source = converter.render(converter.from_mdq(question))
    roundtripped = converter.to_mdq(converter.parse(source))
    assert isinstance(roundtripped, FillInQuestion)
    [blank] = roundtripped.blanks
    assert blank.id == "blank"
    assert blank.type == "multiple-choice"


# ---------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------


def test_gift_supports_short_answer_both_directions():
    assert Gift.supports["short-answer"] == "both"


def test_gift_supports_all_documented_types():
    assert Gift.supports == {
        "multiple-choice": "both",
        "true-false": "both",
        "numeric": "both",
        "essay": "both",
        "fill-in": "both",
        "short-answer": "both",
    }


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
    block = Gift().from_mdq(question).blocks[0]
    assert isinstance(block.answer, GiftChoice)
    assert [option.credit for option in block.answer.options] == [0.0, 1.0, 0.0]

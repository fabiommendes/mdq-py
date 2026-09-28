"""
Tests for `mdq.convert._aiken`: parsing the Aiken multiple-choice format,
and round-tripping through the internal `MultipleChoiceQuestion` model.
"""

from __future__ import annotations

import pytest
from hypothesis import given

from mdq.convert._aiken import Aiken, AikenParser, AikenQuestion
from mdq.convert._string_parser import ParserError
from strategies.aiken import aiken_questions
from mdq.models import EssayQuestion, MultipleChoiceQuestion, ScoredChoice


def parse(source: str) -> AikenQuestion:
    return AikenParser(source).parse()


# ---------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------


def test_parse_basic_question():
    q = parse(
        "What is the capital of Brazil?\n"
        "\n"
        "A. Rio de Janeiro\n"
        "B. Brasilia\n"
        "C. Sao Paulo\n"
        "\n"
        "ANSWER: B\n"
    )
    assert q.stem == "What is the capital of Brazil?"
    assert q.choices == ["Rio de Janeiro", "Brasilia", "Sao Paulo"]
    assert q.answer == 1


def test_parse_multiline_stem_is_joined_with_newlines():
    q = parse("Line one\nLine two\n\nA. opt1\nB. opt2\n\nANSWER: A\n")
    assert q.stem == "Line one\nLine two"


def test_parse_lowercase_answer_letter():
    q = parse("Q\n\nA. opt1\nB. opt2\n\nANSWER: b\n")
    assert q.answer == 1


def test_parse_answer_without_blank_line_before_it():
    q = parse("Q\n\nA. opt1\nB. opt2\nANSWER: A\n")
    assert q.answer == 0
    assert q.choices == ["opt1", "opt2"]


def test_parse_missing_answer_raises():
    with pytest.raises(ParserError):
        parse("Q\n\nA. opt1\nB. opt2\n")


def test_parse_answer_multiple_characters_raises():
    with pytest.raises(ParserError, match="single letter"):
        parse("Q\n\nA. opt1\nB. opt2\n\nANSWER: AB\n")


def test_parse_answer_non_letter_raises():
    with pytest.raises(ParserError, match="single letter"):
        parse("Q\n\nA. opt1\nB. opt2\n\nANSWER: 1\n")


def test_parse_trailing_content_after_answer_raises():
    with pytest.raises(ParserError, match="unparsed"):
        parse("Q\n\nA. opt1\nB. opt2\n\nANSWER: A\nextra garbage\n")


def test_parse_empty_source_raises():
    with pytest.raises(ParserError):
        parse("")


# ---------------------------------------------------------------------
# Rendering (AikenQuestion.__str__)
# ---------------------------------------------------------------------


def test_render_round_trips_through_parser():
    q = AikenQuestion(stem="Q", choices=["opt1", "opt2"], answer=1)
    rendered = str(q)
    assert parse(rendered) == q


def test_render_lowercases_choice_letters():
    q = AikenQuestion(stem="Q", choices=["opt1", "opt2"], answer=0)
    assert "a. opt1" in str(q)
    assert "b. opt2" in str(q)
    assert "ANSWER: a" in str(q)


# ---------------------------------------------------------------------
# to_mdq / from_mdq conversion
# ---------------------------------------------------------------------


def test_to_mdq_marks_answer_choice_with_full_score():
    aiken = AikenQuestion(stem="Q", choices=["wrong", "right"], answer=1)
    question = Aiken().to_mdq(aiken)
    assert isinstance(question, MultipleChoiceQuestion)
    assert [c.score for c in question.choices] == [0.0, 1.0]
    assert [c.text for c in question.choices] == ["wrong", "right"]


def test_from_mdq_picks_highest_scoring_choice():
    question = MultipleChoiceQuestion(
        stem="Q",
        choices=[
            ScoredChoice(text="wrong", score=0.0),
            ScoredChoice(text="right", score=1.0),
        ],
    )
    aiken = Aiken().from_mdq(question)
    assert aiken.answer == 1
    assert aiken.choices == ["wrong", "right"]


def test_from_mdq_joins_preamble_and_stem():
    question = MultipleChoiceQuestion(
        preamble="Consider the following.",
        stem="What is 2 + 2?",
        choices=[ScoredChoice(text="4", score=1.0), ScoredChoice(text="5", score=0.0)],
    )
    aiken = Aiken().from_mdq(question)
    assert aiken.stem == "Consider the following.\n\nWhat is 2 + 2?"


def test_from_mdq_without_preamble_uses_stem_only():
    question = MultipleChoiceQuestion(
        stem="What is 2 + 2?",
        choices=[ScoredChoice(text="4", score=1.0), ScoredChoice(text="5", score=0.0)],
    )
    aiken = Aiken().from_mdq(question)
    assert aiken.stem == "What is 2 + 2?"


def test_full_round_trip_mdq_to_aiken_source_and_back():
    question = MultipleChoiceQuestion(
        stem="Capital of Brazil?",
        choices=[
            ScoredChoice(text="Rio de Janeiro", score=0.0),
            ScoredChoice(text="Brasilia", score=1.0),
        ],
    )
    converter = Aiken()
    aiken = converter.from_mdq(question)
    source = converter.render(aiken)
    reparsed = converter.parse(source)
    roundtripped = converter.to_mdq(reparsed)
    assert [c.text for c in roundtripped.choices] == [c.text for c in question.choices]
    assert [c.score for c in roundtripped.choices] == [
        c.score for c in question.choices
    ]


# ---------------------------------------------------------------------
# Regression tests for bugs fixed in `mdq.convert._aiken`.
# ---------------------------------------------------------------------


def test_choice_letters_out_of_order_are_rejected():
    # "B" appears before "A" in the source, which doesn't match the
    # required sequential a, b, c... labeling.
    with pytest.raises(ParserError):
        parse("Q\n\nB. first\nA. second\n\nANSWER: A\n")


def test_duplicate_choice_letter_is_rejected():
    with pytest.raises(ParserError):
        parse("Q\n\nA. opt1\nA. opt2\n\nANSWER: A\n")


def test_answer_letter_beyond_choice_count_raises():
    with pytest.raises(ParserError):
        parse("Q\n\nA. opt1\nB. opt2\n\nANSWER: C\n")


def test_extra_space_after_marker_is_not_kept_in_choice_text():
    q = parse("Q\n\nA.  double space\nB. normal\n\nANSWER: A\n")
    assert q.choices[0] == "double space"


def test_tab_after_marker_is_not_kept_in_choice_text():
    q = parse("Q\n\nA.\tTabbed\nB. normal\n\nANSWER: A\n")
    assert q.choices[0] == "Tabbed"


def test_from_mdq_with_unset_score_raises_clear_error():
    question = MultipleChoiceQuestion(
        stem="Q",
        choices=[ScoredChoice(text="a"), ScoredChoice(text="b", score=1.0)],
    )
    with pytest.raises(ValueError):
        Aiken().from_mdq(question)


def test_more_than_26_choices_raises_clear_error():
    choices = [
        ScoredChoice(text=f"choice {i}", score=1.0 if i == 0 else 0.0)
        for i in range(27)
    ]
    question = MultipleChoiceQuestion(stem="Q", choices=choices)
    with pytest.raises(ValueError):
        Aiken().from_mdq(question)


def test_aiken_question_rejects_out_of_range_answer_directly():
    with pytest.raises(ValueError):
        AikenQuestion(stem="Q", choices=["a", "b"], answer=2)


def test_aiken_question_rejects_too_many_choices_directly():
    with pytest.raises(ValueError):
        AikenQuestion(stem="Q", choices=[f"c{i}" for i in range(27)], answer=0)


def test_from_mdq_appends_epilogue_to_stem():
    question = MultipleChoiceQuestion(
        preamble="Consider the Brazilian biomes.",
        stem="Which one is the largest?",
        epilogue="Mark exactly one alternative.",
        choices=[
            ScoredChoice(text="Amazon", score=1.0),
            ScoredChoice(text="Pantanal", score=0.0),
        ],
    )
    aiken = Aiken().from_mdq(question)
    assert aiken.stem == (
        "Consider the Brazilian biomes.\n\n"
        "Which one is the largest?\n\n"
        "Mark exactly one alternative."
    )


def test_from_mdq_breaks_score_ties_towards_the_first_choice():
    question = MultipleChoiceQuestion(
        stem="Which river is in Brazil?",
        choices=[
            ScoredChoice(text="Amazon", score=1.0),
            ScoredChoice(text="Sao Francisco", score=1.0),
        ],
    )
    assert Aiken().from_mdq(question).answer == 0


def test_newlines_in_choice_text_are_collapsed_to_spaces():
    # A choice occupies exactly one Aiken line, so keeping the newline would
    # render source that no longer reparses.
    question = MultipleChoiceQuestion(
        stem="Who described the Brazilian rainforest in 1832?",
        choices=[
            ScoredChoice(text="Charles\nDarwin", score=1.0),
            ScoredChoice(text="Alfred Wallace", score=0.0),
        ],
    )
    converter = Aiken()
    aiken = converter.from_mdq(question)
    assert aiken.choices[0] == "Charles Darwin"
    assert converter.parse(converter.render(aiken)) == aiken


def test_from_mdq_rejects_unsupported_question_type():
    with pytest.raises(ValueError, match="essay"):
        Aiken().from_mdq(EssayQuestion(stem="Explain the Cerrado biome."))


def test_parse_accepts_parenthesis_choice_markers():
    # Moodle's Aiken accepts `A)` as well as `A.`, but rendering always
    # normalizes back to the dotted form.
    source = "Capital of Brazil?\n\nA) Rio de Janeiro\nB) Brasilia\n\nANSWER: B\n"
    converter = Aiken()

    q = converter.parse(source)
    assert q.stem == "Capital of Brazil?"
    assert q.choices == ["Rio de Janeiro", "Brasilia"]
    assert q.answer == 1

    rendered = converter.render(q)
    assert "a. Rio de Janeiro" in rendered
    assert "b. Brasilia" in rendered
    assert ")" not in rendered
    assert converter.parse(rendered) == q

    question = converter.to_mdq(q)
    assert [(c.text, c.score) for c in question.choices] == [
        ("Rio de Janeiro", 0.0),
        ("Brasilia", 1.0),
    ]


def test_parse_accepts_dot_and_parenthesis_markers_in_one_question():
    q = parse("Largest Brazilian biome?\n\nA. Amazon\nB) Cerrado\n\nANSWER: A\n")
    assert q.choices == ["Amazon", "Cerrado"]
    assert q.answer == 0


@given(aiken_questions())
def test_render_round_trips_for_any_question(q: AikenQuestion) -> None:
    assert parse(str(q)) == q

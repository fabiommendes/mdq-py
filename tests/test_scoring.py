"""
`Question.score_response`: turning one response into a `QuestionScore`.

Covers every question type's grading formula, per docs/adr/0001-score-scale-and-exam-level-clamping.md
(scores are raw here -- no exam `penalty` applied) and
docs/adr/0002-partial-names-a-range-not-an-algorithm.md (`"partial"` is a
range contract, not one shared formula). The true-false and
multiple-selection tests share one dataset -- five items keyed
`[T, T, F, F, F]`, answered as all-true -- because that is the exact
example the second ADR uses to show the two types' `"partial"` formulas
are not interchangeable: true-false yields 0.4, multiple-selection's
floored symmetric score yields 0.0.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from mdq import models
from mdq.errors import NotAutoGradable, ResponseError

#
# Multiple choice
#
_CAPITAL_OF_BRAZIL = models.MultipleChoiceQuestion(
    stem="What is the capital of Brazil?",
    choices=[
        models.ScoredChoice(
            id="brasilia",
            text="Brasília",
            score=1.0,
            feedback="Correct -- Brasília became the capital in 1960.",
        ),
        models.ScoredChoice(id="rio", text="Rio de Janeiro"),
        models.ScoredChoice(
            id="salvador",
            text="Salvador",
            score=-0.5,
            feedback="Salvador was Brazil's colonial capital, not today's.",
        ),
    ],
)


def test_multiple_choice_scores_the_picked_choice() -> None:
    result = _CAPITAL_OF_BRAZIL.score_response("brasilia")
    assert result.score == 1.0
    assert result.feedback == ["Correct -- Brasília became the capital in 1960."]


def test_multiple_choice_a_penalised_choice_scores_negative() -> None:
    result = _CAPITAL_OF_BRAZIL.score_response("salvador")
    assert result.score == -0.5
    assert result.feedback == ["Salvador was Brazil's colonial capital, not today's."]


def test_multiple_choice_a_choice_without_feedback_yields_none() -> None:
    result = _CAPITAL_OF_BRAZIL.score_response("rio")
    # "rio" declares no score, so the default "symmetric" grading spreads the
    # declared 1.0 and -0.5 over it: -(1.0 - 0.5) / 1 == -0.5.
    assert result.score == -0.5
    assert result.feedback == []


def test_multiple_choice_unknown_response_raises() -> None:
    with pytest.raises(ResponseError):
        _CAPITAL_OF_BRAZIL.score_response("lisbon")


#
# Multiple selection
#
def _biomes(grading: models.GradingStrategy) -> models.MultipleSelectionQuestion:
    return models.MultipleSelectionQuestion(
        stem="Which of these are biomes found in Brazil?",
        grading=grading,
        choices=[
            models.BooleanChoice(id="s1", text="Amazon rainforest", correct=True),
            models.BooleanChoice(id="s2", text="Cerrado", correct=True),
            models.BooleanChoice(
                id="s3",
                text="Taiga",
                correct=False,
                feedback="Taiga does not occur in Brazil.",
            ),
            models.BooleanChoice(
                id="s4",
                text="Tundra",
                correct=False,
                feedback="Tundra does not occur in Brazil.",
            ),
            models.BooleanChoice(
                id="s5",
                text="Sahara desert",
                correct=False,
                feedback="The Sahara is in Africa.",
            ),
        ],
    )


_ALL_MARKED_TRUE = {"s1", "s2", "s3", "s4", "s5"}


def test_multiple_selection_symmetric_subtracts_wrong_marks() -> None:
    """2 correct judgements, 3 wrong -- (2 - 3) / 5."""
    result = _biomes("symmetric").score_response(_ALL_MARKED_TRUE)
    assert result.score == pytest.approx(-0.2)


def test_multiple_selection_partial_is_the_correctly_judged_fraction() -> None:
    """2 of 5 choices judged correctly (s1, s2 ticked-and-correct;
    s3-s5 wrongly ticked) -- 2 / 5, not the floored symmetric score."""
    result = _biomes("partial").score_response(_ALL_MARKED_TRUE)
    assert result.score == pytest.approx(0.4)


def test_multiple_selection_all_or_nothing_requires_every_choice_correct() -> None:
    perfect = {"s1", "s2"}
    assert _biomes("all-or-nothing").score_response(perfect).score == 1.0
    assert _biomes("all-or-nothing").score_response(_ALL_MARKED_TRUE).score == 0.0


def test_multiple_selection_missing_key_asserts_false() -> None:
    """An empty response leaves s1/s2 wrongly unticked and s3-s5 correctly
    unticked -- (3 - 2) / 5."""
    result = _biomes("symmetric").score_response(set())
    assert result.score == pytest.approx(0.2)


def test_multiple_selection_feedback_lists_only_wrongly_judged_choices() -> None:
    response = {"c1", "s1", "s3"}
    result = _biomes("symmetric").score_response(response)
    assert result.feedback == ["Taiga does not occur in Brazil."]


#
# True false
#
def _amazon_statements(grading: models.GradingStrategy) -> models.TrueFalseQuestion:
    return models.TrueFalseQuestion(
        stem="Judge the statements about the Amazon rainforest.",
        grading=grading,
        choices=[
            models.Statement(id="s1", text="It spans nine countries.", correct=True),
            models.Statement(
                id="s2", text="It holds most of Earth's fresh water.", correct=True
            ),
            models.Statement(
                id="s3",
                text="It is the world's driest biome.",
                correct=False,
                feedback="The opposite -- it is one of the wettest.",
            ),
            models.Statement(
                id="s4",
                text="It has no indigenous population.",
                correct=False,
                feedback="Indigenous peoples have lived there for millennia.",
            ),
            models.Statement(
                id="s5",
                text="Its canopy blocks all sunlight from the forest floor.",
                correct=False,
                feedback="Some light penetrates -- that's why understory plants survive.",
            ),
        ],
    )


_ALL_JUDGED_TRUE = {"s1": True, "s2": True, "s3": True, "s4": True, "s5": True}


def test_true_false_partial_is_correct_over_total() -> None:
    """The exact ADR 0002 example: 2 correct out of 5 -> 0.4."""
    result = _amazon_statements("partial").score_response(_ALL_JUDGED_TRUE)
    assert result.score == pytest.approx(0.4)


def test_true_false_symmetric_subtracts_incorrect_judgements() -> None:
    """(2 correct - 3 incorrect) / 5 -- diverges from partial's 0.4."""
    result = _amazon_statements("symmetric").score_response(_ALL_JUDGED_TRUE)
    assert result.score == pytest.approx(-0.2)


def test_true_false_abstention_counts_as_neither_correct_nor_incorrect() -> None:
    response = {"s1": True, "s2": True, "s3": None, "s4": None, "s5": None}
    partial = _amazon_statements("partial").score_response(response)
    symmetric = _amazon_statements("symmetric").score_response(response)
    assert partial.score == pytest.approx(0.4)
    assert symmetric.score == pytest.approx(0.4)


def test_true_false_missing_key_behaves_like_an_explicit_abstention() -> None:
    result = _amazon_statements("symmetric").score_response({"s1": True, "s2": True})
    assert result.score == pytest.approx(0.4)


def test_true_false_all_or_nothing_requires_every_statement_correct() -> None:
    perfect = {"s1": True, "s2": True, "s3": False, "s4": False, "s5": False}
    assert _amazon_statements("all-or-nothing").score_response(perfect).score == 1.0
    assert (
        _amazon_statements("all-or-nothing").score_response(_ALL_JUDGED_TRUE).score
        == 0.0
    )


def test_true_false_feedback_covers_wrong_and_unjudged_statements() -> None:
    response = {"s1": True, "s2": None, "s3": True}
    result = _amazon_statements("symmetric").score_response(response)
    assert result.feedback == [
        "The opposite -- it is one of the wettest.",
        "Indigenous peoples have lived there for millennia.",
        "Some light penetrates -- that's why understory plants survive.",
    ]


#
# Numeric
#
def test_numeric_exact_match_with_no_tolerance() -> None:
    question = models.NumericQuestion(
        stem="What is the freezing point of water, in Celsius?", answer=0
    )
    assert question.score_response(0).score == 1.0
    assert question.score_response(1).score == 0.0


def test_numeric_absolute_tolerance() -> None:
    question = models.NumericQuestion(
        stem="How long is the Amazon River, in kilometers?",
        answer=6400,
        tolerance=models.Tolerance(absolute=100),
    )
    assert question.score_response(6450).score == 1.0
    assert question.score_response(6600).score == 0.0


def test_numeric_relative_tolerance() -> None:
    question = models.NumericQuestion(
        stem="What is the value of pi?",
        answer=3.14159,
        tolerance=models.Tolerance(relative=0.01),
    )
    assert question.score_response(3.15).score == 1.0
    assert question.score_response(4.0).score == 0.0


def test_numeric_either_tolerance_accepts() -> None:
    """docs/question-types/numeric.md#tolerances: both given means either
    one passing is enough, not that they combine."""
    question = models.NumericQuestion(
        stem="x",
        answer=100,
        tolerance=models.Tolerance(absolute=1, relative=0.5),
    )
    assert question.score_response(120).score == 1.0


def test_numeric_accepts_an_exact_rational_answer() -> None:
    """The answer key may be authored as a string ("1/3"), but a response
    arrives already validated -- a `Fraction`, not its string spelling."""
    question = models.NumericQuestion(stem="What is 1 divided by 3?", answer="1/3")
    assert question.score_response(Fraction(1, 3)).score == 1.0
    assert question.score_response(0.5).score == 0.0


#
# Short answer
#
def test_short_answer_accept_matches_after_normalization() -> None:
    question = models.ShortAnswerQuestion(
        stem="Name the capital of Brazil.", accept=["Brasília"]
    )
    assert question.score_response("  BRASÍLIA  ").score == 1.0
    assert question.score_response("Rio de Janeiro").score == 0.0


def test_short_answer_exact_requires_a_literal_match() -> None:
    question = models.ShortAnswerQuestion(
        stem="Name the capital of Brazil.", accept=["`Brasília`"]
    )
    assert question.score_response("Brasília").score == 1.0
    assert question.score_response("brasília").score == 0.0


def test_short_answer_regex_is_a_full_match_not_a_search() -> None:
    """A regex in `accept` has no implicit `i` flag, so it is
    case-sensitive by default -- unlike a plain literal, which is inexact."""
    question = models.ShortAnswerQuestion(
        stem="Name a Brazilian biome.", accept=["/amazon|cerrado/"]
    )
    assert question.score_response("cerrado").score == 1.0
    assert question.score_response("Cerrado").score == 0.0
    assert question.score_response("The Cerrado").score == 0.0


def test_short_answer_without_an_answer_key_is_not_auto_gradable() -> None:
    question = models.ShortAnswerQuestion(
        stem="Describe your favorite Brazilian biome."
    )
    with pytest.raises(NotAutoGradable):
        question.score_response("The Pantanal.")


#
# Essay
#
def test_essay_is_never_auto_gradable() -> None:
    question = models.EssayQuestion(stem="Explain how the greenhouse effect works.")
    with pytest.raises(NotAutoGradable):
        question.score_response("Sunlight warms the Earth, which radiates heat back...")


#
# Fill in
#
def _capital_and_pi(grading: models.GradingStrategy) -> models.FillInQuestion:
    return models.FillInQuestion(
        stem="The capital of Brazil is [^capital], and pi is approximately [^pi].",
        grading=grading,
        blanks=[
            models.ChoiceBlank(
                id="capital",
                choices=[
                    models.ScoredChoice(id="brasilia", text="Brasília", score=1.0),
                    models.ScoredChoice(
                        id="rio",
                        text="Rio",
                        score=0.0,
                        feedback="Rio was the capital until 1960.",
                    ),
                ],
            ),
            models.NumericBlank(
                id="pi", answer=3.14, tolerance=models.Tolerance(absolute=0.01)
            ),
        ],
    )


def test_fill_in_averages_its_blank_scores() -> None:
    result = _capital_and_pi("symmetric").score_response(
        {"capital": "brasilia", "pi": 3.14}
    )
    assert result.score == 1.0


def test_fill_in_unanswered_blank_scores_zero() -> None:
    result = _capital_and_pi("symmetric").score_response({"capital": "brasilia"})
    assert result.score == pytest.approx(0.5)


def test_fill_in_partial_floors_the_mean_at_zero() -> None:
    question = models.FillInQuestion(
        stem="This is [^a].",
        grading="partial",
        blanks=[
            models.ChoiceBlank(
                id="a",
                choices=[
                    models.ScoredChoice(id="bad", text="Wrong", score=-1.0),
                    models.ScoredChoice(id="good", text="Right", score=1.0),
                ],
            )
        ],
    )
    assert question.score_response({"a": "bad"}).score == 0.0

    symmetric = question.model_copy(update={"grading": "symmetric"})
    assert symmetric.score_response({"a": "bad"}).score == -1.0


def test_fill_in_all_or_nothing_requires_every_blank_perfect() -> None:
    question = _capital_and_pi("all-or-nothing")
    assert question.score_response({"capital": "brasilia", "pi": 3.14}).score == 1.0
    assert question.score_response({"capital": "rio", "pi": 3.14}).score == 0.0


def test_fill_in_collects_feedback_in_blank_declaration_order() -> None:
    question = _capital_and_pi("symmetric")
    result = question.score_response({"capital": "rio", "pi": 3.14})
    assert result.feedback == ["Rio was the capital until 1960."]


def test_fill_in_unknown_choice_response_raises() -> None:
    question = _capital_and_pi("symmetric")
    with pytest.raises(ResponseError):
        question.score_response({"capital": "lisbon", "pi": 3.14})


#
# Fill in: diacritics applies to short answer blanks
# (docs/question-types/fill-in.md § Frontmatter, footnote 2)
#
def _state_capital_blank(diacritics: models.Diacritics) -> models.FillInQuestion:
    return models.FillInQuestion(
        stem="The capital of Ceará is [^capital].",
        diacritics=diacritics,
        blanks=[
            models.ShortAnswerBlank(id="capital", accept=["Fortaleza"]),
        ],
    )


def test_fill_in_short_answer_blank_folds_diacritics_by_default() -> None:
    question = _state_capital_blank("fold")
    assert question.score_response({"capital": "fortaleza"}).score == 1.0


def test_fill_in_short_answer_blank_keeps_diacritics_when_configured() -> None:
    question = models.FillInQuestion(
        stem="Name a Brazilian state in the Northeast: [^state].",
        diacritics="keep",
        blanks=[models.ShortAnswerBlank(id="state", accept=["Ceará"])],
    )
    assert question.score_response({"state": "Ceará"}).score == 1.0
    assert question.score_response({"state": " ceará "}).score == 1.0
    assert question.score_response({"state": "Ceara"}).score == 0.0


def test_fill_in_short_answer_blank_diacritics_keep_applies_to_a_plain_accept() -> None:
    """`diacritics: keep` applies to the plain literals of a blank's `accept`."""
    question = models.FillInQuestion(
        stem="Name a Brazilian state in the Northeast: [^state].",
        diacritics="keep",
        blanks=[models.ShortAnswerBlank(id="state", accept=["Ceará"])],
    )
    assert question.score_response({"state": "Ceará"}).score == 1.0
    assert question.score_response({"state": "Ceara"}).score == 0.0

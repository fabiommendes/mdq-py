"""
`Question.score_response`: turning one response into a `QuestionScore`.

Per-type grading scores live in the corpus (`examples/grading/*.yaml`).
What stays here is what the corpus cannot express: the feedback of the
multiple-choice, multiple-selection and true-false types, and the
`ResponseError` and `NotAutoGradable` contracts.
"""

from __future__ import annotations

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


def test_multiple_selection_feedback_lists_only_wrongly_judged_choices() -> None:
    response = {"s1", "s2", "s3"}
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
#
# Short answer
#
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


def test_fill_in_all_or_nothing_requires_every_blank_perfect() -> None:
    question = _capital_and_pi("all-or-nothing")
    assert question.score_response({"capital": "brasilia", "pi": 3.14}).score == 1.0
    assert question.score_response({"capital": "rio", "pi": 3.14}).score == 0.0


def test_fill_in_no_mistakes_zeroes_a_filled_blank_below_one() -> None:
    question = _capital_and_pi("no-mistakes")
    assert question.score_response({"capital": "brasilia", "pi": 3.14}).score == 1.0
    assert question.score_response({"capital": "rio", "pi": 3.14}).score == 0.0


def test_fill_in_collects_feedback_in_blank_declaration_order() -> None:
    question = _capital_and_pi("symmetric")
    result = question.score_response({"capital": "rio", "pi": 3.14})
    assert result.feedback == ["Rio was the capital until 1960."]

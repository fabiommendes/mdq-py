"""
`MultipleChoiceQuestion.unspecified_score()`: the score "symmetric" grading
gives the choices that declare none (docs/question-types/multiple-choice.md,
"Grading"). The grading tables live in `examples/grading/*.yaml`.
"""

from __future__ import annotations

import pytest

from mdq import models


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        ([1.0, None, None, None], -1 / 3),
        ([1.0, 1.0, None, None], -1.0),
        ([1.0, 0.5, None, None], -0.75),
        ([1.0, 1.0, 1.0, None], -1.0),
        ([1.0, -1.0, None, None], 0.0),
        ([1.0, -1.0, -1.0, None], 0.0),
    ],
)
def test_symmetric_spreads_declared_scores_over_the_undeclared_ones(
    scores: list[float | None], expected: float
) -> None:
    # Every row of the table in docs/question-types/multiple-choice.md, so
    # that picking at random averages zero. The last two clamp to [-1, 0].
    question = models.MultipleChoiceQuestion(
        stem="What is the capital of Brazil?",
        choices=[
            models.ScoredChoice(id=f"c{i}", text=f"Choice {i}", score=score)
            for i, score in enumerate(scores)
        ],
    )
    assert question.unspecified_score() == pytest.approx(expected)
    assert question.score_response("c3").score == pytest.approx(expected)

"""
The `automation` and `effective_unmatched` properties of the models
(docs/question-types/short-answer.md "Automation"). Their values are in
`examples/grading/automation.yaml`; what stays here is the shape of the
models.
"""

from __future__ import annotations

import pytest

from mdq import models


def test_open_ended_is_not_a_field_of_the_models() -> None:
    assert "open_ended" not in models.ShortAnswerQuestion.model_fields
    assert "open_ended" not in models.ShortAnswerBlank.model_fields
    with pytest.raises(ValueError):
        models.ShortAnswerQuestion(stem="Qual é a capital do Brasil?", open_ended=True)

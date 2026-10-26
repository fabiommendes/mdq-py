"""
The response to a short answer or essay question is a string (docs/responses.md,
"Short answer and essay"). Any other value is a `ResponseError`. The corpus
(`examples/grading/short-answer.yaml`) covers short answer questions and
short answer blanks.
"""

from __future__ import annotations

from typing import Any

import pytest

from mdq import models
from mdq.errors import NotAutoGradable, ResponseError

NOT_TEXT: list[Any] = [1960, 1960.0, True, ["Brasília"], {"capital": "Brasília"}]


@pytest.mark.parametrize("response", NOT_TEXT)
def test_essay_rejects_a_response_that_is_not_a_string(response: Any) -> None:
    essay = models.EssayQuestion(stem="Explique a fotossíntese.")
    with pytest.raises(ResponseError):
        essay.score_response(response)


def test_essay_with_a_string_is_pending() -> None:
    essay = models.EssayQuestion(stem="Explique a fotossíntese.")
    with pytest.raises(NotAutoGradable):
        essay.score_response("")


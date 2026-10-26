"""
`incorrectFeedback` of a short answer blank (docs/question-types/fill-in.md,
"Frontmatter" [^9], "Feedback" and "Additional Rules"), and the
pre-validation of a blank (short-answer.md, "Pre-validation"). The parsing
and the choice of feedback per response live in the corpus.
"""

from __future__ import annotations

from typing import Any

import pytest

import mdq
from mdq.models import FillInQuestion, ShortAnswerBlank

BODY = """
The [^river] crosses the state of [^state].

[^river/short-answer]: Amazonas

[^state/short-answer]: Pará
"""


def _load(source: str) -> mdq.Loaded:
    return mdq.load(source, kind="question")


def _errors(loaded: mdq.Loaded) -> list[mdq.Diagnostic]:
    return [d for d in loaded.diagnostics if d.severity == "error"]


def _question(**fields: Any) -> FillInQuestion:
    blanks = [
        {"id": "river", "type": "short-answer", "accept": ["Amazonas"], **fields},
        {"id": "state", "type": "short-answer", "accept": ["Pará"]},
    ]
    loaded = mdq.load(
        {
            "type": "fill-in",
            "stem": "The [^river] crosses the state of [^state].",
            "blanks": blanks,
        },
        kind="question",
    )
    assert _errors(loaded) == []
    assert isinstance(loaded.document, FillInQuestion)
    return loaded.document


def test_map_values_must_be_strings() -> None:
    loaded = _load("---\nincorrectFeedback:\n  river: 3\n---\n" + BODY)
    assert [d.code for d in _errors(loaded)] == ["parse-error"]


@pytest.mark.parametrize(
    ("response", "feedback"),
    [
        ("Tocantins", ["Wrong river."]),
    ],
)
def test_score_uses_the_blank_incorrect_feedback(
    response: str, feedback: list[str]
) -> None:
    question = _question(incorrectFeedback="Wrong river.")
    result = question.score_response({"river": response, "state": "Pará"})
    assert result.feedback == feedback


def test_frontmatter_and_render_round_trip() -> None:
    question = _question(incorrectFeedback="Wrong river.")
    assert question.frontmatter()["incorrectFeedback"] == {"river": "Wrong river."}
    again = _load(question.render())
    assert _errors(again) == []
    assert again.document == question


def test_blank_prevalidate() -> None:
    question = _question(
        preAccept=[{"pattern": "/[A-Za-z]+/", "feedback": "Letters only."}],
        preReject=[{"pattern": "Nilo", "feedback": "That river is in Africa."}],
    )
    blank = question.blanks[0]
    assert isinstance(blank, ShortAnswerBlank)
    assert blank.prevalidate("Amazonas") == (True, None)
    assert blank.prevalidate("Nilo") == (False, "That river is in Africa.")
    assert blank.prevalidate("Rio 2") == (False, "Letters only.")

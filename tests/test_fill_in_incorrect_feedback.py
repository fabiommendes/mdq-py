"""
`incorrectFeedback` of a short answer blank (docs/question-types/fill-in.md,
"Frontmatter" [^9], "Feedback" and "Additional Rules"): the render. The
parsing, the choice of feedback per response and the pre-validation of a
blank live in the corpus.
"""

from __future__ import annotations

from typing import Any

import mdq
from mdq.models import FillInQuestion


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


def test_frontmatter_and_render_round_trip() -> None:
    question = _question(incorrectFeedback="Wrong river.")
    assert question.frontmatter()["incorrectFeedback"] == {"river": "Wrong river."}
    again = _load(question.render())
    assert _errors(again) == []
    assert again.document == question

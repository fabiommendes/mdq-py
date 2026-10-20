"""
`incorrectFeedback` of a short answer blank (docs/question-types/fill-in.md,
"Frontmatter" [^9], "Feedback" and "Additional Rules"), and the
pre-validation of a blank (short-answer.md, "Pre-validation").
"""

from __future__ import annotations

from typing import Any

import pytest
from _corpus import EXAMPLES_ROOT, parsed_sibling

import mdq
from mdq._parser import parse_question
from mdq.models import FillInQuestion, ShortAnswerBlank

SOURCE = EXAMPLES_ROOT / "valid" / "fill-in" / "incorrect-feedback.mdq.md"

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


def test_markdown_map_becomes_a_field_of_each_blank() -> None:
    parsed = parse_question('---\nincorrectFeedback:\n  river: No.\n---\n' + BODY)
    assert "incorrectFeedback" not in parsed
    river, state = parsed["blanks"]
    assert river["incorrectFeedback"] == "No."
    assert "incorrectFeedback" not in state


def test_unknown_blank_id_is_undefined_blank() -> None:
    loaded = _load('---\nincorrectFeedback:\n  lake: No.\n---\n' + BODY)
    assert [d.code for d in _errors(loaded)] == ["undefined-blank"]
    assert _errors(loaded)[0].path == ("incorrectFeedback", "lake")


def test_incorrect_feedback_on_a_choice_blank_is_a_schema_error() -> None:
    source = """---
incorrectFeedback:
  state: No.
---

The capital is [^state].

[^state]:
* [ ] Salvador
* [*] Brasília
"""
    loaded = _load(source)
    assert [d.code for d in _errors(loaded)] == ["schema-error"]


def test_map_values_must_be_strings() -> None:
    loaded = _load("---\nincorrectFeedback:\n  river: 3\n---\n" + BODY)
    assert [d.code for d in _errors(loaded)] == ["parse-error"]


def test_blank_incorrect_feedback_must_have_a_visible_character() -> None:
    loaded = _load('---\nincorrectFeedback:\n  river: "  "\n---\n' + BODY)
    assert "blank-text" in [d.code for d in _errors(loaded)]


@pytest.mark.parametrize(
    ("response", "feedback"),
    [
        ("Amazonas", []),
        ("Tocantins", ["Wrong river."]),
    ],
)
def test_score_uses_the_blank_incorrect_feedback(
    response: str, feedback: list[str]
) -> None:
    question = _question(incorrectFeedback="Wrong river.")
    result = question.score_response({"river": response, "state": "Pará"})
    assert result.feedback == feedback


def test_pattern_feedback_wins_over_incorrect_feedback() -> None:
    question = _question(
        incorrectFeedback="Wrong river.",
        reject=[{"pattern": "Tocantins", "feedback": "That is in Goiás."}],
    )
    result = question.score_response({"river": "Tocantins", "state": "Pará"})
    assert result.feedback == ["That is in Goiás."]


def test_incorrect_feedback_of_one_blank_is_not_shown_for_another() -> None:
    question = _question(incorrectFeedback="Wrong river.")
    result = question.score_response({"river": "Amazonas", "state": "Bahia"})
    assert result.feedback == []


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


def test_corpus_markdown_matches_its_yaml_sibling() -> None:
    from_md = _load(SOURCE.read_text(encoding="utf-8"))
    from_yaml = mdq.load(parsed_sibling(SOURCE), kind="question")
    assert _errors(from_md) == []
    assert from_md.document == from_yaml.document

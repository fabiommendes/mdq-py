"""
ADR 0001: a question's `score` ranges from -1 to 1, and only an exam's
`penalty` policy decides whether a negative score survives. Neither a
question nor a choice ever clamps its own score.

These tests cover the two schema knobs the ADR introduces --
`Choice.score`'s bounds and `Exam.penalty`'s enum -- and the parser's
frontmatter round-trip for `penalty`.
"""

from __future__ import annotations

from typing import Any

import pytest

from mdq.parser import parse_any
from mdq import load


def _multiple_choice(score: float) -> dict[str, Any]:
    return {
        "type": "multiple-choice",
        "stem": "What is the capital of Brazil?",
        "choices": [
            {"text": "Brasília", "score": score},
            {"text": "Rio de Janeiro"},
        ],
    }


def _fill_in_with_choice_score(score: float) -> dict[str, Any]:
    """A fill-in choice blank `$ref`s multiple-choice.yaml's Choice def --
    see docs/adr/0001-score-scale-and-exam-level-clamping.md and
    schema/fill-in.yaml. Bounding `score` in one place must bound it here
    too, or the definition is not really shared."""
    return {
        "type": "fill-in",
        "stem": "The capital of Brazil is [^capital].",
        "blanks": [
            {
                "id": "capital",
                "type": "multiple-choice",
                "choices": [
                    {"text": "Brasília", "score": score},
                    {"text": "Rio de Janeiro"},
                ],
            }
        ],
    }


def _exam(penalty: str | None = None) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "type": "exam",
        "title": "Sample Exam",
        "questions": [_multiple_choice(1)],
    }
    if penalty is not None:
        doc["penalty"] = penalty
    return doc


# ---------------------------------------------------------------------
# Choice.score: -1..1, shared by multiple-choice and fill-in
# ---------------------------------------------------------------------


@pytest.mark.parametrize("score", [-1, 0, 1, -0.5, 0.25])
def test_score_within_range_is_accepted(score: float) -> None:
    assert load(_multiple_choice(score))


@pytest.mark.parametrize("score", [-1.5, 1.5])
def test_score_outside_range_is_rejected(score: float) -> None:
    assert not load(_multiple_choice(score))


@pytest.mark.parametrize("score", [-1, 0, 1])
def test_fill_in_choice_blank_accepts_score_within_range(score: float) -> None:
    """Proves the $ref to multiple-choice.yaml#/$defs/Choice actually
    shares the bound, not just the shape."""
    assert load(_fill_in_with_choice_score(score))


@pytest.mark.parametrize("score", [-1.5, 1.5])
def test_fill_in_choice_blank_rejects_score_outside_range(score: float) -> None:
    assert not load(_fill_in_with_choice_score(score))


# ---------------------------------------------------------------------
# Exam.penalty: none | capped | full, defaulting to none
# ---------------------------------------------------------------------


@pytest.mark.parametrize("penalty", ["none", "capped", "full"])
def test_each_penalty_value_is_accepted(penalty: str) -> None:
    assert load(_exam(penalty))


def test_unknown_penalty_value_is_rejected() -> None:
    assert not load(_exam("harsh"))


def test_penalty_is_optional() -> None:
    doc = _exam()
    assert "penalty" not in doc
    assert load(doc)


def test_a_question_cannot_override_penalty() -> None:
    """ADR 0001: 'no per-question override of `penalty` exists'. A question
    document is not an exam, so `penalty` on it is just an unrecognised
    field -- caught by the type schema's `unevaluatedProperties: false`."""
    doc = _multiple_choice(1)
    doc["penalty"] = "full"
    assert not load(doc)


# ---------------------------------------------------------------------
# parser: `penalty` survives exam frontmatter
# ---------------------------------------------------------------------


@pytest.mark.parametrize("penalty", ["none", "capped", "full"])
def test_parser_carries_penalty_from_exam_frontmatter(penalty: str) -> None:
    source = (
        f"---\npenalty: {penalty}\n---\n\n"
        "# Exam\n\n===\n\nWhat is 2 + 2?\n\n* [ ] 3\n* [*] 4\n"
    )
    doc = parse_any(source)
    assert doc["penalty"] == penalty
    assert load(doc)


def test_parser_omits_penalty_when_not_set_in_frontmatter() -> None:
    doc = parse_any("# Exam\n\n===\n\nWhat is 2 + 2?\n\n* [ ] 3\n* [*] 4\n")
    assert "penalty" not in doc

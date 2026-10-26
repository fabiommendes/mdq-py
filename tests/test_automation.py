"""
The `automation` and `effective_unmatched` properties of the models
(docs/question-types/short-answer.md "Automation"; base.md, fill-in.md and
ordering.md "Automation"). Grading vectors live in `examples/grading/`.
"""

from __future__ import annotations

from typing import Any

import pytest

import mdq
from mdq import models

STEM = "Qual é a capital do Brasil?"


def _sa(**fields: Any) -> models.ShortAnswerQuestion:
    return models.ShortAnswerQuestion(stem=STEM, **fields)


def _fill_in(*blanks: Any, **fields: Any) -> models.FillInQuestion:
    stem = " e ".join(f"[^{blank.id}]" for blank in blanks)
    return models.FillInQuestion(
        stem=f"Complete: {stem}.", blanks=list(blanks), **fields
    )


def test_effective_unmatched_defaults() -> None:
    assert _sa(accept=["Brasília"]).effective_unmatched == "incorrect"
    assert _sa().effective_unmatched == "manual"
    assert _sa(reject=["Rio"]).effective_unmatched == "manual"
    assert _sa(accept=["Brasília"], unmatched="manual").effective_unmatched == "manual"
    assert _sa(unmatched="incorrect").effective_unmatched == "incorrect"


#
# Automation
#
@pytest.mark.parametrize(
    ("fields", "unmatched", "automation"),
    [
        ({"accept": ["Brasília"]}, "incorrect", "automatic"),
        ({"accept": ["Brasília"], "unmatched": "manual"}, "manual", "semi-automatic"),
        ({"reject": ["Rio"], "unmatched": "manual"}, "manual", "semi-automatic"),
        ({"reject": ["Rio"]}, "manual", "semi-automatic"),
        (
            {"accept": ["A"], "reject": ["B"], "unmatched": "manual"},
            "manual",
            "semi-automatic",
        ),
        ({"unmatched": "incorrect"}, "incorrect", "automatic"),
        ({"reject": ["Rio"], "unmatched": "incorrect"}, "incorrect", "automatic"),
        ({}, "manual", "manual"),
        ({"unmatched": "manual"}, "manual", "manual"),
        ({"pre_accept": ["/\\d+/"]}, "manual", "manual"),
    ],
    ids=[
        "accept",
        "accept-manual",
        "reject-manual",
        "reject-default",
        "both-manual",
        "incorrect-no-pattern",
        "reject-incorrect",
        "empty",
        "empty-manual",
        "pre-validation-is-not-a-pattern",
    ],
)
def test_short_answer_automation(fields: dict, unmatched: str, automation: str) -> None:
    question = _sa(**fields)
    assert question.effective_unmatched == unmatched
    assert question.automation == automation


@pytest.mark.parametrize(
    ("fields", "question_unmatched", "unmatched", "automation"),
    [
        ({"accept": ["A"]}, None, "incorrect", "automatic"),
        ({"accept": ["A"]}, "manual", "manual", "semi-automatic"),
        ({"reject": ["A"]}, None, "manual", "semi-automatic"),
        ({"reject": ["A"]}, "incorrect", "incorrect", "automatic"),
        ({}, None, "manual", "manual"),
        ({}, "manual", "manual", "manual"),
        ({}, "incorrect", "incorrect", "automatic"),
    ],
)
def test_blank_automation_takes_the_question_unmatched(
    fields: dict, question_unmatched: Any, unmatched: str, automation: str
) -> None:
    blank = models.ShortAnswerBlank(id="x", **fields)
    assert blank.effective_unmatched(question_unmatched) == unmatched
    assert blank.automation(question_unmatched) == automation


_CHOICE = models.ChoiceBlank(
    id="c",
    choices=[
        models.ScoredChoice(id="a", text="Brasília", score=1.0),
        models.ScoredChoice(id="b", text="Rio", score=0.0),
    ],
)
_NUMERIC = models.NumericBlank(
    id="n", answer=3.14, tolerance=models.Tolerance(absolute=0.01)
)
_AUTO = models.ShortAnswerBlank(id="s1", accept=["Cerrado"])
_MANUAL = models.ShortAnswerBlank(id="s2")
_SEMI = models.ShortAnswerBlank(id="s3", reject=["Savana"])


@pytest.mark.parametrize(
    ("blanks", "automation"),
    [
        ([_CHOICE, _NUMERIC], "automatic"),
        ([_AUTO, _CHOICE], "automatic"),
        ([_MANUAL], "manual"),
        ([_MANUAL, _MANUAL.model_copy(update={"id": "s4"})], "manual"),
        ([_AUTO, _MANUAL], "semi-automatic"),
        ([_SEMI], "semi-automatic"),
        ([_CHOICE, _MANUAL], "semi-automatic"),
        ([_SEMI, _MANUAL], "semi-automatic"),
    ],
    ids=[
        "choice-numeric",
        "auto-choice",
        "one-manual",
        "all-manual",
        "auto-manual",
        "one-semi",
        "choice-manual",
        "semi-manual",
    ],
)
def test_fill_in_automation_aggregates_its_blanks(
    blanks: list, automation: str
) -> None:
    assert _fill_in(*blanks).automation == automation


def test_fill_in_unmatched_changes_the_automation_of_its_blanks() -> None:
    blanks = [_AUTO, _MANUAL]
    assert _fill_in(*blanks, unmatched="incorrect").automation == "automatic"
    assert _fill_in(*blanks, unmatched="manual").automation == "semi-automatic"
    assert _fill_in(_MANUAL, unmatched="manual").automation == "manual"


def test_ordering_automation_follows_unmatched() -> None:
    lines = [[0, "x, y = 1, 1"], [0, "print(x)"]]
    incorrect = mdq.load(
        {
            "type": "ordering",
            "content": "text",
            "stem": "Ordene.",
            "lines": lines,
            "unmatched": "incorrect",
        },
        kind="question",
    ).document
    manual = mdq.load(
        {
            "type": "ordering",
            "content": "text",
            "stem": "Ordene.",
            "lines": lines,
            "unmatched": "manual",
        },
        kind="question",
    ).document
    assert incorrect.automation == "automatic"
    assert manual.automation == "semi-automatic"


def test_essay_is_manual() -> None:
    assert models.EssayQuestion(stem="Explique o efeito estufa.").automation == "manual"


def test_choice_numeric_question_types_are_automatic() -> None:
    questions = [
        models.MultipleChoiceQuestion(
            stem=STEM,
            choices=[
                models.ScoredChoice(id="a", text="Brasília", score=1.0),
                models.ScoredChoice(id="b", text="Rio", score=0.0),
            ],
        ),
        models.MultipleSelectionQuestion(
            stem="Biomas do Brasil?",
            choices=[
                models.BooleanChoice(id="a", text="Cerrado", correct=True),
                models.BooleanChoice(id="b", text="Tundra", correct=False),
            ],
        ),
        models.TrueFalseQuestion(
            stem="Julgue.",
            choices=[
                models.Statement(id="a", text="A Amazônia é úmida.", correct=True),
                models.Statement(
                    id="b", text="O Pantanal é um deserto.", correct=False
                ),
            ],
        ),
        models.NumericQuestion(stem="Quanto é pi?", answer=3.14),
    ]
    assert [q.automation for q in questions] == ["automatic"] * 4


def test_open_ended_is_not_a_field_of_the_models() -> None:
    assert "open_ended" not in models.ShortAnswerQuestion.model_fields
    assert "open_ended" not in models.ShortAnswerBlank.model_fields
    with pytest.raises(ValueError):
        _sa(open_ended=True)

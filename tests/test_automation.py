"""
Grading rules and automation of short answer questions and blanks
(docs/question-types/short-answer.md "Grading", "Automation", "Feedback";
base.md, fill-in.md and ordering.md "Automation"; patterns.md, where `*` is an
ordinary literal; lint-codes.md `no-correct-answer`).
"""

from __future__ import annotations

from typing import Any

import pytest
from _corpus import INVALID_DIR

import mdq
from mdq import models
from mdq.errors import NotAutoGradable

STEM = "Qual é a capital do Brasil?"


def _sa(**fields: Any) -> models.ShortAnswerQuestion:
    return models.ShortAnswerQuestion(stem=STEM, **fields)


def _fill_in(*blanks: Any, **fields: Any) -> models.FillInQuestion:
    stem = " e ".join(f"[^{blank.id}]" for blank in blanks)
    return models.FillInQuestion(
        stem=f"Complete: {stem}.", blanks=list(blanks), **fields
    )


def _codes(doc: dict) -> list[tuple[str, str, tuple]]:
    return [
        (d.code, d.severity, tuple(d.path))
        for d in mdq.load(doc, kind="question").diagnostics
    ]


#
# AC1: grading rules of a short answer question
#
def test_accept_match_scores_one() -> None:
    assert _sa(accept=["Brasília"]).score_response("brasilia").score == 1.0


def test_accept_only_unknown_response_is_incorrect_by_default() -> None:
    assert _sa(accept=["Brasília"]).score_response("Salvador").score == 0.0


def test_reject_match_scores_zero_with_its_feedback() -> None:
    question = _sa(
        accept=["Brasília"],
        reject=[
            models.AnswerPattern(pattern="Rio de Janeiro", feedback="Foi até 1960.")
        ],
    )
    result = question.score_response("Rio de Janeiro")
    assert (result.score, result.feedback) == (0.0, ["Foi até 1960."])


def test_accept_wins_over_reject() -> None:
    assert (
        _sa(accept=["Brasília"], reject=["Brasília"]).score_response("Brasília").score
        == 1.0
    )


@pytest.fixture
def semi_automatic() -> models.ShortAnswerQuestion:
    return _sa(
        accept=["Brasília"],
        reject=[
            models.AnswerPattern(pattern="Rio de Janeiro", feedback="Foi até 1960.")
        ],
        unmatched="manual",
    )


def test_manual_unmatched_raises_for_an_unknown_response(
    semi_automatic: models.ShortAnswerQuestion,
) -> None:
    with pytest.raises(NotAutoGradable):
        semi_automatic.score_response("Salvador")


def test_manual_unmatched_still_settles_accept_and_reject(
    semi_automatic: models.ShortAnswerQuestion,
) -> None:
    assert semi_automatic.score_response("Brasília").score == 1.0
    rejected = semi_automatic.score_response("Rio de Janeiro")
    assert (rejected.score, rejected.feedback) == (0.0, ["Foi até 1960."])


def test_reject_only_settles_rejects_and_leaves_the_rest_pending() -> None:
    question = _sa(
        reject=[models.AnswerPattern(pattern="Savana", feedback="Nome o bioma.")]
    )
    result = question.score_response("Savana")
    assert (result.score, result.feedback) == (0.0, ["Nome o bioma."])
    with pytest.raises(NotAutoGradable):
        question.score_response("Cerrado")


def test_question_without_any_pattern_is_always_pending() -> None:
    with pytest.raises(NotAutoGradable):
        _sa().score_response("Brasília")


@pytest.mark.parametrize("response", ["Brasília", "", "qualquer coisa"])
def test_incorrect_unmatched_without_accept_scores_every_response_zero(
    response: str,
) -> None:
    assert _sa(unmatched="incorrect").score_response(response).score == 0.0


def test_effective_unmatched_defaults() -> None:
    assert _sa(accept=["Brasília"]).effective_unmatched == "incorrect"
    assert _sa().effective_unmatched == "manual"
    assert _sa(reject=["Rio"]).effective_unmatched == "manual"
    assert _sa(accept=["Brasília"], unmatched="manual").effective_unmatched == "manual"
    assert _sa(unmatched="incorrect").effective_unmatched == "incorrect"


#
# AC1: the same rules for a blank of a fill-in question
#
def _score_blank(blank: models.ShortAnswerBlank, response: str, **fields: Any) -> float:
    return _fill_in(blank, **fields).score_response({blank.id: response}).score


def test_blank_accept_only_defaults_to_incorrect() -> None:
    blank = models.ShortAnswerBlank(id="capital", accept=["Fortaleza"])
    assert _score_blank(blank, "fortaleza") == 1.0
    assert _score_blank(blank, "Recife") == 0.0


def test_blank_without_pattern_is_pending() -> None:
    with pytest.raises(NotAutoGradable):
        _score_blank(models.ShortAnswerBlank(id="capital"), "Fortaleza")


def test_blank_reject_only_settles_the_reject_and_leaves_the_rest_pending() -> None:
    blank = models.ShortAnswerBlank(
        id="bioma",
        reject=[models.AnswerPattern(pattern="Savana", feedback="Nome o bioma.")],
    )
    question = _fill_in(blank)
    result = question.score_response({"bioma": "Savana"})
    assert (result.score, result.feedback) == (0.0, ["Nome o bioma."])
    with pytest.raises(NotAutoGradable):
        question.score_response({"bioma": "Cerrado"})


def test_question_unmatched_applies_to_its_blanks() -> None:
    blank = models.ShortAnswerBlank(id="capital", accept=["Fortaleza"])
    assert _score_blank(blank, "Fortaleza", unmatched="manual") == 1.0
    with pytest.raises(NotAutoGradable):
        _score_blank(blank, "Recife", unmatched="manual")


def test_question_unmatched_incorrect_applies_to_a_blank_without_accept() -> None:
    assert (
        _score_blank(
            models.ShortAnswerBlank(id="capital"), "Recife", unmatched="incorrect"
        )
        == 0.0
    )


def test_pending_blank_makes_the_whole_fill_in_pending() -> None:
    question = _fill_in(
        models.ShortAnswerBlank(id="a", accept=["Cerrado"]),
        models.ShortAnswerBlank(id="b"),
    )
    with pytest.raises(NotAutoGradable):
        question.score_response({"a": "Cerrado", "b": "Pantanal"})


#
# AC2: incorrectFeedback
#
_INCORRECT = "Essa cidade nunca foi a capital."


def test_incorrect_feedback_is_given_to_an_unmatched_incorrect_response() -> None:
    result = _sa(accept=["Brasília"], incorrect_feedback=_INCORRECT).score_response(
        "Salvador"
    )
    assert (result.score, result.feedback) == (0.0, [_INCORRECT])


def test_incorrect_feedback_is_given_to_a_reject_match_without_feedback() -> None:
    question = _sa(
        accept=["Brasília"], reject=["Rio de Janeiro"], incorrect_feedback=_INCORRECT
    )
    assert question.score_response("Rio de Janeiro").feedback == [_INCORRECT]


def test_reject_feedback_wins_over_incorrect_feedback() -> None:
    question = _sa(
        accept=["Brasília"],
        reject=[
            models.AnswerPattern(pattern="Rio de Janeiro", feedback="Foi até 1960.")
        ],
        incorrect_feedback=_INCORRECT,
    )
    assert question.score_response("Rio de Janeiro").feedback == ["Foi até 1960."]


def test_incorrect_feedback_is_not_given_to_a_correct_response() -> None:
    result = _sa(accept=["Brasília"], incorrect_feedback=_INCORRECT).score_response(
        "Brasília"
    )
    assert (result.score, result.feedback) == (1.0, [])


def test_incorrect_feedback_is_not_given_to_a_pending_response() -> None:
    question = _sa(
        accept=["Brasília"], unmatched="manual", incorrect_feedback=_INCORRECT
    )
    with pytest.raises(NotAutoGradable):
        question.score_response("Salvador")


def test_incorrect_feedback_is_given_when_unmatched_incorrect_has_no_accept() -> None:
    result = _sa(unmatched="incorrect", incorrect_feedback=_INCORRECT).score_response(
        "Salvador"
    )
    assert result.feedback == [_INCORRECT]


#
# AC3: automation
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
            "stem": "Ordene.",
            "lines": lines,
            "unmatched": "incorrect",
        },
        kind="question",
    ).document
    manual = mdq.load(
        {"type": "ordering", "stem": "Ordene.", "lines": lines, "unmatched": "manual"},
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


def test_automation_is_not_exported() -> None:
    question = _sa(accept=["Brasília"])
    assert "automation" not in question.frontmatter()
    assert "automation" not in question.to_dict()
    assert "automation" not in _fill_in(_AUTO).to_dict()


@pytest.mark.parametrize("extra", [{"automation": "automatic"}, {"openEnded": True}])
def test_dict_with_a_removed_or_derived_key_is_an_error(extra: dict) -> None:
    loaded = mdq.load(
        {"type": "short-answer", "stem": STEM, "accept": ["Brasília"], **extra},
        kind="question",
    )
    assert [d for d in loaded.diagnostics if d.severity == "error"]


def test_corpus_automation_field_example_is_invalid() -> None:
    loaded = mdq.load(
        INVALID_DIR / "short-answer-automation-field.yaml", kind="question"
    )
    assert [d for d in loaded.diagnostics if d.severity == "error"]


def test_open_ended_is_not_a_field_of_the_models() -> None:
    assert "open_ended" not in models.ShortAnswerQuestion.model_fields
    assert "open_ended" not in models.ShortAnswerBlank.model_fields
    with pytest.raises(ValueError):
        _sa(open_ended=True)


def test_unmatched_and_incorrect_feedback_load_from_a_dict() -> None:
    question = mdq.load(
        {
            "type": "short-answer",
            "stem": STEM,
            "accept": ["Brasília"],
            "unmatched": "manual",
            "incorrectFeedback": _INCORRECT,
        },
        kind="question",
    ).document
    assert question.unmatched == "manual"
    assert question.incorrect_feedback == _INCORRECT


def test_invalid_unmatched_value_is_an_error() -> None:
    loaded = mdq.load(
        {
            "type": "short-answer",
            "stem": STEM,
            "accept": ["Brasília"],
            "unmatched": "maybe",
        },
        kind="question",
    )
    assert [d for d in loaded.diagnostics if d.severity == "error"]


#
# AC4: `*` is an ordinary literal
#
@pytest.mark.parametrize(
    ("response", "score"),
    [("*", 1.0), (" * ", 1.0), ("Brasília", 0.0), ("", 0.0), ("**", 0.0)],
)
def test_asterisk_pattern_is_a_plain_literal(response: str, score: float) -> None:
    assert _sa(accept=["*"]).score_response(response).score == score


@pytest.mark.parametrize(
    ("response", "score"), [("*", 1.0), (" * ", 1.0), ("Brasília", 0.0), ("x", 0.0)]
)
def test_backtick_asterisk_is_the_exact_literal(response: str, score: float) -> None:
    assert _sa(accept=["`*`"]).score_response(response).score == score


def test_asterisk_in_reject_matches_only_an_asterisk() -> None:
    question = _sa(
        accept=["Brasília"], reject=[models.AnswerPattern(pattern="*", feedback="Não.")]
    )
    assert question.score_response("*").feedback == ["Não."]
    assert question.score_response("Salvador").feedback == []


#
# AC5: lints
#
def test_no_correct_answer_for_incorrect_unmatched_without_accept() -> None:
    doc = {
        "type": "short-answer",
        "stem": STEM,
        "unmatched": "incorrect",
        "reject": ["Rio"],
    }
    assert ("no-correct-answer", "warning", ("unmatched",)) in _codes(doc)


@pytest.mark.parametrize(
    "fields",
    [
        {"accept": ["Brasília"], "unmatched": "incorrect"},
        {"accept": ["Brasília"]},
        {"unmatched": "manual"},
        {"reject": ["Rio"]},
        {},
    ],
    ids=["accept-incorrect", "accept-default", "manual", "reject-default", "empty"],
)
def test_no_correct_answer_is_not_reported_otherwise(fields: dict) -> None:
    doc = {"type": "short-answer", "stem": STEM, **fields}
    assert "no-correct-answer" not in [code for code, _, _ in _codes(doc)]


def _fill_doc(*blanks: dict, **fields: Any) -> dict:
    stem = " e ".join(f"[^{b['id']}]" for b in blanks)
    return {
        "type": "fill-in",
        "stem": f"Complete: {stem}.",
        "blanks": [{"type": "short-answer", **b} for b in blanks],
        **fields,
    }


def test_no_correct_answer_for_a_blank_under_the_question_unmatched() -> None:
    doc = _fill_doc(
        {"id": "a", "accept": ["Cerrado"]}, {"id": "b"}, unmatched="incorrect"
    )
    reported = [
        path for code, severity, path in _codes(doc) if code == "no-correct-answer"
    ]
    assert reported == [("blanks", 1)]
    assert ("no-correct-answer", "warning", ("blanks", 1)) in _codes(doc)


def test_no_correct_answer_is_not_reported_for_a_blank_that_defaults_to_manual() -> (
    None
):
    doc = _fill_doc({"id": "a", "accept": ["Cerrado"]}, {"id": "b"})
    assert "no-correct-answer" not in [code for code, _, _ in _codes(doc)]


@pytest.mark.parametrize("text", ["   ", "​", "\n"])
def test_blank_incorrect_feedback_is_a_warning(text: str) -> None:
    doc = {
        "type": "short-answer",
        "stem": STEM,
        "accept": ["Brasília"],
        "incorrectFeedback": text,
    }
    assert ("blank-text-field", "warning", ("incorrectFeedback",)) in _codes(doc)


def test_visible_incorrect_feedback_is_not_reported() -> None:
    doc = {
        "type": "short-answer",
        "stem": STEM,
        "accept": ["Brasília"],
        "incorrectFeedback": _INCORRECT,
    }
    assert "blank-text-field" not in [code for code, _, _ in _codes(doc)]


@pytest.mark.parametrize(
    "code", ["accept-wildcard", "unreachable-reject", "short-answer-not-gradable"]
)
@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"accept": ["*"]},
        {"accept": ["Brasília"], "reject": ["*", "Rio"]},
        {"reject": ["Rio"]},
    ],
    ids=["no-pattern", "accept-asterisk", "reject-asterisk-first", "reject-only"],
)
def test_removed_lint_codes_are_never_reported(code: str, fields: dict) -> None:
    doc = {"type": "short-answer", "stem": STEM, **fields}
    assert code not in [c for c, _, _ in _codes(doc)]

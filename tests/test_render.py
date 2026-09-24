import difflib
import io
from typing import Any

import pytest
from hypothesis import given
from rich.console import Console

from mdq import models, parse
from mdq.hypothesis import documents as mst


#
# Examples
#
def test_render_essay_question() -> None:
    question = models.EssayQuestion(
        id="life",
        title="Essay Question",
        stem="What is the meaning of life?",
    )
    src = question.render()
    expected = """
---
id: life
title: Essay Question
---

What is the meaning of life?

[essay]
""".strip()
    assert src == expected


def test_render_multiple_choice_question() -> None:
    question = models.MultipleChoiceQuestion(
        id="life",
        preamble="This is the preamble.",
        stem="What is the meaning of life?",
        choices=[
            models.ScoredChoice(text="42", score=1),
            models.ScoredChoice(text="Love"),
            models.ScoredChoice(text="Happiness"),
        ],
    )
    src = question.render()
    expected = """
[life] This is the preamble.

What is the meaning of life?

* [*] 42
* [ ] Love
* [ ] Happiness
""".strip()
    assert src == expected


def test_render_multiple_selection_question() -> None:
    question = models.MultipleSelectionQuestion(
        id="life",
        preamble="This is the preamble.",
        stem="What is the meaning of life?",
        choices=[
            models.BooleanChoice(text="42", correct=True),
            models.BooleanChoice(
                text="Love", correct=True, feedback="All we need is love."
            ),
            models.BooleanChoice(
                text="Happiness", correct=True, comment="Happiness is a warm gun?"
            ),
        ],
    )
    src = question.render()
    expected = """
[life] This is the preamble.

What is the meaning of life?

* [x] 42
* [x] Love
  > All we need is love.
* [x] Happiness
  ! Happiness is a warm gun?
""".strip()
    assert src == expected


def test_render_true_false_question() -> None:
    question = models.TrueFalseQuestion(
        id="life",
        preamble="This is the preamble.",
        stem="What is the meaning of life?",
        choices=[
            models.Statement(text="Happiness", correct=True),
            models.Statement(text="Money"),
        ],
    )
    src = question.render()
    expected = """
[life] This is the preamble.

What is the meaning of life?

* [T] Happiness
* [F] Money
""".strip()
    assert src == expected


def test_render_numeric_question() -> None:
    question = models.NumericQuestion(
        id="pi",
        stem="What is pi?",
        answer=3.14,
        unit="rad",
        domain="decimal",
        decimal_places=2,
        tolerance=models.Tolerance(absolute=0.1, relative=0.05),
    )
    src = question.render()
    expected = """
---
decimalPlaces: 2
domain: decimal
id: pi
---

What is pi?

[numeric(rad)]: 3.14 +- 0.1 +- 5.0%
""".strip()
    assert src == expected


def test_render_short_answer_question() -> None:
    question = models.ShortAnswerQuestion(
        stem="Name a primary colour.",
        one_of=["`red`", "`green`", "`blue`"],
    )
    src = question.render()
    expected = (
        "\nName a primary colour.\n\n"
        "[short-answer]:\n"
        "* `red`\n"
        "* `green`\n"
        "* `blue`"
    )
    assert src == expected


def test_render_essay_question_with_answer_key() -> None:
    question = models.EssayQuestion(
        stem="Explain the greenhouse effect.",
        epilogue="Use one paragraph.",
        input="code",
        highlight="python",
        answer_key="A model answer.",
    )
    src = question.render()
    expected = """
---
highlight: python
input: code
---

Explain the greenhouse effect.

[essay]

Use one paragraph.

## [answer-key]

A model answer.
""".strip()
    assert src == expected


def test_render_fill_in_question() -> None:
    question = models.FillInQuestion(
        stem="The capital is [^capital], and pi is [^pi].",
        shuffle=True,
        grading="partial",
        blanks=[
            models.ChoiceBlank(
                id="capital",
                choices=[
                    models.ScoredChoice(id="brasilia", text="Brasília", score=1),
                    models.ScoredChoice(id="rio", text="Rio", score=0),
                ],
            ),
            models.ShortAnswerBlank(id="river", regex="Amazon"),
            models.NumericBlank(
                id="pi",
                answer=3.14,
                tolerance=models.Tolerance(relative=0.05),
            ),
        ],
    )
    src = question.render()
    expected = """
---
grading: partial
shuffle: true
---

The capital is [^capital], and pi is [^pi].

[^capital]:
* [*] Brasília
* [ ] Rio

[^river/short-answer]: /Amazon/

[^pi/numeric]: 3.14 +- 5.0%
""".strip()
    assert src == expected


#
# normalize() on a multi-block stem
#
# `stem` is just a non-empty string in the schema (`schema/
# question-base.yaml`); `docs/question-types/generic.md` only
# *recommends* -- "SHOULD" -- that it be a single paragraph, so a model
# built by hand (not through `mdq.hypothesis`, which never generates a
# multi-block stem) may legally carry more than one block in it.
# `MDQParser.split_intro` always treats the *last* intro block as the
# stem, so that is where normalize has to leave content too -- not the
# first, and not both (silently dropping everything past the first
# block used to be the bug here).
#
def test_normalize_moves_leading_stem_blocks_into_preamble() -> None:
    question = models.EssayQuestion(
        id="x", stem="First paragraph.\n\nSecond paragraph."
    )
    normalized = question.normalize()

    assert normalized.preamble == "First paragraph."
    assert normalized.stem == "Second paragraph."

    rt = parse(normalized.render(), kind="question")
    assert rt == normalized


def test_normalize_appends_leading_stem_blocks_after_existing_preamble() -> None:
    question = models.EssayQuestion(preamble="Intro.", stem="Middle.\n\nLast one.")
    normalized = question.normalize()

    assert normalized.preamble == "Intro.\n\nMiddle."
    assert normalized.stem == "Last one."

    rt = parse(normalized.render(), kind="question")
    assert rt == normalized


def test_id_does_not_inline_onto_a_stem_that_leads_with_a_non_paragraph_block() -> None:
    """
    Regression test for `can_inline_id`: with no preamble, the `[id]`
    prefix would land on the *stem's* first block. Rendering directly
    (no `.normalize()` first, which would otherwise migrate the leading
    list into the preamble) exercises the check on an unnormalized
    model, where a multi-block stem's first block need not be a
    paragraph.
    """
    question = models.EssayQuestion(id="x", stem="- a list item\n\nActual stem text.")
    src = question.render()

    assert "id: x" in src


#
# Generalization
#
class AssertRTError(AssertionError):
    def __init__(self, question: models.Question, rt: models.Question):
        self.question = question
        self.rt = rt

    def __str__(self) -> str:
        file = io.StringIO()
        console = Console(markup=False, highlight=False, file=file)

        console.print("Roundtrip and original questions are not equal.")

        console.print("Diff (lines)")
        console.print(
            "\n".join(
                difflib.ndiff(
                    str(self.question).splitlines(),
                    str(self.rt).splitlines(),
                )
            )
        )

        console.print("Roundtrip question:")
        console.print(self.rt)

        console.print("Diff (original, roundtrip)")
        console.print(diffdicts(self.question.to_dict(), self.rt.to_dict()))

        return file.getvalue()


@pytest.mark.slow
@given(mst.questions(normalize=True))
def test_render_question_roundtrip(question: models.Question) -> None:
    """
    Test that rendering a question and then parsing it back yields the same
    question.
    """
    # pytest.skip("Skipping this test because it is slow and flaky.")

    src = question.render()
    rt = parse(src, kind="question")
    if rt != question:
        raise AssertRTError(question, rt)


def diffdicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """
    Return a dict of the differences between two dicts.
    """
    return {
        k: (a_value, b_value)
        for k in set(a.keys()).union(b.keys())
        if (a_value := a.get(k)) != (b_value := b.get(k))
    }

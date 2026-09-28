"""
`Exam.render()`: an exam renders to MDQ Markdown that parses back to the
same exam (docs/exam.md).
"""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mdq import models, parse
from mdq.hypothesis import documents as mst
from _corpus import VALID_EXAMS, VALID_EXAMS_DIR, relative_id

#: `exam/bank/` holds the questions the exams include, not exams.
EXAMS = [source for source in VALID_EXAMS if source.parent == VALID_EXAMS_DIR]


@pytest.mark.parametrize("source", EXAMS, ids=relative_id)
def test_valid_exam_roundtrip(source: Path) -> None:
    exam = parse(source, kind="exam")
    rendered = parse(exam.render(), kind="exam", format="mdq")
    assert rendered.to_dict() == exam.to_dict()


def test_render_exam() -> None:
    exam = models.Exam(
        id="midterm",
        title="Midterm Exam",
        course="CS101",
        locale="pt-BR",
        penalty="capped",
        instructions="Answer every question.",
        questions=[
            models.Include(include="recursion-01"),
            models.IncludeAll(include_all="recursion AND NOT draft", max=2),
            models.EssayQuestion(stem="Why is the sky blue?", locale="pt-BR"),
            models.EssayQuestion(id="biomes", stem="Name two Brazilian biomes."),
        ],
    )
    expected = """
---
course: CS101
locale: pt-BR
penalty: capped
---

# [midterm] Midterm Exam

Answer every question.

---
include: recursion-01
---

---
include-all: recursion AND NOT draft
max: 2
---

===

Why is the sky blue?

[essay]

===

[biomes] Name two Brazilian biomes.

[essay]
""".strip()
    assert exam.render() == expected
    assert str(exam) == expected


def test_render_exam_without_title() -> None:
    exam = models.Exam(questions=[])
    assert parse(exam.render(), kind="exam", format="mdq") == exam


def test_render_exam_keeps_title_that_looks_like_a_slug() -> None:
    exam = models.Exam(title="[draft] Final exam", questions=[])
    assert parse(exam.render(), kind="exam", format="mdq") == exam


def test_render_exam_keeps_multiline_title() -> None:
    exam = models.Exam(id="final", title="Final\nexam", questions=[])
    assert parse(exam.render(), kind="exam", format="mdq") == exam


def test_render_exam_keeps_non_slug_id() -> None:
    exam = models.Exam(id="final exam", title="Final", questions=[])
    assert parse(exam.render(), kind="exam", format="mdq") == exam


@st.composite
def exams(draw: st.DrawFn) -> models.Exam:
    questions = draw(st.lists(mst.questions(normalize=True), max_size=3))
    ids = [q.id for q in questions if q.id is not None]
    if len(ids) != len(set(ids)):
        questions = [q.model_copy(update={"id": None}) for q in questions]
    return models.Exam(
        id=draw(st.none() | mst.slugs()),
        title=draw(st.none() | st.sampled_from(["Midterm", "Prova de Biologia"])),
        instructions=draw(st.none() | st.just("Leia com atenção.")),
        questions=questions,
    )


@pytest.mark.slow
@given(exams())
def test_render_exam_roundtrip(exam: models.Exam) -> None:
    rendered = parse(exam.render(), kind="exam", format="mdq")
    assert rendered.to_dict() == exam.to_dict()

"""
Exam documents: the include-resolution API (banks, loaders, errors) and
`Exam` model behavior. Block splitting, recognition, inheritance, numbering
and resolution of the documents themselves are covered by the corpus in
`examples/valid/exam/`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import mdq
from mdq import load
from mdq.models import EssayQuestion, Exam, Include
from mdq._banks import DictLoader, FileLoader, IncludeNotFound, QuestionBank
from _corpus import VALID_DIR

MIDTERM = VALID_DIR / "exam" / "midterm.mdq.md"


# ---------------------------------------------------------------------
# include resolution
# ---------------------------------------------------------------------


def resolved_midterm(bank: QuestionBank | None = None) -> Exam:
    return load(MIDTERM).validate().resolve(bank or FileLoader(MIDTERM.parent))


def _write_question(path: Path, stem: str) -> None:
    path.write_text(
        f"---\ntags: [biomas]\n---\n\n{stem}\n\n* [T] Sim.\n* [F] Não.\n",
        encoding="utf-8",
    )


def test_file_loader_reads_plain_md_files(tmp_path: Path) -> None:
    _write_question(tmp_path / "pantanal.md", "Sobre o Pantanal:")
    _write_question(tmp_path / "cerrado.mdq.md", "Sobre o Cerrado:")
    loader = FileLoader(tmp_path)
    assert "Pantanal" in loader.load("pantanal")
    assert set(loader.tagged("biomas")) == {"pantanal", "cerrado"}


def test_file_loader_prefers_mdq_md_over_md(tmp_path: Path) -> None:
    _write_question(tmp_path / "caatinga.md", "Arquivo .md")
    _write_question(tmp_path / "caatinga.mdq.md", "Arquivo .mdq.md")
    assert "Arquivo .mdq.md" in FileLoader(tmp_path).load("caatinga")


def test_file_loader_can_be_restricted_to_its_root() -> None:
    with pytest.raises(IncludeNotFound):
        FileLoader(MIDTERM.parent, recursive=False).load("recursion-01")


def test_resolve_does_not_change_the_exam() -> None:
    exam = load(MIDTERM).validate()
    exam.resolve(FileLoader(MIDTERM.parent))
    assert isinstance(exam.questions[0], Include)


def test_an_unresolvable_include_raises() -> None:
    with pytest.raises(IncludeNotFound) as excinfo:
        resolved_midterm(DictLoader({}))
    assert excinfo.value.question_id == "recursion-01"


def test_any_object_with_the_protocol_is_a_bank() -> None:
    """`resolve` depends on the protocol, not on FileLoader."""

    class Bank:
        def load(self, question_id: str) -> dict:
            return {"type": "essay", "stem": f"Question {question_id}."}

        def tagged(self, tag: str) -> set[str]:
            return set()

        def ids(self) -> set[str]:
            return set()

    assert isinstance(Bank(), QuestionBank)
    assert resolved_midterm(Bank()).questions[0].stem == "Question recursion-01."


def test_equal_exams_compare_equal_without_recursing() -> None:
    """
    Regression: each question holds a weakref back to its exam, and a
    weakref compares its referents, so `==` used to recurse forever.
    """
    from mdq.models import EssayQuestion, Exam

    first = Exam(questions=[EssayQuestion(stem="Explain photosynthesis.")])
    second = Exam(questions=[EssayQuestion(stem="Explain photosynthesis.")])
    other = Exam(questions=[EssayQuestion(stem="Explain plate tectonics.")])

    assert first == second
    assert first != other


def _exam_with_essay() -> Exam:
    return Exam.model_validate(
        {"type": "exam", "questions": [{"type": "essay", "stem": "Fale do Cerrado."}]}
    )


def test_with_ids_binds_questions_to_the_new_exam() -> None:
    exam = _exam_with_essay()
    with_ids = exam.with_ids()
    question = with_ids.questions[0]
    assert isinstance(question, EssayQuestion)
    assert question.exam is with_ids


def test_model_copy_binds_questions_to_the_copy_only() -> None:
    exam = _exam_with_essay()
    copy = exam.model_copy()
    original, copied = exam.questions[0], copy.questions[0]
    assert isinstance(original, EssayQuestion) and isinstance(copied, EssayQuestion)
    assert copied is not original
    assert copied.exam is copy
    assert original.exam is exam


def test_loading_with_filled_ids_binds_questions_to_the_document() -> None:
    document = mdq.load(
        "# Prova\n\n===\n\nFale do Cerrado.\n\n[essay]\n", format="mdq", ids="fill"
    ).document
    assert isinstance(document, Exam)
    question = document.questions[0]
    assert isinstance(question, EssayQuestion)
    assert question.exam is document

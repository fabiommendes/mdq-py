"""
Exam documents: block splitting, include resolution and `Exam` model
behavior. Recognition, inheritance, numbering and resolution of the
documents themselves are covered by the corpus in `examples/valid/exam/`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mdq import load
from mdq.models import Exam, Include
from mdq._banks import DictLoader, FileLoader, IncludeNotFound, QuestionBank
from _corpus import VALID_DIR
from _parse import parse_any

MIDTERM = VALID_DIR / "exam" / "midterm.mdq.md"


# ---------------------------------------------------------------------
# block splitting
# ---------------------------------------------------------------------


def test_separator_needs_a_blank_line_before_it() -> None:
    """Without one, CommonMark reads `===` as a setext underline and turns
    the paragraph above into an H1 -- which is exam-title syntax."""
    exam = parse_any("# Exam\n\nJudge this\n===\n\nmore text\n")
    assert exam["questions"] == []


#: `duplicate-question-id` is a model error now, not a lint warning --
#: see test_two_inline_questions_with_the_same_id_is_a_model_error and
#: friends in tests/test_unique_ids.py (dev/specs/to-do/unique-ids.md).


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


def test_a_resolved_include_inherits_from_the_exam() -> None:
    assert resolved_midterm().questions[0].locale == "pt-BR"


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

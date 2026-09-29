"""
Exam documents: recognition, block splitting, include resolution, and the
inheritance and numbering rules from docs/exam.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mdq import load
from mdq.models import Exam, Include
from mdq._banks import DictLoader, FileLoader, IncludeNotFound, QuestionBank
from mdq._parser import is_exam
from _corpus import VALID_DIR, parsed_sibling
from _parse import parse_any, parse_file

MIDTERM = VALID_DIR / "exam" / "midterm.mdq.md"


def load_document(path):
    """The parsed sibling's own data, loaded straight off disk."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))

MINIMAL = """# [ex] Exam

===

What is the capital of Brazil?

* [ ] Lisbon
* [*] Brasília
"""


def _rules(diagnostics) -> set[str]:
    return {d.code for d in diagnostics}


# ---------------------------------------------------------------------
# recognition
# ---------------------------------------------------------------------


def test_h1_marks_an_exam() -> None:
    assert is_exam(MINIMAL)


def test_a_question_is_not_an_exam() -> None:
    """A question can never carry an H1, which is what makes the H1 a
    reliable discriminator."""
    assert not is_exam("Explain recursion.\n\n[essay]\n")


def test_h1_after_frontmatter_still_marks_an_exam() -> None:
    assert is_exam("---\ncourse: CS101\n---\n\n# Exam\n")


def test_parse_dispatches_on_kind() -> None:
    assert parse_any(MINIMAL)["type"] == "exam"
    assert parse_any("Explain recursion.\n\n[essay]\n")["type"] == "essay"


# ---------------------------------------------------------------------
# the worked example
# ---------------------------------------------------------------------


def test_midterm_matches_its_fixture() -> None:
    assert parse_file(MIDTERM) == load_document(parsed_sibling(MIDTERM))


def test_midterm_validates() -> None:
    assert load(MIDTERM).document.resolve(FileLoader(MIDTERM.parent))


def test_title_and_slug_come_from_the_h1() -> None:
    doc = parse_file(MIDTERM)
    assert doc["id"] == "midterm"
    assert doc["title"] == "Midterm Exam"


def test_frontmatter_beats_the_h1() -> None:
    doc = parse_any("---\nid: from-front\ntitle: Front\n---\n\n# [from-h1] H1 Title\n")
    assert doc["id"] == "from-front"
    assert doc["title"] == "Front"


def test_instructions_are_the_text_before_the_first_question() -> None:
    assert parse_file(MIDTERM)["instructions"] == (
        "Answer every question. You have two hours."
    )


# ---------------------------------------------------------------------
# block splitting
# ---------------------------------------------------------------------


def test_both_block_forms_are_recognized() -> None:
    """A question begins at a `===` separator or at its own frontmatter."""
    doc = parse_file(MIDTERM)
    assert len(doc["questions"]) == 3


def test_separator_needs_a_blank_line_before_it() -> None:
    """Without one, CommonMark reads `===` as a setext underline and turns
    the paragraph above into an H1 -- which is exam-title syntax."""
    exam = parse_any("# Exam\n\nJudge this\n===\n\nmore text\n")
    assert exam["questions"] == []


def test_exam_with_no_questions_parses_and_warns() -> None:
    doc = parse_any("# [empty] Draft Exam\n\nStill being written.\n")
    assert doc["questions"] == []
    loaded = load(doc)
    assert loaded
    assert "exam-without-questions" in _rules(loaded.diagnostics)


#: `duplicate-question-id` is a model error now, not a lint warning --
#: see test_two_inline_questions_with_the_same_id_is_a_model_error and
#: friends in tests/test_unique_ids.py (dev/specs/to-do/unique-ids.md).


# ---------------------------------------------------------------------
# implicit ids
# ---------------------------------------------------------------------


def test_questions_without_an_id_are_numbered_by_position() -> None:
    """
    The parser itself no longer numbers anything -- a question with no
    declared `id` keeps none (dev/specs/to-do/derived-ids.md).
    `Exam.with_ids()` is what gives it `q1`; see
    tests/test_derived_ids.py.
    """
    doc = parse_any(MINIMAL)
    assert doc["questions"][0].get("id") is None


def test_an_include_occupies_a_position() -> None:
    """
    exam.md: a question's derived id matches the position the student
    sees, so an include in slot 1 makes the next question's derived id
    q2 -- but the parser only leaves the id absent; `Exam.with_ids()`
    does the counting (tests/test_derived_ids.py).
    """
    doc = parse_file(MIDTERM)
    ids = [q.get("include") or q.get("id") for q in doc["questions"]]
    assert ids == ["recursion-01", "factorial", None]


def test_a_declared_id_is_kept() -> None:
    assert parse_file(MIDTERM)["questions"][1]["id"] == "factorial"


# ---------------------------------------------------------------------
# inheritance
# ---------------------------------------------------------------------


def test_questions_inherit_locale_and_author() -> None:
    question = parse_file(MIDTERM)["questions"][1]
    assert question["locale"] == "pt-BR"
    assert question["author"] == "Fábio Macêdo Mendes"


def test_a_question_keeps_its_own_locale() -> None:
    doc = parse_any(
        "---\nlocale: pt-BR\n---\n\n# Exam\n\n---\nlocale: en\n---\n\n"
        "Explain X.\n\n[essay]\n"
    )
    assert doc["questions"][0]["locale"] == "en"


def test_tags_are_not_inherited() -> None:
    doc = parse_any(
        "---\ntags: [midterm, cs101]\n---\n\n# Exam\n\n===\n\nExplain X.\n\n[essay]\n"
    )
    assert doc["tags"] == ["midterm", "cs101"]
    assert "tags" not in doc["questions"][0]


def test_course_is_not_inherited() -> None:
    doc = parse_any(
        "---\ncourse: CS101\n---\n\n# Exam\n\n===\n\nExplain X.\n\n[essay]\n"
    )
    assert "course" not in doc["questions"][0]


def test_description_lands_on_the_exam_and_is_not_inherited() -> None:
    """The exam's frontmatter `description` is copied verbatim onto the
    parsed exam, never onto its questions -- including a question that
    declares its own frontmatter block. `description` is not a question
    field, so the question's block is left exactly as it would be without
    this change: `description` absent from it either way."""
    doc = parse_any(
        "---\ndescription: A midterm covering functions and recursion.\n"
        "---\n\n# Exam\n\n"
        "---\ndescription: Some question-level note.\n---\n\n"
        "Explain X.\n\n[essay]\n"
    )
    assert doc["description"] == "A midterm covering functions and recursion."
    assert "description" not in doc["questions"][0]


# ---------------------------------------------------------------------
# include resolution
# ---------------------------------------------------------------------


def test_includes_are_unresolved_after_load() -> None:
    """An exam whose includes have not been resolved is still well-formed;
    where a question lives is the host's business."""
    doc = parse_file(MIDTERM)
    assert doc["questions"][0] == {"include": "recursion-01"}
    exam = load(MIDTERM).validate()
    assert exam.questions[0] == Include(include="recursion-01")


def resolved_midterm(bank: QuestionBank | None = None) -> Exam:
    return load(MIDTERM).validate().resolve(bank or FileLoader(MIDTERM.parent))


def test_file_loader_resolves_an_include() -> None:
    included = resolved_midterm().questions[0]
    assert included.type == "essay"
    assert included.title == "Base cases"


def test_file_loader_searches_subdirectories() -> None:
    """recursion-01 lives in exam/bank/, not beside the exam itself."""
    loader = FileLoader(MIDTERM.parent)
    source = loader.load("recursion-01")
    assert isinstance(source, str)
    assert parse_any(source)["id"] == "recursion-01"


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


def test_a_resolved_include_keeps_its_own_id() -> None:
    """It names a question that already has an identity, so the exam's
    positional numbering never renames it."""
    assert resolved_midterm().questions[0].id == "recursion-01"


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


@pytest.mark.parametrize("rule", ["***", "___"])
def test_epilogue_thematic_break_other_than_dashes_is_allowed(rule: str) -> None:
    text = f"# Exam\n\n===\n\nExplique.\n\n[essay]\n\n{rule}\n\nRubrica.\n"
    assert len(parse_any(text)["questions"]) == 1


def test_epilogue_dash_thematic_break_is_an_error() -> None:
    """docs/exam.md: after the body, `---` can only start the next block."""
    text = "# Exam\n\n===\n\nExplique.\n\n[essay]\n\n---\n\nRubrica.\n"
    loaded = load(text)
    assert loaded.document is None
    assert [d.code for d in loaded.diagnostics] == ["parse-error"]

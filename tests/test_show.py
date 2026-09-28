"""
Tests for `mdq.show` and the `mdq show` CLI command.

Mirrors the pattern in `tests/test_render.py`: render into a
`rich.console.Console` backed by an `io.StringIO()` and assert on the
captured text. The broad parametrized test over `VALID_SOURCES` guards
against `show` blowing up on any real document in the example corpus;
the targeted tests below it check that each question type actually
shows what makes it different from the others, and that the answer key
is hidden -- not just replaced by a differently-labelled reveal -- when
`show_answer_key` is false.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from mdq import show as show_mod
from mdq.cli import app
from mdq.loaders import FileLoader
from _corpus import VALID_EXAMS, VALID_QUESTIONS, VALID_SOURCES, relative_id

runner = CliRunner()


def render(path: Path, *, show_answer_key: bool = True) -> str:
    """Render `path` with `mdq.show.show_source` and return the plain text."""
    buf = io.StringIO()
    console = Console(file=buf, width=100, highlight=False)
    src = path.read_text(encoding="utf-8")
    show_mod.show_source(
        src,
        console,
        show_answer_key=show_answer_key,
        bank=FileLoader(path.parent),
    )
    return buf.getvalue()


def render_source(src: str, *, show_answer_key: bool = True) -> str:
    """Like `render`, but for source text that isn't on disk (no bank)."""
    buf = io.StringIO()
    console = Console(file=buf, width=100, highlight=False)
    show_mod.show_source(src, console, show_answer_key=show_answer_key)
    return buf.getvalue()


#
# Broad coverage: every valid example must render without raising.
#
def test_valid_sources_dir_has_documents() -> None:
    assert VALID_SOURCES, "no example .mdq.md sources found -- check the fixture path"


@pytest.mark.parametrize(
    "path", VALID_SOURCES, ids=[relative_id(p) for p in VALID_SOURCES]
)
def test_show_runs_on_every_valid_example(path: Path) -> None:
    render(path, show_answer_key=True)
    render(path, show_answer_key=False)


#
# Targeted assertions, one per question type.
#
def test_show_multiple_choice() -> None:
    path = next(p for p in VALID_QUESTIONS if p.name == "partial-credit.mdq.md")
    shown = render(path)
    assert "Pacific" in shown
    assert "Atlantic" in shown
    assert "+50%" in shown
    assert "-25%" in shown

    hidden = render(path, show_answer_key=False)
    assert "Pacific" in hidden
    assert "+50%" not in hidden
    assert "-25%" not in hidden


def test_show_multiple_selection() -> None:
    path = next(
        p
        for p in VALID_QUESTIONS
        if p.name == "simple.mdq.md" and "multiple-selection" in str(p)
    )
    shown = render(path)
    assert "Brasília" in shown
    assert "Lisbon" in shown

    hidden = render(path, show_answer_key=False)
    assert "Brasília" in hidden
    # No correctness mark should distinguish the correct choices anymore.
    marks = {
        line[:4] for line in hidden.splitlines() if "Bras" in line or "Lisbon" in line
    }
    assert len(marks) <= 1


def test_show_true_false() -> None:
    path = next(
        p
        for p in VALID_QUESTIONS
        if p.name == "simple.mdq.md" and "true-false" in str(p)
    )
    shown = render(path)
    assert "Earth is flat" in shown
    assert "Humans descend from apes" in shown


def test_show_numeric() -> None:
    path = next(p for p in VALID_QUESTIONS if p.name == "tolerances.mdq.md")
    shown = render(path)
    assert "Answer key" in shown
    assert "3.14" in shown

    hidden = render(path, show_answer_key=False)
    assert "3.14" not in hidden
    assert "hidden" in hidden.lower()


def test_show_short_answer() -> None:
    path = next(p for p in VALID_QUESTIONS if p.name == "regex.mdq.md")
    shown = render(path)
    assert "Answer key" in shown
    assert "1822" in shown

    hidden = render(path, show_answer_key=False)
    assert "1822-0?9-0?7" not in hidden
    assert "hidden" in hidden.lower()


def test_show_short_answer_open_ended() -> None:
    path = next(p for p in VALID_QUESTIONS if p.name == "open-ended.mdq.md")
    shown = render(path)
    assert "manual" in shown.lower()
    assert "Answer key" not in shown


def test_show_essay() -> None:
    path = next(p for p in VALID_QUESTIONS if p.name == "answer-key.mdq.md")
    shown = render(path)
    assert "Answer key" in shown
    assert "greenhouse effect is a natural process" in shown

    hidden = render(path, show_answer_key=False)
    assert "greenhouse effect is a natural process" not in hidden
    assert "hidden" in hidden.lower()


def test_show_fill_in() -> None:
    path = next(p for p in VALID_QUESTIONS if p.name == "mixed-blanks.mdq.md")
    shown = render(path)
    assert "planet" in shown
    assert "Jupiter" in shown
    assert "95" in shown
    assert "storm" in shown

    hidden = render(path, show_answer_key=False)
    assert "Jupiter" not in hidden
    assert "95" not in hidden


def test_show_ordering() -> None:
    path = next(
        p for p in VALID_QUESTIONS if p.name == "brazil-timeline.mdq.md"
    )
    markers = ["Cabral", "Lisbon", "independence", "Áurea", "Brasília"]

    shown = render(path)
    for marker in markers:
        assert marker in shown
    # `[ordering]`'s lines are always authored in the correct order, so
    # the answer-key view must show them exactly as written.
    assert sorted(markers, key=shown.index) == markers

    hidden = render(path, show_answer_key=False)
    for marker in markers:
        assert marker in hidden
    # `_render_ordering` sorts (text, level) instead of shuffling, since
    # its output is tested -- but the hidden view must still not present
    # the lines in their authored (i.e. correct) order.
    assert sorted(markers, key=hidden.index) != markers


def test_show_ordering_answer_key_reveals_alternatives_and_feedback() -> None:
    path = next(p for p in VALID_QUESTIONS if p.name == "reject-feedback.mdq.md")
    shown = render(path)
    assert "Rejected alternative" in shown
    assert "differential survival must come first" in shown

    hidden = render(path, show_answer_key=False)
    assert "Rejected alternative" not in hidden
    assert "differential survival must come first" not in hidden


#
# Regression: document content must never be parsed as Rich console
# markup. Square brackets show up constantly in real MDQ (`[^blank]`
# references, `[essay]` tags, `[id]` prefixes), and a document is free to
# put anything -- including a stray closing tag -- into a title or tag.
#
def test_show_preserves_brackets_in_title_and_tags() -> None:
    src = """\
---
type: multiple-choice
title: "Escolha [a] ou [b]"
tags: [bold red, item]
---

Qual é o maior rio do Brasil?

* [*] Amazonas
* [ ] São Francisco
"""
    shown = render_source(src)
    assert "Escolha [a] ou [b]" in shown
    assert "bold red, item" in shown


def test_show_survives_a_closing_tag_in_document_content() -> None:
    src = """\
---
type: essay
title: "A [/] B"
---

Explique.

[essay]
"""
    shown = render_source(src)
    assert "A [/] B" in shown


def test_show_exam_renders_description_row() -> None:
    src = (
        "---\ndescription: A midterm covering functions and recursion.\n---\n\n"
        "# Exam\n\n===\n\nExplain X.\n\n[essay]\n"
    )
    shown = render_source(src)
    assert "Description" in shown
    assert "A midterm covering functions and recursion." in shown


def test_show_exam() -> None:
    path = next(p for p in VALID_EXAMS if p.name == "midterm.mdq.md")
    shown = render(path)
    assert "Midterm Exam" in shown
    assert "Question 1" in shown
    assert "Question 2" in shown
    assert "Question 3" in shown
    # The include was resolved: the included question's own content shows up.
    assert "base case" in shown.lower()


#
# CLI, end to end.
#
def test_cli_show_question() -> None:
    path = next(
        p
        for p in VALID_QUESTIONS
        if p.name == "simple.mdq.md" and "multiple-selection" in str(p)
    )
    result = runner.invoke(app, ["show", str(path)])
    assert result.exit_code == 0
    assert "Brasília" in result.output


def test_cli_show_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.mdq.md"
    result = runner.invoke(app, ["show", str(missing)])
    assert result.exit_code == 2


def test_cli_show_malformed_document(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mdq.md"
    broken.write_text("", encoding="utf-8")
    result = runner.invoke(app, ["show", str(broken)])
    assert result.exit_code == 1


def test_cli_show_no_answer_key_flag() -> None:
    path = next(p for p in VALID_QUESTIONS if p.name == "answer-key.mdq.md")
    result = runner.invoke(app, ["show", "--no-answer-key", str(path)])
    assert result.exit_code == 0
    assert "greenhouse effect is a natural process" not in result.output


def test_cli_show_preserves_brackets(tmp_path: Path) -> None:
    doc = tmp_path / "brackets.mdq.md"
    doc.write_text(
        '---\ntitle: "A [/] B"\n---\n\nExplique.\n\n[essay]\n', encoding="utf-8"
    )
    result = runner.invoke(app, ["show", str(doc)])
    assert result.exit_code == 0
    assert "A [/] B" in result.output


def test_cli_show_error_message_with_brackets_does_not_crash(tmp_path: Path) -> None:
    """
    A `ParseError` message can itself embed document content with square
    brackets (e.g. an unrecognized `[^id/type]:` blank tag) -- the error
    path must print it verbatim, not choke on it as markup.
    """
    doc = tmp_path / "bad-blank.mdq.md"
    doc.write_text(
        "The value is [^x].\n\n[^x/weird]: something\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["show", str(doc)])
    assert result.exit_code == 1
    # A clean `typer.Exit` surfaces as `SystemExit` here -- anything else
    # (e.g. the `MarkupError` this test guards against) would be a
    # different exception type reaching the runner uncaught.
    assert isinstance(result.exception, SystemExit)
    assert "[^x/weird]" in result.output


def test_cli_show_stdin() -> None:
    path = next(
        p
        for p in VALID_QUESTIONS
        if p.name == "simple.mdq.md" and "true-false" in str(p)
    )
    src = path.read_text(encoding="utf-8")
    result = runner.invoke(app, ["show", "-"], input=src)
    assert result.exit_code == 0
    assert "Earth is flat" in result.output

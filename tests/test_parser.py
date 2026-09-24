"""
Parse MDQ Markdown source and check it against the paired `.yaml` fixture
that documents the exact document a conforming parser must produce.

Coverage here is intentionally partial: the parser is basic and some
fixtures encode ids or fields that (as far as we can tell) no
deterministic rule can reproduce -- see the comments below and the
project report for specifics. `NOT_YET_SUPPORTED` documents precisely
which of the 38 valid pairs are expected to fail today, so the
parametrized test doubles as a progress log rather than silently
skipping unknown breakage.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from mdq import load
from mdq.loaders import FileLoader
from mdq.parser import parse_any, parse_exam, parse_file
from mdq.testing import VALID_SOURCES, parsed_sibling, relative_id

#: Pairs the parser is known not to reproduce exactly, with the reason.
#: Keyed by the same id `relative_id` gives the pair (e.g.
#: "multiple-choice.composite-ids.mdq.md").
NOT_YET_SUPPORTED: dict[str, str] = {
    "multiple-choice.fenced-code-choice.mdq.md": (
        "choice text is folded to single-line prose the same way preamble/"
        "stem text is, so a fenced code block nested in a choice loses its "
        "line breaks and stops being valid fenced-code Markdown; see "
        "BACKLOG.md"
    ),
    # "numeric.table-preamble.mdq.md": (
    #     "the parser uses plain CommonMark with no table extension, so a "
    #     "GFM pipe table is just an ordinary paragraph to it and its rows "
    #     "collapse into a single line of prose; see BACKLOG.md"
    # ),
}


console = Console(force_terminal=True)


def parse_file_from_text(source: str) -> dict:
    """Parse an inline document, for cases with no example pair."""
    return parse_any(source)


def load_document(path: Path):
    """The parsed sibling's own data, loaded straight off disk."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_source_files_found() -> None:
    assert VALID_SOURCES, "no .mdq.md fixtures found"


def test_parses_minimal_essay() -> None:
    source = next(p for p in VALID_SOURCES if p.name == "no-title.mdq.md")
    assert parse_file(source) == load_document(parsed_sibling(source))


def test_parses_minimal_multiple_choice() -> None:
    source = next(
        p
        for p in VALID_SOURCES
        if p.parent.name == "multiple-choice" and p.name == "simple.mdq.md"
    )
    assert parse_file(source) == load_document(parsed_sibling(source))


def test_parses_minimal_multiple_selection() -> None:
    source = next(
        p
        for p in VALID_SOURCES
        if p.parent.name == "multiple-selection" and p.name == "simple.mdq.md"
    )
    assert parse_file(source) == load_document(parsed_sibling(source))


def test_parses_minimal_true_false() -> None:
    source = next(
        p
        for p in VALID_SOURCES
        if p.parent.name == "true-false" and p.name == "simple.mdq.md"
    )
    assert parse_file(source) == load_document(parsed_sibling(source))


def test_parses_minimal_short_answer() -> None:
    source = next(
        p
        for p in VALID_SOURCES
        if p.parent.name == "short-answer" and p.name == "simple.mdq.md"
    )
    assert parse_file(source) == load_document(parsed_sibling(source))


def test_parses_minimal_numeric() -> None:
    source = next(
        p
        for p in VALID_SOURCES
        if p.parent.name == "numeric" and p.name == "integer.mdq.md"
    )
    assert parse_file(source) == load_document(parsed_sibling(source))


def test_parses_minimal_fill_in() -> None:
    source = next(
        p
        for p in VALID_SOURCES
        if p.parent.name == "fill-in" and p.name == "capital.mdq.md"
    )
    assert parse_file(source) == load_document(parsed_sibling(source))


@pytest.mark.parametrize(
    "source", VALID_SOURCES, ids=[relative_id(p) for p in VALID_SOURCES]
)
def test_parses_matches_fixture(source: Path) -> None:
    key = relative_id(source)
    if key in NOT_YET_SUPPORTED:
        pytest.xfail(NOT_YET_SUPPORTED[key])

    got = parse_file(source)
    parsed_path = parsed_sibling(source)
    expected = load_document(parsed_path)

    # More helpful output than pytest's default diff.
    if got != expected:
        console.print(Panel(Syntax(yaml.dump(got), "yaml"), title="Parsed"))
        console.print(Panel(Syntax(yaml.dump(expected), "yaml"), title="Expected"))

        print("md:", source)
        print("yaml:", parsed_path)

    assert got == expected


@pytest.mark.parametrize(
    "source", VALID_SOURCES, ids=[relative_id(p) for p in VALID_SOURCES]
)
def test_parsed_document_validates(source: Path) -> None:
    key = relative_id(source)
    if key in NOT_YET_SUPPORTED:
        pytest.xfail(NOT_YET_SUPPORTED[key])
    # An exam's `include:` entries need a loader to resolve before the
    # document can validate; harmless for a plain question source.
    document = parse_file(source, loader=FileLoader(source.parent))
    loaded = load(document)
    assert loaded, loaded.diagnostics


# ---------------------------------------------------------------------
# regressions: syntax the docs describe but no example pair exercises
# ---------------------------------------------------------------------


@pytest.mark.parametrize("question_type", ["multiple-choice", "multiple-selection"])
def test_choice_instructor_comment_round_trips(question_type: str) -> None:
    """multiple-choice.md documents `!` lines as instructor comments on a
    choice; the parsed document must carry them AND still validate."""
    marker = "*" if question_type == "multiple-choice" else "x"
    source = (
        f"---\ntype: {question_type}\n---\n\n"
        "Which one is the largest river in the world?\n\n"
        f"* [{marker}] Amazon\n"
        "  ! Students often say the Nile; mention the 2007 survey.\n"
        "* [ ] Nile\n"
    )
    document = parse_file_from_text(source)
    assert document["choices"][0]["comment"] == (
        "Students often say the Nile; mention the 2007 survey."
    )
    assert load(document)


def test_true_false_choice_instructor_comment_round_trips() -> None:
    """true-false.md says choices follow the multiple-choice structure, so
    `!` comments must work there too."""
    source = (
        "---\ntype: true-false\n---\n\n"
        "Judge the alternatives.\n\n"
        "* [T] The Amazon is the largest river by volume.\n"
        "  ! Worth contrasting with the Nile's length.\n"
        "* [F] The Earth is flat.\n"
    )
    document = parse_file_from_text(source)
    assert document["choices"][0]["comment"] == (
        "Worth contrasting with the Nile's length."
    )
    assert load(document)


def test_numeric_blank_infers_domain_like_a_numeric_question() -> None:
    """fill-in.md grades a numeric blank exactly like a numeric question,
    so the domain is inferred from the representation in both."""
    source = (
        "---\ntype: fill-in\n---\n\n"
        "It weighs [^mass] kg and costs [^price] reais.\n\n"
        "[^mass/numeric]: 70\n\n"
        "[^price/numeric]: 12.50\n"
    )
    blanks = {b["id"]: b for b in parse_file_from_text(source)["blanks"]}
    assert blanks["mass"]["domain"] == "integer"
    assert blanks["price"]["domain"] == "decimal"
    assert blanks["price"]["decimalPlaces"] == 2


@pytest.mark.parametrize("question_type", ["multiple-selection", "short-answer"])
def test_prose_list_in_preamble_has_no_trailing_blank_line(question_type: str) -> None:
    """
    markdown-it's `.map` for a list block that isn't the last block in the
    document extends one line past the list itself, into the blank line
    that follows it. `MDQParser.raw_text` must trim that trailing blank
    line back off, or a plain (non-choice) list used as preamble prose
    ends up with a spurious trailing newline baked into the field.
    """
    if question_type == "multiple-selection":
        body = "* [x] 4\n* [ ] 5\n"
    else:
        body = "[short-answer]: 4\n"
    source = "Consider the following:\n\n* first\n* second\n\nWhat is 2 + 2?\n\n" + body
    document = parse_file_from_text(source)
    assert document["preamble"] == "Consider the following:\n\n* first\n* second"


def test_exam_preamble_thematic_break_does_not_fence_a_later_question() -> None:
    """
    `_split_exam_blocks` looks for a `---` that fences a question's
    frontmatter without an explicit `===` separator (exam.md's own
    example chains two bare-frontmatter questions back to back). A
    thematic break inside an earlier question's own preamble/epilogue
    prose is also a lone, blank-line-preceded `---`, and must not be
    mistaken for the start of that fence just because some *later*
    question's real frontmatter closes with one too.
    """
    source = (
        "# Sample Exam\n\n"
        "===\n\n"
        "Some background text.\n\n"
        "---\n\n"
        "More background, after a thematic break.\n\n"
        "What is 2 + 2?\n\n"
        "[short-answer]: 4\n\n"
        "---\ntype: essay\n---\n\n"
        "Describe the water cycle.\n\n"
        "[essay]\n"
    )
    exam = parse_exam(source)
    assert [q["type"] for q in exam["questions"]] == ["short-answer", "essay"]
    assert exam["questions"][0]["preamble"] == (
        "Some background text.\n\n---\n\nMore background, after a thematic break."
    )
    assert load(exam)


def test_colon_bearing_preamble_line_is_not_mistaken_for_frontmatter() -> None:
    """
    A content-only guess at whether a `---` fences YAML is not safe:
    ordinary prose regularly contains a colon (labeled notes like "Nota:
    ..." or "Atenção: ..."), which parses as a one-key YAML mapping just
    as readily as a real frontmatter field does. `_split_exam_blocks`
    must reject a thematic break on *position* -- it sits before this
    question has shown any body tag yet -- not on what its text looks
    like.
    """
    source = (
        "# Sample Exam\n\n"
        "===\n\n"
        "Considere o processo abaixo.\n\n"
        "---\n\n"
        "Atenção: a resposta deve ser justificada.\n\n"
        "Explique a seleção natural.\n\n"
        "[essay]\n"
    )
    exam = parse_exam(source)
    assert len(exam["questions"]) == 1
    assert exam["questions"][0]["preamble"] == (
        "Considere o processo abaixo.\n\n---\n\nAtenção: a resposta deve ser justificada."
    )
    assert exam["questions"][0]["stem"] == "Explique a seleção natural."
    assert load(exam)


def test_exam_separator_immediately_followed_by_frontmatter_is_one_question() -> None:
    """
    A `---` right after a `===`, with nothing but a blank line between
    them, is that question's own frontmatter -- not a second, separate
    start layered on top of the `===` that already opened it. Getting
    this wrong produces a spurious empty question between the two.
    Regression for the exact shape reported against the first version of
    the positional fix above.
    """
    source = (
        "# Prova de Biologia\n\n"
        "Leia com atenção.\n\n"
        "===\n\n"
        "Considere o processo abaixo.\n\n"
        "---\n\n"
        "Atenção: a resposta deve ser justificada.\n\n"
        "Explique a seleção natural.\n\n"
        "[essay]\n\n"
        "===\n\n"
        "---\ntype: essay\nid: q2\n---\n\n"
        "Descreva a fotossíntese.\n\n"
        "[essay]\n"
    )
    exam = parse_exam(source)
    assert exam["instructions"] == "Leia com atenção."
    # The first block declares no `id`; the parser no longer derives one
    # (dev/specs/to-do/derived-ids.md) -- `with_ids()` would give it `q1`.
    assert [q.get("id") for q in exam["questions"]] == [None, "q2"]
    assert [q["type"] for q in exam["questions"]] == ["essay", "essay"]
    assert exam["questions"][0]["preamble"] == (
        "Considere o processo abaixo.\n\n---\n\nAtenção: a resposta deve ser justificada."
    )
    assert exam["questions"][1]["stem"] == "Descreva a fotossíntese."
    assert load(exam)

"""
docs/references/grammar.md: the grammar whitespace `ws` is only spaces and
tabs, `nl` is only `\\r\\n`, `\\r` and `\\n`, and a leading byte order mark
is removed. Every other Unicode space is text, and the
`non-ascii-whitespace` lint reports it.

The characters are built with `chr` so that this file holds no invisible
code point.
"""

from __future__ import annotations

import pytest

from mdq import load
from mdq._parser import is_exam, parse_exam, parse_question
from mdq._parser._frontmatter import _extract_comment
from mdq.errors import MdqError
from mdq.models._query import parse_query

NBSP = chr(0x00A0)
BOM = chr(0xFEFF)
NEL = chr(0x0085)
LS = chr(0x2028)
EM_SPACE = chr(0x2003)
NNBSP = chr(0x202F)

UNUSUAL = [NBSP, BOM, NEL, EM_SPACE]


def _choices(doc: dict) -> list[tuple[str, int]]:
    return [(c["text"], c["score"]) for c in doc["choices"]]


def _lint(source: str) -> list[tuple[str, int | None]]:
    """(severity, line) of every `non-ascii-whitespace` diagnostic."""
    return [
        (d.severity, d.line)
        for d in load(source, format="mdq").diagnostics
        if d.code == "non-ascii-whitespace"
    ]


# ---------------------------------------------------------------------
# ws: only spaces and tabs
# ---------------------------------------------------------------------
@pytest.mark.parametrize("ws", [" ", "\t", " \t  "])
def test_spaces_and_tabs_are_ws(ws: str) -> None:
    doc = parse_question(f"Qual a capital?\n\n[short-answer]:{ws}Brasília\n")
    assert doc["oneOf"] == ["Brasília"]  # type: ignore[typeddict-item]


@pytest.mark.parametrize("ch", UNUSUAL)
def test_unicode_space_after_short_answer_tag_is_text(ch: str) -> None:
    doc = parse_question(f"Qual a capital?\n\n[short-answer]:{ch}Brasília\n")
    assert doc["oneOf"] == [f"{ch}Brasília"]  # type: ignore[typeddict-item]


@pytest.mark.parametrize("ch", UNUSUAL)
def test_unicode_space_after_blank_definition_is_text(ch: str) -> None:
    doc = parse_question(
        f"A capital é [^cap].\n\n[^cap/short-answer]:{ch}Brasília\n"
    )
    blank = doc["blanks"][0]  # type: ignore[typeddict-item]
    assert blank["oneOf"] == [f"{ch}Brasília"]


@pytest.mark.parametrize("ch", [NBSP, BOM, EM_SPACE])
def test_unicode_space_before_tag_is_not_a_tag(ch: str) -> None:
    with pytest.raises(MdqError):
        parse_question(f"Qual a capital?\n\n{ch}[short-answer]: Brasília\n")


@pytest.mark.parametrize(
    "body",
    [
        "[numeric]:{ch}42",
        "[numeric]: 42{ch}+- 1",
        "[numeric]: 42 +-{ch}1",
    ],
)
@pytest.mark.parametrize("ch", UNUSUAL)
def test_unicode_space_breaks_numeric_answer(body: str, ch: str) -> None:
    with pytest.raises(MdqError):
        parse_question(f"Quanto mede o Rio Amazonas?\n\n{body.format(ch=ch)}\n")


@pytest.mark.parametrize("ch", [NBSP, NEL, EM_SPACE])
def test_unicode_space_is_not_part_of_a_unit(ch: str) -> None:
    with pytest.raises(MdqError):
        parse_question(f"Quanto mede o Rio Amazonas?\n\n[numeric(k{ch}m)]: 6400\n")


def test_bom_is_part_of_a_unit() -> None:
    doc = parse_question(f"Quanto mede o Rio Amazonas?\n\n[numeric(k{BOM}m)]: 6400\n")
    assert doc["unit"] == f"k{BOM}m"  # type: ignore[typeddict-item]


def test_tabs_are_ws_in_numeric_answer() -> None:
    doc = parse_question("Quanto mede?\n\n[numeric(km)]:\t6400\t+-\t5%\n")
    assert doc["answer"] == 6400  # type: ignore[typeddict-item]
    assert doc["tolerance"] == {"relative": 0.05}  # type: ignore[typeddict-item]


@pytest.mark.parametrize("ch", UNUSUAL)
def test_unicode_space_is_not_an_empty_checkbox(ch: str) -> None:
    # The parser reads an unknown value such as `[?]` as an unmarked
    # choice. A Unicode space is such an unknown value.
    body = "...\n\n* [{}] Ipê\n* [x] Jatobá\n* [X] Buriti\n"
    assert parse_question(body.format(ch)) == parse_question(body.format("?"))


@pytest.mark.parametrize("ch", [NBSP, BOM, EM_SPACE])
def test_unicode_space_after_choice_marker_is_choice_text(ch: str) -> None:
    doc = parse_question(f"...\n\n* [*]{ch}Ipê\n* [ ] Jatobá\n")
    assert _choices(dict(doc)) == [(f"{ch}Ipê", 1), ("Jatobá", 0)]


@pytest.mark.parametrize("ch", [NBSP, BOM, EM_SPACE])
def test_unicode_space_after_slug_is_stem_text(ch: str) -> None:
    doc = parse_question(f"[Q1]{ch}Qual é a maior árvore da Amazônia?\n\n[essay]\n")
    assert doc["id"] == "Q1"  # type: ignore[typeddict-item]
    assert doc["stem"] == f"{ch}Qual é a maior árvore da Amazônia?"  # type: ignore[typeddict-item]


@pytest.mark.parametrize("ch", [NBSP, EM_SPACE])
def test_unicode_space_starts_a_pattern_line(ch: str) -> None:
    doc = parse_question(
        "Qual a capital?\n\n[short-answer/accept]:\n"
        f"* {ch}/bras[íi]lia/i\n"
    )
    assert doc["accept"] == [f"{ch}/bras[íi]lia/i"]  # type: ignore[typeddict-item]
    loaded = load(
        f"Qual a capital?\n\n[short-answer/accept]:\n* {ch}/bras[íi]lia/i\n",
        format="mdq",
    )
    assert loaded.document is not None
    assert not loaded.document.accept[0].matches("Brasília")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------
# nl: only \r\n, \r and \n
# ---------------------------------------------------------------------
@pytest.mark.parametrize("ch", [NEL, LS, chr(0x2029), "\x0b", "\x0c", "\x1c"])
def test_other_line_separators_are_text(ch: str) -> None:
    doc = parse_question(f"...\n\n* [*] Ipê{ch}amarelo\n* [ ] Jatobá\n")
    assert _choices(dict(doc)) == [(f"Ipê{ch}amarelo", 1), ("Jatobá", 0)]


@pytest.mark.parametrize("eol", ["\n", "\r\n", "\r"])
def test_commonmark_line_endings(eol: str) -> None:
    source = eol.join(
        ["---", "# Ipê", "id: ipe", "---", "", "...", "", "* [*] Ipê", "* [ ] Jatobá", ""]
    )
    doc = parse_question(source)
    assert doc["id"] == "ipe"  # type: ignore[typeddict-item]
    assert doc["comment"] == "Ipê"  # type: ignore[typeddict-item]
    assert _choices(dict(doc)) == [("Ipê", 1), ("Jatobá", 0)]


def test_line_separator_does_not_start_an_exam_title() -> None:
    assert not is_exam(f"Qual a capital?{NEL}# Título\n\n[essay]\n")


# ---------------------------------------------------------------------
# Byte order mark
# ---------------------------------------------------------------------
def test_leading_bom_is_removed_before_frontmatter() -> None:
    doc = parse_question(f"{BOM}---\nid: ipe\n---\n\nDescreva o ipê.\n\n[essay]\n")
    assert doc["id"] == "ipe"  # type: ignore[typeddict-item]
    assert doc["stem"] == "Descreva o ipê."  # type: ignore[typeddict-item]


def test_leading_bom_is_removed_before_exam_title() -> None:
    source = f"{BOM}# Prova\n\nDescreva o ipê.\n\n[essay]\n"
    assert is_exam(source)
    assert parse_exam(source)["title"] == "Prova"


def test_leading_bom_is_not_reported() -> None:
    assert _lint(f"{BOM}Descreva o ipê.\n\n[essay]\n") == []


# ---------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------
def test_frontmatter_blank_lines_before_comment() -> None:
    doc = parse_question("---\n\n  \n# Ipê\nid: ipe\n---\n\nDescreva.\n\n[essay]\n")
    assert doc["comment"] == "Ipê"  # type: ignore[typeddict-item]


def test_unicode_space_line_is_not_blank_in_frontmatter() -> None:
    assert _extract_comment(f"\n \t\n# Ipê\nid: ipe\n") == "Ipê"
    assert _extract_comment(f"{NBSP}\n# Ipê\nid: ipe\n") is None


# ---------------------------------------------------------------------
# Exam query
# ---------------------------------------------------------------------
@pytest.mark.parametrize("ch", [NBSP, EM_SPACE, NEL])
def test_unicode_space_is_not_a_query_separator(ch: str) -> None:
    with pytest.raises(ValueError):
        parse_query(f"biomas{ch}AND cerrado")


def test_bom_is_part_of_a_query_tag() -> None:
    assert parse_query(f"biomas{BOM}") == parse_query(f"biomas{BOM}")
    assert parse_query(f"biomas{BOM}") != parse_query("biomas")


# ---------------------------------------------------------------------
# non-ascii-whitespace lint
# ---------------------------------------------------------------------
def test_ascii_document_has_no_report() -> None:
    assert _lint("Qual a capital?\n\n[short-answer]:\tBrasília\n") == []


@pytest.mark.parametrize("ch", [NBSP, NNBSP, EM_SPACE, BOM])
def test_unicode_space_inside_prose_is_info(ch: str) -> None:
    source = f"O Amazonas tem 6{ch}400 km.\n\nQuanto mede?\n\n[numeric(km)]: 6400\n"
    assert _lint(source) == [("info", 1)]


@pytest.mark.parametrize("ch", [NEL, LS, chr(0x2029)])
def test_line_separator_is_warning_anywhere(ch: str) -> None:
    source = f"O Amazonas{ch}é longo.\n\nQuanto mede?\n\n[numeric(km)]: 6400\n"
    assert _lint(source) == [("warning", 1)]


@pytest.mark.parametrize(
    "source, line",
    [
        # Start and end of a line.
        (f"{NBSP}Descreva o ipê.\n\n[essay]\n", 1),
        (f"Descreva o ipê.{NBSP}\n\n[essay]\n", 1),
        (f"Descreva o ipê. \t{NBSP} \n\n[essay]\n", 1),
        # After list, heading, blockquote and `!` markers.
        (f"Veja:\n\n>{NBSP}citação\n\nDescreva.\n\n[essay]\n", 3),
        (f"...\n\n*{NBSP}[*] Ipê\n* [ ] Jatobá\n", 3),
        # A tag line, answer included.
        (f"Qual a capital?\n\n[short-answer]:{NBSP}Brasília\n", 3),
        (f"Qual a capital?\n\n[short-answer]: Bras{NBSP}ília\n", 3),
        (f"Quanto?\n\n[numeric]: 42{NBSP}+- 1\n", 3),
        (f"A capital é [^c].\n\n[^c/short-answer]: Bras{NBSP}ília\n", 3),
        # A choice prefix.
        (f"...\n\n* [{NBSP}] Ipê\n* [*] Jatobá\n", 3),
        (f"...\n\n* [*] [ipe]{NBSP}Ipê\n* [ ] Jatobá\n", 3),
        # A pattern line.
        (f"Qual a capital?\n\n[short-answer/accept]:\n* Bras{NBSP}ília\n", 4),
    ],
)
def test_unicode_space_in_syntax_position_is_warning(source: str, line: int) -> None:
    assert ("warning", line) in _lint(source)


def test_unicode_space_inside_choice_text_is_info() -> None:
    source = f"...\n\n* [*] Ipê{NBSP}amarelo\n* [ ] Jatobá\n"
    assert _lint(source) == [("info", 3)]


def test_unicode_space_inside_choice_feedback_is_info() -> None:
    source = f"...\n\n* [*] Ipê\n  > Árvore{NBSP}símbolo.\n* [ ] Jatobá\n"
    assert _lint(source) == [("info", 4)]


@pytest.mark.parametrize(
    "source",
    [
        f"Leia:\n\n```python\nx ={NBSP}1\n```\n\nDescreva.\n\n[essay]\n",
        f"Leia:\n\n    x ={NBSP}1\n\nDescreva.\n\n[essay]\n",
        f"Leia `x ={NBSP}1` e descreva.\n\n[essay]\n",
        f"Leia ``x ={LS}1`` e descreva.\n\n[essay]\n",
        f"---\ntitle: Ipê{NBSP}amarelo\n---\n\nDescreva.\n\n[essay]\n",
    ],
)
def test_code_and_frontmatter_are_not_reported(source: str) -> None:
    assert _lint(source) == []


def test_report_line_counts_the_frontmatter() -> None:
    source = f"---\nid: ipe\n---\n\nDescreva o ipê{NBSP}amarelo.\n\n[essay]\n"
    assert _lint(source) == [("info", 5)]


def test_report_is_kept_when_parsing_fails() -> None:
    loaded = load(f"Qual a capital?\n\n{NBSP}[short-answer]: Brasília\n", format="mdq")
    assert loaded.document is None
    codes = [(d.severity, d.code) for d in loaded.diagnostics]
    assert ("warning", "non-ascii-whitespace") in codes
    assert any(severity == "error" for severity, _ in codes)


def test_exam_is_checked() -> None:
    source = f"# Prova\n\nDescreva o ipê{NBSP}amarelo.\n\n[essay]\n"
    assert _lint(source) == [("info", 3)]


def test_one_report_per_character() -> None:
    source = f"Descreva o ipê{NBSP}amarelo e o{NBSP}jatobá.\n\n[essay]\n"
    assert _lint(source) == [("info", 1), ("info", 1)]


def test_question_frontmatter_in_exam_is_not_reported() -> None:
    source = (
        "# Prova\n\n===\n\n---\n"
        f"title: Ipê{NBSP}amarelo\n"
        "---\n\nDescreva o ipê.\n\n[essay]\n"
    )
    assert load(source, format="mdq").document is not None
    assert _lint(source) == []


def test_blank_pattern_line_is_warning() -> None:
    source = (
        "A capital é [^cap].\n\n[^cap/short-answer/accept]:\n"
        f"* Bras{NBSP}ília\n"
    )
    assert _lint(source) == [("warning", 4)]


@pytest.mark.parametrize(
    "tag", ["[ short-answer ]:", "[short-answer /accept]:", "[short-answer/ accept]:"]
)
def test_no_whitespace_inside_tag_brackets(tag: str) -> None:
    with pytest.raises(MdqError):
        parse_question(f"Qual a capital?\n\n{tag} Brasília\n")

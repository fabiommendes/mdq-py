"""
Blank definitions of a fill-in question: the minimum blocks of a short answer
blank and the contiguous run of definitions (docs/question-types/fill-in.md
"Short answer blanks" and "Blank definitions").
"""

from __future__ import annotations

import mdq


def _load(source: str) -> mdq.Loaded:
    return mdq.load(source, kind="question")


def _codes(loaded: mdq.Loaded) -> list[tuple[str, str, tuple[str | int, ...]]]:
    return [(d.code, d.severity, d.path) for d in loaded.diagnostics]


def test_a_blank_with_only_a_reject_block_is_valid() -> None:
    loaded = _load(
        "O maior rio do Brasil é o [^rio].\n\n"
        "[^rio/short-answer/reject]: Tietê\n"
    )
    assert loaded.document is not None
    blank = loaded.document.blanks[0]
    assert blank.type == "short-answer"
    assert not blank.accept
    assert [p.pattern for p in blank.reject] == ["Tietê"]


def test_a_short_answer_question_with_only_a_reject_block_is_valid() -> None:
    loaded = _load("Cite um bioma do Brasil.\n\n[short-answer/reject]: Tundra\n")
    assert loaded.document is not None


def test_a_short_answer_question_without_a_block_is_a_parse_error() -> None:
    loaded = _load("---\ntype: short-answer\n---\nCite um bioma do Brasil.\n")
    assert loaded.document is None
    assert [d.code for d in loaded.diagnostics] == ["parse-error"]


def test_a_definition_after_a_paragraph_is_detached() -> None:
    loaded = _load(
        "A capital é [^capital] e a do Acre é [^acre].\n\n"
        "[^capital/short-answer]: Brasília\n\n"
        "Rio Branco fica às margens do rio Acre.\n\n"
        "[^acre/short-answer]: Rio Branco\n"
    )
    assert loaded.document is None
    assert _codes(loaded) == [("detached-tag", "error", ("epilogue",))]
    assert "[^acre/short-answer]" in loaded.diagnostics[0].message


def test_a_detached_choice_and_numeric_definition_are_reported() -> None:
    loaded = _load(
        "O Brasil tem [^estados] estados e a capital é [^capital].\n\n"
        "[^estados/numeric]: 26\n\n"
        "Mais o Distrito Federal.\n\n"
        "[^capital]:\n"
        "* [x] Brasília\n"
        "* [ ] Lisboa\n"
    )
    assert loaded.document is None
    assert _codes(loaded) == [("detached-tag", "error", ("epilogue",))]


def test_definitions_separated_by_blank_lines_are_not_detached() -> None:
    loaded = _load(
        "A capital é [^capital] e a do Acre é [^acre].\n\n"
        "[^capital/short-answer]: Brasília\n\n\n"
        "[^acre/short-answer]: Rio Branco\n\n"
        "Rio Branco fica às margens do rio Acre.\n"
    )
    assert loaded.document is not None


def test_a_tag_in_fenced_code_of_the_epilogue_is_not_detached() -> None:
    loaded = _load(
        "A capital é [^capital].\n\n"
        "[^capital/short-answer]: Brasília\n\n"
        "```md\n[^acre/short-answer]: Rio Branco\n```\n"
    )
    assert loaded.document is not None

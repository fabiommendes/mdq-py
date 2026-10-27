"""
Tests for `dev/specs/to-do/derived-ids.md`.

Derived ids move from the parser to the models:

- `with_ids()` (on every question model and on `Exam`) returns a new,
  *addressable* copy (GLOSSARY.md "Addressable"): every question and every
  choice has an id. It never mutates `self`, never touches an explicit id,
  and never derives two equal ids.
- `load`/`parse` grow an `ids: Literal["fill", "keep"] = "keep"` keyword.
  `"keep"` is the document as written; `"fill"` is `document.with_ids()`.
  Lint always runs on the document as written, regardless of `ids`.

Written against the public `mdq.load`/`mdq.parse` API and the public model
classes only -- no parser/linter internals. The ids themselves (slug
collisions, named glyphs, positions) are in `examples/valid/**/*.ids.yaml`
(`test_ids_corpus.py`); this file keeps the API: purity, idempotence and the
`ids` keyword.
"""

from __future__ import annotations

from mdq import load, parse


def _ids(choices) -> list[str | None]:
    return [c.id for c in choices]


# ---------------------------------------------------------------------
# with_ids(): purity and idempotence
# ---------------------------------------------------------------------


def test_with_ids_does_not_mutate_the_original_question() -> None:
    text = "Qual é a capital do Brasil?\n\n* [ ] Rio de Janeiro\n* [*] Brasília\n"
    doc = parse(text, kind="question")
    before = _ids(doc.choices)

    filled = doc.with_ids()

    assert filled is not doc
    assert _ids(doc.choices) == before == [None, None]
    assert None not in _ids(filled.choices)


def test_with_ids_does_not_mutate_the_original_exam() -> None:
    text = (
        "# Prova de Geografia do Brasil\n"
        "\n"
        "===\n"
        "\n"
        "Qual é a capital do Brasil?\n"
        "\n"
        "[essay]\n"
    )
    doc = parse(text, kind="exam")

    filled = doc.with_ids()

    assert filled is not doc
    assert doc.questions[0].id is None


def test_with_ids_is_idempotent_for_a_question() -> None:
    text = (
        "Qual é a capital do Brasil?\n"
        "\n"
        "* [ ] Rio de Janeiro\n"
        "* [*] Brasília\n"
        "* [ ] São Paulo\n"
    )
    doc = parse(text, kind="question")
    once = doc.with_ids()
    twice = once.with_ids()
    assert twice == once


def test_with_ids_is_idempotent_for_an_exam() -> None:
    text = (
        "# Prova de Geografia do Brasil\n"
        "\n"
        "===\n"
        "\n"
        "Qual é a capital do Brasil?\n"
        "\n"
        "[essay]\n"
        "\n"
        "===\n"
        "\n"
        "Onde fica a Floresta Amazônica?\n"
        "\n"
        "* [ ] Ásia\n"
        "* [*] América do Sul\n"
    )
    doc = parse(text, kind="exam")
    once = doc.with_ids()
    twice = once.with_ids()
    assert twice == once


# ---------------------------------------------------------------------
# `load`/`parse`: `ids="fill" | "keep"`
# ---------------------------------------------------------------------


def test_load_keep_is_the_default_and_returns_ids_as_written() -> None:
    text = "Qual é a capital do Brasil?\n\n* [ ] Rio de Janeiro\n* [*] Brasília\n"
    default = load(text)
    explicit_keep = load(text, ids="keep")

    assert default.document == explicit_keep.document
    assert _ids(default.document.choices) == [None, None]


def test_load_fill_returns_an_addressable_document() -> None:
    text = "Qual é a capital do Brasil?\n\n* [ ] Rio de Janeiro\n* [*] Brasília\n"
    loaded = load(text, ids="fill")
    assert loaded.document is not None
    assert None not in _ids(loaded.document.choices)


def test_load_fill_matches_calling_with_ids_directly() -> None:
    text = (
        "Qual é a capital do Brasil?\n"
        "\n"
        "* [ ] Rio de Janeiro\n"
        "* [*] Brasília\n"
        "* [ ] São Paulo\n"
    )
    filled_by_load = load(text, ids="fill").document
    filled_by_hand = load(text, ids="keep").document.with_ids()
    assert filled_by_load == filled_by_hand


def test_parse_accepts_the_ids_keyword_too() -> None:
    text = "Qual é a capital do Brasil?\n\n* [ ] Rio de Janeiro\n* [*] Brasília\n"
    kept = parse(text, kind="question", ids="keep")
    filled = parse(text, kind="question", ids="fill")

    assert _ids(kept.choices) == [None, None]
    assert None not in _ids(filled.choices)


def test_lint_runs_on_the_document_as_written_in_both_modes() -> None:
    """
    Lint always inspects the document as the author wrote it -- `ids`
    only changes what `Loaded.document` looks like, never what gets
    linted, so the two modes report the exact same diagnostics.
    """
    text = (
        "Qual é a capital do Brasil?\n"
        "\n"
        "* [ ] Rio de Janeiro\n"
        "* [*] Brasília\n"
        "* [ ] São Paulo\n"
    )
    kept = load(text, ids="keep")
    filled = load(text, ids="fill")

    assert kept.diagnostics == filled.diagnostics
    # And the two documents are not the same, or this assertion would be
    # vacuous: `ids` really does change something.
    assert kept.document != filled.document

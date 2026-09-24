"""
Tests for `dev/specs/to-do/derived-ids.md`.

Derived ids move from the parser to the models:

- The parser only ever keeps an id the author wrote. A choice or question
  with no explicit id has `id is None` right after `load`/`parse`.
- `with_ids()` (on every question model and on `Exam`) returns a new,
  *addressable* copy (GLOSSARY.md "Addressable"): every question and every
  choice has an id. It never mutates `self`, never touches an explicit id,
  and never derives two equal ids.
- `load`/`parse` grow an `ids: Literal["fill", "keep"] = "keep"` keyword.
  `"keep"` is the document as written; `"fill"` is `document.with_ids()`.
  Lint always runs on the document as written, regardless of `ids`.

Written against the public `mdq.load`/`mdq.parse` API and the public model
classes only -- no parser/linter internals. Fixtures use Brazil-themed
questions and exams, per AGENTS.md.
"""

from __future__ import annotations

from mdq import load, parse
from mdq.loaders import DictLoader
from mdq.models import (
    BooleanChoice,
    ChoiceBlank,
    Exam,
    FillInQuestion,
    MultipleChoiceQuestion,
    MultipleSelectionQuestion,
    ScoredChoice,
)


def _ids(choices) -> list[str | None]:
    return [c.id for c in choices]


# ---------------------------------------------------------------------
# The parser keeps only explicit ids
# ---------------------------------------------------------------------


def test_choice_without_explicit_id_is_none_after_load() -> None:
    text = (
        "Qual é a capital do Brasil?\n"
        "\n"
        "* [ ] Rio de Janeiro\n"
        "* [*] Brasília\n"
        "* [ ] São Paulo\n"
    )
    doc = parse(text, kind="question")
    assert isinstance(doc, MultipleChoiceQuestion)
    assert _ids(doc.choices) == [None, None, None]


def test_choice_with_explicit_id_keeps_it() -> None:
    text = (
        "Qual é a capital do Brasil?\n"
        "\n"
        "* [ ] Rio de Janeiro\n"
        "* [*] [df] Brasília\n"
        "* [ ] São Paulo\n"
    )
    doc = parse(text, kind="question")
    assert isinstance(doc, MultipleChoiceQuestion)
    by_text = {c.text: c.id for c in doc.choices}
    assert by_text["Brasília"] == "df"
    assert by_text["Rio de Janeiro"] is None
    assert by_text["São Paulo"] is None


def test_fill_in_choice_blank_choice_without_id_is_none_after_load() -> None:
    text = (
        "A capital do Brasil é [^capital].\n"
        "\n"
        "[^capital]:\n"
        "* [ ] Rio de Janeiro\n"
        "* [*] Brasília\n"
    )
    doc = parse(text, kind="question")
    assert isinstance(doc, FillInQuestion)
    blank = doc.blanks[0]
    assert isinstance(blank, ChoiceBlank)
    assert _ids(blank.choices) == [None, None]


def test_exam_inline_question_without_id_is_none_after_load() -> None:
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
    assert isinstance(doc, Exam)
    assert doc.questions[0].id is None


def test_exam_inline_question_with_explicit_id_keeps_it() -> None:
    text = (
        "# Prova de Geografia do Brasil\n"
        "\n"
        "---\n"
        "id: capital\n"
        "---\n"
        "\n"
        "Qual é a capital do Brasil?\n"
        "\n"
        "[essay]\n"
    )
    doc = parse(text, kind="exam")
    assert doc.questions[0].id == "capital"


# ---------------------------------------------------------------------
# with_ids(): disambiguation
# ---------------------------------------------------------------------


def test_with_ids_disambiguates_brasilia_and_its_ascii_spelling() -> None:
    """
    `Brasília` and `Brasilia` both fold to the same ASCII slug; `with_ids`
    must not collide the two.
    """
    text = (
        "Qual grafia consta no censo demográfico?\n"
        "\n"
        "* [ ] Brasília\n"
        "* [*] Brasilia\n"
        "* [ ] Nenhuma das anteriores\n"
    )
    doc = parse(text, kind="question")
    filled = doc.with_ids()
    ids = _ids(filled.choices)
    assert None not in ids
    assert len(ids) == len(set(ids)), f"derived ids collided: {ids}"


def test_with_ids_disambiguates_punctuation_only_variants() -> None:
    """
    `São Paulo!` and `São Paulo?` both slugify to `sao-paulo` once
    punctuation is stripped; `with_ids` must not collide the two.
    """
    text = (
        "Qual pontuação está correta?\n"
        "\n"
        "* [ ] São Paulo!\n"
        "* [*] São Paulo?\n"
        "* [ ] Rio de Janeiro\n"
    )
    doc = parse(text, kind="question")
    filled = doc.with_ids()
    ids = _ids(filled.choices)
    assert None not in ids
    assert len(ids) == len(set(ids)), f"derived ids collided: {ids}"


def test_with_ids_derived_id_never_takes_an_explicit_id_of_the_same_question() -> None:
    """
    Choice 2 declares the explicit id `brasilia`; choice 1 has no explicit
    id but its text (`Brasília`) would naturally derive to `brasilia` too.
    The derived id must avoid the explicit one.
    """
    text = (
        "Qual é a capital do Brasil?\n"
        "\n"
        "* [ ] Brasília\n"
        "* [*] [brasilia] Distrito Federal, sede do governo\n"
        "* [ ] São Paulo\n"
    )
    doc = parse(text, kind="question")
    filled = doc.with_ids()
    derived_id, explicit_id, _ = _ids(filled.choices)
    assert explicit_id == "brasilia"
    assert derived_id != "brasilia"
    assert derived_id is not None


def test_with_ids_choice_ids_do_not_depend_on_order() -> None:
    """
    Reordering the choices gives each text the same derived id.
    """

    def build(order: list[str]) -> MultipleChoiceQuestion:
        return MultipleChoiceQuestion(
            stem="Qual é a capital do Brasil?",
            choices=[ScoredChoice(text=text) for text in order],
        )

    forward = build(["Rio de Janeiro", "Brasília", "São Paulo"]).with_ids()
    backward = build(["São Paulo", "Brasília", "Rio de Janeiro"]).with_ids()

    assert {c.text: c.id for c in forward.choices} == {
        c.text: c.id for c in backward.choices
    }


def test_with_ids_single_glyph_choices_get_named_ids() -> None:
    """
    A single-glyph choice text has nothing sluggable once punctuation is
    stripped, so `with_ids` names it from a fixed table instead
    (`docs/question-types/multiple-choice.md`; see also
    `examples/valid/multiple-selection/all-correct.yaml`).
    """
    doc = MultipleSelectionQuestion(
        stem="Quais destes são marcadores válidos de lista em Markdown?",
        choices=[
            BooleanChoice(text="-", correct=True),
            BooleanChoice(text="*", correct=True),
            BooleanChoice(text="+", correct=True),
        ],
    )
    filled = doc.with_ids()
    assert {c.text: c.id for c in filled.choices} == {
        "-": "hyphen",
        "*": "asterisk",
        "+": "plus",
    }


def test_with_ids_single_digit_choices_get_named_ids() -> None:
    doc = MultipleSelectionQuestion(
        stem="Quais destes números são primos?",
        choices=[
            BooleanChoice(text="1"),
            BooleanChoice(text="4"),
            BooleanChoice(text="9"),
        ],
    )
    filled = doc.with_ids()
    assert {c.text: c.id for c in filled.choices} == {
        "1": "one",
        "4": "four",
        "9": "nine",
    }


def test_with_ids_fills_fill_in_choice_blank_choice_ids() -> None:
    blank = ChoiceBlank(
        id="capital",
        choices=[
            ScoredChoice(text="Brasília", score=1),
            ScoredChoice(text="Rio de Janeiro", score=0),
        ],
    )
    doc = FillInQuestion(
        stem="A capital do Brasil é [^capital].",
        blanks=[blank],
    )
    filled = doc.with_ids()
    ids = _ids(filled.blanks[0].choices)
    assert None not in ids
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------
# with_ids(): exam position counting
# ---------------------------------------------------------------------

_AMAZONIA = {
    "id": "amazonia",
    "type": "essay",
    "stem": "Onde fica a Floresta Amazônica?",
}


def test_with_ids_exam_position_counts_includes() -> None:
    """
    docs/exam.md, "Question ids": position counts every block, including
    an `include`, so the second block's implicit id is `q2`, not `q1`.
    """
    text = (
        "# Prova de Geografia do Brasil\n"
        "\n"
        "---\n"
        "include: amazonia\n"
        "---\n"
        "\n"
        "---\n"
        "---\n"
        "\n"
        "Qual é a capital do Brasil?\n"
        "\n"
        "[essay]\n"
    )
    loader = DictLoader({"amazonia": _AMAZONIA})

    kept = parse(text, kind="exam", loader=loader, ids="keep")
    assert kept.questions[0].id == "amazonia"
    assert kept.questions[1].id is None

    filled = kept.with_ids()
    assert filled.questions[0].id == "amazonia"
    assert filled.questions[1].id == "q2"


def test_with_ids_exam_assigns_positional_ids_to_every_bare_question() -> None:
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
    assert [q.id for q in doc.questions] == [None, None]

    filled = doc.with_ids()
    assert [q.id for q in filled.questions] == ["q1", "q2"]


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
    assert filled.questions[0].id == "q1"


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
# with_ids(): markdown and YAML agree
# ---------------------------------------------------------------------


def test_with_ids_gives_the_same_result_for_markdown_and_yaml() -> None:
    md = (
        "Qual é a capital do Brasil?\n"
        "\n"
        "* [ ] Rio de Janeiro\n"
        "* [*] Brasília\n"
        "* [ ] São Paulo\n"
    )
    yaml_text = (
        "type: multiple-choice\n"
        "stem: Qual é a capital do Brasil?\n"
        "choices:\n"
        "  - text: Rio de Janeiro\n"
        "    score: 0\n"
        "  - text: Brasília\n"
        "    score: 1\n"
        "  - text: São Paulo\n"
        "    score: 0\n"
    )
    from_md = parse(md, kind="question", format="mdq")
    from_yaml = parse(yaml_text, kind="question", format="yaml")

    assert from_md.with_ids() == from_yaml.with_ids()


def test_with_ids_gives_the_same_result_for_markdown_and_yaml_exams() -> None:
    md = (
        "# Prova de Geografia do Brasil\n"
        "\n"
        "===\n"
        "\n"
        "Qual é a capital do Brasil?\n"
        "\n"
        "[essay]\n"
    )
    yaml_text = (
        "type: exam\n"
        "title: Prova de Geografia do Brasil\n"
        "questions:\n"
        "  - type: essay\n"
        "    stem: Qual é a capital do Brasil?\n"
    )
    from_md = parse(md, kind="exam", format="mdq")
    from_yaml = parse(yaml_text, kind="exam", format="yaml")

    assert from_md.with_ids() == from_yaml.with_ids()


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


def test_load_fill_on_an_exam_assigns_positional_ids() -> None:
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
    loaded = load(text, kind="exam", ids="fill")
    assert loaded.document is not None
    assert [q.id for q in loaded.document.questions] == ["q1", "q2"]


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


# ---------------------------------------------------------------------
# Exam validator: a declared id colliding with the next implicit id
# ---------------------------------------------------------------------


def test_declared_id_colliding_with_next_implicit_id_is_an_error_from_markdown() -> (
    None
):
    """
    Block 1 declares `id: q2`; block 2 has no id, so its implicit,
    position-based id is also `q2` -- computed without being filled in,
    per docs/exam.md "Question ids".
    """
    text = (
        "# Prova de Geografia do Brasil\n"
        "\n"
        "---\n"
        "id: q2\n"
        "---\n"
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
    loaded = load(text, kind="exam")
    assert loaded.document is None
    diagnostics = [d for d in loaded.diagnostics if d.code == "duplicate-question-id"]
    assert len(diagnostics) == 1
    assert diagnostics[0].severity == "error"
    assert diagnostics[0].path[-2:] == ("questions", 1)


def test_declared_id_colliding_with_next_implicit_id_is_an_error_from_yaml() -> None:
    yaml_text = (
        "type: exam\n"
        "title: Prova de Geografia do Brasil\n"
        "questions:\n"
        "  - type: essay\n"
        "    id: q2\n"
        "    stem: Qual é a capital do Brasil?\n"
        "  - type: multiple-selection\n"
        "    stem: Onde fica a Floresta Amazônica?\n"
        "    choices:\n"
        "      - text: Ásia\n"
        "      - text: América do Sul\n"
        "        correct: true\n"
    )
    loaded = load(yaml_text, kind="exam", format="yaml")
    assert loaded.document is None
    diagnostics = [d for d in loaded.diagnostics if d.code == "duplicate-question-id"]
    assert len(diagnostics) == 1
    assert diagnostics[0].severity == "error"
    assert diagnostics[0].path[-2:] == ("questions", 1)


def test_declared_id_colliding_with_next_implicit_id_is_an_error_from_a_mapping() -> (
    None
):
    data = {
        "type": "exam",
        "title": "Prova de Geografia do Brasil",
        "questions": [
            {
                "type": "essay",
                "id": "q2",
                "stem": "Qual é a capital do Brasil?",
            },
            {
                "type": "multiple-selection",
                "stem": "Onde fica a Floresta Amazônica?",
                "choices": [
                    {"text": "Ásia"},
                    {"text": "América do Sul", "correct": True},
                ],
            },
        ],
    }
    loaded = load(data, kind="exam")
    assert loaded.document is None
    diagnostics = [d for d in loaded.diagnostics if d.code == "duplicate-question-id"]
    assert len(diagnostics) == 1
    assert diagnostics[0].severity == "error"
    assert diagnostics[0].path[-2:] == ("questions", 1)


def test_declared_id_not_colliding_with_any_implicit_id_does_not_error() -> None:
    """
    Sanity check: `id: capital` on block 1 never collides with block 2's
    implicit `q2`, so the exam loads clean.
    """
    text = (
        "# Prova de Geografia do Brasil\n"
        "\n"
        "---\n"
        "id: capital\n"
        "---\n"
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
    loaded = load(text, kind="exam")
    assert loaded.document is not None
    assert "duplicate-question-id" not in {d.code for d in loaded.diagnostics}

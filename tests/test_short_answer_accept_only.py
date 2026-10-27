"""
Short answer: `accept` is the only answer list (see
`dev/specs/to-do/short-answer-accept-only.md`).

`oneOf` and `regex` no longer exist in short-answer questions. The Markdown
parser always emits `accept`, and the pattern keeps its delimiters.

The parser, model, lint and grading cases of the spec live in the corpus
(`examples/valid/short-answer/`, `examples/invalid/short-answer-*`,
`examples/grading/`). This module keeps what the corpus cannot express: the
JSON source, `render()`, the converters and the CLI. `test_b4_*` cover AC10-AC12.
"""

from __future__ import annotations

import pytest

from pathlib import Path

from typer.testing import CliRunner

from mdq import Diagnostic, load
from mdq.cli import app
from mdq.convert._gift import Gift, GiftBlock, GiftQuestion, GiftShort, GiftOption
from mdq.convert._moodle_xml import (
    MoodleAnswer,
    MoodleXml,
    ShortAnswerBlock,
    MoodleXmlQuestion,
)
from mdq.models import (
    AnswerPattern,
    FillInQuestion,
    ShortAnswerBlank,
    ShortAnswerQuestion,
)

runner = CliRunner()

STEM = "Qual é a capital do Brasil?"


def _md(body: str, frontmatter: str = "") -> str:
    head = f"---\n{frontmatter}---\n\n" if frontmatter else ""
    return f"{head}{STEM}\n\n{body}"


def _codes(diagnostics: list[Diagnostic]) -> list[str]:
    return [d.code for d in diagnostics]


def _errors(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    return [d for d in diagnostics if d.severity == "error"]


#
# AC3: `oneOf` and `regex` are rejected
#


def test_b1_json_source_with_one_of_is_a_schema_error() -> None:
    source = '{"type": "short-answer", "stem": "Qual é a capital do Brasil?", "oneOf": ["Brasília"]}'
    loaded = load(source, format="json")
    assert loaded.document is None
    assert "schema-error" in _codes(_errors(loaded.diagnostics))


#
# Fill-in helpers
#
_FILL_STEM = "A capital do Brasil é [^cap]."


def _fill_md(definitions: str) -> str:
    return f"{_FILL_STEM}\n\n{definitions}"


def _fill(source: str) -> FillInQuestion:
    loaded = load(source, format="mdq")
    assert isinstance(loaded.document, FillInQuestion), [
        d.code for d in loaded.diagnostics
    ]
    return loaded.document


_BLANK_ACCEPT = "[^cap/short-answer/accept]:\n* Distrito Federal\n* Plano Piloto\n  > Também vale.\n"


#
# AC10: render
#
def _reload_dict(source: str) -> dict:
    loaded = load(source, format="mdq")
    assert loaded.document is not None, [d.code for d in loaded.diagnostics]
    return loaded.document.to_dict()


def test_b4_render_single_plain_accept_as_simple_block() -> None:
    question = ShortAnswerQuestion(stem="Qual a capital?", accept=["Brasília"])
    assert question.render() == "Qual a capital?\n\n[short-answer]: Brasília"


def test_b4_render_single_exact_and_regex_accept_as_simple_block() -> None:
    exact = ShortAnswerQuestion(stem="Qual função?", accept=["`math.isnan`"])
    regex = ShortAnswerQuestion(stem="Quando?", accept=["/1822-0?9-0?7/i"])
    assert exact.render().endswith("[short-answer]: `math.isnan`")
    assert regex.render().endswith("[short-answer]: /1822-0?9-0?7/i")


@pytest.mark.parametrize(
    "question",
    [
        ShortAnswerQuestion(
            stem="Qual a capital?",
            accept=[AnswerPattern(pattern="Brasília", feedback="Certo!")],
        ),
        ShortAnswerQuestion(
            stem="Qual a capital?",
            accept=[AnswerPattern(pattern="Brasília", comment="Oficial")],
        ),
        ShortAnswerQuestion(stem="Qual a capital?", accept=["Brasília", "DF"]),
        ShortAnswerQuestion(
            stem="Qual a capital?", accept=["Brasília"], reject=["Rio"]
        ),
    ],
    ids=["feedback", "comment-only", "two-patterns", "with-reject"],
)
def test_b4_render_other_accept_shapes_use_blocks(
    question: ShortAnswerQuestion,
) -> None:
    src = question.render()
    assert "[short-answer]:\n* " in src
    assert "[short-answer/accept]" not in src


def test_b4_render_comment_only_item_uses_bang_line() -> None:
    question = ShortAnswerQuestion(
        stem="Qual a capital?",
        accept=[AnswerPattern(pattern="Brasília", comment="Oficial")],
    )
    assert "* Brasília\n  ! Oficial" in question.render()


_ROUND_TRIP_BODIES = {
    "no-pattern": "[short-answer]\n",
    "list": "[short-answer/accept]:\n* Brasília\n* DF\n",
    "feedback": "[short-answer/accept]:\n* Brasília\n  > Certo!\n",
    "comment-only": "[short-answer/accept]:\n* Brasília\n  ! Nome oficial\n",
    "feedback-and-comment": "[short-answer/accept]:\n* Brasília\n  > Certo!\n  ! Nome oficial\n",
    "with-reject": "[short-answer]: Brasília\n\n[short-answer/reject]:\n* Rio\n  ! Foi capital\n",
}


@pytest.mark.parametrize(
    "body", list(_ROUND_TRIP_BODIES.values()), ids=list(_ROUND_TRIP_BODIES)
)
def test_b4_question_render_round_trips_through_load(body: str) -> None:
    first = load(_md(body), format="mdq").document
    assert first is not None
    again = _reload_dict(first.render())
    assert again == first.to_dict()


_BLANK_ROUND_TRIP_BODIES = {
    "no-pattern": "[^cap/short-answer]\n",
    "list": "[^cap/short-answer/accept]:\n* Brasília\n* DF\n",
    "comment-only": "[^cap/short-answer/accept]:\n* Brasília\n  ! Nome oficial\n",
    "accept-alias-list": _BLANK_ACCEPT,
    "with-reject": "[^cap/short-answer]: Brasília\n\n[^cap/short-answer/reject]:\n* Rio\n",
}


@pytest.mark.parametrize(
    "body", list(_BLANK_ROUND_TRIP_BODIES.values()), ids=list(_BLANK_ROUND_TRIP_BODIES)
)
def test_b4_fill_in_render_round_trips_through_load(body: str) -> None:
    first = _fill(_fill_md(body))
    again = _reload_dict(first.render())
    assert again == first.to_dict()


def test_b4_render_single_plain_blank_accept_as_simple_definition() -> None:
    question = FillInQuestion(
        stem=_FILL_STEM, blanks=[ShortAnswerBlank(id="cap", accept=["Brasília"])]
    )
    src = question.render()
    assert "[^cap/short-answer]: Brasília" in src
    assert "short-answer/accept" not in src


@pytest.mark.parametrize(
    "blank",
    [
        ShortAnswerBlank(
            id="cap", accept=[AnswerPattern(pattern="Brasília", comment="Oficial")]
        ),
        ShortAnswerBlank(id="cap", accept=["Brasília", "DF"]),
        ShortAnswerBlank(id="cap", accept=["Brasília"], reject=["Rio"]),
    ],
    ids=["comment-only", "two-patterns", "with-reject"],
)
def test_b4_render_other_blank_shapes_use_blocks(blank: ShortAnswerBlank) -> None:
    src = FillInQuestion(stem=_FILL_STEM, blanks=[blank]).render()
    assert "[^cap/short-answer]:\n* " in src
    assert "short-answer/accept" not in src


#
# AC11: converters
#
def _gift_texts(question: ShortAnswerQuestion) -> list[str]:
    [block] = Gift().from_mdq(question).blocks
    assert isinstance(block.answer, GiftShort)
    return [o.text for o in block.answer.options]


def _moodle_texts(question: ShortAnswerQuestion) -> list[str]:
    [block] = MoodleXml().from_mdq(question).blocks
    return [a.text for a in block.answers]


def _gift_import(*texts: str) -> ShortAnswerQuestion:
    block = GiftBlock(
        stem="Qual o maior rio do Brasil?",
        answer=GiftShort(options=[GiftOption(text=t) for t in texts]),
    )
    question = Gift().to_mdq(GiftQuestion(blocks=[block]))
    assert isinstance(question, ShortAnswerQuestion)
    return question


def _moodle_import(*texts: str) -> ShortAnswerQuestion:
    block = ShortAnswerBlock(
        questiontext="Qual o maior rio do Brasil?",
        answers=[MoodleAnswer(text=t, fraction=100.0) for t in texts],
    )
    question = MoodleXml().to_mdq(MoodleXmlQuestion(blocks=[block]))
    assert isinstance(question, ShortAnswerQuestion)
    return question


@pytest.mark.parametrize("texts", ["_gift_texts", "_moodle_texts"])
def test_b4_export_plain_literals_as_is(texts: str) -> None:
    question = ShortAnswerQuestion(stem="Rio?", accept=["Amazonas", "Rio Amazonas"])
    assert globals()[texts](question) == ["Amazonas", "Rio Amazonas"]


@pytest.mark.parametrize("texts", ["_gift_texts", "_moodle_texts"])
def test_b4_export_exact_literal_without_backticks(texts: str) -> None:
    question = ShortAnswerQuestion(stem="Rio?", accept=["`Amazonas`", "Solimões"])
    assert globals()[texts](question) == ["Amazonas", "Solimões"]


@pytest.mark.parametrize("texts", ["_gift_texts", "_moodle_texts"])
def test_b4_export_regex_raises(texts: str) -> None:
    question = ShortAnswerQuestion(stem="Rio?", accept=["Amazonas", "/Amaz[oô]nas/"])
    with pytest.raises(ValueError):
        globals()[texts](question)


@pytest.mark.parametrize("texts", ["_gift_texts", "_moodle_texts"])
def test_b4_export_asterisk_is_a_plain_literal(texts: str) -> None:
    question = ShortAnswerQuestion(stem="Rio?", accept=["Amazonas", "`*`"])
    assert globals()[texts](question) == ["Amazonas", "*"]


@pytest.mark.parametrize("texts", ["_gift_texts", "_moodle_texts"])
def test_b4_export_without_accept_raises(texts: str) -> None:
    question = ShortAnswerQuestion(stem="Rio?")
    with pytest.raises(ValueError):
        globals()[texts](question)


@pytest.mark.parametrize("importer", ["_gift_import", "_moodle_import"])
def test_b4_import_answers_become_accept_entries(importer: str) -> None:
    question = globals()[importer]("Amazonas", "Rio Amazonas")
    assert [p.pattern for p in question.effective_accept()] == [
        "Amazonas",
        "Rio Amazonas",
    ]


@pytest.mark.parametrize("importer", ["_gift_import", "_moodle_import"])
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/usr/bin", "`/usr/bin`"),
        ("`x`", None),
        ("a`b", "a`b"),
        ("Amazonas*", "Amazonas*"),
    ],
    ids=["slash", "backtick-start", "inner-backtick", "trailing-star"],
)
def test_b4_import_wraps_delimiter_lookalikes_in_backticks(
    importer: str, text: str, expected: str | None
) -> None:
    if expected is None:
        with pytest.raises(ValueError):
            globals()[importer](text)
        return
    question = globals()[importer](text)
    assert [p.pattern for p in question.effective_accept()] == [expected]


def test_b4_gift_import_writes_a_lone_asterisk_as_an_exact_literal() -> None:
    question = _gift_import("*")
    assert [p.pattern for p in question.effective_accept()] == ["`*`"]


def test_b4_moodle_import_of_a_full_credit_asterisk_is_the_catch_all_regex() -> None:
    question = _moodle_import("*")
    assert [p.pattern for p in question.effective_accept()] == ["/.*/"]


@pytest.mark.parametrize("importer", ["_gift_import", "_moodle_import"])
def test_b4_import_needing_wrap_with_inner_backtick_raises(importer: str) -> None:
    with pytest.raises(ValueError):
        globals()[importer]("/usr/`bin")


@pytest.mark.parametrize("importer", ["_gift_import", "_moodle_import"])
def test_b4_imported_slash_answer_scores_as_a_literal(importer: str) -> None:
    question = globals()[importer]("/usr/bin")
    assert question.score_response("/usr/bin").score == 1.0
    assert question.score_response("usr").score == 0.0


#
# AC12: CLI show
#
def test_b4_cli_show_lists_accept_patterns(tmp_path: Path) -> None:
    doc = tmp_path / "capital.mdq.md"
    doc.write_text(
        _md(
            "[short-answer]:\n* Brasília\n* Plano Piloto\n* /Distrito Federal/i\n"
        ),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["show", str(doc)])
    assert result.exit_code == 0, result.output
    assert "Brasília" in result.output
    assert "Plano Piloto" in result.output
    assert "Distrito Federal" in result.output


@pytest.mark.parametrize("importer", ["_gift_import", "_moodle_import"])
@pytest.mark.parametrize("text", ["# Brasília", "> x", "- x", "1. x"])
def test_b4_import_wraps_a_block_start_in_backticks(importer: str, text: str) -> None:
    question = globals()[importer](text)
    assert [p.pattern for p in question.effective_accept()] == [f"`{text}`"]

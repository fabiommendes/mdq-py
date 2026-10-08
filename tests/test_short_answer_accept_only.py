"""
Short answer: `accept` is the only answer list (see
`dev/specs/to-do/short-answer-accept-only.md`).

`oneOf` and `regex` no longer exist in short-answer questions. The Markdown
parser always emits `accept`, and the pattern keeps its delimiters.

Naming: `test_b1_*` cover AC1-AC3 (parser and question model), `test_b2_*`
cover AC4-AC6 (edge cases of the question), `test_b3_*` cover AC7-AC9 (fill-in
blanks and lint), `test_b4_*` cover AC10-AC12 (render, converters, CLI).
Select a batch with `-k b1`. Everything goes through `mdq.load`, `to_dict()`,
`score_response`, `render()`, the converters and the CLI.
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
    MoodleXmlBlock,
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


def _loaded_dict(source: str) -> dict:
    loaded = load(source, format="mdq")
    assert loaded.document is not None, [d.code for d in loaded.diagnostics]
    return loaded.document.to_dict()


def _question(source: str) -> ShortAnswerQuestion:
    loaded = load(source, format="mdq")
    assert isinstance(loaded.document, ShortAnswerQuestion), [
        d.code for d in loaded.diagnostics
    ]
    return loaded.document


def _patterns(items: list) -> list[str]:
    """Pattern strings of an `accept`/`reject` list, whatever its item form.

    A model's `to_dict()` may dump every item as `{"pattern": ...}`; the
    parser dict uses a bare string when there is no feedback or comment.
    """
    return [item if isinstance(item, str) else item["pattern"] for item in items]


def _codes(diagnostics: list[Diagnostic]) -> list[str]:
    return [d.code for d in diagnostics]


def _errors(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    return [d for d in diagnostics if d.severity == "error"]


#
# AC1: `[short-answer]: X` emits `accept: [X]`, with delimiters
#
@pytest.mark.parametrize(
    "written",
    [
        "Brasília",
        "`math.isnan`",
        "/1822-0?9-0?7/",
        "/abc/i",
        "*",
    ],
    ids=["plain", "backtick-literal", "regex", "regex-flag", "wildcard"],
)
def test_b1_simple_block_emits_accept_with_the_written_pattern(written: str) -> None:
    document = _loaded_dict(_md(f"[short-answer]: {written}\n"))
    assert _patterns(document["accept"]) == [written]
    assert "oneOf" not in document
    assert "regex" not in document


def test_b1_simple_block_does_not_emit_reject_or_open_ended() -> None:
    document = _loaded_dict(_md("[short-answer]: Brasília\n"))
    assert "reject" not in document
    assert not document.get("openEnded")


#
# AC2: simple block combined with accept/reject blocks
#
_ACCEPT_BLOCK = "[short-answer/accept]:\n* Distrito Federal\n  > Certo, também vale.\n* Plano Piloto\n"
_REJECT_BLOCK = (
    "[short-answer/reject]:\n* Rio de Janeiro\n  > Foi a capital até 1960.\n"
)


@pytest.mark.parametrize("order", ["bare-first", "accept-first"])
def test_b1_simple_block_plus_accept_block_is_a_parse_error(order: str) -> None:
    """`[short-answer/accept]` is an alias: both spellings in one document
    no longer merge (see `tests/test_short_answer_two_blocks.py`)."""
    bare = "[short-answer]: Brasília\n\n"
    body = bare + _ACCEPT_BLOCK if order == "bare-first" else _ACCEPT_BLOCK + "\n" + bare
    loaded = load(_md(body), format="mdq")
    assert loaded.document is None
    assert "parse-error" in _codes(_errors(loaded.diagnostics))


def test_b1_accept_block_alone_scores_every_item() -> None:
    question = _question(_md(_ACCEPT_BLOCK))
    assert question.score_response("Distrito Federal").score == 1.0
    assert question.score_response("plano piloto").score == 1.0
    assert question.score_response("Rio de Janeiro").score == 0.0


def test_b1_feedback_of_accept_block_items_is_kept() -> None:
    question = _question(_md(_ACCEPT_BLOCK))
    assert question.score_response("Distrito Federal").feedback == [
        "Certo, também vale."
    ]


def test_b1_bare_block_with_reject_block_keeps_accept_and_reject() -> None:
    body = "[short-answer]: Brasília\n\n" + _REJECT_BLOCK
    document = _loaded_dict(_md(body))
    assert _patterns(document["accept"]) == ["Brasília"]
    assert _patterns(document["reject"]) == ["Rio de Janeiro"]
    assert document["reject"][0]["feedback"] == "Foi a capital até 1960."
    assert "oneOf" not in document


def test_b1_bare_block_with_reject_block_scores_and_gives_reject_feedback() -> None:
    body = "[short-answer]: Brasília\n\n" + _REJECT_BLOCK
    question = _question(_md(body))
    assert question.score_response("Brasília").score == 1.0
    rejected = question.score_response("Rio de Janeiro")
    assert rejected.score == 0.0
    assert rejected.feedback == ["Foi a capital até 1960."]


@pytest.mark.parametrize(
    "body",
    [
        "[short-answer]: Brasília\n\n[short-answer]: Distrito Federal\n",
        "[short-answer/accept]:\n* Brasília\n\n[short-answer/accept]:\n* DF\n",
        "[short-answer/reject]:\n* Rio\n\n[short-answer/reject]:\n* Salvador\n",
    ],
    ids=["second-simple-block", "second-accept-block", "second-reject-block"],
)
def test_b1_repeated_block_is_an_error(body: str) -> None:
    loaded = load(_md(body), format="mdq")
    assert loaded.document is None
    assert _errors(loaded.diagnostics)


#
# AC3: `oneOf` and `regex` are rejected
#
@pytest.mark.parametrize(
    "extra",
    [
        {"oneOf": ["Brasília"]},
        {"regex": "/Bras[íi]lia/"},
        {"oneOf": ["Brasília"], "regex": "/Bras[íi]lia/"},
        {"accept": ["Brasília"], "oneOf": ["Distrito Federal"]},
    ],
    ids=["oneOf", "regex", "both", "with-accept"],
)
def test_b1_dict_with_one_of_or_regex_is_a_schema_error(extra: dict) -> None:
    loaded = load({"type": "short-answer", "stem": STEM, **extra})
    assert loaded.document is None
    assert "schema-error" in _codes(_errors(loaded.diagnostics))


@pytest.mark.parametrize(
    "extra",
    [{"oneOf": ["Brasília"]}, {"regex": "/Bras[íi]lia/"}],
    ids=["oneOf", "regex"],
)
def test_b1_yaml_source_with_one_of_or_regex_is_a_schema_error(extra: dict) -> None:
    key, value = next(iter(extra.items()))
    rendered = f"[{value[0]}]" if isinstance(value, list) else value
    source = f"type: short-answer\nstem: {STEM}\n{key}: {rendered}\n"
    loaded = load(source, format="yaml")
    assert loaded.document is None
    assert "schema-error" in _codes(_errors(loaded.diagnostics))


def test_b1_json_source_with_one_of_is_a_schema_error() -> None:
    source = '{"type": "short-answer", "stem": "Qual é a capital do Brasil?", "oneOf": ["Brasília"]}'
    loaded = load(source, format="json")
    assert loaded.document is None
    assert "schema-error" in _codes(_errors(loaded.diagnostics))


@pytest.mark.parametrize(
    "frontmatter",
    ["regex: Bras[ií]lia\n", "oneOf: [Brasília]\n"],
    ids=["regex", "oneOf"],
)
def test_b1_markdown_frontmatter_one_of_or_regex_is_dropped_as_unknown_key(
    frontmatter: str,
) -> None:
    loaded = load(_md("[short-answer]: Brasília\n", frontmatter), format="mdq")
    assert loaded.document is not None
    assert "unknown-frontmatter-key" in _codes(loaded.diagnostics)
    document = loaded.document.to_dict()
    assert "oneOf" not in document
    assert "regex" not in document
    assert _patterns(document["accept"]) == ["Brasília"]


#
# AC4: `[short-answer]:` followed by a bullet list
#
def test_b2_bullet_list_after_the_tag_becomes_one_accept_item_per_bullet() -> None:
    body = "[short-answer]:\n* Brasília\n* /Distrito Federal/i\n* `DF`\n"
    document = _loaded_dict(_md(body))
    assert _patterns(document["accept"]) == ["Brasília", "/Distrito Federal/i", "`DF`"]
    assert "oneOf" not in document
    assert "regex" not in document
    assert not document.get("openEnded")


def test_b2_bullet_list_answers_all_score_one() -> None:
    body = "[short-answer]:\n* Brasília\n* /Distrito Federal/i\n"
    question = _question(_md(body))
    assert question.score_response("brasilia").score == 1.0
    assert question.score_response("DISTRITO FEDERAL").score == 1.0
    assert question.score_response("Goiânia").score == 0.0


#
# AC5: content plus frontmatter `accept`
#
def test_b2_bare_content_with_frontmatter_accept_is_conflicting_accept() -> None:
    source = _md("[short-answer]: Brasília\n", "accept: [Distrito Federal]\n")
    loaded = load(source, format="mdq")
    assert loaded.document is None
    assert "conflicting-accept" in _codes(_errors(loaded.diagnostics))


def test_b2_backtick_content_with_frontmatter_accept_is_conflicting_accept() -> None:
    source = _md("[short-answer]: `DF`\n", "accept: [Brasília]\n")
    loaded = load(source, format="mdq")
    assert loaded.document is None
    assert "conflicting-accept" in _codes(_errors(loaded.diagnostics))


def test_b2_empty_block_with_frontmatter_accept_is_valid() -> None:
    source = _md("[short-answer]:\n", "accept: [Brasília]\n")
    loaded = load(source, format="mdq")
    assert "conflicting-accept" not in _codes(loaded.diagnostics)
    assert not _errors(loaded.diagnostics)
    question = _question(source)
    document = question.to_dict()
    assert _patterns(document["accept"]) == ["Brasília"]
    assert not document.get("openEnded")
    assert question.score_response("brasilia").score == 1.0


def test_b2_empty_block_with_accept_block_is_a_parse_error() -> None:
    body = "[short-answer]:\n\n[short-answer/accept]:\n* Brasília\n"
    loaded = load(_md(body), format="mdq")
    assert loaded.document is None
    assert "parse-error" in _codes(_errors(loaded.diagnostics))


def test_b2_empty_block_without_patterns_has_no_accept() -> None:
    document = _loaded_dict(_md("[short-answer]:\n"))
    assert "openEnded" not in document
    assert "accept" not in document
    assert "oneOf" not in document
    assert "regex" not in document


def test_b2_empty_block_reports_nothing_about_not_gradable() -> None:
    loaded = load(_md("[short-answer]:\n"), format="mdq")
    assert "short-answer-not-gradable" not in _codes(loaded.diagnostics)


def test_b2_bare_content_has_no_open_ended() -> None:
    document = _loaded_dict(_md("[short-answer]: Brasília\n"))
    assert not document.get("openEnded")


def test_b2_dict_without_accept_reports_nothing_about_it() -> None:
    loaded = load({"type": "short-answer", "stem": STEM})
    assert loaded.document is not None
    assert "short-answer-not-gradable" not in _codes(loaded.diagnostics)


def test_b2_dict_with_reject_only_reports_nothing_about_it() -> None:
    loaded = load({"type": "short-answer", "stem": STEM, "reject": ["Rio de Janeiro"]})
    assert "short-answer-not-gradable" not in _codes(loaded.diagnostics)


def test_b2_dict_with_accept_is_gradable() -> None:
    loaded = load({"type": "short-answer", "stem": STEM, "accept": ["Brasília"]})
    assert loaded.document is not None
    assert "short-answer-not-gradable" not in _codes(loaded.diagnostics)


def test_b2_dict_with_open_ended_is_an_error() -> None:
    loaded = load({"type": "short-answer", "stem": STEM, "openEnded": True})
    assert loaded.document is None
    assert [d for d in loaded.diagnostics if d.severity == "error"]


#
# AC7: simple blank definition emits `accept`
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


def _blank_dict(source: str, index: int = 0) -> dict:
    return _fill(source).to_dict()["blanks"][index]


@pytest.mark.parametrize(
    "written",
    ["Brasília", "`Brasília`", "/Bras[ií]lia/i"],
    ids=["plain", "backtick-literal", "regex-flag"],
)
def test_b3_simple_blank_definition_emits_accept(written: str) -> None:
    blank = _blank_dict(_fill_md(f"[^cap/short-answer]: {written}\n"))
    assert _patterns(blank["accept"]) == [written]
    assert "oneOf" not in blank
    assert "regex" not in blank
    assert not blank.get("openEnded")


_BLANK_ACCEPT = "[^cap/short-answer/accept]:\n* Distrito Federal\n* Plano Piloto\n  > Também vale.\n"
_BLANK_BARE = "[^cap/short-answer]: Brasília\n"


@pytest.mark.parametrize("order", ["bare-first", "accept-first"])
def test_b3_blank_bare_definition_plus_accept_alias_is_a_parse_error(order: str) -> None:
    text = (
        _BLANK_BARE + "\n" + _BLANK_ACCEPT
        if order == "bare-first"
        else _BLANK_ACCEPT + "\n" + _BLANK_BARE
    )
    loaded = load(_fill_md(text), format="mdq")
    assert loaded.document is None
    assert "parse-error" in _codes(_errors(loaded.diagnostics))


def test_b3_blank_accept_alias_alone_scores_every_item() -> None:
    question = _fill(_fill_md(_BLANK_ACCEPT))
    assert question.score_response({"cap": "Distrito Federal"}).score == 1.0
    assert question.score_response({"cap": "plano piloto"}).score == 1.0
    assert question.score_response({"cap": "Rio de Janeiro"}).score == 0.0


#
# AC8: blank with no pattern
#
def test_b3_empty_blank_definition_has_no_accept() -> None:
    blank = _blank_dict(_fill_md("[^cap/short-answer]:\n"))
    assert "openEnded" not in blank
    assert "accept" not in blank
    assert "oneOf" not in blank
    assert "regex" not in blank


def test_b3_blank_with_no_pattern_loads_without_errors() -> None:
    loaded = load(_fill_md("[^cap/short-answer]:\n"), format="mdq")
    assert loaded.document is not None
    assert not _errors(loaded.diagnostics)
    assert "short-answer-not-gradable" not in _codes(loaded.diagnostics)


def _fill_dict(blank: dict) -> dict:
    return {
        "type": "fill-in",
        "stem": _FILL_STEM,
        "blanks": [{"id": "cap", "type": "short-answer", **blank}],
    }


def test_b3_dict_blank_without_patterns_is_valid() -> None:
    loaded = load(_fill_dict({}))
    assert loaded.document is not None
    assert not _errors(loaded.diagnostics)
    assert "short-answer-not-gradable" not in _codes(loaded.diagnostics)


def test_b3_dict_blank_with_open_ended_is_an_error() -> None:
    loaded = load(_fill_dict({"openEnded": True}))
    assert loaded.document is None
    assert _errors(loaded.diagnostics)


@pytest.mark.parametrize(
    "extra",
    [{"oneOf": ["Brasília"]}, {"regex": "/Bras[íi]lia/"}],
    ids=["oneOf", "regex"],
)
def test_b3_dict_blank_with_one_of_or_regex_is_a_schema_error(extra: dict) -> None:
    loaded = load(_fill_dict(extra))
    assert loaded.document is None
    assert "schema-error" in _codes(_errors(loaded.diagnostics))


def test_b3_dict_blank_without_accept_reports_nothing_about_it() -> None:
    loaded = load(_fill_dict({}))
    assert "short-answer-not-gradable" not in _codes(loaded.diagnostics)


def test_b3_dict_blank_with_accept_is_gradable() -> None:
    loaded = load(_fill_dict({"accept": ["Brasília"]}))
    assert loaded.document is not None
    assert "short-answer-not-gradable" not in _codes(loaded.diagnostics)


#
# AC9: lints on the pattern of a simple block
#
def _paths(diagnostics: list[Diagnostic], code: str) -> list[list]:
    return [list(d.path) for d in diagnostics if d.code == code]


@pytest.mark.parametrize(
    ("written", "code"),
    [
        ("/abc/m", "ignored-regex-flag"),
        ("/^abc/", "redundant-regex-anchor"),
    ],
)
def test_b3_simple_block_pattern_lints_at_accept_zero(written: str, code: str) -> None:
    loaded = load(_md(f"[short-answer]: {written}\n"), format="mdq")
    assert _paths(loaded.diagnostics, code) == [["accept", 0]]


@pytest.mark.parametrize(
    ("written", "code"),
    [
        ("/abc/m", "ignored-regex-flag"),
        ("/^abc/", "redundant-regex-anchor"),
    ],
)
def test_b3_simple_blank_pattern_lints_at_blank_accept_zero(
    written: str, code: str
) -> None:
    source = (
        "O bioma [^a] e o rio [^b].\n\n"
        "[^a/short-answer]: Cerrado\n\n"
        f"[^b/short-answer]: {written}\n"
    )
    loaded = load(source, format="mdq")
    assert _paths(loaded.diagnostics, code) == [["blanks", 1, "accept", 0]]


def test_b3_shadowed_answers_is_never_reported() -> None:
    sources = [
        _md(_ACCEPT_BLOCK),
        _md("[short-answer]: /Bras[íi]lia/\n\n[short-answer/reject]:\n* Rio\n"),
        _fill_md(_BLANK_ACCEPT),
    ]
    for source in sources:
        loaded = load(source, format="mdq")
        assert "shadowed-answers" not in _codes(loaded.diagnostics)


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
    "plain": "[short-answer]: Brasília\n",
    "exact": "[short-answer]: `math.isnan`\n",
    "regex": "[short-answer]: /1822-0?9-0?7/i\n",
    "no-pattern": "[short-answer]:\n",
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
    "plain": "[^cap/short-answer]: Brasília\n",
    "regex": "[^cap/short-answer]: /Bras[ií]lia/i\n",
    "no-pattern": "[^cap/short-answer]:\n",
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
    block = MoodleXmlBlock(
        type="shortanswer",
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
    question = ShortAnswerQuestion(stem="Rio?", accept=["Amazonas", "*"])
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


def test_b4_gift_import_keeps_a_lone_asterisk_unwrapped() -> None:
    question = _gift_import("*")
    assert [p.pattern for p in question.effective_accept()] == ["*"]


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

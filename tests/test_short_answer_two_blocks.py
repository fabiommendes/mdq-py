"""
Short answer: two blocks, `[short-answer]` and `[short-answer/reject]` (see
`dev/specs/to-do/short-answer-two-blocks.md`).

`[short-answer]` is the accept block and `[short-answer/accept]` is only an
alias of it. Each block takes one pattern on the tag line or a bullet list on
the lines right after the tag. A list after a blank line is an epilogue
element and raises the `detached-answer-list` warning. Both spellings of the
accept block in one document are a `parse-error`.

Naming: `test_b1_*` (AC1-AC3, both names and both forms), `test_b2_*`
(AC4-AC6, blank line), `test_b3_*` (AC7-AC9, fill-in blanks), `test_b4_*`
(AC10-AC11, render and corpus).
"""

from __future__ import annotations

import pytest

from mdq import Diagnostic, load
from mdq.models import (
    AnswerPattern,
    FillInQuestion,
    ShortAnswerBlank,
    ShortAnswerQuestion,
)

STEM = "Qual é a capital do Brasil?"
FILL_STEM = "O maior bioma brasileiro é a [^bioma]."

ACCEPT_TAGS = ["[short-answer]", "[short-answer/accept]"]


def _q(body: str) -> str:
    return f"{STEM}\n\n{body}"


def _f(body: str) -> str:
    return f"{FILL_STEM}\n\n{body}"


def _codes(diagnostics: list[Diagnostic]) -> list[str]:
    return [d.code for d in diagnostics]


def _errors(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    return [d for d in diagnostics if d.severity == "error"]


def _patterns(items: list) -> list[str]:
    """Pattern strings of an `accept`/`reject` list, whatever its item form."""
    return [item if isinstance(item, str) else item["pattern"] for item in items]


def _doc(source: str) -> dict:
    loaded = load(source, format="mdq")
    assert loaded.document is not None, [d.code for d in loaded.diagnostics]
    return loaded.document.to_dict()


def _blank(source: str) -> dict:
    return _doc(source)["blanks"][0]


def _assert_parse_error(source: str) -> None:
    loaded = load(source, format="mdq")
    assert loaded.document is None
    assert "parse-error" in _codes(_errors(loaded.diagnostics))


def _detached(source: str) -> list[list]:
    loaded = load(source, format="mdq")
    return [list(d.path) for d in loaded.diagnostics if d.code == "detached-answer-list"]


def _detached_warnings(source: str) -> list[Diagnostic]:
    loaded = load(source, format="mdq")
    return [d for d in loaded.diagnostics if d.code == "detached-answer-list"]


#
# AC1: list right after the tag, in both names, for accept and reject
#
@pytest.mark.parametrize("tag", ACCEPT_TAGS)
def test_b1_accept_list_gives_one_accept_item_per_bullet(tag: str) -> None:
    document = _doc(_q(f"{tag}:\n* Brasília\n* /Bras[íi]lia DF/i\n* `DF`\n"))
    assert _patterns(document["accept"]) == ["Brasília", "/Bras[íi]lia DF/i", "`DF`"]
    assert "oneOf" not in document
    assert "regex" not in document
    assert not document.get("openEnded")


@pytest.mark.parametrize("tag", ACCEPT_TAGS)
def test_b1_accept_list_keeps_feedback_and_comment(tag: str) -> None:
    source = _q(
        f"{tag}:\n"
        "* Brasília\n"
        "  > Certo: capital desde 1960.\n"
        "* /Bras[íi]lia DF/i\n"
        "  ! O sufixo do estado é comum.\n"
        "* DF\n"
        "  > Sigla.\n"
        "  ! Distrito Federal.\n"
    )
    accept = _doc(source)["accept"]
    assert accept[0]["feedback"] == "Certo: capital desde 1960."
    assert accept[1]["comment"] == "O sufixo do estado é comum."
    assert accept[2]["feedback"] == "Sigla."
    assert accept[2]["comment"] == "Distrito Federal."


@pytest.mark.parametrize("tag", ACCEPT_TAGS)
def test_b1_accept_list_scores_every_item(tag: str) -> None:
    loaded = load(_q(f"{tag}:\n* Brasília\n  > Certo!\n* DF\n"), format="mdq")
    question = loaded.document
    assert isinstance(question, ShortAnswerQuestion)
    assert question.score_response("brasilia").score == 1.0
    assert question.score_response("brasilia").feedback == ["Certo!"]
    assert question.score_response("df").score == 1.0
    assert question.score_response("Goiânia").score == 0.0


@pytest.mark.parametrize("tag", ACCEPT_TAGS)
def test_b1_accept_line_form_equals_single_item_list(tag: str) -> None:
    line = _doc(_q(f"{tag}: Brasília\n"))
    listed = _doc(_q(f"{tag}:\n* Brasília\n"))
    assert line == listed
    assert _patterns(line["accept"]) == ["Brasília"]


def test_b1_reject_list_gives_reject_items_with_feedback_and_comment() -> None:
    source = _q(
        "[short-answer]: Brasília\n\n"
        "[short-answer/reject]:\n"
        "* Rio de Janeiro\n"
        "  > Foi capital até 1960.\n"
        "  ! Capital histórica.\n"
        "* *\n"
        "  > Não é a resposta.\n"
    )
    document = _doc(source)
    assert _patterns(document["accept"]) == ["Brasília"]
    assert _patterns(document["reject"]) == ["Rio de Janeiro", "*"]
    assert document["reject"][0]["feedback"] == "Foi capital até 1960."
    assert document["reject"][0]["comment"] == "Capital histórica."
    assert document["reject"][1]["feedback"] == "Não é a resposta."


def test_b1_reject_line_form_equals_single_item_list() -> None:
    head = "[short-answer]: Brasília\n\n"
    line = _doc(_q(head + "[short-answer/reject]: Rio de Janeiro\n"))
    listed = _doc(_q(head + "[short-answer/reject]:\n* Rio de Janeiro\n"))
    assert line == listed
    assert _patterns(line["reject"]) == ["Rio de Janeiro"]


@pytest.mark.parametrize("order", ["accept-first", "reject-first"])
@pytest.mark.parametrize("tag", ACCEPT_TAGS)
def test_b1_accept_and_reject_blocks_in_either_order(tag: str, order: str) -> None:
    accept = f"{tag}:\n* Brasília\n\n"
    reject = "[short-answer/reject]:\n* Rio de Janeiro\n\n"
    body = accept + reject if order == "accept-first" else reject + accept
    document = _doc(_q(body))
    assert _patterns(document["accept"]) == ["Brasília"]
    assert _patterns(document["reject"]) == ["Rio de Janeiro"]


def test_b1_reject_only_reject_list_scores_zero_for_a_rejected_answer() -> None:
    source = _q("[short-answer]:\n* Brasília\n\n[short-answer/reject]:\n* Rio de Janeiro\n  > Não mais.\n")
    question = load(source, format="mdq").document
    assert isinstance(question, ShortAnswerQuestion)
    result = question.score_response("rio de janeiro")
    assert result.score == 0.0
    assert result.feedback == ["Não mais."]


#
# AC2: both spellings, or a repeated block, is an error
#
_FORMS = {
    "line": lambda tag, text: f"{tag}: {text}\n",
    "list": lambda tag, text: f"{tag}:\n* {text}\n",
}


@pytest.mark.parametrize("order", ["short-first", "alias-first"])
@pytest.mark.parametrize("second_form", ["line", "list"])
@pytest.mark.parametrize("first_form", ["line", "list"])
def test_b1_both_accept_spellings_are_a_parse_error(
    first_form: str, second_form: str, order: str
) -> None:
    short = _FORMS[first_form]("[short-answer]", "Brasília")
    alias = _FORMS[second_form]("[short-answer/accept]", "Distrito Federal")
    body = short + "\n" + alias if order == "short-first" else alias + "\n" + short
    _assert_parse_error(_q(body))


def test_b1_both_spellings_with_an_empty_block_are_a_parse_error() -> None:
    _assert_parse_error(_q("[short-answer]:\n\n[short-answer/accept]:\n* Brasília\n"))
    _assert_parse_error(_q("[short-answer/accept]:\n\n[short-answer]:\n* Brasília\n"))


@pytest.mark.parametrize(
    "body",
    [
        "[short-answer]: Brasília\n\n[short-answer]: Distrito Federal\n",
        "[short-answer]:\n* Brasília\n\n[short-answer]:\n* DF\n",
        "[short-answer/accept]:\n* Brasília\n\n[short-answer/accept]:\n* DF\n",
        "[short-answer]: Brasília\n\n[short-answer/reject]: Rio\n\n[short-answer/reject]: Salvador\n",
        "[short-answer]: Brasília\n\n[short-answer/reject]:\n* Rio\n\n[short-answer/reject]:\n* Salvador\n",
    ],
    ids=[
        "two-short-lines",
        "two-short-lists",
        "two-alias-lists",
        "two-reject-lines",
        "two-reject-lists",
    ],
)
def test_b1_repeated_block_is_a_parse_error(body: str) -> None:
    _assert_parse_error(_q(body))


#
# AC3: content on the tag line plus a glued list
#
@pytest.mark.parametrize("tag", ACCEPT_TAGS + ["[short-answer/reject]"])
def test_b1_content_and_glued_list_is_a_parse_error(tag: str) -> None:
    head = "" if tag != "[short-answer/reject]" else "[short-answer]: Brasília\n\n"
    _assert_parse_error(_q(f"{head}{tag}: Brasília\n* Rio de Janeiro\n"))


#
# AC4: blank line, no content on the tag line
#
@pytest.mark.parametrize("tag", ACCEPT_TAGS)
def test_b2_empty_tag_and_detached_list_has_no_accept_and_goes_to_epilogue(tag: str) -> None:
    document = _doc(_q(f"{tag}:\n\n* Cite a evaporação.\n* Cite os rios voadores.\n"))
    assert "openEnded" not in document
    assert "accept" not in document
    assert "* Cite a evaporação." in document["epilogue"]
    assert "* Cite os rios voadores." in document["epilogue"]


@pytest.mark.parametrize("tag", ACCEPT_TAGS)
def test_b2_detached_list_warns_at_epilogue(tag: str) -> None:
    warnings = _detached_warnings(_q(f"{tag}:\n\n* Cite a evaporação.\n"))
    assert [list(w.path) for w in warnings] == [["epilogue"]]
    assert warnings[0].severity == "warning"


@pytest.mark.parametrize("tag", ACCEPT_TAGS)
def test_b2_empty_tag_and_detached_list_loads_without_errors(tag: str) -> None:
    loaded = load(_q(f"{tag}:\n\n* Cite a evaporação.\n"), format="mdq")
    assert loaded.document is not None
    assert not _errors(loaded.diagnostics)
    assert "short-answer-not-gradable" not in _codes(loaded.diagnostics)


def test_b2_detached_list_matches_the_corpus_example_shape() -> None:
    source = (
        "---\nid: sa-detached-list\ntitle: Water cycle\n---\n\n"
        "Describe the water cycle in the Amazon basin.\n\n"
        "[short-answer]:\n\n"
        "* Mention evaporation from the forest canopy.\n"
        '* Mention the "flying rivers" that carry moisture south.\n'
    )
    document = _doc(source)
    assert "openEnded" not in document
    assert document["epilogue"] == (
        "* Mention evaporation from the forest canopy.\n"
        '* Mention the "flying rivers" that carry moisture south.'
    )
    assert "accept" not in document


#
# AC5: blank line, content on the tag line
#
@pytest.mark.parametrize("tag", ACCEPT_TAGS)
def test_b2_line_content_and_detached_list_keeps_accept_and_epilogue(tag: str) -> None:
    document = _doc(_q(f"{tag}: Brasília\n\n* Rio de Janeiro\n* Salvador\n"))
    assert _patterns(document["accept"]) == ["Brasília"]
    assert "* Rio de Janeiro" in document["epilogue"]
    assert "* Salvador" in document["epilogue"]
    assert not document.get("openEnded")


@pytest.mark.parametrize("tag", ACCEPT_TAGS)
def test_b2_line_content_and_detached_list_warns_at_epilogue(tag: str) -> None:
    assert _detached(_q(f"{tag}: Brasília\n\n* Rio de Janeiro\n")) == [["epilogue"]]


def test_b2_detached_list_does_not_warn_when_glued() -> None:
    assert _detached(_q("[short-answer]:\n* Brasília\n")) == []


def test_b2_no_warning_without_a_list() -> None:
    assert _detached(_q("[short-answer]: Brasília\n")) == []


#
# AC6: reject with a blank line
#
def test_b2_reject_without_pattern_and_detached_list_is_a_parse_error() -> None:
    _assert_parse_error(
        _q("[short-answer]: Brasília\n\n[short-answer/reject]:\n\n* Rio de Janeiro\n")
    )


def test_b2_reject_line_and_detached_list_keeps_reject_and_epilogue() -> None:
    source = _q("[short-answer]: Brasília\n\n[short-answer/reject]: Rio de Janeiro\n\n* Salvador\n")
    document = _doc(source)
    assert _patterns(document["reject"]) == ["Rio de Janeiro"]
    assert "* Salvador" in document["epilogue"]
    assert _detached(source) == [["epilogue"]]


#
# AC7: blank blocks, list right after the tag
#
_BLANK_TAGS = ["[^bioma/short-answer]", "[^bioma/short-answer/accept]"]


@pytest.mark.parametrize("tag", _BLANK_TAGS)
def test_b3_blank_list_gives_accept_items(tag: str) -> None:
    blank = _blank(_f(f"{tag}:\n* Amazônia\n* Amazon\n  > As duas grafias valem.\n"))
    assert _patterns(blank["accept"]) == ["Amazônia", "Amazon"]
    assert blank["accept"][1]["feedback"] == "As duas grafias valem."
    assert "oneOf" not in blank
    assert "regex" not in blank
    assert not blank.get("openEnded")


@pytest.mark.parametrize("tag", _BLANK_TAGS)
def test_b3_blank_line_form_equals_single_item_list(tag: str) -> None:
    line = _doc(_f(f"{tag}: Amazônia\n"))
    listed = _doc(_f(f"{tag}:\n* Amazônia\n"))
    assert line == listed


@pytest.mark.parametrize("tag", _BLANK_TAGS)
def test_b3_blank_list_scores_every_item(tag: str) -> None:
    loaded = load(_f(f"{tag}:\n* Amazônia\n* Amazon\n"), format="mdq")
    question = loaded.document
    assert isinstance(question, FillInQuestion)
    assert question.score_response({"bioma": "amazonia"}).score == 1.0
    assert question.score_response({"bioma": "AMAZON"}).score == 1.0
    assert question.score_response({"bioma": "Cerrado"}).score == 0.0


@pytest.mark.parametrize("order", ["accept-first", "reject-first"])
@pytest.mark.parametrize("tag", _BLANK_TAGS)
def test_b3_blank_reject_block_in_either_order(tag: str, order: str) -> None:
    accept = f"{tag}:\n* Amazônia\n\n"
    reject = "[^bioma/short-answer/reject]:\n* Cerrado\n  > É o segundo maior.\n\n"
    body = accept + reject if order == "accept-first" else reject + accept
    blank = _blank(_f(body))
    assert _patterns(blank["accept"]) == ["Amazônia"]
    assert _patterns(blank["reject"]) == ["Cerrado"]
    assert blank["reject"][0]["feedback"] == "É o segundo maior."


def test_b3_blank_reject_line_form_equals_single_item_list() -> None:
    head = "[^bioma/short-answer]: Amazônia\n\n"
    line = _doc(_f(head + "[^bioma/short-answer/reject]: Cerrado\n"))
    listed = _doc(_f(head + "[^bioma/short-answer/reject]:\n* Cerrado\n"))
    assert line == listed


def test_b3_second_blank_is_independent_of_the_first() -> None:
    source = (
        "O bioma [^a] e o rio [^b].\n\n"
        "[^a/short-answer]:\n* Cerrado\n* Savana\n\n"
        "[^b/short-answer]: Tocantins\n"
    )
    blanks = _doc(source)["blanks"]
    assert _patterns(blanks[0]["accept"]) == ["Cerrado", "Savana"]
    assert _patterns(blanks[1]["accept"]) == ["Tocantins"]


#
# AC8: both spellings and content plus list in a blank
#
@pytest.mark.parametrize("order", ["short-first", "alias-first"])
@pytest.mark.parametrize("second_form", ["line", "list"])
@pytest.mark.parametrize("first_form", ["line", "list"])
def test_b3_blank_both_accept_spellings_are_a_parse_error(
    first_form: str, second_form: str, order: str
) -> None:
    short = _FORMS[first_form]("[^bioma/short-answer]", "Amazônia")
    alias = _FORMS[second_form]("[^bioma/short-answer/accept]", "Amazon")
    body = short + "\n" + alias if order == "short-first" else alias + "\n" + short
    _assert_parse_error(_f(body))


@pytest.mark.parametrize(
    "body",
    [
        "[^bioma/short-answer]: Amazônia\n\n[^bioma/short-answer]: Amazon\n",
        "[^bioma/short-answer]:\n* Amazônia\n\n[^bioma/short-answer]:\n* Amazon\n",
        "[^bioma/short-answer]: Amazônia\n\n"
        "[^bioma/short-answer/reject]: Cerrado\n\n[^bioma/short-answer/reject]: Caatinga\n",
    ],
    ids=["two-short-lines", "two-short-lists", "two-rejects"],
)
def test_b3_blank_repeated_block_is_a_parse_error(body: str) -> None:
    _assert_parse_error(_f(body))


@pytest.mark.parametrize("tag", _BLANK_TAGS + ["[^bioma/short-answer/reject]"])
def test_b3_blank_content_and_glued_list_is_a_parse_error(tag: str) -> None:
    head = "[^bioma/short-answer]: Amazônia\n\n" if tag.endswith("reject]") else ""
    _assert_parse_error(_f(f"{head}{tag}: Amazônia\n* Amazon\n"))


#
# AC9: detached list in a blank
#
@pytest.mark.parametrize("tag", _BLANK_TAGS)
def test_b3_empty_blank_and_detached_list_has_no_accept_and_list_goes_to_epilogue(
    tag: str,
) -> None:
    document = _doc(_f(f"{tag}:\n\n* Cite o rio Negro.\n"))
    blank = document["blanks"][0]
    assert "openEnded" not in blank
    assert "accept" not in blank
    assert "* Cite o rio Negro." in document["epilogue"]


@pytest.mark.parametrize("tag", _BLANK_TAGS)
def test_b3_empty_blank_and_detached_list_warns_at_epilogue(tag: str) -> None:
    source = _f(f"{tag}:\n\n* Cite o rio Negro.\n")
    warnings = _detached_warnings(source)
    assert [list(w.path) for w in warnings] == [["epilogue"]]
    assert warnings[0].severity == "warning"
    loaded = load(source, format="mdq")
    assert not _errors(loaded.diagnostics)
    assert "short-answer-not-gradable" not in _codes(loaded.diagnostics)


@pytest.mark.parametrize("tag", _BLANK_TAGS)
def test_b3_blank_line_content_and_detached_list_keeps_accept_and_epilogue(tag: str) -> None:
    source = _f(f"{tag}: Amazônia\n\n* Cerrado\n")
    document = _doc(source)
    assert _patterns(document["blanks"][0]["accept"]) == ["Amazônia"]
    assert "* Cerrado" in document["epilogue"]
    assert _detached(source) == [["epilogue"]]


def test_b3_blank_reject_without_pattern_and_detached_list_is_a_parse_error() -> None:
    _assert_parse_error(
        _f("[^bioma/short-answer]: Amazônia\n\n[^bioma/short-answer/reject]:\n\n* Cerrado\n")
    )


def test_b3_blank_reject_line_and_detached_list_keeps_reject_and_epilogue() -> None:
    source = _f(
        "[^bioma/short-answer]: Amazônia\n\n"
        "[^bioma/short-answer/reject]: Cerrado\n\n* Caatinga\n"
    )
    document = _doc(source)
    assert _patterns(document["blanks"][0]["reject"]) == ["Cerrado"]
    assert "* Caatinga" in document["epilogue"]
    assert _detached(source) == [["epilogue"]]


def test_b3_blank_list_after_blank_line_of_another_kind_is_not_flagged() -> None:
    """A glued list never warns, in a question or in a blank."""
    assert _detached(_f("[^bioma/short-answer]:\n* Amazônia\n")) == []


#
# AC10: render
#
def test_b4_render_single_plain_accept_as_line() -> None:
    question = ShortAnswerQuestion(stem="Qual a capital?", accept=["Brasília"])
    assert question.render() == "Qual a capital?\n\n[short-answer]: Brasília"


def test_b4_render_single_exact_and_regex_accept_as_line() -> None:
    exact = ShortAnswerQuestion(stem="Qual função?", accept=["`math.isnan`"])
    regex = ShortAnswerQuestion(stem="Quando?", accept=["/1822-0?9-0?7/i"])
    assert exact.render().endswith("[short-answer]: `math.isnan`")
    assert regex.render().endswith("[short-answer]: /1822-0?9-0?7/i")


def test_b4_render_two_patterns_as_list_under_short_answer() -> None:
    question = ShortAnswerQuestion(stem="Qual a capital?", accept=["Brasília", "DF"])
    assert question.render() == "Qual a capital?\n\n[short-answer]:\n* Brasília\n* DF"


@pytest.mark.parametrize(
    ("item", "tail"),
    [
        (AnswerPattern(pattern="Brasília", feedback="Certo!"), "* Brasília\n  > Certo!"),
        (AnswerPattern(pattern="Brasília", comment="Oficial"), "* Brasília\n  ! Oficial"),
        (
            AnswerPattern(pattern="Brasília", feedback="Certo!", comment="Oficial"),
            "* Brasília\n  > Certo!\n  ! Oficial",
        ),
    ],
    ids=["feedback", "comment-only", "feedback-and-comment"],
)
def test_b4_render_single_annotated_accept_as_list(item: AnswerPattern, tail: str) -> None:
    question = ShortAnswerQuestion(stem="Qual a capital?", accept=[item])
    assert question.render() == f"Qual a capital?\n\n[short-answer]:\n{tail}"


def test_b4_render_single_accept_with_reject_uses_lists() -> None:
    question = ShortAnswerQuestion(
        stem="Qual a capital?", accept=["Brasília"], reject=["Rio de Janeiro"]
    )
    assert question.render() == (
        "Qual a capital?\n\n"
        "[short-answer]:\n* Brasília\n\n"
        "[short-answer/reject]:\n* Rio de Janeiro"
    )


def test_b4_render_reject_is_always_a_list() -> None:
    question = ShortAnswerQuestion(
        stem="Qual a capital?",
        accept=["Brasília"],
        reject=[AnswerPattern(pattern="Rio", feedback="Não.")],
    )
    assert "[short-answer/reject]:\n* Rio\n  > Não." in question.render()


@pytest.mark.parametrize(
    "question",
    [
        ShortAnswerQuestion(stem="Qual a capital?", accept=["Brasília"]),
        ShortAnswerQuestion(stem="Qual a capital?", accept=["Brasília", "DF"]),
        ShortAnswerQuestion(
            stem="Qual a capital?", accept=[AnswerPattern(pattern="Brasília", comment="x")]
        ),
        ShortAnswerQuestion(stem="Qual a capital?", accept=["Brasília"], reject=["Rio"]),
        ShortAnswerQuestion(stem="Qual a capital?"),
    ],
    ids=["line", "list", "comment", "with-reject", "no-pattern"],
)
def test_b4_render_never_uses_the_accept_alias(question: ShortAnswerQuestion) -> None:
    assert "short-answer/accept" not in question.render()


_ROUND_TRIP_BODIES = {
    "line": "[short-answer]: Brasília\n",
    "alias-line": "[short-answer/accept]: Brasília\n",
    "exact": "[short-answer]: `math.isnan`\n",
    "regex": "[short-answer]: /1822-0?9-0?7/i\n",
    "no-pattern": "[short-answer]:\n",
    "list": "[short-answer]:\n* Brasília\n* DF\n",
    "alias-list": "[short-answer/accept]:\n* Brasília\n* DF\n",
    "feedback": "[short-answer]:\n* Brasília\n  > Certo!\n",
    "comment-only": "[short-answer]:\n* Brasília\n  ! Nome oficial\n",
    "feedback-and-comment": "[short-answer]:\n* Brasília\n  > Certo!\n  ! Nome oficial\n",
    "with-reject-line": "[short-answer]: Brasília\n\n[short-answer/reject]: Rio\n",
    "with-reject-list": "[short-answer]:\n* Brasília\n\n[short-answer/reject]:\n* Rio\n  ! Foi capital\n",
    "detached-list": "[short-answer]:\n\n* Cite a evaporação.\n",
    "line-and-detached-list": "[short-answer]: Brasília\n\n* Rio de Janeiro\n",
}


@pytest.mark.parametrize("body", list(_ROUND_TRIP_BODIES.values()), ids=list(_ROUND_TRIP_BODIES))
def test_b4_question_render_round_trips_through_load(body: str) -> None:
    first = load(_q(body), format="mdq").document
    assert first is not None
    again = load(first.render(), format="mdq").document
    assert again is not None
    assert again.to_dict() == first.to_dict()


def test_b4_blank_render_single_plain_accept_as_line() -> None:
    question = FillInQuestion(
        stem=FILL_STEM, blanks=[ShortAnswerBlank(id="bioma", accept=["Amazônia"])]
    )
    src = question.render()
    assert "[^bioma/short-answer]: Amazônia" in src
    assert "short-answer/accept" not in src


def test_b4_blank_render_two_patterns_as_list() -> None:
    question = FillInQuestion(
        stem=FILL_STEM, blanks=[ShortAnswerBlank(id="bioma", accept=["Amazônia", "Amazon"])]
    )
    assert "[^bioma/short-answer]:\n* Amazônia\n* Amazon" in question.render()


@pytest.mark.parametrize(
    "blank",
    [
        ShortAnswerBlank(id="bioma", accept=["Amazônia", "Amazon"]),
        ShortAnswerBlank(id="bioma", accept=[AnswerPattern(pattern="Amazônia", comment="x")]),
        ShortAnswerBlank(id="bioma", accept=["Amazônia"], reject=["Cerrado"]),
        ShortAnswerBlank(id="bioma"),
    ],
    ids=["list", "comment", "with-reject", "no-pattern"],
)
def test_b4_blank_render_never_uses_the_accept_alias(blank: ShortAnswerBlank) -> None:
    src = FillInQuestion(stem=FILL_STEM, blanks=[blank]).render()
    assert "short-answer/accept" not in src


def test_b4_blank_render_reject_is_a_list() -> None:
    blank = ShortAnswerBlank(id="bioma", accept=["Amazônia"], reject=["Cerrado"])
    src = FillInQuestion(stem=FILL_STEM, blanks=[blank]).render()
    assert "[^bioma/short-answer/reject]:\n* Cerrado" in src


_BLANK_ROUND_TRIP_BODIES = {
    "line": "[^bioma/short-answer]: Amazônia\n",
    "alias-line": "[^bioma/short-answer/accept]: Amazônia\n",
    "regex": "[^bioma/short-answer]: /Amaz[oô]nia/i\n",
    "no-pattern": "[^bioma/short-answer]:\n",
    "list": "[^bioma/short-answer]:\n* Amazônia\n* Amazon\n",
    "alias-list": "[^bioma/short-answer/accept]:\n* Amazônia\n* Amazon\n",
    "comment-only": "[^bioma/short-answer]:\n* Amazônia\n  ! Nome oficial\n",
    "feedback": "[^bioma/short-answer]:\n* Amazônia\n  > Certo!\n",
    "with-reject-line": "[^bioma/short-answer]: Amazônia\n\n[^bioma/short-answer/reject]: Cerrado\n",
    "with-reject-list": "[^bioma/short-answer]:\n* Amazônia\n\n[^bioma/short-answer/reject]:\n* Cerrado\n",
    "detached-list": "[^bioma/short-answer]:\n\n* Cite o rio Negro.\n",
}


@pytest.mark.parametrize(
    "body", list(_BLANK_ROUND_TRIP_BODIES.values()), ids=list(_BLANK_ROUND_TRIP_BODIES)
)
def test_b4_fill_in_render_round_trips_through_load(body: str) -> None:
    first = load(_f(body), format="mdq").document
    assert first is not None
    again = load(first.render(), format="mdq").document
    assert again is not None
    assert again.to_dict() == first.to_dict()


#
# AC11: docs and corpus shapes
#
def test_b4_lint_codes_doc_lists_detached_answer_list() -> None:
    from pathlib import Path

    doc = Path(__file__).resolve().parents[2] / "docs" / "lint-codes.md"
    assert "`detached-answer-list`" in doc.read_text(encoding="utf-8")


def test_b4_corpus_list_with_feedback_shape() -> None:
    source = (
        "---\nid: sa-list-feedback\ntitle: Capital of Brazil\n---\n\n"
        "What is the capital of Brazil?\n\n"
        "[short-answer]:\n"
        "* Brasília\n"
        "  > Right: the capital since 1960.\n"
        "* /Bras[íi]lia DF/i\n"
        "  ! The state suffix is a common addition.\n\n"
        "[short-answer/reject]:\n"
        "* Rio de Janeiro\n"
        "  > It used to be, but not since 1960.\n"
    )
    document = _doc(source)
    assert document["accept"] == [
        {"pattern": "Brasília", "feedback": "Right: the capital since 1960."},
        {"pattern": "/Bras[íi]lia DF/i", "comment": "The state suffix is a common addition."},
    ]
    assert document["reject"] == [
        {"pattern": "Rio de Janeiro", "feedback": "It used to be, but not since 1960."}
    ]
    loaded = load(source, format="mdq")
    assert "detached-answer-list" not in _codes(loaded.diagnostics)


def test_b4_corpus_blank_list_shape() -> None:
    source = (
        "---\nid: fill-in-blank-list\ntitle: Largest biome\n---\n\n"
        "The largest Brazilian biome is the [^biome].\n\n"
        "[^biome/short-answer]:\n"
        "* Amazon\n"
        "* Amazônia\n"
        "  > Both spellings are fine.\n"
    )
    blank = _blank(source)
    assert _patterns(blank["accept"]) == ["Amazon", "Amazônia"]
    assert blank["accept"][1]["feedback"] == "Both spellings are fine."


#
# AC1 (malformed blocks): feedback and comment lines must not interleave
#
_ITEM_TAGS = {
    "short-answer": ("[short-answer]", _q),
    "reject": ("[short-answer/reject]", _q),
    "blank": ("[^bioma/short-answer]", _f),
    "blank-reject": ("[^bioma/short-answer/reject]", _f),
}

_INTERLEAVED_LINES = {
    "feedback-comment-feedback": "  > Um.\n  ! Dois.\n  > Três.\n",
    "comment-feedback-comment": "  ! Um.\n  > Dois.\n  ! Três.\n",
    "feedback-comment-feedback-comment": "  > A.\n  ! B.\n  > C.\n  ! D.\n",
}


def _block(kind: str, item_lines: str) -> str:
    """Source with one pattern item carrying `item_lines`, in block `kind`."""
    tag, wrap = _ITEM_TAGS[kind]
    if kind == "reject":
        return wrap(f"[short-answer]: Brasília\n\n{tag}:\n* Rio de Janeiro\n{item_lines}")
    if kind == "blank-reject":
        return wrap(f"[^bioma/short-answer]: Amazônia\n\n{tag}:\n* Cerrado\n{item_lines}")
    return wrap(f"{tag}:\n* Brasília\n{item_lines}")


@pytest.mark.parametrize("lines", list(_INTERLEAVED_LINES.values()), ids=list(_INTERLEAVED_LINES))
@pytest.mark.parametrize("kind", list(_ITEM_TAGS))
def test_b5_interleaved_feedback_and_comment_is_a_parse_error(kind: str, lines: str) -> None:
    _assert_parse_error(_block(kind, lines))


@pytest.mark.parametrize("kind", list(_ITEM_TAGS))
def test_b5_interleaved_item_after_a_valid_item_is_a_parse_error(kind: str) -> None:
    source = _block(kind, "  > Certo.\n* Outro\n  > Um.\n  ! Dois.\n  > Três.\n")
    _assert_parse_error(source)


_VALID_LINES = {
    "feedback-only": ("  > Certo.\n", "Certo.", None),
    "comment-only": ("  ! Nota.\n", None, "Nota."),
    "feedback-then-comment": ("  > Certo.\n  ! Nota.\n", "Certo.", "Nota."),
    "comment-then-feedback": ("  ! Nota.\n  > Certo.\n", "Certo.", "Nota."),
}


def _item_of(kind: str, document: dict) -> dict:
    if kind == "blank":
        return document["blanks"][0]["accept"][0]
    if kind == "blank-reject":
        return document["blanks"][0]["reject"][0]
    return document["reject" if kind == "reject" else "accept"][0]


@pytest.mark.parametrize("lines", [v[0] for v in _VALID_LINES.values()], ids=list(_VALID_LINES))
@pytest.mark.parametrize("kind", list(_ITEM_TAGS))
def test_b5_non_interleaved_lines_load_and_keep_both_fields(kind: str, lines: str) -> None:
    expected = next(v for v in _VALID_LINES.values() if v[0] == lines)
    source = _block(kind, lines)
    loaded = load(source, format="mdq")
    assert loaded.document is not None
    assert not _errors(loaded.diagnostics)
    item = _item_of(kind, loaded.document.to_dict())
    assert item.get("feedback") == expected[1]
    assert item.get("comment") == expected[2]


@pytest.mark.parametrize("kind", list(_ITEM_TAGS))
def test_b5_multi_line_feedback_then_multi_line_comment_keeps_every_line(kind: str) -> None:
    lines = "  > Primeira.\n  > Segunda.\n  ! Nota um.\n  ! Nota dois.\n"
    item = _item_of(kind, _doc(_block(kind, lines)))
    for text in ("Primeira.", "Segunda."):
        assert text in item["feedback"]
    for text in ("Nota um.", "Nota dois."):
        assert text in item["comment"]


@pytest.mark.parametrize("kind", list(_ITEM_TAGS))
def test_b5_multi_line_comment_then_multi_line_feedback_keeps_every_line(kind: str) -> None:
    lines = "  ! Nota um.\n  ! Nota dois.\n  > Primeira.\n  > Segunda.\n"
    item = _item_of(kind, _doc(_block(kind, lines)))
    for text in ("Primeira.", "Segunda."):
        assert text in item["feedback"]
    for text in ("Nota um.", "Nota dois."):
        assert text in item["comment"]


def test_b5_interleaved_lines_never_merge_into_one_feedback() -> None:
    """The lenient parser used to join `> a`, `! b`, `> c` into `feedback: "a c"`."""
    loaded = load(_block("short-answer", _INTERLEAVED_LINES["feedback-comment-feedback"]), format="mdq")
    assert loaded.document is None


#
# AC2 (malformed blocks): a reject block needs a pattern
#
@pytest.mark.parametrize(
    "tail",
    [
        "[short-answer/reject]:\n",
        "[short-answer/reject]:\n\nUm parágrafo depois.\n",
        "[short-answer/reject]:\n\n* Rio de Janeiro\n",
    ],
    ids=["end-of-document", "followed-by-paragraph", "detached-list"],
)
def test_b5_reject_without_pattern_is_a_parse_error(tail: str) -> None:
    _assert_parse_error(_q(f"[short-answer]: Brasília\n\n{tail}"))


@pytest.mark.parametrize("order", ["reject-last", "reject-first"])
def test_b5_empty_reject_is_a_parse_error_in_either_block_order(order: str) -> None:
    accept = "[short-answer]: Brasília\n\n"
    reject = "[short-answer/reject]:\n\nUm parágrafo.\n"
    _assert_parse_error(_q(accept + reject if order == "reject-last" else reject + "\n" + accept))


@pytest.mark.parametrize(
    "tail",
    [
        "[^bioma/short-answer/reject]:\n",
        "[^bioma/short-answer/reject]:\n\nUm parágrafo depois.\n",
        "[^bioma/short-answer/reject]:\n\n* Cerrado\n",
    ],
    ids=["end-of-document", "followed-by-paragraph", "detached-list"],
)
def test_b5_blank_reject_without_pattern_is_a_parse_error(tail: str) -> None:
    _assert_parse_error(_f(f"[^bioma/short-answer]: Amazônia\n\n{tail}"))


def test_b5_empty_accept_block_stays_valid_with_no_accept() -> None:
    """Only the reject block needs a pattern: an empty accept block has no `accept`."""
    document = _doc(_q("[short-answer]:\n"))
    assert "openEnded" not in document
    assert "accept" not in document

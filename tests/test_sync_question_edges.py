"""Cases of `mdq.sync_question` that tests/test_sync_question.py does not cover."""

from __future__ import annotations

from pathlib import Path

import pytest

from mdq import SyncError, models, parse, sync_question

CHOICES = "Qual rio corta Manaus?\n\n* [*] Rio Negro\n* [ ] Rio Tietê\n"

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "valid"


def assert_law1(out: str, target: models.Question) -> None:
    expected = target.with_ids().normalize().to_dict()
    assert parse(out, ids="fill").normalize().to_dict() == expected


def _blank(question: models.Question, blank_id: str) -> models.Blank:
    assert isinstance(question, models.FillInQuestion)
    [blank] = [b for b in question.blanks if b.id == blank_id]
    return blank


def _with_blank(question: models.Question, blank: models.Blank) -> models.Question:
    assert isinstance(question, models.FillInQuestion)
    blanks = [blank if b.id == blank.id else b for b in question.blanks]
    return question.model_copy(update={"blanks": blanks})


#
# Imports
#


def test_private_helpers_are_reached_through_their_package() -> None:
    from mdq import _parser
    from mdq.models import can_inline_id

    assert not hasattr(_parser, "_frontmatter_fields")
    assert _parser.frontmatter_fields("multiple-choice")
    assert "can_inline_id" not in models.__all__
    assert can_inline_id("Um parágrafo.")


#
# Line endings
#


def test_a_new_field_in_a_source_with_crlf_keeps_the_line_ending() -> None:
    src = "---\r\nid: rios\r\n---\r\n\r\n" + CHOICES.replace("\n", "\r\n")
    target = parse(src).model_copy(update={"title": "Rios", "tags": ["geo", "rios"]})
    out = sync_question(src, target)
    assert "\n" not in out.replace("\r\n", "")
    assert parse(out).title == "Rios"
    assert parse(out).tags == ["geo", "rios"]
    assert_law1(out, target)


def test_a_source_with_cr_only_keeps_the_line_ending() -> None:
    src = "---\rtitle: Rios\rlocale: pt-BR\r---\r\r" + CHOICES.replace("\n", "\r")
    target = parse(src).model_copy(update={"locale": None, "weight": 2.0})
    out = sync_question(src, target)
    assert "\n" not in out
    assert out == src.replace("locale: pt-BR\r", "weight: 2.0\r")
    assert_law1(out, target)


def test_a_removed_key_in_a_source_with_cr_only_removes_the_line() -> None:
    src = "---\rtitle: Rios\rlocale: pt-BR\rauthor: Ana\r---\r\r" + CHOICES.replace(
        "\n", "\r"
    )
    target = parse(src).model_copy(update={"locale": None})
    assert sync_question(src, target) == src.replace("locale: pt-BR\r", "")


def test_a_mixed_source_writes_a_new_key_with_the_ending_of_the_frontmatter() -> None:
    src = "---\r\ntitle: Rios\r\n---\n\n" + CHOICES
    target = parse(src).model_copy(update={"weight": 2.0})
    out = sync_question(src, target)
    assert out == "---\r\ntitle: Rios\r\nweight: 2.0\r\n---\n\n" + CHOICES
    assert_law1(out, target)


def test_a_body_rewrite_uses_the_line_ending_of_the_body() -> None:
    src = "---\ntitle: Rios\n---\r\n\r\n" + CHOICES.replace("\n", "\r\n")
    target = parse(src).model_copy(update={"stem": "Qual rio corta Belém?"})
    out = sync_question(src, target)
    assert out.startswith("---\ntitle: Rios\n---\r\n")
    assert "\n" not in out[len("---\ntitle: Rios\n---\r\n") :].replace("\r\n", "")
    assert_law1(out, target)


def test_the_full_render_keeps_the_final_line_break_of_the_source() -> None:
    src = "---\ntitle: Rios\n---\n\n" + CHOICES
    target = parse(src).model_copy(update={"comment": "linha"})
    # Without a final line break, the result has none either.
    bare = src.rstrip("\n")
    out = sync_question(bare, parse(bare).model_copy(update={"stem": "Qual rio?"}))
    assert not out.endswith("\n")
    assert sync_question(src, target).endswith("\n")


#
# Frontmatter and body together
#


def test_a_renamed_blank_moves_its_entry_in_the_frontmatter_maps() -> None:
    path = EXAMPLES / "fill-in" / "numeric-blank-declared.mdq.md"
    src = path.read_text(encoding="utf-8")
    q = parse(src, ids="fill")
    assert isinstance(q, models.FillInQuestion)
    height = _blank(q, "height").model_copy(update={"id": "altura"})
    blanks = [height if b.id == "height" else b for b in q.blanks]
    target = q.model_copy(
        update={
            "blanks": blanks,
            "stem": q.stem.replace("[^height]", "[^altura]"),
        }
    )
    out = sync_question(src, target)

    assert out.startswith(
        "---\nid: fill-in-numeric-declared\ntitle: Bandeira and Cerrado\n"
    )
    assert "height" not in out
    assert "  altura: decimal\n" in out
    assert_law1(out, target)


def test_a_removed_blank_removes_its_entries_in_the_frontmatter_maps() -> None:
    path = EXAMPLES / "fill-in" / "numeric-blank-declared.mdq.md"
    src = path.read_text(encoding="utf-8")
    q = parse(src, ids="fill")
    assert isinstance(q, models.FillInQuestion)
    target = q.model_copy(
        update={
            "blanks": [b for b in q.blanks if b.id != "height"],
            "stem": q.stem.replace("[^height] meters", "2892 meters"),
        }
    )
    out = sync_question(src, target)

    assert out.startswith(
        "---\nid: fill-in-numeric-declared\ntitle: Bandeira and Cerrado\n---\n"
    )
    assert_law1(out, target)


def test_an_obsolete_type_line_goes_and_the_rest_of_the_frontmatter_stays() -> None:
    src = (
        "---\n# Rios\ntype: multiple-choice\ntitle: 'Rios'  # titulo\n---\n"
        "Q?\n\n* [ ] a\n* [ ] b\n"
    )
    target = parse(src.replace("type: multiple-choice\n", ""), ids="fill")
    assert target.type == "multiple-selection"
    out = sync_question(src, target)

    assert out == "---\n# Rios\ntitle: 'Rios'  # titulo\n---\nQ?\n\n* [ ] a\n* [ ] b\n"
    assert parse(out).type == "multiple-selection"
    assert_law1(out, target)


def test_no_blank_line_appears_after_the_frontmatter_on_a_body_rewrite() -> None:
    src = "---\ntitle: Rios\n---\nQual rio corta Manaus?\n\n* [*] Rio Negro\n* [ ] Rio Tietê\n"
    target = parse(src).model_copy(update={"stem": "Qual rio corta Belém?"})
    out = sync_question(src, target)
    assert out.startswith("---\ntitle: Rios\n---\nQual rio corta Belém?\n")
    assert_law1(out, target)


#
# Ids
#


def test_a_derived_id_that_a_clash_renamed_is_not_written() -> None:
    src = "Q?\n\n* [*] a\n* [ ] [a] b\n"
    q = parse(src, ids="fill")
    target = q.model_copy(update={"stem": "Outra pergunta?"})
    out = sync_question(src, target)

    assert "[a-2]" not in out
    assert out == "Outra pergunta?\n\n* [*] a\n* [ ] [a] b\n"
    assert_law1(out, target)


def test_a_choice_id_that_the_new_text_does_not_derive_is_written() -> None:
    src = "Q?\n\n* [*] Amazonas\n* [ ] Tietê\n"
    q = parse(src, ids="fill")
    assert isinstance(q, models.MultipleChoiceQuestion)
    assert q.choices[0].id == "amazonas"
    first = q.choices[0].model_copy(update={"text": "Rio Amazonas"})
    target = q.model_copy(update={"choices": [first, *q.choices[1:]]})
    out = sync_question(src, target)

    assert "[amazonas]" in out
    kept = parse(out, ids="keep")
    assert isinstance(kept, models.MultipleChoiceQuestion)
    assert [c.id for c in kept.choices] == ["amazonas", None]
    assert_law1(out, target)


#
# Not minimal edits
#


def test_an_unnormalized_source_is_returned_as_it_is() -> None:
    src = "---\nauthor: ' Ana '\n---\nQ?\n\n* [*] a\n* [ ] b\n"
    target = parse(src, ids="fill")
    out = sync_question(src, target)
    assert out == src
    assert_law1(out, target)


def test_an_alias_does_not_edit_the_anchor() -> None:
    src = "---\n# nota\nmeta:\n  a: &x 1\n  b: *x\n---\nQ?\n\n* [*] a\n* [ ] b\n"
    q = parse(src, ids="fill")
    meta = dict(q.meta or {})
    assert meta == {"a": 1, "b": 1}
    target = q.model_copy(update={"meta": {"a": 1, "b": 2}})
    out = sync_question(src, target)

    assert "&x" not in out or "*x" in out
    assert_law1(out, target)
    assert parse(out, ids="fill").meta == {"a": 1, "b": 2}
    # No fallback: the body is as written.
    assert out.endswith("---\nQ?\n\n* [*] a\n* [ ] b\n")


def test_an_edit_of_the_anchor_keeps_its_aliases_right() -> None:
    src = "---\n# nota\nmeta:\n  a: &x 1\n  b: *x\n---\nQ?\n\n* [*] a\n* [ ] b\n"
    q = parse(src, ids="fill")
    target = q.model_copy(update={"meta": {"a": 3, "b": 1}})
    out = sync_question(src, target)

    assert parse(out, ids="fill").meta == {"a": 3, "b": 1}
    assert out.startswith("---\n# nota\nmeta:\n")
    assert out.endswith("---\nQ?\n\n* [*] a\n* [ ] b\n")
    assert_law1(out, target)


def test_a_pattern_list_keeps_the_string_form() -> None:
    path = EXAMPLES / "fill-in" / "pre-validation-entry-forms.mdq.md"
    src = path.read_text(encoding="utf-8")
    q = parse(src, ids="fill")
    state = _blank(q, "state")
    assert isinstance(state, models.ShortAnswerBlank)
    assert state.pre_accept is not None
    extra = models.AnswerPattern(pattern="Pantanal")
    state = state.model_copy(update={"pre_accept": [*state.pre_accept, extra]})
    target = _with_blank(q, state)
    out = sync_question(src, target)

    assert "- Mato Grosso\n" in out
    assert "pattern: Mato Grosso" not in out
    assert "- Pantanal\n" in out
    assert_law1(out, target)


def test_a_declared_domain_that_the_parse_infers_is_removed() -> None:
    src = "---\ndomain: decimal\ntitle: Altura\n---\nQual a altura do Pico da Bandeira, em metros?\n\n[numeric]: 2892 +- 5\n"
    q = parse(src, ids="fill")
    assert isinstance(q, models.NumericQuestion)
    assert q.domain == "decimal"
    target = q.model_copy(update={"domain": "integer", "decimal_places": None})
    out = sync_question(src, target)

    assert out == src.replace("domain: decimal\n", "")
    assert_law1(out, target)


#
# Short cases
#


def test_a_lone_new_id_is_written_inline() -> None:
    target = parse(CHOICES).model_copy(update={"id": "rios"})
    assert sync_question(CHOICES, target) == f"[rios] {CHOICES}"


def test_an_id_that_is_not_a_slug_goes_to_the_frontmatter() -> None:
    src = f"[rios] {CHOICES}"
    target = parse(src).model_copy(update={"id": "2024"})
    out = sync_question(src, target)
    assert "[rios]" not in out
    assert parse(out).id == "2024"


def test_a_removed_key_leaves_the_others_in_place() -> None:
    src = "---\ntitle: Rios\nlocale: pt-BR\nauthor: Ana\n---\n\n" + CHOICES
    target = parse(src).model_copy(update={"locale": None})
    assert sync_question(src, target) == src.replace("locale: pt-BR\n", "")


def test_a_removed_comment_drops_its_lines() -> None:
    src = "---\n# nota\ntitle: Rios\n---\n\n" + CHOICES
    target = parse(src).model_copy(update={"comment": None})
    assert sync_question(src, target) == src.replace("# nota\n", "")


def test_blank_marks_keep_the_multiple_choice_type() -> None:
    target = parse(CHOICES)
    assert isinstance(target, models.MultipleChoiceQuestion)
    target = target.model_copy(
        update={
            "choices": [c.model_copy(update={"score": None}) for c in target.choices]
        }
    )
    out = sync_question(CHOICES, target)
    assert parse(out).type == "multiple-choice"
    assert_law1(out, target)


def test_a_source_that_does_not_parse_is_a_sync_error() -> None:
    with pytest.raises(SyncError):
        sync_question("---\ntitle: [\n---\n\nQ\n", parse(CHOICES))


#
# Fill-in blanks keep the origin of each frontmatter value
#

FILL_IN_SHORT = """\
---
title: Pantanal
preAccept:
  estado:
    - Mato Grosso
preReject:
  estado:
    - pattern: "/\\\\d+/"
      comment: Digits are not a name.
incorrectFeedback:
  estado: Escreva o nome do estado.
---

O Pantanal fica sobretudo em [^estado] e inunda na estação [^estacao].

[^estado/short-answer]:
* Mato Grosso do Sul

[^estacao/short-answer]:
* chuvosa
"""


def _short(src: str, blank_id: str, **update: object) -> tuple[str, models.Question]:
    q = parse(src, ids="fill")
    blank = _blank(q, blank_id)
    assert isinstance(blank, models.ShortAnswerBlank)
    target = _with_blank(q, blank.model_copy(update=update))
    return sync_question(src, target), target


def test_a_changed_pre_accept_changes_only_its_entry() -> None:
    out, target = _short(
        FILL_IN_SHORT,
        "estado",
        pre_accept=[
            models.AnswerPattern(pattern="Mato Grosso"),
            models.AnswerPattern(pattern="MT"),
        ],
    )
    assert "- Mato Grosso\n" in out
    assert "- MT\n" in out
    assert "pattern: Mato Grosso" not in out
    assert out.split("preReject:")[1] == FILL_IN_SHORT.split("preReject:")[1]
    assert_law1(out, target)


def test_a_changed_pre_reject_keeps_the_frontmatter_origin() -> None:
    out, target = _short(
        FILL_IN_SHORT,
        "estado",
        pre_reject=[models.AnswerPattern(pattern="/\\d+/", comment="Numbers.")],
    )
    assert out.count("comment:") == 1
    assert "Numbers." in out
    assert out.split("---\n")[2] == FILL_IN_SHORT.split("---\n")[2]
    assert_law1(out, target)


def test_a_changed_incorrect_feedback_changes_only_its_line() -> None:
    out, target = _short(FILL_IN_SHORT, "estado", incorrect_feedback="Tente de novo.")
    assert out == FILL_IN_SHORT.replace(
        "  estado: Escreva o nome do estado.", "  estado: Tente de novo."
    )
    assert_law1(out, target)


def test_a_new_pre_accept_on_another_blank_extends_the_map() -> None:
    out, target = _short(
        FILL_IN_SHORT,
        "estacao",
        pre_accept=[models.AnswerPattern(pattern="chuva")],
    )
    assert "- Mato Grosso\n" in out
    assert "  estacao:\n" in out
    assert "- chuva\n" in out
    assert_law1(out, target)

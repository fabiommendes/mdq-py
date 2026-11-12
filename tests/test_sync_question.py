"""
`mdq.sync_question`: write a changed question back into its source with
the fewest edits.

Two laws (issue `mdq-py-sync-question-escrita-de-volta-com-edicao-minima`):

1. Correctness: `parse(sync_question(src, t), ids="fill")` equals `t`
   normalized, with ids filled on both sides.
2. Identity: `sync_question(src, parse(src, ids="fill")) == src`, byte
   for byte.

The examples check the exact text that comes out (or the exact lines that
changed), not only law 1: a `render()` of the whole target satisfies law 1
and loses the comments, the quote style and the key order of the source.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mdq import models, parse, sync_question
from mdq.errors import SyncError
from mdq.hypothesis import questions

from _corpus import VALID_QUESTIONS, relative_id

_PROPERTY_SETTINGS = settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)

#: A source with every kind of formatting a naive writer would destroy:
#: comments inside the mapping, quote styles, a blank line between keys and
#: a key order that is not alphabetical.
FRONTMATTER_SRC = """\
---
# Rios brasileiros.
title: "Rios do Brasil"
# peso definido pela coordenacao
weight: 2

meta:
  # origem do item
  autor: 'Ana'
  nivel: 3
tags: [rio, geografia]
---
Qual é o maior rio do Brasil em volume de água?

* [*] Amazonas
* [ ] Tocantins
"""

#: The same question without a front matter.
BARE_SRC = """\
Qual é o maior rio do Brasil em volume de água?

* [*] Amazonas
* [ ] Tocantins
"""


def load(src: str) -> models.Question:
    return parse(src, ids="fill", kind="question")


def lines_of(text: str) -> list[str]:
    return text.splitlines()


def changes(src: str, out: str) -> list[tuple[list[str], list[str]]]:
    """The hunks that turn `src` into `out`, as (old lines, new lines)."""
    old, new = lines_of(src), lines_of(out)
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    return [
        (old[i1:i2], new[j1:j2])
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


def assert_law1(out: str, target: models.Question) -> None:
    expected = target.with_ids().normalize().to_dict()
    got = parse(out, ids="fill", kind="question")
    assert got.normalize().to_dict() == expected


def frontmatter_of(src: str) -> str:
    """The text of `src` up to and including the closing `---` line."""
    assert src.startswith("---\n")
    end = src.index("\n---\n", 3) + len("\n---\n")
    return src[:end]


#
# Law 2: identity
#
@pytest.mark.parametrize("path", VALID_QUESTIONS, ids=relative_id)
def test_identity_on_the_valid_corpus(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    assert sync_question(src, load(src)) == src


@_PROPERTY_SETTINGS
@given(questions(normalize=True))
def test_identity_on_generated_questions(question: models.Question) -> None:
    src = question.render()
    assert sync_question(src, load(src)) == src


#
# Law 1: correctness
#
@_PROPERTY_SETTINGS
@given(questions(normalize=True), questions(normalize=True))
def test_the_output_parses_to_the_normalized_target(
    old: models.Question, target: models.Question
) -> None:
    """Any source and any target: the result is the target."""
    out = sync_question(old.render(), target)
    assert_law1(out, target)


#: Titles with a visible character. A title with none is `blank-text`, so
#: the markdown cannot express it and `sync_question` raises `SyncError`.
_TITLES = st.text(
    st.characters(exclude_categories=("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")),
    min_size=1,
    max_size=30,
).filter(str.strip)


@_PROPERTY_SETTINGS
@given(questions(normalize=True), _TITLES)
def test_a_changed_title_is_written(question: models.Question, title: str) -> None:
    src = question.render()
    target = load(src).model_copy(update={"title": title})
    assert_law1(sync_question(src, target), target)


@pytest.mark.parametrize("path", VALID_QUESTIONS, ids=relative_id)
def test_a_changed_title_on_the_valid_corpus(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    target = load(src).model_copy(update={"title": "Bacias hidrográficas"})
    assert_law1(sync_question(src, target), target)


@pytest.mark.parametrize("path", VALID_QUESTIONS, ids=relative_id)
def test_a_changed_weight_on_the_valid_corpus(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    target = load(src).model_copy(update={"weight": 3.5})
    assert_law1(sync_question(src, target), target)


#
# Front matter: scalars
#
def test_a_changed_scalar_changes_only_its_line() -> None:
    target = load(FRONTMATTER_SRC).model_copy(update={"weight": 3.5})
    out = sync_question(FRONTMATTER_SRC, target)

    assert changes(FRONTMATTER_SRC, out) == [(["weight: 2"], ["weight: 3.5"])]
    assert_law1(out, target)


def test_a_changed_string_keeps_comments_quotes_and_blank_lines() -> None:
    target = load(FRONTMATTER_SRC).model_copy(update={"title": "Bacias do Brasil"})
    out = sync_question(FRONTMATTER_SRC, target)

    [(old, new)] = changes(FRONTMATTER_SRC, out)
    assert old == ['title: "Rios do Brasil"']
    assert len(new) == 1
    assert yaml.safe_load(new[0]) == {"title": "Bacias do Brasil"}
    # The rest is byte for byte the source, comments and blank line included.
    assert "# peso definido pela coordenacao\n" in out
    assert "# origem do item\n" in out
    assert "autor: 'Ana'\n" in out
    assert "weight: 2\n\nmeta:\n" in out
    assert_law1(out, target)


def test_a_changed_body_keeps_the_commented_frontmatter_byte_for_byte() -> None:
    target = load(FRONTMATTER_SRC).model_copy(
        update={"stem": "Qual é o maior rio inteiramente brasileiro?"}
    )
    out = sync_question(FRONTMATTER_SRC, target)

    assert frontmatter_of(out) == frontmatter_of(FRONTMATTER_SRC)
    assert "Qual é o maior rio inteiramente brasileiro?" in out
    assert_law1(out, target)


#
# Front matter: nested keys and lists
#
def test_a_changed_nested_key_changes_only_its_line() -> None:
    q = load(FRONTMATTER_SRC)
    assert q.meta is not None
    target = q.model_copy(update={"meta": {**q.meta, "nivel": 4}})
    out = sync_question(FRONTMATTER_SRC, target)

    assert changes(FRONTMATTER_SRC, out) == [(["  nivel: 3"], ["  nivel: 4"])]
    assert_law1(out, target)


def test_a_changed_list_changes_only_the_tags() -> None:
    target = load(FRONTMATTER_SRC).model_copy(
        update={"tags": ["rio", "geografia", "hidrografia"]}
    )
    out = sync_question(FRONTMATTER_SRC, target)

    [(old, new)] = changes(FRONTMATTER_SRC, out)
    assert old == ["tags: [rio, geografia]"]
    assert yaml.safe_load("\n".join(new)) == {
        "tags": ["rio", "geografia", "hidrografia"]
    }
    assert_law1(out, target)


#
# Front matter: removed and new keys
#
def test_a_removed_key_drops_only_its_line() -> None:
    target = load(FRONTMATTER_SRC).model_copy(update={"weight": 1.0})
    out = sync_question(FRONTMATTER_SRC, target)

    expected = [line for line in lines_of(FRONTMATTER_SRC) if line != "weight: 2"]
    assert lines_of(out) == expected
    assert_law1(out, target)


def test_a_removed_block_key_drops_the_whole_block() -> None:
    target = load(FRONTMATTER_SRC).model_copy(update={"meta": None})
    out = sync_question(FRONTMATTER_SRC, target)

    assert "meta:" not in out
    assert "autor" not in out
    assert "nivel" not in out
    kept = [
        'title: "Rios do Brasil"',
        "weight: 2",
        "tags: [rio, geografia]",
    ]
    out_lines = lines_of(out)
    assert [line for line in out_lines if line in kept] == kept
    assert_law1(out, target)


def test_a_new_key_goes_to_the_end_without_reordering_the_others() -> None:
    target = load(FRONTMATTER_SRC).model_copy(update={"author": "Ana Souza"})
    out = sync_question(FRONTMATTER_SRC, target)

    out_lines = lines_of(out)
    close = out_lines.index("---", 1)
    assert yaml.safe_load(out_lines[close - 1]) == {"author": "Ana Souza"}
    others = [line for i, line in enumerate(out_lines) if i != close - 1]
    assert others == lines_of(FRONTMATTER_SRC)
    assert_law1(out, target)


def test_a_new_key_goes_after_the_last_key_of_a_block_value() -> None:
    """`tags` is last and written in flow style; here it is in block style."""
    src = FRONTMATTER_SRC.replace(
        "tags: [rio, geografia]\n", "tags:\n  - rio\n  - geografia\n"
    )
    target = load(src).model_copy(update={"author": "Ana Souza"})
    out = sync_question(src, target)

    out_lines = lines_of(out)
    close = out_lines.index("---", 1)
    assert yaml.safe_load(out_lines[close - 1]) == {"author": "Ana Souza"}
    assert out_lines[close - 3 : close - 1] == ["  - rio", "  - geografia"]
    assert_law1(out, target)


#
# Front matter: comment
#
def test_a_changed_comment_rewrites_only_the_comment_lines() -> None:
    target = load(FRONTMATTER_SRC).model_copy(
        update={"comment": "Hidrografia do Brasil."}
    )
    out = sync_question(FRONTMATTER_SRC, target)

    assert changes(FRONTMATTER_SRC, out) == [
        (["# Rios brasileiros."], ["# Hidrografia do Brasil."])
    ]
    assert_law1(out, target)


def test_an_unchanged_comment_is_not_touched() -> None:
    target = load(FRONTMATTER_SRC).model_copy(update={"weight": 4.0})
    out = sync_question(FRONTMATTER_SRC, target)

    assert lines_of(out)[:2] == ["---", "# Rios brasileiros."]
    assert len(changes(FRONTMATTER_SRC, out)) == 1


#
# No front matter
#
def test_a_new_field_creates_the_frontmatter_block() -> None:
    target = load(BARE_SRC).model_copy(update={"title": "Rios do Brasil"})
    out = sync_question(BARE_SRC, target)

    assert out.endswith(BARE_SRC)
    header = out[: -len(BARE_SRC)]
    assert header.strip().splitlines() == ["---", "title: Rios do Brasil", "---"]
    assert_law1(out, target)


#
# Fields with more than one origin
#
INLINE_ID_SRC = """\
[rio-amazonas] Qual é o maior rio do Brasil em volume de água?

* [*] Amazonas
* [ ] Tocantins
"""

FRONTMATTER_ID_SRC = """\
---
id: rio-amazonas
title: Rios do Brasil
---
Qual é o maior rio do Brasil em volume de água?

* [*] Amazonas
* [ ] Tocantins
"""

BOTH_IDS_SRC = """\
---
id: rio-amazonas
title: Rios do Brasil
---
[rio-amazonas] Qual é o maior rio do Brasil em volume de água?

* [*] Amazonas
* [ ] Tocantins
"""


def test_the_id_is_updated_in_both_places_when_it_is_in_both() -> None:
    target = load(BOTH_IDS_SRC).model_copy(update={"id": "maior-rio"})
    out = sync_question(BOTH_IDS_SRC, target)

    assert "rio-amazonas" not in out
    assert changes(BOTH_IDS_SRC, out) == [
        (["id: rio-amazonas"], ["id: maior-rio"]),
        (
            ["[rio-amazonas] Qual é o maior rio do Brasil em volume de água?"],
            ["[maior-rio] Qual é o maior rio do Brasil em volume de água?"],
        ),
    ]
    assert_law1(out, target)


def test_the_id_is_updated_only_inline_when_it_is_only_inline() -> None:
    target = load(INLINE_ID_SRC).model_copy(update={"id": "maior-rio"})
    out = sync_question(INLINE_ID_SRC, target)

    assert out == INLINE_ID_SRC.replace("rio-amazonas", "maior-rio")
    assert_law1(out, target)


def test_the_id_is_updated_only_in_the_frontmatter_when_it_is_only_there() -> None:
    target = load(FRONTMATTER_ID_SRC).model_copy(update={"id": "maior-rio"})
    out = sync_question(FRONTMATTER_ID_SRC, target)

    assert changes(FRONTMATTER_ID_SRC, out) == [
        (["id: rio-amazonas"], ["id: maior-rio"])
    ]
    assert_law1(out, target)


NUMERIC_SRC = """\
Qual é a aceleração da gravidade na superfície da Terra?

[numeric(m/s²)]: 9.81 +- 0.05
"""


def test_numeric_domain_and_places_equal_to_the_inferred_are_not_written() -> None:
    q = load(NUMERIC_SRC)
    assert isinstance(q, models.NumericQuestion)
    assert (q.domain, q.decimal_places) == ("decimal", 2)

    target = q.model_copy(update={"title": "Gravidade"})
    out = sync_question(NUMERIC_SRC, target)

    assert out.endswith(NUMERIC_SRC)
    header = out[: -len(NUMERIC_SRC)]
    assert header.strip().splitlines() == ["---", "title: Gravidade", "---"]
    assert_law1(out, target)


def test_numeric_unchanged_inferred_values_stay_out_after_a_body_change() -> None:
    q = load(NUMERIC_SRC)
    target = q.model_copy(update={"answer": 9.8, "decimal_places": 2})
    out = sync_question(NUMERIC_SRC, target)

    assert "domain" not in out
    assert "decimalPlaces" not in out
    assert not out.startswith("---")
    assert_law1(out, target)


def test_numeric_domain_that_diverges_from_the_inferred_is_materialized() -> None:
    src = "Quantos estados tem o Brasil?\n\n[numeric]: 27\n"
    q = load(src)
    assert isinstance(q, models.NumericQuestion)
    assert q.domain == "integer"

    target = q.model_copy(update={"domain": "decimal", "decimal_places": 0})
    out = sync_question(src, target)

    assert out.endswith(src)
    header = yaml.safe_load(out[: -len(src)].strip().strip("-"))
    assert header["domain"] == "decimal"
    assert_law1(out, target)


def test_numeric_places_that_diverge_from_the_inferred_are_materialized() -> None:
    q = load(NUMERIC_SRC)
    target = q.model_copy(update={"decimal_places": 3})
    out = sync_question(NUMERIC_SRC, target)

    assert out.endswith(NUMERIC_SRC)
    header = yaml.safe_load(out[: -len(NUMERIC_SRC)].strip().strip("-"))
    assert header == {"decimalPlaces": 3}
    assert_law1(out, target)


FILL_IN_SRC = """\
---
title: Picos do Brasil
domain:
  bandeira: decimal
decimalPlaces:
  neblina: 3
---

O Pico da Bandeira tem [^bandeira] metros e o Pico da Neblina tem [^neblina] metros.

[^bandeira/numeric(m)]: 2892.25 +- 5

[^neblina/numeric(m)]: 2995.4 +- 5
"""


def _blank(question: models.Question, blank_id: str) -> models.NumericBlank:
    assert isinstance(question, models.FillInQuestion)
    [blank] = [b for b in question.blanks if b.id == blank_id]
    assert isinstance(blank, models.NumericBlank)
    return blank


def _with_blank(
    question: models.Question, blank: models.NumericBlank
) -> models.Question:
    assert isinstance(question, models.FillInQuestion)
    blanks = [blank if b.id == blank.id else b for b in question.blanks]
    return question.model_copy(update={"blanks": blanks})


def test_fill_in_blank_keeps_its_map_origin_when_the_value_changes() -> None:
    """`neblina` declares its places in the map: the map line changes."""
    q = load(FILL_IN_SRC)
    neblina = _blank(q, "neblina").model_copy(update={"decimal_places": 2})
    target = _with_blank(q, neblina)
    out = sync_question(FILL_IN_SRC, target)

    assert changes(FILL_IN_SRC, out) == [(["  neblina: 3"], ["  neblina: 2"])]
    assert_law1(out, target)


def test_fill_in_blank_keeps_its_definition_origin_when_the_value_changes() -> None:
    """`bandeira` infers its places from the definition: no map entry appears."""
    q = load(FILL_IN_SRC)
    bandeira = _blank(q, "bandeira").model_copy(
        update={"answer": 2892.5, "decimal_places": 1}
    )
    target = _with_blank(q, bandeira)
    out = sync_question(FILL_IN_SRC, target)

    assert frontmatter_of(out) == frontmatter_of(FILL_IN_SRC)
    assert "2892.5" in out
    assert_law1(out, target)


#
# Ids derived by `ids="fill"`
#
def _choices(question: models.Question) -> list[models.ScoredChoice]:
    assert isinstance(
        question, models.MultipleChoiceQuestion | models.MultipleSelectionQuestion
    )
    return list(question.choices)


def test_derived_choice_ids_are_not_written() -> None:
    assert all(c.id is None for c in _choices(parse(FRONTMATTER_SRC, ids="keep")))
    target = load(FRONTMATTER_SRC)
    assert all(c.id is not None for c in _choices(target))

    out = sync_question(FRONTMATTER_SRC, target.model_copy(update={"weight": 4.0}))

    assert all(c.id is None for c in _choices(parse(out, ids="keep")))
    assert len(changes(FRONTMATTER_SRC, out)) == 1


def test_explicit_choice_ids_are_written() -> None:
    q = load(BARE_SRC)
    choices = [
        c.model_copy(update={"id": f"rio-{i}"}) for i, c in enumerate(_choices(q))
    ]
    target = q.model_copy(update={"choices": choices})
    out = sync_question(BARE_SRC, target)

    assert [c.id for c in _choices(parse(out, ids="keep"))] == ["rio-0", "rio-1"]
    assert_law1(out, target)


#
# Forced type
#
FORCED_TYPE_SRC = """\
---
type: multiple-choice
title: Rios
---
Qual destes rios nasce na Serra da Canastra?

* [ ] Amazonas
* [ ] São Francisco
"""


def test_a_forced_type_survives_a_change_of_another_field() -> None:
    q = load(FORCED_TYPE_SRC)
    assert q.type == "multiple-choice"

    target = q.model_copy(update={"title": "Rios do Brasil"})
    out = sync_question(FORCED_TYPE_SRC, target)

    assert "type: multiple-choice\n" in out
    assert parse(out, ids="fill").type == "multiple-choice"
    assert len(changes(FORCED_TYPE_SRC, out)) == 1
    assert_law1(out, target)


def test_a_forced_type_survives_a_body_change() -> None:
    q = load(FORCED_TYPE_SRC)
    target = q.model_copy(update={"stem": "Qual rio nasce em Minas Gerais?"})
    out = sync_question(FORCED_TYPE_SRC, target)

    assert "type: multiple-choice\n" in out
    assert parse(out, ids="fill").type == "multiple-choice"
    assert_law1(out, target)


#
# Errors
#
def test_a_target_the_markdown_cannot_express_raises_sync_error() -> None:
    """
    A comment with a line break is written as two `#` lines and read back
    as one line joined by a space: no markdown gives the target.
    """
    target = load(FRONTMATTER_SRC).model_copy(update={"comment": "linha 1\nlinha 2"})

    with pytest.raises(SyncError):
        sync_question(FRONTMATTER_SRC, target)


def test_sync_error_is_an_mdq_error() -> None:
    from mdq.errors import MdqError

    assert issubclass(SyncError, MdqError)


def test_sync_question_does_not_mutate_its_inputs() -> None:
    target = load(FRONTMATTER_SRC).model_copy(update={"weight": 3.5})
    before = target.to_dict()
    sync_question(FRONTMATTER_SRC, target)

    assert target.to_dict() == before

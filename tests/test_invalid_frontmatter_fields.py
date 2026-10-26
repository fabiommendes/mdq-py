"""
Tests for the `invalid-frontmatter-field` error
(docs/question-types/question-base.md, "Frontmatter").

A Markdown frontmatter may hold only the fields of its frontmatter table.
When a caller passes a `warnings` sink, the parser appends one error
`Diagnostic` per other key (a body field or an unknown key) -- for
questions, exams, and question blocks inside exams -- and `load` returns
no document.

`mdq/hypothesis/frontmatter.py` holds the documented known-key lists
(transcribed from docs/question-types/*.md and docs/exam.md), so the
Hypothesis properties below exercise the spec, not the parser's own
notion of what it knows.
"""

from __future__ import annotations

import json

from pathlib import Path

import pytest
from hypothesis import given
from typer.testing import CliRunner

from mdq import load
from mdq.cli import app
from strategies import frontmatter as st_frontmatter
from mdq._diagnostics import Diagnostic
from mdq._parser import parse_exam, parse_question
from _corpus import VALID_SOURCES, relative_id
from _parse import parse_any

runner = CliRunner()


def _rules(warnings: list[Diagnostic]) -> list[str]:
    return [w.code for w in warnings]


#
# Drift guard: real, valid documents never trigger a false positive.
#
@pytest.mark.parametrize(
    "path", VALID_SOURCES, ids=[relative_id(p) for p in VALID_SOURCES]
)
def test_every_frontmatter_key_used_by_a_valid_example_is_known(path: Path) -> None:
    """
    Every key actually used in examples/valid/** is, by construction, a
    key the parser must recognize -- so none of them should ever produce
    an `invalid-frontmatter-field` error. A drift between the parser's
    known-key set and reality would show up here first.
    """
    lint_json = path.with_name(path.name.removesuffix(".mdq.md") + ".lint.json")
    pinned = json.loads(lint_json.read_text(encoding="utf-8")) if lint_json.exists() else []
    if any(entry["code"] == "invalid-frontmatter-field" for entry in pinned):
        pytest.skip("this example pins the error on purpose")
    warnings: list[Diagnostic] = []
    text = path.read_text(encoding="utf-8")
    parse_any(text, warnings=warnings)
    assert "invalid-frontmatter-field" not in _rules(warnings)


#
# Focused example: the path of a key in a later question block of an exam.
#
def test_unknown_key_in_the_second_block_of_an_exam_has_a_questions_path() -> None:
    warnings: list[Diagnostic] = []
    parse_exam(
        "# Exam\n\n"
        "===\n\nFirst question.\n\n[essay]\n\n"
        "===\n\n---\nauther: Ada Lovelace\n---\n\n"
        "Second question.\n\n[essay]\n",
        warnings=warnings,
    )
    assert _rules(warnings) == ["invalid-frontmatter-field"]
    assert warnings[0].path == ("questions", 1, "auther")


def test_parsing_without_a_warnings_sink_stays_silent_and_drops_the_key() -> None:
    """Without `warnings`, behaviour is unchanged: no crash, key still gone."""
    doc = parse_question("---\nauther: Ada Lovelace\n---\n\nExplain X.\n\n[essay]\n")
    assert "auther" not in doc


#
# Hypothesis: unknown key names, known key names.
#
@given(key=st_frontmatter.unknown_keys(st_frontmatter.known_question_keys("essay")))
def test_arbitrary_unknown_key_on_a_question_is_reported_exactly_once(key: str) -> None:
    warnings: list[Diagnostic] = []
    parse_question(
        f"---\n{key}: some value\n---\n\nExplain X.\n\n[essay]\n",
        warnings=warnings,
    )
    assert _rules(warnings) == ["invalid-frontmatter-field"]
    assert warnings[0].path == (key,)


@given(
    key=st_frontmatter.unknown_keys(st_frontmatter.EXAM_KEYS),
)
def test_arbitrary_unknown_key_on_an_exam_is_reported_exactly_once(key: str) -> None:
    warnings: list[Diagnostic] = []
    parse_exam(
        f"---\n{key}: some value\n---\n\n# Exam\n\n===\n\nExplain X.\n\n[essay]\n",
        warnings=warnings,
    )
    assert _rules(warnings) == ["invalid-frontmatter-field"]
    assert warnings[0].path == (key,)


#
# Body fields, and load.
#
@pytest.mark.parametrize(
    ("source", "key", "hint"),
    [
        (
            "---\nstem: Qual é a capital?\n---\n\nQual é a capital?\n\n[short-answer]: Brasília\n",
            "stem",
            "text before the body",
        ),
        (
            "---\naccept: [Brasília]\n---\n\nQual é a capital?\n\n[short-answer]: Brasília\n",
            "accept",
            "[short-answer]",
        ),
        (
            "---\nunit: kg\n---\n\nQual é a massa de uma saca de café?\n\n[numeric]: 60\n",
            "unit",
            "[numeric(unit)]",
        ),
        (
            "---\nchoices: []\n---\n\nQual é o maior bioma?\n\n* [*] Amazônia\n* [ ] Pampa\n",
            "choices",
            "list",
        ),
    ],
)
def test_a_body_field_in_the_frontmatter_is_an_error_that_shows_the_body_syntax(
    source: str, key: str, hint: str
) -> None:
    loaded = load(source, format="mdq")
    assert loaded.document is None
    [d] = [d for d in loaded.diagnostics if d.code == "invalid-frontmatter-field"]
    assert (d.severity, d.path) == ("error", (key,))
    assert "body" in d.message and hint in d.message


def test_an_unknown_key_message_does_not_claim_a_body_field() -> None:
    loaded = load("---\nauther: Ada\n---\n\nExplain X.\n\n[essay]\n", format="mdq")
    [d] = loaded.diagnostics
    assert "body" not in d.message


#
# CLI, end to end.
#
def test_cli_validate_reports_an_invalid_frontmatter_field_and_fails(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "typo.mdq.md"
    doc.write_text(
        "---\nauther: Ada Lovelace\n---\n\nExplain X.\n\n[essay]\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["validate", str(doc)])
    assert result.exit_code == 1
    assert "auther" in result.output


#
# Drift guard: the documented key lists agree with the bundled schemas.
#
@pytest.mark.parametrize("question_type", sorted(st_frontmatter.TYPE_QUESTION_KEYS))
def test_documented_keys_are_the_properties_of_the_bundled_frontmatter_schema(
    question_type: str,
) -> None:
    from _corpus import load_schema_bundle

    schema = load_schema_bundle()["$defs"][f"frontmatter-{question_type}"]
    assert set(schema["properties"]) == set(st_frontmatter.known_question_keys(question_type))


def test_documented_exam_keys_are_the_properties_of_the_bundled_frontmatter_schema() -> None:
    from _corpus import load_schema_bundle

    schema = load_schema_bundle()["$defs"]["frontmatter-exam"]
    assert set(schema["properties"]) == set(st_frontmatter.EXAM_KEYS)


def test_unknown_key_on_a_question_is_an_error_with_its_path() -> None:
    warnings: list[Diagnostic] = []
    parse_question(
        "---\nauther: Ada Lovelace\n---\n\nExplain X.\n\n[essay]\n",
        warnings=warnings,
    )
    assert _rules(warnings) == ["invalid-frontmatter-field"]
    assert warnings[0].severity == "error"
    assert warnings[0].path == ("auther",)
    assert "auther" in warnings[0].message


@pytest.mark.parametrize("slug", ["saca", "Q1"])
def test_id_in_the_frontmatter_and_as_a_slug_is_redundant(slug: str) -> None:
    source = f"---\nid: saca\n---\n\n[{slug}] Massa de uma saca de café?\n\n[numeric]: 60\n"
    loaded = load(source, format="mdq")
    [d] = [d for d in loaded.diagnostics if d.code == "redundant-id"]
    assert (d.severity, d.path) == ("warning", ("id",))
    assert loaded.document is not None and loaded.document.id == "saca"
    assert ("wins" in d.message) == (slug != "saca")

"""
Tests for the `unknown-frontmatter-key` lint rule (see
`dev/specs/to-do/unknown-frontmatter-keys.md`).

The parser silently dropped frontmatter keys it didn't recognize
(questions, exams, and question blocks inside exams). This rule makes
that visible: when a caller passes a `warnings` sink, the parser appends
one `Diagnostic` per unknown key it drops -- parsing itself never fails
because of them.

`mdq/hypothesis/frontmatter.py` holds the documented known-key lists
(transcribed from docs/question-types/*.md and docs/exam.md), so the
Hypothesis properties below exercise the spec, not the parser's own
notion of what it knows.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from typer.testing import CliRunner

from mdq.cli import app
from mdq.hypothesis import frontmatter as st_frontmatter
from mdq._diagnostics import Diagnostic
from mdq.loaders import FileLoader
from mdq.parser import parse_any, parse_exam, parse_question
from mdq.testing import VALID_SOURCES, relative_id

runner = CliRunner()

#: A schema-valid value for each of `COMMON_QUESTION_KEYS`, written as it
#: would appear on the right-hand side of `key: <value>` in a frontmatter
#: YAML mapping.
_VALUE_FOR_COMMON_KEY: dict[str, str] = {
    "type": "essay",
    "title": "A title",
    "id": "q-1",
    "uuid": "11111111-1111-4111-8111-111111111111",
    "tags": "[intro]",
    "author": "Ada Lovelace",
    "locale": "en",
    "meta": "{}",
    "weight": "2",
}


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
    an `unknown-frontmatter-key` warning. A drift between the parser's
    known-key set and reality would show up here first.
    """
    warnings: list[Diagnostic] = []
    text = path.read_text(encoding="utf-8")
    parse_any(text, loader=FileLoader(path.parent), warnings=warnings)
    assert _rules(warnings) == []


#
# Focused examples: one per path shape the rule must produce.
#
def test_unknown_key_on_a_question_warns_with_its_path() -> None:
    warnings: list[Diagnostic] = []
    parse_question(
        "---\nauther: Ada Lovelace\n---\n\nExplain X.\n\n[essay]\n",
        warnings=warnings,
    )
    assert _rules(warnings) == ["unknown-frontmatter-key"]
    assert warnings[0].path == ("auther",)
    assert "auther" in warnings[0].message


def test_unknown_key_on_an_exam_warns_with_its_path() -> None:
    warnings: list[Diagnostic] = []
    parse_exam(
        "---\nfoo: bar\n---\n\n# Exam\n\n===\n\nExplain X.\n\n[essay]\n",
        warnings=warnings,
    )
    assert _rules(warnings) == ["unknown-frontmatter-key"]
    assert warnings[0].path == ("foo",)


def test_unknown_key_in_the_second_block_of_an_exam_has_a_questions_path() -> None:
    warnings: list[Diagnostic] = []
    parse_exam(
        "# Exam\n\n"
        "===\n\nFirst question.\n\n[essay]\n\n"
        "===\n\n---\nauther: Ada Lovelace\n---\n\n"
        "Second question.\n\n[essay]\n",
        warnings=warnings,
    )
    assert _rules(warnings) == ["unknown-frontmatter-key"]
    assert warnings[0].path == ("questions", 1, "auther")


def test_known_exam_block_key_include_does_not_warn() -> None:
    warnings: list[Diagnostic] = []
    parse_exam(
        "# Exam\n\n---\ninclude: recursion-01\n---\n",
        warnings=warnings,
    )
    assert _rules(warnings) == []


def test_parsing_without_a_warnings_sink_stays_silent_and_drops_the_key() -> None:
    """Without `warnings`, behaviour is unchanged: no crash, key still gone."""
    doc = parse_question("---\nauther: Ada Lovelace\n---\n\nExplain X.\n\n[essay]\n")
    assert "auther" not in doc


#
# Hypothesis: unknown key names, known key names.
#
@given(key=st_frontmatter.unknown_keys(st_frontmatter.known_question_keys("essay")))
def test_arbitrary_unknown_key_on_a_question_warns_exactly_once(key: str) -> None:
    warnings: list[Diagnostic] = []
    parse_question(
        f"---\n{key}: some value\n---\n\nExplain X.\n\n[essay]\n",
        warnings=warnings,
    )
    assert _rules(warnings) == ["unknown-frontmatter-key"]
    assert warnings[0].path == (key,)


@given(
    key=st_frontmatter.unknown_keys(st_frontmatter.EXAM_KEYS),
)
def test_arbitrary_unknown_key_on_an_exam_warns_exactly_once(key: str) -> None:
    warnings: list[Diagnostic] = []
    parse_exam(
        f"---\n{key}: some value\n---\n\n# Exam\n\n===\n\nExplain X.\n\n[essay]\n",
        warnings=warnings,
    )
    assert _rules(warnings) == ["unknown-frontmatter-key"]
    assert warnings[0].path == (key,)


@given(key=st.sampled_from(st_frontmatter.COMMON_QUESTION_KEYS))
def test_known_common_question_keys_never_warn(key: str) -> None:
    warnings: list[Diagnostic] = []
    value = _VALUE_FOR_COMMON_KEY[key]
    parse_question(
        f"---\n{key}: {value}\n---\n\nExplain X.\n\n[essay]\n",
        warnings=warnings,
    )
    assert _rules(warnings) == []


#
# CLI, end to end.
#
def test_cli_validate_reports_an_unknown_frontmatter_key_and_still_exits_ok(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "typo.mdq.md"
    doc.write_text(
        "---\nauther: Ada Lovelace\n---\n\nExplain X.\n\n[essay]\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["validate", str(doc)])
    assert result.exit_code == 0
    assert "auther" in result.output

"""
The code question type (docs/question-types/code.md) beyond what the corpus
holds: the resolution step, the rules that need the text of a linked source,
the runner report, the exam entry point, the serialization and the CLI.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from pydantic import ValidationError
from rich.console import Console
from typer.testing import CliRunner

import mdq
from mdq import models
from mdq.cli import _show as show_mod
from mdq.cli import app
from mdq.errors import NotAutoGradable, ReportError, ResponseError, UnresolvedTestSource

TESTS = "def test_a(): ...\n\n# mdq: [+3] Caso difícil\ndef test_b(): ...\n"


def _question(**fields: Any) -> models.CodeQuestion:
    doc = {"type": "code", "id": "q", "stem": "Escreva `f`.", **fields}
    loaded = mdq.load(doc, kind="question")
    assert loaded.document is not None, loaded.diagnostics
    assert isinstance(loaded.document, models.CodeQuestion)
    return loaded.document


def _linked(**fields: Any) -> models.CodeQuestion:
    return _question(tests=[{"format": "py", "origin": "t.py"}], **fields)


#
# Resolution
#
def test_resolve_fills_the_text_and_keeps_the_origin() -> None:
    question = _linked()
    resolved = question.resolve({"t.py": TESTS})
    assert resolved.tests is not None
    assert resolved.tests[0].text == TESTS
    assert resolved.tests[0].origin == "t.py"
    assert question.tests is not None and question.tests[0].text is None  # a copy
    assert resolved.resolved and not question.resolved


def test_resolve_removes_a_leading_byte_order_mark_before_counting_lines() -> None:
    resolved = _linked().resolve({"t.py": "﻿# mdq: [+1] A\ndef test_a(): ...\n"})
    assert resolved.tests is not None
    assert resolved.tests[0].text.startswith("# mdq")  # type: ignore[union-attr]  # text is set by resolve
    assert resolved.full_rubric()[0].line == 1


def test_resolve_ignores_missing_and_unused_keys_and_fills_the_rest_later() -> None:
    question = _question(
        tests=[
            {"format": "py", "origin": "a.py"},
            {"format": "py", "origin": "b.py"},
            {"format": "py", "origin": "a.py"},
        ]
    )
    first = question.resolve({"a.py": "x\n", "unused.py": "y\n"})
    assert first.tests is not None
    assert [s.text for s in first.tests] == ["x\n", None, "x\n"]
    second = first.resolve({"b.py": "z\n", "a.py": "other\n"})
    assert second.tests is not None
    assert [s.text for s in second.tests] == ["x\n", "z\n", "x\n"]  # a text is not replaced


def test_the_origin_is_an_opaque_key() -> None:
    resolved = _linked().resolve({"./t.py": TESTS})
    assert not resolved.resolved


def test_resolve_reports_the_annotation_errors_of_the_text() -> None:
    with pytest.raises(ValidationError) as info:
        _linked().resolve({"t.py": "# mdq: [ 3 ] x\ndef test_a(): ...\n"})
    assert info.value.errors()[0]["type"] == "invalid-rubric-item"
    assert info.value.errors()[0]["loc"] == ("text",)


def test_operations_that_need_the_text_fail_on_an_unresolved_source() -> None:
    question = _linked(answerKey="```py\nx\n```")
    for operation in (
        question.public,
        question.full_rubric,
        lambda: question.score_response("", report={"status": "completed", "cases": []}),
    ):
        with pytest.raises(UnresolvedTestSource):
            operation()


def test_lint_needs_the_text_of_every_source() -> None:
    unresolved = _linked(rubric=[{"binding": "manual", "value": -1, "text": "x"}])
    assert "rubric-without-positive-item" not in {d.code for d in unresolved.lint()}
    resolved = unresolved.resolve({"t.py": "# mdq: [0] A\ndef test_a(): ...\n"})
    assert "rubric-without-positive-item" in {d.code for d in resolved.lint()}


def test_automation_does_not_need_the_text() -> None:
    assert _linked().automation == "automatic"
    assert _linked(rubric=[{"binding": "manual", "text": "x"}]).automation == "semi-automatic"
    assert _question(rubric=[{"binding": "manual", "text": "x"}]).automation == "manual"


#
# Grading
#
def _graded() -> models.CodeQuestion:
    return _question(tests=[{"format": "pytest", "text": TESTS}])


def _report(**fields: Any) -> dict[str, Any]:
    return {"status": "completed", "cases": [{"source": 0, "line": 1, "verdict": "pass"}], **fields}


@pytest.mark.parametrize(
    "report",
    [
        _report(version=True),
        _report(version="1"),
        _report(status="done"),
        _report(extra=1),
        _report(cases=[{"source": "0", "line": 1, "verdict": "pass"}]),
        _report(cases=[{"source": 0, "line": 0, "verdict": "pass"}]),
        _report(cases=[{"source": 0, "line": 1, "verdict": "ok"}]),
        _report(cases=[{"source": 0, "line": 1, "verdict": "pass", "duration": -1}]),
        _report(hashes={"submission": "abc"}),
        _report(runner={"version": "1"}),
        {"status": "completed"},
    ],
)
def test_an_invalid_report_is_a_report_error(report: dict[str, Any]) -> None:
    with pytest.raises(ReportError):
        _graded().score_response("", report=report)


def test_a_report_object_and_a_mapping_grade_the_same() -> None:
    data = _report(runner={"name": "mdq-pytest", "toolchainVersion": "3.13"})
    report = models.RunnerReport.model_validate(data)
    question = _graded()
    assert question.score_response("", report=report).score == question.score_response(
        "", report=data
    ).score


def test_a_response_must_be_a_string() -> None:
    with pytest.raises(ResponseError):
        _graded().score_response(42, report=_report())


def test_score_response_without_a_report_follows_the_checks_of_the_spec() -> None:
    with pytest.raises(ReportError):
        _graded().score_response("")
    with pytest.raises(NotAutoGradable):
        _question(rubric=[{"binding": "manual", "text": "x"}]).score_response("")


def test_manual_scores_must_not_be_booleans() -> None:
    question = _question(rubric=[{"binding": "manual", "text": "x"}])
    with pytest.raises(ValueError):
        question.score_response("", manual=[True])


def test_the_reference_solution_is_the_first_fence_that_is_a_direct_child() -> None:
    question = _question(answerKey="* ```\n  no\n  ```\n\n~~~py\nyes\n~~~\n")
    assert question.reference_solution == "yes\n"
    assert question.correct_responses() == ["yes\n"]


#
# Exam
#
def _exam() -> models.Exam:
    loaded = mdq.load(
        {
            "type": "exam",
            "questions": [
                {"type": "code", "id": "c", "stem": "S", "tests": [{"format": "p", "text": TESTS}]},
                {"type": "essay", "id": "e", "stem": "S"},
            ],
        },
        kind="exam",
    )
    assert loaded.document is not None
    return loaded.document


def test_an_exam_takes_the_reports_by_question_id() -> None:
    result = _exam().score_responses(
        {"c": "x"}, reports={"c": _report(cases=[{"source": 0, "line": 4, "verdict": "pass"}])}
    )
    assert result.questions["c"] is not None
    assert result.questions["c"].score == pytest.approx(1.0)


def test_an_exam_rejects_a_report_for_a_question_that_is_not_code() -> None:
    with pytest.raises(ResponseError):
        _exam().score_responses({"e": "x"}, reports={"e": _report()})


def test_an_exam_leaves_a_pending_code_question_pending() -> None:
    result = _exam().score_responses(
        {"c": "x"}, reports={"c": {"status": "runner-error", "cases": []}}
    )
    assert result.pending == ("c",)


#
# Parser
#
SOURCE = """\
Escreva `f`.

[code]

## [tests]

```pytest
# mdq: [+1] A
def test_a(): ...
```

[link](a.py)

```pytest
x
```

## [rubric]

* [+1] {manual} [Guia][] de estilo
"""


def test_render_round_trips_a_document_with_every_section() -> None:
    question = mdq.parse(SOURCE)
    assert isinstance(question, models.CodeQuestion)
    assert mdq.parse(question.render()) == question


def test_render_uses_a_fence_longer_than_the_backticks_of_the_text() -> None:
    question = _question(tests=[{"format": "md", "text": "```\ninner\n```\n"}])
    again = mdq.parse(question.render())
    assert isinstance(again, models.CodeQuestion)
    assert again.tests is not None and again.tests[0].text == "```\ninner\n```\n"


def test_render_escapes_the_origin() -> None:
    question = _question(tests=[{"format": "py", "origin": "meus testes (1).py"}])
    again = mdq.parse(question.render())
    assert isinstance(again, models.CodeQuestion)
    assert again.tests is not None and again.tests[0].origin == "meus testes (1).py"


def test_a_fenced_source_keeps_crlf_out_of_its_text() -> None:
    question = mdq.parse("S\r\n\r\n[code]\r\n\r\n## [tests]\r\n\r\n```py\r\na\r\nb\r\n```\r\n")
    assert isinstance(question, models.CodeQuestion)
    assert question.tests is not None and question.tests[0].text == "a\nb\n"


def test_a_setext_section_heading_is_a_section() -> None:
    question = mdq.parse("S\n\n[code]\n\nTests\n---\n\n```py\nx\n```\n".replace("Tests", "[tests]"))
    assert isinstance(question, models.CodeQuestion)
    assert question.tests is not None


def test_to_dict_has_no_derived_value() -> None:
    data = mdq.parse(SOURCE).to_dict()
    assert set(data) == {"type", "stem", "tests", "rubric"}


#
# Public form
#
def test_public_form_lists_the_public_regions() -> None:
    question = _question(
        tests=[{"format": "p", "text": "# mdq: [0] {example} E\n\ncode\n\n\n# mdq: [1] H\nhidden\n"}]
    )
    assert question.public()["publicTests"] == [
        {"format": "p", "text": "code", "firstLine": 3, "example": True}
    ]


#
# CLI
#
def test_show_prints_the_full_rubric_and_the_distribution_of_points() -> None:
    question = mdq.parse(SOURCE)
    assert isinstance(question, models.CodeQuestion)
    question = question.resolve({"a.py": "def test_x(): ...\n"})
    buf = io.StringIO()
    show_mod.render_question(question, Console(file=buf, width=100, highlight=False))
    out = buf.getvalue()
    assert "Rubric" in out and "instructor" in out and "tests[0]:1" in out
    assert "tests[1]" in out  # the implicit item
    assert "25%" in out  # 1 of 4 positive points


def test_show_with_an_unresolved_source_says_so() -> None:
    buf = io.StringIO()
    show_mod.render_question(
        mdq.parse(SOURCE), Console(file=buf, width=100, highlight=False)  # type: ignore[arg-type]  # a CodeQuestion
    )
    assert "not resolved" in buf.getvalue()


def test_new_scaffolds_a_valid_code_question(tmp_path: Any) -> None:
    runner = CliRunner()
    for flag in ([], ["--complete"]):
        target = tmp_path / f"code{len(flag)}.mdq.md"
        assert runner.invoke(app, ["new", "code", "-o", str(target), *flag]).exit_code == 0
        loaded = mdq.load(target)
        assert loaded.document is not None, loaded.diagnostics
        assert [d for d in loaded.diagnostics if d.severity != "info"] == []


def test_validate_accepts_a_code_question(tmp_path: Any) -> None:
    target = tmp_path / "q.mdq.md"
    target.write_text(SOURCE, encoding="utf-8")
    assert CliRunner().invoke(app, ["validate", str(target)]).exit_code == 0

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


def _errors(**fields: Any) -> list[tuple[str, tuple[str | int, ...], str]]:
    """The error diagnostics of a code question given as a dict."""
    doc = {"type": "code", "id": "q", "stem": "Escreva `f`.", **fields}
    loaded = mdq.load(doc, kind="question")
    return [(d.code, d.path, d.message) for d in loaded.diagnostics if d.severity == "error"]


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
    assert info.value.errors()[0]["loc"] == ("tests", 0, "text")


def test_resolve_error_names_the_source_by_index() -> None:
    question = _question(
        tests=[{"format": "py", "text": "x\n"}, {"format": "py", "origin": "t.py"}]
    )
    with pytest.raises(ValidationError) as info:
        question.resolve({"t.py": "# mdq: [ 3 ] x\ndef test_a(): ...\n"})
    assert [e["loc"] for e in info.value.errors()] == [("tests", 1, "text")]


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


#
# Review fixes
#
def _doc(body: str) -> str:
    return f"---\nid: q\ntitle: T\n---\nS.\n\n[code]\n\n{body}"


@pytest.mark.parametrize("value", ["0.1", "0.05", "0.07", "1.1"])
@pytest.mark.parametrize("cases", [3, 7, 29])
def test_a_decimal_value_with_every_case_passed_scores_exactly_one(value: str, cases: int) -> None:
    text = f"# mdq: [{value}] a\n" + "t\n" * cases
    question = _question(tests=[{"format": "py", "text": text}])
    report = {
        "status": "completed",
        "cases": [{"source": 0, "line": i + 2, "verdict": "pass"} for i in range(cases)],
    }
    assert question.score_response("x", report=report).score == 1.0


def test_the_template_needs_its_closing_fence() -> None:
    errors = _errors(template="```py\nx")
    assert [e[:2] for e in errors] == [("forbidden-block-element", ("template",))]


@pytest.mark.parametrize("field", ["stem", "epilogue"])
def test_render_closes_a_fence_that_would_swallow_the_next_section(field: str) -> None:
    question = _question(
        **{field: "```py\nx"},
        tests=[{"format": "py", "text": "t\n"}],
        rubric=[{"binding": "manual", "text": "m"}],
    )
    again = mdq.parse(question.render())
    assert isinstance(again, models.CodeQuestion)
    assert again.tests is not None and again.rubric is not None


def test_a_format_with_a_backslash_or_an_entity_round_trips() -> None:
    for fmt in ["a_b", "a\\_b", "a&amp;b", "a\\"]:
        question = _question(tests=[{"format": fmt, "text": "x\n"}])
        again = mdq.parse(question.render())
        assert isinstance(again, models.CodeQuestion)
        assert again.tests is not None and again.tests[0].format == fmt


def test_the_format_of_a_fence_reads_escapes_and_entities() -> None:
    question = mdq.parse(_doc("## [tests]\n\n```py\\_x\nx\n```\n"))
    assert isinstance(question, models.CodeQuestion)
    assert question.tests is not None and question.tests[0].format == "py_x"


@pytest.mark.parametrize("value", [1e-7, 1e16, 2.5, 3.0, -0.0, -1e-7, 5e-324])
def test_a_rubric_value_round_trips_through_markdown(value: float) -> None:
    question = _question(rubric=[{"value": value, "binding": "manual", "text": "a"}])
    again = mdq.parse(question.render())
    assert isinstance(again, models.CodeQuestion)
    assert again.rubric is not None and again.rubric[0].value == value


def test_minus_zero_is_never_negative() -> None:
    import math

    question = mdq.parse(_doc("## [rubric]\n\n* [-0.0] {manual} a\n"))
    assert isinstance(question, models.CodeQuestion)
    assert question.rubric is not None and question.rubric[0].value is not None
    assert math.copysign(1, question.rubric[0].value) == 1


@pytest.mark.parametrize("text", ["a > b", "a ! b", "a b"])
def test_u2028_is_not_a_line_end_in_a_rubric_item_or_a_choice(text: str) -> None:
    question = _question(rubric=[{"binding": "manual", "text": text}])
    again = mdq.parse(question.render())
    assert isinstance(again, models.CodeQuestion)
    assert again.rubric is not None and again.rubric[0].text == text
    assert again.rubric[0].feedback is None and again.rubric[0].comment is None
    choice = mdq.load(
        {
            "type": "multiple-choice",
            "id": "q",
            "stem": "S.",
            "choices": [{"text": text, "score": 1}, {"text": "z"}],
        },
        kind="question",
    ).document
    assert choice is not None
    back = mdq.parse(choice.render())
    assert isinstance(back, models.MultipleChoiceQuestion)
    assert back.choices[0].text == text and back.choices[0].feedback is None


@pytest.mark.parametrize(
    "fmt", ["", "my fmt", "a`b", "a b", "a\tb"],
)
def test_a_format_must_be_a_word(fmt: str) -> None:
    assert [e[:2] for e in _errors(tests=[{"format": fmt, "text": "x\n"}])] == [
        ("schema-error", ("tests", 0, "format"))
    ]


@pytest.mark.parametrize("origin", ["Makefile", "a\nb.py", "a/.", "a.", "dir.d/file"])
def test_an_origin_has_an_extension_and_no_line_break(origin: str) -> None:
    assert [e[:2] for e in _errors(tests=[{"format": "py", "origin": origin}])] == [
        ("schema-error", ("tests", 0, "origin"))
    ]


def test_the_format_is_the_extension_of_the_origin() -> None:
    errors = _errors(tests=[{"format": "pytest", "origin": "t.py"}])
    assert [e[:2] for e in errors] == [("test-format-disagrees-with-origin", ("tests", 0, "format"))]


def test_yaml_to_markdown_to_model_is_the_identity_for_the_valid_code_examples() -> None:
    from _corpus import EXAMPLES_ROOT

    paths = sorted((EXAMPLES_ROOT / "valid" / "code").glob("*.yaml"))
    assert paths
    for path in paths:
        question = mdq.load(path).document
        assert isinstance(question, models.CodeQuestion), path
        # A linked source is written as its link: the text is not kept.
        if any(source.origin for source in question.tests or []):
            continue
        again = mdq.parse(question.render())
        assert again == question, path


def test_a_rubric_item_that_starts_with_another_block_is_a_parse_error() -> None:
    for first in ("# [+1] {manual} a", "> [+1] {manual} a", "```\nx\n```"):
        loaded = mdq.load(_doc(f"## [rubric]\n\n* {first}\n"))
        assert [d.code for d in loaded.diagnostics if d.severity == "error"] == ["parse-error"], first


def test_the_error_of_a_template_points_at_the_extra_block() -> None:
    from mdq._parser import _code

    class Block:
        def __init__(self, type: str) -> None:
            self.type = type

    blocks: list[Any] = [Block("fence"), Block("fence")]
    assert _code._offender(blocks, "fence") is blocks[1]
    blocks = [Block("fence"), Block("paragraph"), Block("fence")]
    assert _code._offender(blocks, "fence") is blocks[1]
    blocks = [Block("paragraph"), Block("fence")]
    assert _code._offender(blocks, "fence") is blocks[0]


@pytest.mark.parametrize("marker", [">", "!"])
def test_a_blank_observation_points_at_its_own_line(marker: str) -> None:
    text = f"# mdq: [+1] a\n# mdq: {marker} ok\n# mdq: [+1] b\n# mdq: {marker}\nx\n"
    errors = _errors(tests=[{"format": "py", "text": text}])
    assert [e[:2] for e in errors] == [("blank-text", ("tests", 0, "text"))]
    assert "line 4" in errors[0][2]


def test_a_manual_item_of_an_unresolved_question_shows_in_the_rubric_table() -> None:
    question = _linked(rubric=[{"value": 2, "binding": "manual", "text": "m"}])
    items = question.model_copy(update={"tests": None}).full_rubric()
    assert [(i.binding, i.value) for i in items] == [("manual", 2)]


def test_setext_section_headings_of_a_code_question_in_an_exam_warn() -> None:
    head = "---\nlocale: pt-BR\n---\n\n# Prova\n\n---\nid: q1\ntitle: A\ntype: code\n---\nS.\n\n[code]\n\n"
    tail = "\n---\nid: q2\ntitle: B\n---\nS2.\n\n[essay]\n"
    sections = {
        "template": "[template]\n-----\n\n```py\nx\n```\n",
        "tests": "[tests]\n---\n\n```py\nx\n```\n",
        "rubric": "[rubric]\n----\n\n* [+1] {manual} M\n",
        "answerKey": "[answer-key]\n-------\n\nk\n",
    }
    for field, body in sections.items():
        loaded = mdq.load(head + body + tail)
        found = [d.path for d in loaded.diagnostics if d.code == "setext-heading"]
        assert found == [("questions", 0, field)], field


#
# Review fixes
#
def test_resolve_reports_the_errors_of_every_source() -> None:
    question = _question(
        tests=[
            {"format": "py", "origin": "a.py"},
            {"format": "py", "origin": "b.py"},
            {"format": "py", "origin": "c.py"},
        ]
    )
    bad = "# mdq: [50%] x\n"
    with pytest.raises(ValidationError) as caught:
        question.resolve({"a.py": bad, "b.py": "ok\n", "c.py": bad})
    locs = [error["loc"] for error in caught.value.errors()]
    assert locs == [("tests", 0, "text"), ("tests", 2, "text")]


def test_a_parse_error_of_a_block_has_the_line_of_the_file() -> None:
    src = (
        "---\nid: q\n---\n\nStem\n\n[code]\n\n## [rubric]\n\n- {manual} x\n\n"
        "## [rubric]\n\n- {manual} y\n"
    )
    loaded = mdq.load(src)
    assert [(d.code, d.line) for d in loaded.diagnostics] == [("parse-error", 13)]


def test_an_invalid_rubric_item_has_the_line_of_the_file() -> None:
    src = "---\nid: q\n---\n\nStem\n\n[code]\n\n## [rubric]\n\n- x\n"
    loaded = mdq.load(src)
    assert [(d.code, d.line, d.path) for d in loaded.diagnostics] == [
        ("invalid-rubric-item", 11, ("rubric", 0))
    ]


def test_a_rubric_value_beyond_a_double_is_invalid() -> None:
    markdown = "Stem\n\n[code]\n\n## [rubric]\n\n- [+" + "9" * 320 + "] {manual} x\n"
    codes = [d.code for d in mdq.load(markdown).diagnostics]
    assert "invalid-rubric-item" in codes
    loaded = mdq.load(
        {
            "type": "code",
            "id": "q",
            "stem": "s",
            "rubric": [{"binding": "manual", "text": "x", "value": 10**400}],
        },
        kind="question",
    )
    assert [(d.code, d.path) for d in loaded.diagnostics][0] == (
        "invalid-rubric-item",
        ("rubric", 0, "value"),
    )


def test_a_rubric_value_above_2_to_the_53_is_the_nearest_double() -> None:
    markdown = "Stem\n\n[code]\n\n## [rubric]\n\n- [+9007199254740993] {manual} x\n"
    value = mdq.load(markdown).document.rubric[0].value  # type: ignore[union-attr]
    assert value == 9007199254740992
    question = _question(
        rubric=[
            {"binding": "manual", "text": "a", "value": 9007199254740993},
            {"binding": "manual", "text": "b", "value": 3},
        ]
    )
    assert question.score_response("x", manual=[0, 1]).score == 3.3306690738754686e-16

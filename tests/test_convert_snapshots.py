"""
Characterization of the converters through the public interface only
(`load_question`, `dump_question`).

Every valid question of the corpus is exported to every format, and the
exported text is imported back. The snapshot of a format,
`tests/snapshots/convert/<format>.json`, holds per question:

* `export`: the exported text, or `{"error": <message>, "code": <code>}`
  if the export fails.
* `import`: `to_dict()` of the question imported from `export`, or the
  error. Absent when the export did not give a text.
* `reexport`: the export of the imported question, or the error, only when
  it is not `export` again. Each one is a known
  bug (dev/issues/converter-round-trip.md).
* `export_diagnostics`, `import_diagnostics`: each diagnostic as
  `"<severity> <code> <path>"`, in the order found, when there is one.

Any change in what a converter writes, reads or rejects changes a
snapshot. Run with `MDQ_UPDATE_SNAPSHOTS=1` to rewrite them after a change
that is intended, and review the diff.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from mdq import load
from mdq._diagnostics import Diagnostic
from mdq.convert import FORMATS, Converted, dump_question, load_question
from mdq.models import Exam, Question
from _corpus import EXAMPLES_ROOT, VALID_EXAMS_DIR, VALID_PARSED

SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "convert"
UPDATE = os.environ.get("MDQ_UPDATE_SNAPSHOTS") == "1"


def _valid_questions() -> list[tuple[str, Question]]:
    questions: list[tuple[str, Question]] = []
    for path in VALID_PARSED:
        if path.is_relative_to(VALID_EXAMS_DIR):
            continue
        document = load(path).document
        if document is not None and not isinstance(document, Exam):
            name = path.relative_to(EXAMPLES_ROOT).as_posix()
            questions.append((name, document))
    return questions


QUESTIONS = _valid_questions()


def _error(converted: Converted[Any]) -> dict[str, str]:
    first = next(d for d in converted.diagnostics if d.severity == "error")
    return {"error": first.message, "code": first.code}


def _lines(diagnostics: list[Diagnostic]) -> list[str]:
    return [
        " ".join([d.severity, d.code, "/".join(str(part) for part in d.path)]).strip()
        for d in diagnostics
    ]


def _convert(question: Question, format: str) -> dict[str, Any]:
    """What the converters do with `question`: see the module docstring."""
    exported = dump_question(question, format=format)
    result: dict[str, Any] = {}
    if exported.diagnostics:
        result["export_diagnostics"] = _lines(exported.diagnostics)
    if exported.value is None:
        return {**result, "export": _error(exported)}
    text = exported.value
    result["export"] = text
    imported = load_question(text, format=format)
    if imported.diagnostics:
        result["import_diagnostics"] = _lines(imported.diagnostics)
    if imported.value is None:
        return {**result, "import": _error(imported)}
    result["import"] = imported.value.to_dict()
    again = dump_question(imported.value, format=format)
    reexport: Any = again.value if again.value is not None else _error(again)
    if reexport != text:
        result["reexport"] = reexport
    return result


def _snapshot(format: str) -> dict[str, Any]:
    return {name: _convert(question, format) for name, question in QUESTIONS}


def test_there_are_questions() -> None:
    assert len(QUESTIONS) > 50


@pytest.mark.parametrize("format", FORMATS)
def test_snapshot(format: str) -> None:
    path = SNAPSHOT_DIR / f"{format}.json"
    actual = _snapshot(format)
    if UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(actual, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(actual) == sorted(expected), "the corpus changed: update the snapshot"
    for name in expected:
        assert actual[name] == expected[name], name

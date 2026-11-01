"""
Characterization of the converters through the public interface only
(`import_question`, `export_question`).

Every valid question of the corpus is exported to every format, and the
exported text is imported back. The snapshot of a format,
`tests/snapshots/convert/<format>.json`, holds per question:

* `export`: the exported text, or `{"error": <message>}` if the export
  fails, or `"unsupported"` if the format does not hold the type.
* `import`: `to_dict()` of the question imported from `export`, or
  `{"error": <message>}`. Absent when the export did not give a text.
* `reexport`: the export of the imported question, or `{"error":
  <message>}`, only when it is not `export` again. Each one is a known
  bug (dev/issues/converter-round-trip.md).

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
from mdq.convert import FORMATS, export_question, import_question
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


def _convert(question: Question, format: str) -> dict[str, Any]:
    """What the converters do with `question`: see the module docstring."""
    try:
        text = export_question(question, format=format)
    except TypeError:
        return {"export": "unsupported"}
    except ValueError as exc:
        return {"export": {"error": str(exc)}}
    try:
        again = import_question(text, format=format)
    except ValueError as exc:
        return {"export": text, "import": {"error": str(exc)}}
    result: dict[str, Any] = {"export": text, "import": again.to_dict()}
    try:
        reexport: Any = export_question(again, format=format)
    except ValueError as exc:
        reexport = {"error": str(exc)}
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

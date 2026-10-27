"""
`examples/valid/exam/*.resolved.yaml`: what an exam with include blocks
becomes once it resolves against the bank in `examples/valid/exam/`
(exam.md, "Include all" and "Question ids").

Each file lists the question ids in order, after `resolve` and
`with_ids`, and the diagnostics `resolve` reports. `max` picks the first
candidates, so the expectation is deterministic. Two optional keys:

* `fields`: a field the questions inherit from the exam (e.g. `locale`) ->
  its value for each question, in order.
* `lint`: every diagnostic of the resolved exam (`Exam.lint()`, before
  `with_ids`), as `{code, severity, path}`; the path of a question starts
  with `questions[i]`.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pytest
import yaml

from mdq import load
from mdq._banks import FileLoader
from mdq.models import Exam, Include, IncludeAll
from _corpus import VALID_EXAMS_DIR, collect_files, collect_sources, relative_id

RESOLVED = sorted(VALID_EXAMS_DIR.glob("*.resolved.yaml"))

#: Every exam document with an include block, by stem.
EXAMS_WITH_INCLUDES: dict[str, Path] = {}
for _path in collect_sources(VALID_EXAMS_DIR) + collect_files(VALID_EXAMS_DIR):
    if _path.parent != VALID_EXAMS_DIR or _path.name.endswith(".resolved.yaml"):
        continue
    _document = load(_path).document
    if isinstance(_document, Exam) and any(
        isinstance(entry, Include | IncludeAll) for entry in _document.questions
    ):
        EXAMS_WITH_INCLUDES.setdefault(_path.name.split(".")[0], _path)


def first(candidates: list[str], max: int | None) -> list[str]:
    return candidates if max is None else candidates[:max]


def _entries(diagnostics: list) -> list[dict]:
    return [{"code": d.code, "severity": d.severity, "path": list(d.path)} for d in diagnostics]


def _resolved(path: Path, fields: list[str]) -> dict:
    warnings: list = []
    exam = load(path).validate().resolve(FileLoader(VALID_EXAMS_DIR), select=first, warnings=warnings)
    lint = _entries(exam.lint())
    filled = exam.with_ids()
    return {
        "questions": [question.id for question in filled.questions],
        "diagnostics": _entries(warnings),
        "fields": {
            field: [getattr(question, field) for question in filled.questions]
            for field in fields
        },
        "lint": lint,
    }


def _multiset(entries: list[dict]) -> Counter:
    return Counter(json.dumps(entry, sort_keys=True) for entry in entries)


def test_there_are_resolved_fixtures() -> None:
    assert RESOLVED


@pytest.mark.parametrize("stem", sorted(EXAMS_WITH_INCLUDES), ids=sorted(EXAMS_WITH_INCLUDES))
def test_every_exam_with_includes_has_a_resolved_fixture(stem: str) -> None:
    assert (VALID_EXAMS_DIR / f"{stem}.resolved.yaml").exists(), (
        f"{stem} has include blocks but no {stem}.resolved.yaml"
    )


@pytest.mark.parametrize("fixture", RESOLVED, ids=[relative_id(p) for p in RESOLVED])
def test_resolved_exam_matches_its_fixture(fixture: Path) -> None:
    stem = fixture.name.removesuffix(".resolved.yaml")
    source = EXAMS_WITH_INCLUDES.get(stem)
    assert source is not None, f"{fixture.name} has no exam document"
    expected = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    actual = _resolved(source, list(expected.get("fields", {})))
    assert actual["questions"] == expected["questions"]
    assert _multiset(actual["diagnostics"]) == _multiset(expected["diagnostics"])
    if "fields" in expected:
        assert actual["fields"] == expected["fields"]
    if "lint" in expected:
        assert _multiset(actual["lint"]) == _multiset(expected["lint"])

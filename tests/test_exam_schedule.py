"""
Exam-level integration of `start`/`duration`: the `Exam` model
round-trip, `mdq.parser.parse_exam` normalization and error reporting,
and the `mdq show` metadata table.

`tests/test_schedule.py` covers `mdq.schedule` in isolation;
`tests/test_exam.py` covers exam parsing in general. This file is only
about the seam between the two: does an `Exam` carrying a schedule
survive `to_dict()` / `model_validate()`, and does the parser wire
`schedule` in correctly.
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta

import pytest
from hypothesis import given
from rich.console import Console

from mdq import load, models, show as show_mod
from mdq.errors import ParseError
from mdq.hypothesis import schedule as st_schedule
from mdq.parser import parse_exam


def _minimal_exam(**kwargs: object) -> models.Exam:
    question = models.EssayQuestion(stem="Explain natural selection.")
    return models.Exam(questions=[question], **kwargs)  # type: ignore[arg-type]


#
# Exam model round trip
#
#: `Exam.__eq__` recurses into each question's `exam` back-reference
#: (a weakref private attribute), which recurses back into the exam --
#: unrelated to `start`/`duration`, but it rules out comparing whole
#: `Exam` instances here. Comparing the schedule fields directly, plus
#: `to_dict()` (a plain dict, no back-references) is equivalent for what
#: this test checks.
@given(st_schedule.starts())
def test_exam_start_round_trips_through_to_dict_and_model_validate(
    value: date | datetime,
) -> None:
    exam = _minimal_exam(start=value)
    data = exam.to_dict()
    loaded = load(data)
    assert loaded, loaded.diagnostics
    round_tripped = models.Exam.model_validate(data)
    assert round_tripped.start == exam.start
    assert round_tripped.to_dict() == data


@given(st_schedule.positive_timedeltas())
def test_exam_duration_round_trips_through_to_dict_and_model_validate(
    value: timedelta,
) -> None:
    exam = _minimal_exam(duration=value)
    data = exam.to_dict()
    loaded = load(data)
    assert loaded, loaded.diagnostics
    round_tripped = models.Exam.model_validate(data)
    assert round_tripped.duration == exam.duration
    assert round_tripped.to_dict() == data


def test_exam_without_a_schedule_has_no_start_or_duration_key() -> None:
    exam = _minimal_exam()
    data = exam.to_dict()
    assert "start" not in data
    assert "duration" not in data


#
# mdq.parser.parse_exam
#
def test_parse_exam_normalizes_an_unquoted_date_only_start() -> None:
    doc = parse_exam("---\nstart: 2026-03-10\n---\n\n# Exam\n")
    assert doc["start"] == "2026-03-10"


def test_parse_exam_normalizes_an_unquoted_offset_datetime_start() -> None:
    doc = parse_exam(
        "---\nstart: 2026-03-10 09:00:00-03:00\n---\n\n# Exam\n"
    )
    assert doc["start"] == "2026-03-10T09:00:00-03:00"


def test_parse_exam_normalizes_an_unquoted_hh_mm_duration() -> None:
    """1:30, unquoted, must survive as the string '1:30', not the YAML
    1.1 base-60 integer 90 -- see docs/exam.md."""
    doc = parse_exam("---\nduration: 1:30\n---\n\n# Exam\n")
    assert doc["duration"] == "PT1H30M"


def test_parse_exam_normalizes_a_shorthand_duration() -> None:
    doc = parse_exam("---\nduration: 90m\n---\n\n# Exam\n")
    assert doc["duration"] == "PT1H30M"


def test_parse_exam_raises_parse_error_naming_the_field_for_a_bad_start() -> None:
    with pytest.raises(ParseError) as excinfo:
        parse_exam("---\nstart: 10/03/2026\n---\n\n# Exam\n")
    assert "start" in str(excinfo.value)
    assert "10/03/2026" in str(excinfo.value)


def test_parse_exam_raises_parse_error_naming_the_field_for_a_bad_duration() -> None:
    with pytest.raises(ParseError) as excinfo:
        parse_exam("---\nduration: P1M\n---\n\n# Exam\n")
    assert "duration" in str(excinfo.value)
    assert "P1M" in str(excinfo.value)


def test_frontmatter_yaml_keeps_hh_mm_like_values_as_strings() -> None:
    """
    Regression for PyYAML 1.1's sexagesimal int resolver: any frontmatter
    field written as `H:MM` must stay a string, not become a base-60
    int, even outside the exam schedule fields.
    """
    doc = parse_exam(
        '---\ntitle: "1:30"\n---\n\n# Exam\n===\n\nExplain.\n\n[essay]\n'
    )
    assert doc["title"] == "1:30"


#
# mdq show
#
def test_show_exam_renders_start_and_duration_rows() -> None:
    src = (
        "---\nstart: 2026-03-10T09:00:00-03:00\nduration: PT2H30M\n---\n\n"
        "# Exam\n\n===\n\nExplain.\n\n[essay]\n"
    )
    buf = io.StringIO()
    console = Console(file=buf, width=100, highlight=False)
    show_mod.show_source(src, console, show_answer_key=True)
    shown = buf.getvalue()
    assert "Start" in shown
    assert "2026-03-10T09:00:00-03:00" in shown
    assert "Duration" in shown
    assert "PT2H30M" in shown

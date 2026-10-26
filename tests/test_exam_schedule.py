"""
Exam-level integration of `start`/`duration`: the `Exam` model
round-trip and the `mdq show` metadata table. Parsing of the schedule
fields is covered by the corpus (`examples/valid/exam/start-*`,
`duration-*`).

`tests/test_schedule.py` covers `mdq._schedule` in isolation;
`tests/test_exam.py` covers exam parsing in general. This file is only
about the seam between the two: does an `Exam` carrying a schedule
survive `to_dict()` / `model_validate()`.
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta

from hypothesis import given
from rich.console import Console

from mdq import load, models
from mdq.cli import _show as show_mod
from strategies import schedule as st_schedule


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
    assert "start" in shown
    assert "2026-03-10T09:00:00-03:00" in shown
    assert "duration" in shown
    assert "PT2H30M" in shown

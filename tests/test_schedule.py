"""
`mdq._schedule`: parsing and canonicalizing an exam's `start` and
`duration` fields (docs/exam.md § "Duration and Start Time",
schema/exam.yaml).

Property tests use the strategies in `strategies.schedule`, built
directly from the spec's grammar and canonicalization rules rather than
from `mdq._schedule` itself. The rejections (bare numbers, the empty
start) are invalid corpus examples: `exam-duration-bare-*`,
`exam-start-empty-string`.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from hypothesis import given

from mdq import _schedule
from strategies import schedule as st_schedule

#: Copied verbatim from schema/exam.yaml so a drift between the schema
#: and this test suite is caught, not silently tolerated.
START_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"(T[0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]+)?)?(Z|[+-][0-9]{2}:[0-9]{2})?)?$"
)
DURATION_PATTERN = re.compile(
    r"^P(?!$)([0-9]+W)?([0-9]+D)?"
    r"(T(?=[0-9])([0-9]+H)?([0-9]+M)?([0-9]+(\.[0-9]+)?S)?)?$"
)


#
# Duration: round trips
#
@given(st_schedule.positive_timedeltas())
def test_parse_duration_undoes_format_duration(td: timedelta) -> None:
    assert _schedule.parse_duration(_schedule.format_duration(td)) == td


@given(st_schedule.canonical_durations())
def test_format_duration_undoes_parse_duration_for_canonical_strings(
    pair: tuple[str, timedelta],
) -> None:
    text, _expected = pair
    assert _schedule.format_duration(_schedule.parse_duration(text)) == text


@given(st_schedule.canonical_durations())
def test_parse_duration_reads_a_canonical_string_to_its_timedelta(
    pair: tuple[str, timedelta],
) -> None:
    text, expected = pair
    assert _schedule.parse_duration(text) == expected


@given(st_schedule.shorthand_duration_strings())
def test_parse_duration_reads_every_surface_form_to_its_timedelta(
    pair: tuple[str, timedelta],
) -> None:
    text, expected = pair
    assert _schedule.parse_duration(text) == expected


@given(st_schedule.xd_yh_zm_strings())
def test_xd_yh_zm_equals_the_iso_form_built_from_the_same_numbers(
    pair: tuple[str, timedelta],
) -> None:
    """Every `Xd Yh Zm` shorthand equals the ISO form built from the same numbers."""
    text, expected = pair
    days, seconds, _ = expected.days, expected.seconds, expected.microseconds
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    iso = "P" + (f"{days}D" if days else "") + "T" + f"{hours}H{minutes}M"
    assert _schedule.parse_duration(text) == _schedule.parse_duration(iso)


@given(st_schedule.hh_mm_strings())
def test_hh_mm_equals_the_iso_form_built_from_the_same_numbers(
    pair: tuple[str, timedelta],
) -> None:
    """Every `HH:MM` shorthand equals the ISO form built from the same numbers."""
    text, expected = pair
    total_minutes = expected.days * 24 * 60 + expected.seconds // 60
    hours, minutes = divmod(total_minutes, 60)
    iso = f"PT{hours}H{minutes}M" if hours else f"PT{minutes}M"
    assert _schedule.parse_duration(text) == _schedule.parse_duration(iso)


@given(st_schedule.positive_timedeltas())
def test_format_duration_matches_the_schema_pattern(td: timedelta) -> None:
    formatted = _schedule.format_duration(td)
    assert DURATION_PATTERN.match(formatted), formatted


@given(st_schedule.positive_timedeltas())
def test_timedelta_is_returned_unchanged_by_parse_duration(td: timedelta) -> None:
    assert _schedule.parse_duration(td) == td


#
# Start: round trips
#
@given(st_schedule.dates())
def test_parse_start_undoes_format_start_for_dates(value: date) -> None:
    assert _schedule.parse_start(_schedule.format_start(value)) == value


@given(st_schedule.naive_datetimes())
def test_parse_start_undoes_format_start_for_naive_datetimes(value: datetime) -> None:
    assert _schedule.parse_start(_schedule.format_start(value)) == value


@given(st_schedule.aware_datetimes())
def test_parse_start_undoes_format_start_for_aware_datetimes(value: datetime) -> None:
    assert _schedule.parse_start(_schedule.format_start(value)) == value


@given(st_schedule.starts())
def test_format_start_matches_the_schema_pattern(value: date | datetime) -> None:
    formatted = _schedule.format_start(value)
    assert START_PATTERN.match(formatted), formatted


@given(st_schedule.starts())
def test_date_or_datetime_is_returned_unchanged_by_parse_start(
    value: date | datetime,
) -> None:
    assert _schedule.parse_start(value) == value

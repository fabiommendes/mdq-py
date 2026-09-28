"""
`mdq._schedule`: parsing and canonicalizing an exam's `start` and
`duration` fields (docs/exam.md § "Duration and Start Time",
schema/exam.yaml).

Property tests use the strategies in `strategies.schedule`, built
directly from the spec's grammar and canonicalization rules rather than
from `mdq._schedule` itself. Table-driven tests pin the rejection list
and a handful of canonical examples the spec calls out by name.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pytest
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


#
# Duration: rejections
#
@pytest.mark.parametrize(
    "value",
    [
        "P1M",  # months have no fixed length
        "P1Y",  # years have no fixed length
        "P1Y2M",
        "",  # empty string
        "P",  # no components at all
        "PT",  # "T" with nothing after it
        "pt1h",  # lowercase ISO
        "0m",  # zero is not positive
        "00:00",  # zero is not positive
        "PT0S",  # zero is not positive
        "1:60",  # minutes must be 00-59
        "2 h",  # space between number and unit
        "1.5h",  # fractional shorthand component
        90,  # bare int: ambiguous unit
        90.0,  # bare float: ambiguous unit
        "garbage",
        "-PT1H",  # negative duration
        "P-1D",
    ],
)
def test_parse_duration_rejects(value: object) -> None:
    with pytest.raises(ValueError):
        _schedule.parse_duration(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("surface", "canonical"),
    [
        ("90m", "PT1H30M"),
        ("1:30", "PT1H30M"),
        ("01:30", "PT1H30M"),
        ("PT90M", "PT1H30M"),
        ("24h", "P1D"),
        ("P2W", "P14D"),
        ("1d 2h 30m", "P1DT2H30M"),
        ("PT1.5S", "PT1.5S"),
    ],
)
def test_parse_duration_canonical_examples(surface: str, canonical: str) -> None:
    assert _schedule.format_duration(_schedule.parse_duration(surface)) == canonical


#
# Start: rejections and canonical examples
#
@pytest.mark.parametrize(
    "value",
    [
        "10/03/2026",
        "2026-13-01",
        "tomorrow",
        "",
        "2026-03-10T",
        "2026-03-10T25:00:00",
    ],
)
def test_parse_start_rejects(value: str) -> None:
    with pytest.raises(ValueError):
        _schedule.parse_start(value)


@pytest.mark.parametrize(
    ("surface", "canonical"),
    [
        ("2026-03-10", "2026-03-10"),
        ("2026-03-10T09:00", "2026-03-10T09:00:00"),
        ("2026-03-10T09:00:00Z", "2026-03-10T09:00:00+00:00"),
    ],
)
def test_parse_start_canonical_examples(surface: str, canonical: str) -> None:
    assert _schedule.format_start(_schedule.parse_start(surface)) == canonical

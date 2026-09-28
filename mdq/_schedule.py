"""
Exam scheduling fields: `start` and `duration`.

Each field has a surface form, written by hand in the exam frontmatter,
and a canonical form, stored in the parsed document (see
schema/exam.yaml). `parse_*` reads any surface form into a Python value;
`format_*` writes that value back in canonical form.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

#: `P[nW][nD][T[nH][nM][n[.f]S]]`, uppercase only -- years and months are
#: not fixed-length, so they are not part of the grammar at all.
_ISO_DURATION_RE = re.compile(
    r"""
    ^P(?=[0-9]|T)
    (?:(?P<weeks>[0-9]+)W)?
    (?:(?P<days>[0-9]+)D)?
    (?:T(?=[0-9])
        (?:(?P<hours>[0-9]+)H)?
        (?:(?P<minutes>[0-9]+)M)?
        (?:(?P<seconds>[0-9]+(?:\.[0-9]+)?)S)?
    )?$
    """,
    re.VERBOSE,
)

#: `H:MM` or `HH:MM`, minutes restricted to 00-59.
_HH_MM_RE = re.compile(r"^([0-9]{1,2}):([0-5][0-9])$")

#: `Xd Yh Zm`, every component optional but at least one required. The
#: grammar only allows spaces between components, not arbitrary whitespace.
_XD_YH_ZM_RE = re.compile(
    r"""
    ^(?:(?P<days>[0-9]+)d)?[ ]*
    (?:(?P<hours>[0-9]+)h)?[ ]*
    (?:(?P<minutes>[0-9]+)m)?$
    """,
    re.VERBOSE,
)


def parse_duration(value: str | timedelta) -> timedelta:
    """
    Read an exam duration.

    Accepts an ISO 8601 duration restricted to fixed-length units
    (`P1W`, `P1DT2H30M`, `PT90M`, `PT1.5S`), `HH:MM` (`1:30`, `01:30`), or
    `Xd Yh Zm` with every component optional (`90m`, `2h 30m`, `1d2h`).
    A `timedelta` is returned unchanged.

    Raises:
        ValueError: If `value` matches none of the forms, uses years or
            months, or is not a positive duration.
    """
    if isinstance(value, timedelta):
        if value <= timedelta(0):
            raise ValueError(f"duration must be positive: {value!r}")
        return value
    if not isinstance(value, str):
        raise ValueError(f"duration must be a string or timedelta, got {value!r}")

    text = value.strip()
    if not text:
        raise ValueError("duration must not be empty")

    delta: timedelta | None = None

    if text.startswith("P"):
        match = _ISO_DURATION_RE.match(text)
        if match:
            seconds_group = match.group("seconds")
            # Split the fractional part by hand rather than going
            # through `float`, so microsecond precision survives exactly.
            if seconds_group and "." in seconds_group:
                whole, _, fraction = seconds_group.partition(".")
                seconds = int(whole)
                microseconds = int((fraction + "000000")[:6])
            else:
                seconds = int(seconds_group or 0)
                microseconds = 0
            delta = timedelta(
                weeks=int(match.group("weeks") or 0),
                days=int(match.group("days") or 0),
                hours=int(match.group("hours") or 0),
                minutes=int(match.group("minutes") or 0),
                seconds=seconds,
                microseconds=microseconds,
            )
    else:
        hh_mm = _HH_MM_RE.match(text)
        if hh_mm:
            delta = timedelta(hours=int(hh_mm.group(1)), minutes=int(hh_mm.group(2)))
        else:
            xdyhzm = _XD_YH_ZM_RE.match(text)
            if xdyhzm and any(xdyhzm.groups()):
                delta = timedelta(
                    days=int(xdyhzm.group("days") or 0),
                    hours=int(xdyhzm.group("hours") or 0),
                    minutes=int(xdyhzm.group("minutes") or 0),
                )

    if delta is None:
        raise ValueError(f"invalid duration: {value!r}")
    if delta <= timedelta(0):
        raise ValueError(f"duration must be positive: {value!r}")
    return delta


def format_duration(value: timedelta) -> str:
    """
    Write `value` as a canonical ISO 8601 duration.

    Components are carried into the largest unit that holds them and zero
    components are omitted: 90 minutes is `PT1H30M`, 24 hours is `P1D`,
    two weeks is `P14D`. Fractional seconds carry no trailing zeros.
    """
    # Work in exact integers (days/seconds/microseconds, as `timedelta`
    # itself normalizes them) rather than `total_seconds()`'s float, so
    # this stays exact at microsecond precision.
    total_seconds = value.days * 86400 + value.seconds
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    if value.microseconds:
        fraction = f"{value.microseconds:06d}".rstrip("0")
        seconds_str = f"{seconds}.{fraction}"
    else:
        seconds_str = str(seconds)

    date_part = f"{days}D" if days else ""

    time_components = []
    if hours:
        time_components.append(f"{hours}H")
    if minutes:
        time_components.append(f"{minutes}M")
    if seconds or value.microseconds:
        time_components.append(f"{seconds_str}S")
    time_part = f"T{''.join(time_components)}" if time_components else ""

    return f"P{date_part}{time_part}"


def parse_start(value: str | date | datetime) -> date | datetime:
    """
    Read an exam start time.

    A string holding only a date is read as a `date`, any other ISO 8601
    string as a `datetime`, keeping its UTC offset if it has one. `date`
    and `datetime` values, as produced by the YAML loader, are returned
    unchanged.

    Raises:
        ValueError: If `value` is not a valid ISO 8601 date or date-time.
    """
    if isinstance(value, datetime | date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"start must be a string, date, or datetime, got {value!r}")

    text = value.strip()
    if not text:
        raise ValueError("start must not be empty")

    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    try:
        # `datetime.fromisoformat` already reads a trailing `Z` as UTC
        # (`+00:00`), which is also `format_start`'s canonical spelling.
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid start date/time: {value!r}") from exc


def format_start(value: date | datetime) -> str:
    """
    Write `value` as a canonical ISO 8601 date or date-time
    (`2026-03-10`, `2026-03-10T09:00:00`, `2026-03-10T09:00:00-03:00`).
    """
    return value.isoformat()

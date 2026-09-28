"""
Hypothesis strategies for the exam `start`/`duration` fields (see
docs/exam.md § "Duration and Start Time", schema/exam.yaml, and
mdq/schedule.py).

Strategies here are built directly from the spec's grammar and
canonicalization rules -- not from `mdq.schedule` itself -- so tests that
use them exercise the contract, not whatever the implementation happens
to do. Most surface-form strategies return `(text, timedelta)` or
`(text, date | datetime)` pairs: the text a user could type, paired with
the value it must parse to.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from hypothesis import strategies as st

#
# Duration: raw timedeltas
#
def positive_timedeltas() -> st.SearchStrategy[timedelta]:
    """
    Any positive `timedelta`, built from timedelta's own normalized
    fields (whole days, whole seconds under a day, microseconds under a
    second) so every draw is representable in canonical ISO 8601 form.
    """
    return st.builds(
        timedelta,
        days=st.integers(min_value=0, max_value=3650),
        seconds=st.integers(min_value=0, max_value=86399),
        microseconds=st.integers(min_value=0, max_value=999_999),
    ).filter(lambda td: td > timedelta(0))


#
# Duration: canonical ISO 8601 strings
#
def canonical_durations() -> st.SearchStrategy[tuple[str, timedelta]]:
    """
    `(canonical_string, timedelta)` pairs built from the canonicalization
    rule in docs/exam.md: components carried into the largest unit that
    holds them (days/hours/minutes/seconds only -- weeks are always
    folded into days), zero components omitted, no trailing zeros on a
    fractional second.
    """

    def build(parts: tuple[int, int, int, int, int]) -> tuple[str, timedelta]:
        days, hours, minutes, seconds, micros = parts
        td = timedelta(
            days=days, hours=hours, minutes=minutes, seconds=seconds, microseconds=micros
        )

        seconds_part = ""
        if seconds or micros:
            if micros:
                frac = f"{micros:06d}".rstrip("0")
                seconds_part = f"{seconds}.{frac}S"
            else:
                seconds_part = f"{seconds}S"

        time_part = ""
        if hours or minutes or seconds_part:
            time_part = (
                "T"
                + (f"{hours}H" if hours else "")
                + (f"{minutes}M" if minutes else "")
                + seconds_part
            )

        days_part = f"{days}D" if days else ""
        return "P" + days_part + time_part, td

    components = st.tuples(
        st.integers(min_value=0, max_value=999),  # days
        st.integers(min_value=0, max_value=23),  # hours
        st.integers(min_value=0, max_value=59),  # minutes
        st.integers(min_value=0, max_value=59),  # seconds
        st.integers(min_value=0, max_value=999_999),  # microseconds
    ).filter(any)

    return components.map(build)


#
# Duration: surface shorthand forms
#
def xd_yh_zm_strings() -> st.SearchStrategy[tuple[str, timedelta]]:
    """
    `Xd Yh Zm` strings with each component optional (but at least one
    present, and the total positive), joined by varied spacing --
    nothing, a single space, or a run of spaces -- matching the
    `xd_yh_zm` grammar rule in docs/exam.md.
    """

    def build(
        days: int | None,
        hours: int | None,
        minutes: int | None,
        sep: str,
    ) -> tuple[str, timedelta]:
        parts = []
        if days is not None:
            parts.append(f"{days}d")
        if hours is not None:
            parts.append(f"{hours}h")
        if minutes is not None:
            parts.append(f"{minutes}m")
        td = timedelta(days=days or 0, hours=hours or 0, minutes=minutes or 0)
        return sep.join(parts), td

    component = st.none() | st.integers(min_value=0, max_value=99)
    return (
        st.tuples(component, component, component, st.sampled_from(["", " ", "  "]))
        .filter(lambda t: any(x is not None for x in t[:3]))
        .filter(lambda t: (t[0] or 0) + (t[1] or 0) + (t[2] or 0) > 0)
        .map(lambda t: build(*t))
    )


def hh_mm_strings() -> st.SearchStrategy[tuple[str, timedelta]]:
    """
    `H:MM` or `HH:MM` strings (hours zero-padded or not, minutes always
    two digits 00-59), with a positive total, matching the `hh_mm`
    grammar rule.
    """

    def build(hours: int, minutes: int, pad: bool) -> tuple[str, timedelta]:
        hour_text = f"{hours:02d}" if pad else str(hours)
        return f"{hour_text}:{minutes:02d}", timedelta(hours=hours, minutes=minutes)

    return (
        st.tuples(
            st.integers(min_value=0, max_value=99),
            st.integers(min_value=0, max_value=59),
            st.booleans(),
        )
        .filter(lambda t: t[0] or t[1])
        .map(lambda t: build(*t))
    )


def iso_duration_strings() -> st.SearchStrategy[tuple[str, timedelta]]:
    """
    ISO 8601 duration strings restricted to fixed-length units
    (W/D/H/M/S, fractional seconds allowed), covering combinations a
    canonical string never produces on its own -- e.g. weeks alongside
    days -- but that the `iso_duration` grammar rule still accepts.
    """

    def build(
        parts: tuple[int, int, int, int, int, int]
    ) -> tuple[str, timedelta]:
        weeks, days, hours, minutes, seconds, micros = parts
        td = timedelta(
            weeks=weeks,
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            microseconds=micros,
        )

        seconds_part = ""
        if seconds or micros:
            if micros:
                frac = f"{micros:06d}".rstrip("0")
                seconds_part = f"{seconds}.{frac}S"
            else:
                seconds_part = f"{seconds}S"

        time_part = ""
        if hours or minutes or seconds_part:
            time_part = (
                "T"
                + (f"{hours}H" if hours else "")
                + (f"{minutes}M" if minutes else "")
                + seconds_part
            )

        date_part = (f"{weeks}W" if weeks else "") + (f"{days}D" if days else "")
        return "P" + date_part + time_part, td

    components = st.tuples(
        st.integers(min_value=0, max_value=20),  # weeks
        st.integers(min_value=0, max_value=20),  # days
        st.integers(min_value=0, max_value=23),  # hours
        st.integers(min_value=0, max_value=59),  # minutes
        st.integers(min_value=0, max_value=59),  # seconds
        st.integers(min_value=0, max_value=999_999),  # microseconds
    ).filter(any)

    return components.map(build)


def shorthand_duration_strings() -> st.SearchStrategy[tuple[str, timedelta]]:
    """Any of the three surface duration forms, paired with the timedelta it denotes."""
    return xd_yh_zm_strings() | hh_mm_strings() | iso_duration_strings()


#
# Start: dates and datetimes
#
def dates() -> st.SearchStrategy[date]:
    """Return a strategy for arbitrary `date`s."""
    return st.dates()


def naive_datetimes() -> st.SearchStrategy[datetime]:
    """Return a strategy for `datetime`s with no UTC offset (local time)."""
    return st.datetimes()


def utc_offsets() -> st.SearchStrategy[timedelta]:
    """Return a strategy for UTC offsets a `datetime.timezone` can hold."""
    return st.builds(
        lambda sign, hours, minutes: sign * timedelta(hours=hours, minutes=minutes),
        st.sampled_from([1, -1]),
        st.integers(min_value=0, max_value=23),
        st.integers(min_value=0, max_value=59),
    ).filter(lambda offset: -timedelta(hours=24) < offset < timedelta(hours=24))


def aware_datetimes() -> st.SearchStrategy[datetime]:
    """Return a strategy for `datetime`s carrying a fixed UTC offset."""
    return st.builds(
        lambda dt, offset: dt.replace(tzinfo=timezone(offset)),
        st.datetimes(),
        utc_offsets(),
    )


def starts() -> st.SearchStrategy[date | datetime]:
    """Return a strategy for any valid exam `start` value: a date, or a naive or offset-aware datetime."""
    return dates() | naive_datetimes() | aware_datetimes()

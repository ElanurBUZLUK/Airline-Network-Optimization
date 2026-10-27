"""Date-aware minute arithmetic for schedule-local timestamps.

The integer timeline intentionally avoids comparing HH:MM values without dates.
Timezone conversion, when needed by the source contract, must happen before this layer.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

MINUTES_PER_DAY = 24 * 60


def to_absolute_minutes(day: date, clock_time: time) -> int:
    """Convert a schedule-local date and clock time to an integer minute timeline."""
    if clock_time.tzinfo is not None:
        raise ValueError("time must be timezone-naive schedule-local time")
    if clock_time.second or clock_time.microsecond:
        raise ValueError("schedule times must have minute precision")
    return day.toordinal() * MINUTES_PER_DAY + clock_time.hour * 60 + clock_time.minute


def datetime_to_absolute_minutes(value: datetime) -> int:
    """Convert a timezone-naive schedule-local datetime to absolute minutes."""
    if value.tzinfo is not None:
        raise ValueError("datetime must be timezone-naive schedule-local time")
    if value.second or value.microsecond:
        raise ValueError("schedule times must have minute precision")
    return to_absolute_minutes(value.date(), value.time())


def from_absolute_minutes(value: int) -> datetime:
    """Convert an integer minute timeline value back to a schedule-local datetime."""
    ordinal, minute_of_day = divmod(value, MINUTES_PER_DAY)
    day = date.fromordinal(ordinal)
    return datetime.combine(day, time()) + timedelta(minutes=minute_of_day)


def add_duration(departure_abs_min: int, duration_min: int) -> int:
    """Return arrival time on the same absolute timeline."""
    if duration_min < 0:
        raise ValueError("flight duration must be non-negative")
    return departure_abs_min + duration_min

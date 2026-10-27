from datetime import date, datetime, time

import pytest

from airline_optimizer.domain.time_model import (
    add_duration,
    datetime_to_absolute_minutes,
    from_absolute_minutes,
    to_absolute_minutes,
)


def test_absolute_minutes_round_trip_across_midnight():
    start = datetime(2026, 10, 24, 23, 50)
    absolute = datetime_to_absolute_minutes(start)
    assert from_absolute_minutes(absolute + 25) == datetime(2026, 10, 25, 0, 15)


def test_date_is_part_of_absolute_time():
    before = to_absolute_minutes(date(2026, 10, 24), time(23, 55))
    after = to_absolute_minutes(date(2026, 10, 25), time(0, 5))
    assert after - before == 10


def test_rejects_seconds_and_timezone_aware_values():
    with pytest.raises(ValueError):
        to_absolute_minutes(date(2026, 10, 24), time(12, 0, 1))
    with pytest.raises(ValueError):
        datetime_to_absolute_minutes(datetime.fromisoformat("2026-10-24T12:00:00+03:00"))


def test_duration_cannot_be_negative():
    with pytest.raises(ValueError):
        add_duration(100, -1)

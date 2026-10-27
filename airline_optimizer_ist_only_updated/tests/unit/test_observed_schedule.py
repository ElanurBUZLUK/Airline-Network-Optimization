from datetime import datetime, time, timedelta

from airline_optimizer.data.observed_schedule import _duration_minutes


def test_duration_parser_supports_excel_time_values():
    assert _duration_minutes(time(2, 35)) == 155
    assert _duration_minutes(datetime(1899, 12, 30, 4, 15)) == 255
    assert _duration_minutes(timedelta(hours=6, minutes=10)) == 370
    assert _duration_minutes("30.12.1899 07:35:00") == 455


def test_duration_parser_rejects_missing_or_invalid_values():
    assert _duration_minutes(None) is None
    assert _duration_minutes("not-a-duration") is None

import pytest

from airline_optimizer.connections.compatibility import evaluate_connection


@pytest.mark.parametrize(("gap", "expected"), [(44, False), (45, True), (300, True), (301, False)])
def test_connection_gap_bounds_are_inclusive(gap, expected):
    result = evaluate_connection(
        "inbound", 1000, 120, "outbound", 1000 + 120 + gap
    )
    assert result.gap_minutes == gap
    assert result.feasible is expected


def test_arrival_uses_inbound_duration_exactly_once():
    result = evaluate_connection("in", 1000, 80, "out", 1000 + 80 + 60)
    assert result.inbound_arrival_abs_min == 1080
    assert result.gap_minutes == 60


def test_rejects_same_flight_connection():
    with pytest.raises(ValueError):
        evaluate_connection("same", 100, 30, "same", 200)

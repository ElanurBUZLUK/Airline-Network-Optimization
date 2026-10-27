from datetime import date

import pytest

from airline_optimizer.domain.flights import FlightInstance, TimeOption
from airline_optimizer.domain.solutions import ScheduleState
from airline_optimizer.scoring.research_metrics import from_schedule_metrics
from airline_optimizer.validation.full_recompute import evaluate_schedule_fully


def flight(fid, origin, dest, departure, duration=60):
    return FlightInstance(fid, fid, date(2026, 10, 24), origin, dest, departure, duration)


def option(fid, departure, method="test"):
    return TimeOption(f"{fid}@{departure}", fid, departure, method)


def make_state():
    flights = [
        flight("A", "ADB", "IST", 8 * 60, 90),
        flight("B", "IST", "LHR", 10 * 60, 240),
        flight("C", "IST", "ESB", 11 * 60, 60),
        flight("D", "LHR", "JFK", 15 * 60, 420),
    ]
    options = {
        "A": [option("A", 8 * 60), option("A", 9 * 60)],
        "B": [option("B", 10 * 60), option("B", 12 * 60)],
        "C": [option("C", 11 * 60), option("C", 14 * 60)],
        "D": [option("D", 15 * 60), option("D", 17 * 60)],
    }
    return flights, options, ScheduleState(flights, options)


def test_state_metrics_match_full_evaluation_initially():
    flights, _, state = make_state()
    state.assert_matches_full_recompute()
    full = evaluate_schedule_fully(flights, state.graph.departures)
    assert state.metrics.connection_count == full.connection_count
    assert dict(state.metrics.od_connection_counts) == dict(full.od_connection_counts)


def test_batch_update_updates_od_counts_incrementally_and_matches_full():
    _, _, state = make_state()
    before_od = dict(state.metrics.od_connection_counts)
    state.update_selection({"A": "A@540", "B": "B@720", "C": "C@840"})
    state.assert_matches_full_recompute()
    assert dict(state.metrics.od_connection_counts) != before_od


def test_invalid_batch_does_not_partially_mutate_state():
    _, _, state = make_state()
    before_departures = dict(state.graph.departures)
    before_selection = dict(state.selected_option_by_flight)
    with pytest.raises(ValueError):
        state.update_selection({"A": "A@540", "B": "B@999"})
    assert state.graph.departures == before_departures
    assert state.selected_option_by_flight == before_selection


def test_unknown_flight_is_rejected():
    _, _, state = make_state()
    with pytest.raises(ValueError):
        state.update_selection({"missing": "x"})


def test_research_metrics_are_not_official_score():
    _, _, state = make_state()
    metrics = from_schedule_metrics(state.metrics)
    assert metrics.total_valid_connections == state.metrics.connection_count
    assert metrics.markets_with_connections == sum(v > 0 for v in state.metrics.od_connection_counts.values())


def test_same_edge_with_changed_gap_does_not_change_od_count():
    flights = [flight("A", "ADB", "IST", 480, 90), flight("B", "IST", "LHR", 615, 240)]
    options = {"A": [option("A", 480), option("A", 475)], "B": [option("B", 615)]}
    state = ScheduleState(flights, options)
    count = dict(state.metrics.od_connection_counts)
    state.update_selection({"A": "A@475"})
    state.assert_matches_full_recompute()
    assert dict(state.metrics.od_connection_counts) == count

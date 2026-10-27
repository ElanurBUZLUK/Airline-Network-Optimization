from datetime import date

from airline_optimizer.domain.flights import FlightInstance, TimeOption
from airline_optimizer.search import SearchConfig, run_search


def flight(fid, origin, destination, departure, duration):
    return FlightInstance(fid, fid, date(2026, 10, 24), origin, destination, departure, duration)


def opt(fid, departure):
    return TimeOption(f"{fid}@{departure}", fid, departure, "test")


def sample_problem():
    flights = [
        flight("in", "ADB", "IST", 480, 90),
        flight("out", "IST", "LHR", 700, 240),
        flight("other", "IST", "ESB", 900, 60),
    ]
    options = {
        "in": [opt("in", 480), opt("in", 540), opt("in", 600)],
        "out": [opt("out", 620), opt("out", 700), opt("out", 780)],
        "other": [opt("other", 660), opt("other", 750), opt("other", 900)],
    }
    return flights, options


def test_search_is_reproducible_and_returns_full_validated_best():
    flights, options = sample_problem()
    cfg = SearchConfig(iterations=30, seed=17, destroy_fraction=0.67)
    a = run_search(flights, options, config=cfg)
    b = run_search(flights, options, config=cfg)
    assert a.best_selection == b.best_selection
    assert a.best_metrics.total_valid_connections == b.best_metrics.total_valid_connections
    assert len(a.history) == 30
    assert a.best_metrics.total_valid_connections >= a.initial_metrics.total_valid_connections


def test_search_handles_zero_iterations():
    flights, options = sample_problem()
    result = run_search(flights, options, config=SearchConfig(iterations=0))
    assert result.history == ()
    assert result.best_selection


def test_search_reports_research_metrics_not_official_score():
    flights, options = sample_problem()
    result = run_search(flights, options, config=SearchConfig(iterations=3))
    assert hasattr(result.best_metrics, "total_valid_connections")
    assert not hasattr(result.best_metrics, "official_score")


def test_search_preserves_incremental_state_after_rejected_moves():
    flights, options = sample_problem()
    cfg = SearchConfig(
        iterations=50, seed=29, destroy_fraction=0.67,
        initial_temperature=0.0, cooling_rate=1.0,
    )
    result = run_search(flights, options, config=cfg)
    assert result.best_metrics.total_valid_connections >= result.initial_metrics.total_valid_connections
    assert len(result.history) == 50


def test_preview_option_objective_matches_mutated_state_objective():
    from airline_optimizer.domain.solutions import ScheduleState

    flights, options = sample_problem()
    state = ScheduleState(flights, options)
    for flight_id, flight_options in options.items():
        for option in flight_options:
            preview = state.preview_option_objective(flight_id, option.option_id)
            previous = state.selected_option_by_flight[flight_id]
            state.update_selection({flight_id: option.option_id})
            actual = float(state.metrics.connection_count) + 0.001 * len(state.metrics.od_connection_counts)
            assert preview == actual
            state.update_selection({flight_id: previous})
            state.assert_matches_full_recompute()

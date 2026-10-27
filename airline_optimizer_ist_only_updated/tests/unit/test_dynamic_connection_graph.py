from datetime import date

import pytest

from airline_optimizer.connections.dynamic_graph import DynamicConnectionGraph
from airline_optimizer.domain.flights import FlightInstance


def f(fid, origin, destination, departure, duration=60):
    return FlightInstance(fid, fid, date(2026, 1, 1), origin, destination, departure, duration)


def test_graph_counts_only_connections_through_istanbul():
    flights = [
        f("A", "ADB", "IST", 1000, 90),
        f("B", "IST", "LHR", 1200),
        f("C", "ESB", "LHR", 1200),
        f("D", "LHR", "AMS", 1300),
        f("E", "LHR", "IST", 1000, 60),
    ]
    graph = DynamicConnectionGraph(flights)
    assert [(e.inbound_flight_id, e.outbound_flight_id, e.gap_minutes) for e in graph.edges] == [("A", "B", 110)]


def test_update_adds_and_removes_edges_incrementally():
    flights = [f("A", "ADB", "IST", 1000, 90), f("B", "IST", "LHR", 1200)]
    graph = DynamicConnectionGraph(flights)
    assert len(graph.edges) == 1
    graph.update_departures({"B": 1400})
    assert graph.edges == ()
    graph.update_departures({"B": 1180})
    assert len(graph.edges) == 1
    graph.assert_matches_full_recompute()


def test_update_rejects_unknown_flight():
    graph = DynamicConnectionGraph([f("A", "ADB", "IST", 1000)])
    with pytest.raises(ValueError):
        graph.update_departures({"NOPE": 1100})


def test_graph_rejects_duplicate_flight_ids():
    with pytest.raises(ValueError):
        DynamicConnectionGraph([f("A", "ADB", "IST", 1000), f("A", "IST", "LHR", 1100)])


def test_incremental_updates_match_full_recomputation_across_changes():
    flights = [f("A", "ADB", "IST", 1000, 90), f("B", "IST", "LHR", 1200),
               f("C", "IST", "FRA", 1400), f("D", "FRA", "AMS", 1600)]
    graph = DynamicConnectionGraph(flights)
    for changes in ({"B": 1390}, {"A": 1100, "C": 1450}, {"D": 1800}, {"A": 1000, "B": 1180}):
        graph.update_departures(changes)
        graph.assert_matches_full_recompute()


def test_graph_excludes_return_to_origin_itinerary_as_od_market():
    flights = [f("A", "AGP", "IST", 1000, 90), f("B", "IST", "AGP", 1180, 60)]
    graph = DynamicConnectionGraph(flights)
    assert graph.edges == ()


def test_delta_update_returns_only_added_and_removed_edges():
    flights = [f("A", "ADB", "IST", 1000, 90), f("B", "IST", "LHR", 1200)]
    graph = DynamicConnectionGraph(flights)
    removed, added = graph.update_departures_with_delta({"B": 1400})
    assert [(e.inbound_flight_id, e.outbound_flight_id) for e in removed] == [("A", "B")]
    assert added == ()
    removed, added = graph.update_departures_with_delta({"B": 1180})
    assert removed == ()
    assert [(e.inbound_flight_id, e.outbound_flight_id) for e in added] == [("A", "B")]
    graph.assert_matches_full_recompute()


def test_delta_ignores_gap_change_when_connection_remains_feasible():
    flights = [f("A", "ADB", "IST", 1000, 90), f("B", "IST", "LHR", 1200)]
    graph = DynamicConnectionGraph(flights)
    removed, added = graph.update_departures_with_delta({"B": 1210})
    assert removed == ()
    assert added == ()
    assert graph.edges[0].gap_minutes == 120
